"""
Position Sync System - Polymarket US API
Fetches real positions and updates real_positions.json

Side and P&L are derived ONLY from the exchange ledger (qtyBought/qtySold,
netPosition). No manual overrides — if the numbers here disagree with what
the app shows, trust neither blindly: check the app's position screen and
compare against the 'scenarios' block this script writes out.
"""

import os
import json
import time
import base64
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()

API_KEY_ID = os.getenv("POLYMARKET_API_KEY")
API_SECRET = os.getenv("POLYMARKET_API_SECRET")
POSITIONS_FILE = "real_positions.json"
AUDIT_LOG = "position_audit.log"

def create_auth_headers(method, path):
    """Create authenticated headers for Polymarket US API"""
    private_key_bytes = base64.b64decode(API_SECRET)[:32]
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}"
    signature = base64.b64encode(private_key.sign(message.encode())).decode()
    return {
        "X-PM-Access-Key": API_KEY_ID,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature
    }

def fetch_positions_from_api():
    """Fetch current positions from Polymarket US API"""
    path = "/v1/portfolio/positions"
    url = f"https://api.polymarket.us{path}"
    headers = create_auth_headers("GET", path)
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API error: {response.status_code} - {response.text[:200]}")

def fetch_balances():
    """Raw live balance fields from the exchange.

    The US app labels ``buyingPower`` as cash. ``currentBalance`` is a risk
    ledger value and includes position margin, so it must not be shown as
    cash or portfolio equity.
    """
    path = "/v1/account/balances"
    r = requests.get(f"https://api.polymarket.us{path}",
                     headers=create_auth_headers("GET", path), timeout=10)
    if r.status_code == 200:
        b = (r.json().get("balances") or [{}])[0]
        return {
            "ledger_balance": round(float(b.get("currentBalance", 0)), 4),
            "cash": round(float(b.get("buyingPower", 0)), 4),
            "buying_power": round(float(b.get("buyingPower", 0)), 4),
            "margin_requirement": round(float(b.get("marginRequirement", 0)), 4),
            "open_orders": round(float(b.get("openOrders", 0)), 4),
            "unsettled_funds": round(float(b.get("unsettledFunds", 0)), 4),
        }
    return {}


def _money(value):
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def summarize_activities(activities):
    """Return net completed funding and display metadata for open markets."""
    net_contributions = 0.0
    market_context = {}
    for activity in activities or []:
        kind = activity.get("type", "")
        if kind in {
            "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
            "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT",
            "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL",
        }:
            change = activity.get("accountBalanceChange", {}) or {}
            if change.get("status") != "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED":
                continue
            amount = _money(change.get("amount"))
            net_contributions += -amount if "WITHDRAWAL" in kind else amount
            continue
        if kind != "ACTIVITY_TYPE_TRADE":
            continue
        trade = activity.get("trade", {}) or {}
        slug = trade.get("marketSlug")
        if not slug or slug in market_context:
            continue
        order = trade.get("aggressor") or trade.get("passive") or {}
        execution = trade.get("aggressorExecution") or trade.get("passiveExecution") or {}
        order = execution.get("order") or order
        outcome_side = (order.get("outcomeSide") or "").replace("OUTCOME_SIDE_", "").title()
        market = trade.get("market", {}) or {}
        market_context[slug] = {
            "selection": outcome_side,
            "question": market.get("question", ""),
        }
    return round(net_contributions, 4), market_context


def load_existing_positions():
    """Load existing positions from file"""
    if not os.path.exists(POSITIONS_FILE):
        return {"positions": [], "closed": [], "total_pnl": 0.0}

    with open(POSITIONS_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)

