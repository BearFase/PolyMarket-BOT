"""Find panthers3698 in the top-holders of the Dodgers-Yankees markets."""
import requests, json, re

HDRS = {"User-Agent": "Mozilla/5.0"}

# 1) get all markets for the event
r = requests.get("https://gamma-api.polymarket.com/events",
                 params={"id": 698839}, headers=HDRS, timeout=15)
evs = r.json()
ev = evs[0] if isinstance(evs, list) else evs
markets = ev.get("markets", [])
print(f"event: {ev.get('title')} | markets: {len(markets)}")

first_inning = [m for m in markets if re.search(r'1st|first', m.get("question", ""), re.I)]
targets = first_inning or markets
for m in targets:
    print("  market:", m.get("question"), "| conditionId:", m.get("conditionId"))

# 2) holders for each target market
for m in targets[:6]:
    cid = m.get("conditionId")
    if not cid:
        continue
    r = requests.get("https://data-api.polymarket.com/holders",
                     params={"market": cid, "limit": 100}, headers=HDRS, timeout=15)
    if r.status_code != 200:
        print(f"holders {m.get('question','')[:30]}: HTTP {r.status_code}")
        continue
    data = r.json()
    groups = data if isinstance(data, list) else [data]
    for g in groups:
        holders = g.get("holders", []) if isinstance(g, dict) else []
        token = g.get("token", "")
        for h in holders:
            name = (h.get("name") or h.get("pseudonym") or "").lower()
            if "panther" in name:
                print(f"\n*** FOUND in {m.get('question')} ***")
                print(json.dumps(h, indent=2)[:500])
        # also show top 3 for context on the first-inning market
    if first_inning and m in first_inning:
        for g in groups:
            hs = g.get("holders", [])[:3]
            for h in hs:
                print(f"   top holder: {h.get('name') or h.get('pseudonym')} | "
                      f"amount {h.get('amount', 0):,.0f} | {h.get('proxyWallet','')[:12]}")
