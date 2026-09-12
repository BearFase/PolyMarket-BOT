# Polymarket Research Platform

A read-only Polymarket US research platform for collecting canonical NFL
evidence, observing market activity, maintaining simulated paper accounting,
and monitoring real positions. It never places real orders. No automatic
paper-entry strategy is active.

## Quick start

1. Create `.env` from `.env.example` and add your own credentials.
2. Install the pinned runtime dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Double-click **`Open Dashboard.cmd`**. It starts or reuses one healthy
   dashboard process and opens <http://127.0.0.1:8766/>.

`Start All Bots.cmd` is retained as a compatibility shortcut. It calls the
same `bot_launcher.py task-start` path and does not launch a second stack.

The dashboard runs as the Windows task `Polymarket Research Dashboard`,
executing `pythonw.exe dashboard_service.py`. `pythonw.exe` allocates no
console, so the server cannot be killed by the CTRL_C / CTRL_CLOSE events
that terminate a console process when an unrelated window in the same session
closes. It has a logon trigger, so it returns after a reboot, and a trigger
repeating every 15 minutes that restarts it if it ever died; `IgnoreNew`
makes that repetition a no-op while it is healthy. `dashboard_service.py`
also restores the stdout/stderr redirection into `dashboard_server.log` and
`dashboard_server_error.log` that a console-less process would otherwise
lose.

Useful checks:

```powershell
.\.venv\Scripts\python.exe bot_launcher.py status
.\.venv\Scripts\python.exe health_check.py
.\.venv\Scripts\python.exe test_all_systems.py
```

## Current architecture

- `bot_launcher.py` — idempotent dashboard lifecycle and health verification.
- `dashboard_service.py` — console-free entry point used by the scheduled
  task; redirects output to the dashboard logs before starting the server.
- `dashboard_server.py` — background real-position, monitoring, edge, and
  dashboard orchestration.
- `trader_dashboard.py` — Flask routes and static asset allowlist.
- `dashboard_live.html` — portfolio and system status.
- `game_flow_dashboard.html`, `game_flow.js`, `game_flow_ui.js` — MLB and NFL
  Game Flow.
- `nfl_schedule.py` — canonical NFL schedule, strict source linkage,
  simulations, results, and production/development registry separation.
- `nfl_daily_update.py` — isolated, idempotent production research workflow.
- `nfl_operations.py`, `health_check.py` — locking, atomic operational state,
  rotating logs, maintenance, scheduler and health observability.
- `nfl_postgame_research.py`, `postgame_research.js` — immutable research
  summaries and append-only analyst note revisions.
- `paper_trader.py` — canonical paper ledger and authoritative settlement.
- `trade_journal.py` — per-league append-only journals of every observed NFL
  and MLB trade; instrumentation only.
- `telegram_notification_center.py` — deduplicated research notifications.
- `sync_positions_api.py`, `monitor_positions.py` — read-only real-position
  synchronization and monitoring.

The detailed per-file classification and dependency findings are in
[`REPOSITORY_INVENTORY.md`](REPOSITORY_INVENTORY.md). The machine-readable
cleanup decisions are in [`cleanup_plan.json`](cleanup_plan.json).

## Game Flow

Game Flow groups qualifying trades by canonical game rather than showing an
undifferentiated chronological tape:

<http://127.0.0.1:8766/game-flow>

The MLB stream keeps its operational top-five display, while every new
qualifying MLB moneyline execution is written first to the immutable
`mlb_research.db` journal. "Qualifying" means a taker BUY_LONG or BUY_SHORT on
a moneyline at or above the display threshold: that journal never recorded
taker sells, ORDER_INTENT_UNDEFINED trades, run lines or totals, so it is a
record of large buys, not of total MLB trading. Display limits are therefore
no longer a research retention policy.

Every NFL and MLB trade the stream delivers is also appended, in full, to a
per-league immutable journal (`trade_journal.py`): `nfl_trade_journal.db` and
`mlb_trade_journal.db`. Sells are included and every market type the stream
delivers is recorded; trades are deduplicated on the exchange's trade id, and
nothing is ever pruned. As of 2026-09-11 the stream had delivered no NFL or MLB
spread or total trade at all, although those markets are subscribed; the likely
cause, a per-connection subscription limit, is unconfirmed. It is
instrumentation only — raw capture keyed by Polymarket US event and market
slugs, with canonical-game linkage left to analysis time. Each journal's
coverage begins at its own `coverage_started_at`; nothing earlier was
backfilled, because the pruned display tape is not a record of what traded.
MLB full-flow coverage therefore starts later than the buy-only
`mlb_research.db` journal, and the two are separate coverage regimes that must
not be combined as if either were complete. Each stream start appends a
capture session, so outages show up as gaps. `python trade_journal.py status`
reports coverage and integrity for both.

## MLB Research Registry

`mlb_research.py` maintains a separate canonical MLB research registry backed
by structured MLB schedule/result identifiers. It preserves schedule revisions,
doubleheader identity, append-only moneyline executions, source-link rejections,
and immutable sportsbook snapshots. Pruned tape rows are copied in as
`LEGACY_INCOMPLETE` when the tape starts and every 30 minutes, and are excluded
from authoritative research totals. Since live journaling began, each of them
duplicates a live row (all 1,064 did on 2026-09-11), so any direct query of
`mlb_trade_observations` must filter `legacy_incomplete = 0`.

