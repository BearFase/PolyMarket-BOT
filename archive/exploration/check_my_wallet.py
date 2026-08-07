#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check specific wallet positions
"""

import requests
import sys

if len(sys.argv) < 2:
    print("\nUsage: python check_my_wallet.py <wallet_address>")
    print("Example: python check_my_wallet.py 0x1234...abcd\n")
    sys.exit(1)

wallet = sys.argv[1]

print(f"\n=== Checking Wallet: {wallet} ===\n")

# Try Polymarket data API
try:
    r = requests.get(
        "https://data-api.polymarket.com/positions",
        params={'user': wallet, 'sortBy': 'CURRENT', 'limit': 50},
        timeout=10
    )
    
    print(f"API Response: {r.status_code}")
    
    if r.status_code == 200:
        positions = r.json()
        print(f"Found {len(positions)} positions\n")
        
        if not positions:
            print("No positions found via API.")
            print("\nPossible reasons:")
            print("1. This wallet has no open Polymarket positions")
            print("2. App is showing a DIFFERENT wallet")
            print("3. Positions are on a different network/version")
        else:
            for i, p in enumerate(positions, 1):
                print(f"{i}. {p.get('title', '?')}")
                print(f"   Outcome: {p.get('outcome', '?')}")
                print(f"   Value: ${float(p.get('currentValue', 0)):,.2f}")
                print(f"   Entry: {float(p.get('avgPrice', 0))*100:.1f}¢")
                print(f"   Current: {float(p.get('curPrice', 0))*100:.1f}¢")
                print()
    else:
        print(f"API Error: {r.status_code}")
        print(r.text)

except Exception as e:
    print(f"Error: {e}")

print("\n" + "="*60)
print("\nTo verify this is the right wallet:")
print("1. Open Polymarket app")
print("2. Go to your position")
print("3. Look for 'View on Explorer' or similar")
print("4. That should show the actual wallet holding the position")
print()
