"""
Quick validation: compares dashboard positions against what parser produced.
Run this after adding a new position to verify it synced correctly.
"""
import json

with open('real_positions.json', 'r') as f:
    data = json.load(f)

positions = data.get('positions', [])
print(f"\n{len(positions)} open positions:\n")

for p in positions:
    outcome = p.get('outcome', 'Unknown')
    market = p.get('market', '')
    pnl = p.get('pnl', 0)
    size = p.get('cost_basis', 0)

    print(f"  {market}")
    print(f"    Outcome: {outcome}")
    print(f"    Size: ${size:.2f} | P&L: ${pnl:+.2f}")
    print()

print("✓ Check: Do outcome names match what you see in the Polymarket app?")
print("  If not, note the position # and market name, then tell me.")
