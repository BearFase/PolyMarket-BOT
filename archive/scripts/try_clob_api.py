#!/usr/bin/env python3
"""
Last resort: Try the Polymarket CLOB (Central Limit Order Book) API
This is a different system from the main US API
"""

import requests
import json

print("="*80)
print("TRYING POLYMARKET CLOB API")
print("="*80)

# CLOB API doesn't require authentication for market data
CLOB_BASE = "https://clob.polymarket.com"

# Try to get markets
print("\n[1] Getting markets from CLOB...")
response = requests.get(f"{CLOB_BASE}/markets")

if response.status_code == 200:
    try:
        data = response.json()
        print(f"    [SUCCESS] Got response!")
        
        # Check structure
        if isinstance(data, list):
            print(f"    Total markets: {len(data)}")
            
            # Search for World Cup / France / England
            wc_markets = []
            for m in data:
                text = str(m).lower()
                if any(kw in text for kw in ["world cup", "fwc", "france", "england", "argentina", "spain"]):
                    wc_markets.append(m)
            
            if wc_markets:
                print(f"\n    [FOUND] {len(wc_markets)} World Cup related markets!")
                for m in wc_markets[:5]:
                    print(f"\n    {m}")
            else:
                print("\n    No World Cup markets found")
                print(f"\n    Sample market: {data[0] if data else 'N/A'}")
        
        elif isinstance(data, dict):
            print(f"    Response keys: {list(data.keys())}")
            print(f"\n{json.dumps(data, indent=2)[:500]}")
    
    except Exception as e:
        print(f"    Error parsing: {e}")
        print(f"    Raw response: {response.text[:500]}")
else:
    print(f"    [{response.status_code}] Failed")

# Try alternative endpoints
endpoints = [
    "/events",
    "/v1/markets",
    "/v2/markets",
    "/markets?active=true",
    "/sampling-markets",
]

for endpoint in endpoints:
    print(f"\n[Testing] {CLOB_BASE}{endpoint}")
    response = requests.get(f"{CLOB_BASE}{endpoint}")
    
    if response.status_code == 200:
        try:
            data = response.json()
            if isinstance(data, list):
                print(f"    [SUCCESS] List with {len(data)} items")
            else:
                print(f"    [SUCCESS] Dict with keys: {list(data.keys())}")
        except:
            print(f"    [SUCCESS] Response length: {len(response.text)}")
    elif response.status_code != 404:
        print(f"    [{response.status_code}]")

print("\n" + "="*80)
print("CLOB API EXPLORATION COMPLETE")
print("="*80)
