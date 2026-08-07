#!/usr/bin/env python3
"""
Find what league codes exist to locate FIFA World Cup
Based on Bear's Argentina position having eventSlug: fwc-esp-arg-2026-07-19
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
print("SEARCHING FOR FIFA WORLD CUP MARKETS")
print("Based on position: fwc-esp-arg-2026-07-19")
print("="*80)

# Try getting markets with gameStartTime filter
path = "/v1/markets"
headers = create_auth_headers("GET", path)

# Try explicit slug pattern
test_slug = "fwc-esp-arg-2026-07-19"
print(f"\n[1] Trying to get market by eventSlug pattern...")
params = {"eventSlug": test_slug, "limit": 50}
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)

if response.status_code == 200:
    data = response.json()
    markets = data.get("markets", [])
    print(f"    Got {len(markets)} markets for eventSlug={test_slug}")
    
    if markets:
        for m in markets:
            print(f"\n    Found: {m.get('question')}")
            print(f"    Slug: {m.get('slug')}")
            print(f"    ID: {m.get('id')}")
else:
    print(f"    [ERROR] {response.status_code}")

# Try to search for "fwc" in event slug
print(f"\n[2] Searching for eventSlug containing 'fwc'...")
params = {"limit": 2000}
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)

if response.status_code == 200:
    data = response.json()
    all_markets = data.get("markets", [])
    print(f"    Total markets retrieved: {len(all_markets)}")
    
    # Find any with fwc in eventSlug
    fwc_markets = []
    for m in all_markets:
        event_slug = m.get("eventSlug", "")
        if event_slug and "fwc" in event_slug.lower():
            fwc_markets.append(m)
    
    print(f"    Markets with 'fwc' in eventSlug: {len(fwc_markets)}")
    
    if fwc_markets:
        print("\n    FOUND FWC MARKETS:")
        for m in fwc_markets[:10]:  # First 10
            print(f"\n    {m.get('question', 'N/A')}")
            print(f"      Slug: {m.get('slug')}")
            print(f"      Event: {m.get('eventSlug')}")
            print(f"      Start: {m.get('gameStartTime')}")
            print(f"      Active: {m.get('active')}")
else:
    print(f"    [ERROR] {response.status_code}")

# Try category=sports with date filter
print(f"\n[3] Trying category=sports with 2026-07 date filter...")
params = {"category": "sports", "limit": 1000}
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)

if response.status_code == 200:
    data = response.json()
    sports_markets = data.get("markets", [])
    print(f"    Total sports markets: {len(sports_markets)}")
    
    # Filter for 2026-07 dates (World Cup month)
    july_2026 = [m for m in sports_markets if "2026-07" in m.get("gameStartTime", "")]
    print(f"    Markets in July 2026: {len(july_2026)}")
    
    if july_2026:
        print("\n    JULY 2026 MARKETS:")
        for m in july_2026:
            print(f"\n    {m.get('question', 'N/A')}")
            print(f"      Slug: {m.get('slug')}")
            print(f"      Event: {m.get('eventSlug', 'N/A')}")
            print(f"      Start: {m.get('gameStartTime')}")

print("\n" + "="*80)
