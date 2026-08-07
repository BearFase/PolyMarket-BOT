"""
Bundles the bot's JSON state into dashboard_data.js so the dashboard renders
even when opened as a plain file (script tags load from file://, fetch doesn't).
Called after every sync; safe to run standalone: python dashboard_data.py
"""
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "dashboard_data.js"
SOURCES = {
    "real": "real_positions.json",
    "edges": "sports_edges.json",
    "history": "price_history.json",
}

def _load(name):
    p = HERE / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}

def build():
    bundle = {k: _load(v) for k, v in SOURCES.items()}
    bundle["generated"] = datetime.now(timezone.utc).isoformat()
    OUT.write_text("window.BOT_DATA = " + json.dumps(bundle) + ";\n", encoding="utf-8")
    return OUT

if __name__ == "__main__":
    print(f"[OK] wrote {build()}")
