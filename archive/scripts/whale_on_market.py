#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check whale activity on specific market
"""

import sys
import time
import requests
from polymarket_consensus_v2 import get_alltime_top, last_trade_ts

GAMMA = "https://gamma-api.polymarket.com"

slug = sys.argv[1] if len(sys.argv) > 1 else "will-england-win-the-2026-fifa-world-cup-937"

print(f"\n=== Checking Whale Activity: {slug} ===\n")

# Get market details
try:
    r = requests.get(f"{GAMMA}/markets", params={"slug": slug}, timeout=10)
    markets = r.json()
    
    if not markets:
        print("Market not found")
        sys.exit(1)
    
    market = markets[0]
    question = market.get('question')
    condition_id = market.get('conditionId')
    
    print(f"Market: {question}")
    print(f"Volume: ${float(market.get('volume', 0)):,.0f}")
    
    # Get current price
    tokens = market.get('tokens', [])
    if tokens:
        for token in tokens:
            outcome = token.get('outcome')
            price = float(token.get('price', 0))
            print(f"\nCurrent odds: {outcome} = {price*100:.1f}%")
    
    print(f"\nCondition ID: {condition_id}")
    
except Exception as e:
    print(f"Error fetching market: {e}")
    sys.exit(1)

# Now check whale positions on this market
print("\n" + "="*60)
print("Checking top whale positions...")
print("="*60 + "\n")

kept, _ = get_alltime_top(15, min_roi=0.02)

# Check recent activity
cutoff = time.time() - 48 * 3600  # Last 48h

whale_positions = []

for t, roi in kept[:10]:  # Top 10 whales
    name = t.get("userName") or t["proxyWallet"][:10]
    wallet = t["proxyWallet"]
    pnl = float(t.get("pnl", 0))
    
    try:
        # Check if they've traded recently
        ts = last_trade_ts(wallet)
        recently_active = ts >= cutoff
        
        # Get their positions
        positions_r = requests.get(
            "https://data-api.polymarket.com/positions",
            params={"user": wallet, "sortBy": "CURRENT", "limit": 100},
            timeout=10
        )
        
        if positions_r.status_code == 200:
            positions = positions_r.json()
            
            # Find positions on this specific market
            for p in positions:
                if p.get('conditionId') == condition_id:
                    value = float(p.get('currentValue', 0))
                    if value > 100:  # Only significant positions
                        whale_positions.append({
                            'name': name,
                            'wallet': wallet,
                            'pnl': pnl,
                            'roi': roi,
                            'outcome': p.get('outcome'),
                            'entry_price': float(p.get('avgPrice', 0)),
                            'current_price': float(p.get('curPrice', 0)),
                            'value': value,
                            'recently_active': recently_active
                        })
        
        time.sleep(0.5)
        
    except Exception as e:
        print(f"[warn] {name}: {e}")

# Show results
if not whale_positions:
    print("\nNo significant whale positions found on this market.")
    print("(This might mean the market isn't live yet, or whales aren't positioned)")
else:
    print(f"\n🐋 Found {len(whale_positions)} whale position(s):\n")
    
    for wp in sorted(whale_positions, key=lambda x: -x['value']):
        active_mark = " [ACTIVE 48h]" if wp['recently_active'] else ""
        print(f"{wp['name']}{active_mark}")
        print(f"  All-time: ${wp['pnl']:,.0f} ({wp['roi']*100:.0f}% ROI)")
        print(f"  Position: {wp['outcome']}")
        print(f"  Entry: {wp['entry_price']*100:.1f}% → Current: {wp['current_price']*100:.1f}%")
        print(f"  Value: ${wp['value']:,.0f}")
        print()

print()
