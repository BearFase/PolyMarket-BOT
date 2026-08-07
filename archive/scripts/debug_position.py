import os, time, base64, json, requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()

key_id = ***'POLYMARKET_API_KEY')
secret = ***'POLYMARKET_API_SECRET')

pk = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret)[:32])
ts = str(int(time.time()*1000))
msg = f'{ts}GET/v1/portfolio/positions'
sig = base64.b64encode(pk.sign(msg.encode())).decode()

r = requests.get('https://api.polymarket.us/v1/portfolio/positions', 
                 headers={'X-PM-Access-Key': key_id, 'X-PM-Timestamp': ts, 'X-PM-Signature': sig})

print("FULL API RESPONSE:")
print("="*60)
print(json.dumps(r.json(), indent=2))
