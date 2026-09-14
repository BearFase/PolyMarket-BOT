#!/usr/bin/env python3
"""Console-free entry point for the dashboard server.

`dashboard_server.py` is a console program: launched through `python.exe` it
gets a console in the interactive session, and any CTRL_C / CTRL_CLOSE /
CTRL_LOGOFF event delivered to that console kills it with exit code
0xC000013A (STATUS_CONTROL_C_EXIT). That is how the scheduled dashboard task
kept dying while reporting no error anywhere: closing an unrelated console in
the same session took the server with it.

This module is the entry point the scheduled task runs under `pythonw.exe`,
which is a GUI-subsystem binary and never allocates a console. With no console
there is no console control event to receive, so the server survives whatever
happens to other windows in the session.

`pythonw.exe` also leaves `sys.stdout` and `sys.stderr` as None, which would
make the server's first `print()` raise. Both are rebound to the existing log
files here, before the server is imported, which additionally restores the
logging the scheduled task silently lost.

Run directly only for debugging; normal startup is `bot_launcher.py task-start`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_LOG = ROOT / "dashboard_server.log"
ERR_LOG = ROOT / "dashboard_server_error.log"
MAX_LOG_BYTES = 5 * 1024 * 1024


def _open_log(path: Path):
    """Append to the log, trimming it first if it has grown past the cap.

    The scheduled task has no rotation of its own and runs indefinitely, so
    without this the two dashboard logs would grow without bound.
    """
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            keep = path.read_bytes()[-(MAX_LOG_BYTES // 2):]
            path.write_bytes(b"[log trimmed]\n" + keep)
    except OSError:
        pass
    return path.open("a", encoding="utf-8", errors="replace", buffering=1)


def main() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    sys.stdout = _open_log(OUT_LOG)
    sys.stderr = _open_log(ERR_LOG)

    # Imported only after stdout exists: dashboard_server reconfigures stdout
    # at import time and prints during startup.
    import dashboard_server

    dashboard_server.main()


if __name__ == "__main__":
    main()
