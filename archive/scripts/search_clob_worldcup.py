#!/usr/bin/env python3
"""
Search CLOB API for World Cup markets
"""

import requests
import json

print("="*80)
print("SEARCHING CLOB API FOR WORLD CUP MARKETS")
print("="*80)

CLOB_BASE = "https://clob.polymarket.com"

# Get all markets with pagination
all_markets = []
next_cursor = None
page = 1

print("\nFetching markets...")
while True:
    params = {"limit": 100}
    if next_cursor:
        params["next_cursor"] = next_cursor
    
    response = requests.get(f"{CLOB_BASE}/markets", params=params)
    
    if response.status_code != 200:
        print(f"Error {response.status_code}")
        break
    
    data = response.json()
    markets = data.get("data", [])
    all_markets.extend(markets)
    
    print(f"  Page {page}: {len(markets)} markets (total: {len(all_markets)})")
    
    next_cursor = data.get("next_cursor")
    if not next_cursor or page >= 20:  # Stop after 20 pages or when done
        break
    
    page += 1

print(f"\nTotal markets fetched: {len(all_markets)}")

# Search for World Cup keywords
keywords = ["world cup", "fwc", "fifa", "france", "england", "argentina", "spain"]

wc_markets = []
for m in all_markets:
    question = m.get("question", "").lower()
    description = m.get("description", "").lower()
    
    if any(kw in question or kw in description for kw in keywords):
        wc_markets.append(m)

print(f"\n" + "="*80)
print(f"WORLD CUP MARKETS FOUND: {len(wc_markets)}")
print("="*80)

if wc_markets:
    for i, m in enumerate(wc_markets, 1):
        print(f"\n[{i}] {m.get('question', 'N/A')}")
        print(f"    Description: {m.get('description', 'N/A')[:100]}")
        print(f"    Active: {m.get('active')}")
        print(f"    Closed: {m.get('closed')}")
        print(f"    Condition ID: {m.get('condition_id', 'N/A')}")
        
        # Check if it's France vs England
        q_lower = m.get("question", "").lower()
        if ("france" in q_lower and "england" in q_lower) or \
           ("fra" in q_lower and "eng" in q_lower):
            print("    *** THIS IS FRANCE VS ENGLAND! ***")
            print(f"\n    FULL MARKET DATA:")
            print(json.dumps(m, indent=2))
else:
    print("\nNo World Cup markets found in CLOB API either.")
    print("\nShowing sample of what markets look like:")
    for m in all_markets[:3]:
        print(f"\n{m.get('question', 'N/A')}")

print("\n" + "="*80)
