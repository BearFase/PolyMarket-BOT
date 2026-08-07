#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check specific whale positions
"""

import sys
import time
from polymarket_consensus_v2 import open_positions, get_alltime_top, last_trade_ts

print("\n=== Finding Active Whales (Last 7 Days) ===\n")

kept, _ = get_alltime_top(25, 0.02)

# Find whales active in last 168h (7 days)
cutoff = time.time() - 168 * 3600
active_whales = []

for t, roi in kept:
    name = t.get("userName") or t["proxyWallet"][:10]
    wallet = t["proxyWallet"]
    
    try:
        ts = last_trade_ts(wallet)
        if ts >= cutoff:
            active_whales.append((name, wallet, t))
            print(f"✓ {name} - last trade {int((time.time() - ts) / 3600)}h ago")
    except Exception as e:
        pass
    
    time.sleep(0.3)

print(f"\n=== Checking {len(active_whales)} Active Whale Positions ===\n")

# Filter threshold for meaningful positions
MIN_POSITION_SIZE = 50000  # $50k minimum

for name, wallet, trader_info in active_whales:
    pnl = float(trader_info.get("pnl", 0))
    print(f"\n{name}")
    print(f"  Wallet: {wallet[:10]}...")
    print(f"  All-time P&L: ${pnl:,.0f}")
    print("-" * 60)
    
    try:
        positions = open_positions(wallet)
        
        # Filter for significant positions only
        significant = [p for p in positions if float(p.get('currentValue', 0)) >= MIN_POSITION_SIZE]
        
        if not significant:
            if positions:
                print(f"  {len(positions)} position(s), but all <${MIN_POSITION_SIZE:,} (filtered out)")
            else:
                print("  (no open unresolved positions)")
        else:
            print(f"  {len(significant)} significant position(s) (>${MIN_POSITION_SIZE:,}):\n")
            for i, p in enumerate(significant, 1):
                current_val = float(p.get('currentValue', 0))
                entry_price = float(p.get('avgPrice', 0))
                current_price = float(p.get('curPrice', 0))
                
                # Calculate unrealized P&L
                if entry_price > 0 and current_price > 0:
                    shares = current_val / current_price if current_price > 0 else 0
                    cost_basis = shares * entry_price
                    pnl_usd = current_val - cost_basis
                    pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                else:
                    pnl_usd = 0
                    pnl_pct = 0
                
                print(f"  {i}. {p.get('title', '?')}")
                print(f"     Outcome:      {p.get('outcome', '?')}")
                print(f"     Current:      {current_price*100:.0f}¢")
                print(f"     Entry Avg:    {entry_price*100:.0f}¢")
                print(f"     Value:        ${current_val:,.0f}")
                print(f"     Unrealized:   ${pnl_usd:+,.0f} ({pnl_pct:+.1f}%)")
                print(f"     Ends:         {p.get('endDate', '?')}")
                print(f"     URL:          https://polymarket.com/event/{p.get('eventSlug', '')}")
                print()
    
    except Exception as e:
        print(f"  [ERROR] {e}")
    
    time.sleep(0.5)

print()
