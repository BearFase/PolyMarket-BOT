"""Tests for the per-league immutable trade journals. Instrumentation only."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import big_money_tape as tape
import trade_journal as journal

NFL_SLUG = "nfl-sf-lar-2026-09-10-moneyline"
NFL_META = {
    "market_slug": NFL_SLUG,
    "event_slug": "nfl-sf-lar-2026-09-10",
    "event_title": "San Francisco vs. Los Angeles R",
    "league": "nfl",
    "question": "Who will win San Francisco vs. Los Angeles R?",
    "market_type": "moneyline",
    "long_label": "49ers",
    "short_label": "Rams",
    "source_start_time": "2026-09-11T00:35:00Z",
}
MLB_SLUG = "mlb-tb-atl-2026-09-10-moneyline"
MLB_META = {
    "market_slug": MLB_SLUG,
    "event_slug": "mlb-tb-atl-2026-09-10",
    "event_title": "Tampa Bay vs. Atlanta",
    "league": "mlb",
    "question": "Who will win Tampa Bay vs. Atlanta?",
    "market_type": "moneyline",
    "long_label": "Rays",
    "short_label": "Braves",
    "source_start_time": "2026-09-10T16:15:00Z",
}

# Names of every object in the NFL journal as it went live. Generalising the
# module must keep them, or the live database would grow a second, empty table.
LIVE_NFL_OBJECTS = {
    "journal_meta", "capture_sessions", "nfl_trade_observations",
    "nfl_trades_market_time", "nfl_trades_event_time", "nfl_trades_derived_key",
    "nfl_trade_observations_no_update", "nfl_trade_observations_no_delete",
    "capture_sessions_no_update", "capture_sessions_no_delete",
    "journal_meta_coverage_no_update", "journal_meta_coverage_no_delete",
}


def trade(trade_id, slug=NFL_SLUG, intent="ORDER_INTENT_BUY_LONG", price="0.35",
          quantity="100", when="2026-09-10T20:00:00.123456789Z", **extra):
    payload = {"marketSlug": slug, "price": price, "quantity": quantity,
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


def object_names(path):
    return {row["name"] for row in query(
        path, "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}


class JournalTestCase(unittest.TestCase):
    def setUp(self):
        journal._reset_for_tests()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "nfl_trade_journal.db"
        self.journal = journal.TradeJournal("nfl", self.path)

    def tearDown(self):
        journal._reset_for_tests()
        self.temp.cleanup()

    def rows(self):
        return query(self.path, "SELECT * FROM nfl_trade_observations "
                                "ORDER BY trade_timestamp_utc, websocket_trade_id")


class SchemaTests(JournalTestCase):
    def test_nfl_journal_keeps_the_object_names_it_went_live_with(self):
        self.assertEqual(object_names(self.path), LIVE_NFL_OBJECTS)

    def test_mlb_full_flow_table_is_not_named_like_the_buy_only_journal(self):
        mlb_path = Path(self.temp.name) / "mlb_trade_journal.db"
        journal.TradeJournal("mlb", mlb_path)
        names = object_names(mlb_path)
        self.assertIn("mlb_full_flow_observations", names)
        self.assertNotIn("mlb_trade_observations", names)

    def test_an_unconfigured_league_is_refused(self):
        with self.assertRaises(ValueError):
            journal.TradeJournal("nba", Path(self.temp.name) / "nba.db")


class ObservationTests(JournalTestCase):
    def test_every_taker_intent_is_recorded_including_sells(self):
        intents = ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_BUY_SHORT",
                   "ORDER_INTENT_SELL_LONG", "ORDER_INTENT_SELL_SHORT")
        for index, intent in enumerate(intents):
            self.assertTrue(self.journal.record(trade(f"T{index}", intent=intent), NFL_META))
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
        self.journal.record(trade("T1", intent="ORDER_INTENT_SOMETHING_NEW"), NFL_META)
        (row,) = self.rows()
        self.assertEqual((row["taker_direction"], row["instrument_side"]), ("UNKNOWN", "UNKNOWN"))
        self.assertIsNone(row["outcome_price"])
        self.assertIn("UNRECOGNIZED_INTENT", json.loads(row["source_quality_flags_json"]))

    def test_invalid_price_is_kept_and_flagged(self):
        self.journal.record(trade("T1", price="1.0"), NFL_META)
        (row,) = self.rows()
        self.assertEqual(row["instrument_price"], 1.0)
        self.assertIsNone(row["outcome_price"])
        self.assertIsNone(row["notional_usd"])
        self.assertIn("PRICE_NOT_STRICTLY_BETWEEN_0_AND_1",
                      json.loads(row["source_quality_flags_json"]))

    def test_pregame_classification_uses_the_polymarket_event_start(self):
        self.journal.record(trade("pre", when="2026-09-11T00:34:59Z"), NFL_META)
        self.journal.record(trade("in", when="2026-09-11T00:35:01Z"), NFL_META)
        self.journal.record(trade("unknown"), dict(NFL_META, source_start_time=None))
        classes = {row["websocket_trade_id"]: row["pregame_classification"] for row in self.rows()}
        self.assertEqual(classes, {"pre": "PREGAME", "in": "IN_GAME", "unknown": "UNKNOWN"})

    def test_unknown_source_fields_are_recorded_by_name_only(self):
        self.journal.record(trade("T1", maker={"account": "acct-123"}, surprise="value-xyz"),
                            NFL_META)
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
        self.assertTrue(self.journal.record(trade("DUP"), NFL_META))
        self.assertFalse(self.journal.record(trade("DUP"), NFL_META))
        restarted = journal.TradeJournal("nfl", self.path)
        self.assertFalse(restarted.record(trade("DUP"), NFL_META))
        self.assertEqual(len(self.rows()), 1)

    def test_same_instant_fills_with_distinct_ids_are_both_kept(self):
        # Two equal fills in one burst: identical market, nanosecond, size, price
        # and intent. The MLB-style derived key cannot tell them apart; the
        # exchange id can.
        self.journal.record(trade("FILL-A"), NFL_META)
        self.journal.record(trade("FILL-B"), NFL_META)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["derived_trade_key"], rows[1]["derived_trade_key"])

    def test_missing_exchange_id_falls_back_to_the_derived_key(self):
        self.assertTrue(self.journal.record(trade(None), NFL_META))
        self.assertFalse(self.journal.record(trade(None), NFL_META))
        (row,) = self.rows()
        self.assertTrue(row["dedupe_key"].startswith("derived:"))
        self.assertIn("NO_EXCHANGE_TRADE_ID", json.loads(row["source_quality_flags_json"]))


class ImmutabilityTests(JournalTestCase):
    def test_observations_cannot_be_updated_or_deleted(self):
        self.journal.record(trade("T1"), NFL_META)
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
        self.assertEqual(journal.read_status("nfl", absent),
                         {"league": "nfl", "database": str(absent), "started": False})
        self.assertFalse(absent.exists())
        self.journal.start_session("status")
        self.journal.record(trade("A", intent="ORDER_INTENT_SELL_SHORT"), NFL_META)
        self.journal.record(trade("B"), NFL_META)
        self.journal.record(trade("C"), NFL_META)  # same instant, size and price as B
        status = journal.read_status("nfl", self.path)
        self.assertEqual(status["observations"], 3)
        self.assertEqual(status["distinct_exchange_trade_ids"], 3)
        self.assertEqual(status["by_taker_intent"]["ORDER_INTENT_SELL_SHORT"], 1)
        self.assertEqual(status["capture_sessions"], 1)
        self.assertIsNotNone(status["coverage_started_at"])
        self.assertEqual(status["derived_keys_shared_by_distinct_trades"], 1)
        self.assertEqual(status["rows_sharing_a_derived_key"], 2)


class RawFieldAllowlistTests(JournalTestCase):
    def test_trade_attributes_are_stored_but_not_reinterpreted(self):
        self.journal.record(trade(
            "T1", state="TRADE_STATE_EXAMPLE",
            taker={"intent": "ORDER_INTENT_UNDEFINED", "side": "ORDER_SIDE_BUY",
                   "action": "ACTION_EXAMPLE", "outcomeSide": "OUTCOME_EXAMPLE"},
            maker={"intent": "ORDER_INTENT_SELL_LONG", "side": "ORDER_SIDE_SELL",
                   "account": "acct-9"}), NFL_META)
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


class TapeHookTests(unittest.TestCase):
    def setUp(self):
        journal._reset_for_tests()
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.saved = (tape.DB_FILE, tape.MLB_RESEARCH_DB_FILE, tape.LOG_FILE,
                      tape.TRADE_JOURNAL_DIR)
        tape.DB_FILE = root / "tape.db"
        tape.MLB_RESEARCH_DB_FILE = root / "mlb-research.db"
        tape.LOG_FILE = root / "tape.log"
        tape.TRADE_JOURNAL_DIR = None
        tape.init_db()
        self.nfl_path = root / "nfl_trade_journal.db"
        self.mlb_path = root / "mlb_trade_journal.db"
        with tape._market_lock:
            tape._market_map[NFL_SLUG] = dict(NFL_META)
            tape._market_map[MLB_SLUG] = dict(MLB_META)
        patchers = [mock.patch.object(tape, "log"), mock.patch.object(tape, "mark_error")]
        self.log, self.mark_error = [patcher.start() for patcher in patchers]
        for patcher in patchers:
            self.addCleanup(patcher.stop)

    def tearDown(self):
        with tape._market_lock:
            tape._market_map.pop(NFL_SLUG, None)
            tape._market_map.pop(MLB_SLUG, None)
        (tape.DB_FILE, tape.MLB_RESEARCH_DB_FILE, tape.LOG_FILE,
         tape.TRADE_JOURNAL_DIR) = self.saved
        journal._reset_for_tests()
        self.temp.cleanup()

    def test_journals_live_beside_the_tape_database(self):
        self.assertEqual(tape._trade_journal_path("nfl"), self.nfl_path)
        self.assertEqual(tape._trade_journal_path("mlb"), self.mlb_path)

    def test_nfl_sells_reach_the_journal_and_the_display_is_unchanged(self):
        tape.record_trade(trade("BUY-1"))
        tape.record_trade(trade("SELL-1", intent="ORDER_INTENT_SELL_LONG",
                                when="2026-09-10T20:00:01Z"))
        intents = sorted(row["taker_intent"] for row in query(
            self.nfl_path, "SELECT taker_intent FROM nfl_trade_observations"))
        self.assertEqual(intents, ["ORDER_INTENT_BUY_LONG", "ORDER_INTENT_SELL_LONG"])
        self.assertEqual(len(query(tape.DB_FILE, "SELECT id FROM bets")), 1)

    def test_mlb_full_flow_captures_sells_the_buy_only_journal_never_sees(self):
        tape.record_trade(trade("MLB-BUY", slug=MLB_SLUG))
        tape.record_trade(trade("MLB-SELL", slug=MLB_SLUG, intent="ORDER_INTENT_SELL_LONG",
                                when="2026-09-10T20:00:01Z"))
        full = sorted(row["taker_intent"] for row in query(
            self.mlb_path, "SELECT taker_intent FROM mlb_full_flow_observations"))
        self.assertEqual(full, ["ORDER_INTENT_BUY_LONG", "ORDER_INTENT_SELL_LONG"])
        # The buy-only MLB journal still records exactly what it always did.
        legacy = query(tape.MLB_RESEARCH_DB_FILE,
                       "SELECT selected_side FROM mlb_trade_observations")
        self.assertEqual([row["selected_side"] for row in legacy], ["LONG"])
        self.assertEqual(len(query(tape.DB_FILE, "SELECT id FROM bets")), 1)

    def test_each_league_has_its_own_journal_and_coverage(self):
        tape.record_trade(trade("NFL-1"))
        tape.record_trade(trade("MLB-1", slug=MLB_SLUG))
        nfl_slugs = {row["market_slug"] for row in query(
            self.nfl_path, "SELECT market_slug FROM nfl_trade_observations")}
        mlb_slugs = {row["market_slug"] for row in query(
            self.mlb_path, "SELECT market_slug FROM mlb_full_flow_observations")}
        self.assertEqual((nfl_slugs, mlb_slugs), ({NFL_SLUG}, {MLB_SLUG}))
        mlb_meta = {row["key"]: row["value"] for row in query(
            self.mlb_path, "SELECT key, value FROM journal_meta")}
        self.assertEqual(mlb_meta["league"], "mlb")
        self.assertIsNotNone(mlb_meta["coverage_started_at"])
        self.assertIn("mlb_trade_observations", mlb_meta["coverage_note"])

    def test_derived_key_matches_the_tape_display_id(self):
        tape.record_trade(trade("BUY-1"))
        (bet,) = query(tape.DB_FILE, "SELECT id FROM bets")
        (row,) = query(self.nfl_path, "SELECT derived_trade_key FROM nfl_trade_observations")
        self.assertEqual(row["derived_trade_key"], bet["id"])

    def test_journal_failure_never_breaks_the_tape(self):
        self.mlb_path.mkdir()  # a directory where the database file should be
        self.assertTrue(tape.record_trade(trade("MLB-BUY", slug=MLB_SLUG)))
        self.assertEqual(len(query(tape.DB_FILE, "SELECT id FROM bets")), 1)
        self.assertEqual(len(query(tape.MLB_RESEARCH_DB_FILE,
                                   "SELECT observation_uuid FROM mlb_trade_observations")), 1)
        self.mark_error.assert_called()
        self.assertEqual(journal.stats("mlb")["failed"], 1)

    def test_unjournaled_leagues_are_ignored(self):
        other = dict(NFL_META, league="nba", market_slug="nba-x", event_slug="nba-x-event")
        with tape._market_lock:
            tape._market_map["nba-x"] = other
        try:
            tape.record_trade(trade("NBA-1", slug="nba-x"))
        finally:
            with tape._market_lock:
                tape._market_map.pop("nba-x", None)
        self.assertFalse((Path(self.temp.name) / "nba_trade_journal.db").exists())
        self.assertFalse(self.nfl_path.exists())
        self.assertFalse(self.mlb_path.exists())


if __name__ == "__main__":
    unittest.main()
