#!/usr/bin/env python3
"""Canonical, observation-only NFL schedule and source-link registry.

This module never creates paper positions or real orders. External records are
linked only when their teams, orientation, season type, kickoff, identifiers,
and market type unambiguously agree with one canonical NFL game.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "sports_registry.db"
PRODUCTION_DB = HERE / "sports_registry_production.db"
DEFAULT_CONFIG = HERE / "nfl_config.json"
SCHEMA_VERSION = 4
MATCHER_VERSION = 2
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"
POLYMARKET_US_EVENTS = "https://gateway.polymarket.us/v1/events"
SUPPORTED_SOURCE_TYPES = {
    "OFFICIAL_SCHEDULE", "ODDS_API", "POLYMARKET_US", "GAME_FLOW_STREAM"
}
REJECTION_CODES = {
    "NO_CANONICAL_GAME", "MULTIPLE_CANONICAL_GAMES", "UNKNOWN_TEAM",
    "AMBIGUOUS_TEAM", "KICKOFF_MISSING", "KICKOFF_MISMATCH",
    "HOME_AWAY_CONFLICT", "SEASON_TYPE_CONFLICT", "IDENTIFIER_MISSING",
    "MALFORMED_SOURCE_DATA",
}


TEAM_ROWS = [
    ("ARI", "Arizona", "Cardinals", "Arizona Cardinals", ["ARI", "Arizona Cardinals", "Cardinals"]),
    ("ATL", "Atlanta", "Falcons", "Atlanta Falcons", ["ATL", "Atlanta Falcons", "Falcons"]),
    ("BAL", "Baltimore", "Ravens", "Baltimore Ravens", ["BAL", "Baltimore Ravens", "Ravens"]),
    ("BUF", "Buffalo", "Bills", "Buffalo Bills", ["BUF", "Buffalo Bills", "Bills"]),
    ("CAR", "Carolina", "Panthers", "Carolina Panthers", ["CAR", "Carolina Panthers", "Panthers"]),
    ("CHI", "Chicago", "Bears", "Chicago Bears", ["CHI", "Chicago Bears", "Bears"]),
    ("CIN", "Cincinnati", "Bengals", "Cincinnati Bengals", ["CIN", "Cincinnati Bengals", "Bengals"]),
    ("CLE", "Cleveland", "Browns", "Cleveland Browns", ["CLE", "Cleveland Browns", "Browns"]),
    ("DAL", "Dallas", "Cowboys", "Dallas Cowboys", ["DAL", "Dallas Cowboys", "Cowboys"]),
    ("DEN", "Denver", "Broncos", "Denver Broncos", ["DEN", "Denver Broncos", "Broncos"]),
    ("DET", "Detroit", "Lions", "Detroit Lions", ["DET", "Detroit Lions", "Lions"]),
    ("GB", "Green Bay", "Packers", "Green Bay Packers", ["GB", "GNB", "Green Bay Packers", "Packers"]),
    ("HOU", "Houston", "Texans", "Houston Texans", ["HOU", "Houston Texans", "Texans"]),
    ("IND", "Indianapolis", "Colts", "Indianapolis Colts", ["IND", "Indianapolis Colts", "Colts"]),
    ("JAX", "Jacksonville", "Jaguars", "Jacksonville Jaguars", ["JAX", "JAC", "Jacksonville Jaguars", "Jaguars", "Jags"]),
    ("KC", "Kansas City", "Chiefs", "Kansas City Chiefs", ["KC", "KAN", "Kansas City Chiefs", "Chiefs"]),
    ("LV", "Las Vegas", "Raiders", "Las Vegas Raiders", ["LV", "LVR", "Las Vegas Raiders", "Oakland Raiders", "Raiders"]),
    ("LAC", "Los Angeles", "Chargers", "Los Angeles Chargers", ["LAC", "LA Chargers", "Los Angeles Chargers", "San Diego Chargers", "Chargers"]),
    ("LAR", "Los Angeles", "Rams", "Los Angeles Rams", ["LAR", "LA Rams", "Los Angeles Rams", "St. Louis Rams", "Rams"]),
    ("MIA", "Miami", "Dolphins", "Miami Dolphins", ["MIA", "Miami Dolphins", "Dolphins"]),
    ("MIN", "Minnesota", "Vikings", "Minnesota Vikings", ["MIN", "Minnesota Vikings", "Vikings"]),
    ("NE", "New England", "Patriots", "New England Patriots", ["NE", "NWE", "New England Patriots", "Patriots"]),
    ("NO", "New Orleans", "Saints", "New Orleans Saints", ["NO", "NOR", "New Orleans Saints", "Saints"]),
    ("NYG", "New York", "Giants", "New York Giants", ["NYG", "NY Giants", "New York Giants", "Giants"]),
    ("NYJ", "New York", "Jets", "New York Jets", ["NYJ", "NY Jets", "New York Jets", "Jets"]),
    ("PHI", "Philadelphia", "Eagles", "Philadelphia Eagles", ["PHI", "Philadelphia Eagles", "Eagles"]),
    ("PIT", "Pittsburgh", "Steelers", "Pittsburgh Steelers", ["PIT", "Pittsburgh Steelers", "Steelers"]),
    ("SEA", "Seattle", "Seahawks", "Seattle Seahawks", ["SEA", "Seattle Seahawks", "Seahawks"]),
    ("SF", "San Francisco", "49ers", "San Francisco 49ers", ["SF", "SFO", "San Francisco 49ers", "49ers", "Niners"]),
    ("TB", "Tampa Bay", "Buccaneers", "Tampa Bay Buccaneers", ["TB", "TAM", "Tampa Bay Buccaneers", "Buccaneers", "Bucs"]),
    ("TEN", "Tennessee", "Titans", "Tennessee Titans", ["TEN", "Tennessee Titans", "Titans"]),
    ("WAS", "Washington", "Commanders", "Washington Commanders", ["WAS", "WSH", "Washington Commanders", "Washington Football Team", "Washington Redskins", "Commanders"]),
]

TEAM_TIMEZONES = {
    "ARI": "America/Phoenix", "ATL": "America/New_York", "BAL": "America/New_York",
    "BUF": "America/New_York", "CAR": "America/New_York", "CHI": "America/Chicago",
    "CIN": "America/New_York", "CLE": "America/New_York", "DAL": "America/Chicago",
    "DEN": "America/Denver", "DET": "America/New_York", "GB": "America/Chicago",
    "HOU": "America/Chicago", "IND": "America/New_York", "JAX": "America/New_York",
    "KC": "America/Chicago", "LV": "America/Los_Angeles", "LAC": "America/Los_Angeles",
    "LAR": "America/Los_Angeles", "MIA": "America/New_York", "MIN": "America/Chicago",
    "NE": "America/New_York", "NO": "America/Chicago", "NYG": "America/New_York",
    "NYJ": "America/New_York", "PHI": "America/New_York", "PIT": "America/New_York",
    "SEA": "America/Los_Angeles", "SF": "America/Los_Angeles", "TB": "America/New_York",
    "TEN": "America/Chicago", "WAS": "America/New_York",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def normalized_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def schedule_local_time(kickoff: datetime, home_team_name: str,
                        venue: str, neutral_site: bool) -> str:
    if neutral_site:
        zone_name = ("America/New_York" if "hall of fame" in normalized_text(venue)
                     or "tom benson" in normalized_text(venue) else "UTC")
    else:
        team_id = next((row[0] for row in TEAM_ROWS
                        if normalized_text(row[3]) == normalized_text(home_team_name)), None)
        zone_name = TEAM_TIMEZONES.get(team_id, "UTC")
    return kickoff.astimezone(ZoneInfo(zone_name)).isoformat()


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    defaults = {
        "nfl_schedule_sync_enabled": True,
        "nfl_season": 2026,
        "enabled_season_types": ["HOF", "PRE", "REG"],
        "hall_of_fame_event_ids": [],
        "kickoff_match_tolerance_seconds": 1800,
        "sportsbook_quote_max_age_seconds": 3600,
        "schedule_refresh_interval_seconds": 21600,
        "result_refresh_interval_seconds": 1800,
        "adapters": {"espn_schedule": True, "odds_api": True, "polymarket_us": True},
    }
    if path.exists():
        supplied = json.loads(path.read_text(encoding="utf-8"))
        defaults.update(supplied)
        defaults["adapters"] = {**defaults["adapters"], **supplied.get("adapters", {})}
    return defaults


@dataclass(frozen=True)
class LinkResult:
    accepted: bool
    game_uuid: Optional[str]
    rejection_reason: Optional[str]
    evidence: dict
    observation_uuid: str


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class NFLRegistry:
    def __init__(self, db_path: Path | str = DEFAULT_DB, config_path: Path = DEFAULT_CONFIG,
                 environment: str = "development"):
        if environment not in {"development", "production", "test"}:
            raise ValueError("registry environment must be development, production, or test")
        self.environment = environment
        self.db_path = Path(db_path)
        self.config = load_config(config_path)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path, timeout=30, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_meta (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS teams (
              team_id TEXT PRIMARY KEY, city TEXT NOT NULL, nickname TEXT NOT NULL,
              full_name TEXT NOT NULL UNIQUE, aliases_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS games (
              game_uuid TEXT PRIMARY KEY, canonical_game_id TEXT NOT NULL UNIQUE,
              league TEXT NOT NULL CHECK(league='NFL'), season INTEGER NOT NULL,
              season_type TEXT NOT NULL CHECK(season_type IN ('HOF','PRE','REG','POST')),
              week TEXT NOT NULL, away_team_id TEXT NOT NULL REFERENCES teams(team_id),
              away_team_name TEXT NOT NULL, home_team_id TEXT NOT NULL REFERENCES teams(team_id),
              home_team_name TEXT NOT NULL, scheduled_kickoff_utc TEXT NOT NULL,
              scheduled_kickoff_local TEXT NOT NULL, venue TEXT, neutral_site INTEGER NOT NULL DEFAULT 0,
              official_source_identifier TEXT NOT NULL, official_source_name TEXT NOT NULL,
              official_source_url TEXT, game_status TEXT NOT NULL, schedule_version INTEGER NOT NULL DEFAULT 1,
              first_observed TEXT NOT NULL, last_updated TEXT NOT NULL,
              postponed INTEGER NOT NULL DEFAULT 0, rescheduled INTEGER NOT NULL DEFAULT 0,
              previous_kickoff_utc TEXT, final_winner_team_id TEXT REFERENCES teams(team_id),
              away_score INTEGER, home_score INTEGER, completion_timestamp TEXT,
              result_source TEXT, source_result_id TEXT,
              largest_buy_side_won INTEGER,
              UNIQUE(official_source_name, official_source_identifier)
            );
            CREATE INDEX IF NOT EXISTS games_lookup ON games(season,season_type,away_team_id,home_team_id,scheduled_kickoff_utc);
            CREATE TABLE IF NOT EXISTS source_links (
              source_link_uuid TEXT PRIMARY KEY, canonical_game_uuid TEXT REFERENCES games(game_uuid),
              source_type TEXT NOT NULL, source_event_id TEXT NOT NULL, source_market_id TEXT,
              source_condition_id TEXT, source_token_outcome_ids_json TEXT,
              source_home_team TEXT, source_away_team TEXT, source_kickoff TEXT,
              normalized_home_team_id TEXT, normalized_away_team_id TEXT,
              kickoff_difference_seconds INTEGER, match_status TEXT NOT NULL,
              match_confidence TEXT NOT NULL, match_evidence_json TEXT NOT NULL,
              rejection_reason TEXT, first_observed TEXT NOT NULL, last_observed TEXT NOT NULL,
              market_slug TEXT, event_slug TEXT, question TEXT, outcome_names_json TEXT,
              accepting_orders INTEGER, active INTEGER, closed INTEGER,
              bid REAL, ask REAL, last_trade REAL, retrieval_timestamp TEXT,
              settlement_metadata_json TEXT,
              UNIQUE(source_type,source_event_id,source_market_id)
            );
            CREATE TABLE IF NOT EXISTS observations (
              observation_uuid TEXT PRIMARY KEY, scan_uuid TEXT NOT NULL,
              canonical_game_uuid TEXT REFERENCES games(game_uuid), source_type TEXT NOT NULL,
              source_record_id TEXT NOT NULL, observed_timestamp TEXT NOT NULL,
              normalized_teams_json TEXT NOT NULL, scheduled_kickoff TEXT,
              match_accepted INTEGER NOT NULL, rejection_reason TEXT,
              matching_evidence_json TEXT NOT NULL, raw_identifiers_json TEXT NOT NULL,
              source_quote_timestamps_json TEXT NOT NULL, market_status_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS observations_scan ON observations(scan_uuid,observed_timestamp);
            CREATE TABLE IF NOT EXISTS sportsbook_quotes (
              quote_uuid TEXT PRIMARY KEY, source_link_uuid TEXT NOT NULL REFERENCES source_links(source_link_uuid),
              bookmaker TEXT NOT NULL, bookmaker_last_update TEXT, away_price REAL,
              home_price REAL, retrieval_timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS game_flow_activity (
              activity_uuid TEXT PRIMARY KEY, canonical_game_uuid TEXT NOT NULL REFERENCES games(game_uuid),
              source_trade_id TEXT NOT NULL UNIQUE, team_id TEXT NOT NULL REFERENCES teams(team_id),
              amount_usd REAL NOT NULL, execution_price REAL NOT NULL, observed_timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS result_conflicts (
              conflict_uuid TEXT PRIMARY KEY, canonical_game_uuid TEXT NOT NULL REFERENCES games(game_uuid),
              existing_result_json TEXT NOT NULL, incoming_result_json TEXT NOT NULL,
              detected_at TEXT NOT NULL, resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS simulation_tracks (
              simulation_uuid TEXT PRIMARY KEY, track_name TEXT NOT NULL, track_version INTEGER NOT NULL,
              canonical_game_uuid TEXT NOT NULL REFERENCES games(game_uuid), selected_team_id TEXT,
              selection_timestamp TEXT NOT NULL, source_values_json TEXT NOT NULL,
              hypothetical_entry_price REAL, final_winner_team_id TEXT,
              result TEXT, hypothetical_cost REAL, hypothetical_payout REAL,
              hypothetical_return REAL, data_quality_flags_json TEXT NOT NULL,
              settled_at TEXT, UNIQUE(track_name,track_version,canonical_game_uuid)
            );
            CREATE TABLE IF NOT EXISTS workflow_runs (
              run_uuid TEXT PRIMARY KEY, environment TEXT NOT NULL, dry_run INTEGER NOT NULL,
              started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
              steps_json TEXT NOT NULL, sanitized_errors_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_snapshots (
              snapshot_uuid TEXT PRIMARY KEY,
              canonical_game_uuid TEXT NOT NULL REFERENCES games(game_uuid),
              source_link_uuid TEXT NOT NULL REFERENCES source_links(source_link_uuid),
              source_type TEXT NOT NULL,
              observed_timestamp TEXT NOT NULL,
              source_values_json TEXT NOT NULL,
              market_status_json TEXT NOT NULL,
              bid REAL, ask REAL, last_trade REAL,
              liquidity REAL,
              bookmaker_count INTEGER
            );
            CREATE INDEX IF NOT EXISTS source_snapshots_game_time
              ON source_snapshots(canonical_game_uuid,source_type,observed_timestamp);
            CREATE TABLE IF NOT EXISTS postgame_research_records (
              record_uuid TEXT PRIMARY KEY,
              canonical_game_uuid TEXT NOT NULL REFERENCES games(game_uuid),
              revision_number INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              revision_reason TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              supersedes_record_uuid TEXT REFERENCES postgame_research_records(record_uuid),
              UNIQUE(canonical_game_uuid,revision_number),
              UNIQUE(canonical_game_uuid,content_hash)
            );
            CREATE TABLE IF NOT EXISTS analyst_note_revisions (
              note_revision_uuid TEXT PRIMARY KEY,
              canonical_game_uuid TEXT NOT NULL REFERENCES games(game_uuid),
              revision_number INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              author TEXT NOT NULL,
              notes_json TEXT NOT NULL,
              supersedes_note_revision_uuid TEXT REFERENCES analyst_note_revisions(note_revision_uuid),
              UNIQUE(canonical_game_uuid,revision_number)
            );
            CREATE TABLE IF NOT EXISTS notification_journal (
              notification_uuid TEXT PRIMARY KEY,
              notification_type TEXT NOT NULL,
              canonical_game_uuid TEXT REFERENCES games(game_uuid),
              reporting_date TEXT,
              research_record_uuid TEXT REFERENCES postgame_research_records(record_uuid),
              warning_code TEXT,
              dedupe_key TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              created_timestamp TEXT NOT NULL,
              attempted_timestamp TEXT NOT NULL,
              delivery_status TEXT NOT NULL,
              telegram_message_id TEXT,
              retry_count INTEGER NOT NULL,
              sanitized_failure_reason TEXT,
              delivered_timestamp TEXT,
              payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS notification_journal_dedupe
              ON notification_journal(dedupe_key,delivery_status,attempted_timestamp);
            CREATE TRIGGER IF NOT EXISTS source_snapshots_no_update
              BEFORE UPDATE ON source_snapshots BEGIN SELECT RAISE(ABORT,'source snapshots are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS source_snapshots_no_delete
              BEFORE DELETE ON source_snapshots BEGIN SELECT RAISE(ABORT,'source snapshots are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS postgame_records_no_update
              BEFORE UPDATE ON postgame_research_records BEGIN SELECT RAISE(ABORT,'research records are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS postgame_records_no_delete
              BEFORE DELETE ON postgame_research_records BEGIN SELECT RAISE(ABORT,'research records are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS analyst_notes_no_update
              BEFORE UPDATE ON analyst_note_revisions BEGIN SELECT RAISE(ABORT,'analyst note revisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS analyst_notes_no_delete
              BEFORE DELETE ON analyst_note_revisions BEGIN SELECT RAISE(ABORT,'analyst note revisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS notification_journal_no_update
              BEFORE UPDATE ON notification_journal BEGIN SELECT RAISE(ABORT,'notification journal is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS notification_journal_no_delete
              BEFORE DELETE ON notification_journal BEGIN SELECT RAISE(ABORT,'notification journal is append-only'); END;
            """)
            current = db.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            if current and int(current[0]) > SCHEMA_VERSION:
                raise RuntimeError("sports registry schema is newer than this code")
            columns = {row[1] for row in db.execute("PRAGMA table_info(source_links)")}
            if "source_values_json" not in columns:
                db.execute("ALTER TABLE source_links ADD COLUMN source_values_json TEXT NOT NULL DEFAULT '{}'")
            stored_env = db.execute("SELECT value FROM schema_meta WHERE key='environment'").fetchone()
            if stored_env and stored_env[0] != self.environment:
                raise RuntimeError(
                    f"registry belongs to {stored_env[0]}, not {self.environment}")
            db.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
            db.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('environment',?)", (self.environment,))
            for team_id, city, nickname, full_name, aliases in TEAM_ROWS:
                db.execute("INSERT OR REPLACE INTO teams VALUES(?,?,?,?,?)",
                           (team_id, city, nickname, full_name, json.dumps(sorted(set(aliases)))))

    def normalize_team(self, value: Any) -> tuple[Optional[str], Optional[str]]:
        needle = normalized_text(value)
        if not needle:
            return None, "UNKNOWN_TEAM"
        matches = []
        with self.connect() as db:
            for row in db.execute("SELECT * FROM teams"):
                candidates = [row["team_id"], row["full_name"], row["city"] + " " + row["nickname"]]
                candidates.extend(json.loads(row["aliases_json"]))
                if needle in {normalized_text(item) for item in candidates}:
                    matches.append(row["team_id"])
        matches = sorted(set(matches))
        if len(matches) == 1:
            return matches[0], None
        return (None, "AMBIGUOUS_TEAM") if len(matches) > 1 else (None, "UNKNOWN_TEAM")

    def upsert_schedule_game(self, game: dict) -> str:
        required = ["source_event_id", "season", "season_type", "week", "away_team",
                    "home_team", "kickoff_utc", "status"]
        if any(game.get(key) in (None, "") for key in required):
            raise ValueError("incomplete schedule row")
        away_id, away_error = self.normalize_team(game["away_team"])
        home_id, home_error = self.normalize_team(game["home_team"])
        if away_error or home_error or away_id == home_id:
            raise ValueError(away_error or home_error or "same team on both sides")
        kickoff = parse_time(game["kickoff_utc"])
        if not kickoff:
            raise ValueError("invalid kickoff")
        season_type = str(game["season_type"]).upper()
        if season_type not in {"HOF", "PRE", "REG", "POST"}:
            raise ValueError("invalid season type")
        week = str(game["week"]).upper()
        id_season_type = "PRE" if season_type == "HOF" else season_type
        readable_week = "HOF" if season_type == "HOF" else f"W{week}"
        canonical_id = f"NFL-{int(game['season'])}-{id_season_type}-{readable_week}-{away_id}-{home_id}"
        now = utc_now()
        source_name = game.get("source_name", "ESPN_STRUCTURED_NFL")
        source_id = str(game["source_event_id"])
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM games WHERE official_source_name=? AND official_source_identifier=?",
                (source_name, source_id)).fetchone()
            if existing:
                old_kickoff = existing["scheduled_kickoff_utc"]
                changed = old_kickoff != kickoff.isoformat()
                db.execute("""UPDATE games SET canonical_game_id=?,season=?,season_type=?,week=?,
                  away_team_id=?,away_team_name=?,home_team_id=?,home_team_name=?,
                  scheduled_kickoff_utc=?,scheduled_kickoff_local=?,venue=?,neutral_site=?,
                  official_source_url=?,game_status=?,schedule_version=schedule_version+?,last_updated=?,
                  postponed=?,rescheduled=?,previous_kickoff_utc=CASE WHEN ? THEN ? ELSE previous_kickoff_utc END
                  WHERE game_uuid=?""",
                  (canonical_id, int(game["season"]), season_type, week, away_id,
                   self.team_name(away_id), home_id, self.team_name(home_id), kickoff.isoformat(),
                   game.get("kickoff_local") or kickoff.isoformat(), game.get("venue"),
                   int(bool(game.get("neutral_site"))), game.get("source_url"), game["status"],
                   int(changed), now, int(bool(game.get("postponed"))),
                   int(bool(changed or game.get("rescheduled"))),
                   int(changed), old_kickoff, existing["game_uuid"]))
                return existing["game_uuid"]
            game_uuid = str(uuid.uuid4())
            db.execute("""INSERT INTO games(game_uuid,canonical_game_id,league,season,season_type,week,
              away_team_id,away_team_name,home_team_id,home_team_name,scheduled_kickoff_utc,
              scheduled_kickoff_local,venue,neutral_site,official_source_identifier,
              official_source_name,official_source_url,game_status,schedule_version,first_observed,
              last_updated,postponed,rescheduled) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (game_uuid, canonical_id, "NFL", int(game["season"]), season_type, week,
               away_id, self.team_name(away_id), home_id, self.team_name(home_id), kickoff.isoformat(),
               game.get("kickoff_local") or kickoff.isoformat(), game.get("venue"),
               int(bool(game.get("neutral_site"))), source_id, source_name, game.get("source_url"),
               game["status"], 1, now, now, int(bool(game.get("postponed"))),
               int(bool(game.get("rescheduled")))))
            return game_uuid

    def team_name(self, team_id: str) -> str:
        with self.connect() as db:
            row = db.execute("SELECT full_name FROM teams WHERE team_id=?", (team_id,)).fetchone()
        if not row:
            raise KeyError(team_id)
        return row[0]

    def ingest_schedule_payload(self, payload: dict, season: int, season_type: str, week: str) -> dict:
        parsed, rejected = parse_espn_schedule(
            payload, season, season_type, week,
            set(self.config.get("hall_of_fame_event_ids", [])))
        loaded = 0
        for game in parsed:
            try:
                self.upsert_schedule_game(game)
                loaded += 1
                if game.get("final"):
                    self.update_authoritative_result(game)
            except ValueError as exc:
                rejected.append({"source_event_id": game.get("source_event_id"), "reason": str(exc)})
        return {"loaded": loaded, "rejected": rejected}

    def link_source(self, source: dict, scan_uuid: Optional[str] = None) -> LinkResult:
        scan_uuid = scan_uuid or str(uuid.uuid4())
        observed = source.get("retrieval_timestamp") or utc_now()
        source_type = str(source.get("source_type") or "")
        evidence: dict[str, Any] = {"matcher_version": MATCHER_VERSION, "rules": [],
                                    "tolerance_seconds": self.config["kickoff_match_tolerance_seconds"]}
        rejection = None
        away_id = home_id = None
        if source_type not in SUPPORTED_SOURCE_TYPES or str(source.get("league", "")).upper() != "NFL":
            rejection = "MALFORMED_SOURCE_DATA"
        if not source.get("source_event_id"):
            rejection = rejection or "IDENTIFIER_MISSING"
        market_type = str(source.get("market_type") or "moneyline").lower()
        if market_type not in {"moneyline", "h2h"}:
            rejection = rejection or "MALFORMED_SOURCE_DATA"
        away_id, away_error = self.normalize_team(source.get("away_team"))
        home_id, home_error = self.normalize_team(source.get("home_team"))
        rejection = rejection or away_error or home_error
        kickoff = parse_time(source.get("kickoff_utc"))
        if not kickoff:
            rejection = rejection or "KICKOFF_MISSING"
        season_type = str(source.get("season_type") or "").upper()
        if season_type and season_type not in {"HOF", "PRE", "REG", "POST"}:
            rejection = rejection or "SEASON_TYPE_CONFLICT"
        if source_type == "POLYMARKET_US" and not source.get("source_market_id"):
            rejection = rejection or "IDENTIFIER_MISSING"

        candidates = []
        orientation_conflict = False
        season_conflict = False
        kickoff_conflict = False
        if not rejection:
            with self.connect() as db:
                rows = db.execute("SELECT * FROM games WHERE season=? AND league='NFL'",
                                  (int(source.get("season", self.config["nfl_season"])),)).fetchall()
            for row in rows:
                same_set = {row["away_team_id"], row["home_team_id"]} == {away_id, home_id}
                if not same_set:
                    continue
                if season_type and row["season_type"] != season_type and not ({row["season_type"], season_type} == {"HOF", "PRE"}):
                    season_conflict = True
                    continue
                orientation_ok = (row["away_team_id"] == away_id and row["home_team_id"] == home_id)
                if not orientation_ok and not row["neutral_site"]:
                    orientation_conflict = True
                    continue
                difference = abs(int((parse_time(row["scheduled_kickoff_utc"]) - kickoff).total_seconds()))
                if difference > int(self.config["kickoff_match_tolerance_seconds"]):
                    kickoff_conflict = True
                    continue
                candidates.append((row, difference))
            if len(candidates) > 1:
                rejection = "MULTIPLE_CANONICAL_GAMES"
            elif not candidates:
                rejection = ("HOME_AWAY_CONFLICT" if orientation_conflict else
                             "SEASON_TYPE_CONFLICT" if season_conflict else
                             "KICKOFF_MISMATCH" if kickoff_conflict else "NO_CANONICAL_GAME")

        matched = candidates[0] if not rejection and len(candidates) == 1 else None
        game_uuid = matched[0]["game_uuid"] if matched else None
        difference = matched[1] if matched else None
        evidence.update({
            "away_team_id": away_id, "home_team_id": home_id,
            "team_set_exact": bool(matched), "home_away_consistent": bool(matched),
            "kickoff_difference_seconds": difference, "candidate_count": len(candidates),
            "source_season_type": season_type or None,
            "canonical_season_type": matched[0]["season_type"] if matched else None,
            "season_type_inherited": bool(matched and not season_type),
        })
        observation_uuid = str(uuid.uuid4())
        link_uuid = str(uuid.uuid4())
        raw_ids = {
            "source_event_id": source.get("source_event_id"),
            "source_market_id": source.get("source_market_id"),
            "condition_id": source.get("condition_id"),
            "token_outcome_ids": source.get("token_outcome_ids"),
        }
        with self.connect() as db:
            existing = db.execute("""SELECT source_link_uuid,first_observed FROM source_links
              WHERE source_type=? AND source_event_id=? AND source_market_id IS ?""",
              (source_type, str(source.get("source_event_id") or ""), source.get("source_market_id"))).fetchone()
            if existing:
                link_uuid = existing["source_link_uuid"]
                db.execute("""UPDATE source_links SET canonical_game_uuid=?,last_observed=?,match_status=?,
                  match_confidence=?,match_evidence_json=?,rejection_reason=?,kickoff_difference_seconds=?,
                  normalized_home_team_id=?,normalized_away_team_id=? WHERE source_link_uuid=?""",
                  (game_uuid, observed, "ACCEPTED" if matched else "REJECTED",
                   "STRICT" if matched else "NONE", json.dumps(evidence, sort_keys=True), rejection,
                   difference, home_id, away_id, link_uuid))
            else:
                db.execute("""INSERT INTO source_links(source_link_uuid,canonical_game_uuid,source_type,
                  source_event_id,source_market_id,source_condition_id,source_token_outcome_ids_json,
                  source_home_team,source_away_team,source_kickoff,normalized_home_team_id,
                  normalized_away_team_id,kickoff_difference_seconds,match_status,match_confidence,
                  match_evidence_json,rejection_reason,first_observed,last_observed,market_slug,event_slug,
                  question,outcome_names_json,accepting_orders,active,closed,bid,ask,last_trade,
                  retrieval_timestamp,settlement_metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (link_uuid, game_uuid, source_type, str(source.get("source_event_id") or ""),
                   source.get("source_market_id"), source.get("condition_id"),
                   json.dumps(source.get("token_outcome_ids") or []), source.get("home_team"),
                   source.get("away_team"), source.get("kickoff_utc"), home_id, away_id, difference,
                   "ACCEPTED" if matched else "REJECTED", "STRICT" if matched else "NONE",
                   json.dumps(evidence, sort_keys=True), rejection, observed, observed,
                   source.get("market_slug"), source.get("event_slug"), source.get("question"),
                   json.dumps(source.get("outcome_names") or []), _bool_int(source.get("accepting_orders")),
                   _bool_int(source.get("active")), _bool_int(source.get("closed")), source.get("bid"),
                   source.get("ask"), source.get("last_trade"), observed,
                   json.dumps(source.get("settlement_metadata") or {})))
            source_values = dict(source.get("source_values") or {})
            favorite_name = source_values.get("favorite_team")
            favorite_id, _ = self.normalize_team(favorite_name) if favorite_name else (None, None)
            if favorite_id:
                source_values["favorite_team_id"] = favorite_id
            db.execute("UPDATE source_links SET source_values_json=? WHERE source_link_uuid=?",
                       (json.dumps(source_values, sort_keys=True), link_uuid))
            db.execute("""INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (observation_uuid, scan_uuid, game_uuid, source_type,
               str(source.get("source_event_id") or source.get("source_market_id") or "missing"),
               observed, json.dumps({"away": away_id, "home": home_id}), source.get("kickoff_utc"),
               int(bool(matched)), rejection, json.dumps(evidence, sort_keys=True),
               json.dumps(raw_ids, sort_keys=True), json.dumps(source.get("quote_timestamps") or {}),
               json.dumps(source.get("market_status") or {})))
            if matched and source_type == "ODDS_API":
                for book in source.get("bookmakers", []):
                    db.execute("INSERT INTO sportsbook_quotes VALUES(?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()), link_uuid, str(book.get("key") or book.get("title") or "unknown"),
                       book.get("last_update"), book.get("away_price"), book.get("home_price"), observed))
            if matched and source_type in {"ODDS_API", "POLYMARKET_US"}:
                db.execute("""INSERT INTO source_snapshots(
                  snapshot_uuid,canonical_game_uuid,source_link_uuid,source_type,
                  observed_timestamp,source_values_json,market_status_json,bid,ask,last_trade,
                  liquidity,bookmaker_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (str(uuid.uuid4()), game_uuid, link_uuid, source_type, observed,
                   json.dumps(source_values, sort_keys=True, default=str),
                   json.dumps(source.get("market_status") or {}, sort_keys=True),
                   source.get("bid"), source.get("ask"), source.get("last_trade"),
                   source_values.get("liquidity"), source_values.get("bookmaker_count")))
        return LinkResult(bool(matched), game_uuid, rejection, evidence, observation_uuid)

    def update_authoritative_result(self, result: dict) -> bool:
        if not result.get("final"):
            return False
        away_id, away_error = self.normalize_team(result.get("away_team"))
        home_id, home_error = self.normalize_team(result.get("home_team"))
        winner_id, winner_error = self.normalize_team(result.get("winner_team"))
        if away_error or home_error or winner_error:
            return False
        try:
            away_score, home_score = int(result["away_score"]), int(result["home_score"])
        except (KeyError, TypeError, ValueError):
            return False
        if away_score == home_score or winner_id not in {away_id, home_id}:
            return False
        with self.connect() as db:
            game = db.execute("""SELECT * FROM games WHERE official_source_name=?
              AND official_source_identifier=?""",
              (result.get("source_name", "ESPN_STRUCTURED_NFL"), str(result["source_event_id"]))).fetchone()
            if not game:
                return False
            if game["final_winner_team_id"] and (
                    game["final_winner_team_id"] != winner_id
                    or game["away_score"] != away_score or game["home_score"] != home_score):
                db.execute("INSERT INTO result_conflicts VALUES(?,?,?,?,?,NULL)",
                  (str(uuid.uuid4()), game["game_uuid"],
                   json.dumps({"winner": game["final_winner_team_id"], "away_score": game["away_score"],
                               "home_score": game["home_score"], "source": game["result_source"]}),
                   json.dumps(result, sort_keys=True, default=str), utc_now()))
                return False
            largest = self._largest_buy_team(db, game["game_uuid"])
            largest_won = None if largest is None else int(largest == winner_id)
            db.execute("""UPDATE games SET game_status='FINAL',final_winner_team_id=?,away_score=?,
              home_score=?,completion_timestamp=?,result_source=?,source_result_id=?,
              largest_buy_side_won=?,last_updated=? WHERE game_uuid=?""",
              (winner_id, away_score, home_score, result.get("completion_timestamp") or utc_now(),
               result.get("source_name", "ESPN_STRUCTURED_NFL"), str(result["source_event_id"]),
               largest_won, utc_now(), game["game_uuid"]))
        from nfl_postgame_research import materialize_postgame_summary
        materialize_postgame_summary(self, game["game_uuid"], "authoritative result ingested")
        return True

    def create_simulation_tracks(self) -> int:
        """Create immutable comparison baselines; never touches paper cash."""
        created = 0
        with self.connect() as db:
            games = db.execute("SELECT * FROM games").fetchall()
            for game in games:
                candidates = [
                    ("HOME_TEAM", game["home_team_id"], None, {"basis": "canonical_home_team"}, []),
                    ("AWAY_TEAM", game["away_team_id"], None, {"basis": "canonical_away_team"}, []),
                ]
                largest = self._largest_buy_team(db, game["game_uuid"])
                if largest:
                    row = db.execute("""SELECT amount_usd,execution_price,observed_timestamp FROM game_flow_activity
                      WHERE canonical_game_uuid=? AND team_id=? ORDER BY amount_usd DESC LIMIT 1""",
                      (game["game_uuid"], largest)).fetchone()
                    candidates.append(("LARGEST_QUALIFYING_BUY", largest, row["execution_price"],
                                       dict(row), []))
                links = db.execute("""SELECT * FROM source_links WHERE canonical_game_uuid=?
                  AND match_status='ACCEPTED'""", (game["game_uuid"],)).fetchall()
                for source_type, track_name in (("ODDS_API", "SPORTSBOOK_CONSENSUS_FAVORITE"),
                                                ("POLYMARKET_US", "POLYMARKET_PREGAME_FAVORITE")):
                    link = next((item for item in links if item["source_type"] == source_type), None)
                    values = json.loads(link["source_values_json"] or "{}") if link else {}
                    selected = values.get("favorite_team_id")
                    if selected:
                        candidates.append((track_name, selected, values.get("entry_price"), values, []))
                for name, selected, entry, values, flags in candidates:
                    before = db.total_changes
                    db.execute("""INSERT OR IGNORE INTO simulation_tracks(
                      simulation_uuid,track_name,track_version,canonical_game_uuid,selected_team_id,
                      selection_timestamp,source_values_json,hypothetical_entry_price,
                      hypothetical_cost,data_quality_flags_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      (str(uuid.uuid4()), name, 1, game["game_uuid"], selected, utc_now(),
                       json.dumps(values, sort_keys=True, default=str), entry, 100.0, json.dumps(flags)))
                    created += int(db.total_changes > before)
        return created

    def settle_simulations(self) -> int:
        settled = 0
        with self.connect() as db:
            rows = db.execute("""SELECT s.*,g.final_winner_team_id game_winner_team_id FROM simulation_tracks s
              JOIN games g ON g.game_uuid=s.canonical_game_uuid
              WHERE s.result IS NULL AND g.final_winner_team_id IS NOT NULL
              AND NOT EXISTS(SELECT 1 FROM result_conflicts c WHERE c.canonical_game_uuid=g.game_uuid AND c.resolved_at IS NULL)""").fetchall()
            for row in rows:
                won = row["selected_team_id"] == row["game_winner_team_id"]
                entry = row["hypothetical_entry_price"]
                payout = (100.0 / entry if won and entry and entry > 0 else
                          100.0 if won and not entry else 0.0)
                db.execute("""UPDATE simulation_tracks SET final_winner_team_id=?,result=?,
                  hypothetical_payout=?,hypothetical_return=?,settled_at=? WHERE simulation_uuid=?""",
                  (row["game_winner_team_id"], "WIN" if won else "LOSS", payout,
                   payout - 100.0, utc_now(), row["simulation_uuid"]))
                settled += 1
        return settled

    def conflict_report(self) -> list[dict]:
        report = []
        with self.connect() as db:
            rejected = db.execute("""SELECT * FROM source_links WHERE source_type='ODDS_API'
              AND match_status='REJECTED' ORDER BY source_kickoff,source_event_id""").fetchall()
            games = db.execute("SELECT * FROM games").fetchall()
        for link in rejected:
            away_id, _ = self.normalize_team(link["source_away_team"])
            home_id, _ = self.normalize_team(link["source_home_team"])
            source_time = parse_time(link["source_kickoff"])
            same_teams = [g for g in games if {g["away_team_id"], g["home_team_id"]} == {away_id, home_id}]
            closest = min(same_teams, key=lambda g: abs((parse_time(g["scheduled_kickoff_utc"]) - source_time).total_seconds())) \
                if same_teams and source_time else None
            difference = abs(int((parse_time(closest["scheduled_kickoff_utc"]) - source_time).total_seconds())) \
                if closest and source_time else None
            reason = link["rejection_reason"]
            explanation = ("bad source home/away orientation" if reason == "HOME_AWAY_CONFLICT" else
                           "schedule-time discrepancy" if reason == "KICKOFF_MISMATCH" else "unresolved")
            report.append({
                "provider_event_id": link["source_event_id"], "source_away": link["source_away_team"],
                "source_home": link["source_home_team"], "normalized_away": away_id,
                "normalized_home": home_id, "source_kickoff": link["source_kickoff"],
                "closest_canonical_game": closest["canonical_game_id"] if closest else None,
                "canonical_kickoff": closest["scheduled_kickoff_utc"] if closest else None,
                "time_difference_seconds": difference,
                "canonical_orientation": f"{closest['away_team_id']}@{closest['home_team_id']}" if closest else None,
                "source_orientation": f"{away_id}@{home_id}" if away_id and home_id else None,
                "rejection_code": reason, "classification": explanation,
            })
        return report

    def game_flow_snapshot(self) -> dict:
        with self.connect() as db:
            games = db.execute("SELECT * FROM games ORDER BY scheduled_kickoff_utc").fetchall()
            cards = []
            for game in games:
                activity = [dict(row) for row in db.execute("""SELECT * FROM game_flow_activity
                  WHERE canonical_game_uuid=? ORDER BY amount_usd DESC,observed_timestamp DESC""",
                  (game["game_uuid"],))]
                links = db.execute("""SELECT * FROM source_links WHERE canonical_game_uuid=?
                  AND source_type='POLYMARKET_US' AND match_status='ACCEPTED' LIMIT 1""",
                  (game["game_uuid"],)).fetchone()
                values = json.loads(links["source_values_json"] or "{}") if links else {}
                research = db.execute("""SELECT record_uuid,revision_number FROM postgame_research_records
                  WHERE canonical_game_uuid=? ORDER BY revision_number DESC LIMIT 1""",
                  (game["game_uuid"],)).fetchone()
                cards.append({
                    "game_uuid": game["game_uuid"], "canonical_game_id": game["canonical_game_id"],
                    "away": game["away_team_name"], "home": game["home_team_name"],
                    "away_team_id": game["away_team_id"], "home_team_id": game["home_team_id"],
                    "season_type": game["season_type"], "week": game["week"],
                    "kickoff": game["scheduled_kickoff_utc"], "status": game["game_status"],
                    "completion_timestamp": game["completion_timestamp"],
                    "winner_team_id": game["final_winner_team_id"],
                    "largest_buy_side_won": None if game["largest_buy_side_won"] is None else bool(game["largest_buy_side_won"]),
                    "moneyline": values.get("outcomes", []),
                    "buys": {
                        game["away_team_id"]: [a for a in activity if a["team_id"] == game["away_team_id"]][:5],
                        game["home_team_id"]: [a for a in activity if a["team_id"] == game["home_team_id"]][:5],
                    },
                    "last_activity": max((a["observed_timestamp"] for a in activity), default=None),
                    "research_summary": dict(research) if research else None,
                })
        return {"environment": self.environment, "games": cards, "generated_at": utc_now()}

    @staticmethod
    def _largest_buy_team(db: sqlite3.Connection, game_uuid: str) -> Optional[str]:
        rows = db.execute("""SELECT team_id,MAX(amount_usd) amount FROM game_flow_activity
          WHERE canonical_game_uuid=? GROUP BY team_id ORDER BY amount DESC""", (game_uuid,)).fetchall()
        if not rows or (len(rows) > 1 and rows[0]["amount"] == rows[1]["amount"]):
            return None
        return rows[0]["team_id"]

    def record_game_flow_activity(self, game_uuid: str, trade_id: str, team: str,
                                  amount: float, execution_price: float,
                                  observed_at: Optional[str] = None) -> bool:
        team_id, error = self.normalize_team(team)
        if error or amount <= 0 or not 0 < execution_price < 1:
            raise ValueError(error or "invalid activity")
        with self.connect() as db:
            before = db.total_changes
            db.execute("INSERT OR IGNORE INTO game_flow_activity VALUES(?,?,?,?,?,?,?)",
              (str(uuid.uuid4()), game_uuid, trade_id, team_id, float(amount),
               float(execution_price), observed_at or utc_now()))
            return db.total_changes > before

    def record_orphan_trade(self, trade: dict, reason: str = "NO_CANONICAL_GAME") -> None:
        with self.connect() as db:
            if db.execute("""SELECT 1 FROM observations WHERE source_type='GAME_FLOW_STREAM'
              AND source_record_id=? AND rejection_reason=? LIMIT 1""",
              (str(trade.get("id") or "missing"), reason)).fetchone():
                return
            db.execute("""INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (str(uuid.uuid4()), str(uuid.uuid4()), None, "GAME_FLOW_STREAM",
               str(trade.get("id") or "missing"), trade.get("trade_time") or utc_now(),
               json.dumps({"selection": trade.get("raw_selection")}), None, 0, reason,
               json.dumps({"matcher_version": MATCHER_VERSION, "market_slug": trade.get("market_slug")}),
               json.dumps({"trade_id": trade.get("id"), "market_slug": trade.get("market_slug")}),
               "{}", json.dumps({"status": trade.get("status")})))

    def list_games(self, season_type: Optional[str] = None, week: Optional[str] = None) -> list[dict]:
        clauses, params = [], []
        if season_type:
            clauses.append("season_type=?"); params.append(season_type.upper())
        if week:
            clauses.append("week=?"); params.append(str(week).upper())
        query = "SELECT * FROM games" + (" WHERE " + " AND ".join(clauses) if clauses else "")
        query += " ORDER BY scheduled_kickoff_utc"
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, params)]

    def status(self) -> dict:
        with self.connect() as db:
            games = {row["season_type"]: row["count"] for row in db.execute(
                "SELECT season_type,COUNT(*) count FROM games GROUP BY season_type")}
            rejected = {row["rejection_reason"]: row["count"] for row in db.execute(
                "SELECT rejection_reason,COUNT(*) count FROM observations WHERE match_accepted=0 GROUP BY rejection_reason")}
            return {
                "schema_version": int(db.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]),
                "environment": self.environment,
                "teams": db.execute("SELECT COUNT(*) FROM teams").fetchone()[0],
                "games": games,
                "total_games": sum(games.values()),
                "duplicate_games": db.execute("SELECT COUNT(*) FROM (SELECT canonical_game_id FROM games GROUP BY canonical_game_id HAVING COUNT(*)>1)").fetchone()[0],
                "accepted_links": db.execute("SELECT COUNT(*) FROM source_links WHERE match_status='ACCEPTED'").fetchone()[0],
                "rejected_observations": rejected,
                "ambiguous_matches": rejected.get("MULTIPLE_CANONICAL_GAMES", 0),
                "missing_kickoffs": rejected.get("KICKOFF_MISSING", 0),
                "final_results": db.execute("SELECT COUNT(*) FROM games WHERE game_status='FINAL'").fetchone()[0],
                "observations": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
                "simulations": db.execute("SELECT COUNT(*) FROM simulation_tracks").fetchone()[0],
                "workflow_runs": db.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0],
            }


