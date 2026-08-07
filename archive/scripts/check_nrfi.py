import requests
import json

r = requests.get('https://gamma-api.polymarket.com/markets', 
                 params={'limit': 200, 'closed': 'false'}, timeout=10)
markets = r.json()

mlb = [m for m in markets if 'mets' in m.get('question', '').lower() 
       or 'phillies' in m.get('question', '').lower()
       or 'nrfi' in m.get('question', '').lower()
       or 'yrfi' in m.get('question', '').lower()
       or 'first inning' in m.get('question', '').lower()]

print(f'Found {len(mlb)} Mets/Phillies/NRFI markets:\n')

for i, m in enumerate(mlb[:15], 1):
    print(f"{i}. {m.get('question')}")
    if m.get('outcomePrices'):
        prices = m.get('outcomePrices', [])
        if isinstance(prices, str):
            prices = json.loads(prices)
        if prices:
            print(f"   Prices: {prices}")
    print()
