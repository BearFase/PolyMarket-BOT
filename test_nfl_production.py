import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

import nfl_daily_update as workflow
import nfl_research_report as report
import nfl_schedule as nfl
from paper_trader import PaperTrader


FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ProductionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_development_and_production_are_separate(self):
        development = nfl.NFLRegistry(self.root / "development.db", environment="development")
        production = nfl.NFLRegistry(self.root / "production.db", environment="production")
        development.ingest_schedule_payload(fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
        self.assertEqual(development.status()["total_games"], 2)
        self.assertEqual(production.status()["total_games"], 0)

    def test_wrong_environment_write_is_prevented(self):
        path = self.root / "registry.db"
        nfl.NFLRegistry(path, environment="production")
        with self.assertRaises(RuntimeError):
            nfl.NFLRegistry(path, environment="development")

    def test_cli_requires_explicit_environment(self):
        with self.assertRaises(SystemExit):
            nfl.main(["status"])

    def test_conflict_report_contains_closest_game_and_classification(self):
        registry = nfl.NFLRegistry(self.root / "production.db", environment="production")
        registry.ingest_schedule_payload(fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
        registry.link_source({
            "source_type": "ODDS_API", "league": "NFL", "season": 2026,
            "season_type": "PRE", "source_event_id": "reversed",
            "away_team": "Baltimore Ravens", "home_team": "Pittsburgh Steelers",
            "kickoff_utc": "2026-08-14T23:30:00Z", "market_type": "h2h",
        })
        item = registry.conflict_report()[0]
        self.assertEqual(item["rejection_code"], "HOME_AWAY_CONFLICT")
        self.assertEqual(item["classification"], "bad source home/away orientation")
        self.assertEqual(item["closest_canonical_game"], "NFL-2026-PRE-W1-PIT-BAL")


class SimulationAndResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = nfl.NFLRegistry(Path(self.temp.name) / "production.db", environment="production")
        self.registry.ingest_schedule_payload(fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
        self.game = self.registry.list_games("PRE")[0]

    def tearDown(self):
        self.temp.cleanup()

    def test_simulation_tracks_are_immutable_and_do_not_touch_paper(self):
        paper_path = Path(self.temp.name) / "paper.json"
        paper = PaperTrader(
            config_path=self.root_config(), state_path=paper_path,
            legacy_state_path=Path(self.temp.name) / "legacy-missing.json")
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "trade-1", "Pittsburgh Steelers", 1000, .5)
        first = self.registry.create_simulation_tracks()
        second = self.registry.create_simulation_tracks()
        self.assertEqual(first, 5)
        self.assertEqual(second, 0)
        self.assertEqual(paper.get_summary()["cash"], 1000)
        self.assertEqual(paper.get_summary()["open_positions"], 0)

    def root_config(self):
        path = Path(self.temp.name) / "paper-config.json"
        path.write_text(json.dumps({"auto_trade": False}), encoding="utf-8")
        return path

    def test_binary_share_simulation_accounting(self):
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "trade-1", "Pittsburgh Steelers", 1000, .5)
        self.registry.create_simulation_tracks()
        self.registry.ingest_schedule_payload(fixture("nfl_espn_final.json"), 2026, "PRE", "2")
        self.registry.settle_simulations()
        with self.registry.connect() as db:
            row = db.execute("SELECT * FROM simulation_tracks WHERE track_name='LARGEST_QUALIFYING_BUY'").fetchone()
        self.assertEqual(row["result"], "WIN")
        self.assertEqual(row["hypothetical_payout"], 200)
        self.assertEqual(row["hypothetical_return"], 100)

    def test_conflicting_final_result_is_preserved_and_not_applied(self):
        self.registry.ingest_schedule_payload(fixture("nfl_espn_final.json"), 2026, "PRE", "2")
        conflict = {
            "source_event_id": "401900002", "source_name": "ESPN_STRUCTURED_NFL",
            "away_team": "Pittsburgh Steelers", "home_team": "Baltimore Ravens",
            "winner_team": "Baltimore Ravens", "away_score": 17, "home_score": 24,
            "final": True,
        }
        self.assertFalse(self.registry.update_authoritative_result(conflict))
        with self.registry.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM result_conflicts").fetchone()[0], 1)
        self.assertEqual(self.registry.list_games("PRE")[0]["final_winner_team_id"], "PIT")

    def test_largest_buy_side_won_false_and_null(self):
        self.registry.record_game_flow_activity(
            self.game["game_uuid"], "trade-bal", "Baltimore Ravens", 1000, .5)
        self.registry.ingest_schedule_payload(fixture("nfl_espn_final.json"), 2026, "PRE", "2")
        self.assertEqual(self.registry.list_games("PRE")[0]["largest_buy_side_won"], 0)
        hof = self.registry.list_games("HOF")[0]
        self.assertIsNone(hof["largest_buy_side_won"])


class WorkflowAndReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = nfl.NFLRegistry(self.root / "production.db", environment="production")

    def tearDown(self):
        self.temp.cleanup()

    def test_step_failure_does_not_stop_later_steps(self):
        with mock.patch.object(workflow, "sync_schedule", side_effect=RuntimeError("secret=bad")), \
             mock.patch.object(workflow, "fetch_odds_api", return_value=[]), \
             mock.patch.object(workflow, "fetch_polymarket_us", return_value={"events": []}), \
             mock.patch.object(workflow, "refresh_game_flow_activity", return_value={"attached": 0, "orphans": 0}), \
             mock.patch.object(workflow, "PaperTrader") as trader:
            trader.return_value.settle_resolved_positions.return_value = []
            trader.return_value.get_summary.return_value = {
                "current_cash": 1000, "total_equity": 1000, "open_positions": 0,
                "realized_pnl": 0, "unrealized_pnl": 0,
            }
            steps, errors = workflow.run_workflow(self.registry, no_telegram=True)
        self.assertEqual(steps["schedule_sync"]["status"], "FAILED")
        self.assertEqual(steps["polymarket_us_link"]["status"], "SUCCESS")
        self.assertNotIn("bad", json.dumps(errors))

    def test_workflow_lock_blocks_second_process(self):
        lock = self.root / "workflow.lock"
        with mock.patch.object(workflow, "LOCK_FILE", lock):
            with workflow.WorkflowLock():
                with self.assertRaises(RuntimeError):
                    with workflow.WorkflowLock():
                        pass
            self.assertFalse(lock.exists())

    def test_empty_scan_is_success_but_source_failure_is_failure(self):
        self.assertEqual(nfl.odds_api_records([], 2026, "PRE"), [])
        fake = mock.Mock(); fake.get.side_effect = requests.Timeout()
        with self.assertRaises(requests.Timeout):
            nfl.fetch_odds_api(session=fake)

    def test_report_is_paper_research_only(self):
        paper = mock.Mock()
        paper.get_summary.return_value = {
            "current_cash": 1000, "total_equity": 1000, "open_positions": 0,
            "realized_pnl": 0, "unrealized_pnl": 0,
        }
        text = report.build_report(self.registry, paper=paper)
        self.assertIn("Paper bankroll/equity", text)
        self.assertNotIn("real position", text.casefold())
        self.assertNotIn("real-money", text.casefold())

    def test_telegram_failure_is_returned_not_raised(self):
        fake = mock.Mock(); fake.post.side_effect = requests.Timeout()
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "1"}):
            result = report.send_report("test", session=fake)
        self.assertFalse(result["sent"])


