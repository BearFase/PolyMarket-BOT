import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import auto_trader
import dashboard_data
import system_status
import trader_dashboard
from paper_trader import PaperTrader


PROJECT = Path(__file__).parent


class WhaleDeactivationTests(unittest.TestCase):
    def test_startup_scripts_do_not_launch_whale_processes(self):
        startup = (PROJECT / "Start All Bots.cmd").read_text(encoding="utf-8").lower()
        opener = (PROJECT / "Open Dashboard.cmd").read_text(encoding="utf-8").lower()
        for source in (startup, opener):
            self.assertNotIn("whale_refresh", source)
            self.assertNotIn("trader_scanner.py", source)
            self.assertNotIn("auto_trader.py", source)
            self.assertNotIn("/whales", source)

    def test_daily_update_has_no_whale_component(self):
        source = (PROJECT / "archive" / "legacy_operations" / "daily_update.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("whale_refresh", source)
        self.assertNotIn("whale_data", source)
        self.assertNotIn("auto_trader", source)
        report = (PROJECT / "archive" / "legacy_operations" / "telegram_morning_report.py").read_text(
            encoding="utf-8").lower()
        self.assertNotIn("whale_data", report)
        self.assertNotIn("format_whales", report)
        server = (PROJECT / "dashboard_server.py").read_text(
            encoding="utf-8").lower()
        self.assertNotIn("whale_refresh", server)
        self.assertNotIn("whale_data", server)

    def test_whale_research_is_archived_outside_active_root(self):
        archived = PROJECT / "archive" / "whale_watch"
        for name in ("check_whale_positions.py", "polymarket_consensus_v2.py",
                     "trader_scanner.py", "whale_refresh.py"):
            self.assertTrue((archived / name).exists())
            self.assertFalse((PROJECT / name).exists())

    def test_dashboard_loads_without_whale_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dashboard_live.html").write_text(
                "<html><body>Active dashboard</body></html>", encoding="utf-8")
            (root / "real_positions.json").write_text(
                '{"positions":[]}', encoding="utf-8")
            with mock.patch.object(trader_dashboard, "HERE", root):
                client = trader_dashboard.app.test_client()
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                response.close()
                response = client.get("/real_positions.json")
                self.assertEqual(response.status_code, 200)
                response.close()
                self.assertEqual(client.get("/whale_data.json").status_code, 404)
                self.assertEqual(client.get("/whales").status_code, 404)

    def test_dashboard_bundle_has_no_whale_source(self):
        self.assertNotIn("whales", dashboard_data.SOURCES)
        html = (PROJECT / "dashboard_live.html").read_text(encoding="utf-8").lower()
        self.assertNotIn("whale_data.json", html)
        self.assertNotIn("/whales", html)
        self.assertNotIn("whale watch", html)

    def test_no_paper_entry_strategy_is_active(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = auto_trader.main()
        self.assertEqual(result, 0)
        self.assertIn("No active paper-entry strategy is configured.", output.getvalue())
        self.assertFalse(hasattr(auto_trader, "run_consensus_check"))

    def test_paper_accounting_and_settlement_remain_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trader = PaperTrader(
                root / "paper_config.json",
                root / "paper_positions.json",
                root / "paper_state.json",
            )
            self.assertEqual(trader.get_summary()["total_equity"], 1000)
            self.assertEqual(trader.settle_resolved_positions(), [])

    def test_system_status_has_no_whale_health_indicator(self):
        with tempfile.TemporaryDirectory() as directory:
            status = system_status.dashboard_status(Path(directory) / "status.json")
        self.assertNotIn("whale_refresh", status["services"])
        self.assertNotIn("last_whale_refresh_at", system_status._defaults())


if __name__ == "__main__":
    unittest.main()
