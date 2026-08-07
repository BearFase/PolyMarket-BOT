#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polymarket Bot Status Dashboard

Quick overview of paper trading performance and recent activity.
"""

import json
from datetime import datetime
from pathlib import Path


def format_time_ago(iso_time):
    """Convert ISO timestamp to human-readable 'X ago' format."""
    if not iso_time:
        return "never"
    
    try:
        dt = datetime.fromisoformat(iso_time)
        delta = datetime.now(dt.tzinfo) - dt
        
        if delta.days > 0:
            return f"{delta.days}d ago"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}h ago"
        minutes = (delta.seconds % 3600) // 60
        return f"{minutes}m ago"
    except:
        return "unknown"


def main():
    state_path = Path("paper_positions.json")
    config_path = Path("paper_config.json")
    
    if not state_path.exists():
        print("\n[!] No paper ledger found. Run paper_trader.py status first.\n")
        return
    
    state = json.loads(state_path.read_text())
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    
    print("\n" + "="*60)
    print("           POLYMARKET BOT STATUS")
    print("="*60 + "\n")
    
    # Last check
    last = state.get("metadata", {}).get("updated_at")
    print(f"Ledger Update:  {format_time_ago(last)}")
    print("Entry Strategy: NONE")
    print()
    
    # Portfolio Summary
    total_pnl = state.get("realized_pnl", 0)
    positions = state.get("open_positions", [])
    history = state.get("closed_positions", [])
    
    open_pnl = state.get("unrealized_pnl", 0)
    exposure = state.get("open_exposure", 0)
    max_exposure = config.get("max_total_exposure", 500)
    
    print("--- PORTFOLIO ---")
    print(f"Total P&L:      ${total_pnl:,.2f}")
    print(f"Open P&L:       ${open_pnl:,.2f}")
    print(f"Exposure:       ${exposure:,.0f} / ${max_exposure:,.0f} "
          f"({exposure/max_exposure*100:.0f}%)")
    print()
    
    # Performance
    if history:
        wins = sum(1 for t in history if t.get("pnl", t.get("realized_pnl", 0)) > 0)
        losses = sum(1 for t in history if t.get("pnl", t.get("realized_pnl", 0)) < 0)
        breakeven = len(history) - wins - losses
        win_rate = wins / len(history) * 100
        pnl_key = "pnl" if "pnl" in history[0] else "realized_pnl"
        avg_win = sum(t[pnl_key] for t in history if t[pnl_key] > 0) / max(wins, 1)
        avg_loss = sum(t[pnl_key] for t in history if t[pnl_key] < 0) / max(losses, 1) if losses > 0 else 0
        
        print("--- PERFORMANCE ---")
        print(f"Closed Trades:  {len(history)} ({wins}W / {losses}L / {breakeven}B)")
        print(f"Win Rate:       {win_rate:.1f}%")
        print(f"Avg Win:        ${avg_win:.2f}")
        print(f"Avg Loss:       ${avg_loss:.2f}")
        print()
    
    # Open Positions
    if positions:
        print("--- OPEN POSITIONS ---")
        for i, p in enumerate(positions, 1):
            pnl = p.get("current_value", 0) - p.get("cost_basis", 0)
            current = p.get("current_price", p.get("entry_price"))
            
            print(f"\n{i}. {p['question']}")
            print(f"   Side:        {p['outcome_name']}")
            print(f"   Entry:       {p['entry_price']*100:.1f}c")
            print(f"   Current:     {current*100:.1f}c")
            print(f"   Size:        ${p['cost_basis']:.0f}")
            print(f"   P&L:         ${pnl:.2f} ({pnl/p['cost_basis']*100:+.1f}%)")
            print(f"   Edge:        {p.get('edge', 0)*100:.1f}%")
            print(f"   Opened:      {format_time_ago(p.get('entry_time'))}")
        print()
    else:
        print("--- OPEN POSITIONS ---")
        print("(none)")
        print()
    
    # Recent Closed
    if history:
        print("--- RECENT CLOSED (Last 3) ---")
        for trade in history[-3:]:
            pnl = trade.get("pnl", trade.get("realized_pnl", 0))
            symbol = "+" if pnl > 0 else ""
            
            print(f"\n{trade['question']}")
            print(f"   Entry: {trade['entry_price']*100:.1f}c | Payout: ${trade.get('payout', 0):.2f}")
            print(f"   P&L: {symbol}${pnl:.2f}")
            print(f"   Result: {trade.get('settlement_result', 'legacy')}")
            print(f"   Closed: {format_time_ago(trade.get('settled_at'))}")
        print()
    
    # Config Summary
    print("--- CONFIG ---")
    print(f"Max Position:       ${config.get('max_position_size', 100):.0f}")
    print(f"Max Exposure:       ${config.get('max_total_exposure', 500):.0f}")
    print()
    
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
