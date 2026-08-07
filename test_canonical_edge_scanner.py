import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import nfl_schedule as nfl
from sports_edge_finder import atomic_write_json, calculate_edges


FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CanonicalEdgeScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = nfl.NFLRegistry(Path(self.temp.name) / "production.db", environment="production")
        self.registry.ingest_schedule_payload(
            fixture("nfl_espn_preseason.json"), 2026, "PRE", "2")
        self.now = datetime(2026, 8, 14, 20, 2, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def link_odds(self):
        record = nfl.odds_api_records(
            fixture("nfl_odds_event.json"), 2026, "PRE", "2026-08-14T20:01:00Z")[0]
        return self.registry.link_source(record)

    def link_polymarket(self):
        record = nfl.polymarket_us_records(
            fixture("nfl_polymarket_us_event.json"), 2026, "PRE", "2026-08-14T20:01:00Z")[0]
        return self.registry.link_source(record)

    def test_no_edge_without_both_verified_links(self):
        self.link_odds()
        result = calculate_edges(self.registry, now=self.now)
        self.assertEqual(result["verified_game_pairs"], 0)
        self.assertEqual(result["edges"], [])

    def test_rejected_link_cannot_create_edge(self):
        self.link_odds()
        record = nfl.polymarket_us_records(
            fixture("nfl_polymarket_us_event.json"), 2026, "PRE", "2026-08-14T20:01:00Z")[0]
        record["home_team"], record["away_team"] = record["away_team"], record["home_team"]
        self.assertFalse(self.registry.link_source(record).accepted)
        self.assertEqual(calculate_edges(self.registry, now=self.now)["edges"], [])

    def test_edges_carry_identical_canonical_uuid_and_source_ids(self):
        odds = self.link_odds()
        polymarket = self.link_polymarket()
        self.assertEqual(odds.game_uuid, polymarket.game_uuid)
        result = calculate_edges(self.registry, now=self.now)
        self.assertEqual(result["verified_game_pairs"], 1)
        for edge in result["edges"]:
            self.assertEqual(edge["canonical_game_uuid"], odds.game_uuid)
            self.assertEqual(edge["odds_api_event_id"], "odds-pit-bal")
            self.assertEqual(edge["polymarket_us_market_id"], "market-pit-bal")
            self.assertGreaterEqual(edge["edge_percentage_points"], 3.0)

    def test_stale_sources_are_not_edges(self):
        self.link_odds()
        self.link_polymarket()
        late = datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc)
        result = calculate_edges(self.registry, now=late)
        self.assertEqual(result["edges"], [])
        self.assertEqual(result["skipped"]["stale"], 1)

    def test_one_game_produces_no_duplicate_edge_rows(self):
        self.link_odds(); self.link_odds()
        self.link_polymarket(); self.link_polymarket()
        result = calculate_edges(self.registry, now=self.now)
        keys = [(edge["canonical_game_uuid"], edge["team_id"]) for edge in result["edges"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_atomic_output_is_complete_json(self):
        path = Path(self.temp.name) / "sports_edges.json"
        payload = {"scanner": "canonical_nfl_registry", "edges": []}
        atomic_write_json(path, payload)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)
        self.assertEqual(list(path.parent.glob(".sports_edges.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
