#!/usr/bin/env python3
"""Canonical, deduplicated Telegram notifications for NFL research operations.

This module reads research and paper-simulation data. It never creates trades,
changes paper cash, reads real positions, or participates in result ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from dotenv import load_dotenv

from nfl_schedule import DEFAULT_CONFIG, NFLRegistry, PRODUCTION_DB, parse_time, utc_now
from paper_trader import PaperTrader

HERE = Path(__file__).resolve().parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FINAL_STATUSES = {"FINAL"}
WARNING_TYPES = {"SOURCE_OUTAGE", "ORPHAN_GAME_FLOW", "RESULT_CONFLICT",
                 "MATCHING_REJECTIONS", "WORKFLOW_FAILURE", "RUNTIME_DATA"}


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().casefold() not in {"0", "false", "no", "off", ""}


def _money(value: Any) -> str:
    return "unavailable" if value is None else f"${float(value):,.2f}"


def _cents(value: Any) -> str:
    return "unavailable" if value is None else f"{round(float(value) * 100):.0f}¢"


def _result_icon(value: Any) -> str:
    return "✅" if value in (True, "WIN") else "❌" if value in (False, "LOSS") else "—"


def sanitized_error(exc: Exception | str) -> str:
    text = f"{exc.__class__.__name__}: delivery failed" if isinstance(exc, Exception) else str(exc)
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[REDACTED]", text)
    text = re.sub(r"(?i)(token|secret|api[_-]?key|chat[_-]?id)\s*[=:]\s*\S+", r"\1=[REDACTED]", text)
    return text[:500]


def load_settings(path: Path = DEFAULT_CONFIG) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    env = os.environ
    settings = {
        "enabled": _bool(env.get("TELEGRAM_NOTIFICATIONS_ENABLED", raw.get("telegram_notifications_enabled")), True),
        "morning_enabled": _bool(env.get("TELEGRAM_MORNING_BRIEF_ENABLED", raw.get("telegram_morning_brief_enabled")), True),
        "morning_hour": int(env.get("TELEGRAM_MORNING_HOUR_LOCAL", raw.get("telegram_morning_hour_local", 7))),
        "pregame_enabled": _bool(env.get("TELEGRAM_PREGAME_ALERTS_ENABLED", raw.get("telegram_pregame_alerts_enabled")), True),
        "pregame_minutes": int(env.get("TELEGRAM_PREGAME_MINUTES_BEFORE", raw.get("telegram_pregame_minutes_before", 60))),
        "final_enabled": _bool(env.get("TELEGRAM_FINAL_ALERTS_ENABLED", raw.get("telegram_final_alerts_enabled")), True),
        "warnings_enabled": _bool(env.get("TELEGRAM_SYSTEM_WARNINGS_ENABLED", raw.get("telegram_system_warnings_enabled")), True),
        "warning_cooldown": int(env.get("TELEGRAM_WARNING_COOLDOWN_MINUTES", raw.get("telegram_warning_cooldown_minutes", 180))),
        "timezone": env.get("TELEGRAM_TIMEZONE", raw.get("telegram_timezone", "America/Los_Angeles")),
    }
    if not 0 <= settings["morning_hour"] <= 23 or settings["pregame_minutes"] < 1 or settings["warning_cooldown"] < 1:
        raise ValueError("invalid Telegram timing configuration")
    try:
        settings["tz"] = ZoneInfo(settings["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError("IANA timezone data unavailable; install the requirements.txt tzdata dependency") from exc
    return settings


class ReadOnlyPaperLedger:
    """Read canonical paper accounting without rewriting runtime metadata."""
    def __init__(self, path: Path = HERE / "paper_positions.json"):
        self.state = json.loads(path.read_text(encoding="utf-8"))
        if self.state.get("version") != 1:
            raise RuntimeError("unsupported canonical paper ledger version")

    def get_summary(self) -> dict:
        state = self.state
        return {"starting_bankroll": state["starting_bankroll"], "cash": state["current_cash"],
          "open_positions": len(state["open_positions"]), "closed_trades": len(state["closed_positions"]),
          "current_exposure": state["open_exposure"],
          "open_market_value": sum(item["current_value"] for item in state["open_positions"]),
          "realized_pnl": state["realized_pnl"], "unrealized_pnl": state["unrealized_pnl"],
          "total_equity": state["total_equity"]}


class TelegramNotificationCenter:
    def __init__(self, registry: NFLRegistry | None = None, paper: PaperTrader | None = None,
                 session=requests, config_path: Path = DEFAULT_CONFIG):
        load_dotenv(HERE / ".env")
        self.registry = registry or NFLRegistry(PRODUCTION_DB, environment="production")
        self.paper = paper or ReadOnlyPaperLedger()
        self.session = session
        self.settings = load_settings(config_path)

    def _journal(self, notification_type: str, text: str, dedupe_key: str,
                 status: str, *, game_uuid: str | None = None,
                 reporting_date: str | None = None, record_uuid: str | None = None,
                 warning_code: str | None = None, message_id: str | None = None,
                 failure: str | None = None) -> dict:
        now = utc_now()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self.registry.connect() as db:
            retry = db.execute("SELECT COUNT(*) FROM notification_journal WHERE dedupe_key=? AND delivery_status='FAILED'",
                               (dedupe_key,)).fetchone()[0]
            notification_uuid = str(uuid.uuid4())
            db.execute("""INSERT INTO notification_journal VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (notification_uuid, notification_type, game_uuid, reporting_date, record_uuid,
               warning_code, dedupe_key, digest, now, now, status, message_id, retry,
               failure, now if status == "DELIVERED" else None,
               json.dumps({"text": text}, ensure_ascii=False),))
        return {"notification_uuid": notification_uuid, "status": status,
                "message_id": message_id, "retry_count": retry, "failure": failure}

    def _delivered(self, dedupe_key: str) -> bool:
        with self.registry.connect() as db:
            return db.execute("SELECT 1 FROM notification_journal WHERE dedupe_key=? AND delivery_status='DELIVERED' LIMIT 1",
                              (dedupe_key,)).fetchone() is not None

    def _send(self, notification_type: str, text: str, dedupe_key: str, *, force=False,
              game_uuid=None, reporting_date=None, record_uuid=None, warning_code=None) -> dict:
        if self._delivered(dedupe_key) and not force:
            return {"status": "SUPPRESSED", "reason": "duplicate", "dedupe_key": dedupe_key}
        if not self.settings["enabled"]:
            return {"status": "SKIPPED", "reason": "notifications disabled"}
        token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            failure = "Telegram configuration incomplete"
            return self._journal(notification_type, text, dedupe_key, "FAILED", game_uuid=game_uuid,
                                 reporting_date=reporting_date, record_uuid=record_uuid,
                                 warning_code=warning_code, failure=failure)
        try:
            response = self.session.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=15)
            response.raise_for_status()
            payload = response.json()
            message_id = str((payload.get("result") or {}).get("message_id") or "") or None
            return self._journal(notification_type, text, dedupe_key, "DELIVERED", game_uuid=game_uuid,
                                 reporting_date=reporting_date, record_uuid=record_uuid,
                                 warning_code=warning_code, message_id=message_id)
        except Exception as exc:
            return self._journal(notification_type, text, dedupe_key, "FAILED", game_uuid=game_uuid,
                                 reporting_date=reporting_date, record_uuid=record_uuid,
                                 warning_code=warning_code, failure=sanitized_error(exc))

    def _local(self, timestamp: str | None) -> datetime | None:
        parsed = parse_time(timestamp) if timestamp else None
        return parsed.astimezone(self.settings["tz"]) if parsed else None

    def _today_games(self, now: datetime) -> list[dict]:
        return [game for game in self.registry.list_games()
                if self._local(game["scheduled_kickoff_utc"]) and
                self._local(game["scheduled_kickoff_utc"]).date() == now.date()]

    def _track_record(self, name: str, *, since: str | None = None) -> tuple[int, int]:
        query = """SELECT result FROM simulation_tracks s JOIN games g ON g.game_uuid=s.canonical_game_uuid
          WHERE s.track_name=? AND s.result IN ('WIN','LOSS')"""
        params: list[Any] = [name]
        if since:
            query += " AND g.completion_timestamp>?"; params.append(since)
        with self.registry.connect() as db:
            rows = db.execute(query, params).fetchall()
        return sum(row[0] == "WIN" for row in rows), sum(row[0] == "LOSS" for row in rows)

    def build_morning_brief(self, now: datetime | None = None, *, test=False) -> tuple[str, str]:
        now = (now or datetime.now(self.settings["tz"])).astimezone(self.settings["tz"])
        date_key = now.date().isoformat()
        games = self._today_games(now)
        paper = self.paper.get_summary()
        with self.registry.connect() as db:
            prior = db.execute("""SELECT delivered_timestamp FROM notification_journal
              WHERE notification_type='MORNING_BRIEF' AND delivery_status='DELIVERED'
              ORDER BY delivered_timestamp DESC LIMIT 1""").fetchone()
            since = prior[0] if prior else ""
            completed_since = db.execute("SELECT COUNT(*) FROM games WHERE completion_timestamp>?", (since,)).fetchone()[0]
            completed = db.execute("SELECT COUNT(*) FROM games WHERE game_status='FINAL'").fetchone()[0]
            summaries = db.execute("SELECT COUNT(DISTINCT canonical_game_uuid) FROM postgame_research_records").fetchone()[0]
            orphans = db.execute("SELECT COUNT(*) FROM observations WHERE source_type='GAME_FLOW_STREAM' AND match_accepted=0").fetchone()[0]
            rejected = db.execute("SELECT COUNT(*) FROM source_links WHERE match_status='REJECTED'").fetchone()[0]
            conflicts = db.execute("SELECT COUNT(*) FROM result_conflicts WHERE resolved_at IS NULL").fetchone()[0]
        lines = ["🧪 TEST — NOTIFICATION CENTER" if test else "🏈 NFL RESEARCH MORNING BRIEF",
                 now.strftime("%A, %B %d, %Y"), "", "TODAY"]
        if games:
            for game in games:
                kickoff = self._local(game["scheduled_kickoff_utc"])
                label = "Hall of Fame Game" if game["season_type"] == "HOF" else f"Week {game['week']}"
                lines += [f"• {game['away_team_name']} @ {game['home_team_name']}",
                          f"  {game['season_type']} · {label}", f"  Kickoff: {kickoff.strftime('%-I:%M %p %Z') if os.name != 'nt' else kickoff.strftime('%I:%M %p %Z').lstrip('0')}"]
        else: lines.append("• No NFL games scheduled today")
        lines += ["", "PAPER PORTFOLIO",
                  f"• Starting bankroll: {_money(paper['starting_bankroll'])}", f"• Cash: {_money(paper['cash'])}",
                  f"• Total equity: {_money(paper['total_equity'])}", f"• Open positions: {paper['open_positions']}",
                  f"• Open exposure: {_money(paper['current_exposure'])}", f"• Realized P&L: {_money(paper['realized_pnl'])}",
                  f"• Unrealized P&L: {_money(paper['unrealized_pnl'])}"]
        if not paper["open_positions"]: lines.append("• No paper trades are open")
        names = [("Largest-buy track", "LARGEST_QUALIFYING_BUY"), ("Sportsbook favorite", "SPORTSBOOK_CONSENSUS_FAVORITE"),
                 ("Polymarket favorite", "POLYMARKET_PREGAME_FAVORITE"), ("Home team track", "HOME_TEAM"), ("Away team track", "AWAY_TEAM")]
        lines += ["", "RESEARCH SEASON", f"• Completed games: {completed}", f"• Research summaries: {summaries}",
                  f"• Completed since prior brief: {completed_since}"]
        for label, name in names:
            wins, losses = self._track_record(name); lines.append(f"• {label}: {wins}-{losses}")
        lines += ["", "SYSTEM", "✅ Canonical registry", "✅ Game Flow", "✅ Results", "✅ Paper ledger", "✅ Telegram"]
        attention = []
        if orphans: attention.append(f"• {orphans} orphan Game Flow trades")
        if rejected: attention.append(f"• {rejected} intentionally rejected source links")
        if conflicts: attention.append(f"• {conflicts} unresolved result conflicts")
        if attention: lines += ["", "ATTENTION", *attention]
        lines += ["", "Research observations only.", "No real orders or automatic paper entries."]
        return "\n".join(lines), date_key

    def send_morning_brief(self, now=None, *, preview=False, force=False, test=False) -> dict:
        text, date_key = self.build_morning_brief(now, test=test)
        if preview: return {"status": "PREVIEW", "text": text}
        if not self.settings["morning_enabled"]: return {"status": "SKIPPED", "reason": "morning brief disabled"}
        notification_type = "TEST_MORNING_BRIEF" if test else "MORNING_BRIEF"
        dedupe_key = f"test-morning:{date_key}" if test else f"morning:{date_key}"
        return self._send(notification_type, text, dedupe_key, force=force,
                          reporting_date=date_key)

    def due_pregame(self, now: datetime | None = None) -> list[dict]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        window = timedelta(minutes=self.settings["pregame_minutes"])
        return [g for g in self.registry.list_games() if g["game_status"] not in FINAL_STATUSES
                and parse_time(g["scheduled_kickoff_utc"]) is not None
                and now <= parse_time(g["scheduled_kickoff_utc"]) <= now + window]

    def build_pregame_alert(self, game_uuid: str) -> str:
        game = next((g for g in self.registry.list_games() if g["game_uuid"] == game_uuid), None)
        if not game: raise ValueError("canonical game not found")
        kickoff = parse_time(game["scheduled_kickoff_utc"])
        if game["game_status"] in FINAL_STATUSES or kickoff <= datetime.now(timezone.utc):
            raise ValueError("pregame alert is not valid after kickoff")
        with self.registry.connect() as db:
            links = db.execute("SELECT source_type FROM source_links WHERE canonical_game_uuid=? AND match_status='ACCEPTED'", (game_uuid,)).fetchall()
            buys = db.execute("SELECT team_id,amount_usd,execution_price FROM game_flow_activity WHERE canonical_game_uuid=? ORDER BY amount_usd DESC", (game_uuid,)).fetchall()
        link_types = {row[0] for row in links}
        activity = []
        for team_id in (game["away_team_id"], game["home_team_id"]):
            row = next((item for item in buys if item["team_id"] == team_id), None)
            activity.append(f"• {self.registry.team_name(team_id)}: {_money(row['amount_usd'])} @ {_cents(row['execution_price'])}" if row else f"• {self.registry.team_name(team_id)}: no qualifying trades")
        warnings = int("ODDS_API" not in link_types) + int("POLYMARKET_US" not in link_types)
        local = self._local(game["scheduled_kickoff_utc"])
        return "\n".join(["🏈 GAME FLOW READY", "", f"{game['away_team_name']} @ {game['home_team_name']}",
          f"{game['season_type']} · Week {game['week']}", f"Kickoff: {local.strftime('%I:%M %p %Z').lstrip('0')}", "",
          "Game Flow is collecting:", "• Largest qualifying buys by side", "• Execution prices",
          "• Sportsbook snapshots", "• Polymarket US snapshots", "• Pregame market movement", "",
          "Current activity:", *activity, "", "Data quality:", "✅ Canonical game verified",
          "✅ Market linked" if "POLYMARKET_US" in link_types else "⚠ Polymarket US market unavailable",
          "✅ Pregame status", f"⚠ {warnings} source warning" if warnings else "✅ Sources verified", "",
          "Research recording is active.", "No paper or real entry was generated."])

    def process_pregame(self, now=None, *, preview=False) -> list[dict]:
        if not self.settings["pregame_enabled"]: return []
        results = []
        for game in self.due_pregame(now):
            text = self.build_pregame_alert(game["game_uuid"])
            results.append({"status": "PREVIEW", "text": text, "game_uuid": game["game_uuid"]} if preview else
              self._send("PREGAME_ALERT", text, f"pregame:{game['game_uuid']}", game_uuid=game["game_uuid"]))
        return results

    def due_finals(self) -> list[dict]:
        with self.registry.connect() as db:
            return [dict(row) for row in db.execute("""SELECT r.*,g.away_team_name,g.home_team_name,g.away_score,g.home_score,
              g.final_winner_team_id,g.result_source,g.source_result_id FROM postgame_research_records r
              JOIN games g ON g.game_uuid=r.canonical_game_uuid WHERE g.game_status='FINAL'
              AND g.result_source IS NOT NULL AND g.source_result_id IS NOT NULL
              AND r.revision_number=(SELECT MAX(r2.revision_number) FROM postgame_research_records r2
                WHERE r2.canonical_game_uuid=r.canonical_game_uuid)
              ORDER BY r.created_at""")]

    def build_final_alert(self, record: dict) -> str:
        payload = json.loads(record["payload_json"])
        info, results = payload["game_information"], payload["research_results"]
        largest = payload["market_snapshot"].get("largest_recorded_buy")
        correction = record["revision_number"] > 1
        lines = ["🏁 CORRECTED FINAL — RESEARCH SUMMARY" if correction else "🏁 FINAL — RESEARCH SUMMARY READY", "",
                 f"{info['away_team']} {info['away_score']}", f"{info['home_team']} {info['home_score']}", "",
                 f"Winner: {info['winner']}", "", "RESEARCH RESULTS",
                 f"{_result_icon(results['largest_buy_side_won'])} Largest-buy side {'won' if results['largest_buy_side_won'] else 'lost' if results['largest_buy_side_won'] is False else 'unavailable'}",
                 f"{_result_icon(results['sportsbook_favorite_won'])} Sportsbook favorite {'won' if results['sportsbook_favorite_won'] else 'lost' if results['sportsbook_favorite_won'] is False else 'unavailable'}",
                 f"{_result_icon(results['polymarket_favorite_won'])} Polymarket favorite {'won' if results['polymarket_favorite_won'] else 'lost' if results['polymarket_favorite_won'] is False else 'unavailable'}", "", "LARGEST BUY"]
        lines += ([f"• {self.registry.team_name(largest['team_id'])}", f"• {_money(largest['amount_usd'])} @ {_cents(largest['execution_price'])}"] if largest else ["• No qualifying buy recorded"])
        linked = [position for position in (*self.paper.state.get("open_positions", []), *self.paper.state.get("closed_positions", []))
                  if position.get("canonical_game_uuid") == record["canonical_game_uuid"]]
        paper_line = "• No canonical paper position was linked to this game"
        if linked:
            position = linked[-1]
            paper_line = f"• {position.get('outcome_name', 'side unavailable')} · {position.get('status', 'status unavailable')}"
            if position.get("realized_pnl") is not None: paper_line += f" · realized P&L {_money(position['realized_pnl'])}"
        lines += ["", "Paper portfolio:", paper_line,
                  "", f"Research Summary revision {record['revision_number']} is ready in Game Flow.",
                  "Research comparisons only; not picks or orders."]
        return "\n".join(lines)

    def process_finals(self, *, preview=False) -> list[dict]:
        if not self.settings["final_enabled"]: return []
        results = []
        for record in self.due_finals():
            text = self.build_final_alert(record)
            key = f"final:{record['record_uuid']}:{record['content_hash']}"
            results.append({"status": "PREVIEW", "text": text, "game_uuid": record["canonical_game_uuid"]} if preview else
              self._send("FINAL_ALERT", text, key, game_uuid=record["canonical_game_uuid"], record_uuid=record["record_uuid"]))
        return results

    def warning_candidates(self) -> list[dict]:
        candidates = []
        with self.registry.connect() as db:
            orphan = db.execute("SELECT COUNT(*) FROM observations WHERE source_type='GAME_FLOW_STREAM' AND match_accepted=0").fetchone()[0]
            conflicts = db.execute("SELECT COUNT(*) FROM result_conflicts WHERE resolved_at IS NULL").fetchone()[0]
            rejected = db.execute("SELECT COUNT(*) FROM source_links WHERE match_status='REJECTED'").fetchone()[0]
            latest = db.execute("SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if orphan: candidates.append({"code": "ORPHAN_GAME_FLOW", "count": orphan, "detail": "Game Flow trades could not be attached to a canonical game."})
        if conflicts: candidates.append({"code": "RESULT_CONFLICT", "count": conflicts, "detail": "Authoritative result conflicts remain unresolved; settlement was withheld."})
        if rejected: candidates.append({"code": "MATCHING_REJECTIONS", "count": rejected, "detail": "Source links were rejected rather than matched uncertainly."})
        if latest and latest["status"] != "SUCCESS":
            candidates.append({"code": "WORKFLOW_FAILURE", "count": 1, "detail": "The latest workflow completed with isolated failures; prior data was preserved."})
            failed_steps = {item.get("step", "") for item in json.loads(latest["sanitized_errors_json"] or "[]")}
            sources = sorted(step for step in failed_steps if step in {"odds_api_link", "polymarket_us_link", "result_refresh"})
            if sources:
                candidates.append({"code": "SOURCE_OUTAGE", "count": len(sources),
                                   "detail": "One or more canonical source steps were unavailable; prior successful observations were preserved."})
        return candidates

    def build_warning(self, warning: dict) -> str:
        return "\n".join(["⚠ NFL RESEARCH WARNING", "", f"Code: {warning['code']}",
          f"Affected records: {warning['count']}", "", warning["detail"], "",
          "No observation, paper entry, settlement, or result was fabricated."])

    def process_warnings(self, *, preview=False, now=None) -> list[dict]:
        if not self.settings["warnings_enabled"]: return []
        now = now or datetime.now(timezone.utc); results = []
        warnings = self.warning_candidates()
        active_codes = {item["code"] for item in warnings}
        with self.registry.connect() as db:
            prior_codes = {row[0] for row in db.execute("""SELECT DISTINCT warning_code FROM notification_journal
              WHERE notification_type='SYSTEM_WARNING' AND delivery_status='DELIVERED' AND warning_code IS NOT NULL""")}
            latest_run = db.execute("SELECT run_uuid FROM workflow_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        for code in sorted(({"SOURCE_OUTAGE", "WORKFLOW_FAILURE"} & prior_codes) - active_codes):
            recovery_code = f"RECOVERY_{code}"
            warnings.append({"code": recovery_code, "count": 0,
                             "detail": f"{code.replace('_', ' ').title()} has recovered. Canonical collection is operating again.",
                             "recovery_key": latest_run[0] if latest_run else utc_now()[:10]})
        for warning in warnings:
            key = f"warning:{warning['code']}:{warning['count']}"
            if warning.get("recovery_key"):
                key = f"recovery:{warning['code']}:{warning['recovery_key']}"
            with self.registry.connect() as db:
                recent = db.execute("""SELECT attempted_timestamp FROM notification_journal
                  WHERE warning_code=? AND delivery_status='DELIVERED' ORDER BY attempted_timestamp DESC LIMIT 1""",
                  (warning["code"],)).fetchone()
            if recent and not warning["code"].startswith("RECOVERY_") and parse_time(recent[0]) > now - timedelta(minutes=self.settings["warning_cooldown"]):
                results.append({"status": "SUPPRESSED", "reason": "cooldown", "warning_code": warning["code"]}); continue
            text = self.build_warning(warning)
            results.append({"status": "PREVIEW", "text": text, "warning_code": warning["code"]} if preview else
              self._send("SYSTEM_WARNING", text, key, warning_code=warning["code"]))
        return results

    def morning_due(self, now=None) -> bool:
        now = (now or datetime.now(self.settings["tz"])).astimezone(self.settings["tz"])
        if not self.settings["morning_enabled"] or now.hour < self.settings["morning_hour"]:
            return False
        with self.registry.connect() as db:
            delivered = db.execute("""SELECT 1 FROM notification_journal
              WHERE notification_type='MORNING_BRIEF' AND reporting_date=?
                AND delivery_status='DELIVERED' LIMIT 1""",
              (now.date().isoformat(),)).fetchone()
        return delivered is None

    def journal_rows(self) -> list[dict]:
        with self.registry.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM notification_journal ORDER BY attempted_timestamp")]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    for name in ("morning", "pregame", "finals", "warnings"):
        item = sub.add_parser(name)
        item.add_argument("--preview", action="store_true")
        item.add_argument("--send", action="store_true")
        if name == "morning":
            item.add_argument("--force", action="store_true"); item.add_argument("--test", action="store_true")
        if name in ("pregame", "finals"):
            item.add_argument("--due", action="store_true")
    args = parser.parse_args(argv)
    if not args.preview and not args.send:
        parser.error("choose --preview or --send")
    center = TelegramNotificationCenter()
    if args.kind == "morning": result = center.send_morning_brief(preview=args.preview, force=args.force, test=args.test)
    elif args.kind == "pregame": result = center.process_pregame(preview=args.preview)
    elif args.kind == "finals": result = center.process_finals(preview=args.preview)
    else: result = center.process_warnings(preview=args.preview)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
