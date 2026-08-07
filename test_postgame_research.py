import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nfl_schedule as nfl
from nfl_postgame_research import (
    NOTE_FIELDS, get_postgame_summary, materialize_postgame_summary,
    save_analyst_notes,
)


FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class PostGameResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "production.db"
        self.registry = nfl.NFLRegistry(self.path, environment="production")
        self.registry.ingest_schedule_payload(fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
        self.game = self.registry.list_games("PRE")[0]

        odds = nfl.odds_api_records(
            fixture("nfl_odds_event.json"), 2026, "PRE", "2026-08-14T22:55:00Z")[0]
        polymarket = nfl.polymarket_us_records(
            fixture("nfl_polymarket_us_event.json"), 2026, "PRE", "2026-08-14T23:00:00Z")[0]
        self.assertTrue(self.registry.link_source(odds).accepted)
        self.assertTrue(self.registry.link_source(polymarket).accepted)
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "away-big", "Pittsburgh Steelers", 1200, .48,
            "2026-08-14T23:10:00Z")
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "home-buy", "Baltimore Ravens", 700, .52,
            "2026-08-14T23:20:00Z")
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "post-buy", "Baltimore Ravens", 300, .60,
            "2026-08-15T00:10:00Z")
        self.registry.create_simulation_tracks()
        self.registry.ingest_schedule_payload(fixture("nfl_espn_final.json"), 2026, "PRE", "2")
        self.registry.settle_simulations()
        materialize_postgame_summary(self.registry, self.game["game_uuid"], "simulation settlement completed")

    def tearDown(self):
        self.temp.cleanup()

    def test_completed_game_has_full_immutable_case_study(self):
        summary = get_postgame_summary(self.registry, self.game["game_uuid"])
        payload = summary["record"]["payload"]
        self.assertEqual(payload["game_information"]["winner_team_id"], "PIT")
        self.assertEqual(payload["market_snapshot"]["largest_recorded_buy"]["amount_usd"], 1200)
        self.assertEqual(payload["market_snapshot"]["bookmaker_count"], 1)
        self.assertTrue(payload["research_results"]["largest_buy_side_won"])
        self.assertFalse(payload["research_results"]["paper_cash_affected"])
        self.assertEqual(payload["game_flow_summary"]["pregame_trade_count"], 2)
        self.assertEqual(payload["game_flow_summary"]["post_kickoff_trade_count"], 1)
        self.assertTrue(payload["research_quality"]["canonical_match_verified"])
        self.assertTrue(payload["research_quality"]["settlement_verified"])

    def test_same_content_is_idempotent_and_correction_creates_revision(self):
        before = get_postgame_summary(self.registry, self.game["game_uuid"])
        result = materialize_postgame_summary(self.registry, self.game["game_uuid"])
        self.assertFalse(result["created"])
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "late-evidence", "Pittsburgh Steelers", 50, .75,
            "2026-08-15T00:20:00Z")
        result = materialize_postgame_summary(self.registry, self.game["game_uuid"], "late evidence appended")
        self.assertTrue(result["created"])
        self.assertEqual(result["record"]["revision_number"], before["record"]["revision_number"] + 1)
        self.assertEqual(result["record"]["supersedes_record_uuid"], before["record"]["record_uuid"])

    def test_database_rejects_record_update_and_delete(self):
        summary = get_postgame_summary(self.registry, self.game["game_uuid"])
        with self.assertRaises(sqlite3.IntegrityError), self.registry.connect() as db:
            db.execute("UPDATE postgame_research_records SET revision_reason='changed' WHERE record_uuid=?",
                       (summary["record"]["record_uuid"],))
        with self.assertRaises(sqlite3.IntegrityError), self.registry.connect() as db:
            db.execute("DELETE FROM postgame_research_records WHERE record_uuid=?",
                       (summary["record"]["record_uuid"],))

    def test_notes_are_separate_append_only_revisions(self):
        first = save_analyst_notes(self.registry, self.game["game_uuid"],
                                   {key: "first" if key == "lessons_learned" else "" for key in NOTE_FIELDS})
        second = save_analyst_notes(self.registry, self.game["game_uuid"],
                                    {key: "revised" if key == "lessons_learned" else "" for key in NOTE_FIELDS})
        self.assertEqual((first["revision_number"], second["revision_number"]), (1, 2))
        self.assertEqual(second["supersedes_note_revision_uuid"], first["note_revision_uuid"])
        with self.registry.connect() as db:
            rows = db.execute("SELECT notes_json FROM analyst_note_revisions ORDER BY revision_number").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(json.loads(rows[0][0])["lessons_learned"], "first")

    def test_postkickoff_source_snapshot_is_not_used_as_closing_price(self):
        record = nfl.polymarket_us_records(
            fixture("nfl_polymarket_us_event.json"), 2026, "PRE", "2026-08-15T00:30:00Z")[0]
        record["source_values"]["entry_price"] = .99
        self.registry.link_source(record)
        revised = materialize_postgame_summary(self.registry, self.game["game_uuid"], "postkickoff source update")
        self.assertFalse(revised["created"])
        summary = get_postgame_summary(self.registry, self.game["game_uuid"])
        self.assertNotEqual(summary["record"]["payload"]["market_snapshot"]["closing_polymarket_probability"], .99)

    def test_api_returns_summary_and_creates_note_revision(self):
        import trader_dashboard
        with mock.patch.object(nfl, "PRODUCTION_DB", self.path):
            client = trader_dashboard.app.test_client()
            response = client.get(f"/api/nfl-games/{self.game['game_uuid']}/research-summary")
            self.assertEqual(response.status_code, 200)
            notes = {key: "" for key in NOTE_FIELDS}; notes["lessons_learned"] = "Keep the evidence."
            response = client.post(f"/api/nfl-games/{self.game['game_uuid']}/analyst-notes",
                                   json={"notes": notes})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()["revision_number"], 1)

    def test_game_flow_exposes_summary_only_for_final_game(self):
        card = next(item for item in self.registry.game_flow_snapshot()["games"]
                    if item["game_uuid"] == self.game["game_uuid"])
        self.assertEqual(card["status"], "FINAL")
        self.assertIsNotNone(card["research_summary"])


class PostGameResearchUITests(unittest.TestCase):
    def test_expandable_analyst_report_assets_are_present(self):
        html = Path("game_flow_dashboard.html").read_text(encoding="utf-8")
        script = Path("postgame_research.js").read_text(encoding="utf-8")
        self.assertIn("postgame_research.js", html)
        self.assertIn("Post-Game Research Summary", script)
        self.assertIn("Research Quality", script)
        self.assertIn("Save New Notes Revision", script)
        self.assertIn('game.status === "FINAL"', script)


if __name__ == "__main__":
    unittest.main()
