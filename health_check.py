#!/usr/bin/env python3
"""Read-only operational health report for the NFL Research Platform."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from nfl_operations import (
    LOCK_FILE, WORKFLOW_LOG, WORKFLOW_STATE, check_sqlite, read_workflow_state,
    startup_checks,
)
from nfl_schedule import NFLRegistry, PRODUCTION_DB

HERE = Path(__file__).resolve().parent


def _item(name, state, detail="", critical=False):
    return {"name": name, "state": state, "detail": detail, "critical": critical}


def last_successful_production_run(state_path: Path = WORKFLOW_STATE,
                                   database: Path = PRODUCTION_DB) -> dict | None:
    """Read the atomic checkpoint, falling back to preserved run history."""
    checkpoint = read_workflow_state(state_path).get("last_successful_run")
    if checkpoint and checkpoint.get("status") == "SUCCESS":
        return checkpoint
    try:
        with closing(sqlite3.connect(database)) as db:
            row = db.execute("""SELECT run_uuid,started_at,completed_at,status
              FROM workflow_runs
              WHERE environment='production' AND dry_run=0 AND status='SUCCESS'
              ORDER BY completed_at DESC LIMIT 1""").fetchone()
        if not row:
            return None
        started = datetime.fromisoformat(row[1])
        completed = datetime.fromisoformat(row[2])
        return {"run_uuid": row[0], "started_at": row[1], "completed_at": row[2],
                "status": row[3],
                "duration_seconds": round((completed - started).total_seconds(), 3)}
    except (sqlite3.Error, TypeError, ValueError):
        return None


def collect_health(check_network: bool = False) -> dict:
    load_dotenv(HERE / ".env")
    items = []
    # Environment loading is performed by nfl_schedule during import.
    ok, detail = check_sqlite(PRODUCTION_DB)
    items.append(_item("Registry", "OK" if ok else "CRITICAL", detail, True))
    schema = "unavailable"
    if ok:
        try:
            schema = str(NFLRegistry(PRODUCTION_DB, environment="production").status().get("schema_version", "current"))
        except Exception as exc:
            schema = exc.__class__.__name__
    items.append(_item("Database Schema", "OK" if ok else "CRITICAL", schema, True))
    ledger = HERE / "paper_positions.json"
    try:
        paper = json.loads(ledger.read_text(encoding="utf-8"))
        paper_ok = paper.get("version") == 1 and isinstance(paper.get("open_positions"), list)
    except (OSError, json.JSONDecodeError):
        paper_ok = False
    items.append(_item("Paper Ledger", "OK" if paper_ok else "CRITICAL", "readable v1" if paper_ok else "unreadable", True))
    telegram = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    items.append(_item("Telegram", "OK" if telegram else "WARNING", "configured" if telegram else "not fully configured"))
    try:
        ZoneInfo("America/Los_Angeles")
        timezone_ok = True
    except ZoneInfoNotFoundError:
        timezone_ok = False
    items.append(_item("Timezone", "OK" if timezone_ok else "CRITICAL", "America/Los_Angeles", True))
    dashboard_files = all((HERE / name).exists() for name in ("dashboard_live.html", "game_flow_dashboard.html", "game_flow.js"))
    items.append(_item("Dashboard", "OK" if dashboard_files else "CRITICAL", "required files present" if dashboard_files else "files missing", True))
    research_ok = ok and (HERE / "nfl_postgame_research.py").exists()
    items.append(_item("Research Records", "OK" if research_ok else "CRITICAL", "registry available" if research_ok else "unavailable", True))
    scheduler = "Not installed"
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", "Polymarket NFL Research Hourly"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            scheduler = "Installed"
    except (OSError, subprocess.SubprocessError):
        scheduler = "Unknown"
    items.append(_item("Task Scheduler", "OK" if scheduler == "Installed" else "WARNING", scheduler))
    last_run = last_successful_production_run() if ok else None
    detail = (f'{last_run["completed_at"]} ({last_run["duration_seconds"]:.1f}s, '
              f'{last_run["run_uuid"]})') if last_run else "never"
    items.append(_item("Last Successful Run", "OK" if last_run else "WARNING", detail))
    if LOCK_FILE.exists():
        items.append(_item("Workflow Lock", "WARNING", "lock file present"))
    if not WORKFLOW_LOG.exists():
        items.append(_item("Workflow Log", "WARNING", "not created yet"))
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "items": items,
            "critical": any(item["state"] == "CRITICAL" for item in items)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = collect_health()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=" * 42, "NFL Research Platform Health", "=" * 42, sep="\n")
        for item in report["items"]:
            print(f'{item["name"]:.<24} {item["state"]:<8} {item["detail"]}')
        print("=" * 42)
    return 1 if report["critical"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
