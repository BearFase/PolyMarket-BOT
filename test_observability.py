import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

import big_money_tape as tape
import system_status


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}", response=self)


class TradeLabelTests(unittest.TestCase):
    def test_moneyline_label(self):
        meta = {
            "market_type": "moneyline",
            "event_title": "Detroit Tigers vs Cleveland Guardians",
        }
        self.assertEqual(
            tape.format_trade_label(meta, "Detroit Tigers"),
            "Detroit Tigers moneyline — Detroit Tigers vs Cleveland Guardians")

    def test_spread_labels_both_sides(self):
        meta = {
            "market_type": "spreads",
            "event_title": "Detroit Tigers vs Cleveland Guardians",
            "question": "Will the Detroit Tigers cover -1.5 vs the Cleveland Guardians in DET vs CLE?",
            "long_label": "-1.50",
            "short_label": "+1.50",
        }
        self.assertEqual(
            tape.format_trade_label(meta, "-1.50"),
            "Detroit Tigers -1.50 vs Cleveland Guardians")
        self.assertEqual(
            tape.format_trade_label(meta, "+1.50"),
            "Cleveland Guardians +1.50 vs Detroit Tigers")

    def test_totals_label(self):
        meta = {
            "market_type": "totals",
            "event_title": "Atlanta Braves vs Chicago Cubs",
            "question": "Will the total in Atlanta Braves vs Chicago Cubs be more than 8.5?",
        }
        self.assertEqual(
            tape.format_trade_label(meta, "Under"),
            "Atlanta Braves vs Chicago Cubs — Under 8.5")

    def test_missing_metadata_falls_back_without_guessing(self):
        self.assertEqual(
            tape.format_trade_label({"market_type": "spreads"}, "-1.50"),
            "-1.50")


class TapeThresholdTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db = tape.DB_FILE
        self.original_log = tape.LOG_FILE
        self.original_threshold = tape.MIN_DISPLAY_TRADE_USD
        tape.DB_FILE = Path(self.temp_dir.name) / "tape.db"
        tape.LOG_FILE = Path(self.temp_dir.name) / "tape.log"
        tape.MIN_DISPLAY_TRADE_USD = 5
        tape.init_db()
        self.slug = "test-market"
        with tape._market_lock:
            tape._market_map[self.slug] = {
                "market_slug": self.slug,
                "event_slug": "test-event",
                "event_title": "Alpha vs Beta",
                "league": "mlb",
                "question": "Who will win Alpha vs Beta?",
                "market_type": "moneyline",
                "long_label": "Alpha",
                "short_label": "Beta",
            }

    def tearDown(self):
        with tape._market_lock:
            tape._market_map.pop(self.slug, None)
        tape.DB_FILE = self.original_db
        tape.LOG_FILE = self.original_log
        tape.MIN_DISPLAY_TRADE_USD = self.original_threshold
        self.temp_dir.cleanup()

    @mock.patch("big_money_tape.log")
    def test_small_trade_is_stored_but_hidden(self, tape_log):
        for trade_time, quantity in (("2026-01-01T00:00:01Z", 4),
                                     ("2026-01-01T00:00:02Z", 20)):
            tape.record_trade({
                "marketSlug": self.slug,
                "tradeTime": trade_time,
                "price": 0.5,
                "quantity": quantity,
                "taker": {"intent": "ORDER_INTENT_BUY_LONG"},
            })
        result = tape.snapshot()
        self.assertEqual(result["summary"]["internal_tracked"], 2)
        self.assertEqual(result["summary"]["tracked"], 1)
        self.assertEqual(len(result["open"]), 1)
        self.assertEqual(result["open"][0]["raw_selection"], "Alpha")
        self.assertIn("Alpha vs Beta", result["open"][0]["selection"])
        tape_log.assert_called_once()
        self.assertIn("$10.00 risk", tape_log.call_args.args[0])


class DiscoveryRetryTests(unittest.TestCase):
    def test_transient_status_retries_then_succeeds(self):
        responses = [
            FakeResponse(504),
            FakeResponse(502),
            FakeResponse(200, {"events": [{"slug": "ok"}]}),
        ]
        sleeps = []

        def request_get(*args, **kwargs):
            return responses.pop(0)

        events = tape._request_events(
            {"tagSlug": "mlb"}, request_get=request_get,
            sleep=sleeps.append, jitter=lambda low, high: 0)
        self.assertEqual(events, [{"slug": "ok"}])
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_non_transient_404_is_not_retried(self):
        calls = []

        def request_get(*args, **kwargs):
            calls.append(1)
            return FakeResponse(404)

        with self.assertRaises(requests.HTTPError):
            tape._request_events(
                {"tagSlug": "mlb"}, request_get=request_get,
                sleep=lambda delay: self.fail("404 must not sleep"),
                jitter=lambda low, high: 0)
        self.assertEqual(len(calls), 1)


class SystemStatusTests(unittest.TestCase):
    def test_atomic_write_uses_replace_and_produces_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            real_replace = os.replace
            with mock.patch("system_status.os.replace",
                            wraps=real_replace) as replace:
                system_status.update_status(
                    path=path, last_position_sync_at="2026-01-01T00:00:00Z")
            replace.assert_called_once()
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))
                ["last_position_sync_at"],
                "2026-01-01T00:00:00Z")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_error_summary_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            system_status.mark_error(
                "test", "timeout API_KEY=do-not-show", path=path)
            error = system_status.read_status(path)["last_error"]
            self.assertNotIn("do-not-show", error["message"])
            self.assertIn("[redacted]", error["message"])

    def test_status_api_returns_sanitized_shape(self):
        from trader_dashboard import app
        fixture = {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "services": {"trade_stream": {"state": "healthy"}},
            "last_error": None,
        }
        with mock.patch("trader_dashboard.dashboard_status",
                        return_value=fixture):
            response = app.test_client().get("/api/system-status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), fixture)


if __name__ == "__main__":
    unittest.main()
