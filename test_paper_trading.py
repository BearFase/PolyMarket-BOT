import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_trader import (
    DuplicatePositionError,
    PaperLedgerError,
    PaperTrader,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return FakeResponse(self.payload)


class PaperLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "paper_config.json"
        self.config.write_text(json.dumps({
            "max_position_size": 100,
            "max_total_exposure": 500,
            "min_whale_overlap": 2,
            "min_edge": 0.1,
            "auto_trade": False,
        }))
        self.state = self.root / "paper_positions.json"
        self.legacy = self.root / "paper_state.json"
        self.trader = PaperTrader(self.config, self.state, self.legacy)

    def tearDown(self):
        self.temp.cleanup()

    def opportunity(self, suffix="1", price=0.4):
        return {
            "condition_id": f"condition-{suffix}",
            "market_slug": f"market-{suffix}",
            "event_slug": f"event-{suffix}",
            "outcome_id": f"token-{suffix}",
            "outcome_name": "Yes",
            "question": f"Test market {suffix}",
            "entry_price": price,
            "signal_source": "whale_consensus",
        }

    def test_cash_and_equity_reconcile_after_entry_and_mark(self):
        position = self.trader.open_position(self.opportunity(price=0.4))
        self.assertEqual(position["cost_basis"], 100)
        self.assertEqual(self.trader.state["current_cash"], 900)
        self.assertEqual(self.trader.state["open_exposure"], 100)
        self.trader.update_positions([{
            "condition_id": "condition-1",
            "outcome_id": "token-1",
            "current_price": 0.5,
        }])
        state = self.trader.state
        self.assertEqual(state["open_positions"][0]["current_value"], 125)
        self.assertEqual(state["unrealized_pnl"], 25)
        self.assertEqual(state["total_equity"], 1025)
        self.assertEqual(
            state["current_cash"] + state["open_positions"][0]["current_value"],
            state["total_equity"],
        )

    def test_duplicate_prevention_and_uuid_uniqueness(self):
        first = self.trader.open_position(self.opportunity("1"))
        with self.assertRaises(DuplicatePositionError):
            self.trader.open_position(self.opportunity("1"))
        second = self.trader.open_position(self.opportunity("2"))
        self.assertNotEqual(first["uuid"], second["uuid"])
        self.assertEqual(len(first["uuid"]), 36)

    def test_maximum_simultaneous_exposure_is_enforced(self):
        for index in range(5):
            self.trader.open_position(self.opportunity(str(index)))
        self.assertEqual(self.trader.state["open_exposure"], 500)
        self.assertEqual(self.trader.state["current_cash"], 500)
        with self.assertRaises(PaperLedgerError):
            self.trader.open_position(self.opportunity("sixth"))

    def test_atomic_write_uses_os_replace(self):
        with patch("paper_trader.os.replace", wraps=os.replace) as replace:
            self.trader.open_position(self.opportunity())
        self.assertTrue(replace.called)
        source, destination = replace.call_args.args
        self.assertEqual(Path(destination), self.state)
        self.assertNotEqual(Path(source), self.state)
        json.loads(self.state.read_text())

    def test_restart_recovers_canonical_state(self):
        opened = self.trader.open_position(self.opportunity())
        restarted = PaperTrader(self.config, self.state, self.legacy)
        self.assertEqual(restarted.state["open_positions"][0]["uuid"], opened["uuid"])
        self.assertEqual(restarted.state["current_cash"], 900)

    def test_migration_backs_up_deduplicates_and_excludes_real(self):
        legacy_positions = {
            "positions": [],
            "closed": [{
                "id": "paper_001",
                "market": "Legitimate paper",
                "outcome": "YES",
                "entry_price": 0.4,
                "size": 100,
                "pnl": 25,
            }],
            "total_pnl": 25,
        }
        self.state.unlink()
        self.state.write_text(json.dumps(legacy_positions))
        self.legacy.write_text(json.dumps({
            "positions": [],
            "history": [
                legacy_positions["closed"][0],
                {
                    "id": "real_001",
                    "market": "Contaminated real trade",
                    "outcome": "YES",
                    "entry_price": 0.5,
                    "size": 100,
                    "realized_pnl": 40,
                },
            ],
        }))
        migrated = PaperTrader(self.config, self.state, self.legacy).state
        self.assertEqual(len(migrated["closed_positions"]), 1)
        self.assertEqual(migrated["closed_positions"][0]["legacy_id"], "paper_001")
        self.assertEqual(migrated["realized_pnl"], 25)
        self.assertEqual(migrated["current_cash"], 1025)
        migration = migrated["metadata"]["migration"]
        self.assertIn("real_001", migration["excluded_records"])
        self.assertEqual(len(migration["backups"]), 2)
        self.assertTrue(all(Path(path).exists() for path in migration["backups"]))

    def test_win_settlement_and_idempotency(self):
        opened = self.trader.open_position(self.opportunity(price=0.4))
        closed = self.trader.settle_position(opened["uuid"], "win")
        self.assertEqual(closed["payout"], 250)
        self.assertEqual(closed["realized_pnl"], 150)
        self.assertEqual(self.trader.state["current_cash"], 1150)
        self.assertEqual(self.trader.state["total_equity"], 1150)
        repeated = self.trader.settle_position(opened["uuid"], "win")
        self.assertTrue(repeated["already_settled"])
        self.assertEqual(self.trader.state["current_cash"], 1150)
        self.assertEqual(len(self.trader.state["closed_positions"]), 1)

    def test_loss_settlement(self):
        opened = self.trader.open_position(self.opportunity(price=0.4))
        closed = self.trader.settle_position(opened["uuid"], "loss")
        self.assertEqual(closed["payout"], 0)
        self.assertEqual(closed["realized_pnl"], -100)
        self.assertEqual(self.trader.state["current_cash"], 900)
        self.assertEqual(self.trader.state["total_equity"], 900)

    def test_void_refunds_cost_basis(self):
        opened = self.trader.open_position(self.opportunity(price=0.4))
        closed = self.trader.settle_position(opened["uuid"], "void")
        self.assertEqual(closed["payout"], 100)
        self.assertEqual(closed["realized_pnl"], 0)
        self.assertEqual(self.trader.state["current_cash"], 1000)
        self.assertEqual(self.trader.state["total_equity"], 1000)

    def test_realized_pnl_reconciles_multiple_settlements(self):
        win = self.trader.open_position(self.opportunity("win", 0.5))
        loss = self.trader.open_position(self.opportunity("loss", 0.5))
        self.trader.settle_position(win["uuid"], "win")
        self.trader.settle_position(loss["uuid"], "loss")
        state = self.trader.state
        self.assertEqual(state["realized_pnl"], 0)
        self.assertEqual(state["current_cash"], 1000)
        self.assertEqual(state["total_equity"], 1000)

    def test_authoritative_closed_market_result_settles(self):
        opened = self.trader.open_position(self.opportunity(price=0.5))
        session = FakeSession([{
            "conditionId": "condition-1",
            "closed": True,
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["1", "0"]',
            "clobTokenIds": '["token-1", "other-token"]',
        }])
        settled = self.trader.settle_resolved_positions(session)
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0]["uuid"], opened["uuid"])
        self.assertEqual(settled[0]["settlement_result"], "win")

    def test_open_market_is_not_settled_from_price(self):
        self.trader.open_position(self.opportunity(price=0.5))
        session = FakeSession([{
            "conditionId": "condition-1",
            "closed": False,
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.99", "0.01"]',
            "clobTokenIds": '["token-1", "other-token"]',
        }])
        self.assertEqual(self.trader.settle_resolved_positions(session), [])
        self.assertEqual(len(self.trader.state["open_positions"]), 1)


if __name__ == "__main__":
    unittest.main()
