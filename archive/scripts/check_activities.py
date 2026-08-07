import os, time, base64, json, requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()

key_id = os.getenv("POLYMARKET_API_KEY")
secret = os.getenv("POLYMARKET_API_SECRET")

pk = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret)[:32])
ts = str(int(time.time()*1000))
path = "/v1/portfolio/activities"
msg = f'{ts}GET{path}'
sig = base64.b64encode(pk.sign(msg.encode())).decode()

r = requests.get(f'https://api.polymarket.us{path}', 
                 headers={'X-PM-Access-Key': key_id, 'X-PM-Timestamp': ts, 'X-PM-Signature': sig})

print("TRADE HISTORY (Argentina related):")
print("="*60)

data = r.json()
activities = data.get('activities', [])

for activity in activities:
    if activity.get('type') == 'ACTIVITY_TYPE_TRADE':
        trade = activity.get('trade', {})
        market = trade.get('marketSlug', '')
        if 'argentina' in market.lower() or 'arg' in market.lower():
            print(f"\nMarket: {market}")
            print(f"  Quantity: {trade.get('qtyDecimal', trade.get('qty'))}")
            print(f"  Price: {trade.get('price', {}).get('value', 'N/A')}")
            print(f"  Is Aggressor: {trade.get('isAggressor')} (True = you initiated/bought)")
            print(f"  Cost: {trade.get('costBasis', {}).get('value', 'N/A')}")
            print(f"  Time: {trade.get('createTime', 'N/A')}")
            print(f"  Full trade data: {json.dumps(trade, indent=2)}")
