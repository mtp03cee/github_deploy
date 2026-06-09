"""
setup_metabase_dashboard.py
---------------------------
Executa UMA VEZ para criar o dashboard cumulativo no Metabase.

Modos de operação:
  python setup_metabase_dashboard.py           → usa CSV upload (requer admin)
  python setup_metabase_dashboard.py --native  → usa SQL nativo (sem admin)

No modo --native, cria um Model com UNION ALL dos dados do historico.json.
O pipeline diário atualiza o SQL desse Model via PUT /api/card/{id}.

Ao final imprime o METABASE_MODEL_CARD_ID — adicione como secret no GitHub.

Variáveis de ambiente (ou config.json):
  METABASE_API_KEY   — token da API do Metabase
  METABASE_BASE_URL  — ex: https://metabase.selvia.app
  METABASE_UPLOAD_DB_ID  (opcional) — banco para uploads/nativo; detectado se omitido
"""

import csv
import io
import json
import os
import sys

import requests

COLLECTION_PATH = ["[Atualizado] CS-Clients", "Aberturas", "Life cycle"]
DASHBOARD_NAME  = "Life cycle — Histórico Cumulativo"
TABLE_PREFIX    = "historico_aberturas"
MODEL_NAME      = "historico_aberturas_dados"
HISTORY_PATH    = "historico.json"


def load_cfg():
    cfg = {}
    if os.path.exists("config.json"):
        with open("config.json", encoding="utf-8") as f:
            cfg = json.load(f)
    for k in ["METABASE_API_KEY", "METABASE_BASE_URL", "METABASE_UPLOAD_DB_ID"]:
        if os.environ.get(k):
            cfg[k.lower()] = os.environ[k]
    missing = [k for k in ["metabase_api_key", "metabase_base_url"] if not cfg.get(k)]
    if missing:
        print(f"ERRO: variáveis faltando: {missing}")
        sys.exit(1)
    return cfg


def hdr(cfg):
    return {"X-API-Key": cfg["metabase_api_key"], "Content-Type": "application/json"}


def find_collection(cfg):
    r = requests.get(f"{cfg['metabase_base_url']}/api/collection/tree", headers=hdr(cfg))
    r.raise_for_status()

    def search(items, parts):
        target = parts[0].lower().strip()
        for item in items:
            if item.get("name", "").lower().strip() == target:
                if len(parts) == 1:
                    return item["id"]
                return search(item.get("children", []), parts[1:])
        return None

    cid = search(r.json(), COLLECTION_PATH)
    if not cid:
        raise RuntimeError(f"Coleção não encontrada: {' / '.join(COLLECTION_PATH)}")
    print(f"  Coleção: {' / '.join(COLLECTION_PATH)} → id={cid}")
    return cid


def find_db(cfg):
    if cfg.get("metabase_upload_db_id"):
        return int(cfg["metabase_upload_db_id"])

    # Tenta listar databases diretamente
    r = requests.get(f"{cfg['metabase_base_url']}/api/database", headers=hdr(cfg))
    if r.ok:
        data = r.json()
        dbs = data if isinstance(data, list) else data.get("data", [])
        for db in dbs:
            if db.get("uploads_enabled"):
                print(f"  Banco (uploads): '{db['name']}' id={db['id']}")
                return db["id"]
        for db in dbs:
            if "sample" not in db.get("name", "").lower():
                print(f"  Banco: '{db['name']}' id={db['id']}")
                return db["id"]

    # Fallback: extrai database_id do dashboard existente
    dash_id = cfg.get("metabase_dashboard_id")
    if dash_id:
        r2 = requests.get(
            f"{cfg['metabase_base_url']}/api/dashboard/{dash_id}", headers=hdr(cfg)
        )
        if r2.ok:
            cards = r2.json().get("dashcards") or r2.json().get("ordered_cards") or []
            for c in cards:
                card = c.get("card") or {}
                db = (card.get("dataset_query") or {}).get("database")
                if db:
                    print(f"  Banco via dashboard: id={db}")
                    return db

    raise RuntimeError(
        "Nenhum banco encontrado. Defina METABASE_UPLOAD_DB_ID nas variaveis de ambiente."
    )


# ── CSV upload (requer admin) ─────────────────────────────────────────────────

