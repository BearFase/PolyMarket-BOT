import os, time, base64, requests, json
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

# Find World Cup markets
wc = [m for m in markets if 'fwc' in m.get('slug','').lower() or 'world cup' in m.get('question','').lower() or 'cup' in m.get('slug','').lower()]

print(f"Found {len(wc)} World Cup markets:\n")
for m in wc:
    slug = m.get('slug', '')
    question = m.get('question', '')
    start = m.get('gameStartTime', 'N/A')
    
    # Check if it's today's 3rd place or tomorrow's final
    if '2026-07-18' in start or '2026-07-19' in start:
        print(f"*** TODAY/TOMORROW: {question}")
        print(f"    Slug: {slug}")
        print(f"    Start: {start}")
        print(f"    ID: {m.get('id')}")
        print()
