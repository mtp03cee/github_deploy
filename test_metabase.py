"""
test_metabase.py - Testa permissões da API key no Metabase
"""
import json
import os
import sys

print("PASSO 1: Python - OK", flush=True)

import requests

api_key  = os.environ.get("METABASE_API_KEY", "")
base_url = os.environ.get("METABASE_BASE_URL", "")
dashboard_id = os.environ.get("METABASE_DASHBOARD_ID", "")
h    = {"X-API-Key": api_key}
hj   = {**h, "Content-Type": "application/json"}
DB   = 84
COLL = 99  # Aberturas/Life Cycle

# ── Passo 2: Listar tabelas acessíveis no DB 84 ───────────────────────────────
print(f"\nPASSO 2: Tabelas no DB {DB}...", flush=True)
r = requests.get(f"{base_url}/api/database/{DB}/schemas", headers=h, timeout=10)
print(f"  /api/database/{DB}/schemas → {r.status_code}", flush=True)
schema = None
if r.ok:
    schemas = r.json()
    print(f"  schemas: {schemas}", flush=True)
    schema = schemas[0] if schemas else None

tables = []
if schema is not None:
    r2 = requests.get(
        f"{base_url}/api/database/{DB}/schema/{schema}", headers=h, timeout=10
    )
    print(f"  /api/database/{DB}/schema/{schema} → {r2.status_code}", flush=True)
    if r2.ok:
        tables = r2.json()
        print(f"  {len(tables)} tabela(s) encontrada(s):", flush=True)
        for t in tables[:10]:
            print(f"    id={t.get('id')} nome='{t.get('name')}'", flush=True)

# ── Passo 3: Tentar criar question MBQL (não-nativa) ─────────────────────────
print(f"\nPASSO 3: Criar question MBQL (nao-nativa)...", flush=True)
if tables:
    table_id = tables[0]["id"]
    print(f"  Usando tabela id={table_id} ('{tables[0].get('name')}')", flush=True)
    payload = {
        "name": "_teste_mbql_deletar",
        "collection_id": COLL,
        "display": "table",
        "dataset_query": {
            "type": "query",
            "database": DB,
            "query": {"source-table": table_id, "limit": 1},
        },
        "visualization_settings": {},
    }
    r = requests.post(f"{base_url}/api/card", headers=hj, json=payload, timeout=15)
    print(f"  POST /api/card (MBQL) → {r.status_code}", flush=True)
    if r.ok:
        cid = r.json().get("id")
        print(f"  Question MBQL criada! card_id={cid}", flush=True)
        requests.delete(f"{base_url}/api/card/{cid}", headers=h, timeout=10)
        print(f"  Removida.", flush=True)
    else:
        print(f"  FALHOU: {r.text[:300]}", flush=True)
else:
    print("  Sem tabelas para testar", flush=True)

# ── Passo 4: Tentar /api/dataset com SQL nativo ───────────────────────────────
print(f"\nPASSO 4: /api/dataset com SQL nativo...", flush=True)
payload = {
    "database": DB,
    "type": "native",
    "native": {"query": "SELECT 1 AS n"},
}
r = requests.post(f"{base_url}/api/dataset", headers=hj, json=payload, timeout=15)
print(f"  POST /api/dataset (native) → {r.status_code}", flush=True)
if r.ok:
    print(f"  Resultado: {r.json().get('data', {}).get('rows', 'N/A')}", flush=True)
    print("  /api/dataset nativo - OK", flush=True)
else:
    print(f"  FALHOU: {r.text[:300]}", flush=True)

# ── Passo 5: Tentar criar dashboard na coleção 99 ────────────────────────────
print(f"\nPASSO 5: Criar dashboard na colecao {COLL}...", flush=True)
r = requests.post(
    f"{base_url}/api/dashboard",
    headers=hj,
    json={"name": "_teste_dashboard_deletar", "collection_id": COLL},
    timeout=10,
)
print(f"  POST /api/dashboard → {r.status_code}", flush=True)
if r.ok:
    dash_id = r.json().get("id")
    print(f"  Dashboard criado! id={dash_id}", flush=True)

    # Passo 5b: Adicionar card de texto
    text_card = {
        "cards": [{
            "id": -1,
            "card_id": None,
            "row": 0, "col": 0, "size_x": 24, "size_y": 6,
            "visualization_settings": {
                "text": "## Teste\nSe aparecer aqui, text cards funcionam.",
                "virtual_card": {
                    "display": "text",
                    "dataset_query": {},
                    "name": "",
                    "visualization_settings": {},
                    "archived": False
                }
            }
        }]
    }
    r2 = requests.put(
        f"{base_url}/api/dashboard/{dash_id}/cards", headers=hj, json=text_card, timeout=10
    )
    print(f"  PUT /api/dashboard/{dash_id}/cards (text) → {r2.status_code}", flush=True)
    if r2.ok:
        print("  Text card adicionado - OK", flush=True)
    else:
        print(f"  Text card FALHOU: {r2.text[:200]}", flush=True)

    # Limpar
    requests.delete(f"{base_url}/api/dashboard/{dash_id}", headers=h, timeout=10)
    print(f"  Dashboard de teste removido.", flush=True)
else:
    print(f"  FALHOU: {r.text[:300]}", flush=True)

print("\nDiagnostico concluido!", flush=True)
