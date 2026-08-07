# Archived legacy paper interface

`position_tracker.py` exposed an older manual position interface spanning the
former paper architecture. It was retired after `paper_trader.py` became the
single canonical, atomic paper ledger and settlement engine.

The code is retained for provenance only. Existing `paper_positions.json`,
legacy `paper_state.json`, and all backups remain preserved in the project
root as ignored runtime history.
