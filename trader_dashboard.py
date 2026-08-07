"""Read-only local dashboard routes for the active application suite.

Whale/trader-scanner routes are intentionally inactive. Their research
modules remain available for manual study but are not imported here.
"""

import os
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from system_status import dashboard_status

app = Flask(__name__)
APP_STARTED_AT = time.time()
HERE = Path(__file__).parent
DASHBOARD_ASSETS = {
    "dashboard_data.js",
    "real_positions.json",
    "sports_edges.json",
    "price_history.json",
    "game_flow.js",
    "game_flow_ui.js",
    "postgame_research.js",
}


@app.route("/api/health")
def health():
    """Small, dependency-free readiness contract used by the launcher."""
    return jsonify({
        "status": "ok",
        "service": "polymarket-dashboard",
        "pid": os.getpid(),
        "started_at": APP_STARTED_AT,
    })


@app.route("/")
def home():
    return send_from_directory(HERE, "dashboard_live.html")


@app.route("/game-flow")
def game_flow_page():
    return send_from_directory(HERE, "game_flow_dashboard.html")


@app.route("/api/big-money")
def api_big_money():
    from big_money_tape import snapshot
    return jsonify(snapshot())


@app.route("/api/nfl-game-flow")
def api_nfl_game_flow():
    from nfl_schedule import NFLRegistry, PRODUCTION_DB
    registry = NFLRegistry(PRODUCTION_DB, environment="production")
    return jsonify(registry.game_flow_snapshot())


@app.route("/api/nfl-games/<game_uuid>/research-summary")
def api_nfl_research_summary(game_uuid):
    from nfl_postgame_research import get_postgame_summary
    from nfl_schedule import NFLRegistry, PRODUCTION_DB
    registry = NFLRegistry(PRODUCTION_DB, environment="production")
    summary = get_postgame_summary(registry, game_uuid)
    if summary is None:
        abort(404)
    return jsonify(summary)


@app.route("/api/nfl-games/<game_uuid>/analyst-notes", methods=["POST"])
def api_nfl_analyst_notes(game_uuid):
    from nfl_postgame_research import save_analyst_notes
    from nfl_schedule import NFLRegistry, PRODUCTION_DB
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("notes"), dict):
        return jsonify({"error": "notes object is required"}), 400
    registry = NFLRegistry(PRODUCTION_DB, environment="production")
    try:
        saved = save_analyst_notes(registry, game_uuid, body["notes"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(saved), 201


@app.route("/api/system-status")
def api_system_status():
    return jsonify(dashboard_status())


@app.route("/<path:filename>")
def dashboard_asset(filename):
    if filename not in DASHBOARD_ASSETS:
        abort(404)
    return send_from_directory(HERE, filename)


@app.after_request
def disable_dashboard_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    print("Run dashboard_server.py to start the unified dashboard.")
