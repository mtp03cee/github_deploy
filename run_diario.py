"""
run_diario.py
-------------
Pipeline diario do relatorio de abertura - usando API key do Metabase.

Le configuracao via variaveis de ambiente (preferencial) ou config.json:
  - METABASE_API_KEY       : token de API do Metabase
  - METABASE_BASE_URL      : URL base, ex: https://metabase.selvia.app
  - METABASE_DASHBOARD_ID  : ID do dashboard, ex: 111
  - SLACK_WEBHOOK_URL      : URL do Workflow Builder trigger

Faz:
  1. Lista cards do dashboard via /api/dashboard/{id}
  2. Identifica os 4 cards por nome
  3. Roda cada card via POST /api/card/{id}/query/csv
  4. Calcula as metricas
  5. Salva snapshot agregado (historico.json)
  6. Posta no Slack
  7. Regenera dashboard HTML cumulativo
"""

import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, date

import pandas as pd
import requests


HISTORY_PATH = "historico.json"
TEMPLATE_PATH = "dashboard_template.html"
DASHBOARD_HTML_PATH = "dashboard_cumulativo.html"

ETAPAS = {
    "Espera": list(range(0, 2)),
    "CNPJ":   list(range(2, 13)),
    "IM":     list(range(13, 17)),
    "CRM":    list(range(17, 22)),
}

CARD_PATTERNS = {
    "tabela_completa": [r"tabela.*completa", r"datas.*inicio", r"user.*data"],
    "sem_atualizacao": [r"sem.*atualizacao", r"ultima.*atualiz"],
    "em_atraso":       [r"em.*atraso", r"atrasados", r"atraso.*abertura"],
    "necessitam_acao": [r"necessit.*acao", r"acao.*selvia", r"requer.*acao"],
    "urgentes":        [r"urgentes?", r"prioritarios?"],
}


def _norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def load_config():
    cfg = {}
    if os.path.exists("config.json"):
        with open("config.json", encoding="utf-8") as f:
            cfg = json.load(f)
    for key in ["METABASE_API_KEY", "METABASE_BASE_URL", "METABASE_DASHBOARD_ID",
                "SLACK_WEBHOOK_URL", "METABASE_TABLE_ID"]:
        if os.environ.get(key):
            cfg[key.lower()] = os.environ[key]
    required = ["metabase_api_key", "metabase_base_url", "metabase_dashboard_id", "slack_webhook_url"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"ERRO: faltando: {missing}")
        sys.exit(1)
    cfg["metabase_dashboard_id"] = int(cfg["metabase_dashboard_id"])
    return cfg


def metabase_headers(cfg):
    return {"X-API-Key": cfg["metabase_api_key"], "Content-Type": "application/json"}


def fetch_dashboard(cfg):
    url = f"{cfg['metabase_base_url']}/api/dashboard/{cfg['metabase_dashboard_id']}"
    r = requests.get(url, headers=metabase_headers(cfg), timeout=30)
    r.raise_for_status()
    return r.json()


def discover_cards(dashboard):
    cards = dashboard.get("dashcards") or dashboard.get("ordered_cards") or []
    found = {}
    leftovers = []
    for c in cards:
        card = c.get("card") or {}
        card_id = card.get("id") or c.get("card_id")
        name = card.get("name") or ""
        if not name or not card_id:
            continue
        norm_name = _norm(name)
        matched = None
        for chave, patterns in CARD_PATTERNS.items():
            if chave in found:
                continue
            for pat in patterns:
                if re.search(pat, norm_name):
                    matched = chave
                    break
            if matched:
                break
        if matched:
            found[matched] = (card_id, name)
        else:
            leftovers.append((card_id, name))
    return found, leftovers


def fetch_card_csv(cfg, card_id):
    url = f"{cfg['metabase_base_url']}/api/card/{card_id}/query/csv"
    r = requests.post(url, headers=metabase_headers(cfg), timeout=120)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def classify(etapa):
    if pd.isna(etapa):
        return None
    e = int(etapa)
    for cat, faixa in ETAPAS.items():
        if e in faixa:
            return cat
    return "OUT"


def find_col(df, candidatos):
    cols_norm = {_norm(c): c for c in df.columns}
    for cand in candidatos:
        cand_n = _norm(cand)
        for low, orig in cols_norm.items():
            if cand_n in low:
                return orig
    return None


