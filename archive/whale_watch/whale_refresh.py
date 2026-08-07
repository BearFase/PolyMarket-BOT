"""
Refresh whale_data.json automatically (was previously a manual step).

Pulls the all-time top traders, keeps the ones active in the last 7 days,
grabs their significant open positions (>= $50k), and writes whale_data.json
in the exact shape the dashboard renders. Safe to call from a loop; all
failures leave the previous file untouched.
"""
import json
import time
from datetime import datetime

from polymarket_consensus_v2 import open_positions, get_alltime_top, last_trade_ts

OUT_FILE = "whale_data.json"
MIN_POSITION_SIZE = 50000
WINDOW_DAYS = 7


def refresh():
    kept, _ = get_alltime_top(25, 0.02)
    cutoff = time.time() - WINDOW_DAYS * 24 * 3600

    active = []
    for t, roi in kept:
        wallet = t["proxyWallet"]
        try:
            if last_trade_ts(wallet) >= cutoff:
                active.append(t)
        except Exception:
            continue
        time.sleep(0.3)  # be polite to the public API

    whales_out = []
    market_holders = {}
    total_value = 0

    for t in active:
        name = t.get("userName") or t["proxyWallet"][:10]
        wallet = t["proxyWallet"]
        entry = {
            "name": name,
            "wallet": wallet[:10] + "...",
            "all_time_pnl": round(float(t.get("pnl", 0))),
        }
        try:
            positions = open_positions(wallet)
        except Exception:
            positions = []

        significant = [p for p in positions
                       if float(p.get("currentValue", 0)) >= MIN_POSITION_SIZE]
        entry["open_positions"] = len(significant)
        if significant:
            entry["positions"] = []
            for p in significant:
                val = float(p.get("currentValue", 0))
                total_value += val
                title = p.get("title", "")
                market_holders.setdefault(title, set()).add(name)
                entry["positions"].append({
                    "market": title,
                    "outcome": p.get("outcome", ""),
                    "current_price": float(p.get("curPrice", 0)),
                    "entry_avg": float(p.get("avgPrice", 0)),
                    "value_usd": round(val),
                    "unrealized_pnl": round(float(p.get("cashPnl", 0))),
                    "unrealized_pnl_pct": round(float(p.get("percentPnl", 0)), 1),
                    "end_date": p.get("endDate", ""),
                    "url": f"https://polymarket.com/event/{p.get('eventSlug', '')}",
                })
        else:
            entry["note"] = (f"All positions <${MIN_POSITION_SIZE:,} (filtered out)"
                             if positions else "No open unresolved positions")
        whales_out.append(entry)
        time.sleep(0.3)

    consensus_markets = {m: sorted(names) for m, names in market_holders.items()
                         if len(names) >= 2}
    with_significant = sum(1 for w in whales_out if w.get("open_positions", 0) > 0)

    data = {
        "last_updated": datetime.now().astimezone().isoformat(),
        "time_window_days": WINDOW_DAYS,
        "active_whales": whales_out,
        "consensus": {
            "found": bool(consensus_markets),
            "min_required": 2,
            "markets": consensus_markets,
            "actual_with_significant_positions": with_significant,
        },
        "summary": {
            "total_whales_tracked": len(kept),
            "whales_with_significant_positions": with_significant,
            "total_position_value_over_50k": round(total_value),
        },
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"[OK] whale_data.json: {len(whales_out)} active whales, "
          f"{with_significant} with positions >= $50k")
    return data


if __name__ == "__main__":
    refresh()
