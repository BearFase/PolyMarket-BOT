#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search Polymarket for specific markets
"""

import sys
import requests

BASE = "https://data-api.polymarket.com"
HEADERS = {"User-Agent": "market-search/1.0"}

def search_markets(query):
    """Search for markets by keyword."""
    try:
        # Try the events endpoint
        r = requests.get(
            f"{BASE}/events",
            headers=HEADERS,
            params={"limit": 20, "active": "true"},
            timeout=15
        )
        r.raise_for_status()
        events = r.json()
        
        # Filter by query
        query_lower = query.lower()
        matches = [
            e for e in events
            if query_lower in e.get("title", "").lower() or
               query_lower in e.get("description", "").lower()
        ]
        
        return matches
    except Exception as e:
        print(f"[ERROR] {e}")
        return []

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "england argentina"
    
    print(f"\nSearching Polymarket for: {query}\n")
    print("="*60)
    
    matches = search_markets(query)
    
    if not matches:
        print("\nNo active markets found.")
        print("\nTrying broader search...")
        # Try just "england"
        matches = search_markets("england")
    
    if not matches:
        print("Still no matches. Market might not exist or is already resolved.")
    else:
        for i, event in enumerate(matches[:10], 1):
            print(f"\n{i}. {event.get('title', '?')}")
            print(f"   Slug: {event.get('slug', '?')}")
            print(f"   URL: https://polymarket.com/event/{event.get('slug', '')}")
            
            # Show markets within event
            markets = event.get("markets", [])
            if markets:
                print(f"   Markets:")
                for m in markets[:3]:  # First 3 outcomes
                    outcome = m.get("question", "?")
                    price = float(m.get("lastPrice", 0)) * 100
                    print(f"     - {outcome}: {price:.0f}c")
    
    print("\n" + "="*60)
