#!/usr/bin/env python3
"""Permanent, append-only journals of every observed trade on Polymarket US.

Instrumentation only. It records what the trade stream reports and nothing
more: no analysis, no signals, no edge logic. Each journaled league has its own
database, table and coverage start:

    league  database               table
    nfl     nfl_trade_journal.db   nfl_trade_observations
    mlb     mlb_trade_journal.db   mlb_full_flow_observations

MLB full-flow capture is a separate coverage regime from the older buy-only MLB
journal, mlb_research.db table mlb_trade_observations. That journal records
taker BUY_LONG / BUY_SHORT moneyline executions at or above the display
threshold and nothing else: no sells, no ORDER_INTENT_UNDEFINED trades, no run
lines or totals. This module never reads or writes it, and it keeps recording
exactly as before. The MLB full-flow table is deliberately not named
mlb_trade_observations, so the two regimes cannot be confused or silently
combined.

These journals mirror that MLB journal — an append-only table whose UPDATE and
DELETE are blocked by triggers, idempotent inserts, WAL — with three deliberate
differences.

Every trade, not a subset.
    big_money_tape feeds these journals ahead of its display filters, so they
    record every trade the stream delivers — sells included, whatever the
    market type. Measuring what trading does after a large trade needs the
    whole tape, not the buys.

Deduplication on the exchange's trade id.
    The MLB journal dedupes on a key derived from market, timestamp, quantity,
    price and intent. The exchange emits bursts of fills sharing a single
    nanosecond timestamp — 6,975 such bursts in the first 63,571 MLB trades —
    so two equal-size fills at one price inside a burst would derive the same
    key and the second would be discarded. The exchange id was present, and
    unique, on all 63,571 of those rows. The derived key is still stored, for
    audit and for joining against the tape and the MLB journal.

No canonical-game resolution at write time.
    Rows carry the Polymarket US event and market slugs. Linking them to a
    canonical game happens at analysis time, so registry locks or schema
    changes can never stall or break capture.

Each league's coverage begins at its own `coverage_started_at` in journal_meta,
written once, when that league's first capture session starts. Nothing earlier
is backfilled: the dashboard tape prunes itself to five rows per event and is
not a record of what traded. Every capture start appends a row to
capture_sessions, stamped with the raw-field allowlist in force, so outages and
field coverage show up explicitly.

Fail-safe: big_money_tape calls `journal_trade`, which never raises. A broken
journal costs journal rows — never display rows, the buy-only MLB journal, or
the stream.

    python trade_journal.py status               # every league
    python trade_journal.py status --league mlb
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
SCHEMA_VERSION = 1
TRADE_NAMESPACE = uuid.UUID("5c1f2e4a-9b7d-4f3a-8e21-6d0b7a9c4e15")

NFL_COVERAGE_NOTE = (
    "NFL permanent trade history begins at coverage_started_at. Nothing earlier "
    "was backfilled: the dashboard tape prunes itself to five rows per event and "
    "is not a record of what traded. Intervals between capture sessions with no "
    "running stream are gaps, not quiet markets.")

MLB_COVERAGE_NOTE = (
    "MLB full-flow trade history begins at coverage_started_at. Earlier MLB trades "
    "exist only in mlb_research.db (table mlb_trade_observations), which recorded "
    "taker BUY_LONG / BUY_SHORT moneyline executions at or above the display "
    "threshold and never recorded sells, ORDER_INTENT_UNDEFINED trades, run lines "
    "or totals. That is a different coverage regime: do not combine it with this "
    "table as if either were complete. Nothing earlier was backfilled. Intervals "
    "between capture sessions with no running stream are gaps, not quiet markets.")


@dataclass(frozen=True)
class LeagueJournal:
    league: str
    table: str
    index_prefix: str
    default_db: Path
    coverage_note: str


# The NFL names are those of the journal that went live first; they must not
# change, or the existing database would grow a second, empty table.
LEAGUE_JOURNALS = {
    "nfl": LeagueJournal("nfl", "nfl_trade_observations", "nfl_trades",
                         HERE / "nfl_trade_journal.db", NFL_COVERAGE_NOTE),
    "mlb": LeagueJournal("mlb", "mlb_full_flow_observations", "mlb_full_flow",
                         HERE / "mlb_trade_journal.db", MLB_COVERAGE_NOTE),
}

INTENTS = {
    "ORDER_INTENT_BUY_LONG": ("BUY", "LONG"),
    "ORDER_INTENT_BUY_SHORT": ("BUY", "SHORT"),
    "ORDER_INTENT_SELL_LONG": ("SELL", "LONG"),
    "ORDER_INTENT_SELL_SHORT": ("SELL", "SHORT"),
}

# Source fields stored verbatim. Any other field the feed sends is recorded by
# key path only (raw_key_paths_json), never by value, so an unexpected field
# cannot put unvetted values into a table that can never be edited.
#
# Version 2 adds the remaining trade attributes seen on the live feed. Polymarket
# US documents `side` (ORDER_SIDE_BUY / ORDER_SIDE_SELL) and states that trade
# messages carry no participant identifiers. `action`, `outcomeSide` and
# `state` are undocumented trade attributes; they are kept because the feed
# also sends ORDER_INTENT_UNDEFINED, and `side` may be the only direction such
# a trade carries. They are stored as sent and not reinterpreted here.
RAW_FIELD_ALLOWLIST_VERSION = 2
RAW_FIELD_ALLOWLIST = ("id", "tradeId", "marketSlug", "market_slug", "price",
                       "quantity", "tradeTime", "trade_time", "state",
                       "taker.intent", "taker.side", "taker.action", "taker.outcomeSide",
                       "maker.intent", "maker.side", "maker.action", "maker.outcomeSide")

ERROR_REPORT_INTERVAL_SECONDS = 60
STATS_LOG_INTERVAL_SECONDS = 15 * 60

SCHEMA_TEMPLATE = """
CREATE TABLE IF NOT EXISTS journal_meta(
  key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS capture_sessions(
  session_uuid TEXT PRIMARY KEY, started_at TEXT NOT NULL,
  process_id INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS __TABLE__(
  observation_uuid TEXT PRIMARY KEY,
  dedupe_key TEXT NOT NULL UNIQUE,
  websocket_trade_id TEXT,
  derived_trade_key TEXT NOT NULL,
  capture_session_uuid TEXT,
  event_slug TEXT NOT NULL,
  market_slug TEXT NOT NULL,
  market_type TEXT NOT NULL,
  event_title TEXT,
  question TEXT,
  long_label TEXT,
  short_label TEXT,
  taker_intent TEXT NOT NULL,
  taker_direction TEXT NOT NULL CHECK(taker_direction IN ('BUY','SELL','UNKNOWN')),
  instrument_side TEXT NOT NULL CHECK(instrument_side IN ('LONG','SHORT','UNKNOWN')),
  outcome_label TEXT,
  instrument_price REAL,
  outcome_price REAL,
  contracts REAL,
  notional_usd REAL,
  trade_timestamp_utc TEXT NOT NULL,
  ingestion_timestamp TEXT NOT NULL,
  source_market_start_time TEXT,
  pregame_classification TEXT NOT NULL
    CHECK(pregame_classification IN ('PREGAME','IN_GAME','UNKNOWN')),
  start_time_evidence TEXT,
  raw_fields_json TEXT NOT NULL,
  raw_key_paths_json TEXT NOT NULL,
  source_quality_flags_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS __PREFIX___market_time
  ON __TABLE__(market_slug, trade_timestamp_utc);
CREATE INDEX IF NOT EXISTS __PREFIX___event_time
  ON __TABLE__(event_slug, trade_timestamp_utc);
CREATE INDEX IF NOT EXISTS __PREFIX___derived_key
  ON __TABLE__(derived_trade_key);
CREATE TRIGGER IF NOT EXISTS __TABLE___no_update
  BEFORE UPDATE ON __TABLE__
  BEGIN SELECT RAISE(ABORT, '__LABEL__ trade observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS __TABLE___no_delete
  BEFORE DELETE ON __TABLE__
  BEGIN SELECT RAISE(ABORT, '__LABEL__ trade observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS capture_sessions_no_update
  BEFORE UPDATE ON capture_sessions
  BEGIN SELECT RAISE(ABORT, 'capture sessions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS capture_sessions_no_delete
  BEFORE DELETE ON capture_sessions
  BEGIN SELECT RAISE(ABORT, 'capture sessions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS journal_meta_coverage_no_update
  BEFORE UPDATE ON journal_meta
  WHEN OLD.key IN ('coverage_started_at', 'coverage_note', 'league')
  BEGIN SELECT RAISE(ABORT, 'coverage markers are immutable'); END;
CREATE TRIGGER IF NOT EXISTS journal_meta_coverage_no_delete
  BEFORE DELETE ON journal_meta
  WHEN OLD.key IN ('coverage_started_at', 'coverage_note', 'league')
  BEGIN SELECT RAISE(ABORT, 'coverage markers are immutable'); END;
"""


def spec_for(league: str) -> LeagueJournal:
    try:
        return LEAGUE_JOURNALS[str(league).lower()]
    except KeyError:
        raise ValueError(f"no trade journal is configured for league {league!r}") from None


def schema_for(spec: LeagueJournal) -> str:
    return (SCHEMA_TEMPLATE.replace("__TABLE__", spec.table)
            .replace("__PREFIX__", spec.index_prefix)
            .replace("__LABEL__", spec.league.upper()))


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3's context manager, then always close."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def stable_uuid(league: str, value: str) -> str:
    return str(uuid.uuid5(TRADE_NAMESPACE, f"{league}-trade:{value}"))


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def derived_trade_key(slug: str, trade_time: str, contracts: float,
                      instrument_price: float, intent: str) -> str:
    """The tape's display id. Must stay identical to big_money_tape.record_trade."""
    raw_id = f"{slug}|{trade_time}|{contracts:.4f}|{instrument_price:.6f}|{intent}"
    return hashlib.sha256(raw_id.encode()).hexdigest()[:24]


_MISSING = object()


def _lookup(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def key_paths(obj: Any, prefix: str = "") -> list[str]:
    """Every key path in a payload, names only: `taker`, `taker.intent`, ..."""
    paths: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.append(path)
            paths.extend(key_paths(value, path))
    elif isinstance(obj, list):
        for item in obj:
            paths.extend(key_paths(item, f"{prefix}[]"))
    return paths


def build_observation(league: str, trade: dict, meta: dict,
                      session_uuid: str | None, ingested_at: str) -> dict:
    """One journal row. Records the trade as reported; judges nothing about it.

    `outcome_price` follows big_money_tape's convention that the feed's `price`
    is quoted on the LONG instrument, so a SHORT-side trade transacts at
    1 - price. The raw price is kept verbatim in case that convention is wrong.
    """
    flags: list[str] = []
    slug = str(trade.get("marketSlug") or trade.get("market_slug")
               or meta.get("market_slug") or "")
    event_slug = str(meta.get("event_slug") or "")
    if not slug:
        flags.append("MARKET_SLUG_MISSING")
    if not event_slug:
        flags.append("EVENT_SLUG_MISSING")

    intent = str((trade.get("taker") or {}).get("intent") or "")
    direction, side = INTENTS.get(intent, ("UNKNOWN", "UNKNOWN"))
    if direction == "UNKNOWN":
        flags.append("UNRECOGNIZED_INTENT")

    price = _number(trade.get("price"))
    contracts = _number(trade.get("quantity"))
    price_valid = price is not None and 0.0 < price < 1.0
    if not price_valid:
        flags.append("PRICE_NOT_STRICTLY_BETWEEN_0_AND_1")
    if contracts is None or contracts <= 0:
        flags.append("QUANTITY_NOT_POSITIVE")

    trade_time = trade.get("tradeTime") or trade.get("trade_time")
    if not trade_time:
        trade_time = ingested_at
        flags.append("TRADE_TIME_MISSING_INGESTION_TIME_USED")
    trade_time = str(trade_time)

    exchange_id = trade.get("id") or trade.get("tradeId")
    exchange_id = str(exchange_id) if exchange_id not in (None, "") else None
    derived = derived_trade_key(slug, trade_time, contracts or 0.0, price or 0.0, intent)
    if exchange_id:
        dedupe_key = f"ws:{exchange_id}"
    else:
        dedupe_key = f"derived:{derived}"
        flags.append("NO_EXCHANGE_TRADE_ID")

    outcome_price = None
    if price_valid and side in ("LONG", "SHORT"):
        outcome_price = price if side == "LONG" else 1.0 - price
    notional = (round(contracts * outcome_price, 6)
                if outcome_price is not None and contracts and contracts > 0 else None)
    outcome_label = (meta.get("long_label") if side == "LONG"
                     else meta.get("short_label") if side == "SHORT" else None)

    start = meta.get("source_start_time")
    trade_at, start_at = parse_time(trade_time), parse_time(start)
    if trade_at and start_at:
        classification = "PREGAME" if trade_at < start_at else "IN_GAME"
    else:
        classification = "UNKNOWN"

    raw = {}
    for path in RAW_FIELD_ALLOWLIST:
        value = _lookup(trade, path)
        if value is not _MISSING:
            raw[path] = value

    return {
        "observation_uuid": stable_uuid(league, dedupe_key),
        "dedupe_key": dedupe_key,
        "websocket_trade_id": exchange_id,
        "derived_trade_key": derived,
        "capture_session_uuid": session_uuid,
        "event_slug": event_slug,
        "market_slug": slug,
        "market_type": str(meta.get("market_type") or "unknown"),
        "event_title": meta.get("event_title"),
        "question": meta.get("question"),
        "long_label": meta.get("long_label"),
        "short_label": meta.get("short_label"),
        "taker_intent": intent or "MISSING",
        "taker_direction": direction,
        "instrument_side": side,
        "outcome_label": outcome_label,
        "instrument_price": price,
        "outcome_price": outcome_price,
        "contracts": contracts,
        "notional_usd": notional,
        "trade_timestamp_utc": trade_time,
        "ingestion_timestamp": ingested_at,
        "source_market_start_time": start,
        "pregame_classification": classification,
        "start_time_evidence": "POLYMARKET_US_EVENT_START" if start else None,
        "raw_fields_json": json.dumps(raw, sort_keys=True, default=str),
        "raw_key_paths_json": json.dumps(sorted(set(key_paths(trade)))),
        "source_quality_flags_json": json.dumps(sorted(set(flags))),
    }


class TradeJournal:
    """Append-only store for one league. Every write is idempotent on dedupe_key."""

    def __init__(self, league: str, db_path: Path | str | None = None):
        self.spec = spec_for(league)
        self.league = self.spec.league
        self.db_path = Path(db_path) if db_path else self.spec.default_db
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        # Only the stream thread writes, so lock waits should be nil; the short
        # timeout bounds the worst case so capture can never stall the stream.
        db = sqlite3.connect(self.db_path, timeout=5, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(schema_for(self.spec))
            db.execute("INSERT OR REPLACE INTO journal_meta VALUES('schema_version', ?)",
                       (str(SCHEMA_VERSION),))
            db.execute("INSERT OR REPLACE INTO journal_meta VALUES('raw_field_allowlist', ?)",
                       (json.dumps({"version": RAW_FIELD_ALLOWLIST_VERSION,
                                    "fields": list(RAW_FIELD_ALLOWLIST)}),))
            db.execute("INSERT OR IGNORE INTO journal_meta VALUES('league', ?)", (self.league,))

    def start_session(self, note: str | None = None) -> str:
        session_uuid = str(uuid.uuid4())
        started_at = utc_now()
        with self.connect() as db:
            # The allowlist in force is stamped on the immutable session row, so each
            # observation's raw-field coverage is recoverable from its session.
            stamped = f"{note or 'capture'} [raw field allowlist v{RAW_FIELD_ALLOWLIST_VERSION}]"
            db.execute("INSERT INTO capture_sessions VALUES(?,?,?,?)",
                       (session_uuid, started_at, os.getpid(), stamped))
            db.execute("INSERT OR IGNORE INTO journal_meta VALUES('coverage_started_at', ?)",
                       (started_at,))
            db.execute("INSERT OR IGNORE INTO journal_meta VALUES('coverage_note', ?)",
                       (self.spec.coverage_note,))
        return session_uuid

    def record(self, trade: dict, meta: dict, session_uuid: str | None = None) -> bool:
        """Append one trade. True if written, False if already journaled."""
        row = build_observation(self.league, trade, meta, session_uuid, utc_now())
        columns = ",".join(row)
        marks = ",".join("?" for _ in row)
        with self.connect() as db:
            before = db.total_changes
            db.execute(f"INSERT OR IGNORE INTO {self.spec.table}({columns}) "
                       f"VALUES({marks})", tuple(row.values()))
            return db.total_changes > before


# --- Fail-safe entry points for the stream ------------------------------------

_lock = threading.Lock()
_journals: dict[str, TradeJournal] = {}
_sessions: dict[str, str] = {}
_stats: dict[str, dict[str, int]] = {}
_last_error_report: dict[str, float] = {}
_last_stats_log: dict[str, float] = {}


def _journal(league: str, path: Path | str) -> TradeJournal:
    key = str(Path(path))
    with _lock:
        existing = _journals.get(key)
    if existing is not None:
        if existing.league != spec_for(league).league:
            raise ValueError(f"{key} is the {existing.league} journal, not {league}")
        return existing
    created = TradeJournal(league, path)
    with _lock:
        return _journals.setdefault(key, created)


def _safe_call(callback: Callable[[str], Any] | None, message: str) -> None:
    if callback is None:
        return
    try:
        callback(message)
    except Exception:
        pass


def stats(league: str | None = None) -> dict:
    with _lock:
        if league is not None:
            return dict(_stats.get(league, {"inserted": 0, "duplicate": 0, "failed": 0}))
        return {name: dict(values) for name, values in _stats.items()}


def stats_line(league: str) -> str:
    current = stats(league)
    return (f"{current['inserted']} new, {current['duplicate']} duplicate, "
            f"{current['failed']} failed since process start")


def _count(league: str, outcome: str) -> None:
    with _lock:
        _stats.setdefault(league, {"inserted": 0, "duplicate": 0, "failed": 0})[outcome] += 1


def start_capture_session(league: str, path: Path | str, note: str | None = None,
                          on_error: Callable[[str], Any] | None = None) -> str | None:
    """Record that capture is live for one league. Never raises; None means it failed."""
    label = str(league).upper()
    try:
        session = _journal(league, path).start_session(note)
    except Exception as exc:
        _safe_call(on_error, f"{label} trade journal could not start a capture session: {exc}")
        return None
    with _lock:
        _sessions[str(Path(path))] = session
        _last_stats_log[league] = time.monotonic()
    return session


def journal_trade(league: str, path: Path | str, trade: dict, meta: dict,
                  on_error: Callable[[str], Any] | None = None,
                  on_stats: Callable[[str], Any] | None = None) -> bool | None:
    """Append one observed trade to its league's journal. Never raises.

    Returns True when a new row was written, False when the trade was already
    journaled, and None when the journal failed — in which case the caller
    carries on exactly as it would if the journal did not exist.
    """
    label = str(league).upper()
    try:
        with _lock:
            session = _sessions.get(str(Path(path)))
        if session is None:
            session = start_capture_session(
                league, path, note="started by first observed trade", on_error=on_error)
        inserted = _journal(league, path).record(trade, meta, session)
        _count(league, "inserted" if inserted else "duplicate")
    except Exception as exc:
        try:
            _count(league, "failed")
            now = time.monotonic()
            with _lock:
                due = now - _last_error_report.get(league, float("-inf")) >= ERROR_REPORT_INTERVAL_SECONDS
                if due:
                    _last_error_report[league] = now
            if due:
                _safe_call(on_error, f"{label} trade journal write failed: {exc}")
        except Exception:
            pass
        return None
    try:
        now = time.monotonic()
        with _lock:
            last = _last_stats_log.get(league)
            due = last is not None and now - last >= STATS_LOG_INTERVAL_SECONDS
            if due:
                _last_stats_log[league] = now
        if due:
            _safe_call(on_stats, f"{label} trade journal: {stats_line(league)}")
    except Exception:
        pass
    return inserted


def _reset_for_tests() -> None:
    with _lock:
        _journals.clear()
        _sessions.clear()
        _stats.clear()
        _last_error_report.clear()
        _last_stats_log.clear()


# --- Read-only status -----------------------------------------------------------

def _open_read_only(path: Path) -> sqlite3.Connection:
    try:
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                               timeout=5, factory=ClosingConnection)
    except sqlite3.OperationalError:
        return sqlite3.connect(path, timeout=5, factory=ClosingConnection)


def read_status(league: str, path: Path | str | None = None) -> dict:
    """Coverage and integrity counts for one league. Never creates or writes a database."""
    spec = spec_for(league)
    path = Path(path) if path else spec.default_db
    if not path.exists():
        return {"league": spec.league, "database": str(path), "started": False}
    table = spec.table
    with _open_read_only(path) as db:
        def one(sql: str) -> Any:
            return db.execute(sql).fetchone()[0]

        def grouped(sql: str) -> dict:
            return {str(key): value for key, value in db.execute(sql).fetchall()}

        meta = grouped("SELECT key, value FROM journal_meta")
        session_starts = [row[0] for row in db.execute(
            "SELECT started_at FROM capture_sessions ORDER BY started_at")]
        flags: dict[str, int] = {}
        for (value,) in db.execute(f"SELECT source_quality_flags_json FROM {table} "
                                   "WHERE source_quality_flags_json <> '[]'"):
            for flag in json.loads(value):
                flags[flag] = flags.get(flag, 0) + 1
        paths: set[str] = set()
        for (value,) in db.execute(f"SELECT raw_key_paths_json FROM {table} "
                                   "ORDER BY rowid DESC LIMIT 1000"):
            paths.update(json.loads(value))
        return {
            "league": spec.league,
            "database": str(path),
            "table": table,
            "started": True,
            "schema_version": meta.get("schema_version"),
            "coverage_started_at": meta.get("coverage_started_at"),
            "coverage_note": meta.get("coverage_note"),
            "raw_field_allowlist": (json.loads(meta["raw_field_allowlist"])
                                    if meta.get("raw_field_allowlist") else None),
            "capture_sessions": len(session_starts),
            "recent_session_starts": session_starts[-10:],
            "observations": one(f"SELECT COUNT(*) FROM {table}"),
            "with_exchange_trade_id": one(f"SELECT COUNT(websocket_trade_id) FROM {table}"),
            "distinct_exchange_trade_ids": one(
                f"SELECT COUNT(DISTINCT websocket_trade_id) FROM {table}"),
            "first_trade_utc": one(f"SELECT MIN(trade_timestamp_utc) FROM {table}"),
            "last_trade_utc": one(f"SELECT MAX(trade_timestamp_utc) FROM {table}"),
            "distinct_markets": one(f"SELECT COUNT(DISTINCT market_slug) FROM {table}"),
            "distinct_events": one(f"SELECT COUNT(DISTINCT event_slug) FROM {table}"),
            "by_market_type": grouped(f"SELECT market_type, COUNT(*) FROM {table} GROUP BY 1"),
            "by_taker_intent": grouped(f"SELECT taker_intent, COUNT(*) FROM {table} GROUP BY 1"),
            "by_pregame_classification": grouped(
                f"SELECT pregame_classification, COUNT(*) FROM {table} GROUP BY 1"),
            # Fills that a derived-key dedupe would have merged into one row.
            "derived_keys_shared_by_distinct_trades": one(
                f"SELECT COUNT(*) FROM (SELECT derived_trade_key FROM {table} "
                "GROUP BY 1 HAVING COUNT(*) > 1)"),
            "rows_sharing_a_derived_key": one(
                f"SELECT COALESCE(SUM(c), 0) FROM (SELECT COUNT(*) c FROM {table} "
                "GROUP BY derived_trade_key HAVING c > 1)"),
            "quality_flags": flags,
            "raw_key_paths_seen_recently": sorted(paths),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Permanent per-league trade journals.")
    parser.add_argument("command", choices=("status",))
    parser.add_argument("--league", choices=(*LEAGUE_JOURNALS, "all"), default="all")
    parser.add_argument("--db", help="database path; only with a single --league")
    args = parser.parse_args(argv)
    if args.league == "all":
        if args.db:
            parser.error("--db needs a single --league")
        print(json.dumps({name: read_status(name) for name in LEAGUE_JOURNALS}, indent=2))
    else:
        print(json.dumps(read_status(args.league, args.db), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