def _bool_int(value: Any) -> Optional[int]:
    return None if value is None else int(bool(value))


def parse_espn_schedule(payload: dict, season: int, season_type: str, week: str,
                        hall_of_fame_event_ids: Optional[set[str]] = None) -> tuple[list[dict], list[dict]]:
    games, rejected = [], []
    events = payload.get("events")
    if not isinstance(events, list):
        return [], [{"reason": "MALFORMED_SOURCE_DATA", "detail": "events missing"}]
    for event in events:
        try:
            competition = event["competitions"][0]
            competitors = competition["competitors"]
            home = next(item for item in competitors if item.get("homeAway") == "home")
            away = next(item for item in competitors if item.get("homeAway") == "away")
            status = event.get("status", {}).get("type", {})
            name = str(event.get("name") or "")
            verified_hof = str(event.get("id")) in (hall_of_fame_event_ids or set())
            actual_type = "HOF" if verified_hof or "hall of fame" in name.casefold() else season_type.upper()
            canonical_week = str(max(1, int(week) - 1)) if actual_type == "PRE" else str(week)
            venue = competition.get("venue") or {}
            kickoff = parse_time(event.get("date"))
            if not event.get("id") or not kickoff:
                raise ValueError("identifier or kickoff missing")
            completed = bool(status.get("completed"))
            away_score = _score(away.get("score")) if completed else None
            home_score = _score(home.get("score")) if completed else None
            winner = None
            if completed and away_score is not None and home_score is not None and away_score != home_score:
                winner = away["team"].get("displayName") if away_score > home_score else home["team"].get("displayName")
            games.append({
                "source_event_id": str(event["id"]), "source_name": "ESPN_STRUCTURED_NFL",
                "source_url": event.get("links", [{}])[0].get("href"), "season": int(season),
                "season_type": actual_type, "week": "HOF" if actual_type == "HOF" else canonical_week,
                "away_team": away["team"].get("displayName"), "home_team": home["team"].get("displayName"),
                "kickoff_utc": kickoff.isoformat(),
                "kickoff_local": schedule_local_time(
                    kickoff, home["team"].get("displayName"), venue.get("fullName", ""),
                    bool(competition.get("neutralSite"))),
                "venue": venue.get("fullName"), "neutral_site": bool(competition.get("neutralSite")),
                "status": status.get("name") or status.get("state") or "SCHEDULED",
                "postponed": "postpon" in str(status.get("name", "")).casefold(),
                "final": completed, "away_score": away_score, "home_score": home_score,
                "winner_team": winner, "completion_timestamp": kickoff.isoformat() if completed else None,
            })
        except (KeyError, IndexError, StopIteration, TypeError, ValueError) as exc:
            rejected.append({"source_event_id": event.get("id"), "reason": "MALFORMED_SOURCE_DATA", "detail": str(exc)})
    return games, rejected