def historico_to_csv(history):
    rows = []
    for s in history:
        t  = s["totals"];          sa = s["sem_atualizacao"]
        at = s["atrasados"];       na = s["necessitam_acao"]
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
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def setup_via_csv(cfg, history, coll_id, db_id):
    print("Fazendo upload do CSV...")
    h = {"X-API-Key": cfg["metabase_api_key"]}
    r = requests.post(
        f"{cfg['metabase_base_url']}/api/uploads/csv",
        headers=h,
        files={"file": (f"{TABLE_PREFIX}.csv", historico_to_csv(history).encode("utf-8"), "text/csv")},
        data={"collection_id": coll_id, "db_id": db_id, "table_prefix": TABLE_PREFIX},
    )
    if not r.ok:
        raise RuntimeError(f"Upload falhou {r.status_code}: {r.text[:400]}")
    model_card_id = r.json()["id"]
    print(f"  model card_id={model_card_id}")

    table_id = _get_model_table_id(cfg, model_card_id)
    fields   = _get_fields(cfg, table_id)
    print(f"  table_id={table_id}, campos: {sorted(fields.keys())}")
    return model_card_id, db_id, table_id, fields


def _get_model_table_id(cfg, card_id):
    r = requests.get(f"{cfg['metabase_base_url']}/api/card/{card_id}", headers=hdr(cfg))
    r.raise_for_status()
    tid = r.json().get("table_id")
    if not tid:
        raise RuntimeError(f"table_id não encontrado no card {card_id}")
    return tid


def _get_fields(cfg, table_id):
    r = requests.get(
        f"{cfg['metabase_base_url']}/api/table/{table_id}/query_metadata",
        headers=hdr(cfg),
    )
    r.raise_for_status()
    return {f["name"]: f["id"] for f in r.json().get("fields", [])}


# ── Native SQL model (sem admin) ──────────────────────────────────────────────

def historico_to_sql(history):
    """Gera UNION ALL com todos os snapshots. Funciona em PostgreSQL, MySQL, SQLite."""
    cols = (
        "data, espera_total, cnpj_total, im_total, crm_total, "
        "espera_sem_atualizacao, cnpj_sem_atualizacao, im_sem_atualizacao, crm_sem_atualizacao, "
        "cnpj_atrasados, im_atrasados, cnpj_necessitam_acao, im_necessitam_acao"
    )
    lines = [f"-- gerado automaticamente por setup_metabase_dashboard.py", f"SELECT {cols} FROM ("]
    for i, s in enumerate(history):
        t  = s["totals"];    sa = s["sem_atualizacao"]
        at = s["atrasados"]; na = s["necessitam_acao"]
        sep = "  VALUES" if i == 0 else "        ,"
        lines.append(
            f"{sep} ('{s['data']}'"
            f", {t.get('Espera') or 0}, {t.get('CNPJ') or 0}, {t.get('IM') or 0}, {t.get('CRM') or 0}"
            f", {sa.get('Espera') or 0}, {sa.get('CNPJ') or 0}, {sa.get('IM') or 0}, {sa.get('CRM') or 0}"
            f", {at.get('CNPJ') or 0}, {at.get('IM') or 0}"
            f", {na.get('CNPJ') or 0}, {na.get('IM') or 0})"
        )
    lines.append(f") AS t({cols})")
    lines.append("ORDER BY data")
    return "\n".join(lines)


def setup_via_native(cfg, history, coll_id, db_id):
    print("Criando Model nativo (SQL)...")
    sql = historico_to_sql(history)
    card = {
        "name": MODEL_NAME,
        "collection_id": coll_id,
        "display": "table",
        "type": "model",
        "dataset_query": {
            "type": "native",
            "database": db_id,
            "native": {"query": sql},
        },
        "visualization_settings": {},
    }
    r = requests.post(f"{cfg['metabase_base_url']}/api/card", headers=hdr(cfg), json=card)
    r.raise_for_status()
    model_card_id = r.json()["id"]
    print(f"  Model criado: card_id={model_card_id}")
    return model_card_id


# ── Perguntas e dashboard ─────────────────────────────────────────────────────

