import requests, re, json

HDRS = {"User-Agent": "Mozilla/5.0"}
handle = "farhanalithegre"

# 1) try the public directory search
r = requests.get("https://gamma-api.polymarket.com/public-search",
                 params={"q": handle, "search_profiles": "true", "limit_per_type": 5},
                 headers=HDRS, timeout=12)
data = r.json()
profiles = []
for key in ("profiles", "users", "results"):
    if isinstance(data.get(key), list):
        profiles = data[key]
        break
wallet, name = None, handle
for p in profiles:
    w = p.get("proxyWallet") or p.get("walletAddress") or p.get("address")
    if w:
        wallet, name = w, p.get("name") or p.get("pseudonym") or handle
        print(f"[search] found: {name} -> {wallet}")
        break

# 2) fallback: scrape the profile page for the wallet
if not wallet:
    r = requests.get(f"https://polymarket.com/@{handle}", headers=HDRS, timeout=15)
    wallets = re.findall(r'0x[a-fA-F0-9]{40}', r.text)
    from collections import Counter
    if wallets:
        wallet = Counter(wallets).most_common(1)[0][0]
        print(f"[scrape] page status {r.status_code}, wallet: {wallet}")

if not wallet:
    raise SystemExit("FAIL: could not resolve wallet")

# 3) track them in Whale Watch
r = requests.post("http://127.0.0.1:5001/api/track",
                  json={"wallet": wallet, "username": name}, timeout=60)
print(f"[track] {r.status_code} {r.json()}")

# 4) show what came back
r = requests.get("http://127.0.0.1:5001/api/traders", timeout=20)
for t in r.json():
    if t["wallet"].lower() == wallet.lower():
        print(f"\n{t['username']}: {t['positions_count']} open positions, "
              f"value ${t['positions_value']:,.0f}, unrealized P&L ${t['total_pnl']:,.0f}")
        for p in t["positions"][:6]:
            print(f"  - {p.get('title')} | {p.get('outcome')} | "
                  f"${p.get('currentValue',0):,.0f} (pnl {p.get('cashPnl',0):+,.0f})")
