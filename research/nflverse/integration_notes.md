# nflverse integration notes

**Status: AUDITED, STAGED, NOT INTEGRATED.** Probed 2026-09-08 against
`nflreadpy` 0.1.5. No production code path touches nflverse. This document
records what exists, what it would cost, and what would have to be true before
any of it lands.

---

## 1. Headline finding — the join key is exact

nflverse `schedules` carries an `espn` column. Our registry keys every game on
`official_source_identifier`, sourced `ESPN_STRUCTURED_NFL`. They are the same
identifier space, and the overlap is not approximate:

| Check | Result |
|---|---|
| 2026 REG games in `sports_registry_production.db` | 272 |
| 2026 games in nflverse `load_schedules` | 272 |
| **Matched on ESPN id** | **272 / 272** |
| Registry-only orphans | 0 |
| nflverse-only orphans | 0 |
| `espn` column populated, 2025 season | 285 / 285 |

Reproduce with `nflverse_probe.py --verify-crosswalk`.

**Why this matters.** The registry's core rule is that external records attach
only through an exact canonical identity — never a fuzzy team-name or
kickoff-time match. That rule is what retired the old title-matching scanner.
An nflverse adapter would not need any of that machinery: it joins on the ESPN
id the registry already stores. If integration ever happens, this is the one
property that makes it defensible.

nflverse also ships `pfr`, `pff`, `ftn`, `gsis`, and `old_game_id`, all fully
populated except `pff` (272/285) and `ftn` (278/285). `nfl_detail_id` is
entirely null in 2025 — ignore it.

---

## 2. Blocking finding — nflverse is not a live feed

At probe time (2026-09-08, after Week 1 kickoff):

- nflverse 2026 schedules: **272 games, 0 with results**
- our ESPN-sourced registry at the same moment: **47 finals recorded**

nflverse publishes on a batch cadence behind the live feed. This is fine for
what it is — a research archive — but it forecloses an entire category of use:

> **nflverse must never become a results, settlement, or live-pricing source.**
> ESPN stays authoritative for finals; the Odds API and Polymarket US stay
> authoritative for prices. Anything else reintroduces the "which source said
> what, and when" ambiguity the registry was built to eliminate.

Any future adapter is therefore **backfill-only** and must run strictly behind
verified FINAL status, never ahead of it.

---

## 3. What is actually in there

Probed `--season 2025`. Row counts are one season unless noted.

| Dataset | Size | Relevance | Notes |
|---|---|---|---|
| `schedules` | 285 × 46 | **High** | Join key + closing lines. See §4. |
| `teams` | 36 × 16 | Low | Abbreviations, colors, logos. 36 rows covers relocations/aliases. |
| `team_stats` | 570 × 138 | **Medium** | Team-week box + EPA/CPOE. Two rows per game. |
| `injuries` | 6,068 × 16 | Medium | Practice + game report status by player-week, since 2009. |
| `depth_charts` | **554,215** × 12 | Low | One season. Snapshot-per-day granularity — do not bulk store. |
| `pbp` | not probed | Low | Behind `--include-pbp`. Play-grain; far below moneyline resolution. |

25 loaders exist in total (`load_players`, `load_rosters`, `load_snap_counts`,
`load_nextgen_stats`, `load_ff_*`, …). The player- and fantasy-oriented ones
are **out of scope**: this platform researches team moneylines, not player
props.

---

## 4. The one genuinely valuable dataset

`schedules` carries historical **closing** market data per game:

```
away_moneyline, home_moneyline, spread_line,
away_spread_odds, home_spread_odds,
total_line, over_odds, under_odds
```

plus context we do not currently store: `away_rest`/`home_rest`, `div_game`,
`roof`, `surface`, `temp`, `wind`, `referee`, starting QB ids and names.

Example (2025 REG W1): `2025_01_DAL_PHI`, espn `401772510`, DAL +330 / PHI
−425, spread 8.5, total 47.5, result 4.

**The opportunity.** `nfl_edge_minimum_percentage_points` is currently 3.0 and
`README_EDGE_FINDER.md` is explicit that it is an unvalidated display
threshold, not a validated strategy rule. A closing-line archive is the
material that could turn that number into something measured rather than
assumed — how often a 3pt observed edge preceded a closing line that moved
toward it.

**The trap.** These are *closing* consensus lines. Our live edge compares a
vig-free book consensus against a Polymarket price at observation time. They
are different quantities. Loading closing lines into the same tables, or
comparing them without labelling which is which, silently redefines "edge" and
corrupts the research record. Any use must keep them in a separately named,
separately sourced structure.

---

## 5. Cost and footprint

- `nflreadpy` 0.1.5, MIT, Python ≥3.10. Pulls **polars** (~30 MB), pydantic,
  pydantic-settings, tqdm, platformdirs. Heavier than the entire current
  production dependency set.
- Default cache is **in-memory** — nothing lands on disk unless
  `--cache-dir` is passed. This is why the folder can stay clean.
- Held in `research/nflverse/.venv`, deliberately **not** in the project
  `requirements.txt`. The dashboard's dependency tree is unchanged.

---

## 6. Recommendation

**Do not integrate now.** The audit is the deliverable. Preconditions before
reopening:

1. **Credentials first.** The live platform is still on placeholder API keys;
   position sync and the edge scanner are not producing data yet. A second
   data source is premature while the first-party ones are dark.
2. **Backfill-only, behind FINAL.** Written as a source-linked adapter, not a
   parallel schedule table — it attaches to existing `game_uuid`s, and never
   creates a game the ESPN sync did not.
3. **Closing lines quarantined from live edge.** Distinct table, distinct
   source label, distinct provenance, never joined into `sports_edges.json`.
4. **Fetch on demand.** No parquet committed. Cache stays out of git.
5. **A concrete question first.** Worth doing to validate the 3.0pp threshold
   against closing-line movement. Not worth doing "because the data exists."

If none of those are pressing, the correct next action on this folder is
**none**. It is already in the state it should be in.
