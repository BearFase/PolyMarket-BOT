#!/usr/bin/env python3
"""Immutable NFL post-game research records and revisioned analyst notes."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from nfl_schedule import NFLRegistry, parse_time, utc_now

NOTE_FIELDS = (
    "observed_market_behavior",
    "interesting_activity",
    "unexpected_price_movement",
    "news_injury_notes",
    "reason_largest_buy_wrong",
    "reason_largest_buy_correct",
    "lessons_learned",
)


def _json(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _snapshot(db, game_uuid: str, source_type: str, kickoff: str):
    return db.execute("""SELECT s.*,l.match_confidence,l.source_event_id,l.source_market_id
      FROM source_snapshots s JOIN source_links l ON l.source_link_uuid=s.source_link_uuid
      WHERE s.canonical_game_uuid=? AND s.source_type=? AND s.observed_timestamp<=?
      ORDER BY s.observed_timestamp DESC,s.rowid DESC LIMIT 1""",
      (game_uuid, source_type, kickoff)).fetchone()


def _favorite(snapshot) -> tuple[str | None, float | None, dict]:
    values = _json(snapshot["source_values_json"]) if snapshot else {}
    team_id = values.get("favorite_team_id")
    price = values.get("entry_price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    return team_id, price, values


def _activity_summary(rows, kickoff: str, away_id: str, home_id: str) -> dict:
    kickoff_time = parse_time(kickoff)
    normalized = [dict(row) for row in rows]
    pre, post = [], []
    for row in normalized:
        observed = parse_time(row["observed_timestamp"])
        (pre if observed and kickoff_time and observed <= kickoff_time else post).append(row)

    def largest(side_rows):
        if not side_rows:
            return None
        return max(side_rows, key=lambda row: (row["amount_usd"], row["observed_timestamp"]))

    def compact(row):
        return None if not row else {
            "team_id": row["team_id"], "amount_usd": row["amount_usd"],
            "execution_price": row["execution_price"], "timestamp": row["observed_timestamp"],
            "source_trade_id": row["source_trade_id"],
        }

    def movement(side_rows):
        ordered = sorted(side_rows, key=lambda row: row["observed_timestamp"])
        if not ordered:
            return None
        first, latest = ordered[0], ordered[-1]
        return {"first_price": first["execution_price"], "latest_price": latest["execution_price"],
                "change": round(latest["execution_price"] - first["execution_price"], 6),
                "first_timestamp": first["observed_timestamp"],
                "latest_timestamp": latest["observed_timestamp"]}

    largest_pre = largest(pre)
    latest = max(normalized, key=lambda row: row["observed_timestamp"]) if normalized else None
    return {
        "largest_recorded_buy": compact(largest_pre),
        "away_largest_buy": compact(largest([row for row in pre if row["team_id"] == away_id])),
        "home_largest_buy": compact(largest([row for row in pre if row["team_id"] == home_id])),
        "qualifying_trade_count": len(normalized),
        "pregame_trade_count": len(pre), "post_kickoff_trade_count": len(post),
        "largest_execution_price": max((row["execution_price"] for row in normalized), default=None),
        "latest_execution_price": latest["execution_price"] if latest else None,
        "latest_execution_timestamp": latest["observed_timestamp"] if latest else None,
        "price_movement_before_kickoff": {
            away_id: movement([row for row in pre if row["team_id"] == away_id]),
            home_id: movement([row for row in pre if row["team_id"] == home_id]),
        },
        "price_movement_after_kickoff": {
            away_id: movement([row for row in post if row["team_id"] == away_id]),
            home_id: movement([row for row in post if row["team_id"] == home_id]),
        },
    }


def _track(db, game_uuid: str, name: str) -> dict | None:
    row = db.execute("""SELECT * FROM simulation_tracks WHERE canonical_game_uuid=?
      AND track_name=? ORDER BY track_version DESC LIMIT 1""", (game_uuid, name)).fetchone()
    if not row:
        return None
    return {"selected_team_id": row["selected_team_id"], "result": row["result"],
            "hypothetical_entry_price": row["hypothetical_entry_price"],
            "hypothetical_return": row["hypothetical_return"],
            "settled_at": row["settled_at"]}


def _record(db, where: str = "1=1", params: tuple = ()) -> dict:
    games = db.execute(f"SELECT * FROM games WHERE game_status='FINAL' AND {where}", params).fetchall()
    ids = {game["game_uuid"] for game in games}
    totals = {"games": len(games), "home_wins": 0, "away_wins": 0,
              "largest_buy": {"wins": 0, "losses": 0},
              "sportsbook_favorite": {"wins": 0, "losses": 0},
              "polymarket_favorite": {"wins": 0, "losses": 0}}
    for game in games:
        totals["home_wins" if game["final_winner_team_id"] == game["home_team_id"] else "away_wins"] += 1
    for name, key in (("LARGEST_QUALIFYING_BUY", "largest_buy"),
                      ("SPORTSBOOK_CONSENSUS_FAVORITE", "sportsbook_favorite"),
                      ("POLYMARKET_PREGAME_FAVORITE", "polymarket_favorite")):
        if not ids:
            continue
        placeholders = ",".join("?" for _ in ids)
        rows = db.execute(f"SELECT result FROM simulation_tracks WHERE track_name=? AND canonical_game_uuid IN ({placeholders})",
                          (name, *sorted(ids))).fetchall()
        totals[key]["wins"] = sum(row["result"] == "WIN" for row in rows)
        totals[key]["losses"] = sum(row["result"] == "LOSS" for row in rows)
    return totals


def build_postgame_payload(registry: NFLRegistry, game_uuid: str) -> dict:
    with registry.connect() as db:
        game = db.execute("SELECT * FROM games WHERE game_uuid=?", (game_uuid,)).fetchone()
        if not game or game["game_status"] != "FINAL" or not game["final_winner_team_id"]:
            raise ValueError("post-game research requires a verified FINAL game")
        activities = db.execute("SELECT * FROM game_flow_activity WHERE canonical_game_uuid=?",
                                (game_uuid,)).fetchall()
        flow = _activity_summary(activities, game["scheduled_kickoff_utc"],
                                 game["away_team_id"], game["home_team_id"])
        odds = _snapshot(db, game_uuid, "ODDS_API", game["scheduled_kickoff_utc"])
        polymarket = _snapshot(db, game_uuid, "POLYMARKET_US", game["scheduled_kickoff_utc"])
        sportsbook_team, sportsbook_price, sportsbook_values = _favorite(odds)
        polymarket_team, polymarket_price, polymarket_values = _favorite(polymarket)
        tracks = {
            "largest_buy": _track(db, game_uuid, "LARGEST_QUALIFYING_BUY"),
            "sportsbook_favorite": _track(db, game_uuid, "SPORTSBOOK_CONSENSUS_FAVORITE"),
            "polymarket_favorite": _track(db, game_uuid, "POLYMARKET_PREGAME_FAVORITE"),
        }
        conflicts = db.execute("SELECT COUNT(*) FROM result_conflicts WHERE canonical_game_uuid=? AND resolved_at IS NULL",
                               (game_uuid,)).fetchone()[0]
        largest_all = db.execute("""SELECT a.amount_usd,a.canonical_game_uuid,g.canonical_game_id
          FROM game_flow_activity a JOIN games g ON g.game_uuid=a.canonical_game_uuid
          WHERE g.game_status='FINAL' ORDER BY a.amount_usd DESC LIMIT 1""").fetchone()
        current_season = _record(db, "season=?", (game["season"],))
        week = _record(db, "season=? AND season_type=? AND week=?",
                       (game["season"], game["season_type"], game["week"]))
        preseason = _record(db, "season=? AND season_type IN ('HOF','PRE')", (game["season"],))

    def result_for(team_id, track):
        if track and track.get("result"):
            return track["result"] == "WIN"
        return None if not team_id else team_id == game["final_winner_team_id"]

    largest = flow["largest_recorded_buy"]
    largest_won = result_for(largest["team_id"] if largest else None, tracks["largest_buy"])
    sportsbook_won = result_for(sportsbook_team, tracks["sportsbook_favorite"])
    polymarket_won = result_for(polymarket_team, tracks["polymarket_favorite"])
    warnings = []
    if not odds: warnings.append("No sportsbook snapshot captured at or before kickoff.")
    if not polymarket: warnings.append("No Polymarket US snapshot captured at or before kickoff.")
    if not activities: warnings.append("No qualifying Game Flow trades were recorded.")
    if conflicts: warnings.append("Authoritative result conflict is unresolved.")
    if odds and not odds["bookmaker_count"]: warnings.append("Sportsbook source count is unavailable.")
    if polymarket and polymarket["liquidity"] is None: warnings.append("Market liquidity is unavailable.")

    kickoff = parse_time(game["scheduled_kickoff_utc"])
    freshness = {}
    for label, snapshot in (("sportsbook", odds), ("polymarket_us", polymarket)):
        observed = parse_time(snapshot["observed_timestamp"]) if snapshot else None
        freshness[label] = None if not observed or not kickoff else max(0, int((kickoff-observed).total_seconds()))

    indicators = []
    for label, value in (("Largest Buy", largest_won), ("Sportsbook Favorite", sportsbook_won),
                         ("Polymarket Favorite", polymarket_won)):
        if value is not None: indicators.append({"kind": "success" if value else "failure", "label": f"{label} {'Won' if value else 'Lost'}"})
    if largest and largest_all and largest["amount_usd"] == largest_all["amount_usd"]:
        indicators.append({"kind": "money", "label": "Largest Recorded Buy"})
    if largest and largest_won is False and largest["amount_usd"] >= 1000:
        indicators.append({"kind": "warning", "label": "Large Buy Lost"})
    if sportsbook_won is False and polymarket_won is False:
        indicators.append({"kind": "trend", "label": "Biggest Upset Candidate"})

    return {
        "record_schema_version": 1,
        "canonical_game_uuid": game_uuid,
        "canonical_game_id": game["canonical_game_id"],
        "game_information": {
            "season": game["season"], "season_type": game["season_type"], "week": game["week"],
            "away_team_id": game["away_team_id"], "away_team": game["away_team_name"],
            "home_team_id": game["home_team_id"], "home_team": game["home_team_name"],
            "kickoff_time": game["scheduled_kickoff_utc"], "away_score": game["away_score"],
            "home_score": game["home_score"], "winner_team_id": game["final_winner_team_id"],
            "winner": registry.team_name(game["final_winner_team_id"]), "game_status": game["game_status"],
            "completion_timestamp": game["completion_timestamp"],
        },
        "market_snapshot": {
            **{key: flow[key] for key in ("largest_recorded_buy", "away_largest_buy", "home_largest_buy")},
            "pregame_polymarket_favorite_team_id": polymarket_team,
            "pregame_sportsbook_favorite_team_id": sportsbook_team,
            "closing_polymarket_probability": polymarket_price,
            "closing_sportsbook_probability": sportsbook_price,
            "polymarket_probabilities": polymarket_values.get("outcomes", []),
            "sportsbook_probabilities": {"away": sportsbook_values.get("away_probability"),
                                          "home": sportsbook_values.get("home_probability")},
            "bookmaker_count": odds["bookmaker_count"] if odds else None,
            "market_liquidity": polymarket["liquidity"] if polymarket else None,
            "sportsbook_snapshot_timestamp": odds["observed_timestamp"] if odds else None,
            "polymarket_snapshot_timestamp": polymarket["observed_timestamp"] if polymarket else None,
        },
        "research_results": {
            "largest_buy_side_won": largest_won, "sportsbook_favorite_won": sportsbook_won,
            "polymarket_favorite_won": polymarket_won,
            "largest_buy_return": tracks["largest_buy"]["hypothetical_return"] if tracks["largest_buy"] else None,
            "sportsbook_favorite_return": tracks["sportsbook_favorite"]["hypothetical_return"] if tracks["sportsbook_favorite"] else None,
            "polymarket_favorite_return": tracks["polymarket_favorite"]["hypothetical_return"] if tracks["polymarket_favorite"] else None,
            "comparison_only": True, "paper_cash_affected": False,
        },
        "game_flow_summary": flow,
        "historical_comparisons": {
            "largest_buy_overall": dict(largest_all) if largest_all else None,
            "current_season_totals": current_season, "week_totals": week,
            "preseason_totals": preseason,
        },
        "visual_indicators": indicators,
        "research_quality": {
            "bookmaker_count": odds["bookmaker_count"] if odds else None,
            "data_freshness_seconds_before_kickoff": freshness,
            "sportsbook_matching_confidence": odds["match_confidence"] if odds else None,
            "polymarket_matching_confidence": polymarket["match_confidence"] if polymarket else None,
            "canonical_match_verified": True,
            "settlement_verified": bool(game["result_source"] and game["source_result_id"] and not conflicts),
            "settlement_source": game["result_source"], "missing_data_warnings": warnings,
            "incomplete_source_warning": bool(warnings),
        },
    }


def materialize_postgame_summary(registry: NFLRegistry, game_uuid: str,
                                 reason: str = "research data refreshed") -> dict:
    payload = build_postgame_payload(registry, game_uuid)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    with registry.connect() as db:
        existing = db.execute("""SELECT * FROM postgame_research_records
          WHERE canonical_game_uuid=? ORDER BY revision_number DESC LIMIT 1""", (game_uuid,)).fetchone()
        same = db.execute("SELECT * FROM postgame_research_records WHERE canonical_game_uuid=? AND content_hash=?",
                          (game_uuid, digest)).fetchone()
        if same:
            return {"created": False, "record": _record_row(same)}
        record_uuid = str(uuid.uuid4())
        revision = 1 if not existing else existing["revision_number"] + 1
        db.execute("""INSERT INTO postgame_research_records VALUES(?,?,?,?,?,?,?,?)""",
          (record_uuid, game_uuid, revision, utc_now(), reason, digest, canonical,
           existing["record_uuid"] if existing else None))
        row = db.execute("SELECT * FROM postgame_research_records WHERE record_uuid=?", (record_uuid,)).fetchone()
    return {"created": True, "record": _record_row(row)}


def materialize_completed_summaries(registry: NFLRegistry) -> dict:
    with registry.connect() as db:
        games = [row[0] for row in db.execute("SELECT game_uuid FROM games WHERE game_status='FINAL'")]
    created = sum(materialize_postgame_summary(registry, game_uuid)["created"] for game_uuid in games)
    return {"completed_games": len(games), "revisions_created": created}


def _record_row(row) -> dict:
    return {"record_uuid": row["record_uuid"], "canonical_game_uuid": row["canonical_game_uuid"],
            "revision_number": row["revision_number"], "created_at": row["created_at"],
            "revision_reason": row["revision_reason"], "content_hash": row["content_hash"],
            "supersedes_record_uuid": row["supersedes_record_uuid"],
            "payload": json.loads(row["payload_json"])}


def get_postgame_summary(registry: NFLRegistry, game_uuid: str) -> dict | None:
    with registry.connect() as db:
        latest = db.execute("""SELECT * FROM postgame_research_records WHERE canonical_game_uuid=?
          ORDER BY revision_number DESC LIMIT 1""", (game_uuid,)).fetchone()
        if not latest:
            return None
        history = [dict(row) for row in db.execute("""SELECT record_uuid,revision_number,created_at,
          revision_reason,content_hash,supersedes_record_uuid FROM postgame_research_records
          WHERE canonical_game_uuid=? ORDER BY revision_number DESC""", (game_uuid,))]
        note = db.execute("""SELECT * FROM analyst_note_revisions WHERE canonical_game_uuid=?
          ORDER BY revision_number DESC LIMIT 1""", (game_uuid,)).fetchone()
    return {"record": _record_row(latest), "revision_history": history,
            "analyst_notes": _note_row(note) if note else {"revision_number": 0, "notes": {key: "" for key in NOTE_FIELDS}}}


def save_analyst_notes(registry: NFLRegistry, game_uuid: str, notes: dict,
                       author: str = "local analyst") -> dict:
    cleaned = {key: str(notes.get(key, "")).strip()[:10000] for key in NOTE_FIELDS}
    unknown = set(notes) - set(NOTE_FIELDS)
    if unknown:
        raise ValueError("unknown analyst note fields")
    with registry.connect() as db:
        game = db.execute("SELECT game_status FROM games WHERE game_uuid=?", (game_uuid,)).fetchone()
        if not game or game["game_status"] != "FINAL":
            raise ValueError("analyst notes require a completed canonical game")
        previous = db.execute("""SELECT * FROM analyst_note_revisions WHERE canonical_game_uuid=?
          ORDER BY revision_number DESC LIMIT 1""", (game_uuid,)).fetchone()
        revision = 1 if not previous else previous["revision_number"] + 1
        note_uuid = str(uuid.uuid4())
        db.execute("INSERT INTO analyst_note_revisions VALUES(?,?,?,?,?,?,?)",
          (note_uuid, game_uuid, revision, utc_now(), author[:100], json.dumps(cleaned, sort_keys=True),
           previous["note_revision_uuid"] if previous else None))
        row = db.execute("SELECT * FROM analyst_note_revisions WHERE note_revision_uuid=?", (note_uuid,)).fetchone()
    return _note_row(row)


def _note_row(row) -> dict:
    return {"note_revision_uuid": row["note_revision_uuid"], "revision_number": row["revision_number"],
            "created_at": row["created_at"], "author": row["author"],
            "supersedes_note_revision_uuid": row["supersedes_note_revision_uuid"],
            "notes": json.loads(row["notes_json"])}
