import requests
r = requests.get('http://127.0.0.1:5001/api/whales', params={'q': 'Dodgers Yankees'}, timeout=45)
markets = r.json()
print(f'markets with holders: {len(markets)}')
for m in markets[:3]:
    print(f'  {m["market"][:70]}')
    for h in m['holders'][:3]:
        print(f'    {h["name"]} - {h["shares"]:,} shares')