```powershell
python mlb_research.py sync-schedule
python mlb_research.py sync-odds
python mlb_research.py sync-all
python mlb_research.py migrate-legacy
python mlb_research.py summary
python mlb_research.py status
```

The human-readable evidence page is at
<http://127.0.0.1:8766/mlb-research>. It exposes missing evidence rather than
inferring starts, favorites, winners, or deleted legacy trades. Descriptive
price and concentration buckets are research summaries, not strategy rules.

MLB activity continues to use `big_money_tape.py` as its stream and storage
backend. The old “Big Money Tape” UI is retired; the backend remains active.
NFL activity is attached only through canonical game UUIDs. Unmatched trades
are rejected and journaled rather than guessed.

## NFL Research Registry

Development and production data are deliberately separate:

- `sports_registry.db` — development fixtures and provenance.
- `sports_registry_production.db` — production schedule, observations, source
  links, Game Flow activity, results, simulations, research summaries,
  notification journal, and workflow history.

Always select the environment explicitly:

```powershell
python nfl_schedule.py status --env production
python nfl_schedule.py sync --env production
python nfl_schedule.py link-odds --env production
python nfl_schedule.py link-polymarket --env production
```

External records require exact canonical teams, compatible home/away
orientation, league, season type, kickoff tolerance, identifiers, and market
type. Ambiguous or conflicting records remain rejected observations.

The active edge research is described in `README_EDGE_FINDER.md`. It calculates
only after both sources link to the identical canonical game UUID. Its
threshold is an unvalidated research/display parameter, not a strategy claim.

## Research Summaries

Every verified FINAL NFL game can produce an immutable, revisioned case study.
Market evidence and simulation results are never overwritten; corrected
evidence creates a new revision. Analyst notes are stored separately as
append-only revisions. Missing evidence remains visibly missing rather than
being reconstructed or inferred from prices.

## Paper Accounting

`paper_positions.json` is the single canonical paper ledger. It uses atomic
writes, UUID positions, duplicate prevention, cash/equity reconciliation,
authoritative settlement, and idempotent win/loss/void processing.

```powershell
python paper_trader.py status
python paper_trader.py history
python paper_trader.py settle
```

The workflow may settle already-existing simulated positions. It does not open
new positions. Paper totals are never mixed with real-position totals.

## Telegram

Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. If the chat ID
is unknown, message the configured bot and run:

```powershell
python telegram_setup.py discover-chat
```

Safe previews do not send or journal delivery attempts:

```powershell
python telegram_notification_center.py morning --preview
python telegram_notification_center.py pregame --due --preview
python telegram_notification_center.py finals --due --preview
python telegram_notification_center.py warnings --preview
```

Production sends are deduplicated by reporting date, canonical game UUID,
research revision, or warning cooldown. Telegram failure cannot block result
ingestion, research materialization, or settlement.

## Automation

The canonical production workflow is:

```powershell
python nfl_daily_update.py --dry-run
python nfl_daily_update.py --no-telegram
python nfl_daily_update.py
python nfl_daily_update.py status
```

Each independent step is journaled. One failed source preserves prior data and
does not stop unrelated work. Successful production runs atomically checkpoint
their run UUID, completion time, status, and duration in
`.runtime/nfl_workflow_state.json`; dry runs do not count as production
successes.

Install or update the supported hourly Windows task:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task_scheduler.ps1
```

Remove it with:

```powershell
powershell -ExecutionPolicy Bypass -File .\remove_task_scheduler.ps1
```

The standard task runs while this Windows user is logged in; the dashboard
does not need to be open. Fully logged-out execution requires an elevated S4U
registration. Logs rotate under `logs/workflow.log`.

## Health Check

```powershell
python health_check.py
python health_check.py --json
```

The report checks the registry, schema, paper ledger, Telegram configuration,
timezone data, dashboard assets, research support, Task Scheduler, workflow
lock/log, and the actual last successful production run. Critical failures
return a nonzero exit code; optional configuration is reported as a warning.

## Development vs production data

Source is tracked by Git. Runtime databases, JSON state, logs, secrets, caches,
WAL files, backups, generated dashboard snapshots, and operational checkpoints
are excluded by `.gitignore`.

Never delete or replace the production registry, paper ledger, notification
journal, research summaries, analyst notes, workflow history, Game Flow
history, real-position state, or backups as a cleanup shortcut.

## Archived experiments

Retired code is preserved under `archive/` with subsystem READMEs:

- `archive/exploration/` — one-off API and wallet investigations.
- `archive/whale_watch/` — disabled whale analysis and scanner research.
- `archive/legacy_operations/` — superseded daily update, report, status,
  stream listener, and launcher.
- `archive/legacy_paper/` — superseded manual paper tracker.
- `archive/old-dashboard/` — prior dashboard implementations.
- `archive/docs/` and `archive/scripts/` — historical notes and experiments.

Archived modules are not imported, launched, or scheduled by production. No
performance claim should be based on retired whale or legacy scanner research.

## Tests

```powershell
python -m unittest discover -v
node test_game_flow_navigation.js
python -m py_compile *.py
```

The full system test performs configured read-only API checks:

```powershell
python test_all_systems.py
```
