#!/usr/bin/env python3
"""
Polymarket Consensus Tracker v2 — "proven whales" edition

Strategy:
 1. Pull the ALL-TIME top 25 traders by profit
 2. (Optional) filter out market makers (huge volume, tiny ROI — their
    positions are inventory, not opinions)
 3. Keep only traders who actually traded in the last N hours
 4. Take the top 5 of those (by all-time PnL)
 5. Compare their CURRENT OPEN positions on markets that haven't
    resolved yet — flag any market+side that min-overlap+ of them share

Usage:
 python3 polymarket_consensus_v2.py
 python3 polymarket_consensus_v2.py --pool 25 --active 5 --min-overlap 3 --hours 24
 python3 polymarket_consensus_v2.py --min-roi 0  # keep market makers too

No API key needed.
"""

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

BASE = "https://data-api.polymarket.com"
HEADERS = {"User-Agent": "consensus-tracker/2.0"}


def api(path, **params):
    r = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_alltime_top(pool=25, min_roi=0.02):
    board = api("/v1/leaderboard", timePeriod="ALL", orderBy="PNL", limit=min(pool, 50))
    kept, skipped = [], []
    for t in board:
        vol, pnl = float(t.get("vol") or 0), float(t.get("pnl") or 0)
        roi = (pnl / vol) if vol > 0 else 1.0
        (kept if roi >= min_roi else skipped).append((t, roi))
    return kept, skipped


def last_trade_ts(wallet):
    """Timestamp of the most recent trade, or 0."""
    trades = api("/activity", user=wallet, type="TRADE", limit=1)
    return trades[0].get("timestamp", 0) if trades else 0


def open_positions(wallet):
    """Current positions on markets that haven't resolved."""
    positions = api("/positions", user=wallet, sortBy="CURRENT", limit=100)
    now = datetime.now(timezone.utc)
    out = []
    for p in positions:
        if p.get("redeemable"):  # market already resolved
            continue
        cur = float(p.get("curPrice") or 0)
        if cur <= 0.01 or cur >= 0.99:  # effectively decided
            continue
        end = p.get("endDate")
        if end:
            try:
                end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                # Ensure end_dt has timezone info
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if end_dt < now:
                    continue  # event already ended, awaiting resolution
            except (ValueError, AttributeError):
                pass
        out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=25, help="all-time leaderboard depth")
    ap.add_argument("--active", type=int, default=5, help="how many active whales to track")
    ap.add_argument("--min-overlap", type=int, default=3, help="min whales on same side")
    ap.add_argument("--hours", type=int, default=24, help="'active' = traded within N hours")
    ap.add_argument("--min-roi", type=float, default=0.02,
                    help="min all-time pnl/volume; filters market makers (0 to disable)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    print(f"=== Polymarket Whale Consensus v2 — {datetime.now():%Y-%m-%d %H:%M} ===\n")

    kept, skipped = get_alltime_top(args.pool, args.min_roi)
    if skipped:
        names = ", ".join(t.get("userName") or t["proxyWallet"][:8] for t, _ in skipped)
        print(f"Filtered as likely market makers (ROI < {args.min_roi:.0%}): {names}\n")

    cutoff = time.time() - args.hours * 3600
    active = []
    print(f"Checking activity for {len(kept)} all-time leaders...")
    for t, roi in kept:
        name = t.get("userName") or t["proxyWallet"][:10]
        try:
            ts = last_trade_ts(t["proxyWallet"])
        except Exception as e:
            print(f" [warn] {name}: {e}")
            continue
        mark = "ACTIVE" if ts >= cutoff else "quiet"
        print(f" {name:<28} pnl ${float(t['pnl']):>13,.0f} roi {roi:>5.1%} {mark}")
        if ts >= cutoff:
            active.append(t)
        if len(active) >= args.active:
            break  # leaderboard is already sorted by pnl
        time.sleep(0.4)

    if len(active) < args.min_overlap:
        print(f"\nOnly {len(active)} whales active in the last {args.hours}h — "
              f"not enough for a {args.min_overlap}-way consensus. Try --hours 72.")
        return

    print(f"\nTracking {len(active)} active whales. Pulling open positions...\n")

    groups = defaultdict(dict)  # (conditionId, outcome) -> {name: position}
    for t in active:
        name = t.get("userName") or t["proxyWallet"][:10]
        try:
            for p in open_positions(t["proxyWallet"]):
                key = (p.get("conditionId"), p.get("outcome"))
                groups[key][name] = p
        except Exception as e:
            print(f" [warn] positions for {name}: {e}")
        time.sleep(0.4)

    hits = []
    for key, by in groups.items():
        if len(by) >= args.min_overlap:
            sample = next(iter(by.values()))
            hits.append({
                "market": sample.get("title", "?"),
                "outcome": sample.get("outcome", "?"),
                "current_price": float(sample.get("curPrice") or 0),
                "ends": sample.get("endDate", ""),
                "url": f"https://polymarket.com/event/{sample.get('eventSlug','')}",
                "overlap": len(by),
                "traders": {
                    n: {"avg_entry": round(float(p.get("avgPrice") or 0), 3),
                        "value_usd": round(float(p.get("currentValue") or 0), 2)}
                    for n, p in by.items()
                },
            })
    hits.sort(key=lambda h: -h["overlap"])

    if args.json:
        print(json.dumps(hits, indent=2))
        return
    if not hits:
        print(f"No unresolved market where {args.min_overlap}+ of these whales "
              f"hold the same side. (Normal — real consensus is rare. That's the point.)")
        return

    print(f"WHALE CONSENSUS ({args.min_overlap}+ on same market & side, unresolved):\n")
    for h in hits:
        print(f"● {h['market']} → {h['outcome']}")
        print(f"  now {h['current_price']*100:.0f}¢ | ends {h['ends'] or '?'} | "
              f"{h['overlap']}/{len(active)} whales | {h['url']}")
        for n, d in h["traders"].items():
            print(f"    {n}: in @ {d['avg_entry']*100:.0f}¢, holding ${d['value_usd']:,.0f}")
        print()


if __name__ == "__main__":
    main()
