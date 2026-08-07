import requests
for url in ["https://docs.polymarket.us/api-reference/websocket/overview.md",
            "https://docs.polymarket.us/api-reference/websocket/private.md"]:
    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    print(f"\n{'='*70}\n{url} -> {r.status_code}\n{'='*70}")
    print(r.text[:6000].encode("ascii", "replace").decode())
