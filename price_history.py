"""
Price history logger for open positions.

Called from sync_positions_api.sync_positions() after each sync, so every
60s server cycle appends one point per open position to price_history.json:

    { "<event_slug>": [ {"t": iso_utc, "price": 0.413, "pnl": -1.93}, ... ] }

The dashboard reads this to draw the live price line on each position card.
Safe by design: dedupes double-calls within ~20s, prunes points older than
7 days, caps each series at 5000 points, and shrugs off a missing or
corrupt file (starts fresh rather than crashing the sync).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY_FILE = Path(__file__).parent / "price_history.json"
DEDUPE_SECONDS = 20      # ignore a second snapshot within this window
MAX_AGE_DAYS = 7         # drop points older than this
MAX_POINTS = 5000        # hard cap per series


def _load():
    """Load the history file; return {} on missing/corrupt/wrong-shape."""
    if not HISTORY_FILE.exists():
        return {}
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_t(iso):
    """Parse an ISO timestamp; always return an aware UTC datetime or None."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def append_snapshot(positions):
    """Append one price point per open position (list of parsed position
    dicts from sync_positions_api). Returns the updated history dict."""
    history = _load()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff = now - timedelta(days=MAX_AGE_DAYS)

    for p in positions or []:
        slug = p.get("event_slug") or p.get("id") or "unknown"
        series = history.get(slug)
        if not isinstance(series, list):
            series = []

        # Dedupe: skip if we already logged this series moments ago.
        if series:
            last_t = _parse_t(series[-1].get("t", "")) if isinstance(series[-1], dict) else None
            if last_t and (now - last_t).total_seconds() < DEDUPE_SECONDS:
                continue

        series.append({
            "t": now_iso,
            "price": round(float(p.get("current_price") or 0), 4),
            "pnl": round(float(p.get("pnl") or 0), 2),
        })
        history[slug] = series

    # Prune every series (including ones no longer open) and cap length.
    for slug in list(history.keys()):
        series = history[slug]
        if not isinstance(series, list):
            del history[slug]
            continue
        kept = []
        for pt in series:
            if not isinstance(pt, dict):
                continue
            t = _parse_t(pt.get("t", ""))
            if t and t >= cutoff:
                kept.append(pt)
        if kept:
            history[slug] = kept[-MAX_POINTS:]
        else:
            del history[slug]

    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return history


if __name__ == "__main__":
    h = _load()
    for slug, series in h.items():
        print(f"{slug}: {len(series)} points"
              + (f" ({series[0]['t']} -> {series[-1]['t']})" if series else ""))
