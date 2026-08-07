"""Book the 2026-07-19 World Cup final settlements into the ledger."""
import json

with open('real_positions.json', encoding='utf-8-sig') as f:
    data = json.load(f)

already = {c.get('market_slug') for c in data['closed']}

settlements = [
    {
        "id": "real_wc_001",
        "market": "Spain vs. Argentina — Argentina to advance",
        "market_slug": "aadc-fwc-esp-arg-2026-07-19-to-advance",
        "outcome": "Argentina",
        "size": 50.00, "pnl": -50.00, "result": "LOSS",
        "exit_time": "2026-07-19T22:08:08Z",
        "notes": "World Cup final: Spain won (market resolved Spain=1, Argentina=0). Full stake lost."
    },
    {
        "id": "real_wc_002",
        "market": "Spain vs. Argentina — Messi 1+ goals",
        "market_slug": "astatc-fwc-esp-arg-2026-07-19-g-fwcliomes-gte1",
        "outcome": "Lionel Messi",
        "size": 33.75, "pnl": -33.75, "result": "LOSS",
        "exit_time": "2026-07-19T22:02:05Z",
        "notes": "Messi did not score (realized -32.50 + 1.25 fees). Full stake lost."
    },
]

for s in settlements:
    if s["market_slug"] not in already:
        data['closed'].append(s)

open_pnl = sum(p.get('pnl', 0) for p in data['positions'])
closed_pnl = sum(c.get('pnl', 0) for c in data['closed'])
data['total_pnl'] = round(open_pnl + closed_pnl, 2)

with open('real_positions.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print(f"Booked. Closed trades: {len(data['closed'])}, total P&L: ${data['total_pnl']}")
