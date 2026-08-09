#!/usr/bin/env python3
"""Canonical, append-only MLB research storage and descriptive reporting.

This module records evidence only. It never creates recommendations, paper
positions, or real orders. Historical observations and source snapshots are
immutable; corrections are represented by new schedule revisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import statistics
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "mlb_research.db"
LEGACY_TAPE_DB = HERE / "big_money_tape.db"
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
SCHEMA_VERSION = 1
TRADE_NAMESPACE = uuid.UUID("af9db343-941e-4ac7-84ed-edf27a689a6a")

TEAM_ROWS = [
    ("ARI", "Arizona Diamondbacks", ["Arizona Diamondbacks", "Diamondbacks"]),
    ("ATH", "Athletics", ["Athletics", "Oakland Athletics", "A's"]),
    ("ATL", "Atlanta Braves", ["Atlanta Braves", "Braves"]),
    ("BAL", "Baltimore Orioles", ["Baltimore Orioles", "Orioles"]),
    ("BOS", "Boston Red Sox", ["Boston Red Sox", "Red Sox"]),
    ("CHC", "Chicago Cubs", ["Chicago Cubs", "Cubs"]),
    ("CWS", "Chicago White Sox", ["Chicago White Sox", "White Sox"]),
    ("CIN", "Cincinnati Reds", ["Cincinnati Reds", "Reds"]),
    ("CLE", "Cleveland Guardians", ["Cleveland Guardians", "Guardians"]),
    ("COL", "Colorado Rockies", ["Colorado Rockies", "Rockies"]),
    ("DET", "Detroit Tigers", ["Detroit Tigers", "Tigers"]),
    ("HOU", "Houston Astros", ["Houston Astros", "Astros"]),
    ("KC", "Kansas City Royals", ["Kansas City Royals", "Royals"]),
    ("LAA", "Los Angeles Angels", ["Los Angeles Angels", "Angels"]),
    ("LAD", "Los Angeles Dodgers", ["Los Angeles Dodgers", "Dodgers"]),
    ("MIA", "Miami Marlins", ["Miami Marlins", "Marlins"]),
    ("MIL", "Milwaukee Brewers", ["Milwaukee Brewers", "Brewers"]),
    ("MIN", "Minnesota Twins", ["Minnesota Twins", "Twins"]),
    ("NYM", "New York Mets", ["New York Mets", "Mets"]),
    ("NYY", "New York Yankees", ["New York Yankees", "Yankees"]),
    ("PHI", "Philadelphia Phillies", ["Philadelphia Phillies", "Phillies"]),
    ("PIT", "Pittsburgh Pirates", ["Pittsburgh Pirates", "Pirates"]),
    ("SD", "San Diego Padres", ["San Diego Padres", "Padres"]),
    ("SF", "San Francisco Giants", ["San Francisco Giants", "Giants"]),
    ("SEA", "Seattle Mariners", ["Seattle Mariners", "Mariners"]),
    ("STL", "St. Louis Cardinals", ["St. Louis Cardinals", "Cardinals"]),
    ("TB", "Tampa Bay Rays", ["Tampa Bay Rays", "Rays"]),
    ("TEX", "Texas Rangers", ["Texas Rangers", "Rangers"]),
    ("TOR", "Toronto Blue Jays", ["Toronto Blue Jays", "Blue Jays"]),
    ("WSH", "Washington Nationals", ["Washington Nationals", "Nationals"]),
]


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


def normalized(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold()
                   if character.isalnum())


def stable_uuid(namespace: str, value: str) -> str:
    return str(uuid.uuid5(TRADE_NAMESPACE, f"{namespace}:{value}"))


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class MLBResearchRegistry:
    def __init__(self, db_path: Path | str = DEFAULT_DB):
        self.db_path = Path(db_path)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta(
              key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mlb_teams(
              team_id TEXT PRIMARY KEY,full_name TEXT NOT NULL UNIQUE,
              aliases_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS mlb_games(
              game_uuid TEXT PRIMARY KEY,mlb_game_pk INTEGER NOT NULL UNIQUE,
              official_date TEXT NOT NULL,away_team_id TEXT NOT NULL,
              away_team_name TEXT NOT NULL,home_team_id TEXT NOT NULL,
              home_team_name TEXT NOT NULL,scheduled_start_utc TEXT NOT NULL,
              actual_start_utc TEXT,status TEXT NOT NULL,detailed_status TEXT,
              doubleheader_code TEXT,game_number INTEGER,doubleheader_identifier TEXT,
              series_game_number INTEGER,postponed INTEGER NOT NULL DEFAULT 0,
              rescheduled INTEGER NOT NULL DEFAULT 0,original_start_utc TEXT,
              away_score INTEGER,home_score INTEGER,final_winner_team_id TEXT,
              completion_timestamp TEXT,source TEXT NOT NULL,source_url TEXT,
              first_observed TEXT NOT NULL,last_observed TEXT NOT NULL,schedule_version INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS mlb_games_match
              ON mlb_games(away_team_id,home_team_id,scheduled_start_utc);
            CREATE TABLE IF NOT EXISTS mlb_schedule_revisions(
              revision_uuid TEXT PRIMARY KEY,game_uuid TEXT NOT NULL,
              revision_number INTEGER NOT NULL,observed_timestamp TEXT NOT NULL,
              scheduled_start_utc TEXT NOT NULL,actual_start_utc TEXT,status TEXT NOT NULL,
              detailed_status TEXT,doubleheader_identifier TEXT,postponed INTEGER NOT NULL,
              rescheduled INTEGER NOT NULL,away_score INTEGER,home_score INTEGER,
              final_winner_team_id TEXT,source_payload_json TEXT NOT NULL,
              UNIQUE(game_uuid,revision_number));
            CREATE TABLE IF NOT EXISTS mlb_trade_observations(
              observation_uuid TEXT PRIMARY KEY,source_trade_key TEXT NOT NULL UNIQUE,
              websocket_trade_id TEXT,event_slug TEXT NOT NULL,market_slug TEXT NOT NULL,
              canonical_game_uuid TEXT,league TEXT NOT NULL,market_type TEXT NOT NULL,
              home_team_id TEXT,home_team TEXT,away_team_id TEXT,away_team TEXT,
              selected_team_id TEXT,selected_team TEXT,raw_selection TEXT,
              selected_side TEXT NOT NULL,contracts REAL NOT NULL,
              execution_price REAL NOT NULL,risk_usd REAL NOT NULL,
              trade_timestamp_utc TEXT NOT NULL,ingestion_timestamp TEXT NOT NULL,
              source_market_start_time TEXT,pregame_classification TEXT NOT NULL
                CHECK(pregame_classification IN ('PREGAME','IN_GAME','UNKNOWN')),
              canonical_start_evidence TEXT,source_identifiers_json TEXT NOT NULL,
              source_quality_flags_json TEXT NOT NULL,legacy_incomplete INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS mlb_trades_game_time
              ON mlb_trade_observations(canonical_game_uuid,trade_timestamp_utc);
            CREATE INDEX IF NOT EXISTS mlb_trades_research_lookup
              ON mlb_trade_observations(canonical_game_uuid,legacy_incomplete,
                pregame_classification,trade_timestamp_utc,risk_usd);
            CREATE TABLE IF NOT EXISTS mlb_link_rejections(
              rejection_uuid TEXT PRIMARY KEY,source_kind TEXT NOT NULL,
              source_identifier TEXT NOT NULL,observed_timestamp TEXT NOT NULL,
              reason TEXT NOT NULL,evidence_json TEXT NOT NULL,
              UNIQUE(source_kind,source_identifier,reason));
            CREATE TABLE IF NOT EXISTS mlb_sportsbook_snapshots(
              snapshot_uuid TEXT PRIMARY KEY,canonical_game_uuid TEXT NOT NULL,
              sportsbook_event_id TEXT NOT NULL,bookmaker TEXT NOT NULL,
              quote_timestamp TEXT NOT NULL,home_odds REAL NOT NULL,away_odds REAL NOT NULL,
              home_raw_probability REAL NOT NULL,away_raw_probability REAL NOT NULL,
              home_vig_free_probability REAL NOT NULL,away_vig_free_probability REAL NOT NULL,
              consensus_mean_home REAL NOT NULL,consensus_mean_away REAL NOT NULL,
              consensus_median_home REAL NOT NULL,consensus_median_away REAL NOT NULL,
              favorite_team_id TEXT,underdog_team_id TEXT,source_count INTEGER NOT NULL,
              retrieval_timestamp TEXT NOT NULL,source_quality_flags_json TEXT NOT NULL,
              UNIQUE(sportsbook_event_id,bookmaker,quote_timestamp,home_odds,away_odds));
            CREATE INDEX IF NOT EXISTS mlb_books_game_time
              ON mlb_sportsbook_snapshots(canonical_game_uuid,quote_timestamp);
            CREATE TRIGGER IF NOT EXISTS mlb_schedule_revisions_no_update BEFORE UPDATE ON mlb_schedule_revisions BEGIN SELECT RAISE(ABORT,'schedule revisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS mlb_schedule_revisions_no_delete BEFORE DELETE ON mlb_schedule_revisions BEGIN SELECT RAISE(ABORT,'schedule revisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS mlb_trade_observations_no_update BEFORE UPDATE ON mlb_trade_observations BEGIN SELECT RAISE(ABORT,'MLB trade observations are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS mlb_trade_observations_no_delete BEFORE DELETE ON mlb_trade_observations BEGIN SELECT RAISE(ABORT,'MLB trade observations are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS mlb_sportsbook_snapshots_no_update BEFORE UPDATE ON mlb_sportsbook_snapshots BEGIN SELECT RAISE(ABORT,'sportsbook snapshots are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS mlb_sportsbook_snapshots_no_delete BEFORE DELETE ON mlb_sportsbook_snapshots BEGIN SELECT RAISE(ABORT,'sportsbook snapshots are immutable'); END;
            """)
            db.execute("INSERT OR REPLACE INTO schema_meta VALUES('schema_version',?)",
                       (str(SCHEMA_VERSION),))
            db.executemany("INSERT OR IGNORE INTO mlb_teams VALUES(?,?,?)",
                           ((team_id, name, json.dumps(aliases))
                            for team_id, name, aliases in TEAM_ROWS))

    def normalize_team(self, value: Any) -> str | None:
        needle = normalized(value)
        matches = []
        for team_id, name, aliases in TEAM_ROWS:
            if needle in {normalized(name), *(normalized(alias) for alias in aliases)}:
                matches.append(team_id)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def team_name(team_id: str | None) -> str | None:
        return next((name for candidate, name, _ in TEAM_ROWS if candidate == team_id), None)

    def ingest_schedule(self, payload: dict, observed_at: str | None = None) -> dict:
        observed_at = observed_at or utc_now()
        inserted = updated = unchanged = 0
        for day in payload.get("dates", []):
            for raw in day.get("games", []):
                parsed = parse_mlb_game(raw, observed_at)
                if not parsed:
                    continue
                with self.connect() as db:
                    existing = db.execute("SELECT * FROM mlb_games WHERE mlb_game_pk=?",
                                          (parsed["mlb_game_pk"],)).fetchone()
                    version = 1 if not existing else int(existing["schedule_version"])
                    comparison = ("scheduled_start_utc", "actual_start_utc", "status",
                                  "detailed_status", "away_score", "home_score",
                                  "final_winner_team_id", "doubleheader_identifier")
                    changed = not existing or any(existing[key] != parsed[key] for key in comparison)
                    if existing and changed:
                        version += 1
                        parsed["rescheduled"] = int(
                            existing["scheduled_start_utc"] != parsed["scheduled_start_utc"])
                        parsed["original_start_utc"] = (
                            existing["original_start_utc"] or existing["scheduled_start_utc"]
                            if parsed["rescheduled"] else existing["original_start_utc"])
                    parsed["schedule_version"] = version
                    if not existing:
                        inserted += 1
                        parsed["first_observed"] = observed_at
                    elif changed:
                        updated += 1
                        parsed["first_observed"] = existing["first_observed"]
                    else:
                        unchanged += 1
                        db.execute("UPDATE mlb_games SET last_observed=? WHERE mlb_game_pk=?",
                                   (observed_at, parsed["mlb_game_pk"]))
                        continue
                    db.execute("""INSERT INTO mlb_games(
                      game_uuid,mlb_game_pk,official_date,away_team_id,away_team_name,
                      home_team_id,home_team_name,scheduled_start_utc,actual_start_utc,
                      status,detailed_status,doubleheader_code,game_number,doubleheader_identifier,
                      series_game_number,postponed,rescheduled,original_start_utc,away_score,
                      home_score,final_winner_team_id,completion_timestamp,source,source_url,
                      first_observed,last_observed,schedule_version)
                      VALUES(:game_uuid,:mlb_game_pk,:official_date,:away_team_id,:away_team_name,
                      :home_team_id,:home_team_name,:scheduled_start_utc,:actual_start_utc,
                      :status,:detailed_status,:doubleheader_code,:game_number,:doubleheader_identifier,
                      :series_game_number,:postponed,:rescheduled,:original_start_utc,:away_score,
                      :home_score,:final_winner_team_id,:completion_timestamp,:source,:source_url,
                      :first_observed,:last_observed,:schedule_version)
                      ON CONFLICT(mlb_game_pk) DO UPDATE SET
                      official_date=excluded.official_date,scheduled_start_utc=excluded.scheduled_start_utc,
                      actual_start_utc=excluded.actual_start_utc,status=excluded.status,
                      detailed_status=excluded.detailed_status,doubleheader_code=excluded.doubleheader_code,
                      game_number=excluded.game_number,doubleheader_identifier=excluded.doubleheader_identifier,
                      series_game_number=excluded.series_game_number,postponed=excluded.postponed,
                      rescheduled=excluded.rescheduled,original_start_utc=excluded.original_start_utc,
                      away_score=excluded.away_score,home_score=excluded.home_score,
                      final_winner_team_id=excluded.final_winner_team_id,
                      completion_timestamp=excluded.completion_timestamp,last_observed=excluded.last_observed,
                      schedule_version=excluded.schedule_version""", parsed)
                    revision_payload = {key: parsed[key] for key in parsed}
                    db.execute("""INSERT INTO mlb_schedule_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                               (stable_uuid("schedule-revision", f"{parsed['game_uuid']}:{version}"),
                                parsed["game_uuid"], version, observed_at,
                                parsed["scheduled_start_utc"], parsed["actual_start_utc"],
                                parsed["status"], parsed["detailed_status"],
                                parsed["doubleheader_identifier"], parsed["postponed"],
                                parsed["rescheduled"], parsed["away_score"], parsed["home_score"],
                                parsed["final_winner_team_id"],
                                json.dumps(revision_payload, sort_keys=True)))
        return {"inserted": inserted, "updated": updated, "unchanged": unchanged}

    def match_game(self, away: str | None, home: str | None,
                   source_start: str | None, tolerance_hours: float = 12) -> tuple[dict | None, str]:
        away_id, home_id = self.normalize_team(away), self.normalize_team(home)
        start = parse_time(source_start)
        if not away_id or not home_id:
            return None, "UNKNOWN_TEAM"
        if not start:
            return None, "CANONICAL_START_UNAVAILABLE"
        with self.connect() as db:
            candidates = [dict(row) for row in db.execute(
                "SELECT * FROM mlb_games WHERE away_team_id=? AND home_team_id=?",
                (away_id, home_id))]
        candidates = [(candidate, abs((parse_time(candidate["scheduled_start_utc"]) - start).total_seconds()))
                      for candidate in candidates]
        candidates = [item for item in candidates if item[1] <= tolerance_hours * 3600]
        if not candidates:
            return None, "NO_CANONICAL_GAME"
        candidates.sort(key=lambda item: item[1])
        if len(candidates) > 1 and candidates[0][1] == candidates[1][1]:
            return None, "AMBIGUOUS_DOUBLEHEADER"
        return candidates[0][0], "ACCEPTED"

    def record_rejection(self, source_kind: str, identifier: str,
                         reason: str, evidence: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO mlb_link_rejections VALUES(?,?,?,?,?,?)",
                       (stable_uuid("rejection", f"{source_kind}:{identifier}:{reason}"),
                        source_kind, identifier, utc_now(), reason,
                        json.dumps(evidence, sort_keys=True)))

    def record_trade(self, trade: dict) -> bool:
        if str(trade.get("league", "")).lower() != "mlb" \
                or str(trade.get("market_type", "")).lower() != "moneyline":
            return False
        event_slug = str(trade.get("event_slug") or "")
        market_slug = str(trade.get("market_slug") or "")
        source_key = str(trade.get("source_trade_key") or trade.get("websocket_trade_id") or "")
        if not event_slug or not market_slug or not source_key:
            raise ValueError("trade requires event_slug, market_slug, and source_trade_key")
        away, home = split_matchup(trade.get("event_title"))
        game, reason = self.match_game(away, home, trade.get("source_market_start_time"))
        flags = list(trade.get("source_quality_flags") or [])
        classification = "UNKNOWN"
        canonical_start = None
        selected_team_id = self.normalize_team(trade.get("selected_team"))
        if game:
            canonical_start = game.get("actual_start_utc") or game["scheduled_start_utc"]
            trade_time = parse_time(trade.get("trade_timestamp_utc"))
            start_time = parse_time(canonical_start)
            classification = ("PREGAME" if trade_time and start_time and trade_time < start_time
                              else "IN_GAME" if trade_time and start_time else "UNKNOWN")
            if selected_team_id not in {game["away_team_id"], game["home_team_id"]}:
                flags.append("SELECTED_TEAM_MISMATCH")
        else:
            flags.extend([reason, "CANONICAL_MATCH_UNVERIFIED"])
            self.record_rejection("GAME_FLOW_STREAM", source_key, reason, {
                "event_slug": event_slug, "away": away, "home": home,
                "source_start": trade.get("source_market_start_time")})
        observation_uuid = stable_uuid("trade", source_key)
        values = (
            observation_uuid, source_key, trade.get("websocket_trade_id"), event_slug,
            market_slug, game["game_uuid"] if game else None, "MLB", "moneyline",
            game["home_team_id"] if game else self.normalize_team(home),
            game["home_team_name"] if game else home,
            game["away_team_id"] if game else self.normalize_team(away),
            game["away_team_name"] if game else away, selected_team_id,
            trade.get("selected_team"), trade.get("raw_selection"), trade["selected_side"],
            float(trade["contracts"]), float(trade["execution_price"]),
            float(trade["risk_usd"]), trade["trade_timestamp_utc"], utc_now(),
            trade.get("source_market_start_time"), classification, canonical_start,
            json.dumps(trade.get("source_identifiers") or {}, sort_keys=True),
            json.dumps(sorted(set(flags)), sort_keys=True), int(bool(trade.get("legacy_incomplete"))))
        with self.connect() as db:
            before = db.total_changes
            db.execute("INSERT OR IGNORE INTO mlb_trade_observations VALUES(" +
                       ",".join("?" for _ in values) + ")", values)
            return db.total_changes > before

    def ingest_sportsbook(self, payload: list, retrieved_at: str | None = None) -> dict:
        retrieved_at = retrieved_at or utc_now()
        inserted = rejected = 0
        for event in payload if isinstance(payload, list) else []:
            game, reason = self.match_game(event.get("away_team"), event.get("home_team"),
                                           event.get("commence_time"))
            source_id = str(event.get("id") or "")
            if not game:
                rejected += 1
                self.record_rejection("ODDS_API", source_id or stable_uuid("odds", json.dumps(event, sort_keys=True)),
                                      reason, {"away": event.get("away_team"),
                                               "home": event.get("home_team"),
                                               "commence_time": event.get("commence_time")})
                continue
            books = parse_sportsbook_books(event)
            if not books:
                continue
            home_probs = [book["home_vig_free_probability"] for book in books]
            away_probs = [book["away_vig_free_probability"] for book in books]
            mean_home, mean_away = statistics.mean(home_probs), statistics.mean(away_probs)
            median_home, median_away = statistics.median(home_probs), statistics.median(away_probs)
            favorite = game["home_team_id"] if mean_home > mean_away else game["away_team_id"]
            underdog = game["away_team_id"] if favorite == game["home_team_id"] else game["home_team_id"]
            for book in books:
                identity = (f"{source_id}:{book['bookmaker']}:{book['quote_timestamp']}:"
                            f"{book['home_odds']}:{book['away_odds']}")
                row = (stable_uuid("sportsbook", identity), game["game_uuid"], source_id,
                       book["bookmaker"], book["quote_timestamp"], book["home_odds"],
                       book["away_odds"], book["home_raw_probability"],
                       book["away_raw_probability"], book["home_vig_free_probability"],
                       book["away_vig_free_probability"], mean_home, mean_away,
                       median_home, median_away, favorite, underdog, len(books),
                       retrieved_at, "[]")
                with self.connect() as db:
                    before = db.total_changes
                    db.execute("INSERT OR IGNORE INTO mlb_sportsbook_snapshots VALUES(" +
                               ",".join("?" for _ in row) + ")", row)
                    inserted += int(db.total_changes > before)
        return {"inserted": inserted, "rejected_events": rejected}

    def migrate_legacy(self, tape_path: Path | str = LEGACY_TAPE_DB) -> dict:
        tape_path = Path(tape_path)
        if not tape_path.exists():
            return {"imported": 0, "source": "missing"}
        source = sqlite3.connect(f"file:{tape_path.resolve().as_posix()}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        rows = source.execute("""SELECT b.*,m.market_type,e.start_time FROM bets b
          JOIN markets m USING(market_slug) JOIN events e USING(event_slug)
          WHERE b.league='mlb' AND m.market_type='moneyline' AND b.risk_usd>=5""").fetchall()
        imported = 0
        for row in rows:
            imported += int(self.record_trade({
                "source_trade_key": f"legacy:{row['id']}", "event_slug": row["event_slug"],
                "market_slug": row["market_slug"], "league": "mlb", "market_type": "moneyline",
                "event_title": row["event_title"], "selected_team": row["raw_selection"],
                "raw_selection": row["raw_selection"], "selected_side": row["selected_side"],
                "contracts": row["contracts"], "execution_price": row["entry_price"],
                "risk_usd": row["risk_usd"], "trade_timestamp_utc": row["trade_time"],
                "source_market_start_time": row["start_time"], "legacy_incomplete": True,
                "source_quality_flags": ["LEGACY_INCOMPLETE", "SOURCE_TAPE_PRUNED"],
                "source_identifiers": {"legacy_bet_id": row["id"]},
            }))
        source.close()
        return {"imported": imported, "examined": len(rows), "source": str(tape_path.resolve())}

    def overview(self, today: str | None = None) -> dict:
        today = today or datetime.now().astimezone().date().isoformat()
        with self.connect() as db:
            one = lambda sql, args=(): db.execute(sql, args).fetchone()[0]
            return {
                "generated_at": utc_now(),
                "trustworthy_observations": one("""SELECT COUNT(*) FROM mlb_trade_observations
                  WHERE legacy_incomplete=0 AND canonical_game_uuid IS NOT NULL"""),
                "legacy_incomplete_observations": one("""SELECT COUNT(*) FROM mlb_trade_observations
                  WHERE legacy_incomplete=1"""),
                "sportsbook_snapshots": one("SELECT COUNT(*) FROM mlb_sportsbook_snapshots"),
                "canonical_games": one("SELECT COUNT(*) FROM mlb_games"),
                "games_with_pregame_evidence": one("""SELECT COUNT(DISTINCT canonical_game_uuid)
                  FROM mlb_trade_observations WHERE legacy_incomplete=0
                    AND canonical_game_uuid IS NOT NULL AND pregame_classification='PREGAME'"""),
                "games_with_sportsbook_observations": one("""SELECT COUNT(DISTINCT canonical_game_uuid)
                  FROM mlb_sportsbook_snapshots"""),
                "complete_research_cases": one("""SELECT COUNT(*) FROM mlb_games g
                  WHERE g.status='FINAL' AND g.final_winner_team_id IS NOT NULL
                    AND EXISTS(SELECT 1 FROM mlb_trade_observations t
                      WHERE t.canonical_game_uuid=g.game_uuid AND t.legacy_incomplete=0
                        AND t.pregame_classification='PREGAME')
                    AND EXISTS(SELECT 1 FROM mlb_sportsbook_snapshots s
                      WHERE s.canonical_game_uuid=g.game_uuid
                        AND s.quote_timestamp<g.scheduled_start_utc)"""),
                "games_currently_collecting": one("""SELECT COUNT(*) FROM mlb_games g
                  WHERE g.official_date=? AND g.status!='FINAL'
                    AND EXISTS(SELECT 1 FROM mlb_trade_observations t
                      WHERE t.canonical_game_uuid=g.game_uuid AND t.legacy_incomplete=0)""", (today,)),
                "earliest_observation": one("""SELECT MIN(trade_timestamp_utc)
                  FROM mlb_trade_observations WHERE legacy_incomplete=0
                    AND canonical_game_uuid IS NOT NULL"""),
                "latest_observation": one("""SELECT MAX(trade_timestamp_utc)
                  FROM mlb_trade_observations WHERE legacy_incomplete=0
                    AND canonical_game_uuid IS NOT NULL"""),
                "today": today,
            }

    def research_games(self, filters: dict | None = None) -> list[dict]:
        filters = filters or {}
        clauses, arguments = ["1=1"], []
        if filters.get("game_uuid"):
            clauses.append("game_uuid=?"); arguments.append(filters["game_uuid"])
        if filters.get("date"):
            clauses.append("official_date=?"); arguments.append(filters["date"])
        if filters.get("date_from"):
            clauses.append("official_date>=?"); arguments.append(filters["date_from"])
        if filters.get("date_to"):
            clauses.append("official_date<=?"); arguments.append(filters["date_to"])
        if filters.get("team"):
            clauses.append("(LOWER(away_team_name) LIKE ? OR LOWER(home_team_name) LIKE ?)")
            needle = f"%{str(filters['team']).casefold()}%"; arguments.extend((needle, needle))
        with self.connect() as db:
            games = [dict(row) for row in db.execute(
                f"SELECT * FROM mlb_games WHERE {' AND '.join(clauses)}", arguments)]
            games = self._hydrate_summaries(db, games)
        return filter_and_sort_games(games, filters)

    def _hydrate_summaries(self, db: sqlite3.Connection,
                           games: list[dict]) -> list[dict]:
        if not games:
            return games
        identifiers = [game["game_uuid"] for game in games]
        placeholders = ",".join("?" for _ in identifiers)
        game_by_id = {game["game_uuid"]: game for game in games}
        books = db.execute(f"""WITH ranked AS (
          SELECT s.*,ROW_NUMBER() OVER(PARTITION BY s.canonical_game_uuid
            ORDER BY s.quote_timestamp DESC,s.retrieval_timestamp DESC) rank
          FROM mlb_sportsbook_snapshots s JOIN mlb_games g
            ON g.game_uuid=s.canonical_game_uuid
          WHERE s.canonical_game_uuid IN ({placeholders})
            AND s.quote_timestamp<g.scheduled_start_utc)
          SELECT * FROM ranked WHERE rank=1""", identifiers).fetchall()
        book_by_game = {row["canonical_game_uuid"]: dict(row) for row in books}
        trade_rows = db.execute(f"""WITH ranked AS (
          SELECT t.*,
            ROW_NUMBER() OVER(PARTITION BY canonical_game_uuid,selected_team_id
              ORDER BY risk_usd DESC,trade_timestamp_utc) side_risk_rank,
            ROW_NUMBER() OVER(PARTITION BY canonical_game_uuid,selected_team_id
              ORDER BY trade_timestamp_utc) side_first_rank,
            ROW_NUMBER() OVER(PARTITION BY canonical_game_uuid,selected_team_id
              ORDER BY trade_timestamp_utc DESC) side_last_rank
          FROM mlb_trade_observations t
          WHERE canonical_game_uuid IN ({placeholders}) AND legacy_incomplete=0
            AND pregame_classification='PREGAME')
          SELECT canonical_game_uuid,selected_team_id,COUNT(*) trade_count,
            ROUND(SUM(risk_usd),2) dollars,
            MAX(CASE WHEN side_risk_rank=1 THEN risk_usd END) largest_amount,
            MAX(CASE WHEN side_risk_rank=1 THEN execution_price END) largest_price,
            MAX(CASE WHEN side_risk_rank=1 THEN trade_timestamp_utc END) largest_timestamp,
            MAX(CASE WHEN side_risk_rank=1 THEN observation_uuid END) largest_observation_uuid,
            MAX(CASE WHEN side_first_rank=1 THEN execution_price END) earliest_price,
            MAX(CASE WHEN side_first_rank=1 THEN trade_timestamp_utc END) first_timestamp,
            MAX(CASE WHEN side_last_rank=1 THEN execution_price END) final_pregame_price,
            MAX(CASE WHEN side_last_rank=1 THEN trade_timestamp_utc END) final_timestamp
          FROM ranked GROUP BY canonical_game_uuid,selected_team_id""", identifiers).fetchall()
        sides: dict[str, dict[str, dict]] = {}
        for row in trade_rows:
            sides.setdefault(row["canonical_game_uuid"], {})[row["selected_team_id"]] = dict(row)
        legacy_counts = dict(db.execute(f"""SELECT canonical_game_uuid,COUNT(*) FROM mlb_trade_observations
          WHERE canonical_game_uuid IN ({placeholders}) AND legacy_incomplete=1
          GROUP BY canonical_game_uuid""", identifiers))
        for game_uuid, game in game_by_id.items():
            game.update(derive_aggregated_game_summary(
                game, sides.get(game_uuid, {}), book_by_game.get(game_uuid),
                int(legacy_counts.get(game_uuid, 0))))
        return games

    def research_page(self, filters: dict | None = None, page: int = 1,
                      per_page: int = 25) -> dict:
        page, per_page = max(1, page), min(100, max(1, per_page))
        games = self.research_games(filters)
        total = len(games); start = (page - 1) * per_page
        return {"generated_at": utc_now(), "page": page, "per_page": per_page,
                "count": total, "total": total, "pages": (total + per_page - 1) // per_page,
                "games": games[start:start + per_page],
                "statistics": filtered_statistics(games)}

    def game_detail(self, game_uuid: str) -> dict | None:
        games = self.research_games({"game_uuid": game_uuid})
        return games[0] if games else None

    def timeline(self, game_uuid: str, *, page: int = 1, per_page: int = 100,
                 summarized: bool = True, bucket_minutes: int = 15) -> dict | None:
        page, per_page = max(1, page), min(250, max(1, per_page))
        bucket_minutes = min(60, max(1, bucket_minutes))
        with self.connect() as db:
            game = db.execute("SELECT game_uuid FROM mlb_games WHERE game_uuid=?", (game_uuid,)).fetchone()
            if not game:
                return None
            if summarized:
                bucket_seconds = bucket_minutes * 60
                rows = [dict(row) for row in db.execute("""SELECT
                  (CAST(strftime('%s',substr(trade_timestamp_utc,1,19)) AS INTEGER)/?)*? bucket_epoch,
                  selected_team_id,COUNT(*) trade_count,ROUND(SUM(risk_usd),2) dollars,
                  ROUND(MAX(risk_usd),2) largest_trade,
                  ROUND(SUM(execution_price*risk_usd)/SUM(risk_usd),6) weighted_price,
                  MIN(trade_timestamp_utc) first_timestamp,MAX(trade_timestamp_utc) last_timestamp
                  FROM mlb_trade_observations WHERE canonical_game_uuid=?
                    AND legacy_incomplete=0 AND pregame_classification='PREGAME'
                  GROUP BY bucket_epoch,selected_team_id ORDER BY bucket_epoch,selected_team_id""",
                  (bucket_seconds, bucket_seconds, game_uuid))]
            else:
                rows = [dict(row) for row in db.execute("""SELECT observation_uuid,
                  trade_timestamp_utc,selected_team_id,selected_team,risk_usd,execution_price
                  FROM mlb_trade_observations WHERE canonical_game_uuid=?
                    AND legacy_incomplete=0 AND pregame_classification='PREGAME'
                  ORDER BY trade_timestamp_utc LIMIT ? OFFSET ?""",
                  (game_uuid, per_page, (page - 1) * per_page))]
            total = (len(rows) if summarized else db.execute("""SELECT COUNT(*)
              FROM mlb_trade_observations WHERE canonical_game_uuid=? AND legacy_incomplete=0
                AND pregame_classification='PREGAME'""", (game_uuid,)).fetchone()[0])
        if summarized:
            start = (page - 1) * per_page; paged = rows[start:start + per_page]
        else:
            paged = rows
        return {"game_uuid": game_uuid, "mode": "summary" if summarized else "detail",
                "bucket_minutes": bucket_minutes if summarized else None,
                "page": page, "per_page": per_page, "total": total,
                "pages": (total + per_page - 1) // per_page, "rows": paged}

    def summary(self) -> dict:
        games = self.research_games()
        complete = [game for game in games if game["data_completeness"] == "COMPLETE"]
        incomplete = [game for game in games if game["data_completeness"] != "COMPLETE"]
        largest_record = record(complete, "largest_buy_won")
        favorite_games = [game for game in complete if not game["largest_buy_backed_underdog"]]
        underdog_games = [game for game in complete if game["largest_buy_backed_underdog"]]
        return {
            "generated_at": utc_now(), "complete_games": len(complete),
            "incomplete_games": len(incomplete), "largest_pregame_buy": largest_record,
            "favorite_backed_largest_buy": record(favorite_games, "largest_buy_won"),
            "underdog_backed_largest_buy": record(underdog_games, "largest_buy_won"),
            "entry_price_buckets": bucket_records(underdog_games, "largest_buy_execution_price", price_bucket),
            "money_concentration_buckets": bucket_records(
                underdog_games, "underdog_money_share", concentration_bucket),
            "combination_table": combination_records(underdog_games),
            "games": games,
        }


def split_matchup(title: Any) -> tuple[str | None, str | None]:
    text = str(title or "")
    for separator in (" vs. ", " vs ", " @ "):
        if separator in text:
            away, home = text.split(separator, 1)
            return away.strip(), home.strip()
    return None, None


def parse_mlb_game(raw: dict, observed_at: str) -> dict | None:
    try:
        game_pk = int(raw["gamePk"])
        away_name = raw["teams"]["away"]["team"]["name"]
        home_name = raw["teams"]["home"]["team"]["name"]
        away_id = next(team_id for team_id, name, _ in TEAM_ROWS if normalized(name) == normalized(away_name))
        home_id = next(team_id for team_id, name, _ in TEAM_ROWS if normalized(name) == normalized(home_name))
        scheduled = parse_time(raw["gameDate"]).isoformat()
    except (KeyError, TypeError, ValueError, StopIteration, AttributeError):
        return None
    status_data = raw.get("status") or {}
    abstract = str(status_data.get("abstractGameState") or "UNKNOWN").upper()
    detailed = status_data.get("detailedState")
    final = abstract == "FINAL"
    away_score = raw["teams"]["away"].get("score")
    home_score = raw["teams"]["home"].get("score")
    winner = away_id if final and away_score is not None and home_score is not None and away_score > home_score \
        else home_id if final and away_score is not None and home_score is not None and home_score > away_score else None
    double_code = str(raw.get("doubleHeader") or "N")
    game_number = int(raw.get("gameNumber") or 1)
    status_lower = str(detailed or "").casefold()
    return {
        "game_uuid": stable_uuid("mlb-game", str(game_pk)), "mlb_game_pk": game_pk,
        "official_date": str(raw.get("officialDate") or scheduled[:10]),
        "away_team_id": away_id, "away_team_name": away_name,
        "home_team_id": home_id, "home_team_name": home_name,
        "scheduled_start_utc": scheduled, "actual_start_utc": None,
        "status": abstract, "detailed_status": detailed, "doubleheader_code": double_code,
        "game_number": game_number,
        "doubleheader_identifier": f"{raw.get('officialDate')}:{away_id}:{home_id}:{game_number}" if double_code != "N" else None,
        "series_game_number": raw.get("seriesGameNumber"),
        "postponed": int("postpon" in status_lower), "rescheduled": 0,
        "original_start_utc": None, "away_score": away_score, "home_score": home_score,
        "final_winner_team_id": winner, "completion_timestamp": observed_at if final else None,
        "source": "MLB_STATS_API", "source_url": f"https://www.mlb.com/gameday/{game_pk}",
        "first_observed": observed_at, "last_observed": observed_at, "schedule_version": 1,
    }


def parse_sportsbook_books(event: dict) -> list[dict]:
    output = []
    for bookmaker in event.get("bookmakers", []):
        market = next((item for item in bookmaker.get("markets", []) if item.get("key") == "h2h"), None)
        if not market:
            continue
        prices = {item.get("name"): item.get("price") for item in market.get("outcomes", [])}
        try:
            away_odds = float(prices[event["away_team"]])
            home_odds = float(prices[event["home_team"]])
            if away_odds <= 1 or home_odds <= 1:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        away_raw, home_raw = 1 / away_odds, 1 / home_odds
        total = away_raw + home_raw
        output.append({
            "bookmaker": bookmaker.get("key") or bookmaker.get("title") or "unknown",
            "quote_timestamp": market.get("last_update") or bookmaker.get("last_update") or utc_now(),
            "away_odds": away_odds, "home_odds": home_odds,
            "away_raw_probability": away_raw, "home_raw_probability": home_raw,
            "away_vig_free_probability": away_raw / total,
            "home_vig_free_probability": home_raw / total,
        })
    return output


def derive_game_summary(game: dict, trades: list[dict], book: dict | None) -> dict:
    missing = []
    if game.get("status") != "FINAL" or not game.get("final_winner_team_id"):
        missing.append("AUTHORITATIVE_FINAL_RESULT")
    if not book:
        missing.append("PREGAME_SPORTSBOOK_SNAPSHOT")
    if not trades:
        missing.append("COMPLETE_PREGAME_TRADE_EVIDENCE")
    favorite = book.get("favorite_team_id") if book else None
    underdog = book.get("underdog_team_id") if book else None
    largest = trades[0] if trades else None
    favorite_trades = [trade for trade in trades if trade["selected_team_id"] == favorite]
    underdog_trades = [trade for trade in trades if trade["selected_team_id"] == underdog]
    favorite_dollars = sum(trade["risk_usd"] for trade in favorite_trades)
    underdog_dollars = sum(trade["risk_usd"] for trade in underdog_trades)
    total = favorite_dollars + underdog_dollars
    start = parse_time(game.get("scheduled_start_utc"))
    trade_time = parse_time(largest["trade_timestamp_utc"]) if largest else None
    return {
        "sportsbook_favorite_team_id": favorite, "sportsbook_underdog_team_id": underdog,
        "largest_pregame_buy": largest, "largest_buy_team_id": largest["selected_team_id"] if largest else None,
        "largest_buy_amount": largest["risk_usd"] if largest else None,
        "largest_buy_execution_price": largest["execution_price"] if largest else None,
        "largest_buy_timestamp": largest["trade_timestamp_utc"] if largest else None,
        "minutes_before_first_pitch": round((start - trade_time).total_seconds() / 60, 2) if start and trade_time else None,
        "favorite_pregame_dollars": round(favorite_dollars, 2),
        "underdog_pregame_dollars": round(underdog_dollars, 2),
        "favorite_trade_count": len(favorite_trades), "underdog_trade_count": len(underdog_trades),
        "underdog_money_share": underdog_dollars / total if total else None,
        "favorite_money_share": favorite_dollars / total if total else None,
        "largest_buy_backed_underdog": largest["selected_team_id"] == underdog if largest and underdog else None,
        "largest_buy_won": largest["selected_team_id"] == game.get("final_winner_team_id")
            if largest and game.get("final_winner_team_id") else None,
        "data_completeness": "COMPLETE" if not missing else "INCOMPLETE",
        "missing_evidence": missing,
    }


def derive_aggregated_game_summary(game: dict, sides: dict[str, dict],
                                   book: dict | None, legacy_count: int) -> dict:
    """Build a compact research case from server-side evidence aggregates."""
    away_id, home_id = game["away_team_id"], game["home_team_id"]
    away = sides.get(away_id, {})
    home = sides.get(home_id, {})
    trustworthy_count = int(away.get("trade_count") or 0) + int(home.get("trade_count") or 0)
    total_dollars = float(away.get("dollars") or 0) + float(home.get("dollars") or 0)
    candidates = [(away_id, away), (home_id, home)]
    candidates = [(team_id, row) for team_id, row in candidates if row.get("largest_amount") is not None]
    largest_team, largest = max(candidates, key=lambda item: (item[1]["largest_amount"],
                                 item[1].get("largest_timestamp") or "")) if candidates else (None, {})
    favorite = book.get("favorite_team_id") if book else None
    underdog = book.get("underdog_team_id") if book else None
    favorite_row, underdog_row = sides.get(favorite, {}), sides.get(underdog, {})
    favorite_dollars = float(favorite_row.get("dollars") or 0)
    underdog_dollars = float(underdog_row.get("dollars") or 0)
    known_side_total = favorite_dollars + underdog_dollars
    start = parse_time(game.get("actual_start_utc") or game.get("scheduled_start_utc"))
    largest_time = parse_time(largest.get("largest_timestamp")) if largest else None
    missing = []
    if game.get("status") != "FINAL" or not game.get("final_winner_team_id"):
        missing.append("AUTHORITATIVE_FINAL_RESULT")
    if not book:
        missing.append("PREGAME_SPORTSBOOK_SNAPSHOT")
    if not trustworthy_count:
        missing.append("COMPLETE_PREGAME_TRADE_EVIDENCE")
    if trustworthy_count:
        completeness = "COMPLETE" if not missing else "INCOMPLETE"
    else:
        completeness = "LEGACY_INCOMPLETE" if legacy_count else "INCOMPLETE"
    winner = game.get("final_winner_team_id")

    def side_summary(team_id: str, row: dict) -> dict:
        return {"team_id": team_id, "team_name": game["away_team_name"] if team_id == away_id else game["home_team_name"],
                "trade_count": int(row.get("trade_count") or 0), "dollars": float(row.get("dollars") or 0),
                "largest_amount": row.get("largest_amount"), "largest_execution_price": row.get("largest_price"),
                "largest_timestamp": row.get("largest_timestamp"), "earliest_price": row.get("earliest_price"),
                "final_pregame_price": row.get("final_pregame_price"),
                "first_timestamp": row.get("first_timestamp"), "final_timestamp": row.get("final_timestamp"),
                "price_movement": round(float(row["final_pregame_price"]) - float(row["earliest_price"]), 6)
                    if row.get("final_pregame_price") is not None and row.get("earliest_price") is not None else None}

    return {
        "sportsbook_favorite_team_id": favorite, "sportsbook_underdog_team_id": underdog,
        "sportsbook_source_count": int(book.get("source_count") or 0) if book else 0,
        "sportsbook_quote_timestamp": book.get("quote_timestamp") if book else None,
        "sportsbook_away_probability": book.get("consensus_mean_away") if book else None,
        "sportsbook_home_probability": book.get("consensus_mean_home") if book else None,
        "away_pregame": side_summary(away_id, away), "home_pregame": side_summary(home_id, home),
        "largest_pregame_buy": {"observation_uuid": largest.get("largest_observation_uuid"),
            "selected_team_id": largest_team, "risk_usd": largest.get("largest_amount"),
            "execution_price": largest.get("largest_price"), "trade_timestamp_utc": largest.get("largest_timestamp")}
            if largest_team else None,
        "largest_buy_team_id": largest_team, "largest_buy_amount": largest.get("largest_amount"),
        "largest_buy_execution_price": largest.get("largest_price"),
        "largest_buy_timestamp": largest.get("largest_timestamp"),
        "minutes_before_first_pitch": round((start - largest_time).total_seconds() / 60, 2)
            if start and largest_time else None,
        "favorite_pregame_dollars": round(favorite_dollars, 2),
        "underdog_pregame_dollars": round(underdog_dollars, 2),
        "favorite_trade_count": int(favorite_row.get("trade_count") or 0),
        "underdog_trade_count": int(underdog_row.get("trade_count") or 0),
        "total_pregame_dollars": round(total_dollars, 2), "trustworthy_pregame_trade_count": trustworthy_count,
        "underdog_trade_share": int(underdog_row.get("trade_count") or 0) / trustworthy_count if trustworthy_count else None,
        "legacy_observation_count": legacy_count,
        "underdog_money_share": underdog_dollars / known_side_total if known_side_total else None,
        "favorite_money_share": favorite_dollars / known_side_total if known_side_total else None,
        "largest_buy_backed_underdog": largest_team == underdog if largest_team and underdog else None,
        "largest_buy_won": largest_team == winner if largest_team and winner else None,
        "sportsbook_favorite_won": favorite == winner if favorite and winner else None,
        "underdog_won": underdog == winner if underdog and winner else None,
        "data_completeness": completeness, "missing_evidence": missing,
    }


def filter_and_sort_games(games: list[dict], filters: dict) -> list[dict]:
    completeness = str(filters.get("completeness") or "").upper()
    if completeness in {"COMPLETE", "INCOMPLETE", "LEGACY_INCOMPLETE"}:
        games = [game for game in games if game["data_completeness"] == completeness]
    if str(filters.get("pregame_only") or "").lower() in {"1", "true", "yes"}:
        games = [game for game in games if game["trustworthy_pregame_trade_count"] > 0]
    side = str(filters.get("side") or "").upper()
    if side == "FAVORITE": games = [game for game in games if game["largest_buy_backed_underdog"] is False]
    if side == "UNDERDOG": games = [game for game in games if game["largest_buy_backed_underdog"] is True]
    outcome = str(filters.get("outcome") or "").upper()
    outcome_map = {"LARGEST_BUY_WON": ("largest_buy_won", True), "LARGEST_BUY_LOST": ("largest_buy_won", False),
                   "FAVORITE_WON": ("sportsbook_favorite_won", True), "UNDERDOG_WON": ("underdog_won", True)}
    if outcome in outcome_map:
        field, value = outcome_map[outcome]; games = [game for game in games if game.get(field) is value]
    winner = str(filters.get("winner") or "").casefold().strip()
    if winner:
        games = [game for game in games if winner in (game["away_team_name"] if game.get("final_winner_team_id") == game["away_team_id"]
                 else game["home_team_name"] if game.get("final_winner_team_id") == game["home_team_id"] else "").casefold()]
    for field, low_key, high_key in (("largest_buy_execution_price", "price_min", "price_max"),
                                     ("underdog_money_share", "concentration_min", "concentration_max")):
        low, high = filters.get(low_key), filters.get(high_key)
        if low is not None: games = [game for game in games if game.get(field) is not None and game[field] >= float(low)]
        if high is not None: games = [game for game in games if game.get(field) is not None and game[field] <= float(high)]
    sort = str(filters.get("sort") or "date_desc")
    specs = {"date_desc": (lambda g: (g.get("official_date") or "", g.get("scheduled_start_utc") or ""), True),
             "date_asc": (lambda g: (g.get("official_date") or "", g.get("scheduled_start_utc") or ""), False),
             "largest_buy_desc": (lambda g: g.get("largest_buy_amount") or -1, True),
             "underdog_share_desc": (lambda g: g.get("underdog_money_share") or -1, True),
             "matchup": (lambda g: (g["away_team_name"], g["home_team_name"]), False)}
    key, reverse = specs.get(sort, specs["date_desc"])
    return sorted(games, key=key, reverse=reverse)


def filtered_statistics(games: list[dict]) -> dict:
    complete = [game for game in games if game["data_completeness"] == "COMPLETE"]
    numeric_shares = [game["underdog_money_share"] for game in games if game.get("underdog_money_share") is not None]
    numeric_prices = [game["largest_buy_execution_price"] for game in games if game.get("largest_buy_execution_price") is not None]
    return {"sample_size": len(games), "complete_cases": len(complete),
            "largest_buy_record": record(complete, "largest_buy_won"),
            "favorite_largest_buy_record": record([g for g in complete if g["largest_buy_backed_underdog"] is False], "largest_buy_won"),
            "underdog_largest_buy_record": record([g for g in complete if g["largest_buy_backed_underdog"] is True], "largest_buy_won"),
            "sportsbook_favorite_record": record(complete, "sportsbook_favorite_won"),
            "median_underdog_money_share": statistics.median(numeric_shares) if numeric_shares else None,
            "median_largest_buy_price": statistics.median(numeric_prices) if numeric_prices else None}


def record(games: list[dict], field: str) -> dict:
    wins = sum(game.get(field) is True for game in games)
    losses = sum(game.get(field) is False for game in games)
    return {"wins": wins, "losses": losses, "games": wins + losses,
            "win_percentage": round(wins / (wins + losses) * 100, 2) if wins + losses else None}


def price_bucket(value: float | None) -> str:
    if value is None: return "UNKNOWN"
    if value < .20: return "<20c"
    if value < .30: return "20-29c"
    if value < .40: return "30-39c"
    if value < .50: return "40-49c"
    return "50c+"


def concentration_bucket(value: float | None) -> str:
    if value is None: return "UNKNOWN"
    percentage = value * 100
    if percentage < 50: return "<50%"
    if percentage < 60: return "50-59%"
    if percentage < 70: return "60-69%"
    if percentage < 80: return "70-79%"
    if percentage < 90: return "80-89%"
    return "90-100%"


def bucket_records(games: list[dict], field: str, bucket_function) -> dict:
    buckets: dict[str, list] = {}
    for game in games:
        buckets.setdefault(bucket_function(game.get(field)), []).append(game)
    return {name: record(rows, "largest_buy_won") for name, rows in buckets.items()}


def combination_records(games: list[dict]) -> dict:
    output: dict[str, list] = {}
    for game in games:
        key = f"{price_bucket(game.get('largest_buy_execution_price'))} | {concentration_bucket(game.get('underdog_money_share'))}"
        output.setdefault(key, []).append(game)
    return {key: record(rows, "largest_buy_won") for key, rows in output.items()}


def fetch_schedule(start_date: date, end_date: date, session=requests) -> dict:
    response = session.get(MLB_SCHEDULE_URL, params={"sportId": 1,
                           "startDate": start_date.isoformat(), "endDate": end_date.isoformat(),
                           "hydrate": "team,linescore"}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("MLB schedule returned non-object JSON")
    return payload


def fetch_sportsbook(session=requests) -> list:
    load_dotenv(HERE / ".env")
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY is not configured")
    response = session.get(ODDS_API_URL, params={"apiKey": key, "regions": "us",
                           "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso"},
                           timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Odds API returned non-list JSON")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "sync-schedule", "sync-odds", "sync-all",
                                             "migrate-legacy", "summary", "status"))
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    args = parser.parse_args(argv)
    registry = MLBResearchRegistry(args.db)
    today = datetime.now(timezone.utc).date()
    if args.command in {"sync-schedule", "sync-all"}:
        payload = fetch_schedule(args.start_date or today - timedelta(days=7),
                                 args.end_date or today + timedelta(days=7))
        print(json.dumps({"schedule": registry.ingest_schedule(payload)}, indent=2))
    if args.command in {"sync-odds", "sync-all"}:
        print(json.dumps({"sportsbook": registry.ingest_sportsbook(fetch_sportsbook())}, indent=2))
    if args.command == "migrate-legacy":
        print(json.dumps(registry.migrate_legacy(), indent=2))
    elif args.command == "summary":
        print(json.dumps(registry.summary(), indent=2, sort_keys=True))
    elif args.command in {"init", "status"}:
        with registry.connect() as db:
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("mlb_games", "mlb_schedule_revisions",
                                    "mlb_trade_observations", "mlb_sportsbook_snapshots",
                                    "mlb_link_rejections")}
        print(json.dumps({"database": str(registry.db_path.resolve()), **counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
