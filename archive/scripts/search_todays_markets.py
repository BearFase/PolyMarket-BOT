import os, time, base64, requests, json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()

key_id = os.getenv('POLYMARKET_API_KEY')
secret = os.getenv('POLYMARKET_API_SECRET')

pk = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret)[:32])
ts = str(int(time.time()*1000))
path = '/v1/markets'
msg = f'{ts}GET{path}'
sig = base64.b64encode(pk.sign(msg.encode())).decode()

r = requests.get(f'https://api.polymarket.us{path}', 
                 headers={'X-PM-Access-Key': key_id, 'X-PM-Timestamp': ts, 'X-PM-Signature': sig},
                 params={'active': 'true', 'limit': 500})

data = r.json()
markets = data.get('markets', [])

print(f"Total active markets: {len(markets)}\n")

# Look for markets starting today or tomorrow
today = "2026-07-18"
tomorrow = "2026-07-19"

for m in markets:
    start = m.get('gameStartTime', '')
    if today in start or tomorrow in start:
        print(f"Market: {m.get('question')}")
        print(f"  Slug: {m.get('slug')}")
        print(f"  Start: {start}")
        print(f"  Category: {m.get('category')}")
        print()
