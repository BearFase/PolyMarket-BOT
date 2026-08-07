#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Get current odds for England and Argentina to win World Cup"""

import requests

GAMMA = "https://gamma-api.polymarket.com"

markets = {
    "England": "will-england-win-the-2026-fifa-world-cup-937",
    "Argentina": "will-argentina-win-the-2026-fifa-world-cup-245",
    "Spain": "will-spain-win-the-2026-fifa-world-cup-963"
}

print("\n=== World Cup Winner Odds (Pre-Semifinal) ===\n")

for country, slug in markets.items():
    try:
        r = requests.get(f"{GAMMA}/markets", params={"slug": slug}, timeout=10)
        data = r.json()
        
        if data:
            market = data[0]
            volume = float(market.get('volume', 0))
            
            # Try to get Yes price
            tokens = market.get('tokens', [])
            if tokens:
                for token in tokens:
                    if token.get('outcome') == 'Yes':
                        price = float(token.get('price', 0))
                        print(f"{country:12} {price*100:5.1f}%   (${volume/1e6:.1f}M volume)")
                        break
            else:
                # Binary market
                price = float(market.get('price', 0.5))
                print(f"{country:12} {price*100:5.1f}%   (${volume/1e6:.1f}M volume)")
    
    except Exception as e:
        print(f"{country}: Error - {e}")

print("\n" + "="*50)
print("\nContext: England vs Argentina semifinal in 40 min")
print("Winner plays Spain (or other semifinal winner) in final\n")
