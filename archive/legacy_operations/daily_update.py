#!/usr/bin/env python3
"""
Daily Update - one command to run the whole pipeline.

    python daily_update.py           # sync + edges + report
    python daily_update.py --quick   # sync + report only (skip edge scan)

Steps:
  1. Sync real positions from Polymarket US API -> real_positions.json
  2. Calculate NFL observations from sources already linked to the same
     production canonical game UUID -> sports_edges.json
  3. Check open positions for big moves (Telegram alert if configured)
  4. Build the daily report (prints; sends to Telegram if configured)

Read-only: this never places or closes a trade.
"""

import sys
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def step(name, fn):
    print(f"\n{'='*60}\nSTEP: {name}\n{'='*60}")
    try:
        fn()
        return True
    except Exception as e:
        print(f"[ERROR] {name} failed: {e}")
        traceback.print_exc()
        return False


def main():
    quick = "--quick" in sys.argv
    results = {}

    from sync_positions_api import sync_positions
    results["sync"] = step("Sync positions from Polymarket", sync_positions)

    if not quick:
        import sports_edge_finder
        results["edges"] = step("Scan canonical NFL edges", sports_edge_finder.main)

    from monitor_positions import monitor_positions
    results["monitor"] = step("Check position moves", monitor_positions)

    from dashboard_data import build as build_dashboard_data
    results["bundle"] = step("Bundle dashboard data", build_dashboard_data)

    import telegram_morning_report
    results["report"] = step("Daily report", telegram_morning_report.main)

    print(f"\n{'='*60}")
    failed = [k for k, ok in results.items() if not ok]
    if failed:
        print(f"DONE WITH ERRORS: {', '.join(failed)} failed")
        sys.exit(1)
    print("DONE: all steps completed")


if __name__ == "__main__":
    main()
