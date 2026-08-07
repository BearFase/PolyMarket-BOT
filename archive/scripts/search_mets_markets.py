import requests
import json

# Search for all markets with "run" or "first" in them
r = requests.get('https://gamma-api.polymarket.com/markets', 
                 params={'limit': 500, 'closed': 'false'}, timeout=15)
markets = r.json()

# Look for anything related to Mets/Phillies today
mets_markets = []
for m in markets:
    q = m.get('question', '').lower()
    desc = m.get('description', '').lower()
    
    if any(term in q or term in desc for term in ['mets', 'phillies', 'nym', 'phi']):
        mets_markets.append(m)

print(f'Found {len(mets_markets)} Mets/Phillies markets:\n')

for i, m in enumerate(mets_markets, 1):
    print(f"{i}. {m.get('question')}")
    print(f"   Slug: {m.get('slug')}")
    
    outcomes = m.get('outcomes', [])
    prices = m.get('outcomePrices')
    
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except:
            prices = []
    
    if outcomes and prices:
        for outcome, price in zip(outcomes, prices):
            print(f"   {outcome}: {float(price)*100:.1f}¢")
    
    print()
