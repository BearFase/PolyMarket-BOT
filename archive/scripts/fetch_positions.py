#!/usr/bin/env python3
import os, time, base64, requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()

API_KEY_ID = ***"POLYMARKET_API_KEY")
API_SECRET = ***"POLYMARKET_API_SECRET")

def create_auth_headers(method, path):
    private_key_bytes = base64.b64decode(API_SECRET)[:32]
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}"
    signature = base64.b64encode(private_key.sign(message.encode())).decode()
    return {
        "X-PM-Access-Key": API_KEY_ID,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature,
        "Content-Type": "application/json",
    }

def main():
    print("="*60)
    print("FETCHING POSITIONS")
    print("="*60 + "\n")
    
    if not API_KEY_ID or not API_SECRET:
        ***"ERROR: Missing API keys")
        return
    
    print(f"Key ID: {API_KEY_ID[:8]}...{API_KEY_ID[-4:]}\n")
    
    try:
        path = "/v1/portfolio/positions"
        url = f"https://api.polymarket.us{path}"
        headers = create_auth_headers("GET", path)
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            positions = data.get("positions", {})
            print(f"SUCCESS! Found {len(positions)} position(s)\n")
            
            for slug, pos in positions.items():
                print(f"{slug}:")
                print(f"  Position: {pos.get('netPositionDecimal', '0')}")
                print(f"  Cost: ${pos.get('cost', {}).get('amount', '0')}")
                print(f"  Value: ${pos.get('cashValue', {}).get('amount', '0')}")
                meta = pos.get("marketMetadata", {})
                print(f"  {meta.get('title', 'N/A')}")
                print()
        else:
            print(f"ERROR: {response.status_code}")
            print(response.text[:300])
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    main()
