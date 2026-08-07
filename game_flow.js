(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GameFlow = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MAX_BUYS_PER_SIDE = 5;
  const SORTS = new Set(["smart", "kickoff", "kickoff-desc", "activity", "largest-buy", "matchup", "matchup-desc"]);
  const SPORTS = new Set(["all", "nfl", "mlb"]);
  const SEASON_TYPES = new Set(["all", "hof", "pre", "reg", "post"]);
  const STATUSES = new Set(["all", "upcoming", "live", "final", "postponed"]);
  const DATES = new Set(["all", "today", "upcoming", "completed"]);

  function timeValue(value) {
    if (!value) return 0;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    const normalized = String(value).replace(/(\.\d{3})\d+(Z$)/, "$1$2");
    const parsed = Date.parse(normalized);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function teamsFromTitle(title) {
    const teams = String(title || "").split(/\s+vs\.?\s+/i);
    return teams.length === 2
      ? {away: teams[0].trim(), home: teams[1].trim()}
      : null;
  }

  function startTime(row) {
    if (row.game_start_time || row.start_time) {
      return timeValue(row.game_start_time || row.start_time);
    }
    const question = String(row.question || "");
    const scheduled = question.match(
      /scheduled for ([A-Z][a-z]+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2} [AP]M) UTC/i
    );
    if (scheduled) return timeValue(`${scheduled[1]} ${scheduled[2]} UTC`);
    const slugDate = String(row.event_slug || "").match(/(\d{4}-\d{2}-\d{2})$/);
    return slugDate ? timeValue(`${slugDate[1]}T00:00:00Z`) : 0;
  }

  function isMoneylineBuy(row, minimum) {
    return String(row.league || "").toLowerCase() === "mlb"
      && String(row.status || "").toUpperCase() === "OPEN"
      && Number(row.risk_usd || 0) >= minimum
      && /moneyline/i.test(String(row.selection || ""));
  }

  function groupGameFlow(rows, minimumDisplayUsd) {
    const minimum = Number(minimumDisplayUsd || 0);
    const grouped = new Map();

    (rows || []).filter(row => isMoneylineBuy(row, minimum)).forEach(row => {
      const teams = teamsFromTitle(row.event_title);
      if (!teams || !row.event_slug) return;
      const rawSide = String(row.raw_selection || "").trim();
      const side = [teams.away, teams.home].find(
        team => team.toLowerCase() === rawSide.toLowerCase()
      );
      if (!side) return;

      if (!grouped.has(row.event_slug)) {
        grouped.set(row.event_slug, {
          event_slug: row.event_slug,
          away: teams.away,
          home: teams.home,
          market: "Moneyline",
          start_time: startTime(row),
          last_activity: 0,
          probabilities: {},
          buys: {[teams.away]: [], [teams.home]: []},
          _latest_price_time: 0,
          status: row.game_status || row.event_status || "UPCOMING",
        });
      }

      const game = grouped.get(row.event_slug);
      const activity = timeValue(row.trade_time);
      game.last_activity = Math.max(game.last_activity, activity);
      game.start_time = game.start_time || startTime(row);
      game.buys[side].push({
        id: row.id,
        risk_usd: Number(row.risk_usd || 0),
        entry_price: Number(row.entry_price || 0),
        trade_time: row.trade_time,
      });

      if (activity >= game._latest_price_time) {
        const selectedProbability = Number(row.entry_price || 0) * 100;
        const other = side === game.away ? game.home : game.away;
        game.probabilities[side] = selectedProbability;
        game.probabilities[other] = 100 - selectedProbability;
        game._latest_price_time = activity;
      }
    });

    const games = Array.from(grouped.values());
    games.forEach(game => {
      [game.away, game.home].forEach(team => {
        game.buys[team].sort((a, b) =>
          b.risk_usd - a.risk_usd || timeValue(b.trade_time) - timeValue(a.trade_time)
        );
        game.buys[team] = game.buys[team].slice(0, MAX_BUYS_PER_SIDE);
      });
      delete game._latest_price_time;
    });
    games.sort((a, b) =>
      b.last_activity - a.last_activity || a.start_time - b.start_time
    );
    return games;
  }

  function normalizeSpace(value) {
    return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
  }

  function statusBucket(game, nowMs) {
    const raw = String(game.status || "").toUpperCase();
    if (["LIVE", "IN_PROGRESS", "IN PROGRESS", "HALFTIME"].includes(raw)) return "live";
    if (["FINAL", "COMPLETED", "CLOSED"].includes(raw)) return "final";
    if (["POSTPONED", "CANCELED", "CANCELLED", "SUSPENDED", "NO_CONTEST"].includes(raw)) return "postponed";
    return "upcoming";
  }

  function matchup(game) { return `${game.away || ""} @ ${game.home || ""}`.trim(); }

  function searchText(game) {
    return normalizeSpace([
      matchup(game), game.away, game.home, game.away_team_id, game.home_team_id,
      game.canonical_game_id, game.event_slug, game.search_aliases,
    ].filter(Boolean).join(" "));
  }

  function matchesSearch(game, query) {
    const tokens = normalizeSpace(query).split(" ").filter(Boolean);
    const haystack = searchText(game);
    return !tokens.length || tokens.every(token => haystack.includes(token));
  }

  function localDay(value) {
    const time = timeValue(value);
    if (!time) return "";
    const date = new Date(time);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function largestBuy(game) {
    const groups = Object.values(game.buys || {});
    return Math.max(0, ...groups.flat().map(row => Number(row.amount_usd ?? row.risk_usd ?? 0)));
  }

  function stableKey(game) {
    return String(game.canonical_game_id || game.game_uuid || game.event_slug || matchup(game));
  }

  function defaultState() {
    return {q: "", sport: "all", season_type: "all", week: "all", status: "all",
      date: "all", sort: "smart", live_first: true, quick: "all"};
  }

  function parseState(queryString, preferences) {
    const params = new URLSearchParams(String(queryString || "").replace(/^\?/, ""));
    const state = defaultState();
    const storedSort = preferences && SORTS.has(preferences.sort) ? preferences.sort : null;
    const storedLive = preferences && typeof preferences.live_first === "boolean" ? preferences.live_first : null;
    state.sort = storedSort || state.sort;
    if (storedLive !== null) state.live_first = storedLive;
    state.q = String(params.get("q") || "").trim().replace(/\s+/g, " ");
    const values = {sport: SPORTS, season_type: SEASON_TYPES, status: STATUSES, date: DATES, sort: SORTS};
    Object.entries(values).forEach(([key, allowed]) => {
      const value = String(params.get(key) || "").toLowerCase();
      if (allowed.has(value)) state[key] = value;
    });
    const week = params.get("week");
    if (week && /^[A-Za-z0-9_-]+$/.test(week)) state.week = week;
    if (params.has("live_first")) state.live_first = params.get("live_first") !== "0";
    const quick = String(params.get("quick") || "").toLowerCase();
    if (["all", "today", "preseason", "live", "finals"].includes(quick)) state.quick = quick;
    else if (["q", "sport", "season_type", "week", "status", "date", "sort", "live_first"].some(key => params.has(key))) state.quick = "";
    return state;
  }

  function serializeState(state) {
    const params = new URLSearchParams();
    const defaults = defaultState();
    ["q", "sport", "season_type", "week", "status", "date", "sort", "quick"].forEach(key => {
      if (state[key] && state[key] !== defaults[key]) params.set(key, state[key]);
    });
    if (!state.live_first) params.set("live_first", "0");
    const value = params.toString();
    return value ? `?${value}` : "";
  }

  function applyQuickView(state, quick) {
    const next = {...state, q: "", sport: "all", season_type: "all", week: "all", status: "all", date: "all", quick};
    if (quick === "today") next.date = "today";
    if (quick === "preseason") { next.sport = "nfl"; next.season_type = "pre"; }
    if (quick === "live") next.status = "live";
    if (quick === "finals") next.status = "final";
    return next;
  }

  function filterGames(games, state, nowMs) {
    const today = localDay(nowMs);
    return (games || []).filter(game => {
      const status = statusBucket(game, nowMs);
      const kickoff = timeValue(game.kickoff || game.start_time);
      if (!matchesSearch(game, state.q)) return false;
      if (state.sport !== "all" && String(game.sport || "").toLowerCase() !== state.sport) return false;
      if (state.season_type !== "all" && String(game.season_type || "").toLowerCase() !== state.season_type) return false;
      if (state.week !== "all" && String(game.week) !== state.week) return false;
      if (state.status !== "all" && status !== state.status) return false;
      if (state.date === "today" && localDay(kickoff) !== today) return false;
      if (state.date === "upcoming" && (status === "final" || !kickoff || kickoff < nowMs)) return false;
      if (state.date === "completed" && status !== "final") return false;
      return true;
    });
  }

  function smartRank(game, nowMs) {
    const status = statusBucket(game, nowMs), kickoff = timeValue(game.kickoff || game.start_time);
    if (status === "live") return [0, kickoff || Number.MAX_SAFE_INTEGER];
    if (status === "upcoming" && kickoff && localDay(kickoff) === localDay(nowMs)) return [1, kickoff];
    if (status === "upcoming" && kickoff) return [2, kickoff];
    if (status === "final") return [3, -(timeValue(game.completion_timestamp) || kickoff || 0)];
    if (kickoff) return [4, kickoff];
    return [5, 0];
  }

  function sortGames(games, state, nowMs) {
    const alpha = state.sort === "matchup" || state.sort === "matchup-desc";
    const liveFirst = state.live_first && !alpha;
    const direction = state.sort === "matchup-desc" ? -1 : 1;
    return [...games].sort((a, b) => {
      if (liveFirst) {
        const liveDiff = Number(statusBucket(b, nowMs) === "live") - Number(statusBucket(a, nowMs) === "live");
        if (liveDiff) return liveDiff;
      }
      let result = 0;
      if (state.sort === "smart") {
        const ar = smartRank(a, nowMs), br = smartRank(b, nowMs);
        result = ar[0] - br[0] || ar[1] - br[1];
      } else if (state.sort === "kickoff" || state.sort === "kickoff-desc") {
        const av = timeValue(a.kickoff || a.start_time) || Number.MAX_SAFE_INTEGER;
        const bv = timeValue(b.kickoff || b.start_time) || Number.MAX_SAFE_INTEGER;
        result = state.sort === "kickoff" ? av - bv : bv - av;
      } else if (state.sort === "activity") {
        result = timeValue(b.last_activity) - timeValue(a.last_activity);
      } else if (state.sort === "largest-buy") {
        result = largestBuy(b) - largestBuy(a);
      } else if (alpha) result = matchup(a).localeCompare(matchup(b)) * direction;
      return result || stableKey(a).localeCompare(stableKey(b));
    });
  }

  function selectGames(games, state, nowMs) {
    return sortGames(filterGames(games, state, nowMs), state, nowMs);
  }

  function deriveOptions(games, sport) {
    const relevant = (games || []).filter(game => sport === "all" || String(game.sport).toLowerCase() === sport);
    return {
      weeks: [...new Set(relevant.map(game => String(game.week || "")).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, {numeric: true})),
      season_types: [...new Set(relevant.map(game => String(game.season_type || "").toLowerCase()).filter(Boolean))],
      statuses: [...new Set(relevant.map(game => statusBucket(game, Date.now())))],
    };
  }

  return {groupGameFlow, teamsFromTitle, timeValue, normalizeSpace, statusBucket,
    matchesSearch, largestBuy, defaultState, parseState, serializeState,
    applyQuickView, filterGames, sortGames, selectGames, deriveOptions};
}));
