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

def get_positions():
    path = "/v1/portfolio/positions"
    url = f"https://api.polymarket.us{path}"
    headers = create_auth_headers("GET", path)
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API error: {response.status_code} - {response.text[:200]}")

import json; data = get_positions(); print(json.dumps(data, indent=2))
    print("="*60)
    print("YOUR POLYMARKET POSITIONS")
    print("="*60 + "\n")
    
    data = get_positions()
    positions = data.get("positions", {})
    
    if not positions:
        print("No open positions")
    else:
        for slug, pos in positions.items():
            meta = pos.get("marketMetadata", {})
            net_pos = float(pos.get("netPositionDecimal", pos.get("netPosition", "0")))
            cost = float(pos.get("cost", {}).get("value", "0"))
            cash_value = float(pos.get("cashValue", {}).get("value", "0"))
            realized = float(pos.get("realized", {}).get("value", "0"))
            unrealized = cash_value - cost
            
            print(f"Market: {meta.get('title', slug)}")
            print(f"  Outcome: {meta.get('outcome', 'N/A')}")
            print(f"  Position Size: {abs(net_pos):.2f} contracts")
            print(f"  Side: {'LONG' if net_pos > 0 else 'SHORT'}")
            print(f"  Cost Basis: ${cost:.2f}")
            print(f"  Current Value: ${cash_value:.2f}")
            print(f"  Unrealized P&L: ${unrealized:.2f}")
            print(f"  Realized P&L: ${realized:.2f}")
            print(f"  Event: {meta.get('eventSlug', 'N/A')}")
            print()
