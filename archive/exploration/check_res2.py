import requests, json
from sync_positions_api import create_auth_headers

path = "/v1/portfolio/activities"
r = requests.get(f"https://api.polymarket.us{path}",
                 headers=create_auth_headers("GET", path), timeout=15)
acts = r.json().get("activities", [])
res = [a for a in acts if "RESOLUTION" in str(a)]
print(json.dumps(res[0], indent=2)[:1500])
print("---- second ----")
print(json.dumps(res[1], indent=2)[:800])
