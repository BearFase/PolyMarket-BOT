import requests, json
from sync_positions_api import create_auth_headers

path = "/v1/portfolio/activities"
r = requests.get(f"https://api.polymarket.us{path}",
                 headers=create_auth_headers("GET", path), timeout=15)
acts = r.json().get("activities", [])

for a in acts:
    pr = a.get("positionResolution")
    if not pr:
        continue
    slug = pr.get("marketSlug", "")
    if "2026-07-19" not in slug:
        continue
    print(f"\n=== {slug} ===")
    print("keys:", list(pr.keys()))
    for k, v in pr.items():
        if k == "beforePosition":
            bp = v
            print(f"  beforePosition.cost: {bp.get('cost',{}).get('value')}")
            print(f"  beforePosition.netPosition: {bp.get('netPosition')}")
            outcome = bp.get('marketMetadata',{}).get('outcome')
            subj = (bp.get('marketMetadata',{}).get('subject') or {}).get('name')
            print(f"  outcome: {subj or outcome}")
        else:
            print(f"  {k}: {json.dumps(v)[:200]}")
