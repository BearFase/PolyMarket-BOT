import requests

# Search for France vs England / 3rd place
r = requests.get('https://gamma-api.polymarket.com/markets', params={'limit': 100})
markets = r.json()

print("=== FRANCE VS ENGLAND (3RD PLACE MATCH) ===\n")

for m in markets:
    question = m.get('question', '').lower()
    slug = m.get('slug', '')
    
    if ('france' in question and 'england' in question) or '3rd place' in question or 'third place' in question:
        print(f"Market: {m['question']}")
        print(f"  Slug: {slug}")
        print(f"  Outcomes: {m.get('outcomes', 'N/A')}")
        
        # Get current odds from CLOB
        tokens = m.get('tokens', [])
        if tokens:
            for token in tokens:
                token_id = token.get('token_id')
                outcome = token.get('outcome')
                
                clob_r = requests.get(f'https://clob.polymarket.com/price?token_id={token_id}&side=buy')
                if clob_r.status_code == 200:
                    price_data = clob_r.json()
                    price = float(price_data.get('price', 0))
                    print(f"  {outcome}: {price*100:.1f}%")
        print()
