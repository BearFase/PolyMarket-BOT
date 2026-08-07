"""Find panthers3698 via the public comments API (chat posts carry wallets)."""
import requests, json, re

HDRS = {"User-Agent": "Mozilla/5.0"}

# 1) find recent Dodgers-Yankees events
r = requests.get("https://gamma-api.polymarket.com/events",
                 params={"slug": "", "limit": 20, "closed": "true",
                         "order": "endDate", "ascending": "false",
                         "tag_slug": "mlb"},
                 headers=HDRS, timeout=15)
events = r.json() if r.status_code == 200 else []
if not isinstance(events, list):
    events = events.get("data", [])
dy = [e for e in events
      if re.search(r'dodgers', json.dumps(e), re.I) and re.search(r'yankees', json.dumps(e), re.I)]
print(f"MLB events fetched: {len(events)}, dodgers-yankees matches: {len(dy)}")
for e in dy[:3]:
    print("  event:", e.get("id"), e.get("slug"), e.get("title"))

# fallback: public-search for the game
if not dy:
    r = requests.get("https://gamma-api.polymarket.com/public-search",
                     params={"q": "Dodgers Yankees", "limit_per_type": 10},
                     headers=HDRS, timeout=15)
    d = r.json()
    evs = d.get("events", []) or []
    print(f"search events: {len(evs)}")
    for e in evs[:5]:
        print("  event:", e.get("id"), e.get("slug"), e.get("title"))
    dy = evs

# 2) pull comments for candidate events, hunt for panthers
for e in dy[:5]:
    eid = e.get("id")
    r = requests.get("https://gamma-api.polymarket.com/comments",
                     params={"parent_entity_type": "Event",
                             "parent_entity_id": eid, "limit": 100},
                     headers=HDRS, timeout=15)
    if r.status_code != 200:
        print(f"comments for event {eid}: HTTP {r.status_code}")
        continue
    comments = r.json()
    if not isinstance(comments, list):
        comments = comments.get("data", [])
    print(f"event {eid} ({e.get('slug','')[:40]}): {len(comments)} comments")
    for c in comments:
        blob = json.dumps(c)
        if re.search(r'panthers', blob, re.I):
            print("  *** PANTHERS FOUND ***")
            print(blob[:600])
