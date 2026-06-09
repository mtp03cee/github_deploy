"""
test_metabase.py
Testa a conexão com o Metabase passo a passo.
"""
import json
import os
import sys

print("PASSO 1: Python rodando - OK", flush=True)

try:
    import requests
    print("PASSO 2: import requests - OK", flush=True)
except Exception as e:
    print(f"PASSO 2: import requests - FALHOU: {e}", flush=True)
    sys.exit(1)

api_key  = os.environ.get("METABASE_API_KEY", "")
base_url = os.environ.get("METABASE_BASE_URL", "")
dashboard_id = os.environ.get("METABASE_DASHBOARD_ID", "")

if not api_key or not base_url:
    print("PASSO 3: secrets ausentes - FALHOU", flush=True)
    sys.exit(1)
print("PASSO 3: secrets - OK", flush=True)

h = {"X-API-Key": api_key}

# ── Passo 4: Buscar database_id a partir do dashboard existente ───────────────
print(f"\nPASSO 4: Buscando database_id via dashboard {dashboard_id}...", flush=True)
db_id = None
if dashboard_id:
    r = requests.get(f"{base_url}/api/dashboard/{dashboard_id}", headers=h, timeout=15)
    print(f"  GET /api/dashboard/{dashboard_id} → status {r.status_code}", flush=True)
    if r.ok:
        dash = r.json()
        cards = dash.get("dashcards") or dash.get("ordered_cards") or []
        print(f"  {len(cards)} dashcard(s) encontrado(s)", flush=True)
        for c in cards:
            card = c.get("card") or {}
            db = (card.get("dataset_query") or {}).get("database")
            if db:
                db_id = db
                print(f"  database_id encontrado: {db_id} (card '{card.get('name')}')", flush=True)
                break
    else:
        print(f"  FALHOU: {r.text[:200]}", flush=True)
else:
    print("  METABASE_DASHBOARD_ID nao definido", flush=True)

if db_id:
    print(f"PASSO 4: database_id = {db_id} - OK", flush=True)
else:
    print("PASSO 4: nao foi possivel obter database_id - FALHOU", flush=True)
    sys.exit(1)

# ── Passo 5: Sub-coleções de [Atualizado] CS-Clients (id=72) ─────────────────
print("\nPASSO 5: Sub-colecoes de '[Atualizado] CS-Clients' (id=72)...", flush=True)
r = requests.get(
    f"{base_url}/api/collection/72/items?models=collection",
    headers=h, timeout=10
)
print(f"  status {r.status_code}", flush=True)
if r.ok:
    items = r.json().get("data", [])
    print(f"  {len(items)} item(ns) encontrado(s):", flush=True)
    for item in items:
        print(f"  - '{item.get('name')}' id={item.get('id')}", flush=True)
else:
    print(f"  FALHOU: {r.text[:200]}", flush=True)

# ── Passo 6: Tentar criar Model nativo de teste ───────────────────────────────
print("\nPASSO 6: Tentando criar Model nativo de teste...", flush=True)
test_sql = "SELECT 1 AS teste"
payload = {
    "name": "_teste_conexao_deletar",
    "collection_id": 72,
    "display": "table",
    "type": "model",
    "dataset_query": {
        "type": "native",
        "database": db_id,
        "native": {"query": test_sql},
    },
    "visualization_settings": {},
}
r = requests.post(f"{base_url}/api/card", headers={**h, "Content-Type": "application/json"},
                  json=payload, timeout=15)
print(f"  POST /api/card → status {r.status_code}", flush=True)
if r.ok:
    card_id = r.json().get("id")
    print(f"  Model criado com sucesso! card_id={card_id}", flush=True)
    # Limpar card de teste
    requests.delete(f"{base_url}/api/card/{card_id}", headers=h, timeout=10)
    print(f"  Card de teste removido.", flush=True)
    print("PASSO 6: criar Model nativo - OK", flush=True)
else:
    print(f"  FALHOU: {r.text[:400]}", flush=True)

print("\nDiagnostico concluido!", flush=True)
