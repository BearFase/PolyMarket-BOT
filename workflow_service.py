#!/usr/bin/env python3
"""Console-free entry point for the hourly NFL research workflow.

The "Polymarket NFL Research Hourly" task used to run `nfl_daily_update.py`
under `python.exe`. That is a console program, so every hour Windows opened a
terminal window on top of whatever the user was doing, titled with the bot's
Python path. This module is what the task runs instead, under `pythonw.exe`,
which is a GUI-subsystem binary and never allocates a console.

`pythonw.exe` leaves `sys.stdout` and `sys.stderr` as None, which would drop the
run summary the workflow prints and any traceback, and would break an imported
module that reconfigures stdout. Both are rebound to a log file before the
workflow is imported. The workflow's own logger still writes
`logs/workflow.log`; this file keeps only what reaches stdout and stderr.

Run by hand for debugging: `python workflow_service.py [--dry-run]`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONSOLE_LOG = ROOT / "logs" / "workflow_console.log"
MAX_LOG_BYTES = 5 * 1024 * 1024


def _open_log(path: Path):
    """Append to the log, trimming it first once it has grown past the cap."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            keep = path.read_bytes()[-(MAX_LOG_BYTES // 2):]
            path.write_bytes(b"[log trimmed]\n" + keep)
    except OSError:
        pass
    return path.open("a", encoding="utf-8", errors="replace", buffering=1)


def main(argv=None) -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    log = _open_log(CONSOLE_LOG)
    sys.stdout = log
    sys.stderr = log

    # Imported only after stdout exists, for modules that touch it at import.
    import nfl_daily_update

    return nfl_daily_update.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
