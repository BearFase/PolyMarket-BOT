"""
Real-time position/order/balance stream from Polymarket US.

Connects to wss://api.polymarket.us/v1/ws/private (same Ed25519 auth as REST,
path "/v1/ws/private"), subscribes to ORDER + POSITION + ACCOUNT_BALANCE, and
triggers an immediate ledger sync + dashboard rebuild whenever an event lands.
The 60s polling loop in dashboard_server.py stays on as a safety net.

Run: python stream_listener.py   (started alongside the dashboard server)
"""
import json
import time
import threading
from datetime import datetime

import websocket  # websocket-client

from sync_positions_api import create_auth_headers, sync_positions
from dashboard_data import build as build_dashboard_data

WS_PATH = "/v1/ws/private"
WS_URL = f"wss://api.polymarket.us{WS_PATH}"
LOG_FILE = "stream.log"

_sync_requested = threading.Event()


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line.encode("ascii", "replace").decode())
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def sync_worker():
    """Debounced sync: at most one ledger sync per 3s no matter how many
    events arrive in a burst (a single order can fire several messages)."""
    while True:
        _sync_requested.wait()
        time.sleep(3)  # let the burst finish
        _sync_requested.clear()
        try:
            sync_positions()
            build_dashboard_data()
            log("[OK] event-driven sync complete")
        except Exception as e:
            log(f"[ERROR] event-driven sync failed: {e}")


def subscriptions():
    """Subscribe messages per docs (camelCase, string enums)."""
    return [
        {"subscribe": {"requestId": "pos-1",
                       "subscriptionType": "SUBSCRIPTION_TYPE_POSITION",
                       "marketSlugs": []}},
        {"subscribe": {"requestId": "ord-1",
                       "subscriptionType": "SUBSCRIPTION_TYPE_ORDER",
                       "marketSlugs": []}},
        {"subscribe": {"requestId": "bal-1",
                       "subscriptionType": "SUBSCRIPTION_TYPE_ACCOUNT_BALANCE"}},
    ]


def on_open(ws):
    log("connected; subscribing to positions, orders, balances")
    for sub in subscriptions():
        ws.send(json.dumps(sub))


def on_message(ws, raw):
    try:
        msg = json.loads(raw)
    except Exception:
        return
    if "heartbeat" in msg:
        return
    if msg.get("error"):
        log(f"[WARN] subscription error: {msg['error']}")
        return

    # snapshots just confirm the stream is live; updates trigger a sync
    for key in ("orderSubscriptionSnapshot", "accountBalancesSnapshot"):
        if key in msg:
            log(f"snapshot received: {key} (stream live)")
            return

    for key in ("positionSubscription", "orderSubscriptionUpdate",
                "accountBalancesUpdate"):
        if key in msg:
            entry = msg[key].get("entryType", "")
            log(f"EVENT: {key} {entry}")
            _sync_requested.set()
            return


def on_error(ws, err):
    log(f"[WARN] socket error: {err}")


def run():
    threading.Thread(target=sync_worker, daemon=True).start()
    backoff = 2
    while True:
        try:
            headers = create_auth_headers("GET", WS_PATH)
            ws = websocket.WebSocketApp(
                WS_URL,
                header=[f"{k}: {v}" for k, v in headers.items()],
                on_open=on_open, on_message=on_message, on_error=on_error)
            log(f"connecting to {WS_URL} ...")
            ws.run_forever(ping_interval=25, ping_timeout=10)
            log("disconnected")
            backoff = 2  # clean disconnect: quick retry
        except Exception as e:
            log(f"[ERROR] connection failed: {e}")
            backoff = min(backoff * 2, 120)
        time.sleep(backoff)


if __name__ == "__main__":
    run()
