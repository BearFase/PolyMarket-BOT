(function () {
  "use strict";
  window.GameFlowNavigationActive = true;

  const PREFERENCE_KEY = "game-flow-preferences-v1";
  const REFRESH_MS = 30000;
  const seasonLabels = {hof: "Hall of Fame", pre: "Preseason", reg: "Regular Season", post: "Postseason"};
  const sortLabels = {smart: "Smart order", kickoff: "Kickoff: soonest", "kickoff-desc": "Kickoff: latest",
    activity: "Most recent activity", "largest-buy": "Largest qualifying buy", matchup: "Matchup A–Z", "matchup-desc": "Matchup Z–A"};
  const esc = value => String(value == null ? "" : value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  const usd = value => "$" + Number(value || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const cents = value => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? Math.round(Number(value) * 100) + "¢" : "—";
  const pct = value => Number.isFinite(value) ? (Math.abs(value - Math.round(value)) < .05 ? Math.round(value) : value.toFixed(1)) + "%" : "—";
  const gameTime = timestamp => timestamp ? new Date(timestamp).toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}) : "Start time unavailable";
  const age = timestamp => {
    if (!timestamp) return "none";
    const value = typeof timestamp === "number" ? timestamp : Date.parse(timestamp);
    const seconds = Math.max(0, Math.round((Date.now() - value) / 1000));
    if (seconds < 60) return seconds + " seconds ago";
    if (seconds < 3600) return Math.round(seconds / 60) + " minutes ago";
    return Math.round(seconds / 3600) + " hours ago";
  };
  const helpers = {esc, usd, cents, age, gameTime};
  let state, games = [], sourceState = {mlb: "loading", nfl: "loading"};

  function preferences() {
    try { return JSON.parse(localStorage.getItem(PREFERENCE_KEY) || "{}"); } catch (_) { return {}; }
  }

  function savePreferences() {
    try { localStorage.setItem(PREFERENCE_KEY, JSON.stringify({sort: state.sort, live_first: state.live_first})); } catch (_) {}
  }

  function nflCards(data) {
    return (data.games || []).map(game => ({...game, sport: "NFL", kind: "nfl",
      search_aliases: `${game.away_team_id || ""} ${game.home_team_id || ""}`}));
  }

  function mlbCards(data) {
    return GameFlow.groupGameFlow(data.open || [], data.minimum_display_usd).map(game => ({...game,
      sport: "MLB", kind: "mlb", kickoff: game.start_time, canonical_game_id: game.event_slug,
      completion_timestamp: null, season_type: "", week: ""}));
  }

  function maxBuy(game) { return GameFlow.largestBuy(game); }

  function nflBuySide(game, teamId, teamName) {
    const rows = (game.buys && game.buys[teamId]) || [];
    return `<section class="side"><div class="side-name">${esc(teamName)}</div>${rows.length ? rows.map(row =>
      `<div class="buy"><span class="amount">${usd(row.amount_usd)}</span><span class="price">@ ${cents(row.execution_price)}</span></div>`).join("") : '<div class="none">No qualifying buys</div>'}</section>`;
  }

  function mlbBuySide(game, team) {
    const rows = game.buys[team] || [];
    return `<section class="side"><div class="side-name">${esc(team)}</div>${rows.length ? rows.map(row =>
      `<div class="buy"><span class="amount">${usd(row.risk_usd)}</span><span class="price">@ ${cents(row.entry_price)}</span></div>`).join("") : '<div class="none">No qualifying buys</div>'}</section>`;
  }

  function cardMarkup(game) {
    if (game.kind === "mlb") {
      return `<article class="game" data-game-key="${esc(game.event_slug)}"><header class="game-head"><div class="matchup">${esc(game.away)} @ ${esc(game.home)}</div><div class="market">MLB · Moneyline · ${gameTime(game.start_time)}</div><div class="probabilities"><div class="prob"><b>${esc(game.away)}</b><b>${pct(game.probabilities[game.away])}</b></div><div class="prob"><b>${esc(game.home)}</b><b>${pct(game.probabilities[game.home])}</b></div></div></header><div class="buys"><div class="buys-title">Largest qualifying buys</div>${mlbBuySide(game, game.away)}${mlbBuySide(game, game.home)}</div><footer class="game-foot"><span>Last activity: ${age(game.last_activity)}</span><span class="future"><span>Observations</span><span>Paper Position</span><span>Settlement</span><span>History</span></span></footer></article>`;
    }
    const outcomes = (game.moneyline || []).map(outcome => `<div class="prob"><b>${esc(outcome.team)}</b><b>${cents(outcome.price)}</b></div>`).join("");
    const winner = game.winner_team_id ? `<span>Winner: ${esc(game.winner_team_id)}</span>` : "";
    const research = game.status === "FINAL" && game.research_summary ? `<button class="research-button" data-research="${esc(game.game_uuid)}">Research Summary</button>` : "";
    return `<article class="game" data-game-key="${esc(game.game_uuid)}" data-game-uuid="${esc(game.game_uuid)}"><header class="game-head"><div class="matchup">${esc(game.away)} @ ${esc(game.home)}</div><div class="market">NFL · ${esc(seasonLabels[String(game.season_type).toLowerCase()] || game.season_type)} · Week ${esc(game.week)} · ${gameTime(game.kickoff)} · ${esc(game.status)}</div><div class="probabilities">${outcomes || '<div class="none">Moneyline unavailable</div>'}</div></header><div class="buys"><div class="buys-title">Largest qualifying buys</div>${nflBuySide(game, game.away_team_id, game.away)}${nflBuySide(game, game.home_team_id, game.home)}</div><footer class="game-foot"><span>Last activity: ${game.last_activity ? age(game.last_activity) : "none"}</span>${winner}${research}</footer><div class="research-panel"></div></article>`;
  }

  function selectedOption(select, value) { if ([...select.options].some(option => option.value === value)) select.value = value; else select.value = "all"; }

  function populateOptions() {
    const options = GameFlow.deriveOptions(games, "nfl");
    if (state.week !== "all" && !options.weeks.includes(state.week)) state.week = "all";
    const season = document.getElementById("filter-season");
    season.innerHTML = '<option value="all">All</option>' + options.season_types.sort().map(value => `<option value="${esc(value)}">${esc(seasonLabels[value] || value.toUpperCase())}</option>`).join("");
    const week = document.getElementById("filter-week");
    week.innerHTML = '<option value="all">All</option>' + options.weeks.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
    const statuses = GameFlow.deriveOptions(games, state.sport).statuses;
    if (state.status !== "all" && !statuses.includes(state.status)) statuses.push(state.status);
    const status = document.getElementById("filter-status");
    const statusLabels = {upcoming: "Upcoming", live: "Live", final: "Final", postponed: "Postponed / Canceled"};
    status.innerHTML = '<option value="all">All</option>' + statuses.sort().map(value => `<option value="${esc(value)}">${esc(statusLabels[value] || value)}</option>`).join("");
    selectedOption(season, state.season_type); selectedOption(week, state.week);
    selectedOption(status, state.status);
  }

  function syncControls() {
    document.getElementById("game-search").value = state.q;
    document.getElementById("filter-sport").value = state.sport;
    document.getElementById("filter-status").value = state.status;
    document.getElementById("filter-date").value = state.date;
    document.getElementById("sort-games").value = state.sort;
    document.getElementById("live-first").checked = state.live_first;
    selectedOption(document.getElementById("filter-season"), state.season_type);
    selectedOption(document.getElementById("filter-week"), state.week);
    document.querySelectorAll("[data-nfl-filter]").forEach(element => { element.hidden = state.sport !== "nfl"; });
    document.querySelectorAll("[data-quick]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.quick === state.quick)));
  }

  function chip(label, key) { return `<span class="chip">${esc(label)} <button data-clear-state="${key}" aria-label="Remove ${esc(label)} filter">×</button></span>`; }

  function renderState(total, showing) {
    const chips = [];
    if (state.q) chips.push(chip(`Search: ${state.q}`, "q"));
    if (state.sport !== "all") chips.push(chip(state.sport.toUpperCase(), "sport"));
    if (state.season_type !== "all") chips.push(chip(seasonLabels[state.season_type] || state.season_type, "season_type"));
    if (state.week !== "all") chips.push(chip(`Week ${state.week}`, "week"));
    if (state.status !== "all") chips.push(chip(state.status, "status"));
    if (state.date !== "all") chips.push(chip(state.date, "date"));
    if (state.sort !== "smart") chips.push(chip(sortLabels[state.sort], "sort"));
    document.getElementById("active-state").innerHTML = `<span class="result-count">Showing ${showing} of ${total} games</span>${chips.join("")}${chips.length ? '<button class="clear-button" id="clear-all">Clear all</button>' : ""}`;
    document.querySelectorAll("[data-clear-state]").forEach(button => button.addEventListener("click", () => {
      const key = button.dataset.clearState; state[key] = GameFlow.defaultState()[key]; state.quick = ""; applyState(true);
    }));
    const clearAll = document.getElementById("clear-all"); if (clearAll) clearAll.addEventListener("click", () => { state = GameFlow.defaultState(); applyState(true); });
  }

  function emptyMessage() {
    if (sourceState.mlb === "error" && sourceState.nfl === "error") return "Game Flow source data is unavailable.";
    if (!games.length) return "No Game Flow games are loaded.";
    if (state.quick === "live" || state.status === "live") return "No live games right now.";
    if (state.quick === "today" || state.date === "today") return "No games today.";
    return "No Game Flow games match your search.";
  }

  function expandedKeys() { return [...document.querySelectorAll(".research-panel.open")].map(panel => panel.closest(".game").dataset.gameKey); }

  function render() {
    const scroll = window.scrollY, expanded = expandedKeys();
    const selected = GameFlow.selectGames(games, state, Date.now());
    renderState(games.length, selected.length);
    document.getElementById("flow-sub").textContent = sourceState.mlb === "error" || sourceState.nfl === "error" ? "Showing available canonical data; one source is temporarily unavailable." : "Search and organize canonical NFL games and qualifying MLB activity without changing the underlying evidence.";
    document.getElementById("summary").innerHTML = `<div class="stat"><b>${selected.length}</b><span>games shown</span></div><div class="stat"><b>${selected.filter(game => maxBuy(game) > 0).length}</b><span>with qualifying activity</span></div>`;
    document.getElementById("games").innerHTML = selected.length ? selected.map(cardMarkup).join("") : `<div class="empty">${emptyMessage()}</div>`;
    document.querySelectorAll("[data-research]").forEach(button => {
      const game = selected.find(item => item.game_uuid === button.dataset.research);
      button.addEventListener("click", () => PostGameResearch.toggle(button, game, helpers));
      if (expanded.includes(game.game_uuid)) button.click();
    });
    requestAnimationFrame(() => window.scrollTo(0, scroll));
  }

  function updateUrl(push) {
    const url = location.pathname + GameFlow.serializeState(state);
    history[push ? "pushState" : "replaceState"]({}, "", url);
  }

  function applyState(push) { savePreferences(); updateUrl(push); populateOptions(); syncControls(); render(); }

  function bindControls() {
    document.getElementById("game-search").addEventListener("input", event => { state.q = event.target.value.trim().replace(/\s+/g, " "); state.quick = ""; applyState(true); });
    document.getElementById("clear-search").addEventListener("click", () => { state.q = ""; state.quick = ""; applyState(true); document.getElementById("game-search").focus(); });
    const bindings = {"filter-sport": "sport", "filter-season": "season_type", "filter-week": "week", "filter-status": "status", "filter-date": "date", "sort-games": "sort"};
    Object.entries(bindings).forEach(([id, key]) => document.getElementById(id).addEventListener("change", event => {
      state[key] = event.target.value; state.quick = "";
      if (key === "sport" && state.sport === "mlb") { state.season_type = "all"; state.week = "all"; }
      applyState(true);
    }));
    document.getElementById("live-first").addEventListener("change", event => { state.live_first = event.target.checked; state.quick = ""; applyState(true); });
    document.querySelectorAll("[data-quick]").forEach(button => button.addEventListener("click", () => { state = GameFlow.applyQuickView(state, button.dataset.quick); applyState(true); }));
    addEventListener("popstate", () => { state = GameFlow.parseState(location.search, preferences()); syncControls(); render(); });
  }

  async function refresh(initial) {
    const settled = await Promise.allSettled([
      fetch("/api/big-money?t=" + Date.now()).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }),
      fetch("/api/nfl-game-flow?t=" + Date.now()).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }),
    ]);
    sourceState = {mlb: settled[0].status === "fulfilled" ? "ok" : "error", nfl: settled[1].status === "fulfilled" ? "ok" : "error"};
    games = [...(settled[0].status === "fulfilled" ? mlbCards(settled[0].value) : []), ...(settled[1].status === "fulfilled" ? nflCards(settled[1].value) : [])];
    populateOptions(); syncControls(); render();
    if (initial) updateUrl(false);
  }

  document.addEventListener("DOMContentLoaded", () => {
    state = GameFlow.parseState(location.search, preferences());
    bindControls(); syncControls(); refresh(true);
    setInterval(() => refresh(false), REFRESH_MS);
  });
}());
