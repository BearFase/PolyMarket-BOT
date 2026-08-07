#!/usr/bin/env python3
"""
Dump raw position data to understand the structure
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

path = "/v1/portfolio/positions"
url = f"https://api.polymarket.us{path}"
headers = create_auth_headers("GET", path)
response = requests.get(url, headers=headers)

print("="*80)
print("RAW POSITIONS DATA")
print("="*80)
print(json.dumps(response.json(), indent=2))