class NFLGameFlowTests(unittest.TestCase):
    def test_canonical_grouping_side_separation_cents_and_winner_markup(self):
        html = Path("game_flow_dashboard.html").read_text(encoding="utf-8")
        self.assertIn("data-game-uuid", html)
        self.assertIn("NFL Game Flow", html)
        self.assertIn("execution_price", html)
        self.assertIn("+'¢'", html)
        self.assertIn("winner_team_id", html)

    def test_snapshot_groups_by_canonical_uuid_and_separates_sides(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = nfl.NFLRegistry(Path(directory) / "production.db", environment="production")
            registry.ingest_schedule_payload(fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
            game = registry.list_games("PRE")[0]
            registry.record_game_flow_activity(game["game_uuid"], "away-big", "Pittsburgh Steelers", 900, .53)
            registry.record_game_flow_activity(game["game_uuid"], "away-small", "Pittsburgh Steelers", 100, .51)
            registry.record_game_flow_activity(game["game_uuid"], "home", "Baltimore Ravens", 500, .47)
            card = next(item for item in registry.game_flow_snapshot()["games"]
                        if item["game_uuid"] == game["game_uuid"])
            self.assertEqual(card["canonical_game_id"], "NFL-2026-PRE-W1-PIT-BAL")
            self.assertEqual([row["amount_usd"] for row in card["buys"]["PIT"]], [900, 100])
            self.assertEqual([row["amount_usd"] for row in card["buys"]["BAL"]], [500])

    def test_nfl_game_flow_api_uses_production_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "production.db"
            registry = nfl.NFLRegistry(path, environment="production")
            registry.ingest_schedule_payload(fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
            from trader_dashboard import app
            with mock.patch.object(nfl, "PRODUCTION_DB", path):
                response = app.test_client().get("/api/nfl-game-flow")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["environment"], "production")
            self.assertEqual(len(response.get_json()["games"]), 2)

    def test_game_flow_snapshot_includes_regular_season_games(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = nfl.NFLRegistry(Path(directory) / "production.db", environment="production")
            registry.ingest_schedule_payload(fixture("nfl_espn_regular.json"), 2026, "REG", "1")
            cards = registry.game_flow_snapshot()["games"]
            self.assertTrue(cards)
            self.assertTrue(all(card["season_type"] == "REG" for card in cards))


if __name__ == "__main__":
    unittest.main()
