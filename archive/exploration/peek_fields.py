import requests, json
r = requests.get("https://data-api.polymarket.com/positions",
                 params={"user": "0xb8128d057e3b64d422af55e2f41b2c8cf832be01", "limit": 1},
                 headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
pos = r.json()
if pos:
    print(json.dumps(pos[0], indent=2)[:1200])
