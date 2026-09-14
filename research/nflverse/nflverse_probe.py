#!/usr/bin/env python3
r"""Quarantined nflverse capability probe.

Read-only. This script exists to answer one question: *what is in nflverse,
and could it ever be joined to our canonical NFL registry?* It deliberately
stops short of integrating anything.

Guarantees
----------
- Writes exactly one file, `sample_schema.json`, in its own directory:
  column names, dtypes, row counts, and at most `--sample-rows` example rows
  per dataset. No bulk data is ever persisted.
- Opens the canonical registry only under `--verify-crosswalk`, and then only
  through a SQLite `mode=ro` URI. It issues one SELECT and writes nothing.
  Every other project database, the paper ledger, and `.runtime/` state are
  never opened at all.
- Uses nflreadpy's default in-memory cache, so no parquet lands on disk
  unless the caller explicitly passes `--cache-dir`.

Run:
    .\.venv\Scripts\python.exe nflverse_probe.py
    .\.venv\Scripts\python.exe nflverse_probe.py --verify-crosswalk
    .\.venv\Scripts\python.exe nflverse_probe.py --season 2025 --include-pbp
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "sample_schema.json"
REGISTRY = HERE.parents[1] / "sports_registry_production.db"

# Datasets worth probing for this project. Anything player- or
# fantasy-oriented is out of scope: we price team moneylines, not players.
CORE_PROBES = ("schedules", "teams", "team_stats", "injuries", "depth_charts")
HEAVY_PROBES = ("pbp",)


def _json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def describe(frame, sample_rows: int) -> dict:
    """Reduce a polars frame to schema plus a handful of example rows."""
    return {
        "rows": frame.height,
        "columns": frame.width,
        "schema": {name: str(dtype) for name, dtype in frame.schema.items()},
        "sample": json.loads(
            json.dumps(frame.head(sample_rows).to_dicts(), default=_json_safe)
        ),
    }


def crosswalk_report(schedules) -> dict:
    """Which external IDs nflverse carries, and how completely.

    Our canonical registry is keyed on ESPN event IDs. If nflverse ships a
    fully populated `espn` column, a future adapter could join on it *without*
    matching on team names or kickoff times — which is exactly the guessing
    the registry was built to refuse.
    """
    known_id_columns = ("game_id", "espn", "pfr", "pff", "ftn", "old_game_id",
                        "nfl_detail_id", "gsis", "away_team", "home_team")
    present = [c for c in known_id_columns if c in schedules.columns]
    report = {"id_columns_present": present, "coverage": {}}
    for column in present:
        nulls = schedules.get_column(column).null_count()
        report["coverage"][column] = {
            "null": nulls,
            "populated": schedules.height - nulls,
        }
    return report


def verify_crosswalk(schedules, season: int) -> dict:
    """Join nflverse ESPN ids against the canonical registry, read-only.

    Proves or disproves the join key on real data rather than asserting it
    from documentation. Opens the registry through a `mode=ro` URI so the
    probe cannot write even by accident.
    """
    if not REGISTRY.exists():
        return {"status": "SKIPPED", "detail": f"{REGISTRY.name} not present"}

    uri = f"file:{REGISTRY.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        rows = db.execute(
            "SELECT official_source_identifier, official_source_name FROM games "
            "WHERE season = ? AND season_type = 'REG'", (season,)
        ).fetchall()

    if not rows:
        return {"status": "SKIPPED", "detail": f"no {season} REG games in registry"}

    registry_ids = {str(r[0]) for r in rows}
    nflverse_ids = {str(v) for v in schedules.get_column("espn").to_list()}
    matched = registry_ids & nflverse_ids
    return {
        "status": "EXACT" if registry_ids == nflverse_ids else "PARTIAL",
        "season": season,
        "registry_source": rows[0][1],
        "registry_games": len(registry_ids),
        "nflverse_games": len(nflverse_ids),
        "matched": len(matched),
        "registry_only": sorted(registry_ids - nflverse_ids)[:10],
        "nflverse_only": sorted(nflverse_ids - registry_ids)[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantined nflverse probe.")
    parser.add_argument("--season", type=int, default=2025,
                        help="season to probe (default: 2025, last complete)")
    parser.add_argument("--current-season", type=int, default=2026,
                        help="additionally probe schedule availability here")
    parser.add_argument("--sample-rows", type=int, default=2,
                        help="example rows retained per dataset (default: 2)")
    parser.add_argument("--include-pbp", action="store_true",
                        help="also probe play-by-play (large download)")
    parser.add_argument("--verify-crosswalk", action="store_true",
                        help="read-only ESPN id join against the canonical registry")
    parser.add_argument("--cache-dir",
                        help="opt in to filesystem caching at this path")
    args = parser.parse_args()

    if args.cache_dir:
        import os
        os.environ["NFLREADPY_CACHE_MODE"] = "filesystem"
        os.environ["NFLREADPY_CACHE_DIR"] = args.cache_dir

    import nflreadpy as nfl

    findings: dict = {
        "probed_at": datetime.now().astimezone().isoformat(),
        "nflreadpy_version": nfl.__version__,
        "season_probed": args.season,
        "loaders_available": sorted(
            name for name in dir(nfl) if name.startswith("load_")
        ),
        "datasets": {},
        "errors": {},
    }

    names = list(CORE_PROBES) + (list(HEAVY_PROBES) if args.include_pbp else [])
    seasonless = {"teams"}

    for name in names:
        loader = getattr(nfl, f"load_{name}")
        try:
            frame = loader() if name in seasonless else loader(seasons=args.season)
            findings["datasets"][name] = describe(frame, args.sample_rows)
            print(f"  [ok]   {name:14} {frame.height:>7} rows x {frame.width:>3} cols")
        except Exception as error:                      # probe must not abort
            findings["errors"][name] = f"{type(error).__name__}: {error}"
            print(f"  [fail] {name:14} {type(error).__name__}: {error}")

    try:
        schedules = nfl.load_schedules(seasons=args.season)
        findings["crosswalk"] = crosswalk_report(schedules)
        present = ", ".join(findings["crosswalk"]["id_columns_present"])
        print(f"  [ok]   crosswalk      {present}")
    except Exception as error:
        findings["errors"]["crosswalk"] = f"{type(error).__name__}: {error}"

    try:
        current = nfl.load_schedules(seasons=args.current_season)
        played = current.filter(current.get_column("result").is_not_null())
        findings["current_season"] = {
            "season": args.current_season,
            "games": current.height,
            "with_result": played.height,
        }
        print(f"  [ok]   {args.current_season} schedule  {current.height} games, "
              f"{played.height} with results")

        if args.verify_crosswalk:
            check = verify_crosswalk(current, args.current_season)
            findings["registry_crosswalk"] = check
            status = check["status"].lower()
            print(f"  [{status}] registry join  {check.get('matched', 0)}"
                  f"/{check.get('registry_games', 0)} matched on ESPN id")
    except Exception as error:
        findings["errors"]["current_season"] = f"{type(error).__name__}: {error}"

    OUTPUT.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"\nWrote {OUTPUT.name} ({size_kb:.1f} KB) - schema only, no bulk data.")
    return 1 if findings["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
