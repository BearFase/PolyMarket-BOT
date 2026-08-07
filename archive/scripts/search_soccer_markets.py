#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Search for soccer/football/World Cup markets specifically
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
print("SEARCHING FOR SOCCER/FOOTBALL MARKETS")
print("="*80)

# Pull all sports markets
path = "/v1/markets"
headers = create_auth_headers("GET", path)
params = {"active": "true", "limit": 1000, "category": "sports"}

response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)

if response.status_code != 200:
    print(f"[ERROR] API returned {response.status_code}")
    exit(1)

data = response.json()
all_markets = data.get("markets", [])

print(f"\nTotal sports markets: {len(all_markets)}")

# Filter for soccer keywords
soccer_keywords = ["soccer", "football", "fifa", "world cup", "fwc", "uefa", "champions", 
                   "premier league", "epl", "la liga", "bundesliga", "serie a"]

soccer_markets = []
for m in all_markets:
    text = f"{m.get('question', '')} {m.get('slug', '')} {m.get('description', '')}".lower()
    if any(kw in text for kw in soccer_keywords):
        soccer_markets.append(m)

print(f"Soccer markets found: {len(soccer_markets)}")

if not soccer_markets:
    print("\n[MISS] No soccer markets found at all!")
    print("\nDumping first 20 sports market slugs to see what's there:")
    for m in all_markets[:20]:
        print(f"  - {m.get('slug', 'N/A')}")
else:
    print("\n" + "="*80)
    print("SOCCER MARKETS:")
    print("="*80)
    
    for i, m in enumerate(soccer_markets, 1):
        print(f"\n[{i}] {m.get('question', 'N/A')}")
        print(f"    Slug: {m.get('slug', 'N/A')}")
        print(f"    ID: {m.get('id', 'N/A')}")
        print(f"    Start: {m.get('gameStartTime', 'N/A')}")
        print(f"    Active: {m.get('active', 'N/A')}")
        print(f"    Closed: {m.get('closed', 'N/A')}")
        
        # Check if it's France vs England
        if "france" in m.get("question", "").lower() and "england" in m.get("question", "").lower():
            print("    *** THIS IS FRANCE VS ENGLAND! ***")

print("\n" + "="*80)
