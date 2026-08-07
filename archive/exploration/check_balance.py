import requests, json
from sync_positions_api import create_auth_headers

for path in ("/v1/account/balances", "/v1/portfolio/balances", "/v1/balances"):
    r = requests.get(f"https://api.polymarket.us{path}",
                     headers=create_auth_headers("GET", path), timeout=12)
    print(f"{path}: {r.status_code}")
    if r.status_code == 200:
        print(json.dumps(r.json(), indent=2)[:800])
        break
