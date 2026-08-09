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
    "mlb_research.js",
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


@app.route("/mlb-research")
def mlb_research_page():
    return send_from_directory(HERE, "mlb_research.html")


@app.route("/api/big-money")
def api_big_money():
    from big_money_tape import snapshot
    return jsonify(snapshot())


@app.route("/api/nfl-game-flow")
def api_nfl_game_flow():
    from nfl_schedule import NFLRegistry, PRODUCTION_DB
    registry = NFLRegistry(PRODUCTION_DB, environment="production")
    return jsonify(registry.game_flow_snapshot())


@app.route("/api/mlb-research")
def api_mlb_research():
    from mlb_research import MLBResearchRegistry, DEFAULT_DB
    registry = MLBResearchRegistry(DEFAULT_DB)
    filters = {key: request.args.get(key) for key in (
        "date", "date_from", "date_to", "team", "completeness", "side", "outcome",
        "winner", "pregame_only", "sort") if request.args.get(key) not in (None, "")}
    for key in ("price_min", "price_max", "concentration_min", "concentration_max"):
        if request.args.get(key) not in (None, ""):
            try: filters[key] = float(request.args[key])
            except ValueError: return jsonify({"error": f"{key} must be numeric"}), 400
    try:
        page, per_page = int(request.args.get("page", 1)), int(request.args.get("per_page", 25))
    except ValueError:
        return jsonify({"error": "page and per_page must be integers"}), 400
    return jsonify(registry.research_page(filters, page, per_page))


@app.route("/api/mlb-research/overview")
def api_mlb_research_overview():
    from mlb_research import MLBResearchRegistry, DEFAULT_DB
    return jsonify(MLBResearchRegistry(DEFAULT_DB).overview(request.args.get("date")))


@app.route("/api/mlb-research/games/<game_uuid>")
def api_mlb_research_game(game_uuid):
    from mlb_research import MLBResearchRegistry, DEFAULT_DB
    game = MLBResearchRegistry(DEFAULT_DB).game_detail(game_uuid)
    if game is None: abort(404)
    return jsonify(game)


@app.route("/api/mlb-research/games/<game_uuid>/timeline")
def api_mlb_research_timeline(game_uuid):
    from mlb_research import MLBResearchRegistry, DEFAULT_DB
    try:
        page, per_page = int(request.args.get("page", 1)), int(request.args.get("per_page", 100))
        bucket = int(request.args.get("bucket_minutes", 15))
    except ValueError:
        return jsonify({"error": "timeline pagination values must be integers"}), 400
    summarized = request.args.get("mode", "summary") != "detail"
    result = MLBResearchRegistry(DEFAULT_DB).timeline(
        game_uuid, page=page, per_page=per_page, summarized=summarized, bucket_minutes=bucket)
    if result is None: abort(404)
    return jsonify(result)


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
