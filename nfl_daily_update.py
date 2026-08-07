#!/usr/bin/env python3
"""Idempotent, production-only NFL research workflow. No entry creation."""

import argparse
import json
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from nfl_schedule import (
    NFLRegistry, PRODUCTION_DB, fetch_odds_api, fetch_polymarket_us,
    odds_api_records, polymarket_us_records, refresh_game_flow_activity,
    sync_schedule, utc_now,
)
from nfl_research_report import build_report
from nfl_postgame_research import materialize_completed_summaries
from nfl_operations import (
    LOCK_FILE as DEFAULT_LOCK_FILE, WorkflowAlreadyRunning,
    WorkflowLock as OperationsWorkflowLock, record_workflow_completion,
    run_daily_maintenance, startup_checks, workflow_logger,
)
from paper_trader import PaperTrader
from telegram_notification_center import TelegramNotificationCenter

HERE = Path(__file__).parent
LOCK_FILE = DEFAULT_LOCK_FILE


class WorkflowLock(OperationsWorkflowLock):
    """Compatibility wrapper whose path remains patchable by existing tests."""
    def __init__(self, path=None, logger=None):
        super().__init__(path or LOCK_FILE, logger=logger)


def sanitized_error(exc):
    return f"{exc.__class__.__name__}: operation failed"


def run_workflow(registry, no_telegram=False, paper=None, logger=None, maintenance=None):
    steps, errors = {}, []
    logger = logger or workflow_logger()

    def step(name, callback):
        began = time.monotonic()
        logger.info("step started name=%s", name)
        try:
            value = callback()
            steps[name] = {"status": "SUCCESS", "result": value}
            logger.info("step succeeded name=%s duration_seconds=%.3f result=%s",
                        name, time.monotonic() - began, json.dumps(value, default=str))
            return value
        except Exception as exc:
            error = sanitized_error(exc)
            steps[name] = {"status": "FAILED", "error": error}
            errors.append({"step": name, "error": error})
            logger.exception("step failed name=%s duration_seconds=%.3f recovery=continue-independent-steps",
                             name, time.monotonic() - began)
            return None

    paper = paper or PaperTrader()
    preflight = step("startup_self_check", lambda: startup_checks(
        registry.db_path, Path(paper.state_path), HERE))
    production_target = Path(registry.db_path).resolve() == PRODUCTION_DB.resolve()
    if production_target and (not preflight or not preflight["safe_to_continue"]):
        errors.append({"step": "startup_self_check", "error": "critical startup check failed"})
        logger.error("workflow stopped recovery=repair-critical-startup-check")
        return steps, errors

    step("schedule_sync", lambda: sync_schedule(registry))

    def odds():
        scan = str(uuid.uuid4())
        records = odds_api_records(fetch_odds_api("americanfootball_nfl_preseason"),
                                   registry.config["nfl_season"], "PRE")
        records += odds_api_records(fetch_odds_api("americanfootball_nfl"),
                                    registry.config["nfl_season"], "REG")
        results = [registry.link_source(record, scan) for record in records]
        return {"records": len(results), "accepted": sum(r.accepted for r in results)}
    step("odds_api_link", odds)

    def polymarket():
        scan = str(uuid.uuid4())
        records = polymarket_us_records(
            fetch_polymarket_us(season=registry.config["nfl_season"]),
            registry.config["nfl_season"], None)
        results = [registry.link_source(record, scan) for record in records]
        return {"records": len(results), "accepted": sum(r.accepted for r in results)}
    step("polymarket_us_link", polymarket)
    step("game_flow_refresh", lambda: refresh_game_flow_activity(registry))
    step("result_refresh", lambda: {"final_results": registry.status()["final_results"]})
    step("simulation_tracks", lambda: {"created": registry.create_simulation_tracks(),
                                        "settled": registry.settle_simulations()})
    step("paper_settlement", lambda: {"settled": len(paper.settle_resolved_positions())})
    step("postgame_research", lambda: materialize_completed_summaries(registry))
    step("research_report", lambda: build_report(registry=registry, paper=paper))
    if maintenance is None:
        maintenance = production_target
    if maintenance:
        step("daily_maintenance", lambda: run_daily_maintenance(registry.db_path, logger=logger))
    else:
        steps["daily_maintenance"] = {"status": "SKIPPED", "reason": "dry run"}
    if no_telegram:
        for name in ("telegram_pregame", "telegram_finals", "telegram_warnings", "telegram_morning"):
            steps[name] = {"status": "SKIPPED", "reason": "--no-telegram"}
    else:
        center = step("telegram_initialize", lambda: TelegramNotificationCenter(registry=registry, paper=paper))
        if center is not None:
            step("telegram_pregame", lambda: center.process_pregame())
            step("telegram_finals", lambda: center.process_finals())
            step("telegram_warnings", lambda: center.process_warnings())
            if center.morning_due():
                step("telegram_morning", lambda: center.send_morning_brief())
            else:
                steps["telegram_morning"] = {"status": "SKIPPED", "reason": "outside configured morning window"}
    return steps, errors


