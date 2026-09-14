#!/usr/bin/env python3
r"""Quarantined Kalshi capability probe.

Read-only. Answers one question: does Kalshi expose clean NFL/MLB straight
moneyline contracts that could be linked deterministically to our canonical
registries and priced from executable depth? It stops short of any arbitrage
calculation, order placement, or production integration.

Guarantees
----------
- Writes exactly one file, `sample_schema.json`, in its own directory: field
  names, counts, distributions and a handful of example rows. No bulk data.
- Never prints, logs, hashes or copies credential material. It reads the key
  id and the private key path from `.env` and the PEM from disk, and the only
  thing derived from them that ever leaves this process is a request
  signature.
- Opens the canonical registries only under `--verify-linkage`, and then only
  through SQLite `mode=ro` URIs, issuing SELECTs and writing nothing.
- Sends GET requests only, paced by MIN_INTERVAL_SECONDS.

Run:
    .\.venv\Scripts\python.exe research\kalshi\kalshi_probe.py --verify-linkage
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
OUTPUT = HERE / "sample_schema.json"
NFL_DB = PROJECT / "sports_registry_production.db"
MLB_DB = PROJECT / "mlb_research.db"

BASE = "https://external-api.kalshi.com/trade-api/v2"
API_PREFIX = "/trade-api/v2"
MIN_INTERVAL_SECONDS = 0.25

# Series carrying straight game winner contracts. Confirmed by
# product_metadata.competition_scope == "Game"; see SCOPE_GAME below.
GAME_SERIES = {"NFL": "KXNFLGAME", "MLB": "KXMLBGAME"}
SCOPE_GAME = "Game"

EASTERN = ZoneInfo("America/New_York")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}

# Kalshi team codes that differ from our canonical registry codes. Kept as an
# explicit, reviewable table: the registry rejects guessed identity, and a
# fuzzy fallback here would reintroduce exactly that.
TEAM_ALIASES = {"JAC": "JAX", "AZ": "ARI"}

# Kalshi's occurrence_datetime runs exactly this far ahead of the true
# scheduled start on every game measured. Applied as a correction, but
# asserted rather than trusted — see check_occurrence_offset.
OCCURRENCE_OFFSET = timedelta(hours=3)
KICKOFF_TOLERANCE_SECONDS = 1800   # matches nfl_config.json


class Kalshi:
    """Minimal signed GET client. Holds key material, never emits it."""

    def __init__(self) -> None:
        load_dotenv(PROJECT / ".env", override=True)
        key_id = os.getenv("KALSHI_API_KEY_ID")
        key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        if not key_id or not key_path:
            raise SystemExit(
                "KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH must be set in .env")
        # Never echo the variable's value. A common misconfiguration is pasting
        # the PEM body into .env instead of a path, and echoing it in an error
        # would print private key material to the terminal and any log capturing
        # it. Detect that case by shape and describe it without quoting it.
        # `MII` is the base64 prefix of a DER-encoded key, so a value starting
        # with it is a pasted key body even when the PEM armor was omitted.
        if ("PRIVATE KEY" in key_path or "\n" in key_path
                or len(key_path) > 260 or key_path.startswith("MII")):
            raise SystemExit(
                "KALSHI_PRIVATE_KEY_PATH appears to contain key material rather "
                "than a file path. Save the PEM to secrets/kalshi_private_key.pem "
                "and set the variable to that path.")
        pem = (PROJECT / key_path)
        if not pem.exists():
            raise SystemExit(
                "Private key file named by KALSHI_PRIVATE_KEY_PATH does not exist.")
        self._key_id = key_id
        self._key = serialization.load_pem_private_key(pem.read_bytes(), password=None)
        self._last = 0.0

    def get(self, path: str, params: dict | None = None) -> dict:
        gap = time.monotonic() - self._last
        if gap < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - gap)
        timestamp = str(int(time.time() * 1000))
        signature = self._key.sign(
            (timestamp + "GET" + API_PREFIX + path).encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
        response = requests.get(BASE + path, params=params, timeout=30, headers={
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()})
        self._last = time.monotonic()
        response.raise_for_status()
        return response.json()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def ticker_start(event_ticker: str) -> datetime | None:
    """Scheduled start encoded in the event ticker, read as US Eastern.

    MLB tickers carry a HHMM component (`KXMLBGAME-26SEP101215TBATL`) and are
    the most reliable start signal available: consecutive games in a series
    collide on a shared UTC date, so a date-only key is ambiguous. NFL tickers
    carry no time, and fall back to the corrected occurrence_datetime.
    """
    match = re.match(r"^KX(?:NFL|MLB)GAME-(\d\d)([A-Z]{3})(\d\d)(\d{4})?", event_ticker)
    if not match:
        return None
    year, month, day, hhmm = match.groups()
    if not hhmm:
        return None
    return datetime(2000 + int(year), MONTHS[month], int(day),
                    int(hhmm[:2]), int(hhmm[2:]), tzinfo=EASTERN)


def team_codes(event: dict) -> list[str]:
    """Canonical team codes for an event, from its two market tickers."""
    return [TEAM_ALIASES.get(code, code) for code in
            (market["ticker"].rsplit("-", 1)[1] for market in event.get("markets", []))]


def scheduled_start(event: dict) -> datetime | None:
    explicit = ticker_start(event["event_ticker"])
    if explicit:
        return explicit
    markets = event.get("markets") or []
    if not markets or not markets[0].get("occurrence_datetime"):
        return None
    return parse_time(markets[0]["occurrence_datetime"]) - OCCURRENCE_OFFSET


def derived_asks(yes_bid: float | None, no_bid: float | None) -> dict:
    """Executable asks derived from the bids-only book.

    Kalshi's orderbook returns resting bids on both sides and no asks. Buying
    YES means lifting the best NO bid, so YES ask = 1 - best NO bid, and
    symmetrically NO ask = 1 - best YES bid. A displayed probability is not
    this number and must never be substituted for it.
    """
    return {
        "yes_ask": None if no_bid is None else round(1.0 - no_bid, 4),
        "no_ask": None if yes_bid is None else round(1.0 - yes_bid, 4),
    }


def book_summary(orderbook: dict) -> dict:
    levels = orderbook.get("orderbook_fp") or {}
    yes = levels.get("yes_dollars") or []
    no = levels.get("no_dollars") or []
    # Levels arrive ascending by price, so the last entry is the best bid.
    best_yes = float(yes[-1][0]) if yes else None
    best_no = float(no[-1][0]) if no else None
    asks = derived_asks(best_yes, best_no)
    return {
        "yes_levels": len(yes),
        "no_levels": len(no),
        "best_yes_bid": best_yes,
        "best_no_bid": best_no,
        **asks,
        "spread": (None if best_yes is None or asks["yes_ask"] is None
                   else round(asks["yes_ask"] - best_yes, 4)),
        "top_yes_qty": float(yes[-1][1]) if yes else 0.0,
        "top_no_qty": float(no[-1][1]) if no else 0.0,
        "yes_qty_top5": round(sum(float(x[1]) for x in yes[-5:]), 2),
        "no_qty_top5": round(sum(float(x[1]) for x in no[-5:]), 2),
    }


def check_transform(market: dict, book: dict) -> str:
    """Cross-check the derived asks against the market's own quoted asks."""
    quoted_yes = market.get("yes_ask_dollars")
    quoted_no = market.get("no_ask_dollars")
    if quoted_yes is None or quoted_no is None or book["yes_ask"] is None:
        return "UNCHECKED"
    agree = (abs(float(quoted_yes) - book["yes_ask"]) < 1e-6
             and abs(float(quoted_no) - book["no_ask"]) < 1e-6)
    return "CONFIRMED" if agree else "MISMATCH"


