"""
Quick position viewer - reads from synced real_positions.json
Run sync_positions_api.py first for fresh data.
"""
import json
import os

POSITIONS_FILE = "real_positions.json"

def display_positions():
    if not os.path.exists(POSITIONS_FILE):
        print("No positions file found. Run sync_positions_api.py first.")
        return

    with open(POSITIONS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("=" * 60)
    print("YOUR POLYMARKET POSITIONS")
    print("=" * 60)
    print()

    positions = data.get("positions", [])

    if not positions:
        print("No open positions")
    else:
        for pos in positions:
            print(f"Market: {pos['market']}")
            print(f"  YOUR BET: {pos['bet_type']}")
            print(f"  Position: {pos['side']} {pos['outcome']} ({pos['contracts']:.2f} contracts @ {pos['entry_price']:.2f})")
            print(f"  Cost: ${pos['cost_basis']:.2f}")
            print(f"  Current Value: ${pos['current_value']:.2f}")
            print(f"  P&L: ${pos['pnl']:+.2f}")
            print()
            for s in pos.get("scenarios", []):
                print(f"  If {s['scenario']}: ${s['pnl']:+.2f}")
            print()

    closed = data.get("closed", [])
    if closed:
        print("=" * 60)
        print("CLOSED POSITIONS")
        print("=" * 60)
        for pos in closed:
            print(f"{pos['market']}: ${pos['pnl']:.2f} ({pos.get('result', 'N/A')})")
        print()

    print(f"TOTAL P&L: ${data['total_pnl']:.2f}")
    print(f"Last sync: {data.get('last_sync', 'Never')}")
    if data.get("note"):
        print(f"\nNOTE: {data['note']}")

if __name__ == "__main__":
    display_positions()
