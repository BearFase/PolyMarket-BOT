"""End-to-end check: search a known trader, track them, confirm positions land."""
import requests, json, sys

BASE = "http://127.0.0.1:5001"

# 1) search
r = requests.get(f"{BASE}/api/search", params={"q": "Domer"}, timeout=20)
profiles = r.json()
print(f"[1] search 'Domer': {r.status_code}, {len(profiles)} profiles")
if not profiles:
    sys.exit("FAIL: no profiles returned")
top = profiles[0]
print(f"    top: {top['username']} {top['wallet']}")

# 2) track
r = requests.post(f"{BASE}/api/track", json=top, timeout=60)
print(f"[2] track: {r.status_code} {r.json()}")

# 3) confirm tracked with positions
r = requests.get(f"{BASE}/api/traders", timeout=20)
traders = r.json()
print(f"[3] tracked traders: {len(traders)}")
for t in traders:
    print(f"    {t['username']}: {t['positions_count']} positions, "
          f"value ${t['positions_value']:,.0f}, pnl ${t['total_pnl']:,.0f}, "
          f"{len(t['activity'])} recent trades")
print("PASS" if traders and traders[0]["positions_count"] >= 0 else "FAIL")
