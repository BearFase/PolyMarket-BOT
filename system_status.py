"""Atomic operational status shared by the local dashboard services.

This module contains no trading behavior. It only records timestamps, a
sanitized error summary, and the public trade-stream connection state.
"""
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
STATUS_FILE = HERE / "system_status.json"
_lock = threading.RLock()

STALE_AFTER_SECONDS = {
    "position_sync": 3 * 60,
    "market_discovery": 35 * 60,
    "edge_scan": 7 * 60 * 60,
    "last_trade": 30 * 60,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _defaults():
    return {
        "stream": {"state": "disconnected", "updated_at": None},
        "last_trade_at": None,
        "last_position_sync_at": None,
        "last_market_discovery_at": None,
        "last_edge_scan_at": None,
        "last_error": None,
    }


def _safe_error(message):
    """Keep browser-facing errors short and free of multiline trace output."""
    text = " ".join(str(message).split())
    text = re.sub(
        r"(?i)\b(api[_ -]?key|secret|token|authorization)\b\s*[:=]\s*\S+",
        r"\1=[redacted]", text)
    return text[:240]


def read_status(path=STATUS_FILE):
    data = _defaults()
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    except (OSError, ValueError, TypeError):
        pass
    return data


def write_status(data, path=STATUS_FILE):
    """Atomically replace the JSON file so readers never see partial output."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    with _lock:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def update_status(path=STATUS_FILE, **changes):
    with _lock:
        data = read_status(path)
        data.update(changes)
        write_status(data, path)
    return data


def set_stream_state(state, error=None, path=STATUS_FILE):
    now = _now()
    with _lock:
        data = read_status(path)
        data["stream"] = {"state": state, "updated_at": now}
        if error:
            data["last_error"] = {
                "component": "trade_stream",
                "message": _safe_error(error),
                "at": now,
            }
        write_status(data, path)


def mark_success(component, at=None, path=STATUS_FILE):
    field = {
        "trade": "last_trade_at",
        "position_sync": "last_position_sync_at",
        "market_discovery": "last_market_discovery_at",
        "edge_scan": "last_edge_scan_at",
    }[component]
    update_status(path=path, **{field: at or _now()})


def mark_error(component, message, path=STATUS_FILE):
    update_status(path=path, last_error={
        "component": component,
        "message": _safe_error(message),
        "at": _now(),
    })


def _age_seconds(value, now):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return max(0, (now - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def dashboard_status(path=STATUS_FILE, now=None):
    """Return sanitized state plus health classifications for the UI."""
    raw = read_status(path)
    current = now or datetime.now(timezone.utc)
    services = {}
    stream = raw.get("stream") or {}
    stream_state = stream.get("state", "disconnected")
    services["trade_stream"] = {
        "state": "healthy" if stream_state == "connected" else "disconnected",
        "detail": stream_state,
        "timestamp": stream.get("updated_at"),
    }
    for component, label in (
        ("position_sync", "last_position_sync_at"),
        ("market_discovery", "last_market_discovery_at"),
        ("edge_scan", "last_edge_scan_at"),
    ):
        timestamp = raw.get(label)
        age = _age_seconds(timestamp, current)
        state = ("healthy" if age is not None
                 and age <= STALE_AFTER_SECONDS[component] else "stale")
        services[component] = {
            "state": state,
            "timestamp": timestamp,
            "age_seconds": round(age) if age is not None else None,
        }
    trade_age = _age_seconds(raw.get("last_trade_at"), current)
    services["last_trade"] = {
        "state": ("healthy" if trade_age is not None
                  and trade_age <= STALE_AFTER_SECONDS["last_trade"]
                  else "stale"),
        "timestamp": raw.get("last_trade_at"),
        "age_seconds": round(trade_age) if trade_age is not None else None,
    }
    return {
        "generated_at": current.isoformat(),
        "services": services,
        "last_error": raw.get("last_error"),
    }
