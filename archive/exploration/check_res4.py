import requests, json
from sync_positions_api import create_auth_headers

path = "/v1/portfolio/activities"
r = requests.get(f"https://api.polymarket.us{path}",
                 headers=create_auth_headers("GET", path), timeout=15)
acts = r.json().get("activities", [])

for a in acts:
    pr = a.get("positionResolution")
    if not pr or "aadc-fwc" not in pr.get("marketSlug", ""):
        continue
    print("=== FULL market object ===")
    print(json.dumps(pr.get("market", {}), indent=2))
    print("\n=== FULL afterPosition ===")
    print(json.dumps(pr.get("afterPosition", {}), indent=2)[:900])