def make_question_from_table(cfg, coll_id, db_id, table_id, date_fid, name, metrics):
    card = {
        "name": name,
        "collection_id": coll_id,
        "display": "line",
        "dataset_query": {
            "type": "query",
            "database": db_id,
            "query": {
                "source-table": table_id,
                "order-by": [["asc", ["field", date_fid, None]]],
            },
        },
        "visualization_settings": {"graph.dimensions": ["data"], "graph.metrics": metrics},
    }
    r = requests.post(f"{cfg['metabase_base_url']}/api/card", headers=hdr(cfg), json=card)
    r.raise_for_status()
    return r.json()["id"]


def make_question_from_model(cfg, coll_id, db_id, model_card_id, name, metrics):
    card = {
        "name": name,
        "collection_id": coll_id,
        "display": "line",
        "dataset_query": {
            "type": "query",
            "database": db_id,
            "query": {"source-card": model_card_id},
        },
        "visualization_settings": {"graph.dimensions": ["data"], "graph.metrics": metrics},
    }
    r = requests.post(f"{cfg['metabase_base_url']}/api/card", headers=hdr(cfg), json=card)
    r.raise_for_status()
    return r.json()["id"]


QUESTIONS = [
    ("Totais em andamento (CNPJ + IM)",           ["cnpj_total", "im_total"]),
    ("Totais por fase (Espera / CNPJ / IM / CRM)", ["espera_total", "cnpj_total", "im_total", "crm_total"]),
    ("Sem atualização >5 dias",                    ["espera_sem_atualizacao", "cnpj_sem_atualizacao", "im_sem_atualizacao"]),
    ("Atrasados (CNPJ / IM)",                      ["cnpj_atrasados", "im_atrasados"]),
    ("Necessitam ação (CNPJ / IM)",                ["cnpj_necessitam_acao", "im_necessitam_acao"]),
]


def make_dashboard(cfg, coll_id, card_ids):
    r = requests.post(
        f"{cfg['metabase_base_url']}/api/dashboard",
        headers=hdr(cfg),
        json={"name": DASHBOARD_NAME, "collection_id": coll_id},
    )
    r.raise_for_status()
    dash_id = r.json()["id"]

    positions = [(0, 0), (12, 0), (0, 8), (12, 8), (0, 16)]
    dashcards = [
        {"card_id": cid, "row": positions[i][1], "col": positions[i][0], "size_x": 12, "size_y": 8}
        for i, cid in enumerate(card_ids)
    ]
    r2 = requests.put(
        f"{cfg['metabase_base_url']}/api/dashboard/{dash_id}/cards",
        headers=hdr(cfg),
        json={"cards": dashcards},
    )
    r2.raise_for_status()
    return dash_id


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    native_mode = "--native" in sys.argv

    cfg = load_cfg()
    with open(HISTORY_PATH, encoding="utf-8") as f:
        history = json.load(f)
    print(f"Histórico: {len(history)} snapshots")

    print("Localizando coleção...")
    coll_id = find_collection(cfg)

    print("Identificando banco de dados...")
    db_id = find_db(cfg)

    if native_mode:
        print("Modo: SQL nativo (sem admin)")
        model_card_id = setup_via_native(cfg, history, coll_id, db_id)

        print("Criando perguntas...")
        card_ids = [
            make_question_from_model(cfg, coll_id, db_id, model_card_id, name, metrics)
            for name, metrics in QUESTIONS
        ]
    else:
        print("Modo: CSV upload (requer admin)")
        model_card_id, db_id, table_id, fields = setup_via_csv(cfg, history, coll_id, db_id)

        if "data" not in fields:
            raise RuntimeError(f"Campo 'data' não encontrado. Disponíveis: {list(fields.keys())}")
        date_fid = fields["data"]

        print("Criando perguntas...")
        card_ids = [
            make_question_from_table(cfg, coll_id, db_id, table_id, date_fid, name, metrics)
            for name, metrics in QUESTIONS
        ]

    print(f"  {len(card_ids)} perguntas criadas: {card_ids}")

    print("Criando dashboard...")
    dash_id = make_dashboard(cfg, coll_id, card_ids)

    url = f"{cfg['metabase_base_url']}/dashboard/{dash_id}"
    print(f"\nDashboard criado: {url}")
    print(f"\nAdicione estes secrets no GitHub Actions:")
    print(f"  METABASE_MODEL_CARD_ID={model_card_id}")
    print(f"  METABASE_CUMULATIVE_DASHBOARD_ID={dash_id}")


if __name__ == "__main__":
    main()