def compute_metrics(dfs):
    completa = dfs["tabela_completa"].copy()
    sem = dfs["sem_atualizacao"].copy()
    atraso = dfs["em_atraso"].copy()
    necessita = dfs["necessitam_acao"].copy()

    col_etapa = find_col(completa, ["etapa_atual_numero", "etapa atual numero", "etapa"])
    col_fase = find_col(completa, ["fase_nome", "dicionario de fases"])
    completa["cat"] = completa[col_etapa].apply(classify)
    completa_in = completa[completa["cat"].isin(["Espera", "CNPJ", "IM", "CRM"])]

    fase_to_cat = {}
    if col_fase:
        for _, r in completa.iterrows():
            fn = r.get(col_fase)
            if pd.notna(fn) and r.get("cat") in ("Espera", "CNPJ", "IM", "CRM"):
                fase_to_cat[fn] = r["cat"]

    totals = {c: int((completa_in["cat"] == c).sum()) for c in ["Espera", "CNPJ", "IM", "CRM"]}

    col_fase_sem = find_col(sem, ["fase_nome", "dicionario de fases"])
    col_dias = find_col(sem, ["dias_desde_ultima", "desde a ultima"])
    if col_fase_sem:
        sem["cat"] = sem[col_fase_sem].map(fase_to_cat)
    if col_dias:
        sem = sem[sem[col_dias] > 5]
    sem_counts = {c: int((sem["cat"] == c).sum()) for c in ["Espera", "CNPJ", "IM", "CRM"]}

    col_etapa_atr = find_col(atraso, ["etapa_atual_numero", "etapa atual"])
    if col_etapa_atr:
        atraso["cat"] = atraso[col_etapa_atr].apply(classify)
    else:
        col_fase_atr = find_col(atraso, ["fase_nome", "dicionario de fases"])
        if col_fase_atr:
            atraso["cat"] = atraso[col_fase_atr].map(fase_to_cat)
    atrasados = {c: int((atraso["cat"] == c).sum()) for c in ["CNPJ", "IM"]}

    col_fase_nec = find_col(necessita, ["fase_nome", "dicionario de fases"])
    if col_fase_nec:
        necessita["cat"] = necessita[col_fase_nec].map(fase_to_cat)
    necessitam = {c: int((necessita["cat"] == c).sum()) for c in ["CNPJ", "IM"]}

    return {
        "data": date.today().strftime("%Y-%m-%d"),
        "totals": totals,
        "sem_atualizacao": sem_counts,
        "atrasados": atrasados,
        "necessitam_acao": necessitam,
    }


def pct(n, d):
    if not d:
        return "0,0%"
    return ("%.1f" % (n / d * 100)).replace(".", ",") + "%"


def format_message(snap):
    t = snap["totals"]; sa = snap["sem_atualizacao"]
    at = snap["atrasados"]; na = snap["necessitam_acao"]
    total_and = t["CNPJ"] + t["IM"]
    data_br = datetime.strptime(snap["data"], "%Y-%m-%d").strftime("%d/%m/%Y")
    L = [f"*Relatório de Abertura — {data_br}*", "",
         "*Visão geral dos casos em abertura*",
         f"Cards em andamento — Total: {total_and}",
         f"  • CNPJ: {t['CNPJ']} ({pct(t['CNPJ'], total_and)})",
         f"  • IM: {t['IM']} ({pct(t['IM'], total_and)})",
         f"Cards em espera — Total: {t['Espera']}",
         f"Cards CRM — Total: {t['CRM']}", "",
         "*Clientes há muito tempo sem atualização (5 dias)*",
         f"  • Em espera: {sa['Espera']} de {t['Espera']} cards ({pct(sa['Espera'], t['Espera'])})",
         f"  • CNPJ: {sa['CNPJ']} de {t['CNPJ']} cards ({pct(sa['CNPJ'], t['CNPJ'])})",
         f"  • IM: {sa['IM']} de {t['IM']} cards ({pct(sa['IM'], t['IM'])})",
         f"  • CRM: {sa['CRM']} de {t['CRM']} cards ({pct(sa['CRM'], t['CRM'])})", "",
         "*Clientes atrasados*",
         f"  • CNPJ: {at['CNPJ']} de {t['CNPJ']} cards ({pct(at['CNPJ'], t['CNPJ'])}) estão atrasados",
         f"  • IM: {at['IM']} de {t['IM']} cards ({pct(at['IM'], t['IM'])}) estão atrasados", "",
         "*Necessitam ação*",
         f"  • CNPJ: {na['CNPJ']} de {t['CNPJ']} cards ({pct(na['CNPJ'], t['CNPJ'])}) necessitam ação",
         f"  • IM: {na['IM']} de {t['IM']} cards ({pct(na['IM'], t['IM'])}) necessitam ação"]
    return "\n".join(L)


