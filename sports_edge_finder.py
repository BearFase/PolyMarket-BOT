#!/usr/bin/env python3
"""Canonical NFL edge scanner.

The retired scanner matched free-form event titles directly.  This replacement
never performs event matching: it calculates an observation only when accepted
Odds API and Polymarket US links already reference the same canonical NFL game
UUID in the selected registry.  It is research-only and never opens an order or
paper position.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nfl_schedule import NFLRegistry, registry_path

HERE = Path(__file__).resolve().parent
OUTPUT_PATH = HERE / "sports_edges.json"
SCANNER_VERSION = 2


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _fresh(value: str | None, now: datetime, max_age_seconds: int) -> bool:
    timestamp = _parse_time(value)
    return bool(timestamp and 0 <= (now - timestamp).total_seconds() <= max_age_seconds)


def _team_prices(registry: NFLRegistry, values: dict[str, Any]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for outcome in values.get("outcomes", []):
        team_id, error = registry.normalize_team(outcome.get("team"))
        try:
            price = float(outcome.get("price"))
        except (TypeError, ValueError):
            continue
        if not error and team_id and 0 < price < 1:
            prices[team_id] = price
    return prices


def calculate_edges(registry: NFLRegistry, *, now: datetime | None = None) -> dict[str, Any]:
    """Build edge observations exclusively from same-UUID accepted source links."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    config = registry.config
    max_age = int(config.get("sportsbook_quote_max_age_seconds", 3600))
    minimum_points = float(config.get("nfl_edge_minimum_percentage_points", 3.0))

    with registry.connect() as db:
        rows = db.execute("""
          SELECT g.game_uuid,g.canonical_game_id,g.away_team_id,g.home_team_id,
                 g.away_team_name,g.home_team_name,g.scheduled_kickoff_utc,
                 o.source_event_id AS odds_event_id,o.last_observed AS odds_observed,
                 o.source_values_json AS odds_values,
                 p.source_event_id AS polymarket_event_id,
                 p.source_market_id AS polymarket_market_id,
                 p.source_condition_id AS polymarket_condition_id,
                 p.event_slug,p.market_slug,p.last_observed AS polymarket_observed,
                 p.source_values_json AS polymarket_values
          FROM games g
          JOIN source_links o ON o.canonical_game_uuid=g.game_uuid
            AND o.source_type='ODDS_API' AND o.match_status='ACCEPTED'
          JOIN source_links p ON p.canonical_game_uuid=g.game_uuid
            AND p.source_type='POLYMARKET_US' AND p.match_status='ACCEPTED'
          WHERE g.league='NFL'
            AND o.canonical_game_uuid IS NOT NULL
            AND p.canonical_game_uuid IS NOT NULL
            AND o.canonical_game_uuid=p.canonical_game_uuid
            AND COALESCE(p.closed,0)=0
          ORDER BY g.scheduled_kickoff_utc,o.last_observed DESC,p.last_observed DESC
        """).fetchall()

    # Multiple observations may refresh the same source link. One canonical
    # game produces at most one pair and therefore at most two side observations.
    paired: dict[str, Any] = {}
    for row in rows:
        paired.setdefault(row["game_uuid"], row)

    edges, skipped = [], {"stale": 0, "incomplete_prices": 0, "incoherent_prices": 0}
    for row in paired.values():
        if not (_fresh(row["odds_observed"], now, max_age)
                and _fresh(row["polymarket_observed"], now, max_age)):
            skipped["stale"] += 1
            continue
        odds_values = json.loads(row["odds_values"] or "{}")
        market_values = json.loads(row["polymarket_values"] or "{}")
        book_probs = {
            row["away_team_id"]: odds_values.get("away_probability"),
            row["home_team_id"]: odds_values.get("home_probability"),
        }
        market_prices = _team_prices(registry, market_values)
        if (any(not isinstance(book_probs[t], (int, float)) for t in book_probs)
                or set(market_prices) != set(book_probs)):
            skipped["incomplete_prices"] += 1
            continue
        # Both side prices must form a coherent probability pair before either
        # can be compared with a vig-free book consensus. Polymarket US does
        # not publish a price per team here: `outcomePrices` is the bid and the
        # ask of a SINGLE side, while `outcomes` carries two team names whose
        # order does not track the prices. Both published numbers therefore
        # describe the same team, arrive one tick apart, and sum to anything
        # but one. Measured against Kalshi as an independent reference, the
        # first entry sits a median 0.010 from that game's away-team price and
        # 0.345 from the home team's. Read as two teams' probabilities they
        # produce enormous fictional edges: on 2026-09-08 this yielded 25
        # "edges" between 40 and 69 percentage points.
        pair_total = sum(market_prices.values())
        if not 0.97 <= pair_total <= 1.03:
            skipped["incoherent_prices"] += 1
            continue
        team_names = {
            row["away_team_id"]: row["away_team_name"],
            row["home_team_id"]: row["home_team_name"],
        }
        for team_id, fair_probability in book_probs.items():
            market_probability = market_prices[team_id]
            edge_points = (float(fair_probability) - market_probability) * 100
            if edge_points < minimum_points:
                continue
            edges.append({
                "canonical_game_uuid": row["game_uuid"],
                "canonical_game_id": row["canonical_game_id"],
                "market": f"{row['away_team_name']} @ {row['home_team_name']} (moneyline)",
                "team_id": team_id,
                "team": team_names[team_id],
                "polymarket_prob": round(market_probability * 100, 2),
                "consensus_prob": round(float(fair_probability) * 100, 2),
                "edge_percentage_points": round(edge_points, 2),
                # Kept for the existing dashboard display contract.
                "edge_pct": round(edge_points, 2),
                "direction": "RESEARCH_UNDERPRICED",
                "odds_api_event_id": row["odds_event_id"],
                "polymarket_us_event_id": row["polymarket_event_id"],
                "polymarket_us_market_id": row["polymarket_market_id"],
                "condition_id": row["polymarket_condition_id"],
                "scheduled_kickoff_utc": row["scheduled_kickoff_utc"],
                "odds_observed_at": row["odds_observed"],
                "polymarket_observed_at": row["polymarket_observed"],
                "url": f"https://polymarket.us/event/{row['event_slug']}" if row["event_slug"] else "",
            })
    edges.sort(key=lambda item: item["edge_percentage_points"], reverse=True)
    return {
        "schema_version": 2,
        "scanner": "canonical_nfl_registry",
        "scanner_version": SCANNER_VERSION,
        "environment": registry.environment,
        "last_updated": now.isoformat(),
        "minimum_edge_percentage_points": minimum_points,
        "verified_game_pairs": len(paired),
        "skipped": skipped,
        "edges": edges,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("development", "production"), default="production")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args(argv)
    registry = NFLRegistry(registry_path(args.env), environment=args.env)
    result = calculate_edges(registry)
    atomic_write_json(args.output, result)
    print(f"Canonical NFL edge scan: {len(result['edges'])} edges from "
          f"{result['verified_game_pairs']} verified same-game source pairs")
    print(f"Saved {args.output}")
    return result


if __name__ == "__main__":
    main()
