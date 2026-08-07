"""Probe #3: authenticated US-app endpoints + public data-api positions."""
import requests, json
from sync_positions_api import create_auth_headers

def us_get(path):
    try:
        r = requests.get(f"https://api.polymarket.us{path}",
                         headers=create_auth_headers("GET", path), timeout=12)
        print(f"\n=== US {path} ===\nStatus: {r.status_code}")
        print(r.text[:400].encode('ascii','replace').decode())
    except Exception as e:
        print(f"\n=== US {path} ===\nERROR: {e}")

def pub_get(name, url):
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        print(f"\n=== {name} ===\nStatus: {r.status_code}")
        print(r.text[:400].encode('ascii','replace').decode())
    except Exception as e:
        print(f"\n=== {name} ===\nERROR: {e}")

# control (known good)
us_get("/v1/portfolio/positions")

# candidate profile/social/leaderboard endpoints on the US exchange
us_get("/v1/markets")
us_get("/v1/leaderboard")
us_get("/v1/users/search?q=Panthers3698")
us_get("/v1/profiles/search?q=Panthers3698")
us_get("/v1/profiles/Panthers3698")
us_get("/v1/social/users?username=Panthers3698")
us_get("/v1/comments?limit=3")

# public data-api positions for a known crypto-side whale wallet (from Domer search)
pub_get("data-api positions (crypto side)",
        "https://data-api.polymarket.com/positions?user=0x2ae42fc5245ba97f86ad98d08b1c12ea2b1aacab&limit=2")
pub_get("data-api activity (crypto side)",
        "https://data-api.polymarket.com/activity?user=0x2ae42fc5245ba97f86ad98d08b1c12ea2b1aacab&limit=2")
