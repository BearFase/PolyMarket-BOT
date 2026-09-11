#!/usr/bin/env python3
r"""Net executable edge between Polymarket US and Kalshi. Read-only.

Answers one question: after fees, do executable cross-venue arbitrage
opportunities exist on matched NFL moneylines? It computes costs and prints
findings. It places no orders, simulates no fills, and writes no state beyond
its own JSON summary.

Two price-reading hazards it exists to encode
---------------------------------------------
Kalshi's book is bids-only, so executable asks are derived:
    YES ask = 1 - best NO bid

Polymarket US publishes `outcomePrices` for a moneyline as
`[bestBidQuote, bestAskQuote]` of a SINGLE side, while `outcomes` carries two
team names. The labels do not track the prices. Reading `outcomePrices[1]` as
the second team's price is wrong by roughly 35 cents at the median and
manufactures enormous fictional edges. The other side is derived as
`1 - price`, never read from the API.

Run:
    .\.venv\Scripts\python.exe research\kalshi\arb_economics_probe.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from datetime import timedelta
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
OUTPUT = HERE / "economics_sample.json"
sys.path.insert(0, str(HERE))

from kalshi_probe import (  # noqa: E402
    Kalshi, TEAM_ALIASES, parse_time, ticker_start, KICKOFF_TOLERANCE_SECONDS,
    OCCURRENCE_OFFSET, SCOPE_GAME)

POLY_EVENTS = "https://gateway.polymarket.us/v1/events"

# From Kalshi's /series/fee_changes endpoint: KXNFLGAME is
# `quadratic_with_maker_fees` at multiplier 1.0 (KXMLBGAME is 0.5). The base
# constant of the quadratic is NOT published in the API and the fee schedule
# PDF was unreachable, so it stays a swept parameter rather than a guess.
KALSHI_FEE_MULTIPLIER = {"KXNFLGAME": 1.0, "KXMLBGAME": 0.5}
BASE_SWEEP = (0.0, 0.035, 0.07, 0.10)

# Polymarket US publishes `feeCoefficient` on the market. Its exact semantics
# are unconfirmed; applied here on the same expected-earnings shape and
# reported separately so a correction changes one term, not the conclusion.
POLY_FEE_SHAPE = "coefficient * contracts * price * (1 - price)"


def kalshi_fee(contracts: float, price: float, base: float, multiplier: float) -> float:
    """Quadratic fee, rounded up to $0.000001 per Kalshi's fee_rounding doc."""
    raw = base * multiplier * contracts * price * (1.0 - price)
    return -(-raw * 1_000_000 // 1) / 1_000_000


def poly_fee(contracts: float, price: float, coefficient: float) -> float:
    return coefficient * contracts * price * (1.0 - price)


def registry_games() -> list[dict]:
    database = PROJECT / "sports_registry_production.db"
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT canonical_game_id id, away_team_id, home_team_id,"
            " scheduled_kickoff_utc start FROM games")]


def kalshi_games(client: Kalshi) -> list[dict]:
    payload = client.get("/events", {"series_ticker": "KXNFLGAME", "status": "open",
                                     "with_nested_markets": "true", "limit": 200})
    games = []
    for event in payload.get("events", []):
        if (event.get("product_metadata") or {}).get("competition_scope") != SCOPE_GAME:
            continue
        start = ticker_start(event["event_ticker"])
        if start is None:
            start = parse_time(event["markets"][0]["occurrence_datetime"]) - OCCURRENCE_OFFSET
        codes = [TEAM_ALIASES.get(m["ticker"].rsplit("-", 1)[1], m["ticker"].rsplit("-", 1)[1])
                 for m in event["markets"]]
        games.append({"event": event, "start": start, "codes": codes})
    return games


def poly_markets() -> dict:
    response = requests.get(POLY_EVENTS, params={
        "tagSlug": "nfl", "limit": 500,
        "startTimeMin": "2026-09-01T00:00:00Z",
        "startTimeMax": "2026-10-15T00:00:00Z"}, timeout=30)
    response.raise_for_status()
    out = {}
    for event in response.json().get("events", []):
        moneylines = [m for m in event.get("markets", [])
                      if str(m.get("marketType", "")).lower() == "moneyline"]
        if moneylines:
            out[event["slug"]] = moneylines[0]
    return out


