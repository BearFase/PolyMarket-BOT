"""Tests for the NFL permanent trade journal. Instrumentation only."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import big_money_tape as tape
import nfl_trade_journal as journal

SLUG = "nfl-sf-lar-2026-09-10-moneyline"
META = {
    "market_slug": SLUG,
    "event_slug": "nfl-sf-lar-2026-09-10",
    "event_title": "San Francisco vs. Los Angeles R",
    "league": "nfl",
    "question": "Who will win San Francisco vs. Los Angeles R?",
    "market_type": "moneyline",
    "long_label": "49ers",
    "short_label": "Rams",
    "source_start_time": "2026-09-11T00:35:00Z",
}


def trade(trade_id, intent="ORDER_INTENT_BUY_LONG", price="0.35", quantity="100",
          when="2026-09-10T20:00:00.123456789Z", **extra):
    payload = {"marketSlug": SLUG, "price": price, "quantity": quantity,
               "tradeTime": when, "taker": {"intent": intent}}
    if trade_id is not None:
        payload["id"] = trade_id
    payload.update(extra)
    return payload


def query(path, sql, params=()):
    """Read with a connection that is always closed, so Windows can delete temp dirs."""
    db = sqlite3.connect(path)
    try:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, params)]
    finally:
        db.close()


class JournalTestCase(unittest.TestCase):
    def setUp(self):
        journal._reset_for_tests()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "nfl_trade_journal.db"
        self.journal = journal.NFLTradeJournal(self.path)

    def tearDown(self):
        journal._reset_for_tests()
        self.temp.cleanup()

    def rows(self):
        return query(self.path, "SELECT * FROM nfl_trade_observations "
                                "ORDER BY trade_timestamp_utc, websocket_trade_id")


class ObservationTests(JournalTestCase):
    def test_every_taker_intent_is_recorded_including_sells(self):
        intents = ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_BUY_SHORT",
                   "ORDER_INTENT_SELL_LONG", "ORDER_INTENT_SELL_SHORT")
        for index, intent in enumerate(intents):
            self.assertTrue(self.journal.record(trade(f"T{index}", intent=intent), META))
        rows = {row["taker_intent"]: row for row in self.rows()}
        self.assertEqual(set(rows), set(intents))
        sell = rows["ORDER_INTENT_SELL_LONG"]
        self.assertEqual((sell["taker_direction"], sell["instrument_side"], sell["outcome_label"]),
                         ("SELL", "LONG", "49ers"))
        short = rows["ORDER_INTENT_BUY_SHORT"]
        self.assertEqual(short["outcome_label"], "Rams")
        self.assertAlmostEqual(short["instrument_price"], 0.35)
        self.assertAlmostEqual(short["outcome_price"], 0.65)
        self.assertAlmostEqual(short["notional_usd"], 65.0)

    def test_unrecognized_intent_is_kept_and_flagged(self):
        self.journal.record(trade("T1", intent="ORDER_INTENT_SOMETHING_NEW"), META)
        (row,) = self.rows()
        self.assertEqual((row["taker_direction"], row["instrument_side"]), ("UNKNOWN", "UNKNOWN"))
        self.assertIsNone(row["outcome_price"])
        self.assertIn("UNRECOGNIZED_INTENT", json.loads(row["source_quality_flags_json"]))

    def test_invalid_price_is_kept_and_flagged(self):
        self.journal.record(trade("T1", price="1.0"), META)
        (row,) = self.rows()
        self.assertEqual(row["instrument_price"], 1.0)
        self.assertIsNone(row["outcome_price"])
        self.assertIsNone(row["notional_usd"])
        self.assertIn("PRICE_NOT_STRICTLY_BETWEEN_0_AND_1",
                      json.loads(row["source_quality_flags_json"]))

    def test_pregame_classification_uses_the_polymarket_event_start(self):
        self.journal.record(trade("pre", when="2026-09-11T00:34:59Z"), META)
        self.journal.record(trade("in", when="2026-09-11T00:35:01Z"), META)
        self.journal.record(trade("unknown"), dict(META, source_start_time=None))
        classes = {row["websocket_trade_id"]: row["pregame_classification"] for row in self.rows()}
        self.assertEqual(classes, {"pre": "PREGAME", "in": "IN_GAME", "unknown": "UNKNOWN"})

    def test_unknown_source_fields_are_recorded_by_name_only(self):
        self.journal.record(trade("T1", maker={"account": "acct-123"}, surprise="value-xyz"), META)
        (row,) = self.rows()
        stored = json.dumps(row)
        self.assertNotIn("acct-123", stored)
        self.assertNotIn("value-xyz", stored)
        paths = json.loads(row["raw_key_paths_json"])
        for path in ("maker", "maker.account", "surprise", "taker.intent"):
            self.assertIn(path, paths)
        raw = json.loads(row["raw_fields_json"])
        self.assertEqual(raw["taker.intent"], "ORDER_INTENT_BUY_LONG")
        self.assertEqual(raw["price"], "0.35")


class DedupeTests(JournalTestCase):
    def test_same_exchange_id_is_written_once_even_after_a_restart(self):
        self.assertTrue(self.journal.record(trade("DUP"), META))
        self.assertFalse(self.journal.record(trade("DUP"), META))
        restarted = journal.NFLTradeJournal(self.path)
        self.assertFalse(restarted.record(trade("DUP"), META))
        self.assertEqual(len(self.rows()), 1)

    def test_same_instant_fills_with_distinct_ids_are_both_kept(self):
        # Two equal fills in one burst: identical market, nanosecond, size, price
        # and intent. The MLB-style derived key cannot tell them apart; the
        # exchange id can.
        self.journal.record(trade("FILL-A"), META)
        self.journal.record(trade("FILL-B"), META)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["derived_trade_key"], rows[1]["derived_trade_key"])

    def test_missing_exchange_id_falls_back_to_the_derived_key(self):
        self.assertTrue(self.journal.record(trade(None), META))
        self.assertFalse(self.journal.record(trade(None), META))
        (row,) = self.rows()
        self.assertTrue(row["dedupe_key"].startswith("derived:"))
        self.assertIn("NO_EXCHANGE_TRADE_ID", json.loads(row["source_quality_flags_json"]))


class ImmutabilityTests(JournalTestCase):
    def test_observations_cannot_be_updated_or_deleted(self):
        self.journal.record(trade("T1"), META)
        for sql in ("UPDATE nfl_trade_observations SET contracts = 1",
                    "DELETE FROM nfl_trade_observations"):
            db = sqlite3.connect(self.path)
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute(sql)
            finally:
                db.close()
        self.assertEqual(len(self.rows()), 1)

    def test_coverage_start_is_written_once_and_frozen(self):
        self.journal.start_session("first")
        coverage = query(self.path, "SELECT value FROM journal_meta "
                                    "WHERE key='coverage_started_at'")[0]["value"]
        self.journal.start_session("second")
        again = query(self.path, "SELECT value FROM journal_meta "
                                 "WHERE key='coverage_started_at'")[0]["value"]
        self.assertEqual(coverage, again)
        self.assertEqual(len(query(self.path, "SELECT * FROM capture_sessions")), 2)
        db = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE journal_meta SET value='x' WHERE key='coverage_started_at'")
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM capture_sessions")
        finally:
            db.close()


class StatusTests(JournalTestCase):
    def test_status_reports_coverage_and_integrity_without_writing(self):
        absent = Path(self.temp.name) / "absent.db"
        self.assertEqual(journal.read_status(absent), {"database": str(absent), "started": False})
        self.assertFalse(absent.exists())
        self.journal.start_session("status")
        self.journal.record(trade("A", intent="ORDER_INTENT_SELL_SHORT"), META)
        self.journal.record(trade("B"), META)
        self.journal.record(trade("C"), META)  # same instant, size and price as B
        status = journal.read_status(self.path)
        self.assertEqual(status["observations"], 3)
        self.assertEqual(status["distinct_exchange_trade_ids"], 3)
        self.assertEqual(status["by_taker_intent"]["ORDER_INTENT_SELL_SHORT"], 1)
        self.assertEqual(status["capture_sessions"], 1)
        self.assertIsNotNone(status["coverage_started_at"])
        self.assertEqual(status["derived_keys_shared_by_distinct_trades"], 1)
        self.assertEqual(status["rows_sharing_a_derived_key"], 2)


class TapeHookTests(unittest.TestCase):
    def setUp(self):
        journal._reset_for_tests()
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.saved = (tape.DB_FILE, tape.MLB_RESEARCH_DB_FILE, tape.LOG_FILE,
                      tape.NFL_JOURNAL_DB_FILE)
        tape.DB_FILE = root / "tape.db"
        tape.MLB_RESEARCH_DB_FILE = root / "mlb-research.db"
        tape.LOG_FILE = root / "tape.log"
        tape.NFL_JOURNAL_DB_FILE = None
        tape.init_db()
        self.journal_path = root / "nfl_trade_journal.db"
        with tape._market_lock:
            tape._market_map[SLUG] = dict(META)
        patchers = [mock.patch.object(tape, "log"), mock.patch.object(tape, "mark_error")]
        self.log, self.mark_error = [patcher.start() for patcher in patchers]
        for patcher in patchers:
            self.addCleanup(patcher.stop)

    def tearDown(self):
        with tape._market_lock:
            tape._market_map.pop(SLUG, None)
        (tape.DB_FILE, tape.MLB_RESEARCH_DB_FILE, tape.LOG_FILE,
         tape.NFL_JOURNAL_DB_FILE) = self.saved
        journal._reset_for_tests()
        self.temp.cleanup()

    def test_journal_lives_beside_the_tape_database(self):
        self.assertEqual(tape._nfl_journal_path(), self.journal_path)

    def test_nfl_sells_reach_the_journal_and_the_display_is_unchanged(self):
        tape.record_trade(trade("BUY-1"))
        tape.record_trade(trade("SELL-1", intent="ORDER_INTENT_SELL_LONG",
                                when="2026-09-10T20:00:01Z"))
        intents = sorted(row["taker_intent"] for row in query(
            self.journal_path, "SELECT taker_intent FROM nfl_trade_observations"))
        self.assertEqual(intents, ["ORDER_INTENT_BUY_LONG", "ORDER_INTENT_SELL_LONG"])
        self.assertEqual(len(query(tape.DB_FILE, "SELECT id FROM bets")), 1)

    def test_derived_key_matches_the_tape_display_id(self):
        tape.record_trade(trade("BUY-1"))
        (bet,) = query(tape.DB_FILE, "SELECT id FROM bets")
        (row,) = query(self.journal_path, "SELECT derived_trade_key FROM nfl_trade_observations")
        self.assertEqual(row["derived_trade_key"], bet["id"])

    def test_journal_failure_never_breaks_the_tape(self):
        self.journal_path.mkdir()  # a directory where the database file should be
        self.assertTrue(tape.record_trade(trade("BUY-1")))
        self.assertEqual(len(query(tape.DB_FILE, "SELECT id FROM bets")), 1)
        self.mark_error.assert_called()
        self.assertEqual(journal.stats()["failed"], 1)

    def test_other_leagues_are_not_journaled(self):
        other = dict(META, league="mlb", market_slug="mlb-x", event_slug="mlb-x-event")
        with tape._market_lock:
            tape._market_map["mlb-x"] = other
        try:
            tape.record_trade(dict(trade("M1"), marketSlug="mlb-x"))
        finally:
            with tape._market_lock:
                tape._market_map.pop("mlb-x", None)
        self.assertFalse(self.journal_path.exists())


class RawFieldAllowlistTests(JournalTestCase):
    def test_trade_attributes_are_stored_but_not_reinterpreted(self):
        self.journal.record(trade(
            "T1", state="TRADE_STATE_EXAMPLE",
            taker={"intent": "ORDER_INTENT_UNDEFINED", "side": "ORDER_SIDE_BUY",
                   "action": "ACTION_EXAMPLE", "outcomeSide": "OUTCOME_EXAMPLE"},
            maker={"intent": "ORDER_INTENT_SELL_LONG", "side": "ORDER_SIDE_SELL",
                   "account": "acct-9"}), META)
        (row,) = self.rows()
        raw = json.loads(row["raw_fields_json"])
        self.assertEqual(raw["taker.side"], "ORDER_SIDE_BUY")
        self.assertEqual(raw["taker.action"], "ACTION_EXAMPLE")
        self.assertEqual(raw["taker.outcomeSide"], "OUTCOME_EXAMPLE")
        self.assertEqual(raw["maker.side"], "ORDER_SIDE_SELL")
        self.assertEqual(raw["state"], "TRADE_STATE_EXAMPLE")
        # An undefined intent stays UNKNOWN; the raw side is kept for later, not applied.
        self.assertEqual(row["taker_direction"], "UNKNOWN")
        self.assertNotIn("acct-9", json.dumps(row))

    def test_sessions_are_stamped_with_the_allowlist_version(self):
        self.journal.start_session("probe")
        (session,) = query(self.path, "SELECT note FROM capture_sessions")
        self.assertIn(f"raw field allowlist v{journal.RAW_FIELD_ALLOWLIST_VERSION}",
                      session["note"])


if __name__ == "__main__":
    unittest.main()
