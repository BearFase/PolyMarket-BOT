"""Paper/research-only NFL morning report; never mixes real positions."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from nfl_schedule import NFLRegistry, PRODUCTION_DB, parse_time
from paper_trader import PaperTrader

HERE = Path(__file__).parent


def build_report(registry=None, paper=None, now=None):
    registry = registry or NFLRegistry(PRODUCTION_DB, environment="production")
    paper = paper or PaperTrader()
    now = now or datetime.now(ZoneInfo("America/Los_Angeles"))
    today = now.date().isoformat()
    status = registry.status()
    games = registry.list_games()
    today_games = [g for g in games if parse_time(g["scheduled_kickoff_utc"])
                   and parse_time(g["scheduled_kickoff_utc"]).astimezone(now.tzinfo).date().isoformat() == today]
    with registry.connect() as db:
        simulations = db.execute("SELECT result,COUNT(*) count FROM simulation_tracks GROUP BY result").fetchall()
        unresolved_conflicts = db.execute("SELECT COUNT(*) FROM result_conflicts WHERE resolved_at IS NULL").fetchone()[0]
        rejected = db.execute("SELECT COUNT(*) FROM source_links WHERE match_status='REJECTED'").fetchone()[0]
        previous = db.execute("SELECT completed_at FROM workflow_runs WHERE completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1").fetchone()
        completed_since = db.execute("SELECT COUNT(*) FROM games WHERE completion_timestamp IS NOT NULL AND completion_timestamp>?",
                                     (previous[0] if previous else "",)).fetchone()[0]
        largest_wins = db.execute("SELECT COUNT(*) FROM games WHERE largest_buy_side_won=1").fetchone()[0]
        largest_losses = db.execute("SELECT COUNT(*) FROM games WHERE largest_buy_side_won=0").fetchone()[0]
    paper_summary = paper.get_summary()
    sim_text = ", ".join(f"{row['result'] or 'OPEN'} {row['count']}" for row in simulations) or "none"
    game_lines = [f"- {g['away_team_id']} @ {g['home_team_id']} ({g['scheduled_kickoff_local']})" for g in today_games]
    return "\n".join([
        "NFL Research Morning Report",
        f"Production registry: {status['total_games']} games, {status['observations']} observations",
        f"Games today: {len(today_games)}",
        *(game_lines[:8] or ["- none"]),
        f"Simulation tracks: {sim_text}",
        f"Completed since previous report: {completed_since}",
        f"Largest-buy side results: {largest_wins} won / {largest_losses} lost",
        f"Paper bankroll/equity: ${paper_summary.get('cash', paper_summary.get('current_cash', 0)):.2f} / ${paper_summary['total_equity']:.2f}",
        f"Paper open positions: {paper_summary['open_positions']}",
        f"Paper realized/unrealized P&L: ${paper_summary['realized_pnl']:.2f} / ${paper_summary['unrealized_pnl']:.2f}",
        f"Source links requiring attention: {rejected}",
        f"Unresolved result conflicts: {unresolved_conflicts}",
    ])


def send_report(text, session=requests):
    load_dotenv(HERE / ".env")
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"sent": False, "reason": "TELEGRAM_CHAT_ID missing" if token else "TELEGRAM_BOT_TOKEN missing"}
    try:
        response = session.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                json={"chat_id": chat_id, "text": text}, timeout=15)
        response.raise_for_status()
        return {"sent": True, "reason": None}
    except requests.RequestException as exc:
        return {"sent": False, "reason": f"Telegram request failed: {exc.__class__.__name__}"}


if __name__ == "__main__":
    report = build_report()
    print(report)
    print(json.dumps(send_report(report), indent=2))