def check_occurrence_offset(events: list[dict], rows: list[dict]) -> dict:
    """Assert the occurrence_datetime offset instead of silently relying on it.

    If Kalshi ever corrects this, a hardcoded constant would keep matching and
    start attaching markets to the wrong game. Any drift must surface loudly.
    """
    deltas = []
    for event, row in zip(events, rows):
        occurrence = (event.get("markets") or [{}])[0].get("occurrence_datetime")
        if not occurrence or not row.get("registry_start"):
            continue
        deltas.append(round(
            (parse_time(occurrence) - parse_time(row["registry_start"])).total_seconds() / 3600, 3))
    if not deltas:
        return {"status": "NO_DATA"}
    unique = sorted(set(deltas))
    expected = OCCURRENCE_OFFSET.total_seconds() / 3600
    return {
        "status": "STABLE" if unique == [expected] else "DRIFTED",
        "expected_hours": expected,
        "observed_hours": unique[:5],
        "sample": len(deltas),
    }


def load_registry(sport: str) -> list[dict]:
    database, query = ((NFL_DB, "SELECT canonical_game_id id, game_uuid, away_team_id,"
                                " home_team_id, scheduled_kickoff_utc start FROM games")
                       if sport == "NFL" else
                       (MLB_DB, "SELECT mlb_game_pk id, game_uuid, away_team_id,"
                                " home_team_id, scheduled_start_utc start FROM mlb_games"))
    if not database.exists():
        return []
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query)]


