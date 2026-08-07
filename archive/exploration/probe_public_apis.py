"""Probe Polymarket's PUBLIC data APIs (no keys) to find what works."""
import requests, json

HDRS = {"User-Agent": "Mozilla/5.0"}

def probe(name, url):
    try:
        r = requests.get(url, timeout=12, headers=HDRS)
        print(f"\n=== {name} ===")
        print(f"Status: {r.status_code}")
        print(r.text[:600].encode('ascii', 'replace').decode())
        return r
    except Exception as e:
        print(f"\n=== {name} ===\nERROR: {e}")
        return None

# 1) Username search (this is what the polymarket.com site itself calls)
r = probe("PUBLIC SEARCH: Panthers3698", "https://gamma-api.polymarket.com/public-search?q=Panthers3698")

# 2) Leaderboard (top traders w/ usernames + wallets)
lb = probe("LEADERBOARD", "https://lb-api.polymarket.com/leaderboard?window=all&limit=5")

# 3) Positions for an arbitrary wallet pulled off the leaderboard
if lb is not None and lb.status_code == 200:
    try:
        wallet = lb.json()[0].get("proxyWallet") or lb.json()[0].get("wallet")
        probe(f"POSITIONS for {wallet[:10]}...", f"https://data-api.polymarket.com/positions?user={wallet}&limit=2")
    except Exception as e:
        print(f"couldn't parse leaderboard: {e}")

# 4) US-app profile search variants (in case Panthers3698 is a US-app user)
probe("US search v1", "https://polymarket.us/api/profile/search?q=Panthers3698")
probe("US search v2", "https://api.polymarket.us/v1/profiles/search?q=Panthers3698")
