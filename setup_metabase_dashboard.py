"""
setup_metabase_dashboard.py
---------------------------
Executa UMA VEZ para criar o dashboard cumulativo no Metabase.

O que faz:
  1. Localiza a coleção [Atualizado]CS-clients/Aberturas/Life cycle
  2. Sobe historico.json como CSV via /api/uploads/csv
  3. Cria 5 perguntas (gráficos de linha) nessa coleção
  4. Cria o dashboard e adiciona as perguntas

Ao final imprime METABASE_TABLE_ID — adicione como secret no GitHub Actions.
A partir daí, run_diario.py atualiza a tabela automaticamente todo dia.

Variáveis de ambiente (ou config.json):
  METABASE_API_KEY   — token da API do Metabase
  METABASE_BASE_URL  — ex: https://metabase.selvia.app
  METABASE_UPLOAD_DB_ID  (opcional) — banco para uploads; detectado se omitido
"""

import csv
import io
import json
import os
import sys

import requests

COLLECTION_PATH = ["[Atualizado]CS-clients", "Aberturas", "Life cycle"]
DASHBOARD_NAME  = "Life cycle — Histórico Cumulativo"
TABLE_PREFIX    = "historico_aberturas"
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


def find_upload_db(cfg):
    if cfg.get("metabase_upload_db_id"):
        return int(cfg["metabase_upload_db_id"])
    r = requests.get(f"{cfg['metabase_base_url']}/api/database", headers=hdr(cfg))
    r.raise_for_status()
    data = r.json()
    dbs = data if isinstance(data, list) else data.get("data", [])
    for db in dbs:
        if db.get("uploads_enabled"):
            print(f"  Banco uploads: '{db['name']}' id={db['id']}")
            return db["id"]
    for db in dbs:
        if "sample" not in db.get("name", "").lower():
            print(f"  Banco fallback: '{db['name']}' id={db['id']}")
            return db["id"]
    raise RuntimeError("Nenhum banco disponível para upload. Habilite uploads em Admin > Databases.")


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
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def upload_csv(cfg, csv_data, collection_id, db_id):
    h = {"X-API-Key": cfg["metabase_api_key"]}
    r = requests.post(
        f"{cfg['metabase_base_url']}/api/uploads/csv",
        headers=h,
        files={"file": (f"{TABLE_PREFIX}.csv", csv_data.encode("utf-8"), "text/csv")},
        data={"collection_id": collection_id, "db_id": db_id, "table_prefix": TABLE_PREFIX},
    )
    if not r.ok:
        raise RuntimeError(f"Upload falhou {r.status_code}: {r.text[:400]}")
    return r.json()


def get_model_table_id(cfg, card_id):
    r = requests.get(f"{cfg['metabase_base_url']}/api/card/{card_id}", headers=hdr(cfg))
    r.raise_for_status()
    tid = r.json().get("table_id")
    if not tid:
        raise RuntimeError(f"table_id não encontrado no card {card_id}: {r.json()}")
    return tid


def get_fields(cfg, table_id):
    r = requests.get(
        f"{cfg['metabase_base_url']}/api/table/{table_id}/query_metadata",
        headers=hdr(cfg),
    )
    r.raise_for_status()
    return {f["name"]: f["id"] for f in r.json().get("fields", [])}


def make_question(cfg, coll_id, db_id, table_id, date_fid, name, metric_col_names):
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
        "visualization_settings": {
            "graph.dimensions": ["data"],
            "graph.metrics": metric_col_names,
            "graph.x_axis.title_text": "Data",
        },
    }
    r = requests.post(f"{cfg['metabase_base_url']}/api/card", headers=hdr(cfg), json=card)
    r.raise_for_status()
    return r.json()["id"]


def make_dashboard(cfg, coll_id, card_ids):
    r = requests.post(
        f"{cfg['metabase_base_url']}/api/dashboard",
        headers=hdr(cfg),
        json={"name": DASHBOARD_NAME, "collection_id": coll_id},
    )
    r.raise_for_status()
    dash_id = r.json()["id"]

    positions = [(0, 0), (12, 0), (0, 8), (12, 8), (0, 16)]
    dashcards = []
    for i, cid in enumerate(card_ids):
        col, row = positions[i] if i < len(positions) else (0, i * 8)
        dashcards.append({"card_id": cid, "row": row, "col": col, "size_x": 12, "size_y": 8})

    r2 = requests.put(
        f"{cfg['metabase_base_url']}/api/dashboard/{dash_id}/cards",
        headers=hdr(cfg),
        json={"cards": dashcards},
    )
    r2.raise_for_status()
    return dash_id


def main():
    cfg = load_cfg()

    with open(HISTORY_PATH, encoding="utf-8") as f:
        history = json.load(f)
    print(f"Histórico: {len(history)} snapshots")

    print("Localizando coleção...")
    coll_id = find_collection(cfg)

    print("Identificando banco para upload...")
    db_id = find_upload_db(cfg)

    print("Fazendo upload do CSV...")
    upload_res = upload_csv(cfg, historico_to_csv(history), coll_id, db_id)
    model_card_id = upload_res.get("id")
    print(f"  model card_id={model_card_id}")

    print("Obtendo table_id e campos...")
    table_id = get_model_table_id(cfg, model_card_id)
    fields   = get_fields(cfg, table_id)
    print(f"  table_id={table_id}")
    print(f"  campos: {sorted(fields.keys())}")

    if "data" not in fields:
        raise RuntimeError(f"Campo 'data' não encontrado. Campos disponíveis: {list(fields.keys())}")

    date_fid = fields["data"]

    print("Criando perguntas...")
    card_ids = []

    card_ids.append(make_question(cfg, coll_id, db_id, table_id, date_fid,
        "Totais em andamento (CNPJ + IM)",
        ["cnpj_total", "im_total"]))

    card_ids.append(make_question(cfg, coll_id, db_id, table_id, date_fid,
        "Totais por fase (Espera / CNPJ / IM / CRM)",
        ["espera_total", "cnpj_total", "im_total", "crm_total"]))

    card_ids.append(make_question(cfg, coll_id, db_id, table_id, date_fid,
        "Sem atualização >5 dias",
        ["espera_sem_atualizacao", "cnpj_sem_atualizacao", "im_sem_atualizacao"]))

    card_ids.append(make_question(cfg, coll_id, db_id, table_id, date_fid,
        "Atrasados (CNPJ / IM)",
        ["cnpj_atrasados", "im_atrasados"]))

    card_ids.append(make_question(cfg, coll_id, db_id, table_id, date_fid,
        "Necessitam ação (CNPJ / IM)",
        ["cnpj_necessitam_acao", "im_necessitam_acao"]))

    print(f"  {len(card_ids)} perguntas criadas: {card_ids}")

    print("Criando dashboard...")
    dash_id = make_dashboard(cfg, coll_id, card_ids)

    url = f"{cfg['metabase_base_url']}/dashboard/{dash_id}"
    print(f"\nDashboard criado: {url}")
    print(f"\nAdicione estes secrets no GitHub Actions:")
    print(f"  METABASE_TABLE_ID={table_id}")
    print(f"  METABASE_CUMULATIVE_DASHBOARD_ID={dash_id}")


if __name__ == "__main__":
    main()
