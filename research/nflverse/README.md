# nflverse — quarantined research area

This folder is an **audit**, not an integration. It records what the nflverse
NFL datasets contain and whether they could ever be joined to our canonical
NFL registry. Nothing here is imported, launched, scheduled, or routed by
production, and nothing here writes to project state.

Findings and the recommendation are in
[`integration_notes.md`](integration_notes.md). The captured schemas are in
[`sample_schema.json`](sample_schema.json).

## Why it is quarantined

The registry exists to refuse guessed matches. A second NFL data source that
also has schedules, results, and betting lines is exactly the thing that could
quietly become a competing source of truth — same games, slightly different
numbers, no record of which one a research summary was built from.

So this area is fenced by construction:

| Fence | How |
|---|---|
| Separate dependency tree | Its own `.venv`; `nflreadpy` is **not** in the project `requirements.txt` |
| No production reachability | No project module imports anything under `research/` |
| No bulk data on disk | nflreadpy defaults to an in-memory cache; the probe persists schema only |
| Registry is read-only | `--verify-crosswalk` opens SQLite via a `mode=ro` URI, one SELECT, no writes |
| Not committed | `research/**/.venv/` and the nflverse cache are gitignored |

## Setup

Already done, but to rebuild from scratch:

```bash
cd research/nflverse && "$LOCALAPPDATA/Programs/Python/Python314/python.exe" -m venv .venv && ./.venv/Scripts/python.exe -m pip install nflreadpy
```

## Run the probe

```bash
cd research/nflverse && ./.venv/Scripts/python.exe nflverse_probe.py --verify-crosswalk
```

| Flag | Effect |
|---|---|
| *(none)* | Probes schedules, teams, team stats, injuries, depth charts for `--season` |
| `--verify-crosswalk` | Read-only ESPN-id join against `sports_registry_production.db` |
| `--season N` | Season to probe (default 2025, the last complete one) |
| `--include-pbp` | Also probe play-by-play — a large download, off by default |
| `--sample-rows N` | Example rows kept per dataset (default 2) |
| `--cache-dir PATH` | Opt in to filesystem caching; **off by default on purpose** |

Rewrites `sample_schema.json` (~26 KB). Exits nonzero if any loader failed.

## What this folder must not become

- A source of NFL **results**. nflverse lags live feeds — see the staleness
  finding in the notes. ESPN stays authoritative for finals.
- A source of **prices** for edge research. nflverse ships *closing* consensus
  lines; our edge is computed against live pre-kickoff quotes. Mixing them
  silently changes what "edge" means.
- A place to park seasons of parquet. Data is fetched on demand and kept in
  memory.

## Package

[`nflverse/nflreadpy`](https://github.com/nflverse/nflreadpy) — 0.1.5, MIT,
Python ≥3.10, polars-backed. Python port of the R package `nflreadr`. Note
that `nfl_data_py` is deprecated in favour of it.
