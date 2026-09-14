import json
import logging
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import health_check
import nfl_daily_update as workflow
import nfl_operations
from nfl_operations import (
    WorkflowAlreadyRunning, WorkflowLock, atomic_json_write,
    read_workflow_state, record_workflow_completion, run_daily_maintenance,
    startup_checks, workflow_logger,
)


class NFLOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        for logger_name in ("nfl_research_workflow",):
            logger = logging.getLogger(logger_name)
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
        self.temp.cleanup()

    def database(self):
        path = self.root / "registry.db"
        with closing(sqlite3.connect(path)) as db:
            for name in ("games", "workflow_runs", "notification_journal"):
                db.execute(f"CREATE TABLE {name}(id TEXT)")
            db.commit()
        return path

    def project_files(self):
        for name in ("dashboard_live.html", "game_flow_dashboard.html", "game_flow.js"):
            (self.root / name).write_text("ok", encoding="utf-8")

    def ledger(self):
        path = self.root / "paper_positions.json"
        atomic_json_write(path, {"version": 1, "open_positions": []})
        return path

    def test_lock_prevents_overlap_and_recovers_stale_owner(self):
        lock = self.root / "workflow.lock"
        logger = workflow_logger(self.root / "workflow.log")
        with WorkflowLock(lock, logger):
            with self.assertRaises(WorkflowAlreadyRunning):
                WorkflowLock(lock, logger).__enter__()
        lock.write_text(json.dumps({"pid": 99999999}), encoding="utf-8")
        with WorkflowLock(lock, logger):
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())

    def test_logger_writes_and_rotates(self):
        path = self.root / "workflow.log"
        logger = workflow_logger(path)
        logger.info("operational event")
        for handler in logger.handlers:
            handler.flush()
        self.assertIn("operational event", path.read_text(encoding="utf-8"))
        handler = next(h for h in logger.handlers if hasattr(h, "doRollover"))
        handler.doRollover()
        self.assertTrue((self.root / "workflow.log.1").exists())

    def test_startup_checks_classify_critical_and_warning(self):
        database = self.database()
        ledger = self.ledger()
        self.project_files()
        report = startup_checks(database, ledger, self.root)
        self.assertTrue(report["safe_to_continue"])
        self.assertIn(report["checks"]["telegram"]["status"], {"OK", "WARNING"})
        ledger.write_text("not json", encoding="utf-8")
        report = startup_checks(database, ledger, self.root)
        self.assertFalse(report["safe_to_continue"])

    def test_daily_maintenance_is_safe_and_idempotent(self):
        database = self.database()
        state = self.root / "maintenance.json"
        logger = workflow_logger(self.root / "workflow.log")
        first = run_daily_maintenance(database, logger, state_path=state)
        second = run_daily_maintenance(database, logger, state_path=state)
        self.assertEqual("SUCCESS", first["status"])
        self.assertEqual("SKIPPED", second["status"])
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual("ok", db.execute("PRAGMA quick_check").fetchone()[0])

    def test_scheduler_scripts_are_safe_and_use_project_venv(self):
        setup = (Path(__file__).parent / "setup_task_scheduler.ps1").read_text(encoding="utf-8")
        remove = (Path(__file__).parent / "remove_task_scheduler.ps1").read_text(encoding="utf-8")
        # pythonw.exe, not python.exe: the console binary opened a window every hour.
        self.assertIn('.venv\\Scripts\\pythonw.exe', setup)
        self.assertIn("workflow_service.py", setup)
        # Re-registering must not move the hourly cadence (it once shifted :07 to :56).
        self.assertIn("AddMinutes(7)", setup)
        self.assertNotIn("AddMinutes(2)", setup)
        self.assertIn("-MultipleInstances IgnoreNew", setup)
        self.assertIn("-RestartCount 3", setup)
        self.assertIn("-WorkingDirectory $Project", setup)
        self.assertIn("-LogonType Interactive", setup)
        self.assertIn("Unregister-ScheduledTask", remove)

    def test_dashboard_shortcuts_use_project_venv(self):
        for name in ("Open Dashboard.cmd", "Start All Bots.cmd"):
            content = (Path(__file__).parent / name).read_text(encoding="utf-8")
            self.assertIn('%~dp0.venv\\Scripts\\python.exe', content)
            self.assertNotIn('D:\\Python314', content)

    def test_successful_completion_is_atomic_and_survives_restart(self):
        state = self.root / "workflow-state.json"
        record_workflow_completion(
            run_uuid="run-success", started_at="2026-08-07T12:00:00+00:00",
            completed_at="2026-08-07T12:00:15+00:00", status="SUCCESS",
            duration_seconds=15.125, path=state,
        )
        restarted = read_workflow_state(state)["last_successful_run"]
        self.assertEqual("run-success", restarted["run_uuid"])
        self.assertEqual("SUCCESS", restarted["status"])
        self.assertEqual(15.125, restarted["duration_seconds"])
        self.assertFalse(any(state.parent.glob("*.tmp")))

    def test_failed_completion_does_not_replace_last_success(self):
        state = self.root / "workflow-state.json"
        record_workflow_completion(run_uuid="good", started_at="s", completed_at="c1",
                                   status="SUCCESS", duration_seconds=1, path=state)
        record_workflow_completion(run_uuid="bad", started_at="s", completed_at="c2",
                                   status="COMPLETED_WITH_ERRORS", duration_seconds=2, path=state)
        saved = read_workflow_state(state)
        self.assertEqual("good", saved["last_successful_run"]["run_uuid"])
        self.assertEqual("bad", saved["last_production_run"]["run_uuid"])

    def test_normal_main_records_success_but_dry_run_does_not(self):
        production = self.root / "production.db"
        with mock.patch.object(workflow, "PRODUCTION_DB", production), \
             mock.patch.object(workflow, "LOCK_FILE", self.root / "workflow.lock"), \
             mock.patch.object(workflow, "run_workflow", return_value=({}, [])), \
             mock.patch.object(workflow, "journal_run"), \
             mock.patch.object(workflow, "record_workflow_completion") as record:
            self.assertEqual(0, workflow.main([]))
            self.assertEqual("SUCCESS", record.call_args.kwargs["status"])
            record.reset_mock()
            self.assertEqual(0, workflow.main(["--dry-run"]))
            record.assert_not_called()

    def test_health_reads_checkpoint_and_database_fallback(self):
        state = self.root / "workflow-state.json"
        record_workflow_completion(run_uuid="checkpoint", started_at="2026-08-07T12:00:00+00:00",
                                   completed_at="2026-08-07T12:00:10+00:00", status="SUCCESS",
                                   duration_seconds=10, path=state)
        self.assertEqual("checkpoint", health_check.last_successful_production_run(
            state, self.root / "missing.db")["run_uuid"])

        database = self.root / "history.db"
        with closing(sqlite3.connect(database)) as db:
            db.execute("""CREATE TABLE workflow_runs(
              run_uuid TEXT, environment TEXT, dry_run INTEGER, started_at TEXT,
              completed_at TEXT, status TEXT, steps_json TEXT, sanitized_errors_json TEXT)""")
            db.execute("INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?)",
                       ("historical", "production", 0, "2026-08-07T12:00:00+00:00",
                        "2026-08-07T12:00:12+00:00", "SUCCESS", "{}", "[]"))
            db.commit()
        fallback = health_check.last_successful_production_run(self.root / "absent.json", database)
        self.assertEqual("historical", fallback["run_uuid"])
        self.assertEqual(12, fallback["duration_seconds"])

    def test_manual_and_scheduler_share_canonical_state_location(self):
        expected = Path(nfl_operations.__file__).resolve().parent / ".runtime" / "nfl_workflow_state.json"
        self.assertEqual(expected, nfl_operations.WORKFLOW_STATE)
        scheduler = (Path(__file__).parent / "setup_task_scheduler.ps1").read_text(encoding="utf-8")
        self.assertIn('-WorkingDirectory $Project', scheduler)
        self.assertIn("nfl_daily_update.py", scheduler)


if __name__ == "__main__":
    unittest.main()