def append_history(snapshot, path):
    history = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            history = json.load(f)
    history = [h for h in history if h.get("data") != snapshot["data"]]
    history.append(snapshot)
    history.sort(key=lambda h: h["data"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    return history


def post_slack_workflow(webhook_url, text):
    r = requests.post(webhook_url, json={"message": text}, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"Slack respondeu {r.status_code}: {r.text[:200]}")


def regenerate_dashboard(history, template_path, output_path):
    if not os.path.exists(template_path):
        print(f"  AVISO: {template_path} nao encontrado, pulando dashboard.")
        return
    with open(template_path, encoding="utf-8") as f:
        tpl = f.read()
    html = tpl.replace(
        "__HISTORY_PLACEHOLDER__", json.dumps(history, ensure_ascii=False)
    ).replace("__COHORT_PLACEHOLDER__", "[]")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def historico_to_csv(history):
    rows = []
    for s in history:
        t  = s["totals"]
        sa = s["sem_atualizacao"]
        at = s["atrasados"]
        na = s["necessitam_acao"]
        rows.append({
            "data":                   s["data"],
            "espera_total":           t.get("Espera") or 0,
            "cnpj_total":             t.get("CNPJ")   or 0,
            "im_total":               t.get("IM")     or 0,
            "crm_total":              t.get("CRM")    or 0,
            "espera_sem_atualizacao": sa.get("Espera") or 0,
            "cnpj_sem_atualizacao":   sa.get("CNPJ")   or 0,
            "im_sem_atualizacao":     sa.get("IM")     or 0,
            "crm_sem_atualizacao":    sa.get("CRM")    or 0,
            "cnpj_atrasados":         at.get("CNPJ") or 0,
            "im_atrasados":           at.get("IM")   or 0,
            "cnpj_necessitam_acao":   na.get("CNPJ") or 0,
            "im_necessitam_acao":     na.get("IM")   or 0,
        })
    buf = io.StringIO()
    if rows:
        import csv as _csv
        w = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def push_historico_to_metabase(history, cfg):
    table_id = cfg.get("metabase_table_id")
    if not table_id:
        print("  AVISO: METABASE_TABLE_ID não configurado — pulando push para Metabase.")
        return
    csv_data = historico_to_csv(history)
    h = {"X-API-Key": cfg["metabase_api_key"]}
    r = requests.post(
        f"{cfg['metabase_base_url']}/api/uploads/csv",
        headers=h,
        files={"file": ("historico_aberturas.csv", csv_data.encode("utf-8"), "text/csv")},
        data={"table_id": int(table_id)},
    )
    if not r.ok:
        print(f"  AVISO: push Metabase falhou {r.status_code}: {r.text[:200]}")
    else:
        print(f"  Metabase tabela {table_id} atualizada.")


def main():
    cfg = load_config()
    print(f"[{datetime.now().isoformat()}] Pipeline iniciado")

    print("  Buscando dashboard...")
    dashboard = fetch_dashboard(cfg)
    found, leftovers = discover_cards(dashboard)
    print(f"  Cards identificados: {len(found)}")
    for chave, (cid, name) in found.items():
        print(f"    - {chave}: '{name}' (card_id={cid})")

    obrigatorios = {"tabela_completa", "sem_atualizacao", "em_atraso", "necessitam_acao"}
    faltando = obrigatorios - set(found.keys())
    if faltando:
        print(f"\nERRO: cards faltando: {faltando}")
        sys.exit(1)

    dfs = {}
    for chave, (card_id, name) in found.items():
        print(f"  Baixando '{chave}' (card {card_id})...")
        dfs[chave] = fetch_card_csv(cfg, card_id)

    snapshot = compute_metrics(dfs)
    print(f"  Metricas: {json.dumps(snapshot, ensure_ascii=False)}")

    history = append_history(snapshot, HISTORY_PATH)
    print(f"  Historico: {len(history)} snapshots.")

    msg = format_message(snapshot)
    print("  Enviando Slack...")
    post_slack_workflow(cfg["slack_webhook_url"], msg)
    print("  Enviado.")

    regenerate_dashboard(history, TEMPLATE_PATH, DASHBOARD_HTML_PATH)
    print(f"  Dashboard atualizado: {DASHBOARD_HTML_PATH}")

    push_historico_to_metabase(history, cfg)

    print(f"[{datetime.now().isoformat()}] Concluido.")


if __name__ == "__main__":
    main()