def build_rows(client: Kalshi) -> list[dict]:
    games, kalshi, poly = registry_games(), kalshi_games(client), poly_markets()
    rows = []
    for entry in kalshi:
        matches = [g for g in games
                   if {g["away_team_id"], g["home_team_id"]} == set(entry["codes"])
                   and abs((parse_time(g["start"]) - entry["start"]).total_seconds())
                   <= KICKOFF_TOLERANCE_SECONDS]
        if len(matches) != 1:
            continue
        game = matches[0]
        away, home = game["away_team_id"], game["home_team_id"]
        market = poly.get(f"nfl-{away.lower()}-{home.lower()}-{entry['start'].date()}")
        if not market:
            continue

        asks = {}
        for m in entry["event"]["markets"]:
            code = TEAM_ALIASES.get(m["ticker"].rsplit("-", 1)[1], m["ticker"].rsplit("-", 1)[1])
            if m.get("yes_ask_dollars") is not None:
                asks[code] = float(m["yes_ask_dollars"])
        prices = json.loads(market.get("outcomePrices") or "[]")
        if len(asks) != 2 or len(prices) != 2:
            continue
        poly_bid, poly_ask = float(prices[0]), float(prices[1])

        # Direction A: buy Polymarket's quoted side at its ask, hedge the other
        # side on Kalshi. Direction B: buy the unquoted Polymarket side, derived
        # as 1 - bid, and hedge on Kalshi.
        a_cost = round(poly_ask + asks[home], 4)
        b_cost = round((1.0 - poly_bid) + asks[away], 4)
        best, legs = ((a_cost, (poly_ask, asks[home])) if a_cost <= b_cost
                      else (b_cost, (1.0 - poly_bid, asks[away])))
        rows.append({
            "game": game["id"], "away": away, "home": home,
            "poly_bid": poly_bid, "poly_ask": poly_ask,
            "poly_labels": json.loads(market.get("outcomes") or "[]"),
            "poly_fee_coefficient": market.get("feeCoefficient"),
            "kalshi_away_ask": asks[away], "kalshi_home_ask": asks[home],
            "cost_direction_a": a_cost, "cost_direction_b": b_cost,
            "best_cost": best, "gross_edge": round(1.0 - best, 4),
            "poly_leg_price": round(legs[0], 4), "kalshi_leg_price": round(legs[1], 4),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-venue net edge probe.")
    parser.add_argument("--json", action="store_true", help="write economics_sample.json")
    args = parser.parse_args()

    rows = build_rows(Kalshi())
    if not rows:
        print("  no games quoted on both venues")
        return 1

    costs = [r["best_cost"] for r in rows]
    below = [r for r in rows if r["best_cost"] < 1.0]
    print(f"=== matched NFL games quoted on both venues: {len(rows)} ===\n")
    print("  GROSS cost of the complete outcome, before any fee")
    print(f"    min {min(costs):.4f}   median {statistics.median(costs):.4f}   max {max(costs):.4f}")
    print(f"    games below $1.00 : {len(below)}/{len(rows)}")
    for r in sorted(rows, key=lambda x: x["best_cost"])[:3]:
        print(f"      {r['game']:26} cost {r['best_cost']:.4f}  gross edge {r['gross_edge']*100:+.2f}c")

    multiplier = KALSHI_FEE_MULTIPLIER["KXNFLGAME"]
    coefficient = float(rows[0]["poly_fee_coefficient"] or 0.0)
    print(f"\n  NET after fees  (Kalshi multiplier {multiplier}, "
          f"Polymarket coefficient {coefficient})")
    print(f"    {'kalshi base':>12} {'median friction':>16} {'games net > 0':>15}")
    for base in BASE_SWEEP:
        frictions, winners = [], 0
        for r in rows:
            friction = (kalshi_fee(1, r["kalshi_leg_price"], base, multiplier)
                        + poly_fee(1, r["poly_leg_price"], coefficient))
            frictions.append(friction)
            if r["gross_edge"] - friction > 0:
                winners += 1
        print(f"    {base:>12.3f} {statistics.median(frictions):>16.5f} {winners:>15}")

    print("\n  Break-even gross edge required, at median leg prices")
    for base in BASE_SWEEP[1:]:
        need = statistics.median([
            kalshi_fee(1, r["kalshi_leg_price"], base, multiplier)
            + poly_fee(1, r["poly_leg_price"], coefficient) for r in rows])
        print(f"    base {base:.3f} -> {need*100:.2f} cents per contract")

    best = max(rows, key=lambda x: x["gross_edge"])
    print(f"\n  Best observed gross edge: {best['gross_edge']*100:+.2f}c on {best['game']}")
    print("  Polymarket US publishes no order-book depth, so the Polymarket leg")
    print("  cannot be sized from the API at any price level.")

    if args.json:
        OUTPUT.write_text(json.dumps(
            {"rows": rows, "kalshi_fee_multiplier": multiplier,
             "poly_fee_shape": POLY_FEE_SHAPE,
             "kalshi_base_constant": "UNRESOLVED"}, indent=2), encoding="utf-8")
        print(f"\n  wrote {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
