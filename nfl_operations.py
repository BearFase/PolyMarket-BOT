"""Operational safeguards for the unattended NFL research workflow."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
RUNTIME_DIR = HERE / ".runtime"
LOG_DIR = HERE / "logs"
WORKFLOW_LOG = LOG_DIR / "workflow.log"
LOCK_FILE = RUNTIME_DIR / "nfl_daily_update.lock"
MAINTENANCE_STATE = RUNTIME_DIR / "nfl_maintenance.json"
WORKFLOW_STATE = RUNTIME_DIR / "nfl_workflow_state.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_workflow_state(path: Path = WORKFLOW_STATE) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def record_workflow_completion(*, run_uuid: str, started_at: str,
                               completed_at: str, status: str,
                               duration_seconds: float,
                               path: Path = WORKFLOW_STATE) -> dict[str, Any]:
    """Atomically checkpoint a production run without erasing prior success."""
    state = read_workflow_state(path)
    record = {
        "run_uuid": run_uuid,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "duration_seconds": round(float(duration_seconds), 3),
    }
    state.update({"version": 1, "last_production_run": record})
    if status == "SUCCESS":
        state["last_successful_run"] = record
    atomic_json_write(path, state)
    return state


def workflow_logger(path: Path = WORKFLOW_LOG) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("nfl_research_workflow")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    wanted = str(path.resolve())
    if not any(getattr(handler, "baseFilename", None) == wanted for handler in logger.handlers):
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=7, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s"))
        handler.formatter.converter = __import__("time").gmtime
        logger.addHandler(handler)
    return logger


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


class WorkflowAlreadyRunning(RuntimeError):
    pass


class WorkflowLock:
    """Exclusive PID lock that safely recovers a lock left by a dead process."""

    def __init__(self, path: Path = LOCK_FILE, logger: logging.Logger | None = None):
        self.path = path
        self.logger = logger or workflow_logger()
        self.fd: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, json.dumps({"pid": os.getpid(), "started_at": utc_now()}).encode())
                os.fsync(self.fd)
                return self
            except FileExistsError:
                try:
                    owner = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(owner.get("pid", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pid = 0
                if _pid_running(pid):
                    self.logger.warning("workflow overlap prevented owner_pid=%s", pid)
                    raise WorkflowAlreadyRunning(f"NFL research workflow is already running (PID {pid})")
                self.logger.warning("recovering stale workflow lock owner_pid=%s", pid or "unknown")
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
        raise WorkflowAlreadyRunning("unable to acquire NFL research workflow lock")

    def __exit__(self, *_args):
        if self.fd is not None:
            os.close(self.fd)
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
            if int(owner.get("pid", -1)) == os.getpid():
                self.path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass


def check_sqlite(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    try:
        with closing(sqlite3.connect(path)) as db:
            result = db.execute("PRAGMA quick_check").fetchone()[0]
        return result == "ok", result
    except sqlite3.Error as exc:
        return False, f"{exc.__class__.__name__}"


def startup_checks(database: Path, paper_ledger: Path, project: Path = HERE) -> dict:
    """Return safe-to-display preflight results without making network calls."""
    load_dotenv(project / ".env")
    checks = {}
    registry_ok, detail = check_sqlite(database)
    checks["registry"] = {"status": "OK" if registry_ok else "CRITICAL", "detail": detail}
    try:
        with closing(sqlite3.connect(database)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        schema_ok = {"games", "workflow_runs", "notification_journal"}.issubset(tables)
    except sqlite3.Error:
        schema_ok = False
    checks["database_schema"] = {"status": "OK" if schema_ok else "CRITICAL"}
    try:
        ledger = json.loads(paper_ledger.read_text(encoding="utf-8"))
        paper_ok = ledger.get("version") == 1 and isinstance(ledger.get("open_positions"), list)
    except (OSError, json.JSONDecodeError):
        paper_ok = False
    checks["paper_ledger"] = {"status": "OK" if paper_ok else "CRITICAL"}
    try:
        ZoneInfo("America/Los_Angeles")
        timezone_ok = True
    except ZoneInfoNotFoundError:
        timezone_ok = False
    checks["timezone"] = {"status": "OK" if timezone_ok else "CRITICAL"}
    files_ok = all((project / name).exists() for name in
                   ("dashboard_live.html", "game_flow_dashboard.html", "game_flow.js"))
    checks["dashboard_files"] = {"status": "OK" if files_ok else "WARNING"}
    telegram_ok = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    checks["telegram"] = {"status": "OK" if telegram_ok else "WARNING"}
    checks["apis"] = {"status": "DEFERRED", "detail": "verified independently by isolated source steps"}
    return {"checks": checks, "safe_to_continue": not any(
        item["status"] == "CRITICAL" for item in checks.values())}


def run_daily_maintenance(database: Path, logger: logging.Logger | None = None,
                          state_path: Path = MAINTENANCE_STATE, force: bool = False) -> dict:
    """Integrity-check and compact runtime stores at most once per UTC day."""
    logger = logger or workflow_logger()
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    if not force and state.get("last_completed_date") == today:
        return {"status": "SKIPPED", "reason": "already completed today"}
    ok, detail = check_sqlite(database)
    if not ok:
        raise RuntimeError(f"registry integrity check failed: {detail}")
    with closing(sqlite3.connect(database, timeout=30)) as db:
        journal_ok = db.execute("PRAGMA integrity_check").fetchone()[0]
        if journal_ok != "ok":
            raise RuntimeError("registry integrity check failed")
        db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        db.execute("VACUUM")
        db.commit()
    removed = 0
    for candidate in RUNTIME_DIR.glob("*.tmp"):
        try:
            if candidate.is_file():
                candidate.unlink()
                removed += 1
        except OSError:
            logger.warning("temporary cleanup failed file=%s", candidate.name)
    result = {"status": "SUCCESS", "completed_at": utc_now(), "temporary_files_removed": removed}
    atomic_json_write(state_path, {"last_completed_date": today, **result})
    logger.info("daily maintenance complete temporary_files_removed=%s", removed)
    return result