def _score(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def fetch_espn_week(season: int, season_type: str, week: int, session=requests) -> dict:
    type_number = {"PRE": 1, "REG": 2, "POST": 3}[season_type]
    response = session.get(ESPN_SCOREBOARD,
                           params={"dates": season, "seasontype": type_number, "week": week, "limit": 100},
                           timeout=20)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("schedule source returned non-object JSON")
    return payload


def sync_schedule(registry: NFLRegistry, session=requests) -> dict:
    if not registry.config["nfl_schedule_sync_enabled"] or not registry.config["adapters"]["espn_schedule"]:
        return {"loaded": 0, "rejected": [], "source_failures": ["schedule adapter disabled"]}
    season = int(registry.config["nfl_season"])
    loaded, rejected, failures = 0, [], []
    enabled = set(registry.config["enabled_season_types"])
    requests_to_make = []
    if enabled & {"HOF", "PRE"}:
        requests_to_make += [("PRE", week) for week in range(1, 5)]
    if "REG" in enabled:
        requests_to_make += [("REG", week) for week in range(1, 19)]
    for season_type, week in requests_to_make:
        try:
            outcome = registry.ingest_schedule_payload(
                fetch_espn_week(season, season_type, week, session=session), season, season_type, str(week))
            loaded += outcome["loaded"]
            rejected.extend(outcome["rejected"])
        except (requests.RequestException, ValueError) as exc:
            failures.append(f"{season_type} week {week}: {exc}")
    return {"loaded": loaded, "rejected": rejected, "source_failures": failures}


def odds_api_records(payload: list, season: int, season_type: Optional[str], retrieved: Optional[str] = None) -> list[dict]:
    retrieved = retrieved or utc_now()
    records = []
    for event in payload if isinstance(payload, list) else []:
        books = []
        for book in event.get("bookmakers", []):
            h2h = next((market for market in book.get("markets", []) if market.get("key") == "h2h"), None)
            if not h2h:
                continue
            prices = {item.get("name"): item.get("price") for item in h2h.get("outcomes", [])}
            books.append({"key": book.get("key"), "last_update": book.get("last_update"),
                          "away_price": prices.get(event.get("away_team")),
                          "home_price": prices.get(event.get("home_team"))})
        away_probs = [1 / b["away_price"] for b in books if b.get("away_price") and b.get("home_price")]
        home_probs = [1 / b["home_price"] for b in books if b.get("away_price") and b.get("home_price")]
        consensus = {}
        if away_probs and home_probs:
            away_raw, home_raw = sum(away_probs) / len(away_probs), sum(home_probs) / len(home_probs)
            total = away_raw + home_raw
            consensus = {
                "away_probability": away_raw / total, "home_probability": home_raw / total,
                "favorite_team": event.get("away_team") if away_raw > home_raw else event.get("home_team"),
                "entry_price": max(away_raw, home_raw) / total,
            }
        records.append({
            "source_type": "ODDS_API", "league": "NFL", "season": season,
            "season_type": season_type, "source_event_id": event.get("id"),
            "away_team": event.get("away_team"), "home_team": event.get("home_team"),
            "kickoff_utc": event.get("commence_time"), "market_type": "h2h",
            "bookmakers": books, "quote_timestamps": {b["key"]: b["last_update"] for b in books if b.get("key")},
            "source_values": {**consensus, "bookmaker_count": len(books)},
            "retrieval_timestamp": retrieved,
        })
    return records


def fetch_odds_api(sport_key: str = "americanfootball_nfl", session=requests) -> list:
    load_dotenv(HERE / ".env")
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY is not configured")
    if sport_key not in {"americanfootball_nfl", "americanfootball_nfl_preseason"}:
        raise ValueError("unsupported Odds API sport key")
    response = session.get(f"{ODDS_API_BASE}/{sport_key}/odds",
                           params={"apiKey": key, "regions": "us", "markets": "h2h", "oddsFormat": "decimal"}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Odds API returned non-list JSON")
    return payload


def polymarket_us_records(payload: dict, season: int, season_type: Optional[str], retrieved: Optional[str] = None) -> list[dict]:
    retrieved = retrieved or utc_now()
    events = payload.get("events", []) if isinstance(payload, dict) else []
    records = []
    for event in events:
        event_title = str(event.get("title") or "")
        title_teams = re.split(r"\s+(?:vs\.?|@)\s+", event_title, maxsplit=1, flags=re.IGNORECASE)
        if len(title_teams) != 2:
            title_teams = [None, None]
        for market in event.get("markets", []):
            if str(market.get("marketType") or "").lower() != "moneyline":
                continue
            sides = market.get("marketSides") or []
            outcome_ids = [side.get("id") or side.get("tokenId") for side in sides]
            outcomes = [side.get("description") for side in sides]
            away_side = next((side for side in sides
                              if str((side.get("team") or {}).get("ordering", "")).lower() == "away"), None)
            home_side = next((side for side in sides
                              if str((side.get("team") or {}).get("ordering", "")).lower() == "home"), None)
            away_team = ((away_side or {}).get("team") or {}).get("name") or title_teams[0]
            home_team = ((home_side or {}).get("team") or {}).get("name") or title_teams[1]
            priced_outcomes = []
            for side in sides:
                team_name = (side.get("team") or {}).get("name") or side.get("description")
                try:
                    price = float(side.get("price"))
                except (TypeError, ValueError):
                    price = None
                priced_outcomes.append({"team": team_name, "price": price})
            valid_prices = [item for item in priced_outcomes if item["price"] is not None]
            favorite = max(valid_prices, key=lambda item: item["price"]) if valid_prices else None
            records.append({
                "source_type": "POLYMARKET_US", "league": "NFL", "season": season,
                "season_type": season_type, "source_event_id": event.get("id") or event.get("slug"),
                "source_market_id": market.get("id") or market.get("slug"),
                "condition_id": market.get("conditionId"), "token_outcome_ids": outcome_ids,
                "away_team": away_team, "home_team": home_team,
                "kickoff_utc": event.get("startTime") or event.get("eventDate"), "market_type": "moneyline",
                "market_slug": market.get("slug"), "event_slug": event.get("slug"),
                "question": market.get("question"), "outcome_names": outcomes,
                "accepting_orders": market.get("acceptingOrders"), "active": market.get("active"),
                "closed": market.get("closed"), "bid": market.get("bestBid"), "ask": market.get("bestAsk"),
                "last_trade": market.get("lastTradePrice"), "retrieval_timestamp": retrieved,
                "market_status": {"accepting_orders": market.get("acceptingOrders"),
                                  "active": market.get("active"), "closed": market.get("closed")},
                "settlement_metadata": market.get("settlement") or market.get("resolution") or {},
            "source_values": {
                    "outcomes": priced_outcomes,
                    "favorite_team": favorite["team"] if favorite else None,
                    "entry_price": favorite["price"] if favorite else None,
                    "liquidity": market.get("liquidity"),
                },
            })
    return records


def fetch_polymarket_us(session=requests, season: Optional[int] = None) -> dict:
    season = season or load_config()["nfl_season"]
    response = session.get(POLYMARKET_US_EVENTS, params={
        "tagSlug": "nfl", "limit": 100,
        "startTimeMin": f"{season}-07-01T00:00:00Z",
        "startTimeMax": f"{season}-09-06T00:00:00Z",
    }, timeout=25)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Polymarket US returned non-object JSON")
    return payload


def refresh_game_flow_activity(registry: NFLRegistry,
                               tape_db: Path = HERE / "big_money_tape.db") -> dict:
    if not tape_db.exists():
        return {"attached": 0, "orphans": 0, "source_failure": "tape database missing"}
    connection = sqlite3.connect(tape_db)
    connection.row_factory = sqlite3.Row
    try:
        trades = [dict(row) for row in connection.execute("""SELECT * FROM bets
          WHERE lower(league)='nfl' AND status='OPEN' AND risk_usd>=5""")]
    except sqlite3.Error as exc:
        return {"attached": 0, "orphans": 0, "source_failure": str(exc)}
    finally:
        connection.close()
    attached = orphans = 0
    with registry.connect() as db:
        mappings = {row["market_slug"]: row["canonical_game_uuid"] for row in db.execute("""
          SELECT market_slug,canonical_game_uuid FROM source_links
          WHERE source_type='POLYMARKET_US' AND match_status='ACCEPTED'
          AND market_slug IS NOT NULL""")}
    for trade in trades:
        game_uuid = mappings.get(trade.get("market_slug"))
        if not game_uuid:
            registry.record_orphan_trade(trade)
            orphans += 1
            continue
        try:
            created = registry.record_game_flow_activity(
                game_uuid, trade["id"], trade.get("raw_selection") or trade.get("selection"),
                float(trade["risk_usd"]), float(trade["entry_price"]), trade.get("trade_time"))
            attached += int(created)
        except ValueError:
            registry.record_orphan_trade(trade, "UNKNOWN_TEAM")
            orphans += 1
    return {"attached": attached, "orphans": orphans, "source_failure": None}


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def registry_path(environment: str) -> Path:
    return PRODUCTION_DB if environment == "production" else DEFAULT_DB


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sync_parser = commands.add_parser("sync")
    status_parser = commands.add_parser("status")
    listing = commands.add_parser("list")
    listing.add_argument("--season-type")
    listing.add_argument("--week")
    odds_parser = commands.add_parser("link-odds")
    poly_parser = commands.add_parser("link-polymarket")
    conflict_parser = commands.add_parser("conflict-report")
    for command_parser in (sync_parser, status_parser, listing, odds_parser,
                           poly_parser, conflict_parser):
        command_parser.add_argument(
            "--env", choices=("development", "production"), required=True,
            help="explicit registry environment; writes never cross environments")
    args = parser.parse_args(argv)
    registry = NFLRegistry(registry_path(args.env), environment=args.env)
    if args.command == "sync":
        print_json(sync_schedule(registry))
    elif args.command == "status":
        print_json(registry.status())
    elif args.command == "list":
        print_json(registry.list_games(args.season_type, args.week))
    elif args.command == "link-odds":
        scan = str(uuid.uuid4())
        records = odds_api_records(
            fetch_odds_api("americanfootball_nfl_preseason"),
            registry.config["nfl_season"], "PRE")
        records += odds_api_records(
            fetch_odds_api("americanfootball_nfl"),
            registry.config["nfl_season"], "REG")
        print_json([registry.link_source(record, scan).__dict__ for record in records])
    elif args.command == "link-polymarket":
        scan = str(uuid.uuid4())
        records = polymarket_us_records(
            fetch_polymarket_us(season=registry.config["nfl_season"]),
            registry.config["nfl_season"], None)
        print_json([registry.link_source(record, scan).__dict__ for record in records])
    elif args.command == "conflict-report":
        print_json(registry.conflict_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
