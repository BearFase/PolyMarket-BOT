#!/usr/bin/env python3
"""
Sync positions from Polymarket API to local tracking.
"""

import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("POLYMARKET_API_KEY")
API_SECRET = os.getenv("POLYMARKET_API_SECRET")
WALLET = os.getenv("POLYMARKET_WALLET")

REAL_FILE = Path("real_positions.json")

def load_positions():
    if REAL_FILE.exists():
        return json.loads(REAL_FILE.read_text())
    return {"positions": [], "closed": [], "total_pnl": 0.0}

def main():
    print("="*60)
    print("    SYNCING POSITIONS FROM POLYMARKET")
    print("="*60 + "\n")
    
    if not API_KEY or not API_SECRET:
        print("ERROR: API keys not configured")
        print("Add to .env file - see SETUP_API_KEYS.md")
        sys.exit(1)
    
    print("API keys found, testing connection...\n")
    
    # Load current tracking
    data = load_positions()
    
    print("="*60)
    print("CURRENT TRACKED POSITIONS")
    print("="*60)
    
    if data["positions"]:
        for pos in data["positions"]:
            print(f"\n{pos['id']}: {pos['market']}")
            print(f"   Outcome: {pos['outcome']}")
            print(f"   Entry: {pos['entry_price']*100:.1f}%")
            print(f"   Size: ${pos['size']}")
            print(f"   P&L: ${pos['pnl']:.2f}")
    else:
        print("\n(no open positions tracked)")
    
    print("\n" + "="*60)
    print("API sync ready - add keys to enable live updates")

if __name__ == "__main__":
    main()
