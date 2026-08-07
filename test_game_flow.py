import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import big_money_tape


HERE = Path(__file__).parent


def group(rows, minimum=5):
    script = """
const fs = require('fs');
const flow = require('./game_flow.js');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(flow.groupGameFlow(input.rows, input.minimum)));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=HERE,
        input=json.dumps({"rows": rows, "minimum": minimum}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def trade(event, team, risk, when, price=0.58, title="Yankees vs. Red Sox",
          start="2026-07-28T23:00:00Z", identifier=None):
    return {
        "id": identifier or f"{event}-{team}-{risk}-{when}",
        "event_slug": event,
        "event_title": title,
        "league": "mlb",
        "selection": f"{team} moneyline — {title}",
        "raw_selection": team,
        "entry_price": price,
        "risk_usd": risk,
        "trade_time": when,
        "game_start_time": start,
        "status": "OPEN",
    }


class GameFlowGroupingTests(unittest.TestCase):
    def test_empty_state_data(self):
        rows = [
            trade("tiny", "Yankees", 4, "2026-07-28T20:00:00Z"),
            {**trade("nba", "Yankees", 100, "2026-07-28T20:00:00Z"),
             "league": "nba"},
        ]
        self.assertEqual(group(rows), [])

    def test_single_game_groups_without_duplicate_card(self):
        rows = [
            trade("game-1", "Yankees", 100, "2026-07-28T20:00:01Z"),
            trade("game-1", "Red Sox", 80, "2026-07-28T20:00:02Z",
                  price=0.42),
            trade("game-1", "Yankees", 60, "2026-07-28T20:00:03Z"),
        ]
        games = group(rows)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["away"], "Yankees")
        self.assertEqual(games[0]["home"], "Red Sox")

    def test_sides_are_separate_and_largest_buys_first(self):
        rows = [
            trade("game-1", "Yankees", 20, "2026-07-28T20:00:01Z"),
            trade("game-1", "Red Sox", 70, "2026-07-28T20:00:02Z"),
            trade("game-1", "Yankees", 90, "2026-07-28T20:00:03Z"),
        ]
        game = group(rows)[0]
        self.assertEqual(
            [buy["risk_usd"] for buy in game["buys"]["Yankees"]], [90, 20])
        self.assertEqual(
            [buy["risk_usd"] for buy in game["buys"]["Red Sox"]], [70])


class FeedAvailabilityTests(unittest.TestCase):
    def test_market_discovery_network_wait_does_not_block_snapshot(self):
        first_request_complete = threading.Event()
        release_later_request = threading.Event()
        event = {
            "slug": "test-game",
            "title": "Away vs. Home",
            "markets": [{
                "slug": "test-market",
                "marketType": "moneyline",
                "question": "Will Away win?",
                "marketSides": [],
            }],
        }
        calls = 0

        def request_events(_params):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_request_complete.set()
                return [event]
            release_later_request.wait(timeout=2)
            return []

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "tape.db"
            with patch.object(big_money_tape, "DB_FILE", database), \
                    patch.object(big_money_tape, "LEAGUES", ("mlb", "nfl")), \
                    patch.object(big_money_tape, "_request_events", request_events), \
                    patch.object(big_money_tape, "mark_success"), \
                    patch.object(big_money_tape, "log"):
                big_money_tape.init_db()
                worker = threading.Thread(target=big_money_tape.discover_markets)
                worker.start()
                self.assertTrue(first_request_complete.wait(timeout=1))
                started = time.monotonic()
                big_money_tape.snapshot()
                elapsed = time.monotonic() - started
                release_later_request.set()
                worker.join(timeout=2)

        self.assertLess(elapsed, 0.5)
        self.assertFalse(worker.is_alive())

    def test_multiple_games_sort_by_recent_activity(self):
        rows = [
            trade("older", "Cubs", 100, "2026-07-28T20:00:00Z",
                  title="Cubs vs. Cardinals"),
            trade("newer", "Dodgers", 100, "2026-07-28T21:00:00Z",
                  title="Dodgers vs. Giants"),
        ]
        self.assertEqual(
            [game["event_slug"] for game in group(rows)], ["newer", "older"])

    def test_equal_activity_sorts_by_game_start(self):
        same_time = "2026-07-28T20:00:00Z"
        rows = [
            trade("late", "Cubs", 100, same_time,
                  title="Cubs vs. Cardinals", start="2026-07-29T02:00:00Z"),
            trade("early", "Dodgers", 100, same_time,
                  title="Dodgers vs. Giants", start="2026-07-29T01:00:00Z"),
        ]
        self.assertEqual(
            [game["event_slug"] for game in group(rows)], ["early", "late"])


class GameFlowRouteTests(unittest.TestCase):
    def test_workspace_and_script_routes(self):
        from trader_dashboard import app
        client = app.test_client()
        page = client.get("/game-flow")
        self.assertEqual(page.status_code, 200)
        self.assertIn("GAME FLOW", page.get_data(as_text=True))
        self.assertNotIn("BIG MONEY TAPE", page.get_data(as_text=True))
        page.close()
        script = client.get("/game_flow.js")
        self.assertEqual(script.status_code, 200)
        script.close()
        self.assertEqual(client.get("/big-money").status_code, 404)


if __name__ == "__main__":
    unittest.main()
