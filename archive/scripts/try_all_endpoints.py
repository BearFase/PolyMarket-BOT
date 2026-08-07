#!/usr/bin/env python3
"""
Try all possible API endpoints to find France vs England
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

endpoints_to_try = [
    "/v1/markets?active=true&limit=100&offset=500",  # Try pagination
    "/v1/markets?active=true&limit=100&offset=1000",
    "/v1/markets?active=true&limit=100&offset=1500",
    "/v1/markets?limit=2000",  # Try massive limit
    "/v1/portfolio/available-positions",  # Available positions endpoint
    "/v1/games?date=2026-07-18",  # Try games by date
    "/v1/events?date=2026-07-18",  # Try events by date
    "/v1/markets?gameStartTime=2026-07-18",  # Try filtering by game start
    "/v1/markets?eventSlug=fwc",  # Try filtering by event
    "/v1/markets?category=soccer",  # Try soccer category
    "/v1/markets?league=fwc",  # Try league filter
]

print("="*80)
print("TRYING ALL POSSIBLE ENDPOINTS")
print("="*80)

for endpoint in endpoints_to_try:
    print(f"\n[TRYING] {endpoint}")
    
    # Parse query params
    if "?" in endpoint:
        path, query = endpoint.split("?", 1)
        params = dict(p.split("=") for p in query.split("&"))
    else:
        path = endpoint
        params = {}
    
    headers = create_auth_headers("GET", path)
    response = requests.get(f"https://api.polymarket.us{path}", headers=headers, params=params)
    
    if response.status_code == 200:
        try:
            data = response.json()
            
            # Check what we got back
            if isinstance(data, dict):
                if "markets" in data:
                    markets = data["markets"]
                    print(f"  [SUCCESS] Got {len(markets)} markets")
                    
                    # Check for FWC
                    fwc = [m for m in markets if "fwc" in str(m).lower()]
                    if fwc:
                        print(f"  [FOUND] {len(fwc)} FWC markets!")
                        for m in fwc[:3]:
                            print(f"    - {m.get('question', m.get('slug', 'N/A'))}")
                
                elif "positions" in data or "availablePositions" in data:
                    print(f"  [SUCCESS] Positions endpoint")
                    print(f"    Keys: {list(data.keys())}")
                
                elif "events" in data:
                    events = data["events"]
                    print(f"  [SUCCESS] Got {len(events)} events")
                
                else:
                    print(f"  [SUCCESS] Response keys: {list(data.keys())}")
            
            elif isinstance(data, list):
                print(f"  [SUCCESS] Got list with {len(data)} items")
        
        except Exception as e:
            print(f"  [SUCCESS] but error parsing: {e}")
            print(f"    First 200 chars: {str(response.text)[:200]}")
    
    elif response.status_code == 404:
        print(f"  [404] Not found")
    else:
        print(f"  [ERROR] {response.status_code}")

print("\n" + "="*80)
print("ENDPOINT SCAN COMPLETE")
print("="*80)