def journal_run(registry, run_uuid, dry_run, started, completed, steps, errors):
    with registry.connect() as db:
        db.execute("""INSERT OR REPLACE INTO workflow_runs VALUES(?,?,?,?,?,?,?,?)""",
          (run_uuid, registry.environment, int(dry_run), started, completed,
           "COMPLETED_WITH_ERRORS" if errors else "SUCCESS",
           json.dumps(steps, default=str), json.dumps(errors)))


def workflow_status():
    registry = NFLRegistry(PRODUCTION_DB, environment="production")
    with registry.connect() as db:
        row = db.execute("SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    return dict(row) if row else {"status": "NEVER_RUN"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["run", "status"], default="run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(workflow_status(), indent=2, default=str)); return 0
    logger = workflow_logger()
    began = time.monotonic()
    started, run_uuid = utc_now(), str(uuid.uuid4())
    logger.info("workflow started run_uuid=%s dry_run=%s no_telegram=%s", run_uuid, args.dry_run, args.no_telegram)
    try:
        with WorkflowLock(logger=logger):
            if args.dry_run:
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "production-dry-run.db"
                    if PRODUCTION_DB.exists():
                        shutil.copy2(PRODUCTION_DB, target)
                    registry = NFLRegistry(target, environment="production")
                    paper_target = Path(directory) / "paper_positions.json"
                    paper_config = Path(directory) / "paper_config.json"
                    if (HERE / "paper_positions.json").exists():
                        shutil.copy2(HERE / "paper_positions.json", paper_target)
                    if (HERE / "paper_config.json").exists():
                        shutil.copy2(HERE / "paper_config.json", paper_config)
                    paper = PaperTrader(config_path=paper_config, state_path=paper_target,
                                        legacy_state_path=Path(directory) / "paper_state.json")
                    steps, errors = run_workflow(registry, no_telegram=True, paper=paper)
            else:
                registry = NFLRegistry(PRODUCTION_DB, environment="production")
                steps, errors = run_workflow(registry, no_telegram=args.no_telegram)
                completed = utc_now()
                status = "COMPLETED_WITH_ERRORS" if errors else "SUCCESS"
                journal_run(registry, run_uuid, False, started, completed, steps, errors)
                record_workflow_completion(
                    run_uuid=run_uuid, started_at=started, completed_at=completed,
                    status=status, duration_seconds=time.monotonic() - began,
                )
    except WorkflowAlreadyRunning as exc:
        logger.warning("workflow skipped run_uuid=%s reason=overlap", run_uuid)
        print(str(exc))
        return 0
    logger.info("workflow finished run_uuid=%s status=%s duration_seconds=%.3f failures=%s",
                run_uuid, "FAILED" if errors else "SUCCESS", time.monotonic() - began, len(errors))
    print(json.dumps({"run_uuid": run_uuid, "dry_run": args.dry_run,
                      "steps": steps, "errors": errors}, indent=2, default=str))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
