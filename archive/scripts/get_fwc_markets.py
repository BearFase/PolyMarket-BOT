#!/usr/bin/env python3
"""
Get all FIFA World Cup markets
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
print("WORLD CUP MARKETS")
print("="*80)

path = "/v1/markets"
headers = create_auth_headers("GET", path)
params = {"league": "fwc", "limit": 200}

response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)

if response.status_code != 200:
    print(f"[ERROR] {response.status_code}")
    exit(1)

data = response.json()
markets = data.get("markets", [])

print(f"\nTotal FWC markets: {len(markets)}\n")
print("="*80)

# Find France vs England
france_england = None

for m in markets:
    question = m.get("question", "")
    slug = m.get("slug", "")
    game_start = m.get("gameStartTime", "")
    
    # Check if this is France vs England
    q_lower = question.lower()
    s_lower = slug.lower()
    
    if ("france" in q_lower and "england" in q_lower) or \
       ("fra" in s_lower and "eng" in s_lower):
        print("\n*** FRANCE VS ENGLAND FOUND! ***")
        france_england = m
        print(f"\nQuestion: {question}")
        print(f"Slug: {slug}")
        print(f"ID: {m.get('id')}")
        print(f"Game Start: {game_start}")
        print(f"Active: {m.get('active')}")
        print(f"Event Slug: {m.get('eventSlug')}")
        print("\nFull market data:")
        print(json.dumps(m, indent=2))
        print("\n" + "="*80)

# Show all markets for today (2026-07-18)
print("\nALL MARKETS FOR TODAY (2026-07-18):")
print("="*80)

today_markets = [m for m in markets if "2026-07-18" in m.get("gameStartTime", "")]

if today_markets:
    for m in today_markets:
        print(f"\n{m.get('question', 'N/A')}")
        print(f"  Slug: {m.get('slug')}")
        print(f"  Start: {m.get('gameStartTime')}")
        print(f"  Active: {m.get('active')}")
else:
    print("\nNo games starting today")

# Show all markets for tomorrow (final)
print("\n\nMARKETS FOR TOMORROW (2026-07-19 - FINAL):")
print("="*80)

tomorrow_markets = [m for m in markets if "2026-07-19" in m.get("gameStartTime", "")]

for m in tomorrow_markets:
    print(f"\n{m.get('question', 'N/A')}")
    print(f"  Slug: {m.get('slug')}")
    print(f"  Start: {m.get('gameStartTime')}")
    print(f"  Active: {m.get('active')}")

print("\n" + "="*80)

if not france_england:
    print("\n[MISS] France vs England market NOT FOUND")
    print("\nDumping ALL FWC markets to inspect:")
    for i, m in enumerate(markets, 1):
        print(f"\n[{i}] {m.get('question', 'N/A')}")
        print(f"    Slug: {m.get('slug', 'N/A')}")
        print(f"    Start: {m.get('gameStartTime', 'N/A')}")
