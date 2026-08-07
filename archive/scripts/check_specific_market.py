#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check specific market by URL or slug
"""

import sys
import requests
import json

CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"

def check_market(slug_or_url):
    """Get market details and check for whale activity."""
    
    # Extract slug from URL if needed
    slug = slug_or_url.split('/')[-1] if '/' in slug_or_url else slug_or_url
    
    print(f"\nChecking market: {slug}\n")
    
    # Get market data
    try:
        r = requests.get(
            f"{GAMMA}/markets",
            params={"slug": slug},
            timeout=10
        )
        
        if r.status_code == 200:
            markets = r.json()
            if not markets:
                print("Market not found.")
                return
            
            market = markets[0]
            print(f"Market: {market.get('question')}")
            print(f"Volume: ${float(market.get('volume', 0)):,.0f}")
            print(f"Liquidity: ${float(market.get('liquidity', 0)):,.0f}")
            print()
            
            # Get price/odds
            tokens = market.get('tokens', [])
            if tokens:
                print("Current Odds:")
                for token in tokens:
                    outcome = token.get('outcome')
                    # Try to get price from CLOB
                    price = token.get('price', 0.5)
                    print(f"  {outcome}: {float(price)*100:.1f}%")
            
            print(f"\nURL: https://polymarket.com/event/{slug}")
            
        else:
            print(f"API error: {r.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")

# List all FIFA markets
print("\n=== Searching for FIFA/World Cup Markets ===\n")

try:
    r = requests.get(f"{GAMMA}/markets", params={"limit": 100}, timeout=15)
    if r.status_code == 200:
        all_markets = r.json()
        
        fifa_markets = [
            m for m in all_markets
            if any(term in m.get('question', '').lower() 
                   for term in ['fifa', 'world cup', 'england', 'argentina', 'semifinal'])
        ]
        
        print(f"Found {len(fifa_markets)} FIFA/World Cup related markets:\n")
        
        for i, m in enumerate(fifa_markets, 1):
            print(f"{i}. {m.get('question')}")
            print(f"   Slug: {m.get('slug')}")
            print(f"   Volume: ${float(m.get('volume', 0)):,.0f}")
            print()
            
except Exception as e:
    print(f"Error listing markets: {e}")
