#!/usr/bin/env python3
"""Canonical cash-based paper accounting and settlement engine."""

from __future__ import annotations

import json
import copy
import os
import random
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests

SCHEMA_VERSION = 1
STARTING_BANKROLL = 1000.0
FIXED_POSITION_SIZE = 100.0
MAX_EXPOSURE = 500.0
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value, default=0.0) -> float:
    try:
        return round(float(value), 10)
    except (TypeError, ValueError):
        return default


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


class PaperLedgerError(RuntimeError):
    """Paper-ledger validation or persistence failure."""


class DuplicatePositionError(PaperLedgerError):
    """The same market/outcome is already open."""


class PaperTrader:
    def __init__(
        self,
        config_path="paper_config.json",
        state_path="paper_positions.json",
        legacy_state_path="paper_state.json",
    ):
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.legacy_state_path = Path(legacy_state_path)
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        self.config = self._load_config()
        self.state = self._initialize_or_migrate()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        else:
            config = {
                "max_position_size": FIXED_POSITION_SIZE,
                "max_total_exposure": MAX_EXPOSURE,
                "auto_trade": False,
                "notify_on_trade": True,
            }
        # Accounting constraints are intentionally fixed for this foundation.
        config["max_position_size"] = FIXED_POSITION_SIZE
        config["max_total_exposure"] = MAX_EXPOSURE
        return config

    @contextmanager
    def _locked(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while True:
            try:
                descriptor = os.open(
                    self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                os.write(descriptor, f"{os.getpid()} {_now()}".encode())
                os.close(descriptor)
                break
            except FileExistsError:
                try:
                    if time.time() - self.lock_path.stat().st_mtime > 60:
                        self.lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise PaperLedgerError("Timed out waiting for paper-ledger lock")
                time.sleep(0.025 + random.random() * 0.025)
        try:
            yield
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _atomic_write(self, data: dict):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.",
            suffix=".tmp",
            dir=str(self.state_path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def _empty_ledger(self) -> dict:
        now = _now()
        return {
            "version": SCHEMA_VERSION,
            "starting_bankroll": STARTING_BANKROLL,
            "current_cash": STARTING_BANKROLL,
            "reserved_capital": 0.0,
            "total_equity": STARTING_BANKROLL,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "open_exposure": 0.0,
            "open_positions": [],
            "closed_positions": [],
            "metadata": {"created_at": now, "updated_at": now},
        }

    def _read(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _initialize_or_migrate(self) -> dict:
        with self._locked():
            existing = None
            if self.state_path.exists():
                existing = self._read()
                if existing.get("version") == SCHEMA_VERSION:
                    original = copy.deepcopy(existing)
                    self._recalculate(existing, touch=False)
                    self._validate(existing)
                    if existing != original:
                        self._atomic_write(existing)
                    return existing

            ledger = self._migrate(existing)
            self._recalculate(ledger)
            self._validate(ledger)
            self._atomic_write(ledger)
            return ledger

    def _backup(self, path: Path, stamp: str) -> Optional[str]:
        if not path.exists():
            return None
        backup = path.with_name(f"{path.name}.bak.{stamp}")
        shutil.copy2(path, backup)
        return str(backup)

    def _migrate(self, canonical_legacy: Optional[dict]) -> dict:
        ledger = self._empty_ledger()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backups = []
        for path in (self.state_path, self.legacy_state_path):
            backup = self._backup(path, stamp)
            if backup:
                backups.append(backup)

        sources = []
        if canonical_legacy is not None:
            sources.append(("paper_positions.json", canonical_legacy))
        if self.legacy_state_path.exists():
            sources.append(
                (
                    "paper_state.json",
                    json.loads(self.legacy_state_path.read_text(encoding="utf-8")),
                )
            )

        seen = set()
        excluded = []
        for source_name, source in sources:
            open_items = source.get("positions", source.get("open_positions", []))
            closed_items = source.get("closed", source.get("history", source.get("closed_positions", [])))
            for is_closed, items in ((False, open_items), (True, closed_items)):
                for old in items:
                    old_id = str(old.get("id") or old.get("uuid") or "")
                    if old_id == "real_001" or (old_id and not old_id.startswith("paper")):
                        excluded.append(old_id or "unlabelled non-paper record")
                        continue
                    fingerprint = old_id or (
                        old.get("market"),
                        old.get("outcome"),
                        old.get("entry_time") or old.get("opened_at"),
                    )
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    migrated = self._migrate_position(old, source_name, is_closed)
                    destination = "closed_positions" if is_closed else "open_positions"
                    ledger[destination].append(migrated)

        ledger["metadata"]["migration"] = {
            "performed_at": _now(),
            "backups": backups,
            "sources": [name for name, _ in sources],
            "excluded_records": excluded,
        }
        return ledger

    def _migrate_position(self, old: dict, source: str, is_closed: bool) -> dict:
        entry = _number(old.get("entry_price") or old.get("price"))
        cost = _number(old.get("cost_basis") or old.get("size"))
        shares = _number(old.get("shares"), cost / entry if entry > 0 else 0)
        current = _number(old.get("current_price"), entry)
        realized = _number(old.get("realized_pnl", old.get("pnl", 0)))
        payout = _number(old.get("payout"), cost + realized) if is_closed else None
        legacy_id = str(old.get("id") or "")
        stable_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}:{legacy_id}:{old!r}"))
        market = str(old.get("market") or old.get("question") or "Legacy paper market")
        outcome = str(old.get("outcome") or old.get("outcome_name") or "Unknown")
        condition_id = str(old.get("condition_id") or old.get("conditionId") or f"legacy:{stable_uuid}")
        outcome_id = str(old.get("outcome_id") or old.get("asset") or f"legacy:{stable_uuid}:{outcome}")
        position = {
            "uuid": stable_uuid,
            "condition_id": condition_id,
            "market_slug": str(old.get("market_slug") or old.get("slug") or f"legacy-{stable_uuid}"),
            "event_slug": str(old.get("event_slug") or old.get("eventSlug") or f"legacy-{stable_uuid}"),
            "outcome_id": outcome_id,
            "outcome_name": outcome,
            "question": market,
            "entry_time": str(old.get("entry_time") or old.get("opened_at") or _now()),
            "entry_price": entry,
            "shares": shares,
            "cost_basis": cost,
            "current_price": 0.0 if is_closed else current,
            "current_value": 0.0 if is_closed else _number(shares * current),
            "status": "closed" if is_closed else "open",
            "signal_source": str(old.get("signal_source") or "legacy_paper"),
            "settlement_status": str(
                old.get("settlement_status") or ("legacy_closed" if is_closed else "pending")
            ),
            "legacy_id": legacy_id or None,
        }
        if is_closed:
            position.update(
                {
                    "payout": payout,
                    "realized_pnl": realized,
                    "settled_at": str(old.get("closed_at") or old.get("exit_time") or _now()),
                    "settlement_result": str(old.get("result") or old.get("reason") or "legacy"),
                }
            )
        return position

    def _recalculate(self, ledger: dict, *, touch=True):
        open_positions = ledger["open_positions"]
        closed_positions = ledger["closed_positions"]
        exposure = sum(_number(p["cost_basis"]) for p in open_positions)
        market_value = sum(_number(p["current_value"]) for p in open_positions)
        realized = sum(_number(p.get("realized_pnl")) for p in closed_positions)
        unrealized = sum(
            _number(p["current_value"]) - _number(p["cost_basis"])
            for p in open_positions
        )
        ledger["starting_bankroll"] = STARTING_BANKROLL
        ledger["current_cash"] = _number(STARTING_BANKROLL + realized - exposure)
        ledger["reserved_capital"] = _number(exposure)
        ledger["open_exposure"] = _number(exposure)
        ledger["realized_pnl"] = _number(realized)
        ledger["unrealized_pnl"] = _number(unrealized)
        ledger["total_equity"] = _number(ledger["current_cash"] + market_value)
        ledger["version"] = SCHEMA_VERSION
        if touch:
            ledger.setdefault("metadata", {})["updated_at"] = _now()

    def _validate(self, ledger: dict):
        cash = _number(ledger["current_cash"])
        market_value = sum(_number(p["current_value"]) for p in ledger["open_positions"])
        if abs(cash + market_value - _number(ledger["total_equity"])) > 1e-7:
            raise PaperLedgerError("Equity does not reconcile")
        if ledger["open_exposure"] > MAX_EXPOSURE + 1e-7:
            raise PaperLedgerError("Paper exposure exceeds $500")
        if cash < -1e-7:
            raise PaperLedgerError("Paper cash cannot be negative")
        keys = [(p["condition_id"], p["outcome_id"]) for p in ledger["open_positions"]]
        if len(keys) != len(set(keys)):
            raise PaperLedgerError("Duplicate open market/outcome positions")

    def _mutate(self, callback):
        with self._locked():
            ledger = self._read()
            result = callback(ledger)
            self._recalculate(ledger)
            self._validate(ledger)
            self._atomic_write(ledger)
            self.state = ledger
            return result

    def refresh(self):
        with self._locked():
            self.state = self._read()
        return self.state

    def open_position(self, opportunity: dict) -> dict:
        required = ("condition_id", "market_slug", "event_slug", "outcome_id")
        missing = [key for key in required if not opportunity.get(key)]
        if missing:
            raise PaperLedgerError(
                "Cannot open auditable paper position; missing " + ", ".join(missing)
            )
        entry = _number(opportunity["entry_price"])
        if not 0 < entry <= 1:
            raise PaperLedgerError("Entry price must be greater than 0 and at most 1")

        def add(ledger):
            key = (str(opportunity["condition_id"]), str(opportunity["outcome_id"]))
            if any((p["condition_id"], p["outcome_id"]) == key for p in ledger["open_positions"]):
                raise DuplicatePositionError("This market/outcome already has an open paper trade")
            if ledger["current_cash"] < FIXED_POSITION_SIZE:
                raise PaperLedgerError("Insufficient paper cash")
            if ledger["open_exposure"] + FIXED_POSITION_SIZE > MAX_EXPOSURE:
                raise PaperLedgerError("Maximum simultaneous exposure is $500")
            position = {
                "uuid": str(uuid.uuid4()),
                "condition_id": key[0],
                "market_slug": str(opportunity["market_slug"]),
                "event_slug": str(opportunity["event_slug"]),
                "outcome_id": key[1],
                "outcome_name": str(opportunity.get("outcome_name") or opportunity.get("outcome") or "Unknown"),
                "question": str(opportunity.get("question") or opportunity.get("market") or "Unknown market"),
                "entry_time": _now(),
                "entry_price": entry,
                "shares": _number(FIXED_POSITION_SIZE / entry),
                "cost_basis": FIXED_POSITION_SIZE,
                "current_price": entry,
                "current_value": FIXED_POSITION_SIZE,
                "status": "open",
                "signal_source": str(opportunity.get("signal_source") or "manual"),
                "settlement_status": "pending",
            }
            for optional in ("whale_avg", "edge", "overlap", "url"):
                if optional in opportunity:
                    position[optional] = opportunity[optional]
            ledger["open_positions"].append(position)
            return position

        return self._mutate(add)

    def update_positions(self, current_markets: List[dict]):
        by_id = {
            (str(m.get("condition_id")), str(m.get("outcome_id"))): m.get("current_price")
            for m in current_markets
            if m.get("condition_id") and m.get("outcome_id")
        }

        def update(ledger):
            for position in ledger["open_positions"]:
                price = by_id.get((position["condition_id"], position["outcome_id"]))
                if price is not None and 0 <= _number(price) <= 1:
                    position["current_price"] = _number(price)
                    position["current_value"] = _number(position["shares"] * _number(price))
            ledger["metadata"]["last_price_update"] = _now()

        self._mutate(update)

    def settle_position(self, position_uuid: str, result: str) -> dict:
        normalized = result.strip().lower()
        if normalized in {"cancel", "cancelled", "canceled", "tie"}:
            normalized = "void"
        if normalized not in {"win", "loss", "void"}:
            raise PaperLedgerError("Settlement result must be win, loss, or void")

        def settle(ledger):
            for closed in ledger["closed_positions"]:
                if closed["uuid"] == position_uuid:
                    return {**closed, "already_settled": True}
            position = next(
                (p for p in ledger["open_positions"] if p["uuid"] == position_uuid),
                None,
            )
            if position is None:
                raise PaperLedgerError(f"Unknown paper position UUID: {position_uuid}")
            if normalized == "win":
                payout = _number(position["shares"])
                final_price = 1.0
            elif normalized == "loss":
                payout = 0.0
                final_price = 0.0
            else:
                payout = _number(position["cost_basis"])
                final_price = _number(position["entry_price"])
            position.update(
                {
                    "status": "closed",
                    "settlement_status": f"settled_{normalized}",
                    "settlement_result": normalized,
                    "settled_at": _now(),
                    "current_price": final_price,
                    "current_value": 0.0,
                    "payout": payout,
                    "realized_pnl": _number(payout - position["cost_basis"]),
                }
            )
            ledger["open_positions"].remove(position)
            ledger["closed_positions"].append(position)
            return position

        return self._mutate(settle)

    def _authoritative_result(self, position: dict, session=requests) -> Optional[str]:
        response = session.get(
            GAMMA_MARKETS_URL,
            params={"condition_ids": position["condition_id"]},
            timeout=15,
        )
        response.raise_for_status()
        markets = response.json()
        market = next(
            (m for m in markets if str(m.get("conditionId")) == position["condition_id"]),
            None,
        )
        if not market or not market.get("closed"):
            return None
        outcomes = [str(value) for value in _json_list(market.get("outcomes"))]
        prices = [_number(value) for value in _json_list(market.get("outcomePrices"))]
        tokens = [str(value) for value in _json_list(market.get("clobTokenIds"))]
        if len(prices) < 2 or abs(sum(prices) - 1.0) > 1e-6:
            return None
        if all(abs(price - 0.5) < 1e-6 for price in prices):
            return "void"
        selected_index = None
        if position["outcome_id"] in tokens:
            selected_index = tokens.index(position["outcome_id"])
        elif position["outcome_name"] in outcomes:
            selected_index = outcomes.index(position["outcome_name"])
        if selected_index is None or selected_index >= len(prices):
            return None
        if abs(prices[selected_index] - 1.0) < 1e-6:
            return "win"
        if abs(prices[selected_index]) < 1e-6 and any(abs(p - 1.0) < 1e-6 for p in prices):
            return "loss"
        return None

    def settle_resolved_positions(self, session=requests) -> List[dict]:
        self.refresh()
        settled = []
        for position in list(self.state["open_positions"]):
            if position["condition_id"].startswith("legacy:"):
                continue
            result = self._authoritative_result(position, session=session)
            if result:
                settled.append(self.settle_position(position["uuid"], result))
        return settled

    def record_last_check(self):
        def record(ledger):
            ledger["metadata"]["last_consensus_check"] = _now()
        self._mutate(record)

    def get_summary(self) -> dict:
        self.refresh()
        closed = self.state["closed_positions"]
        wins = sum(1 for item in closed if item.get("realized_pnl", 0) > 0)
        return {
            "starting_bankroll": self.state["starting_bankroll"],
            "cash": self.state["current_cash"],
            "open_positions": len(self.state["open_positions"]),
            "closed_trades": len(closed),
            "current_exposure": self.state["open_exposure"],
            "open_market_value": sum(p["current_value"] for p in self.state["open_positions"]),
            "realized_pnl": self.state["realized_pnl"],
            "unrealized_pnl": self.state["unrealized_pnl"],
            "total_equity": self.state["total_equity"],
            "win_rate": wins / len(closed) if closed else 0.0,
            # Compatibility names for existing console output.
            "total_pnl": self.state["realized_pnl"],
            "open_pnl": self.state["unrealized_pnl"],
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Canonical paper ledger")
    parser.add_argument("command", choices=["status", "config", "history", "settle"])
    args = parser.parse_args()
    trader = PaperTrader()
    if args.command == "config":
        print(json.dumps(trader.config, indent=2))
    elif args.command == "settle":
        settled = trader.settle_resolved_positions()
        print(f"Authoritatively settled {len(settled)} paper position(s).")
    elif args.command == "history":
        print(json.dumps(trader.state["closed_positions"][-10:], indent=2))
    else:
        summary = trader.get_summary()
        print("=== Paper Trading Summary ===")
        print(f"Cash: ${summary['cash']:.2f}")
        print(f"Open exposure: ${summary['current_exposure']:.2f}")
        print(f"Open market value: ${summary['open_market_value']:.2f}")
        print(f"Realized P&L: ${summary['realized_pnl']:.2f}")
        print(f"Unrealized P&L: ${summary['unrealized_pnl']:.2f}")
        print(f"Total equity: ${summary['total_equity']:.2f}")


if __name__ == "__main__":
    main()
