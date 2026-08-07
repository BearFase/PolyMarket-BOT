#!/usr/bin/env python3
"""
Test new Polymarket SDK (polymarket-client v0.1.0b21)
"""

import os
from dotenv import load_dotenv

load_dotenv()

print("="*60)
print("    POLYMARKET NEW SDK TEST")
print("="*60 + "\n")

# Test 1: Public client (no auth)
print("Test 1: Public data access...")
try:
    from polymarket import PublicClient, Market
    
    with PublicClient() as client:
        # Get a market (Argentina World Cup)
        market = client.get_market(
            url="https://polymarket.com/event/will-argentina-win-the-2026-fifa-world-cup-245"
        )
        
        print(f"Success: Got market data")
        print(f"  Question: {market.question}")
        print(f"  Active: {market.active}")
        
except Exception as e:
    print(f"Error: {e}")

# Test 2: Check if we can use REST API with API key for positions
print("\n" + "="*60)
print("Test 2: REST API with API key...")

API_KEY = os.getenv('POLYMARKET_API_KEY')
API_SECRET = os.getenv('POLYMARKET_API_SECRET')

if not API_KEY or not API_SECRET:
    print("No API keys configured")
else:
    import requests
    
    # Try authenticated endpoint
    try:
        headers = {
            "Authorization": f"Bearer {API_SECRET}",
            "X-API-Key": API_KEY
        }
        
        # Try to get positions (this is a guess at the endpoint)
        wallet = os.getenv('POLYMARKET_WALLET')
        url = f"https://clob.polymarket.com/positions/{wallet}"
        
        response = requests.get(url, headers=headers)
        
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print("Success! Got positions data")
            print(response.json())
        else:
            print(f"Response: {response.text[:200]}")
            
    except Exception as e:
        print(f"Error: {e}")

print("\n" + "="*60)
print("Note: New SDK uses wallet private keys, not API keys")
print("Your Polymarket API key might be for different endpoints")
print("\nChecking Polymarket docs for correct API usage...")
