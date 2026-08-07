import requests, re, json
from collections import Counter

HDRS = {"User-Agent": "Mozilla/5.0"}

# 1) what does the profile page actually contain?
r = requests.get("https://polymarket.com/@panthers3698", headers=HDRS, timeout=15)
print("page status:", r.status_code)
title = re.search(r'<title>(.*?)</title>', r.text)
print("page title:", title.group(1) if title else "none")

wallets = Counter(re.findall(r'0x[a-fA-F0-9]{40}', r.text))
print("wallets on page:", wallets.most_common(5))

# look for the wallet specifically tied to profile fields
for field in ("proxyWallet", "walletAddress", "userAddress"):
    m = re.findall(field + r'["\\s:]+0x[a-fA-F0-9]{40}', r.text)
    if m:
        print(f"{field} matches:", m[:3])

# 2) current positions for the wallet we tracked (no filter)
w = "0xb2445087e4"
full = None
conn_wallets = wallets.most_common(1)
r2 = requests.get("https://data-api.polymarket.com/positions",
                  params={"user": [k for k in wallets if k.lower().startswith(w)][0]
                          if any(k.lower().startswith(w) for k in wallets) else list(wallets)[0],
                          "limit": 100},
                  headers=HDRS, timeout=15)
positions = r2.json()
print(f"\ntracked-wallet positions: {len(positions)}")
positions.sort(key=lambda p: -(p.get("currentValue") or 0))
for p in positions[:8]:
    print(f"  {p.get('title')} | {p.get('outcome')} | "
          f"val ${p.get('currentValue',0):,.0f} | size {p.get('size',0):,.0f} shares")
hits = [p for p in positions
        if any(k in json.dumps(p).lower() for k in ("dodgers", "yankees", "inning"))]
print("dodgers/yankees/inning position hits:", len(hits))
for p in hits:
    print("  HIT:", json.dumps(p)[:300])
