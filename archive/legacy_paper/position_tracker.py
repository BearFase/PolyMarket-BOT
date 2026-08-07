#!/usr/bin/env python3
"""
Position Tracker - Clear separation of paper vs real positions.

Prevents confusion by:
1. Separate files: paper_positions.json and real_positions.json
2. Clear labeling: PAPER vs REAL in all outputs
3. Strict validation: Can't mix paper/real in same operation
4. Audit trail: Every change logged with timestamp

Usage:
    python position_tracker.py status
    python position_tracker.py open --type paper --market "Argentina World Cup" --outcome YES --price 0.402 --size 100
    python position_tracker.py close --id paper_001 --price 0.405
    python position_tracker.py list --type real
"""

import json
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from paper_trader import PaperTrader, PaperLedgerError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# File paths
PAPER_FILE = Path("paper_positions.json")
REAL_FILE = Path("real_positions.json")
AUDIT_FILE = Path("position_audit.log")

def load_positions(position_type):
    """Load positions from file."""
    if position_type == "paper":
        ledger = PaperTrader().state
        return {
            "positions": ledger["open_positions"],
            "closed": ledger["closed_positions"],
            "total_pnl": ledger["realized_pnl"],
        }
    file = PAPER_FILE if position_type == "paper" else REAL_FILE
    
    if not file.exists():
        return {"positions": [], "closed": [], "total_pnl": 0.0}
    
    return json.loads(file.read_text())

def save_positions(position_type, data):
    """Save positions to file."""
    if position_type == "paper":
        raise PaperLedgerError("Paper positions must be changed through PaperTrader")
    file = PAPER_FILE if position_type == "paper" else REAL_FILE
    file.write_text(json.dumps(data, indent=2))

def audit_log(action, position_type, details):
    """Log all position changes."""
    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry = f"[{timestamp}] {action.upper()} | {position_type.upper()} | {details}\n"
    
    with AUDIT_FILE.open("a") as f:
        f.write(log_entry)

def generate_id(position_type):
    """Generate unique position ID."""
    data = load_positions(position_type)
    existing_ids = [p["id"] for p in data["positions"]] + [p["id"] for p in data["closed"]]
    
    counter = 1
    while True:
        new_id = f"{position_type}_{counter:03d}"
        if new_id not in existing_ids:
            return new_id
        counter += 1

def cmd_status(args):
    """Show overall status."""
    paper = load_positions("paper")
    real = load_positions("real")
    
    print("\n" + "="*60)
    print("           POSITION TRACKER STATUS")
    print("="*60 + "\n")
    
    print("📄 PAPER TRADING")
    print(f"   Open: {len(paper['positions'])}")
    print(f"   Closed: {len(paper['closed'])}")
    print(f"   Total P&L: ${paper['total_pnl']:.2f}")
    
    print("\n💵 REAL MONEY")
    print(f"   Open: {len(real['positions'])}")
    print(f"   Closed: {len(real['closed'])}")
    print(f"   Total P&L: ${real['total_pnl']:.2f}")
    
    print("\n" + "="*60 + "\n")

def cmd_open(args):
    """Open a new position."""
    position_type = args.type
    if position_type == "paper":
        position = PaperTrader().open_position({
            "condition_id": args.condition_id,
            "market_slug": args.market_slug,
            "event_slug": args.event_slug,
            "outcome_id": args.outcome_id,
            "outcome_name": args.outcome,
            "question": args.market,
            "entry_price": args.price,
            "signal_source": "manual",
        })
        audit_log("OPEN", "paper", f"UUID={position['uuid']} | {args.market} | {args.outcome} @ ${args.price}")
        print(f"\nOpened PAPER position {position['uuid']} for ${position['cost_basis']:.2f}")
        return
    data = load_positions(position_type)
    
    position = {
        "id": generate_id(position_type),
        "market": args.market,
        "outcome": args.outcome,
        "entry_price": args.price,
        "size": args.size,
        "pnl": 0.0,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "notes": args.notes or ""
    }
    
    data["positions"].append(position)
    save_positions(position_type, data)
    
    audit_log("OPEN", position_type, f"ID={position['id']} | {args.market} | {args.outcome} @ ${args.price} x ${args.size}")
    
    print(f"\n✅ Opened {position_type.upper()} position:")
    print(f"   ID: {position['id']}")
    print(f"   Market: {args.market}")
    print(f"   Outcome: {args.outcome}")
    print(f"   Entry: ${args.price} x ${args.size}")
    print()

def cmd_close(args):
    """Close an existing position."""
    paper = PaperTrader().state
    paper_ids = {p["uuid"] for p in paper["open_positions"] + paper["closed_positions"]}
    if args.id in paper_ids or args.id.startswith("paper"):
        print("Paper positions may only be settled from authoritative market results.")
        print("Run: python paper_trader.py settle")
        return
    if args.price is None:
        print("Error: --price is required for real position closes")
        return
    position_type = "real"
    data = load_positions(position_type)
    
    # Find position
    position = None
    for i, pos in enumerate(data["positions"]):
        if pos["id"] == args.id:
            position = data["positions"].pop(i)
            break
    
    if not position:
        print(f"❌ Error: Position {args.id} not found in {position_type} positions")
        return
    
    # Calculate P&L
    position["exit_price"] = args.price
    position["exit_time"] = datetime.now(timezone.utc).isoformat()
    position["pnl"] = (args.price - position["entry_price"]) * position["size"]
    
    if args.notes:
        position["notes"] += f" | CLOSE: {args.notes}"
    
    # Update totals
    data["closed"].append(position)
    data["total_pnl"] += position["pnl"]
    save_positions(position_type, data)
    
    audit_log("CLOSE", position_type, f"ID={position['id']} | P&L: ${position['pnl']:.2f}")
    
    pnl_emoji = "📈" if position["pnl"] > 0 else "📉"
    print(f"\n✅ Closed {position_type.upper()} position:")
    print(f"   ID: {position['id']}")
    print(f"   Entry: ${position['entry_price']}")
    print(f"   Exit: ${args.price}")
    print(f"   {pnl_emoji} P&L: ${position['pnl']:.2f}")
    print()

