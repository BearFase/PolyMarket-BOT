(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PostGameResearch = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const NOTE_LABELS = {
    observed_market_behavior: "Observed Market Behavior",
    interesting_activity: "Interesting Activity",
    unexpected_price_movement: "Unexpected Price Movement",
    news_injury_notes: "News / Injury Notes",
    reason_largest_buy_wrong: "Reason Largest Buy May Have Been Wrong",
    reason_largest_buy_correct: "Reason Largest Buy May Have Been Correct",
    lessons_learned: "Lessons Learned",
  };

  const yesNo = value => value === true ? "YES" : value === false ? "NO" : "Not established";
  const valueOrDash = value => value == null || value === "" ? "—" : value;

  function facts(rows, h) {
    return `<div class="facts">${rows.map(([label, value]) =>
      `<span>${h.esc(label)}</span><span>${h.esc(valueOrDash(value))}</span>`).join("")}</div>`;
  }

  function movement(value, h) {
    if (!value) return "Not tracked";
    const sign = value.change > 0 ? "+" : "";
    return `${h.cents(value.first_price)} → ${h.cents(value.latest_price)} (${sign}${Math.round(value.change * 100)}¢)`;
  }

  function reportMarkup(response, game, h) {
    const record = response.record;
    const p = record.payload;
    const info = p.game_information;
    const market = p.market_snapshot;
    const results = p.research_results;
    const flow = p.game_flow_summary;
    const quality = p.research_quality;
    const hist = p.historical_comparisons;
    const notes = response.analyst_notes.notes || {};
    const largest = market.largest_recorded_buy;
    const returns = value => value == null ? "Not simulated" : h.usd(value);
    const icon = kind => ({success: "✅", failure: "❌", money: "💰", warning: "⚠", trend: "📈"}[kind] || "•");

    return `<div class="report-title"><div><h2>Post-Game Research Summary</h2>
      <div class="revision">Immutable record revision ${record.revision_number} · ${h.esc(record.created_at)}</div></div>
      <div class="revision">${h.esc(p.canonical_game_id)}</div></div>
      <div class="indicators">${(p.visual_indicators || []).map(item =>
        `<span class="indicator ${h.esc(item.kind)}">${icon(item.kind)} ${h.esc(item.label)}</span>`).join("")}</div>
      <div class="report-grid">
      <section class="report-section"><h3>Game Information</h3>${facts([
        ["Season", info.season], ["Season Type", info.season_type], ["Week", info.week],
        ["Matchup", `${info.away_team} @ ${info.home_team}`], ["Kickoff", h.gameTime(info.kickoff_time)],
        ["Final Score", `${info.away_team} ${info.away_score} — ${info.home_team} ${info.home_score}`],
        ["Winner", info.winner], ["Status", info.game_status]], h)}</section>
      <section class="report-section"><h3>Market Snapshot</h3>${facts([
        ["Largest Buy", largest ? `${largest.team_id} · ${h.usd(largest.amount_usd)} @ ${h.cents(largest.execution_price)}` : "Not recorded"],
        ["Largest Buy Time", largest && largest.timestamp],
        ["Away Largest", market.away_largest_buy && h.usd(market.away_largest_buy.amount_usd)],
        ["Home Largest", market.home_largest_buy && h.usd(market.home_largest_buy.amount_usd)],
        ["Polymarket Favorite", market.pregame_polymarket_favorite_team_id],
        ["Sportsbook Favorite", market.pregame_sportsbook_favorite_team_id],
        ["Closing Polymarket", market.closing_polymarket_probability == null ? null : h.cents(market.closing_polymarket_probability)],
        ["Closing Sportsbook", market.closing_sportsbook_probability == null ? null : h.cents(market.closing_sportsbook_probability)],
        ["Sportsbooks", market.bookmaker_count], ["Liquidity", market.market_liquidity == null ? null : h.usd(market.market_liquidity)]], h)}</section>
      <section class="report-section"><h3>Research Results</h3>${facts([
        ["Largest Buy Side Won", yesNo(results.largest_buy_side_won)],
        ["Sportsbook Favorite Won", yesNo(results.sportsbook_favorite_won)],
        ["Polymarket Favorite Won", yesNo(results.polymarket_favorite_won)],
        ["Largest Buy Return", returns(results.largest_buy_return)],
        ["Sportsbook Favorite Return", returns(results.sportsbook_favorite_return)],
        ["Polymarket Favorite Return", returns(results.polymarket_favorite_return)]], h)}</section>
      <section class="report-section"><h3>Game Flow Summary</h3>${facts([
        ["Qualifying Trades", flow.qualifying_trade_count], ["Pregame Trades", flow.pregame_trade_count],
        ["Post-Kickoff Trades", flow.post_kickoff_trade_count],
        ["Largest Execution Price", flow.largest_execution_price == null ? null : h.cents(flow.largest_execution_price)],
        ["Latest Execution Price", flow.latest_execution_price == null ? null : h.cents(flow.latest_execution_price)],
        ["Away Pregame Movement", movement(flow.price_movement_before_kickoff[info.away_team_id], h)],
        ["Home Pregame Movement", movement(flow.price_movement_before_kickoff[info.home_team_id], h)],
        ["Away Post-Kickoff Movement", movement(flow.price_movement_after_kickoff[info.away_team_id], h)],
        ["Home Post-Kickoff Movement", movement(flow.price_movement_after_kickoff[info.home_team_id], h)]], h)}</section>
      <section class="report-section"><h3>Historical Comparisons</h3>${facts([
        ["Season Games", hist.current_season_totals.games],
        ["Largest Buy Record", `${hist.current_season_totals.largest_buy.wins}-${hist.current_season_totals.largest_buy.losses}`],
        ["Sportsbook Favorite Record", `${hist.current_season_totals.sportsbook_favorite.wins}-${hist.current_season_totals.sportsbook_favorite.losses}`],
        ["Polymarket Favorite Record", `${hist.current_season_totals.polymarket_favorite.wins}-${hist.current_season_totals.polymarket_favorite.losses}`],
        ["Home Team Record", `${hist.current_season_totals.home_wins}-${hist.current_season_totals.away_wins}`],
        ["Week Games", hist.week_totals.games], ["Preseason Games", hist.preseason_totals.games],
        ["Largest Buy Overall", hist.largest_buy_overall && h.usd(hist.largest_buy_overall.amount_usd)]], h)}</section>
      <section class="report-section"><h3>Research Quality</h3>${facts([
        ["Canonical Match Verified", yesNo(quality.canonical_match_verified)],
        ["Settlement Verified", yesNo(quality.settlement_verified)], ["Bookmaker Count", quality.bookmaker_count],
        ["Sportsbook Match", quality.sportsbook_matching_confidence], ["Polymarket Match", quality.polymarket_matching_confidence],
        ["Sportsbook Freshness", quality.data_freshness_seconds_before_kickoff.sportsbook == null ? null : `${quality.data_freshness_seconds_before_kickoff.sportsbook}s before kickoff`],
        ["Polymarket Freshness", quality.data_freshness_seconds_before_kickoff.polymarket_us == null ? null : `${quality.data_freshness_seconds_before_kickoff.polymarket_us}s before kickoff`]], h)}
        ${quality.missing_data_warnings.length ? `<ul class="warning-list">${quality.missing_data_warnings.map(w => `<li>${h.esc(w)}</li>`).join("")}</ul>` : ""}</section>
      <section class="report-section wide"><h3>Analyst Observations · Revision ${response.analyst_notes.revision_number || 0}</h3>
        <div class="notes-grid">${Object.entries(NOTE_LABELS).map(([key, label]) =>
          `<div class="note-field"><label>${h.esc(label)}</label><textarea data-note-field="${key}">${h.esc(notes[key] || "")}</textarea></div>`).join("")}</div>
        <div class="note-actions"><span class="note-status">Notes are stored as revisions; previous versions remain intact.</span>
        <button class="save-notes" data-save-notes>Save New Notes Revision</button></div></section></div>`;
  }

  async function saveNotes(panel, game) {
    const button = panel.querySelector("[data-save-notes]");
    const status = panel.querySelector(".note-status");
    const notes = {};
    panel.querySelectorAll("[data-note-field]").forEach(field => { notes[field.dataset.noteField] = field.value; });
    button.disabled = true;
    status.textContent = "Saving a new immutable notes revision…";
    try {
      const response = await fetch(`/api/nfl-games/${encodeURIComponent(game.game_uuid)}/analyst-notes`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({notes}),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const saved = await response.json();
      status.textContent = `Saved notes revision ${saved.revision_number}. Previous revisions remain preserved.`;
    } catch (error) {
      status.textContent = `Notes were not saved (${error.message}).`;
    } finally { button.disabled = false; }
  }

  async function toggle(button, game, h) {
    const panel = button.closest(".game").querySelector(".research-panel");
    if (panel.classList.contains("open")) {
      panel.classList.remove("open"); button.textContent = "Research Summary"; return;
    }
    panel.classList.add("open"); button.textContent = "Close Research Summary";
    panel.innerHTML = '<div class="none">Loading immutable research record…</div>';
    try {
      const response = await fetch(`/api/nfl-games/${encodeURIComponent(game.game_uuid)}/research-summary`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      panel.innerHTML = reportMarkup(await response.json(), game, h);
      panel.querySelector("[data-save-notes]").addEventListener("click", () => saveNotes(panel, game));
    } catch (error) { panel.innerHTML = `<div class="error">Research summary unavailable (${h.esc(error.message)}).</div>`; }
  }

  function render(data, helpers) {
    const games = data.games || [];
    const withActivity = games.filter(game => game.last_activity).length;
    document.getElementById("flow-sub").textContent = "Canonical 2026 NFL research. Completed games become permanent, revisioned case studies.";
    document.getElementById("summary").innerHTML = `<div class="stat"><b>${games.length}</b><span>canonical games</span></div><div class="stat"><b>${withActivity}</b><span>games with activity</span></div>`;
    document.getElementById("games").innerHTML = games.length ? games.map(game => {
      const outcomes = (game.moneyline || []).map(outcome => `<div class="prob"><b>${helpers.esc(outcome.team)}</b><b>${helpers.cents(outcome.price)}</b></div>`).join("");
      const winner = game.winner_team_id ? `<span>Winner: ${helpers.esc(game.winner_team_id)}</span>` : "";
      const research = game.status === "FINAL" && game.research_summary ? `<button class="research-button" data-research="${helpers.esc(game.game_uuid)}">Research Summary</button>` : "";
      const buySide = (teamId, teamName) => {
        const rows = (game.buys && game.buys[teamId]) || [];
        return `<section class="side"><div class="side-name">${helpers.esc(teamName)}</div>${rows.length ? rows.map(row => `<div class="buy"><span class="amount">${helpers.usd(row.amount_usd)}</span><span class="price">@ ${helpers.cents(row.execution_price)}</span></div>`).join("") : '<div class="none">No qualifying buys</div>'}</section>`;
      };
      return `<article class="game" data-game-uuid="${helpers.esc(game.game_uuid)}"><header class="game-head"><div class="matchup">${helpers.esc(game.away)} @ ${helpers.esc(game.home)}</div><div class="market">${helpers.esc(game.season_type)} ${helpers.esc(game.week)} · ${helpers.gameTime(game.kickoff)} · ${helpers.esc(game.status)}</div><div class="probabilities">${outcomes || '<div class="none">Moneyline unavailable</div>'}</div></header><div class="buys"><div class="buys-title">Largest qualifying buys</div>${buySide(game.away_team_id, game.away)}${buySide(game.home_team_id, game.home)}</div><footer class="game-foot"><span>Last activity: ${game.last_activity ? helpers.age(Date.parse(game.last_activity)) : "none"}</span>${winner}${research}</footer><div class="research-panel"></div></article>`;
    }).join("") : '<div class="empty">No canonical NFL games are available.</div>';
    document.querySelectorAll("[data-research]").forEach(button => {
      const game = games.find(item => item.game_uuid === button.dataset.research);
      button.addEventListener("click", () => toggle(button, game, helpers));
    });
  }

  return {NOTE_LABELS, yesNo, reportMarkup, render, toggle};
}));
