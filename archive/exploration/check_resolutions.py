import requests, json
from sync_positions_api import create_auth_headers

path = "/v1/portfolio/activities"
r = requests.get(f"https://api.polymarket.us{path}",
                 headers=create_auth_headers("GET", path), timeout=15)
print("status:", r.status_code)
acts = r.json().get("activities", []) if r.status_code == 200 else []
for a in acts[:12]:
    t = a.get("activityType", a.get("type", "?"))
    meta = a.get("marketMetadata", {}) or {}
    amt = (a.get("amount") or {}).get("value", a.get("cashDelta", ""))
    print(f"{a.get('createTime','')[:19]} | {t} | {meta.get('title','')} / {meta.get('outcome','')} | amount: {amt}")
