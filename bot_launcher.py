#!/usr/bin/env python3
"""Reliable, idempotent launcher for the local Polymarket research dashboard."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
PID_FILE = RUNTIME / "dashboard.pid.json"
OUT_LOG = ROOT / "dashboard_server.log"
ERR_LOG = ROOT / "dashboard_server_error.log"
HEALTH_URL = "http://127.0.0.1:8766/api/health"
DASHBOARD_URL = "http://127.0.0.1:8766/"


def health(timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            payload = json.load(response)
        if response.status == 200 and payload.get("service") == "polymarket-dashboard":
            return payload
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return None


def read_pid() -> int | None:
    try:
        return int(json.loads(PID_FILE.read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_pid(pid: int) -> None:
    RUNTIME.mkdir(exist_ok=True)
    temporary = PID_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"pid": pid, "root": str(ROOT)}), encoding="utf-8")
    os.replace(temporary, PID_FILE)


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return f'"{pid}"' in result.stdout


def process_is_owned(pid: int) -> bool:
    """Confirm a saved PID still belongs to this project's dashboard server."""
    script = (
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' "
        "-ErrorAction SilentlyContinue; if($p){$p.CommandLine}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    command = result.stdout.casefold()
    return "dashboard_server.py" in command and str(ROOT).casefold() in command


def stop_owned() -> bool:
    pid = read_pid()
    if pid and process_exists(pid) and process_is_owned(pid):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 5
        while process_exists(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
    PID_FILE.unlink(missing_ok=True)
    return health() is None


def recent_error() -> str:
    try:
        lines = ERR_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(line for line in lines if line.strip())[-2000:]
    except OSError:
        return "No error log was created."


def start(*, health_only: bool = False, timeout: float = 30.0) -> dict:
    running = health()
    if running:
        write_pid(int(running["pid"]))
        return running

    stale = read_pid()
    if stale and process_exists(stale) and process_is_owned(stale):
        stop_owned()
    elif stale:
        PID_FILE.unlink(missing_ok=True)

    env = os.environ.copy()
    if health_only:
        env["POLYMARKET_HEALTH_ONLY"] = "1"
    else:
        env.pop("POLYMARKET_HEALTH_ONLY", None)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    with OUT_LOG.open("a", encoding="utf-8") as stdout, ERR_LOG.open("a", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "dashboard_server.py")],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=flags,
            close_fds=True,
        )
    write_pid(process.pid)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = health()
        if ready:
            write_pid(int(ready["pid"]))
            return ready
        if process.poll() is not None:
            break
        time.sleep(0.25)
    stop_owned()
    raise RuntimeError(f"Dashboard did not become healthy.\n{recent_error()}")


def lifecycle_test(cycles: int) -> None:
    stop_owned()
    started = time.monotonic()
    for cycle in range(1, cycles + 1):
        ready = start(health_only=True, timeout=10)
        if not ready or not stop_owned():
            raise RuntimeError(f"Lifecycle cycle {cycle} failed")
        if cycle % 10 == 0 or cycle == cycles:
            print(f"Lifecycle test: {cycle}/{cycles} passed")
    print(f"PASS: {cycles} clean start/health/stop cycles in {time.monotonic() - started:.1f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "stop", "self-test"), nargs="?", default="start")
    parser.add_argument("--cycles", type=int, default=100)
    args = parser.parse_args()
    try:
        if args.command == "start":
            ready = start()
            print(f"Dashboard ready (PID {ready['pid']}): {DASHBOARD_URL}")
        elif args.command == "status":
            ready = health()
            print(f"Dashboard healthy (PID {ready['pid']}): {DASHBOARD_URL}" if ready else "Dashboard is not running.")
            return 0 if ready else 1
        elif args.command == "stop":
            print("Dashboard stopped." if stop_owned() else "Dashboard could not be stopped cleanly.")
        else:
            if args.cycles < 1:
                parser.error("--cycles must be positive")
            lifecycle_test(args.cycles)
        return 0
    except Exception as exc:
        print(f"STARTUP ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
