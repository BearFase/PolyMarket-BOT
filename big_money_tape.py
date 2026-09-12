"""Anonymous Polymarket US big-money sports execution tape.

Discovers standard markets for major sports events, subscribes to the retail
market WebSocket trade feed, and retains the five largest taker-initiated BUY
trades per event. The feed contains no participant identity; records are
therefore deliberately anonymous.
"""
import hashlib
import json
import os
import random
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import websocket
from dotenv import load_dotenv

from sync_positions_api import create_auth_headers
from system_status import (
    mark_error,
    mark_success,
    set_stream_state,
)

try:
    import trade_journal
except Exception:  # a broken journal module must never stop the tape loading
    trade_journal = None

load_dotenv()

HERE = Path(__file__).parent
DB_FILE = HERE / "big_money_tape.db"
MLB_RESEARCH_DB_FILE = HERE / "mlb_research.db"
# Leagues whose every delivered trade is appended to an immutable journal. MLB
# full-flow capture is separate from the buy-only MLB journal above, which is
# left exactly as it was.
JOURNALED_LEAGUES = ("nfl", "mlb")
# None keeps the journals beside DB_FILE. Tests point DB_FILE at a temporary
# directory, so they isolate the journals automatically; a stray test row in an
# append-only table could never be removed.
TRADE_JOURNAL_DIR = None
LOG_FILE = HERE / "big_money_tape.log"
GATEWAY = "https://gateway.polymarket.us"
WS_PATH = "/v1/ws/markets"
WS_URL = "wss://api.polymarket.us" + WS_PATH

LEAGUES = ("nfl", "nba", "wnba", "mlb", "nhl", "cbb", "cfb", "ufc")
STANDARD_TYPES = {"moneyline", "spread", "spreads", "total", "totals"}
TOP_PER_EVENT = 5
DISCOVERY_EVERY = 15 * 60
SETTLE_EVERY = 10 * 60
MLB_RESEARCH_SYNC_EVERY = 30 * 60
MLB_SPORTSBOOK_SYNC_EVERY = 6 * 60 * 60
MIN_DISPLAY_TRADE_USD = float(os.getenv("BIG_MONEY_MIN_DISPLAY_USD", "5"))
DISCOVERY_MAX_ATTEMPTS = 3
DISCOVERY_BACKOFF_BASE = 1.0
DISCOVERY_BACKOFF_JITTER = 0.5
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}