def cmd_list(args):
    """List positions."""
    position_type = args.type or "both"
    
    if position_type in ["paper", "both"]:
        print("\n" + "="*60)
        print("📄 PAPER TRADING POSITIONS")
        print("="*60)
        
        data = load_positions("paper")
        if data["positions"]:
            for pos in data["positions"]:
                print(f"\n{pos['uuid']}: {pos['question']}")
                print(f"   {pos['outcome_name']} @ ${pos['entry_price']} | cost ${pos['cost_basis']:.2f}")
                print(f"   Market value: ${pos['current_value']:.2f}")
        else:
            print("(no open positions)")
    
    if position_type in ["real", "both"]:
        print("\n" + "="*60)
        print("💵 REAL MONEY POSITIONS")
        print("="*60)
        
        data = load_positions("real")
        if data["positions"]:
            for pos in data["positions"]:
                print(f"\n{pos['id']}: {pos['market']}")
                print(f"   {pos['outcome']} @ ${pos['entry_price']} x ${pos['size']}")
                print(f"   P&L: ${pos['pnl']:.2f}")
                if pos['notes']:
                    print(f"   Notes: {pos['notes']}")
        else:
            print("(no open positions)")
    
    print()

def cmd_migrate(args):
    """Migrate position from paper to real (or vice versa)."""
    if "paper" in (args.from_type, args.to_type):
        print("Paper/real migration is retired; the canonical paper ledger cannot mix with real positions.")
        return
    from_type = args.from_type
    to_type = args.to_type
    
    if from_type == to_type:
        print("❌ Error: Can't migrate to same type")
        return
    
    # Load both
    from_data = load_positions(from_type)
    to_data = load_positions(to_type)
    
    # Find position
    position = None
    for i, pos in enumerate(from_data["positions"]):
        if pos["id"] == args.id:
            position = from_data["positions"].pop(i)
            break
    
    if not position:
        print(f"❌ Error: Position {args.id} not found in {from_type} positions")
        return
    
    # Change ID
    old_id = position["id"]
    position["id"] = generate_id(to_type)
    position["notes"] += f" | Migrated from {old_id}"
    
    # Add to new type
    to_data["positions"].append(position)
    
    # Save both
    save_positions(from_type, from_data)
    save_positions(to_type, to_data)
    
    audit_log("MIGRATE", f"{from_type}->{to_type}", f"{old_id} -> {position['id']} | {position['market']}")
    
    print(f"\n✅ Migrated position {old_id} -> {position['id']}")
    print(f"   From: {from_type.upper()}")
    print(f"   To: {to_type.upper()}")
    print(f"   Market: {position['market']}")
    print()

def main():
    parser = argparse.ArgumentParser(description="Position Tracker - Paper vs Real")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # status
    subparsers.add_parser("status", help="Show overall status")
    
    # open
    open_parser = subparsers.add_parser("open", help="Open new position")
    open_parser.add_argument("--type", required=True, choices=["paper", "real"])
    open_parser.add_argument("--market", required=True, help="Market name")
    open_parser.add_argument("--outcome", required=True, help="Outcome (YES/NO/etc)")
    open_parser.add_argument("--price", required=True, type=float, help="Entry price")
    open_parser.add_argument("--size", required=True, type=float, help="Position size ($)")
    open_parser.add_argument("--notes", help="Optional notes")
    open_parser.add_argument("--condition-id", help="Required stable condition ID for paper")
    open_parser.add_argument("--market-slug", help="Required market slug for paper")
    open_parser.add_argument("--event-slug", help="Required event slug for paper")
    open_parser.add_argument("--outcome-id", help="Required outcome token ID for paper")
    
    # close
    close_parser = subparsers.add_parser("close", help="Close position")
    close_parser.add_argument("--id", required=True, help="Position ID")
    close_parser.add_argument("--price", type=float, help="Exit price (real positions only)")
    close_parser.add_argument("--notes", help="Close notes")
    
    # list
    list_parser = subparsers.add_parser("list", help="List positions")
    list_parser.add_argument("--type", choices=["paper", "real", "both"], default="both")
    
    # migrate
    migrate_parser = subparsers.add_parser("migrate", help="Migrate paper <-> real")
    migrate_parser.add_argument("--id", required=True, help="Position ID")
    migrate_parser.add_argument("--from-type", required=True, choices=["paper", "real"], dest="from_type")
    migrate_parser.add_argument("--to-type", required=True, choices=["paper", "real"], dest="to_type")
    
    args = parser.parse_args()
    
    if args.command == "status":
        cmd_status(args)
    elif args.command == "open":
        cmd_open(args)
    elif args.command == "close":
        cmd_close(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "migrate":
        cmd_migrate(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
