#!/usr/bin/env python3
"""
Migrate from old paper_state.json to new position tracking system.

This is a ONE-TIME migration script.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

OLD_FILE = Path("paper_state.json")
PAPER_FILE = Path("paper_positions.json")
REAL_FILE = Path("real_positions.json")

def migrate():
    if not OLD_FILE.exists():
        print("❌ No paper_state.json found")
        return
    
    old_data = json.loads(OLD_FILE.read_text())
    
    # Separate paper and real positions
    paper_positions = []
    real_positions = []
    paper_closed = []
    real_closed = []
    paper_pnl = 0.0
    real_pnl = 0.0
    
    # Process history
    for trade in old_data.get("history", []):
        trade_id = trade.get("id", "")
        is_paper = trade_id.startswith("paper")
        
        closed_trade = {
            "id": trade_id,
            "market": trade.get("market", ""),
            "outcome": trade.get("outcome", ""),
            "entry_price": trade.get("entry_price", 0),
            "exit_price": trade.get("exit_price", 0),
            "size": trade.get("size", 0),
            "pnl": trade.get("pnl", 0),
            "entry_time": trade.get("entry_time", ""),
            "exit_time": trade.get("exit_time", ""),
            "notes": trade.get("notes", "")
        }
        
        if is_paper:
            paper_closed.append(closed_trade)
            paper_pnl += closed_trade["pnl"]
        else:
            real_closed.append(closed_trade)
            real_pnl += closed_trade["pnl"]
    
    # Process open positions (if any)
    for pos in old_data.get("positions", []):
        pos_id = pos.get("id", "")
        is_paper = pos_id.startswith("paper")
        
        open_pos = {
            "id": pos_id,
            "market": pos.get("market", ""),
            "outcome": pos.get("outcome", ""),
            "entry_price": pos.get("entry_price", 0),
            "size": pos.get("size", 0),
            "pnl": pos.get("pnl", 0),
            "entry_time": pos.get("entry_time", pos.get("opened_at", "")),
            "notes": pos.get("notes", "")
        }
        
        if is_paper:
            paper_positions.append(open_pos)
        else:
            real_positions.append(open_pos)
    
    # Create new format
    paper_data = {
        "positions": paper_positions,
        "closed": paper_closed,
        "total_pnl": paper_pnl
    }
    
    real_data = {
        "positions": real_positions,
        "closed": real_closed,
        "total_pnl": real_pnl
    }
    
    # Save
    PAPER_FILE.write_text(json.dumps(paper_data, indent=2))
    REAL_FILE.write_text(json.dumps(real_data, indent=2))
    
    print("✅ Migration complete!\n")
    print(f"📄 Paper: {len(paper_closed)} closed, ${paper_pnl:.2f} P&L")
    print(f"💵 Real: {len(real_closed)} closed, ${real_pnl:.2f} P&L")
    print(f"\nOld file backed up to: paper_state.json.bak")
    
    # Backup old file
    backup = Path("paper_state.json.bak")
    backup.write_text(OLD_FILE.read_text())
    
    print("\nRun: python position_tracker.py status")

if __name__ == "__main__":
    migrate()
