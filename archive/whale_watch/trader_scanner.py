"""
Polymarket Trader Scanner - search any trader by username, track their
positions and trades continuously.

Data sources (all public, no API keys):
  - gamma-api.polymarket.com/public-search  -> username search, returns profiles + wallets
  - data-api.polymarket.com/positions?user= -> live positions for any wallet
  - data-api.polymarket.com/activity?user=  -> recent trades for any wallet

Run standalone to refresh the watchlist every 5 minutes:
  python trader_scanner.py
The dashboard (trader_dashboard.py) imports refresh_trader() for instant adds.
"""
import json
import time
import sqlite3
import requests
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DB_FILE = str(HERE / "trader_scanner.db")
SCANNER_LOG = str(HERE / "scanner.log")

GAMMA_SEARCH = "https://gamma-api.polymarket.com/public-search"
DATA_API = "https://data-api.polymarket.com"
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

REFRESH_SECONDS = 300


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line.encode("ascii", "replace").decode())
    with open(SCANNER_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS traders (
        wallet TEXT PRIMARY KEY,
        username TEXT,
        bio TEXT,
        added_at TEXT,
        last_refreshed TEXT,
        positions_json TEXT DEFAULT '[]',
        activity_json TEXT DEFAULT '[]',
        total_pnl REAL DEFAULT 0,
        positions_value REAL DEFAULT 0,
        positions_count INTEGER DEFAULT 0
    )""")
    # migrate older schemas in place (ALTER is a no-op error if column exists)
    for col, decl in [("bio", "TEXT"), ("added_at", "TEXT"),
                      ("last_refreshed", "TEXT"),
                      ("positions_json", "TEXT DEFAULT '[]'"),
                      ("activity_json", "TEXT DEFAULT '[]'"),
                      ("total_pnl", "REAL DEFAULT 0"),
                      ("positions_value", "REAL DEFAULT 0"),
                      ("positions_count", "INTEGER DEFAULT 0")]:
        try:
            conn.execute(f"ALTER TABLE traders ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass  # column already there
    conn.commit()
    conn.close()


# ---------- live API calls ----------

def search_profiles(query):
    """Search Polymarket by username. Returns [{username, wallet, bio}, ...]"""
    try:
        r = requests.get(GAMMA_SEARCH,
                         params={"q": query, "search_profiles": "true",
                                 "limit_per_type": 10},
                         headers=HDRS, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        # profiles can arrive under different keys; normalize defensively
        raw = []
        for key in ("profiles", "users", "results"):
            if isinstance(data.get(key), list):
                raw = data[key]
                break
        out = []
        for p in raw:
            wallet = (p.get("proxyWallet") or p.get("walletAddress")
                      or p.get("address") or p.get("wallet") or "")
            name = (p.get("name") or p.get("pseudonym")
                    or p.get("username") or "Unknown")
            if wallet:
                out.append({"username": name, "wallet": wallet,
                            "bio": p.get("bio") or ""})
        return out
    except Exception as e:
        log(f"[ERROR] search '{query}': {e}")
        return []


def resolve_query(query):
    """Turn any user input into trader profiles: a username, an @handle, a
    pasted profile URL, or a raw 0x wallet address all work."""
    import re
    q = query.strip()

    m = re.search(r'0x[a-fA-F0-9]{40}', q)
    if m:
        return [{"username": q if not q.startswith("http") else "Wallet",
                 "wallet": m.group(0), "bio": ""}]

    # pasted URL or @handle -> extract the handle
    m = re.search(r'(?:polymarket\.com/)?@([\w.-]+)', q)
    handle = m.group(1) if m else q

    results = search_profiles(handle)
    if results:
        return results

    # search missed: scrape the profile page for the wallet — but ONLY if the
    # profile actually exists (a 404 page still contains site-widget wallets
    # belonging to random featured traders; scraping those tracks a stranger)
    try:
        r = requests.get(f"https://polymarket.com/@{handle}",
                         headers=HDRS, timeout=15)
        if r.status_code == 200 and handle.lower() in r.text.lower():
            wallets = re.findall(r'0x[a-fA-F0-9]{40}', r.text)
            if wallets:
                from collections import Counter
                wallet = Counter(wallets).most_common(1)[0][0]
                return [{"username": handle, "wallet": wallet, "bio": ""}]
        log(f"[WARN] no profile named '{handle}' on polymarket.com "
            f"(status {r.status_code})")
    except Exception as e:
        log(f"[ERROR] profile scrape '{handle}': {e}")
    return []


def find_market_whales(query, max_markets=8, holders_per_market=8):
    """Given an event/market URL or search text, return the top holders of
    each market in the event: [{market, holders: [{name, wallet, shares}]}]"""
    import re
    q = query.strip()
    event = None
    try:
        m = re.search(r'polymarket\.com/event/([\w-]+)', q)
        if m:
            r = requests.get("https://gamma-api.polymarket.com/events",
                             params={"slug": m.group(1)}, headers=HDRS, timeout=12)
            evs = r.json()
            event = evs[0] if isinstance(evs, list) and evs else None
        if event is None:
            r = requests.get("https://gamma-api.polymarket.com/public-search",
                             params={"q": q, "limit_per_type": 3},
                             headers=HDRS, timeout=12)
            evs = r.json().get("events", []) or []
            event = evs[0] if evs else None
        if event is None:
            return []

        out = []
        for mkt in (event.get("markets") or [])[:max_markets]:
            cid = mkt.get("conditionId")
            if not cid:
                continue
            r = requests.get(f"{DATA_API}/holders",
                             params={"market": cid, "limit": holders_per_market},
                             headers=HDRS, timeout=12)
            if r.status_code != 200:
                continue
            groups = r.json()
            groups = groups if isinstance(groups, list) else [groups]
            holders = []
            for g in groups:
                for h in (g.get("holders") or []):
                    w = h.get("proxyWallet") or h.get("wallet") or ""
                    if not w:
                        continue
                    holders.append({
                        "name": h.get("name") or h.get("pseudonym") or w[:10],
                        "wallet": w,
                        "shares": round(h.get("amount", 0)),
                    })
            holders.sort(key=lambda x: -x["shares"])
            if holders:
                out.append({"market": mkt.get("question", ""),
                            "event": event.get("title", ""),
                            "holders": holders[:holders_per_market]})
        return out
    except Exception as e:
        log(f"[ERROR] find_market_whales '{q[:40]}': {e}")
        return []


def fetch_positions(wallet):
    """Live open positions for a wallet (public data-api)."""
    try:
        r = requests.get(f"{DATA_API}/positions",
                         params={"user": wallet, "limit": 100,
                                 "sortBy": "CURRENT", "sortDirection": "DESC"},
                         headers=HDRS, timeout=12)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        log(f"[ERROR] positions {wallet[:10]}: {e}")
        return []


def fetch_activity(wallet):
    """Recent trades for a wallet (public data-api)."""
    try:
        r = requests.get(f"{DATA_API}/activity",
                         params={"user": wallet, "limit": 100},
                         headers=HDRS, timeout=12)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        log(f"[ERROR] activity {wallet[:10]}: {e}")
        return []


# ---------- watchlist management ----------

def track_trader(wallet, username="", bio=""):
    """Add a trader to the watchlist and refresh them immediately."""
    init_db()
    conn = get_db()
    conn.execute("""INSERT OR IGNORE INTO traders (wallet, username, bio, added_at)
                    VALUES (?, ?, ?, ?)""",
                 (wallet, username, bio, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    refresh_trader(wallet)
    log(f"[OK] tracking {username or wallet[:10]}")


def untrack_trader(wallet):
    conn = get_db()
    conn.execute("DELETE FROM traders WHERE wallet = ?", (wallet,))
    conn.commit()
    conn.close()


def refresh_trader(wallet):
    """Pull fresh positions + activity for one tracked wallet."""
    positions = fetch_positions(wallet)
    activity = fetch_activity(wallet)

    # drop resolved/dust leftovers so the watchlist shows live money only
    if isinstance(positions, list):
        positions = [p for p in positions
                     if (p.get("currentValue") or 0) >= 1.0]

    total_pnl = 0.0
    total_value = 0.0
    for p in positions if isinstance(positions, list) else []:
        for pnl_key in ("cashPnl", "pnl", "unrealizedPnl"):
            if isinstance(p.get(pnl_key), (int, float)):
                total_pnl += p[pnl_key]
                break
        for val_key in ("currentValue", "value", "curValue"):
            if isinstance(p.get(val_key), (int, float)):
                total_value += p[val_key]
                break

    conn = get_db()
    conn.execute("""UPDATE traders SET positions_json=?, activity_json=?,
                    total_pnl=?, positions_value=?, positions_count=?,
                    last_refreshed=? WHERE wallet=?""",
                 (json.dumps(positions), json.dumps(activity),
                  round(total_pnl, 2), round(total_value, 2),
                  len(positions) if isinstance(positions, list) else 0,
                  datetime.now(timezone.utc).isoformat(), wallet))
    conn.commit()
    conn.close()
    return positions, activity


def get_tracked():
    init_db()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM traders ORDER BY total_pnl DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["positions"] = json.loads(d.pop("positions_json") or "[]")
        d["activity"] = json.loads(d.pop("activity_json") or "[]")
        out.append(d)
    return out


# ---------- continuous loop ----------

def run_continuously():
    init_db()
    log("Trader Scanner started. Watchlist refresh every 5 minutes.")
    log("Dashboard: http://127.0.0.1:5001/")
    iteration = 0
    while True:
        try:
            iteration += 1
            conn = get_db()
            wallets = [r["wallet"] for r in
                       conn.execute("SELECT wallet FROM traders").fetchall()]
            conn.close()
            log(f"=== Refresh #{iteration}: {len(wallets)} tracked trader(s) ===")
            for w in wallets:
                positions, _ = refresh_trader(w)
                log(f"  {w[:10]}... {len(positions)} open positions")
            time.sleep(REFRESH_SECONDS)
        except Exception as e:
            log(f"[ERROR] refresh loop: {e}")
            time.sleep(60)


if __name__ == "__main__":
    run_continuously()
