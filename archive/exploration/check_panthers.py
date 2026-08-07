import sqlite3, requests, json

conn = sqlite3.connect("trader_scanner.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT wallet, username FROM traders").fetchall()
print("tracked:", [(r["username"], r["wallet"][:12]) for r in rows])

panthers = next((r for r in rows if "panther" in (r["username"] or "").lower()), None)
if not panthers:
    raise SystemExit("Panthers not in watchlist")

w = panthers["wallet"]
HDRS = {"User-Agent": "Mozilla/5.0"}
all_acts = []
for offset in (0, 100, 200, 300, 400):
    r = requests.get("https://data-api.polymarket.com/activity",
                     params={"user": w, "limit": 100, "offset": offset},
                     headers=HDRS, timeout=15)
    batch = r.json()
    if not batch:
        break
    all_acts.extend(batch)

print(f"\ntotal activities fetched: {len(all_acts)}")
hits = [a for a in all_acts
        if any(k in json.dumps(a).lower() for k in ("dodgers", "yankees", "inning"))]
print(f"dodgers/yankees/inning hits: {len(hits)}\n")
for i, a in enumerate(hits[:10]):
    idx = all_acts.index(a)
    print(f"#{idx+1} of {len(all_acts)} | {a.get('type')} | {a.get('side','')} | "
          f"{a.get('title','')} | {a.get('outcome','')} | "
          f"${a.get('usdcSize', a.get('size', 0)):,.0f} @ {a.get('price', '')}")