def link(event: dict, registry: list[dict]) -> dict:
    """Classify one event against the canonical registry.

    EXACT requires a single registry game with the identical canonical team
    pair whose scheduled start agrees within the project's kickoff tolerance.
    Anything else is reported, never guessed: several candidates is AMBIGUOUS,
    none is UNMATCHED. There is deliberately no title-similarity fallback.
    """
    codes = team_codes(event)
    start = scheduled_start(event)
    if len(codes) != 2 or start is None:
        return {"status": "UNMATCHED", "reason": "MISSING_TEAMS_OR_START"}
    candidates = [game for game in registry
                  if {game["away_team_id"], game["home_team_id"]} == set(codes)
                  and abs((parse_time(game["start"]) - start).total_seconds())
                  <= KICKOFF_TOLERANCE_SECONDS]
    if len(candidates) == 1:
        game = candidates[0]
        subtitle = event.get("sub_title") or ""
        order = re.match(r"([A-Z]+) vs ([A-Z]+)", subtitle)
        oriented = bool(order) and [TEAM_ALIASES.get(order.group(1), order.group(1)),
                                    TEAM_ALIASES.get(order.group(2), order.group(2))] == \
            [game["away_team_id"], game["home_team_id"]]
        return {"status": "EXACT" if oriented else "ORIENTATION_CONFLICT",
                "registry_id": str(game["id"]), "registry_start": game["start"]}
    if candidates:
        return {"status": "AMBIGUOUS", "candidates": len(candidates)}
    return {"status": "UNMATCHED", "reason": "NO_CANDIDATE_IN_TOLERANCE"}


def audit_sport(client: Kalshi, sport: str, verify: bool, books: int) -> dict:
    series = GAME_SERIES[sport]
    payload = client.get("/events", {"series_ticker": series, "status": "open",
                                     "with_nested_markets": "true", "limit": 200})
    events = payload.get("events") or []

    scoped = [e for e in events
              if (e.get("product_metadata") or {}).get("competition_scope") == SCOPE_GAME]
    registry = load_registry(sport) if verify else []

    rows, summaries, transforms = [], [], []
    for index, event in enumerate(scoped):
        row = {"event_ticker": event["event_ticker"],
               "teams": team_codes(event),
               "markets": len(event.get("markets") or []),
               "mutually_exclusive": event.get("mutually_exclusive")}
        row.update(link(event, registry) if registry else {"status": "NOT_VERIFIED"})
        if index < books and event.get("markets"):
            market = event["markets"][0]
            book = book_summary(client.get(
                f"/markets/{market['ticker']}/orderbook", {"depth": 20}))
            row["book"] = book
            row["transform_check"] = check_transform(market, book)
            summaries.append(book)
            transforms.append(row["transform_check"])
        rows.append(row)

    spreads = [b["spread"] for b in summaries if b["spread"] is not None]
    quantities = [b["top_no_qty"] for b in summaries if b["top_no_qty"]]
    statuses: dict[str, int] = {}
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1

    return {
        "series_ticker": series,
        "events_returned": len(events),
        "events_scope_game": len(scoped),
        "excluded_non_game": len(events) - len(scoped),
        "link_status_counts": statuses,
        "occurrence_offset": check_occurrence_offset(scoped, rows) if registry else {"status": "NOT_VERIFIED"},
        "books_sampled": len(summaries),
        "books_two_sided": sum(1 for b in summaries if b["yes_levels"] and b["no_levels"]),
        "transform_checks": {v: transforms.count(v) for v in set(transforms)},
        "spread": ({"min": min(spreads), "median": statistics.median(spreads),
                    "max": max(spreads)} if spreads else None),
        "top_level_quantity": ({"min": min(quantities),
                                "median": statistics.median(quantities),
                                "max": max(quantities)} if quantities else None),
        "examples": rows[:3],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantined Kalshi audit probe.")
    parser.add_argument("--sport", choices=("nfl", "mlb", "both"), default="both")
    parser.add_argument("--books", type=int, default=12,
                        help="order books to fetch per sport (default: 12)")
    parser.add_argument("--verify-linkage", action="store_true",
                        help="read-only canonical registry join")
    args = parser.parse_args()

    client = Kalshi()
    sports = ["NFL", "MLB"] if args.sport == "both" else [args.sport.upper()]

    findings = {
        "probed_at": datetime.now().astimezone().isoformat(),
        "base_url": BASE,
        "team_aliases": TEAM_ALIASES,
        "occurrence_offset_hours": OCCURRENCE_OFFSET.total_seconds() / 3600,
        "sports": {},
    }
    for sport in sports:
        result = audit_sport(client, sport, args.verify_linkage, args.books)
        findings["sports"][sport] = result
        print(f"  [{sport}] {result['events_scope_game']} scope=Game events, "
              f"{result['books_sampled']} books, "
              f"links={result['link_status_counts']}, "
              f"transform={result['transform_checks']}, "
              f"offset={result['occurrence_offset']['status']}")

    OUTPUT.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT.name} ({OUTPUT.stat().st_size / 1024:.1f} KB) — "
          "schema and aggregates only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
