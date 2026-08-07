#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Find France vs England market by searching for FWC event slug pattern
Based on Argentina market: fwc-esp-arg-2026-07-19
France vs England should be: fwc-fra-eng-2026-07-18 (3rd place is today)
"""

import os
import time
import base64
import json
import requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()

API_KEY_ID = os.getenv("POLYMARKET_API_KEY")
API_SECRET = os.getenv("POLYMARKET_API_SECRET")

def create_auth_headers(method, path):
    private_key_bytes = base64.b64decode(API_SECRET)[:32]
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}"
    signature = base64.b64encode(private_key.sign(message.encode())).decode()
    return {
        "X-PM-Access-Key": API_KEY_ID,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature
    }

print("="*80)
print("SEARCHING FOR FRANCE VS ENGLAND BY EVENT PATTERN")
print("="*80)

# Try various slug patterns for France vs England
possible_slugs = [
    "fwc-fra-eng-2026-07-18",  # France vs England
    "fwc-eng-fra-2026-07-18",  # England vs France (reversed)
    "fwc-france-england-2026-07-18",
    "fwc-england-france-2026-07-18",
]

# Try to find the market by searching all markets
path = "/v1/markets"
headers = create_auth_headers("GET", path)
params = {"limit": 1000}  # Get as many as possible

response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)

if response.status_code == 200:
    data = response.json()
    markets = data.get("markets", [])
    print(f"\nTotal markets retrieved: {len(markets)}")
    
    # Search for any FWC markets
    fwc_markets = [m for m in markets if "fwc" in m.get("slug", "").lower() or
                   "fwc" in str(m.get("eventSlug", "")).lower()]
    
    print(f"FWC markets found: {len(fwc_markets)}")
    
    if fwc_markets:
        print("\n" + "="*80)
        print("ALL FWC MARKETS:")
        print("="*80)
        for m in fwc_markets:
            print(f"\nQuestion: {m.get('question', 'N/A')}")
            print(f"Slug: {m.get('slug', 'N/A')}")
            print(f"Event Slug: {m.get('eventSlug', 'N/A')}")
            print(f"Game Start: {m.get('gameStartTime', 'N/A')}")
            print(f"Active: {m.get('active', 'N/A')}")
            print(f"ID: {m.get('id', 'N/A')}")
            
            # Check if it's France vs England
            q_lower = m.get('question', '').lower()
            if ('france' in q_lower and 'england' in q_lower) or \
               ('fra' in m.get('slug', '').lower() and 'eng' in m.get('slug', '').lower()):
                print("    *** THIS IS FRANCE VS ENGLAND! ***")
    
    # Also check for ANY markets with today's date
    print("\n" + "="*80)
    print("MARKETS WITH 2026-07-18 DATE:")
    print("="*80)
    
    today_markets = [m for m in markets if "2026-07-18" in str(m.get("gameStartTime", ""))]
    print(f"Found {len(today_markets)} markets with today's date")
    
    for m in today_markets[:10]:  # First 10
        print(f"\n{m.get('question', 'N/A')}")
        print(f"  Slug: {m.get('slug', 'N/A')}")
        print(f"  Start: {m.get('gameStartTime', 'N/A')}")

else:
    print(f"[ERROR] API returned {response.status_code}")

# Try to fetch market by specific event ID if we know it
print("\n" + "="*80)
print("TRYING TO GET SPECIFIC MARKET BY ID/SLUG:")
print("="*80)

# Try fetching a specific market endpoint (if it exists)
for slug_pattern in possible_slugs:
    test_path = f"/v1/markets/{slug_pattern}"
    headers = create_auth_headers("GET", test_path)
    response = requests.get(f"https://api.polymarket.us{test_path}", headers=headers)
    
    if response.status_code == 200:
        print(f"\n[FOUND] Market found with slug: {slug_pattern}")
        print(json.dumps(response.json(), indent=2))
        break
    elif response.status_code != 404:
        print(f"Slug {slug_pattern}: {response.status_code}")

print("\n" + "="*80)
