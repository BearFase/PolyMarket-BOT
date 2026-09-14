"""Position sync must survive null fields without inventing values.

On 2026-09-13 the exchange started sending "fees": null for new positions, and
one bad field froze every position on the dashboard for hours. These tests pin
that a null fee is harmless, that a missing valuation is refused rather than
shown as a fake zero, and that one malformed position never blocks the rest.
Hermetic: no network, no real files.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

import monitor_positions
import sync_positions_api as spa

SLUG = "aec-nfl-dal-nyg-2026-09-13"
TOTAL_SLUG = "tsc-nfl-dal-nyg-2026-09-13-total-46pt5"


def raw_position(**overrides):
    position = {
        "marketMetadata": {"title": "DAL Cowboys vs NY Giants", "outcome": "Cowboys",
                           "eventSlug": "nfl-dal-nyg-2026-09-13"},
        "netPositionDecimal": "20",
        "qtyBoughtDecimal": "20",
        "qtySoldDecimal": "0",
        "cost": {"value": "11.00"},
        "cashValue": {"value": "12.40"},
        "fees": {"value": "0.20"},
    }
    position.update(overrides)
    return position


class ParsePositionTests(unittest.TestCase):
    def test_null_fees_parse_as_zero_without_touching_pnl(self):
        parsed = spa.parse_position(SLUG, raw_position(fees=None), 1)
        self.assertEqual(parsed["fees"], 0.0)
        self.assertEqual(parsed["pnl"], 1.40)

    def test_null_metadata_falls_back_to_the_slug(self):
        parsed = spa.parse_position(SLUG, raw_position(marketMetadata=None), 1)
        self.assertEqual(parsed["market"], SLUG)
        self.assertEqual(parsed["event_slug"], "unknown")

    def test_null_cash_value_is_refused_not_shown_as_zero(self):
        with self.assertRaises(ValueError):
            spa.parse_position(SLUG, raw_position(cashValue=None), 1)

    def test_missing_cost_is_refused_not_shown_as_zero(self):
        position = raw_position()
        del position["cost"]
        with self.assertRaises(ValueError):
            spa.parse_position(SLUG, position, 1)


class SyncIsolationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.positions_file = os.path.join(tmp.name, "real_positions.json")
        patches = [
            mock.patch.object(spa, "POSITIONS_FILE", self.positions_file),
            mock.patch.object(spa, "AUDIT_LOG", os.path.join(tmp.name, "position_audit.log")),
            mock.patch.object(spa, "fetch_balances", return_value={"cash": 50.0}),
            mock.patch("settle_positions.fetch_activities", return_value=[]),
            mock.patch("settle_positions.settle_missing", return_value=[]),
            mock.patch("price_history.append_snapshot"),
            mock.patch("builtins.print"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def sync(self, positions):
        with mock.patch.object(spa, "fetch_positions_from_api", return_value={"positions": positions}):
            return spa.sync_positions()

    def test_one_malformed_position_does_not_block_the_rest(self):
        result = self.sync({SLUG: raw_position(fees=None), TOTAL_SLUG: raw_position(cashValue=None)})
        self.assertEqual([p["market_slug"] for p in result["positions"]], [SLUG])
        self.assertEqual(result["skipped_positions"], [TOTAL_SLUG])
        with open(self.positions_file, encoding="utf-8") as handle:
            self.assertEqual(len(json.load(handle)["positions"]), 1)

    def test_unparseable_position_keeps_its_last_verified_record(self):
        first = self.sync({TOTAL_SLUG: raw_position()})
        second = self.sync({SLUG: raw_position(), TOTAL_SLUG: raw_position(cashValue=None)})
        kept = next(p for p in second["positions"] if p["market_slug"] == TOTAL_SLUG)
        self.assertTrue(kept["stale"])
        self.assertEqual(kept["current_value"], first["positions"][0]["current_value"])
        self.assertEqual(len({p["id"] for p in second["positions"]}), 2)


class MonitorNullTests(unittest.TestCase):
    def test_monitor_skips_unvalued_positions_and_survives_null_metadata(self):
        positions = {SLUG: raw_position(marketMetadata=None), TOTAL_SLUG: raw_position(cashValue=None)}
        with mock.patch.object(monitor_positions, "fetch_positions_from_api",
                               return_value={"positions": positions}), \
                mock.patch.object(monitor_positions, "load_previous_state", return_value={}), \
                mock.patch.object(monitor_positions, "save_state") as save_state, \
                mock.patch.object(monitor_positions, "send_telegram_alert") as alert, \
                mock.patch.object(monitor_positions, "log_event"):
            monitor_positions.monitor_positions()
        save_state.assert_called_once()
        self.assertEqual(sorted(save_state.call_args.args[0]), [SLUG])
        alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
