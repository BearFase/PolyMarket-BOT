import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import nfl_schedule as nfl
import nfl_daily_update as workflow
from nfl_postgame_research import materialize_postgame_summary
from telegram_notification_center import TelegramNotificationCenter, load_settings, sanitized_error

FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class PaperStub:
    def __init__(self, open_positions=0):
        self.open_positions = open_positions
        self.state = {"open_positions": [], "closed_positions": []}
    def get_summary(self):
        return {"starting_bankroll": 1000, "cash": 900 if self.open_positions else 1000,
                "total_equity": 995 if self.open_positions else 1000,
                "open_positions": self.open_positions, "current_exposure": 100 if self.open_positions else 0,
                "realized_pnl": 0, "unrealized_pnl": -5}


class ResponseStub:
    def __init__(self, message_id=42, error=None): self.message_id, self.error = message_id, error
    def raise_for_status(self):
        if self.error: raise self.error
    def json(self): return {"ok": True, "result": {"message_id": self.message_id}}


class SessionStub:
    def __init__(self, responses=None): self.responses, self.calls = list(responses or [ResponseStub()]), []
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0) if self.responses else ResponseStub(42 + len(self.calls))


class NotificationCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.registry = nfl.NFLRegistry(root / "production.db", environment="production")
        self.registry.ingest_schedule_payload(fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
        self.config = root / "config.json"
        self.config.write_text(json.dumps({"telegram_timezone": "America/Los_Angeles",
          "telegram_pregame_minutes_before": 60, "telegram_warning_cooldown_minutes": 180}), encoding="utf-8")
        self.session = SessionStub()
        self.center = TelegramNotificationCenter(self.registry, PaperStub(), self.session, self.config)
        self.game = self.registry.list_games("PRE")[0]

    def tearDown(self): self.temp.cleanup()

    def test_morning_brief_format_today_local_time_and_empty_paper(self):
        now = datetime(2026, 8, 14, 7, tzinfo=ZoneInfo("America/Los_Angeles"))
        text, date_key = self.center.build_morning_brief(now)
        self.assertEqual(date_key, "2026-08-14")
        self.assertIn("NFL RESEARCH MORNING BRIEF", text)
        self.assertIn("Pittsburgh Steelers @ Baltimore Ravens", text)
        self.assertIn("4:30 PM PDT", text)
        self.assertIn("No paper trades are open", text)
        self.assertNotIn("real position", text.casefold())

    def test_nonempty_paper_portfolio(self):
        center = TelegramNotificationCenter(self.registry, PaperStub(1), self.session, self.config)
        text, _ = center.build_morning_brief(datetime(2026, 8, 14, 7, tzinfo=ZoneInfo("America/Los_Angeles")))
        self.assertIn("Open positions: 1", text); self.assertIn("Open exposure: $100.00", text)

    def test_research_tracks_and_completed_since_prior_report(self):
        self.registry.create_simulation_tracks()
        with self.registry.connect() as db:
            db.execute("UPDATE simulation_tracks SET result='WIN' WHERE track_name='HOME_TEAM'")
        text, _ = self.center.build_morning_brief(datetime(2026, 8, 14, 7, tzinfo=ZoneInfo("America/Los_Angeles")))
        self.assertIn("Home team track: 2-0", text)
        self.assertIn("Completed since prior brief: 0", text)

    @mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "1"})
    def test_morning_duplicate_prevention_and_message_id(self):
        now = datetime(2026, 8, 14, 7, tzinfo=ZoneInfo("America/Los_Angeles"))
        first = self.center.send_morning_brief(now)
        second = self.center.send_morning_brief(now)
        self.assertEqual(first["status"], "DELIVERED"); self.assertEqual(first["message_id"], "42")
        self.assertEqual(second["status"], "SUPPRESSED"); self.assertEqual(len(self.session.calls), 1)

    @mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "1"})
    def test_morning_due_catches_up_after_configured_hour_once(self):
        early = datetime(2026, 8, 14, 6, 59, tzinfo=ZoneInfo("America/Los_Angeles"))
        late = datetime(2026, 8, 14, 9, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.assertFalse(self.center.morning_due(early))
        self.assertTrue(self.center.morning_due(late))
        self.assertEqual("DELIVERED", self.center.send_morning_brief(late)["status"])
        self.assertFalse(self.center.morning_due(late))

    def test_pregame_timing_and_no_alert_after_kickoff(self):
        kickoff = nfl.parse_time(self.game["scheduled_kickoff_utc"])
        self.assertEqual(len(self.center.due_pregame(kickoff - timedelta(minutes=30))), 1)
        self.assertEqual(self.center.due_pregame(kickoff + timedelta(seconds=1)), [])
        with mock.patch("telegram_notification_center.datetime") as dt:
            dt.now.return_value = kickoff + timedelta(seconds=1)
            with self.assertRaises(ValueError): self.center.build_pregame_alert(self.game["game_uuid"])

    def test_game_flow_activity_and_whole_cent_format(self):
        self.registry.record_game_flow_activity(self.game["game_uuid"], "trade", self.game["away_team_name"], 8200, .53)
        with mock.patch("telegram_notification_center.datetime") as dt:
            dt.now.return_value = nfl.parse_time(self.game["scheduled_kickoff_utc"]) - timedelta(hours=2)
            text = self.center.build_pregame_alert(self.game["game_uuid"])
        self.assertIn("$8,200.00 @ 53¢", text)
        self.assertIn("no qualifying trades", text)

    @mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "1"})
    def test_pregame_duplicate_prevention(self):
        kickoff = nfl.parse_time(self.game["scheduled_kickoff_utc"])
        now = kickoff - timedelta(minutes=30)
        with mock.patch("telegram_notification_center.datetime") as dt:
            dt.now.return_value = now
            first = self.center.process_pregame(now)
            second = self.center.process_pregame(now)
        self.assertEqual(first[0]["status"], "DELIVERED"); self.assertEqual(second[0]["status"], "SUPPRESSED")

    def _finalize(self):
        odds = nfl.odds_api_records(fixture("nfl_odds_event.json"), 2026, "PRE", "2026-08-14T22:55:00Z")[0]
        market = nfl.polymarket_us_records(fixture("nfl_polymarket_us_event.json"), 2026, "PRE", "2026-08-14T23:00:00Z")[0]
        self.registry.link_source(odds); self.registry.link_source(market)
        self.registry.record_game_flow_activity(self.game["game_uuid"], "trade", self.game["away_team_name"], 18000, .62, "2026-08-14T23:10:00Z")
        self.registry.create_simulation_tracks()
        self.registry.ingest_schedule_payload(fixture("nfl_espn_final.json"), 2026, "PRE", "2")
        self.registry.settle_simulations()
        return materialize_postgame_summary(self.registry, self.game["game_uuid"], "test")

    def test_final_requires_authoritative_result_and_summary(self):
        self.assertEqual(self.center.due_finals(), [])
        self._finalize()
        due = self.center.due_finals()
        self.assertTrue(due); self.assertIn("Research Summary revision", self.center.build_final_alert(due[-1]))

    @mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "1"})
    def test_final_duplicate_and_corrected_revision(self):
        self._finalize()
        first = self.center.process_finals(); second = self.center.process_finals()
        self.assertEqual(first[-1]["status"], "DELIVERED"); self.assertTrue(all(x["status"] == "SUPPRESSED" for x in second))
        previous_revision = self.center.due_finals()[-1]["revision_number"]
        self.registry.record_game_flow_activity(self.game["game_uuid"], "late", self.game["home_team_name"], 20, .55, "2026-08-15T00:10:00Z")
        materialize_postgame_summary(self.registry, self.game["game_uuid"], "correction")
        due = self.center.due_finals()[-1]
        self.assertEqual(due["revision_number"], previous_revision + 1); self.assertIn("CORRECTED FINAL", self.center.build_final_alert(due))

    def test_warning_aggregation(self):
        self.registry.record_orphan_trade({"id": "o1"})
        warnings = self.center.warning_candidates()
        self.assertEqual(next(w["count"] for w in warnings if w["code"] == "ORPHAN_GAME_FLOW"), 1)

    @mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "1"})
    def test_warning_cooldown(self):
        self.registry.record_orphan_trade({"id": "o1"})
        first = self.center.process_warnings(); second = self.center.process_warnings()
        self.assertEqual(first[0]["status"], "DELIVERED"); self.assertEqual(second[0]["reason"], "cooldown")

    @mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "1"})
    def test_meaningful_workflow_recovery_alert(self):
        with self.registry.connect() as db:
            db.execute("INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?)",
              ("failed", "production", 0, "2026-08-14T01:00:00Z", "2026-08-14T01:01:00Z",
               "COMPLETED_WITH_ERRORS", "{}", json.dumps([{"step": "odds_api_link", "error": "Timeout: operation failed"}])))
        sent = self.center.process_warnings()
        self.assertTrue(any(item["status"] == "DELIVERED" for item in sent))
        with self.registry.connect() as db:
            db.execute("INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?)",
              ("recovered", "production", 0, "2026-08-14T02:00:00Z", "2026-08-14T02:01:00Z",
               "SUCCESS", "{}", "[]"))
        preview = self.center.process_warnings(preview=True)
        self.assertTrue(any(item.get("warning_code") == "RECOVERY_SOURCE_OUTAGE" for item in preview))

    @mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "1"})
    def test_delivery_failure_isolation_and_retry_accounting(self):
        self.center.session = SessionStub([ResponseStub(error=RuntimeError("token=secret")), ResponseStub(7)])
        now = datetime(2026, 8, 14, 7, tzinfo=ZoneInfo("America/Los_Angeles"))
        failed = self.center.send_morning_brief(now); delivered = self.center.send_morning_brief(now)
        self.assertEqual(failed["status"], "FAILED"); self.assertNotIn("secret", failed["failure"])
        self.assertEqual(delivered["retry_count"], 1)

    def test_journal_is_immutable(self):
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "1"}):
            self.center.send_morning_brief(datetime(2026, 8, 14, 7, tzinfo=ZoneInfo("America/Los_Angeles")))
        row = self.center.journal_rows()[0]
        with self.assertRaises(sqlite3.IntegrityError), self.registry.connect() as db:
            db.execute("UPDATE notification_journal SET delivery_status='FAILED' WHERE notification_uuid=?", (row["notification_uuid"],))
        with self.assertRaises(sqlite3.IntegrityError), self.registry.connect() as db:
            db.execute("DELETE FROM notification_journal WHERE notification_uuid=?", (row["notification_uuid"],))

    def test_credential_sanitization(self):
        clean = sanitized_error("token=abc secret=xyz chat_id=123")
        self.assertNotIn("abc", clean); self.assertNotIn("xyz", clean); self.assertNotIn("123", clean)

    def test_missing_timezone_dependency_diagnostic(self):
        with mock.patch("telegram_notification_center.ZoneInfo", side_effect=__import__('zoneinfo').ZoneInfoNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "tzdata"): load_settings(self.config)

    def test_workflow_notification_failure_is_isolated(self):
        fake_center = mock.Mock()
        fake_center.process_pregame.side_effect = RuntimeError("delivery failed")
        fake_center.process_finals.return_value = []
        fake_center.process_warnings.return_value = []
        fake_center.morning_due.return_value = False
        trader = mock.Mock()
        trader.settle_resolved_positions.return_value = []
        trader.get_summary.return_value = PaperStub().get_summary()
        with mock.patch.object(workflow, "sync_schedule", return_value={}), \
             mock.patch.object(workflow, "fetch_odds_api", return_value=[]), \
             mock.patch.object(workflow, "fetch_polymarket_us", return_value={"events": []}), \
             mock.patch.object(workflow, "refresh_game_flow_activity", return_value={"attached": 0, "orphans": 0}), \
             mock.patch.object(workflow, "materialize_completed_summaries", return_value={"completed_games": 0}), \
             mock.patch.object(workflow, "PaperTrader", return_value=trader), \
             mock.patch.object(workflow, "TelegramNotificationCenter", return_value=fake_center):
            steps, errors = workflow.run_workflow(self.registry)
        self.assertEqual(steps["telegram_pregame"]["status"], "FAILED")
        self.assertEqual(steps["telegram_finals"]["status"], "SUCCESS")
        self.assertEqual(steps["postgame_research"]["status"], "SUCCESS")
        self.assertTrue(errors)

    def test_dry_run_uses_temporary_paper_ledger(self):
        root = Path(self.temp.name)
        live_paper = root / "paper_positions.json"
        live_paper.write_text(json.dumps({"version": 1, "starting_bankroll": 1000,
          "current_cash": 1000, "reserved_capital": 0, "total_equity": 1000,
          "realized_pnl": 0, "unrealized_pnl": 0, "open_exposure": 0,
          "open_positions": [], "closed_positions": [], "metadata": {}}), encoding="utf-8")
        before = live_paper.read_bytes()
        captured = {}
        def fake_run(registry, no_telegram=False, paper=None):
            captured["paper_path"] = paper.state_path
            return {}, []
        with mock.patch.object(workflow, "HERE", root), \
             mock.patch.object(workflow, "PRODUCTION_DB", self.registry.db_path), \
             mock.patch.object(workflow, "LOCK_FILE", root / "workflow.lock"), \
             mock.patch.object(workflow, "run_workflow", side_effect=fake_run):
            self.assertEqual(workflow.main(["--dry-run"]), 0)
        self.assertNotEqual(captured["paper_path"], live_paper)
        self.assertEqual(live_paper.read_bytes(), before)


if __name__ == "__main__": unittest.main()
