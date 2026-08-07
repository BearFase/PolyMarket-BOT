#!/usr/bin/env python3
"""
Dashboard server with live sync.

Serves the dashboard on http://127.0.0.1:8765 AND re-syncs positions from
the Polymarket US API every 60 seconds, so trades made in the app (phone or
web) appear on the dashboard within ~90s without touching anything.

Position alerts (monitor_positions) run every 5th cycle. Canonical NFL edge data refreshes
automatically on a slow cadence in a separate thread:
edges every 6h (The Odds API free tier is 500 requests/month — 4 scans/day
stays well inside it). It runs at startup when its file is stale.

Launched by Open Dashboard.cmd through bot_launcher.py. Manual: python dashboard_server.py
"""

import os
import sys
import time
import threading
from pathlib import Path

from system_status import mark_error, mark_success

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
# 8765 may be held indefinitely by an older dashboard process. Use a fresh,
# dedicated port so the unified app can always load the current routes.
PORT = 8766
SYNC_EVERY = 60          # seconds between position syncs
MONITOR_EVERY = 5        # run alert check every N sync cycles
EDGE_EVERY = 6 * 3600    # seconds between edge scans (Odds API quota)

def _age(fname):
    """Seconds since a data file was last written (inf if missing)."""
    try:
        return time.time() - os.path.getmtime(HERE / fname)
    except OSError:
        return float("inf")

def refresh_loop():
    """Slow-cadence edge refresh; never blocks position sync."""
    from dashboard_data import build
    while True:
        try:
            if _age("sports_edges.json") > EDGE_EVERY:
                print("[refresh] canonical NFL edge calculation starting...")
                import sports_edge_finder
                before = (HERE / "sports_edges.json").stat().st_mtime \
                    if (HERE / "sports_edges.json").exists() else 0
                sports_edge_finder.main()
                after = (HERE / "sports_edges.json").stat().st_mtime \
                    if (HERE / "sports_edges.json").exists() else 0
                if after <= before:
                    raise RuntimeError("edge scan produced no fresh output")
                build()
                mark_success("edge_scan")
                print("[refresh] edge scan done")
        except Exception as e:
            print(f"[refresh] edge scan error: {e}")
            mark_error("edge_scan", e)
        time.sleep(300)  # re-check staleness every 5 minutes

def sync_loop():
    from sync_positions_api import sync_positions
    from dashboard_data import build
    from monitor_positions import monitor_positions

    cycle = 0
    while True:
        try:
            result = sync_positions()
            if not result:
                raise RuntimeError("position sync returned no updated data")
            build()
            mark_success("position_sync")
            if cycle % MONITOR_EVERY == 0:
                monitor_positions()
        except Exception as e:
            print(f"[sync-loop] error: {e}")
            mark_error("position_sync", e)
        cycle += 1
        time.sleep(SYNC_EVERY)

def main():
    from trader_dashboard import app
    health_only = os.environ.get("POLYMARKET_HEALTH_ONLY") == "1"
    if not health_only:
        from big_money_tape import run as run_big_money_tape
        threading.Thread(target=sync_loop, daemon=True).start()
        threading.Thread(target=refresh_loop, daemon=True).start()
        threading.Thread(target=run_big_money_tape, daemon=True).start()
    print(f"[SERVER] Dashboard live at http://127.0.0.1:{PORT}/")
    print(f"[SERVER] Game Flow at http://127.0.0.1:{PORT}/game-flow")
    if health_only:
        print("[SERVER] Health-only lifecycle test mode; background workers disabled")
    else:
        print(f"[SERVER] Re-syncing positions from Polymarket every {SYNC_EVERY}s")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True, use_reloader=False)

if __name__ == "__main__":
    main()
