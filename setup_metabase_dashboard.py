"""
setup_metabase_dashboard.py
---------------------------
Cria o dashboard de texto no Metabase em:
  [Atualizado] CS-Clients / Aberturas/Life Cycle

Permissões necessárias: criar dashboards e text cards (sem acesso ao banco).

Ao final imprime METABASE_TEXT_DASHBOARD_ID — adicione como secret no GitHub.
A partir daí, run_diario.py atualiza os cards automaticamente todo dia.

Variáveis de ambiente:
  METABASE_API_KEY, METABASE_BASE_URL
"""

import json
import os
import sys

import requests

COLLECTION_ID  = 99   # Aberturas/Life Cycle
DASHBOARD_NAME = "Life cycle — Histórico Cumulativo"
HISTORY_PATH   = "historico.json"
PAGES_URL_ENV  = "PAGES_URL"


def load_cfg():
    cfg = {}
    if os.path.exists("config.json"):
        with open("config.json", encoding="utf-8") as f:
            cfg = json.load(f)
    for k in ["METABASE_API_KEY", "METABASE_BASE_URL", "PAGES_URL",
              "METABASE_TEXT_DASHBOARD_ID"]:
        if os.environ.get(k):
            cfg[k.lower()] = os.environ[k]
    missing = [k for k in ["metabase_api_key", "metabase_base_url"] if not cfg.get(k)]
    if missing:
        print(f"ERRO: variáveis faltando: {missing}")
        sys.exit(1)
    return cfg


def hdr(cfg):
    return {"X-API-Key": cfg["metabase_api_key"], "Content-Type": "application/json"}


def find_or_create_dashboard(cfg):
    existing_id = cfg.get("metabase_text_dashboard_id")
    if existing_id:
        print(f"  Usando dashboard existente: id={existing_id}")
        return int(existing_id)

    r = requests.get(
        f"{cfg['metabase_base_url']}/api/collection/{COLLECTION_ID}/items?models=dashboard",
        headers=hdr(cfg), timeout=10,
    )
    if r.ok:
        for item in r.json().get("data", []):
            if item.get("name") == DASHBOARD_NAME:
                print(f"  Dashboard encontrado: id={item['id']}")
                return item["id"]

    r = requests.post(
        f"{cfg['metabase_base_url']}/api/dashboard",
        headers=hdr(cfg),
        json={"name": DASHBOARD_NAME, "collection_id": COLLECTION_ID},
    )
    r.raise_for_status()
    dash_id = r.json()["id"]
    print(f"  Dashboard criado: id={dash_id}")
    return dash_id


# ── Builders de Markdown ──────────────────────────────────────────────────────

def _fmt_date(d):
    try:
        from datetime import datetime
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return d


def build_header(history, pages_url):
    latest = history[-1] if history else {}
    t  = latest.get("totals", {})
    at = latest.get("atrasados", {})
    na = latest.get("necessitam_acao", {})
    sa = latest.get("sem_atualizacao", {})
    data = _fmt_date(latest.get("data", "—"))
    link = f"[Ver dashboard com gráficos →]({pages_url})" if pages_url else ""

    return f"""# Life Cycle — Histórico Cumulativo
{link}

**Último snapshot: {data}** · {len(history)} dias registrados

| | Espera | CNPJ | IM | CRM |
|---|:---:|:---:|:---:|:---:|
| **Total** | {t.get("Espera", 0)} | {t.get("CNPJ", 0)} | {t.get("IM", 0)} | {t.get("CRM", 0)} |
| **Sem atualização** | {sa.get("Espera") or 0} | {sa.get("CNPJ") or 0} | {sa.get("IM") or 0} | {sa.get("CRM") or 0} |
| **Atrasados** | — | {at.get("CNPJ", 0)} | {at.get("IM", 0)} | — |
| **Necessitam ação** | — | {na.get("CNPJ", 0)} | {na.get("IM", 0)} | — |"""


def build_totals_table(history):
    rows = "\n".join(
        f"| {_fmt_date(s['data'])} "
        f"| {s['totals'].get('Espera', 0)} "
        f"| {s['totals'].get('CNPJ', 0)} "
        f"| {s['totals'].get('IM', 0)} "
        f"| {s['totals'].get('CRM', 0)} |"
        for s in reversed(history)
    )
    return f"""## Totais por fase

| Data | Espera | CNPJ | IM | CRM |
|------|:------:|:----:|:--:|:---:|
{rows}"""


