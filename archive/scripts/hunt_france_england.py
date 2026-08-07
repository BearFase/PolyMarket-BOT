#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
URGENT: Find France vs England 3rd Place Market
Try every possible API endpoint and search method
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
    """Create authenticated headers for Polymarket US API"""
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
print("HUNTING FOR FRANCE VS ENGLAND 3RD PLACE MARKET")
print("="*80)

# Method 1: Search all markets with max limit
print("\n[1] Searching /v1/markets with limit=500, active=true...")
path = "/v1/markets"
headers = create_auth_headers("GET", path)
params = {"active": "true", "limit": 500}

response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    markets = data.get("markets", [])
    print(f"    Got {len(markets)} markets")
    
    # Search for France, England, 3rd place, bronze
    keywords = ["france", "england", "3rd", "third", "bronze", "place"]
    matches = []
    for m in markets:
        text = f"{m.get('question', '')} {m.get('slug', '')} {m.get('description', '')}".lower()
        if any(kw in text for kw in ["france", "england"]):
            matches.append(m)
    
    if matches:
        print(f"\n    [FOUND] {len(matches)} matches with France/England:")
        for m in matches:
            print(f"\n    Market: {m.get('question', 'N/A')}")
            print(f"    Slug: {m.get('slug', 'N/A')}")
            print(f"    ID: {m.get('id', 'N/A')}")
            print(f"    Game Start: {m.get('gameStartTime', 'N/A')}")
            print(f"    Category: {m.get('category', 'N/A')}")
    else:
        print("    [MISS] No France/England markets found in active markets")
else:
    print(f"    [ERROR] Status {response.status_code}")

# Method 2: Try closed=false instead of active
print("\n[2] Trying closed=false parameter...")
params = {"closed": "false", "limit": 500}
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    markets = data.get("markets", [])
    print(f"    Got {len(markets)} markets with closed=false")
else:
    print(f"    [ERROR] Status {response.status_code}")

# Method 3: Sports category only
print("\n[3] Searching category=sports...")
params = {"active": "true", "limit": 500, "category": "sports"}
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    markets = data.get("markets", [])
    print(f"    Got {len(markets)} sports markets")
    
    # Filter for soccer/football
    soccer = [m for m in markets if any(kw in f"{m.get('question', '')} {m.get('slug', '')}".lower() 
                                       for kw in ["soccer", "football", "fwc", "world cup", "fifa"])]
    if soccer:
        print(f"\n    Found {len(soccer)} soccer markets:")
        for m in soccer[:20]:  # Show first 20
            print(f"    - {m.get('question', 'N/A')}")
else:
    print(f"    [ERROR] Status {response.status_code}")

# Method 4: Try by date range
print("\n[4] Searching by game start date (2026-07-18)...")
params = {"active": "true", "limit": 500}
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    markets = data.get("markets", [])
    
    today_games = [m for m in markets if "2026-07-18" in m.get("gameStartTime", "")]
    if today_games:
        print(f"\n    [FOUND] {len(today_games)} games starting today:")
        for m in today_games:
            print(f"\n    Market: {m.get('question', 'N/A')}")
            print(f"    Slug: {m.get('slug', 'N/A')}")
            print(f"    ID: {m.get('id', 'N/A')}")
            print(f"    Start: {m.get('gameStartTime', 'N/A')}")
    else:
        print("    [MISS] No games starting 2026-07-18")
else:
    print(f"    [ERROR] Status {response.status_code}")

# Method 5: Check /v1/events endpoint
print("\n[5] Trying /v1/events endpoint...")
path = "/v1/events"
headers = create_auth_headers("GET", path)
params = {"active": "true", "limit": 200}
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    events = data.get("events", [])
    print(f"    Got {len(events)} events")
    
    soccer_events = [e for e in events if any(kw in f"{e.get('title', '')} {e.get('slug', '')}".lower() 
                                              for kw in ["france", "england", "world cup", "fwc"])]
    if soccer_events:
        print(f"\n    Found {len(soccer_events)} relevant events:")
        for e in soccer_events:
            print(f"    - {e.get('title', 'N/A')}")
else:
    print(f"    [ERROR] Status {response.status_code}: Events endpoint may not exist")

# Method 6: Try /v1/games endpoint
print("\n[6] Trying /v1/games endpoint...")
path = "/v1/games"
headers = create_auth_headers("GET", path)
params = {"limit": 200}
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    print(f"    [FOUND] Games endpoint exists! Response: {json.dumps(data, indent=2)[:500]}")
else:
    print(f"    [ERROR] Status {response.status_code}: Games endpoint may not exist")

# Method 7: Search for ALL markets without filters
print("\n[7] Pulling ALL markets (no filters, max limit)...")
path = "/v1/markets"
headers = create_auth_headers("GET", path)
params = {"limit": 1000}  # Max out
response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)
if response.status_code == 200:
    data = response.json()
    all_markets = data.get("markets", [])
    print(f"    Got {len(all_markets)} total markets")
    
    # Dump all slugs with "france" or "england"
    fe_markets = [m for m in all_markets if "france" in m.get("slug", "").lower() or 
                  "england" in m.get("slug", "").lower() or
                  "france" in m.get("question", "").lower() or
                  "england" in m.get("question", "").lower()]
    
    if fe_markets:
        print(f"\n    [FOUND] {len(fe_markets)} France/England markets (ANY STATUS):")
        for m in fe_markets:
            print(f"\n    Question: {m.get('question', 'N/A')}")
            print(f"    Slug: {m.get('slug', 'N/A')}")
            print(f"    ID: {m.get('id', 'N/A')}")
            print(f"    Active: {m.get('active', 'N/A')}")
            print(f"    Closed: {m.get('closed', 'N/A')}")
            print(f"    Start: {m.get('gameStartTime', 'N/A')}")
    else:
        print("    [MISS] Still no France/England markets in entire catalog")
else:
    print(f"    [ERROR] Status {response.status_code}")

print("\n" + "="*80)
print("HUNT COMPLETE")
print("="*80)
