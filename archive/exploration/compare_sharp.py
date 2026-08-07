"""Compare today's sharp-money games vs Polymarket live prices."""
import requests, json

HDRS = {"User-Agent": "Mozilla/5.0"}
# implied win probability from the best available American odds in the screenshot
games = [
    ("mlb-mia-hou-2026-07-20", "Marlins",   108, "Astros",   100),
    ("mlb-sf-kc-2026-07-20",   "Giants",    108, "Royals",   100),
    ("mlb-wsh-col-2026-07-20", "Nationals", 100, "Rockies",  113),
    ("mlb-cin-sea-2026-07-20", "Reds",      133, "Mariners", 100),
]

def imp(odds):  # american odds -> implied probability
    return 100/(odds+100) if odds > 0 else abs(odds)/(abs(odds)+100)

for slug, away, ao, home, ho in games:
    r = requests.get("https://gamma-api.polymarket.com/events",
                     params={"slug": slug}, headers=HDRS, timeout=12)
    evs = r.json()
    ev = evs[0] if isinstance(evs, list) and evs else None
    if not ev:
        print(f"{away}@{home}: event not found ({slug})")
        continue
    ml = None
    for m in ev.get("markets", []):
        q = m.get("question", "")
        if "vs" in q.lower() and not any(x in q.lower() for x in ("inning", "spread", "o/u", "run", "strikeout", "hits")):
            ml = m
            break
    if not ml:
        ml = (ev.get("markets") or [None])[0]
    try:
        outcomes = json.loads(ml.get("outcomes", "[]"))
        prices = [float(p) for p in json.loads(ml.get("outcomePrices", "[]"))]
    except Exception:
        print(f"{away}@{home}: no prices")
        continue
    print(f"\n{away} @ {home}  ({ml.get('question','')[:50]})")
    for team, odds in ((away, ao), (home, ho)):
        book_p = imp(odds)
        pm_p = None
        for o, p in zip(outcomes, prices):
            if team.lower() in o.lower():
                pm_p = p
        if pm_p is None:
            continue
        edge = (book_p - pm_p) * 100
        tag = "  <-- POLYMARKET CHEAPER (edge)" if edge > 2 else ""
        print(f"  {team}: books imply {book_p*100:.1f}% | Polymarket {pm_p*100:.1f}%{tag}")
