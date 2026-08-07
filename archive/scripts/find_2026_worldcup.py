#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search for 2026 World Cup markets in CLOB API
"""

import requests
import json

print("="*80)
print("SEARCHING FOR 2026 WORLD CUP MARKETS")
print("="*80)

CLOB_BASE = "https://clob.polymarket.com"

# Get markets with filter for active only
params = {"limit": 100, "active": "true"}
all_markets = []
next_cursor = None
page = 1

print("\nFetching active markets...")
while page <= 50:  # Up to 50 pages
    if next_cursor:
        params["next_cursor"] = next_cursor
    
    response = requests.get(f"{CLOB_BASE}/markets", params=params)
    
    if response.status_code != 200:
        break
    
    data = response.json()
    markets = data.get("data", [])
    
    if not markets:
        break
    
    all_markets.extend(markets)
    print(f"  Page {page}: +{len(markets)} (total: {len(all_markets)})")
    
    next_cursor = data.get("next_cursor")
    if not next_cursor:
        break
    
    page += 1

print(f"\nTotal active markets: {len(all_markets)}")

# Search for 2026 World Cup
wc_2026 = []

for m in all_markets:
    question = m.get("question", "")
    description = m.get("description", "")
    game_start = m.get("game_start_time", "")
    
    # Check for 2026 in the text or game start time
    if "2026" in question or "2026" in description or "2026" in game_start:
        # Also check if it's World Cup related
        text = f"{question} {description}".lower()
        if any(kw in text for kw in ["world cup", "fwc", "fifa"]):
            wc_2026.append(m)

print(f"\n" + "="*80)
print(f"2026 WORLD CUP MARKETS: {len(wc_2026)}")
print("="*80)

if wc_2026:
    for i, m in enumerate(wc_2026, 1):
        q = m.get("question", "N/A")
        print(f"\n[{i}] {q}")
        print(f"    Start: {m.get('game_start_time', 'N/A')}")
        print(f"    Active: {m.get('active')}")
        print(f"    Closed: {m.get('closed')}")
        
        # Check for France vs England
        if ("france" in q.lower() and "england" in q.lower()):
            print("    *** FRANCE VS ENGLAND FOUND! ***")
            print(f"\n{json.dumps(m, indent=2)}")
        
        # Check for Spain vs Argentina
        if ("spain" in q.lower() and "argentina" in q.lower()):
            print("    *** SPAIN VS ARGENTINA (Bear's position) ***")

# Also search for July 2026 dates
print(f"\n" + "="*80)
print("MARKETS WITH JULY 2026 GAME START:")
print("="*80)

july_2026 = [m for m in all_markets if "2026-07" in m.get("game_start_time", "")]
print(f"Found: {len(july_2026)}")

for m in july_2026:
    print(f"\n{m.get('question', 'N/A')}")
    print(f"  Start: {m.get('game_start_time')}")
    print(f"  Market Slug: {m.get('market_slug', 'N/A')}")

print("\n" + "="*80)