_market_lock = threading.Lock()
_market_map = {}
_last_trade_status_write = 0.0


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3's context manager, then always close."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def log(message):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line.encode("ascii", "replace").decode())
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def connect_db():
    conn = sqlite3.connect(
        DB_FILE, timeout=20, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
          event_slug TEXT PRIMARY KEY, title TEXT NOT NULL, league TEXT,
          start_time TEXT, last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS markets (
          market_slug TEXT PRIMARY KEY, event_slug TEXT NOT NULL,
          question TEXT, market_type TEXT, long_label TEXT, short_label TEXT,
          last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bets (
          id TEXT PRIMARY KEY, event_slug TEXT NOT NULL, market_slug TEXT NOT NULL,
          league TEXT, event_title TEXT, question TEXT, selection TEXT,
          raw_selection TEXT,
          selected_side TEXT, contracts REAL, entry_price REAL, risk_usd REAL,
          potential_profit REAL, trade_time TEXT, status TEXT DEFAULT 'OPEN',
          result TEXT, payout REAL, profit REAL, settled_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_bets_event_risk
          ON bets(event_slug, risk_usd DESC);
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(bets)")}
        if "raw_selection" not in columns:
            conn.execute("ALTER TABLE bets ADD COLUMN raw_selection TEXT")
        conn.execute("""UPDATE bets SET raw_selection=selection
                        WHERE raw_selection IS NULL""")


def _iso(value):
    return value or datetime.now(timezone.utc).isoformat()


def _request_events(params, request_get=requests.get, sleep=time.sleep,
                    jitter=random.uniform):
    """Fetch one event page with bounded transient-only retries."""
    url = f"{GATEWAY}/v1/events"
    league = params.get("tagSlug", "unknown")
    last_exc = None
    for attempt in range(1, DISCOVERY_MAX_ATTEMPTS + 1):
        try:
            response = request_get(url, params=params, timeout=25)
            if response.status_code in TRANSIENT_HTTP_STATUSES:
                response.raise_for_status()
            if 400 <= response.status_code < 500:
                response.raise_for_status()  # ordinary 4xx: fail immediately
            response.raise_for_status()
            return response.json().get("events", [])
        except (requests.ConnectionError, requests.Timeout) as exc:
            transient = True
            last_exc = exc
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            transient = status in TRANSIENT_HTTP_STATUSES
            last_exc = exc
        if not transient or attempt >= DISCOVERY_MAX_ATTEMPTS:
            raise last_exc
        delay = (DISCOVERY_BACKOFF_BASE * (2 ** (attempt - 1))
                 + jitter(0, DISCOVERY_BACKOFF_JITTER))
        status_text = getattr(
            getattr(last_exc, "response", None), "status_code", "")
        reason = (f"HTTP {status_text}" if status_text
                  else last_exc.__class__.__name__)
        log(f"discovery {league} transient {reason}; retry "
            f"{attempt + 1}/{DISCOVERY_MAX_ATTEMPTS} in {delay:.1f}s")
        sleep(delay)


def _clean_line(value):
    text = str(value or "").strip()
    match = re.search(r"[+-]?\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def format_trade_label(meta, raw_selection):
    """Build a matchup-aware label strictly from supplied market metadata."""
    raw = str(raw_selection or "").strip()
    event = str(meta.get("event_title") or "").strip()
    question = str(meta.get("question") or "").strip()
    market_type = str(meta.get("market_type") or "").lower()

    if market_type == "moneyline":
        if raw and event:
            return f"{raw} moneyline — {event}"
        return raw or question or event or "Unknown selection"

    if market_type in {"total", "totals"}:
        total_match = re.search(
            r"\b(?:more\s+than|over|under)\s+(\d+(?:\.\d+)?)", question,
            flags=re.IGNORECASE)
        line = total_match.group(1) if total_match else _clean_line(raw)
        if event and raw and line:
            return f"{event} — {raw} {line}"
        if event and raw:
            return f"{event} — {raw}"
        return question or raw or event or "Unknown total"

    if market_type in {"spread", "spreads"}:
        spread_match = re.search(
            r"Will (?:the )?(.+?) cover ([+-]?\d+(?:\.\d+)?) "
            r"vs (?:the )?(.+?)(?: in |\?|$)",
            question, flags=re.IGNORECASE)
        if spread_match and raw:
            favorite = spread_match.group(1).strip()
            opponent = spread_match.group(3).strip()
            offered = _clean_line(raw) or raw
            long_line = _clean_line(meta.get("long_label"))
            if raw == str(meta.get("short_label") or "").strip() \
                    or (long_line and offered != long_line):
                return f"{opponent} {offered} vs {favorite}"
            return f"{favorite} {offered} vs {opponent}"
        if event and raw:
            return f"{event} — {raw}"
        return question or raw or event or "Unknown spread"

    if event and raw:
        return f"{event} — {raw}"
    return question or raw or event or "Unknown selection"


def discover_markets():
    """Discover near-term standard markets. Individual league failures are safe."""
    now = datetime.now(timezone.utc)
    params_base = {
        "limit": 100,
        "startTimeMin": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "startTimeMax": (now + timedelta(days=3)).isoformat().replace("+00:00", "Z"),
    }
    found = {}
    found_events = {}
    successful_request = False
    # Complete network discovery before opening a database transaction. A slow
    # upstream retry must never hold SQLite's writer lock and block feed reads.
    for league in LEAGUES:
        try:
            params = dict(params_base, tagSlug=league)
            events = _request_events(params)
            successful_request = True
        except Exception as exc:
            log(f"discovery {league} failed: {exc}")
            mark_error("market_discovery", f"{league}: {exc}")
            continue
        for event in events:
            event_slug = event.get("slug")
            if not event_slug:
                continue
            found_events[event_slug] = (
                event_slug,
                event.get("title", event_slug),
                league,
                event.get("startTime") or event.get("eventDate"),
                _iso(None),
            )
            for market in event.get("markets", []):
                market_type = (market.get("marketType") or "").lower()
                # The US gateway currently reports `closed: true` even for
                # active same-day app markets, so it is not reliable here.
                if market_type not in STANDARD_TYPES:
                    continue
                slug = market.get("slug")
                if not slug:
                    continue
                sides = market.get("marketSides") or []
                long_label = next((s.get("description") for s in sides
                                   if s.get("long") is True), None)
                short_label = next((s.get("description") for s in sides
                                    if s.get("long") is False), None)
                long_label = long_label or (market.get("marketMetadata") or {}).get("outcome") or "Yes"
                short_label = short_label or "No"
                found[slug] = {
                    "market_slug": slug, "event_slug": event_slug,
                    "event_title": event.get("title", event_slug),
                    "league": league, "question": market.get("question", ""),
                    "market_type": market_type, "long_label": long_label,
                    "short_label": short_label,
                    "source_start_time": event.get("startTime") or event.get("eventDate"),
                }

    with connect_db() as conn:
        conn.executemany("""INSERT INTO events VALUES (?,?,?,?,?)
          ON CONFLICT(event_slug) DO UPDATE SET title=excluded.title,
          league=excluded.league,start_time=excluded.start_time,
          last_seen=excluded.last_seen""", found_events.values())
        conn.executemany("""INSERT INTO markets VALUES (?,?,?,?,?,?,?)
          ON CONFLICT(market_slug) DO UPDATE SET
          event_slug=excluded.event_slug,question=excluded.question,
          market_type=excluded.market_type,long_label=excluded.long_label,
          short_label=excluded.short_label,last_seen=excluded.last_seen""",
          ((slug, meta["event_slug"], meta["question"], meta["market_type"],
            meta["long_label"], meta["short_label"], _iso(None))
           for slug, meta in found.items()))
        conn.commit()
    with _market_lock:
        _market_map.update(found)
    if successful_request:
        mark_success("market_discovery")
    log(f"discovered {len(found)} standard markets")
    return found


def load_known_markets():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with connect_db() as conn:
        rows = conn.execute("""SELECT m.*, e.title event_title, e.league,
          e.start_time source_start_time
          FROM markets m JOIN events e USING(event_slug)
          WHERE m.last_seen >= ?""", (cutoff,)).fetchall()
    with _market_lock:
        for row in rows:
            _market_map[row["market_slug"]] = dict(row)


def _number(value):
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _trade_journal_path(league):
    name = f"{league}_trade_journal.db"
    if TRADE_JOURNAL_DIR:
        return Path(TRADE_JOURNAL_DIR) / name
    return Path(DB_FILE).with_name(name)


def _report_trade_journal_error(message):
    log(message)
    mark_error("trade_journal", message)


def record_trade(trade):
    slug = trade.get("marketSlug") or trade.get("market_slug")
    with _market_lock:
        meta = _market_map.get(slug)
    if not meta:
        return False
    league = meta.get("league")
    if trade_journal is not None and league in JOURNALED_LEAGUES:
        # Journal every observed trade before the display filters below discard
        # sells and invalid prints. journal_trade never raises.
        trade_journal.journal_trade(
            league, _trade_journal_path(league), trade, meta,
            on_error=_report_trade_journal_error, on_stats=log)
    taker = trade.get("taker") or {}
    intent = taker.get("intent", "")
    if intent not in ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_BUY_SHORT"):
        return False
    instrument_price = _number(trade.get("price"))
    contracts = _number(trade.get("quantity"))
    if not contracts or not (0 < instrument_price < 1):
        return False
    is_long = intent == "ORDER_INTENT_BUY_LONG"
    entry_price = instrument_price if is_long else 1 - instrument_price
    risk = contracts * entry_price
    potential_profit = contracts - risk
    trade_time = trade.get("tradeTime") or trade.get("trade_time") or _iso(None)
    raw_id = f"{slug}|{trade_time}|{contracts:.4f}|{instrument_price:.6f}|{intent}"
    bet_id = hashlib.sha256(raw_id.encode()).hexdigest()[:24]
    raw_selection = meta["long_label"] if is_long else meta["short_label"]
    selection = format_trade_label(meta, raw_selection)
    if meta["league"] == "mlb" and meta["market_type"] == "moneyline" \
            and risk >= MIN_DISPLAY_TRADE_USD:
        try:
            from mlb_research import MLBResearchRegistry
            MLBResearchRegistry(MLB_RESEARCH_DB_FILE).record_trade({
                "source_trade_key": bet_id,
                "websocket_trade_id": trade.get("id") or trade.get("tradeId"),
                "event_slug": meta["event_slug"], "market_slug": slug,
                "league": "mlb", "market_type": "moneyline",
                "event_title": meta["event_title"], "selected_team": raw_selection,
                "raw_selection": raw_selection,
                "selected_side": "LONG" if is_long else "SHORT",
                "contracts": round(contracts, 4), "execution_price": round(entry_price, 6),
                "risk_usd": round(risk, 2), "trade_timestamp_utc": trade_time,
                "source_market_start_time": meta.get("source_start_time"),
                "source_identifiers": {"market_slug": slug,
                                       "event_slug": meta["event_slug"]},
            })
        except Exception as exc:
            log(f"MLB research journal failed for {bet_id}: {exc}")
            mark_error("mlb_research_journal", str(exc))
    with connect_db() as conn:
        conn.execute("""INSERT OR IGNORE INTO bets
          (id,event_slug,market_slug,league,event_title,question,selection,raw_selection,
           selected_side,contracts,entry_price,risk_usd,potential_profit,trade_time)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (bet_id, meta["event_slug"], slug, meta["league"],
           meta["event_title"], meta["question"], selection, raw_selection,
           "LONG" if is_long else "SHORT", round(contracts, 4),
           round(entry_price, 6), round(risk, 2), round(potential_profit, 2),
           trade_time))
        conn.execute("""DELETE FROM bets WHERE event_slug=? AND status='OPEN'
          AND id NOT IN (SELECT id FROM bets WHERE event_slug=? AND status='OPEN'
                         ORDER BY risk_usd DESC LIMIT ?)""",
          (meta["event_slug"], meta["event_slug"], TOP_PER_EVENT))
        conn.commit()
    if risk >= MIN_DISPLAY_TRADE_USD:
        log(f"trade {meta['league']} {selection}: ${risk:,.2f} risk")
    return True


def settle_open_bets():
    with connect_db() as conn:
        slugs = [r[0] for r in conn.execute(
            "SELECT DISTINCT market_slug FROM bets WHERE status='OPEN'")]
    settled = 0
    for slug in slugs:
        try:
            response = requests.get(f"{GATEWAY}/v1/markets/{slug}/settlement",
                                    timeout=15)
            if response.status_code != 200:
                continue
            data = response.json()
            px = _number(data.get("settlementPrice") or data.get("price")
                         or data.get("settlement"))
            if px not in (0.0, 1.0):
                continue
        except Exception:
            continue
        with connect_db() as conn:
            rows = conn.execute(
                "SELECT * FROM bets WHERE status='OPEN' AND market_slug=?", (slug,)
            ).fetchall()
            for row in rows:
                won = (row["selected_side"] == "LONG" and px == 1.0) or \
                      (row["selected_side"] == "SHORT" and px == 0.0)
                payout = row["contracts"] if won else 0.0
                profit = payout - row["risk_usd"]
                conn.execute("""UPDATE bets SET status='SETTLED',result=?,payout=?,
                  profit=?,settled_at=? WHERE id=?""",
                  ("WIN" if won else "LOSS", round(payout, 2),
                   round(profit, 2), _iso(None), row["id"]))
                settled += 1
            conn.commit()
    if settled:
        log(f"settled {settled} tape bet(s)")
    return settled


def snapshot():
    init_db()
    with connect_db() as conn:
        bets = [dict(r) for r in conn.execute(
            "SELECT * FROM bets ORDER BY trade_time DESC, risk_usd DESC LIMIT 500")]
        markets = {
            row["market_slug"]: dict(row)
            for row in conn.execute("SELECT * FROM markets")
        }
    for bet in bets:
        market = markets.get(bet["market_slug"], {})
        meta = {
            "event_title": bet.get("event_title"),
            "question": bet.get("question") or market.get("question"),
            "market_type": market.get("market_type"),
            "long_label": market.get("long_label"),
            "short_label": market.get("short_label"),
        }
        bet["selection"] = format_trade_label(
            meta, bet.get("raw_selection") or bet.get("selection"))
    visible = [b for b in bets if b["risk_usd"] >= MIN_DISPLAY_TRADE_USD]
    settled = [b for b in visible if b["status"] == "SETTLED"]
    risk = sum(b["risk_usd"] for b in settled)
    profit = sum(b["profit"] or 0 for b in settled)
    return {
        "generated": _iso(None), "anonymous": True,
        "minimum_display_usd": MIN_DISPLAY_TRADE_USD,
        "open": [b for b in visible if b["status"] == "OPEN"],
        "settled": settled,
        "summary": {"tracked": len(visible), "internal_tracked": len(bets),
                    "settled": len(settled),
                    "wins": sum(b["result"] == "WIN" for b in settled),
                    "risk": round(risk, 2), "profit": round(profit, 2),
                    "roi_pct": round(profit / risk * 100, 1) if risk else 0},
    }


def _subscriptions(slugs):
    return [{"subscribe": {"requestId": f"tape-{i // 100 + 1}",
             "subscriptionType": "SUBSCRIPTION_TYPE_TRADE",
             "marketSlugs": slugs[i:i + 100]}}
            for i in range(0, len(slugs), 100)]


def run():
    init_db()
    load_known_markets()
    discover_markets()
    if trade_journal is None:
        _report_trade_journal_error("trade journal unavailable: module failed to import")
    else:
        for league in JOURNALED_LEAGUES:
            session = trade_journal.start_capture_session(
                league, _trade_journal_path(league), note="big_money_tape stream start",
                on_error=_report_trade_journal_error)
            log(f"{league.upper()} trade journal capture session "
                f"{session or 'FAILED TO START'}")

    def mlb_research_sync():
        from mlb_research import MLBResearchRegistry, fetch_schedule
        registry = MLBResearchRegistry(MLB_RESEARCH_DB_FILE)
        today = datetime.now(timezone.utc).date()
        registry.ingest_schedule(fetch_schedule(today - timedelta(days=7),
                                                today + timedelta(days=7)))
        registry.migrate_legacy(DB_FILE)

    def mlb_sportsbook_sync():
        from mlb_research import MLBResearchRegistry, fetch_sportsbook
        registry = MLBResearchRegistry(MLB_RESEARCH_DB_FILE)
        registry.ingest_sportsbook(fetch_sportsbook())

    def mlb_sportsbook_loop():
        while True:
            try:
                mlb_sportsbook_sync()
            except Exception as exc:
                log(f"MLB sportsbook snapshot refresh failed: {exc}")
            time.sleep(MLB_SPORTSBOOK_SYNC_EVERY)

    def mlb_research_loop():
        while True:
            try:
                mlb_research_sync()
            except Exception as exc:
                log(f"MLB canonical research refresh failed: {exc}")
                mark_error("mlb_research_sync", str(exc))
            time.sleep(MLB_RESEARCH_SYNC_EVERY)

    threading.Thread(target=mlb_research_loop, daemon=True).start()
    threading.Thread(target=mlb_sportsbook_loop, daemon=True).start()

    def maintenance_loop():
        while True:
            time.sleep(SETTLE_EVERY)
            try:
                settle_open_bets()
            except Exception as exc:
                log(f"settlement maintenance failed: {exc}")
            try:
                discover_markets()
            except Exception as exc:
                log(f"market discovery maintenance failed: {exc}")

    threading.Thread(target=maintenance_loop, daemon=True).start()
    while True:
        with _market_lock:
            slugs = sorted(_market_map)
        if not slugs:
            time.sleep(60)
            continue

        def on_open(ws):
            for subscription in _subscriptions(slugs):
                ws.send(json.dumps(subscription))
            log(f"trade stream subscribed to {len(slugs)} markets")
            set_stream_state("connected")

        def on_message(ws, raw):
            global _last_trade_status_write
            try:
                msg = json.loads(raw)
            except Exception:
                return
            if msg.get("trade"):
                trade = msg["trade"]
                now_monotonic = time.monotonic()
                if now_monotonic - _last_trade_status_write >= 1:
                    mark_success(
                        "trade", at=trade.get("tradeTime")
                        or trade.get("trade_time") or _iso(None))
                    _last_trade_status_write = now_monotonic
                record_trade(trade)

        def on_error(ws, err):
            log(f"trade stream error: {err}")
            set_stream_state("error", err)

        try:
            headers = create_auth_headers("GET", WS_PATH)
            app = websocket.WebSocketApp(
                WS_URL, header=[f"{k}: {v}" for k, v in headers.items()],
                on_open=on_open, on_message=on_message,
                on_error=on_error)
            # Reconnect periodically so newly discovered markets are included.
            timer = threading.Timer(DISCOVERY_EVERY, app.close)
            timer.daemon = True
            timer.start()
            app.run_forever(ping_interval=25, ping_timeout=10)
            timer.cancel()
            set_stream_state("disconnected")
        except Exception as exc:
            log(f"trade stream connection failed: {exc}")
            set_stream_state("error", exc)
        time.sleep(5)


if __name__ == "__main__":
    run()
