#!/usr/bin/env python3
"""
Telegram Morning Report - sends daily Polymarket summary at 8am.

Includes:
- Portfolio status (P&L, positions, exposure)
- Current sports edges
- Open positions (paper vs real)
- Recent closed trades

Usage: python telegram_morning_report.py
"""

import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Windows console defaults to cp1252 and chokes on emoji
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def load_json(filename):
    """Load JSON file, return empty dict if not found."""
    try:
        path = Path(filename)
        if path.exists():
            return json.loads(path.read_text())
        return {}
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return {}

def send_message(text):
    """Send message to Telegram."""
    if not TOKEN or not CHAT_ID:
        print("❌ Telegram not configured (missing TOKEN or CHAT_ID)")
        return False
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    response = requests.post(url, json=data)
    
    if response.status_code == 200:
        return True
    else:
        print(f"❌ Telegram error: {response.status_code}")
        print(response.text)
        return False

def combine_positions(real_data, paper_state):
    """Merge real (synced from API) and paper positions into one view."""
    real_positions = real_data.get('positions', [])
    paper_positions = paper_state.get('open_positions', [])
    total_pnl = real_data.get('total_pnl', 0) + paper_state.get('realized_pnl', 0)
    return {
        'positions': real_positions + paper_positions,
        'real_count': len(real_positions),
        'paper_count': len(paper_positions),
        'total_pnl': total_pnl,
        'history': real_data.get('closed', []) + paper_state.get('closed_positions', []),
    }

def format_portfolio(combined):
    """Format portfolio section."""
    total_pnl = combined['total_pnl']
    positions = combined['positions']
    exposure = sum(p.get('cost_basis', p.get('size', 0)) for p in positions)
    max_exposure = 500

    pnl_emoji = "📈" if total_pnl > 0 else "📉" if total_pnl < 0 else "➡️"

    return f"""*💼 Portfolio*
{pnl_emoji} Total P&L: ${total_pnl:.2f}
📊 Open Positions: {len(positions)} ({combined['real_count']} real, {combined['paper_count']} paper)
💰 Exposure: ${exposure:.0f} / ${max_exposure}"""

def format_edges(edges):
    """Format current edges section."""
    edge_list = edges.get('edges', [])
    
    if not edge_list:
        return "*🎯 Current Edges*\nNo edges found. Next scan in progress..."
    
    lines = ["*🎯 Current Edges*"]
    
    for edge in edge_list[:3]:  # Top 3
        market = edge.get('market', 'Unknown')
        team = edge.get('team', 'YES')
        poly = edge.get('polymarket_prob', 0)
        consensus = edge.get('consensus_prob', 0)
        edge_pct = edge.get('edge_pct', 0)
        liquidity = edge.get('liquidity', 0)
        
        lines.append(f"\n🔥 *{market}*")
        lines.append(f"   → BUY {team}")
        lines.append(f"   Polymarket: {poly:.1f}% | Consensus: {consensus:.1f}%")
        lines.append(f"   Edge: +{edge_pct:.1f}% | Liquidity: ${liquidity/1000000:.1f}M")
    
    return "\n".join(lines)

def format_positions(combined):
    """Format open positions section."""
    positions = combined['positions']

    if not positions:
        return "*📈 Open Positions*\nNone"

    lines = ["*📈 Open Positions*"]

    for pos in positions:
        market = pos.get('question', pos.get('market', 'Unknown'))
        bet = pos.get('bet_type') or pos.get('outcome_name') or f"{pos.get('side', '')} {pos.get('outcome', '?')}".strip()
        size = pos.get('cost_basis', pos.get('size', 0))
        pnl = pos.get('current_value', pos.get('cost_basis', 0)) - pos.get('cost_basis', pos.get('size', 0))
        pos_type = "📄" if pos.get('uuid') else "💵"

        pnl_text = f"+${pnl:.2f}" if pnl > 0 else f"${pnl:.2f}"

        lines.append(f"\n{pos_type} *{market}*")
        lines.append(f"   {bet} | ${size:.0f} | P&L: {pnl_text}")
        for s in pos.get('scenarios', []):
            lines.append(f"   if {s['scenario']}: ${s['pnl']:+.2f}")

    return "\n".join(lines)

def format_history(combined):
    """Format recent closed trades."""
    history = combined.get('history', [])

    if not history:
        return "*📊 Recent Closed*\nNone yet"
    
    recent = history[-3:]  # Last 3
    lines = ["*📊 Recent Closed*"]
    
    for trade in reversed(recent):
        market = trade.get('question', trade.get('market', 'Unknown'))
        pnl = trade.get('realized_pnl', trade.get('pnl', 0))
        result = trade.get('settlement_result', trade.get('result', 'CLOSED'))
        
        emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
        pnl_text = f"+${pnl:.2f}" if pnl > 0 else f"${pnl:.2f}"
        
        lines.append(f"{emoji} {market}: {pnl_text}")
    
    return "\n".join(lines)

def main():
    """Generate and send morning report."""
    print("=== Generating Morning Report ===\n")
    
    # Load data
    real_data = load_json('real_positions.json')
    paper_state = load_json('paper_positions.json')
    edges = load_json('sports_edges.json')
    combined = combine_positions(real_data, paper_state)

    # Build report (%-I is not supported on Windows strftime)
    dt = datetime.now()
    now = dt.strftime(f"%A, %B %d at {dt.strftime('%I').lstrip('0') or '12'}:%M %p")

    report = f"""☀️ *Good Morning! Polymarket Daily Report*
_{now}_

{format_portfolio(combined)}

{format_edges(edges)}

{format_positions(combined)}

{format_history(combined)}

---
📊 View dashboard: `Open Dashboard.cmd`
"""
    
    print(report)
    print("\n" + "="*50 + "\n")
    
    # Send to Telegram
    if send_message(report):
        print("✅ Report sent to Telegram!")
    else:
        print("❌ Failed to send report")

if __name__ == "__main__":
    main()
