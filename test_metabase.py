"""
test_metabase.py
Testa a conexão com o Metabase passo a passo.
Rode via GitHub Actions para identificar onde o erro ocorre.
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

try:
    with open("historico.json", encoding="utf-8") as f:
        history = json.load(f)
    print(f"PASSO 3: historico.json - OK ({len(history)} snapshots)", flush=True)
except Exception as e:
    print(f"PASSO 3: historico.json - FALHOU: {e}", flush=True)
    sys.exit(1)

api_key  = os.environ.get("METABASE_API_KEY", "")
base_url = os.environ.get("METABASE_BASE_URL", "")
print(f"PASSO 4: METABASE_API_KEY  presente: {'SIM' if api_key  else 'NAO'}", flush=True)
print(f"PASSO 4: METABASE_BASE_URL presente: {'SIM' if base_url else 'NAO'}", flush=True)
if not api_key or not base_url:
    print("PASSO 4: secrets ausentes - FALHOU", flush=True)
    sys.exit(1)
print("PASSO 4: secrets - OK", flush=True)

try:
    r = requests.get(f"{base_url}/api/health", timeout=10)
    print(f"PASSO 5: GET /api/health - status {r.status_code}", flush=True)
except Exception as e:
    print(f"PASSO 5: GET /api/health - FALHOU: {e}", flush=True)
    sys.exit(1)

try:
    h = {"X-API-Key": api_key}
    r = requests.get(f"{base_url}/api/user/current", headers=h, timeout=10)
    print(f"PASSO 6: autenticacao - status {r.status_code}", flush=True)
    if r.ok:
        print(f"PASSO 6: autenticado como: {r.json().get('email', 'N/A')}", flush=True)
    else:
        print(f"PASSO 6: autenticacao - FALHOU: {r.text[:300]}", flush=True)
        sys.exit(1)
except Exception as e:
    print(f"PASSO 6: autenticacao - FALHOU: {e}", flush=True)
    sys.exit(1)

try:
    r = requests.get(f"{base_url}/api/collection/tree", headers=h, timeout=10)
    print(f"PASSO 7: GET /api/collection/tree - status {r.status_code}", flush=True)
    if r.ok:
        tree = r.json()
        print(f"PASSO 7: {len(tree)} colecoes raiz encontradas:", flush=True)
        for item in tree[:10]:
            print(f"  - {item.get('name')} (id={item.get('id')})", flush=True)
    else:
        print(f"PASSO 7: collections - FALHOU: {r.text[:300]}", flush=True)
        sys.exit(1)
except Exception as e:
    print(f"PASSO 7: collections - FALHOU: {e}", flush=True)
    sys.exit(1)

try:
    r = requests.get(f"{base_url}/api/database", headers=h, timeout=10)
    print(f"PASSO 8: GET /api/database - status {r.status_code}", flush=True)
    if r.ok:
        data = r.json()
        dbs = data if isinstance(data, list) else data.get("data", [])
        print(f"PASSO 8: {len(dbs)} banco(s) encontrado(s):", flush=True)
        for db in dbs:
            uploads = db.get("uploads_enabled", False)
            print(f"  - '{db.get('name')}' id={db.get('id')} uploads_enabled={uploads}", flush=True)
    else:
        print(f"PASSO 8: databases - FALHOU: {r.text[:300]}", flush=True)
        sys.exit(1)
except Exception as e:
    print(f"PASSO 8: databases - FALHOU: {e}", flush=True)
    sys.exit(1)

print("\nTodos os passos concluidos!", flush=True)
