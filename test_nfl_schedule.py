import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

import nfl_schedule as nfl


FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class RegistryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "registry.db"
        self.registry = nfl.NFLRegistry(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def load_preseason(self):
        return self.registry.ingest_schedule_payload(
            fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")

    def source(self, **changes):
        record = {
            "source_type": "ODDS_API", "league": "NFL", "season": 2026,
            "season_type": "PRE", "source_event_id": "source-1",
            "away_team": "Pittsburgh Steelers", "home_team": "Baltimore Ravens",
            "kickoff_utc": "2026-08-14T23:35:00Z", "market_type": "h2h",
            "retrieval_timestamp": "2026-08-14T20:00:00Z",
        }
        record.update(changes)
        return record


class TeamMappingTests(RegistryCase):
    def test_all_32_team_mappings_are_loaded(self):
        with self.registry.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 32)

    def test_every_team_full_name_and_id_normalize(self):
        for team_id, _, _, full_name, _ in nfl.TEAM_ROWS:
            self.assertEqual(self.registry.normalize_team(team_id), (team_id, None))
            self.assertEqual(self.registry.normalize_team(full_name.upper()), (team_id, None))

    def test_aliases_and_legacy_names(self):
        cases = {"LA Chargers": "LAC", "NY Jets": "NYJ", "JAC": "JAX",
                 "Washington Football Team": "WAS", "San Diego Chargers": "LAC"}
        for alias, expected in cases.items():
            self.assertEqual(self.registry.normalize_team(alias), (expected, None))

    def test_unknown_team_rejected(self):
        self.assertEqual(self.registry.normalize_team("Springfield Atoms"), (None, "UNKNOWN_TEAM"))

    def test_city_only_is_not_accepted(self):
        self.assertEqual(self.registry.normalize_team("New York"), (None, "UNKNOWN_TEAM"))


class ScheduleTests(RegistryCase):
    def test_preseason_and_hall_of_fame_ingestion(self):
        outcome = self.load_preseason()
        self.assertEqual(outcome, {"loaded": 2, "rejected": []})
        status = self.registry.status()
        self.assertEqual(status["games"], {"HOF": 1, "PRE": 1})
        self.assertEqual(self.registry.list_games("HOF")[0]["canonical_game_id"],
                         "NFL-2026-PRE-HOF-DAL-LAC")

    def test_regular_week_ingestion(self):
        result = self.registry.ingest_schedule_payload(
            fixture("nfl_espn_regular.json"), 2026, "REG", "1")
        self.assertEqual(result["loaded"], 1)
        game = self.registry.list_games("REG", "1")[0]
        self.assertEqual(game["canonical_game_id"], "NFL-2026-REG-W1-KC-DEN")

    def test_timezone_conversion_retains_utc_and_local_offset(self):
        self.load_preseason()
        game = self.registry.list_games("PRE")[0]
        self.assertEqual(game["scheduled_kickoff_utc"], "2026-08-14T23:30:00+00:00")
        self.assertRegex(game["scheduled_kickoff_local"], r"-04:00$")

    def test_western_venue_uses_home_team_timezone(self):
        self.registry.ingest_schedule_payload(
            fixture("nfl_espn_regular.json"), 2026, "REG", "1")
        game = self.registry.list_games("REG")[0]
        self.assertRegex(game["scheduled_kickoff_local"], r"-06:00$")

    def test_repeated_sync_does_not_duplicate(self):
        self.load_preseason(); self.load_preseason()
        self.assertEqual(self.registry.status()["total_games"], 2)
        self.assertEqual(self.registry.status()["duplicate_games"], 0)

    def test_kickoff_change_records_previous_and_increments_version(self):
        payload = fixture("nfl_espn_preseason.json")
        self.registry.ingest_schedule_payload(payload, 2026, "PRE", "2")
        payload["events"][1]["date"] = "2026-08-15T00:00:00Z"
        self.registry.ingest_schedule_payload(payload, 2026, "PRE", "2")
        game = self.registry.list_games("PRE")[0]
        self.assertEqual(game["previous_kickoff_utc"], "2026-08-14T23:30:00+00:00")
        self.assertEqual(game["schedule_version"], 2)
        self.assertEqual(game["rescheduled"], 1)

    def test_malformed_schedule_row_rejected(self):
        payload = {"events": [{"id": "broken"}]}
        result = self.registry.ingest_schedule_payload(payload, 2026, "PRE", "1")
        self.assertEqual(result["loaded"], 0)
        self.assertEqual(result["rejected"][0]["reason"], "MALFORMED_SOURCE_DATA")

    def test_restart_recovery_and_schema_version(self):
        self.load_preseason()
        reopened = nfl.NFLRegistry(self.db)
        self.assertEqual(reopened.status()["total_games"], 2)
        self.assertEqual(reopened.status()["schema_version"], 4)

    def test_newer_database_schema_is_rejected(self):
        with self.registry.connect() as db:
            db.execute("UPDATE schema_meta SET value='999' WHERE key='schema_version'")
        with self.assertRaises(RuntimeError):
            nfl.NFLRegistry(self.db)


class MatchingTests(RegistryCase):
    def setUp(self):
        super().setUp()
        self.load_preseason()

    def test_exact_team_set_home_away_and_tolerance_match(self):
        result = self.registry.link_source(self.source())
        self.assertTrue(result.accepted)
        self.assertEqual(result.evidence["kickoff_difference_seconds"], 300)

    def test_missing_source_season_type_inherits_unique_canonical_type(self):
        result = self.registry.link_source(self.source(season_type=None))
        self.assertTrue(result.accepted)
        self.assertTrue(result.evidence["season_type_inherited"])
        self.assertEqual(result.evidence["canonical_season_type"], "PRE")

    def test_home_away_conflict_rejected(self):
        result = self.registry.link_source(self.source(
            away_team="Baltimore Ravens", home_team="Pittsburgh Steelers"))
        self.assertEqual(result.rejection_reason, "HOME_AWAY_CONFLICT")

    def test_neutral_site_allows_orientation_difference(self):
        result = self.registry.link_source(self.source(
            source_event_id="hof-source", season_type="HOF",
            away_team="Los Angeles Chargers", home_team="Dallas Cowboys",
            kickoff_utc="2026-08-07T00:10:00Z"))
        self.assertTrue(result.accepted)

    def test_kickoff_at_tolerance_is_accepted(self):
        result = self.registry.link_source(self.source(kickoff_utc="2026-08-15T00:00:00Z"))
        self.assertTrue(result.accepted)

    def test_kickoff_over_tolerance_rejected(self):
        result = self.registry.link_source(self.source(kickoff_utc="2026-08-15T00:00:01Z"))
        self.assertEqual(result.rejection_reason, "KICKOFF_MISMATCH")

    def test_missing_kickoff_rejected(self):
        self.assertEqual(self.registry.link_source(self.source(kickoff_utc=None)).rejection_reason,
                         "KICKOFF_MISSING")

    def test_unknown_team_rejected(self):
        self.assertEqual(self.registry.link_source(self.source(away_team="London Foxes")).rejection_reason,
                         "UNKNOWN_TEAM")

    def test_season_type_mismatch_rejected(self):
        self.assertEqual(self.registry.link_source(self.source(season_type="REG")).rejection_reason,
                         "SEASON_TYPE_CONFLICT")

    def test_missing_polymarket_market_id_rejected(self):
        record = self.source(source_type="POLYMARKET_US", market_type="moneyline")
        self.assertEqual(self.registry.link_source(record).rejection_reason, "IDENTIFIER_MISSING")

    def test_multiple_candidate_rejected(self):
        duplicate = {
            "source_event_id": "alternate-official", "season": 2026, "season_type": "PRE",
            "week": "2", "away_team": "Pittsburgh Steelers", "home_team": "Baltimore Ravens",
            "kickoff_utc": "2026-08-14T23:40:00Z", "status": "SCHEDULED",
        }
        self.registry.upsert_schedule_game(duplicate)
        result = self.registry.link_source(self.source())
        self.assertEqual(result.rejection_reason, "MULTIPLE_CANONICAL_GAMES")

    def test_no_canonical_game_rejected(self):
        result = self.registry.link_source(self.source(
            away_team="Miami Dolphins", home_team="Buffalo Bills"))
        self.assertEqual(result.rejection_reason, "NO_CANONICAL_GAME")

    def test_observations_are_append_only_across_repeated_scans(self):
        self.registry.link_source(self.source(), "scan-1")
        self.registry.link_source(self.source(), "scan-2")
        with self.registry.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_links").fetchone()[0], 1)


class AdapterTests(RegistryCase):
    def setUp(self):
        super().setUp()
        self.registry.ingest_schedule_payload(
            fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")

    def test_odds_api_h2h_record_links_and_quotes_are_retained(self):
        records = nfl.odds_api_records(fixture("nfl_odds_event.json"), 2026, "PRE",
                                       "2026-08-14T20:01:00Z")
        result = self.registry.link_source(records[0])
        self.assertTrue(result.accepted)
        with self.registry.connect() as db:
            quote = db.execute("SELECT * FROM sportsbook_quotes").fetchone()
        self.assertEqual(quote["bookmaker"], "fictionalbook")
        self.assertEqual(quote["away_price"], 2.1)

    def test_polymarket_us_moneyline_record_links_and_fields_are_retained(self):
        records = nfl.polymarket_us_records(
            fixture("nfl_polymarket_us_event.json"), 2026, "PRE",
            "2026-08-14T20:01:00Z")
        result = self.registry.link_source(records[0])
        self.assertTrue(result.accepted)
        with self.registry.connect() as db:
            link = db.execute("SELECT * FROM source_links WHERE source_type='POLYMARKET_US'").fetchone()
        self.assertEqual(link["source_condition_id"], "condition-pit-bal")
        self.assertEqual(json.loads(link["source_token_outcome_ids_json"]), ["token-pit", "token-bal"])
        self.assertEqual(link["bid"], 0.48)

    def test_non_moneyline_polymarket_market_is_excluded(self):
        payload = fixture("nfl_polymarket_us_event.json")
        payload["events"][0]["markets"][0]["marketType"] = "spread"
        self.assertEqual(nfl.polymarket_us_records(payload, 2026, "PRE"), [])

    def test_source_fetch_failure_propagates_without_creating_data(self):
        fake = mock.Mock()
        fake.get.side_effect = requests.Timeout("timeout")
        with self.assertRaises(requests.Timeout):
            nfl.fetch_espn_week(2026, "PRE", 1, session=fake)
        self.assertEqual(self.registry.status()["observations"], 0)


class ResultsAndGameFlowTests(RegistryCase):
    def setUp(self):
        super().setUp()
        self.registry.ingest_schedule_payload(
            fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
        self.game = self.registry.list_games("PRE")[0]

    def test_authoritative_final_records_winner_score_and_largest_buy_result(self):
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "trade-pit", "Pittsburgh Steelers", 500, .48)
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "trade-bal", "Baltimore Ravens", 300, .52)
        result = self.registry.ingest_schedule_payload(
            fixture("nfl_espn_final.json"), 2026, "PRE", "2")
        self.assertEqual(result["loaded"], 1)
        game = self.registry.list_games("PRE")[0]
        self.assertEqual(game["final_winner_team_id"], "PIT")
        self.assertEqual((game["away_score"], game["home_score"]), (24, 17))
        self.assertEqual(game["largest_buy_side_won"], 1)

    def test_unresolved_game_does_not_gain_winner(self):
        game = self.registry.list_games("PRE")[0]
        self.assertIsNone(game["final_winner_team_id"])
        self.assertIsNone(game["largest_buy_side_won"])

    def test_no_qualifying_buy_leaves_derived_field_null(self):
        self.registry.ingest_schedule_payload(fixture("nfl_espn_final.json"), 2026, "PRE", "2")
        self.assertIsNone(self.registry.list_games("PRE")[0]["largest_buy_side_won"])

    def test_duplicate_game_flow_trade_is_ignored(self):
        for _ in range(2):
            self.registry.record_game_flow_activity(
                self.game["game_uuid"], "same-trade", "Pittsburgh Steelers", 50, .5)
        with self.registry.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM game_flow_activity").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
