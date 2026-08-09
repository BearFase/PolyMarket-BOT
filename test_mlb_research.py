import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import big_money_tape
import mlb_research
import trader_dashboard
from mlb_research import MLBResearchRegistry


def game(game_pk=1001, start="2026-08-08T20:10:00Z", *, number=1,
         doubleheader="N", state="Preview", detailed="Scheduled",
         away_score=None, home_score=None):
    return {
        "gamePk": game_pk, "gameDate": start, "officialDate": start[:10],
        "gameNumber": number, "doubleHeader": doubleheader,
        "status": {"abstractGameState": state, "detailedState": detailed},
        "teams": {
            "away": {"team": {"name": "Los Angeles Angels"}, "score": away_score},
            "home": {"team": {"name": "Miami Marlins"}, "score": home_score},
        },
    }


def payload(*games):
    return {"dates": [{"date": "2026-08-08", "games": list(games)}]}


def trade(key, amount=100, when="2026-08-08T19:00:00Z", selected="Los Angeles Angels",
          legacy=False, source_start="2026-08-08T20:10:00Z"):
    return {
        "source_trade_key": key, "event_slug": "mlb-laa-mia-2026-08-08",
        "market_slug": "laa-mia-moneyline", "league": "mlb", "market_type": "moneyline",
        "event_title": "Los Angeles Angels vs. Miami Marlins", "selected_team": selected,
        "raw_selection": selected, "selected_side": "LONG", "contracts": amount / .4,
        "execution_price": .4, "risk_usd": amount, "trade_timestamp_utc": when,
        "source_market_start_time": source_start, "legacy_incomplete": legacy,
        "source_quality_flags": ["LEGACY_INCOMPLETE"] if legacy else [],
    }


def odds_payload():
    return [{
        "id": "odds-1", "away_team": "Los Angeles Angels",
        "home_team": "Miami Marlins", "commence_time": "2026-08-08T20:10:00Z",
        "bookmakers": [
            {"key": "book-a", "last_update": "2026-08-08T18:00:00Z", "markets": [{
                "key": "h2h", "outcomes": [
                    {"name": "Los Angeles Angels", "price": 2.5},
                    {"name": "Miami Marlins", "price": 1.6},
                ]}]},
            {"key": "book-b", "last_update": "2026-08-08T18:01:00Z", "markets": [{
                "key": "h2h", "outcomes": [
                    {"name": "Los Angeles Angels", "price": 2.4},
                    {"name": "Miami Marlins", "price": 1.62},
                ]}]},
        ],
    }]


class MLBResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "research.db"
        self.registry = MLBResearchRegistry(self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_schedule_is_canonical_and_reschedule_creates_revision(self):
        result = self.registry.ingest_schedule(payload(game()))
        self.assertEqual(result["inserted"], 1)
        changed = game(start="2026-08-08T21:10:00Z", detailed="Rescheduled")
        self.registry.ingest_schedule(payload(changed))
        with self.registry.connect() as db:
            stored = db.execute("SELECT * FROM mlb_games").fetchone()
            revisions = db.execute("SELECT COUNT(*) FROM mlb_schedule_revisions").fetchone()[0]
        self.assertEqual(stored["schedule_version"], 2)
        self.assertEqual(stored["original_start_utc"], "2026-08-08T20:10:00+00:00")
        self.assertEqual(revisions, 2)

    def test_doubleheaders_match_by_canonical_time(self):
        first = game(1001, "2026-08-08T17:10:00Z", number=1, doubleheader="Y")
        second = game(1002, "2026-08-08T23:10:00Z", number=2, doubleheader="Y")
        self.registry.ingest_schedule(payload(first, second))
        matched, reason = self.registry.match_game(
            "Los Angeles Angels", "Miami Marlins", "2026-08-08T23:10:00Z")
        self.assertEqual(reason, "ACCEPTED")
        self.assertEqual(matched["mlb_game_pk"], 1002)
        self.assertTrue(matched["doubleheader_identifier"].endswith(":2"))

    def test_append_only_duplicate_prevention_and_classification(self):
        self.registry.ingest_schedule(payload(game()))
        for index in range(12):
            self.assertTrue(self.registry.record_trade(trade(f"trade-{index}", amount=10 + index)))
        self.assertFalse(self.registry.record_trade(trade("trade-0")))
        self.registry.record_trade(trade("in-game", when="2026-08-08T20:11:00Z"))
        self.registry.record_trade(trade("unknown", source_start=None))
        with self.registry.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM mlb_trade_observations").fetchone()[0]
            classes = dict(db.execute("SELECT source_trade_key,pregame_classification FROM mlb_trade_observations"))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM mlb_trade_observations")
        self.assertEqual(count, 14)
        self.assertEqual(classes["trade-0"], "PREGAME")
        self.assertEqual(classes["in-game"], "IN_GAME")
        self.assertEqual(classes["unknown"], "UNKNOWN")

    def test_sportsbook_snapshots_are_immutable_and_idempotent(self):
        self.registry.ingest_schedule(payload(game()))
        first = self.registry.ingest_sportsbook(odds_payload())
        second = self.registry.ingest_sportsbook(odds_payload())
        self.assertEqual(first["inserted"], 2)
        self.assertEqual(second["inserted"], 0)
        with self.registry.connect() as db:
            rows = db.execute("SELECT * FROM mlb_sportsbook_snapshots").fetchall()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE mlb_sportsbook_snapshots SET source_count=9")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["favorite_team_id"], "MIA")
        self.assertEqual(rows[0]["underdog_team_id"], "LAA")

    def test_summary_calculates_largest_buy_totals_concentration_and_result(self):
        final = game(state="Final", detailed="Final", away_score=5, home_score=3)
        self.registry.ingest_schedule(payload(final))
        self.registry.ingest_sportsbook(odds_payload())
        self.registry.record_trade(trade("favorite", amount=50, selected="Miami Marlins"))
        self.registry.record_trade(trade("underdog-small", amount=70))
        self.registry.record_trade(trade("underdog-largest", amount=130))
        summary = self.registry.summary()
        row = next(item for item in summary["games"] if item["mlb_game_pk"] == 1001)
        self.assertEqual(row["data_completeness"], "COMPLETE")
        self.assertEqual(row["largest_buy_amount"], 130)
        self.assertEqual(row["favorite_pregame_dollars"], 50)
        self.assertEqual(row["underdog_pregame_dollars"], 200)
        self.assertEqual(row["favorite_trade_count"], 1)
        self.assertEqual(row["underdog_trade_count"], 2)
        self.assertAlmostEqual(row["underdog_money_share"], .8)
        self.assertTrue(row["largest_buy_backed_underdog"])
        self.assertTrue(row["largest_buy_won"])
        self.assertEqual(summary["largest_pregame_buy"]["wins"], 1)
        self.assertIn("40-49c | 80-89%", summary["combination_table"])

    def test_legacy_incomplete_is_excluded(self):
        final = game(state="Final", detailed="Final", away_score=5, home_score=3)
        self.registry.ingest_schedule(payload(final))
        self.registry.ingest_sportsbook(odds_payload())
        self.registry.record_trade(trade("legacy", amount=1000, legacy=True))
        row = self.registry.research_games()[0]
        self.assertEqual(row["data_completeness"], "LEGACY_INCOMPLETE")
        self.assertIn("COMPLETE_PREGAME_TRADE_EVIDENCE", row["missing_evidence"])
        self.assertIsNone(row["largest_pregame_buy"])

    def test_restart_preserves_rows(self):
        self.registry.ingest_schedule(payload(game()))
        self.registry.record_trade(trade("restart"))
        restarted = MLBResearchRegistry(self.db_path)
        with restarted.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mlb_trade_observations").fetchone()[0], 1)

    def test_operational_top_five_does_not_prune_research_journal(self):
        tape_db = Path(self.temp.name) / "tape.db"
        self.registry.ingest_schedule(payload(game()))
        metadata = {
            "market_slug": "laa-mia-moneyline", "event_slug": "mlb-laa-mia-2026-08-08",
            "event_title": "Los Angeles Angels vs. Miami Marlins", "league": "mlb",
            "question": "Moneyline", "market_type": "moneyline",
            "long_label": "Los Angeles Angels", "short_label": "Miami Marlins",
            "source_start_time": "2026-08-08T20:10:00Z",
        }
        with patch.object(big_money_tape, "DB_FILE", tape_db), \
                patch.object(big_money_tape, "MLB_RESEARCH_DB_FILE", self.db_path), \
                patch.object(big_money_tape, "_market_map", {"laa-mia-moneyline": metadata}), \
                patch.object(big_money_tape, "log"):
            big_money_tape.init_db()
            for index in range(10):
                big_money_tape.record_trade({
                    "marketSlug": "laa-mia-moneyline", "price": .4,
                    "quantity": 100 + index, "tradeTime": f"2026-08-08T19:{index:02d}:00Z",
                    "taker": {"intent": "ORDER_INTENT_BUY_LONG"},
                })
        with closing(sqlite3.connect(tape_db)) as tape, self.registry.connect() as research:
            self.assertEqual(tape.execute("SELECT COUNT(*) FROM bets").fetchone()[0], 5)
            self.assertEqual(research.execute("SELECT COUNT(*) FROM mlb_trade_observations").fetchone()[0], 10)

    def test_ui_endpoint(self):
        self.registry.ingest_schedule(payload(game()))
        with patch.object(mlb_research, "DEFAULT_DB", self.db_path):
            client = trader_dashboard.app.test_client()
            page = client.get("/mlb-research")
            self.assertEqual(page.status_code, 200)
            page.close()
            response = client.get("/api/mlb-research?team=Angels&completeness=INCOMPLETE")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 1)

    def test_overview_separates_trustworthy_and_legacy_evidence(self):
        self.registry.ingest_schedule(payload(game()))
        self.registry.record_trade(trade("trusted"))
        self.registry.record_trade(trade("legacy", legacy=True))
        overview = self.registry.overview("2026-08-08")
        self.assertEqual(overview["trustworthy_observations"], 1)
        self.assertEqual(overview["legacy_incomplete_observations"], 1)
        self.assertEqual(overview["games_with_pregame_evidence"], 1)

    def test_today_filter_and_pagination_do_not_return_raw_journal(self):
        self.registry.ingest_schedule(payload(game(), game(1002, "2026-08-09T20:10:00Z")))
        result = self.registry.research_page({"date": "2026-08-08"}, page=1, per_page=1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["games"][0]["official_date"], "2026-08-08")
        self.assertNotIn("trades", result["games"][0])

    def test_dynamic_filtered_statistics_and_continuous_filters(self):
        final = game(state="Final", detailed="Final", away_score=5, home_score=3)
        self.registry.ingest_schedule(payload(final))
        self.registry.ingest_sportsbook(odds_payload())
        self.registry.record_trade(trade("large", amount=130))
        excluded = self.registry.research_page({"price_min": .41})
        included = self.registry.research_page({"price_min": .39, "concentration_min": .9})
        self.assertEqual(excluded["total"], 0)
        self.assertEqual(included["statistics"]["complete_cases"], 1)
        self.assertEqual(included["statistics"]["largest_buy_record"]["wins"], 1)

    def test_game_drilldown_and_lazy_timeline(self):
        self.registry.ingest_schedule(payload(game()))
        self.registry.record_trade(trade("one", amount=30, when="2026-08-08T18:00:00Z"))
        self.registry.record_trade(trade("two", amount=40, when="2026-08-08T18:05:00Z"))
        game_uuid = self.registry.research_games()[0]["game_uuid"]
        detail = self.registry.game_detail(game_uuid)
        summarized = self.registry.timeline(game_uuid, summarized=True, bucket_minutes=15)
        raw = self.registry.timeline(game_uuid, summarized=False, per_page=1)
        self.assertEqual(detail["trustworthy_pregame_trade_count"], 2)
        self.assertEqual(len(summarized["rows"]), 1)
        self.assertEqual(summarized["rows"][0]["trade_count"], 2)
        self.assertEqual(raw["total"], 2)
        self.assertEqual(len(raw["rows"]), 1)
        self.assertLess(raw["rows"][0]["trade_timestamp_utc"], "2026-08-08T18:05:00Z")

    def test_research_routes_include_overview_detail_and_timeline(self):
        self.registry.ingest_schedule(payload(game()))
        self.registry.record_trade(trade("route"))
        game_uuid = self.registry.research_games()[0]["game_uuid"]
        with patch.object(mlb_research, "DEFAULT_DB", self.db_path):
            client = trader_dashboard.app.test_client()
            self.assertEqual(client.get("/api/mlb-research/overview").status_code, 200)
            self.assertEqual(client.get(f"/api/mlb-research/games/{game_uuid}").status_code, 200)
            timeline = client.get(f"/api/mlb-research/games/{game_uuid}/timeline?mode=detail&per_page=1")
        self.assertEqual(timeline.status_code, 200)
        self.assertEqual(timeline.get_json()["total"], 1)


if __name__ == "__main__":
    unittest.main()
