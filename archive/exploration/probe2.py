"""Probe #2: US-app public profile pages + fixed leaderboard/search variants."""
import requests, re, json

HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

def probe(name, url, show=400):
    try:
        r = requests.get(url, timeout=12, headers=HDRS, allow_redirects=True)
        body = r.text
        print(f"\n=== {name} ===")
        print(f"Status: {r.status_code}  Final URL: {r.url}")
        # hunt for useful signals rather than dumping HTML
        wallets = list(set(re.findall(r'0x[a-fA-F0-9]{40}', body)))[:5]
        hits = re.findall(r'.{60}Panthers3698.{60}', body)[:3]
        if wallets: print(f"WALLETS FOUND: {wallets}")
        if hits:
            print("USERNAME CONTEXT:")
            for h in hits: print("  ..." + h.encode('ascii','replace').decode() + "...")
        if not wallets and not hits:
            print(body[:show].encode('ascii','replace').decode())
        return r
    except Exception as e:
        print(f"\n=== {name} ===\nERROR: {e}")
        return None

# --- US app public profile page guesses ---
probe("US @username page", "https://polymarket.us/@Panthers3698")
probe("US /profile/username", "https://polymarket.us/profile/Panthers3698")
probe("US /u/username", "https://polymarket.us/u/Panthers3698")

# --- gamma search with profile flags + sanity check w/ famous trader ---
probe("gamma search w/ flags", "https://gamma-api.polymarket.com/public-search?q=Panthers3698&search_profiles=true&limit_per_type=5")
probe("gamma search sanity (Domer)", "https://gamma-api.polymarket.com/public-search?q=Domer&search_profiles=true&limit_per_type=3")

# --- leaderboard URL variants ---
probe("lb-api w/ rankType", "https://lb-api.polymarket.com/leaderboard?window=all&rankType=pnl&limit=5")
probe("data-api leaderboard", "https://data-api.polymarket.com/leaderboard?window=all&limit=5")