def log_audit(message):
    """Log to audit file with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")

def parse_position(slug, pos, position_id, market_context=None):
    """Convert one raw API position into our tracked format.

    Polymarket US moneyline semantics (verified 2026-07-18 against the order
    fill record for the ESP-ARG position — see archive notes):
      - marketMetadata.outcome names the team YOUR money is on. The app is
        pick-a-team style; every open position backs its named outcome.
      - netPosition's SIGN is instrument bookkeeping, not direction. Each
        moneyline is one instrument whose "long side" is one team; betting
        the other team is recorded as a negative/short net position on the
        instrument (order shows action=BUY even when side=SELL).
      - cashValue is your stake valued at YOUR team's current price, so
        pnl = cashValue - cost for every position.
      - Payout: qty shares pay $1 each if your team wins; $0 if it loses.
    Do NOT branch bet direction on the netPosition sign.
    """
    meta = pos.get("marketMetadata", {})
    net_pos = float(pos.get("netPositionDecimal", pos.get("netPosition", "0")))
    qty = abs(net_pos)
    cost = float(pos.get("cost", {}).get("value", "0"))
    cash_value = float(pos.get("cashValue", {}).get("value", "0"))
    fees = float(pos.get("fees", {}).get("value", "0"))

    market_title = meta.get('title', slug)
    team_color = (meta.get('team') or {}).get('colorPrimary', '')

    context = market_context or {}
    # Prefer the executed order's Yes/No selection. Position metadata names the
    # instrument label (e.g. Under), which can differ from what the app shows.
    subject = meta.get('subject', {})
    if context.get("selection"):
        outcome_name = context["selection"]
        question = context.get("question") or market_title
        bet_description = f"{outcome_name} — {question}"
    elif subject and subject.get('name'):
        outcome_name = subject.get('name')
        bet_description = f"Backing {outcome_name} to score"
    else:
        outcome_name = meta.get('outcome', 'Unknown')
        bet_description = f"Backing {outcome_name} to win"

    side = "BACKING"
    pnl = cash_value - cost
    pnl_if_wins = qty * 1.00 - cost      # shares pay $1 each
    pnl_if_loses = -cost                 # shares expire worthless

    entry_price = cost / qty if qty else 0   # effective price incl. fees
    current_price = cash_value / qty if qty else 0

    return {
        "id": f"real_{position_id:03d}",
        "market_slug": slug,
        "market": market_title,
        "outcome": outcome_name,
        "side": side,
        "entry_price": round(entry_price, 4),
        "current_price": round(current_price, 4),
        "contracts": qty,
        "size": cost,
        "cost_basis": cost,
        "current_value": round(cash_value, 2),
        "fees": fees,
        "pnl": round(pnl, 2),
        "scenarios": [
            {"scenario": f"{outcome_name} wins", "pnl": round(pnl_if_wins, 2)},
            {"scenario": f"{outcome_name} loses", "pnl": round(pnl_if_loses, 2)},
        ],
        "ledger": {
            "qty_bought": float(pos.get("qtyBoughtDecimal", "0")),
            "qty_sold": float(pos.get("qtySoldDecimal", "0")),
            "net_position": net_pos,
        },
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "team_color": team_color,
        "event_slug": meta.get("eventSlug", "unknown"),
        "bet_type": bet_description,
        "market_question": context.get("question", ""),
        "instrument_outcome": meta.get("outcome", ""),
        "selected_side": (context.get("selection") or
                          ("Yes" if net_pos >= 0 else "No")),
        "notes": f"Synced from API ledger. {bet_description}.",
    }

def sync_positions():
    """Main sync function"""
    print("[SYNC] Syncing positions from Polymarket US API...")
    log_audit("=== Position Sync Started ===")

    try:
        api_data = fetch_positions_from_api()
        positions_dict = api_data.get("positions", {})
    except Exception as e:
        error_msg = f"Failed to fetch from API: {e}"
        print(f"[ERROR] {error_msg}")
        log_audit(f"ERROR: {error_msg}")
        return

    existing_data = load_existing_positions()

    try:
        from settle_positions import fetch_activities
        activities = fetch_activities(max_pages=50)
    except Exception as e:
        log_audit(f"WARN: activity history fetch failed: {e}")
        activities = []
    net_contributions, market_context = summarize_activities(activities)

    # Auto-settle: book results for tracked positions that vanished from the
    # API (market resolved or position closed) BEFORE rebuilding the open list.
    try:
        from settle_positions import settle_missing
        settled = settle_missing(existing_data, positions_dict,
                                 fetch_activities_fn=lambda: activities)
        # A temporarily omitted position is not a closed position. Only an
        # exchange-confirmed resolution/close may remove it from the open list;
        # retain inconclusive entries at their last verified mark.
        deferred_ids = {entry.get("id") for entry in settled
                        if entry.get("result") == "UNKNOWN"}
        if deferred_ids:
            existing_data["closed"] = [
                entry for entry in existing_data.get("closed", [])
                if entry.get("id") not in deferred_ids
            ]
            settled = [entry for entry in settled
                       if entry.get("result") != "UNKNOWN"]
            log_audit(f"DEFERRED: {len(deferred_ids)} position(s) missing from "
                      "API without a closing trade or resolution")
        for entry in settled:
            log_audit(f"SETTLED: {entry.get('market')} | {entry.get('outcome')} "
                      f"| {entry.get('result')} | P&L ${entry.get('pnl', 0):+.2f}")
            print(f"[SETTLE] {entry.get('market')}: {entry.get('result')} "
                  f"(${entry.get('pnl', 0):+.2f})")
    except Exception as e:
        log_audit(f"WARN: settlement check failed: {e}")

    new_positions = []
    for i, (slug, pos) in enumerate(positions_dict.items(), start=1):
        p = parse_position(slug, pos, i, market_context.get(slug))
        new_positions.append(p)
        # Log parser path for validation (subject vs outcome)
        meta = pos.get("marketMetadata", {})
        parser_path = "subject" if meta.get("subject", {}).get("name") else "outcome"
        log_audit(f"Position: {p['market']} | {p['side']} {p['outcome']} | P&L: ${p['pnl']:.2f} [parsed via {parser_path}]")

    api_event_slugs = {p.get("event_slug") for p in new_positions}
    # If an API-omitted position reappears, remove any earlier inconclusive
    # fallback record so it is not counted twice in the local audit history.
    existing_data["closed"] = [
        entry for entry in existing_data.get("closed", [])
        if not (entry.get("result") == "UNKNOWN"
                and entry.get("event_slug") in api_event_slugs)
    ]
    for old in existing_data.get("positions", []):
        if old.get("id") in locals().get("deferred_ids", set()) \
                and old.get("event_slug") not in api_event_slugs:
            old = dict(old)
            old["stale"] = True
            old["status_note"] = "Temporarily missing from positions API; showing last verified mark."
            new_positions.append(old)

    try:  # log a price point per position for the dashboard chart
        from price_history import append_snapshot
        append_snapshot(new_positions)
    except Exception as e:
        log_audit(f"WARN: price history not recorded: {e}")

    total_open_pnl = sum(p["pnl"] for p in new_positions)

    try:
        account = fetch_balances()
    except Exception as e:
        log_audit(f"WARN: balance fetch failed: {e}")
        account = existing_data.get("account", {})

    position_value = round(sum(p["current_value"] for p in new_positions), 2)
    cash = float(account.get("cash", account.get("buying_power", 0)) or 0)
    equity = round(cash + position_value, 2)
    if activities:
        total_pnl = round(equity - net_contributions, 2)
    else:
        total_pnl = existing_data.get("total_pnl", 0)
        net_contributions = existing_data.get("account", {}).get("net_contributions", 0)
    realized_pnl = round(total_pnl - total_open_pnl, 2)
    account.update({
        "balance": round(cash, 2),
        "cash": round(cash, 2),
        "position_value": position_value,
        "equity": equity,
        "net_contributions": round(net_contributions, 2),
    })

    updated_data = {
        "positions": new_positions,
        "closed": existing_data.get("closed", []),
        "account": account,
        "total_pnl": round(total_pnl, 2),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": round(total_open_pnl, 2),
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "sync_source": "polymarket_us_api",
        "note": "Equity and all-time P&L are reconciled from exchange positions, buying power, and completed funding activity.",
    }

    with open(POSITIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(updated_data, f, indent=2)

    print(f"[OK] Synced {len(new_positions)} open positions")
    for p in new_positions:
        print(f"     {p['market']}: {p['side']} {p['outcome']} | P&L ${p['pnl']:+.2f}")
        for s in p["scenarios"]:
            print(f"       if {s['scenario']}: ${s['pnl']:+.2f}")
    print(f"[P&L] Total P&L: ${total_pnl:.2f}")
    log_audit(f"Sync complete. {len(new_positions)} positions, Total P&L: ${total_pnl:.2f}")
    log_audit("=== Position Sync Finished ===\n")

    return updated_data

if __name__ == "__main__":
    result = sync_positions()
    if result:
        from dashboard_data import build as build_dashboard_data
        build_dashboard_data()
        print(f"\n[SAVE] Updated {POSITIONS_FILE} + dashboard_data.js")
        print(f"[LOG] Audit log: {AUDIT_LOG}")
