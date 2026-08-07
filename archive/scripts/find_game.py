#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find specific game on Polymarket by scraping their site
"""

import requests
import sys

# Try using gamma API which is more stable
GAMMA_API = "https://gamma-api.polymarket.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "england"

print(f"\nSearching for: {query}\n")

try:
    # Try to get all markets
    r = requests.get(
        f"{GAMMA_API}/markets",
        headers=HEADERS,
        params={"closed": "false", "limit": 100},
        timeout=15
    )
    
    if r.status_code == 200:
        markets = r.json()
        
        query_lower = query.lower()
        matches = []
        
        for m in markets:
            question = m.get("question", "").lower()
            description = m.get("description", "").lower()
            
            if query_lower in question or query_lower in description:
                matches.append(m)
        
        if not matches:
            print("No active markets found for that query.")
            print("\nTrying 'football' or 'soccer'...")
            
            # Try sports
            for m in markets:
                q = m.get("question", "").lower()
                if "football" in q or "soccer" in q or "match" in q:
                    matches.append(m)
                    if len(matches) >= 10:
                        break
        
        if matches:
            print(f"Found {len(matches)} market(s):\n")
            for i, m in enumerate(matches[:10], 1):
                print(f"{i}. {m.get('question', '?')}")
                print(f"   Current odds:")
                
                # Get outcome tokens
                outcomes = m.get("outcomes", [])
                if outcomes:
                    for outcome in outcomes:
                        price = float(m.get("outcomePrices", [0.5, 0.5])[outcomes.index(outcome)])
                        print(f"     {outcome}: {price*100:.0f}%")
                else:
                    # Binary market
                    print(f"     Yes: {float(m.get('price', 0.5))*100:.0f}%")
                    print(f"     No: {(1-float(m.get('price', 0.5)))*100:.0f}%")
                
                print(f"   Volume: ${float(m.get('volume', 0)):,.0f}")
                print(f"   https://polymarket.com/event/{m.get('slug', '')}")
                print()
        else:
            print("No matches found.")
    else:
        print(f"API Error: {r.status_code}")
        print("Polymarket API might be down or changed.")

except Exception as e:
    print(f"[ERROR] {e}")
    print("\nCouldn't fetch market data. Try checking Polymarket.com directly.")
