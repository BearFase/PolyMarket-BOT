#!/usr/bin/env python3
"""
Get market data from Bear's existing position
Position slug: aadc-fwc-esp-arg-2026-07-19-to-advance
Event slug: fwc-esp-arg-2026-07-19
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
print("TRYING TO FETCH MARKET FROM POSITION DATA")
print("="*80)

# From the position we know:
# - Market slug: aadc-fwc-esp-arg-2026-07-19-to-advance
# - Event ID: 52846
# - Event slug: fwc-esp-arg-2026-07-19

# Try getting market by ID
market_id = "52846"  # This is eventId, might not be market ID

# Try fetching by event slug
event_slug = "fwc-esp-arg-2026-07-19"

print(f"\n[1] Trying /v1/events/{event_slug}...")
path = f"/v1/events/{event_slug}"
headers = create_auth_headers("GET", path)
response = requests.get(f"https://api.polymarket.us{path}", headers=headers)

if response.status_code == 200:
    print(f"    [SUCCESS] Event found!")
    data = response.json()
    print(json.dumps(data, indent=2))
elif response.status_code == 404:
    print(f"    [404] Event not found via /v1/events/{{slug}}")
else:
    print(f"    [ERROR] {response.status_code}")

# Try getting all markets for that event
print(f"\n[2] Trying /v1/events/{event_slug}/markets...")
path = f"/v1/events/{event_slug}/markets"
headers = create_auth_headers("GET", path)
response = requests.get(f"https://api.polymarket.us{path}", headers=headers)

if response.status_code == 200:
    print(f"    [SUCCESS] Markets found!")
    data = response.json()
    print(json.dumps(data, indent=2)[:2000])
elif response.status_code == 404:
    print(f"    [404] Endpoint doesn't exist")
else:
    print(f"    [ERROR] {response.status_code}")

# Try getting market by the market slug
market_slug = "aadc-fwc-esp-arg-2026-07-19-to-advance"
print(f"\n[3] Trying /v1/markets/{market_slug}...")
path = f"/v1/markets/{market_slug}"
headers = create_auth_headers("GET", path)
response = requests.get(f"https://api.polymarket.us{path}", headers=headers)

if response.status_code == 200:
    print(f"    [SUCCESS] Market found!")
    data = response.json()
    print("\n" + "="*80)
    print("MARKET DATA:")
    print("="*80)
    print(json.dumps(data, indent=2))
elif response.status_code == 404:
    print(f"    [404] Market not found by slug")
else:
    print(f"    [ERROR] {response.status_code}")

# Try listing all markets for the entire event
print(f"\n[4] Searching for related markets (France vs England should have similar pattern)...")

# France vs England should be:
possible_france_england_events = [
    "fwc-fra-eng-2026-07-18",
    "fwc-eng-fra-2026-07-18",
    "fwc-france-england-2026-07-18",
    "fwc-england-france-2026-07-18",
]

for event_slug in possible_france_england_events:
    path = f"/v1/markets/{event_slug}"
    headers = create_auth_headers("GET", path)
    response = requests.get(f"https://api.polymarket.us{path}", headers=headers)
    
    if response.status_code == 200:
        print(f"\n    [FOUND] {event_slug}")
        data = response.json()
        print(json.dumps(data, indent=2)[:500])
    elif response.status_code != 404:
        print(f"    {event_slug}: {response.status_code}")

print("\n" + "="*80)