def build_sem_atualizacao_table(history):
    rows = "\n".join(
        f"| {_fmt_date(s['data'])} "
        f"| {s['sem_atualizacao'].get('Espera') or 0} "
        f"| {s['sem_atualizacao'].get('CNPJ') or 0} "
        f"| {s['sem_atualizacao'].get('IM') or 0} |"
        for s in reversed(history)
    )
    return f"""## Sem atualização (>5 dias)

| Data | Espera | CNPJ | IM |
|------|:------:|:----:|:--:|
{rows}"""


def build_atrasados_table(history):
    rows = "\n".join(
        f"| {_fmt_date(s['data'])} "
        f"| {s['atrasados'].get('CNPJ', 0)} "
        f"| {s['atrasados'].get('IM', 0)} "
        f"| {s['necessitam_acao'].get('CNPJ', 0)} "
        f"| {s['necessitam_acao'].get('IM', 0)} |"
        for s in reversed(history)
    )
    return f"""## Atrasados e necessitam ação

| Data | Atr. CNPJ | Atr. IM | Ação CNPJ | Ação IM |
|------|:---------:|:-------:|:---------:|:-------:|
{rows}"""


# ── Montar e publicar cards ───────────────────────────────────────────────────

def text_card(slot_id, row, col, size_x, size_y, md):
    return {
        "id": slot_id,
        "card_id": None,
        "row": row, "col": col, "size_x": size_x, "size_y": size_y,
        "visualization_settings": {
            "text": md,
            "virtual_card": {
                "display": "text",
                "dataset_query": {},
                "name": "",
                "visualization_settings": {},
                "archived": False,
            },
        },
    }


def push_cards(cfg, dash_id, history, cohort_tables, pages_url):
    from cohort import build_cohort_markdown

    # Linha 0–6   : cabeçalho com resumo e link
    # Linha 7–22  : totais | atrasados+ação
    # Linha 23–36 : sem atualização
    # Linha 37–52 : cohort CNPJ | cohort IM
    # Linha 53–68 : cohort Espera | cohort CRM
    cards = [
        text_card(-1,  0,  0, 24,  7, build_header(history, pages_url)),
        text_card(-2,  7,  0, 12, 16, build_totals_table(history)),
        text_card(-3,  7, 12, 12, 16, build_atrasados_table(history)),
        text_card(-4, 23,  0, 24, 14, build_sem_atualizacao_table(history)),
        text_card(-5, 37,  0, 12, 16, build_cohort_markdown(cohort_tables, "CNPJ")),
        text_card(-6, 37, 12, 12, 16, build_cohort_markdown(cohort_tables, "IM")),
        text_card(-7, 53,  0, 12, 16, build_cohort_markdown(cohort_tables, "Espera")),
        text_card(-8, 53, 12, 12, 16, build_cohort_markdown(cohort_tables, "CRM")),
    ]
    r = requests.put(
        f"{cfg['metabase_base_url']}/api/dashboard/{dash_id}/cards",
        headers=hdr(cfg),
        json={"cards": cards},
    )
    r.raise_for_status()
    print(f"  {len(cards)} cards publicados.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    cfg = load_cfg()

    with open(HISTORY_PATH, encoding="utf-8") as f:
        history = json.load(f)
    print(f"Histórico: {len(history)} snapshots")

    # Carrega cohort se disponível
    cohort_tables = {}
    try:
        from cohort import load_cohort_snapshots, compute_cohorts
        snaps = load_cohort_snapshots()
        if snaps:
            # Usa os cards do snapshot mais recente para recomputar
            latest_cards = snaps[-1]["cards"]
            cohort_tables = compute_cohorts(latest_cards)
            print(f"Cohort: {sum(len(v) for v in cohort_tables.values())} semanas")
        else:
            print("Cohort: cohort_snapshots.json vazio ou inexistente.")
    except Exception as e:
        print(f"AVISO: cohort não carregado: {e}")

    pages_url = cfg.get("pages_url", "")
    if not pages_url:
        print("  AVISO: PAGES_URL não definida — link para gráficos omitido.")

    print("Localizando/criando dashboard...")
    dash_id = find_or_create_dashboard(cfg)

    print("Publicando cards...")
    push_cards(cfg, dash_id, history, cohort_tables, pages_url)

    url = f"{cfg['metabase_base_url']}/dashboard/{dash_id}"
    print(f"\nDashboard disponível: {url}")
    print(f"\nAdicione ao GitHub Actions Secrets:")
    print(f"  METABASE_TEXT_DASHBOARD_ID={dash_id}")


if __name__ == "__main__":
    main()
