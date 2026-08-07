"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const Flow = require("./game_flow.js");

const NOW = Date.parse("2026-08-06T16:00:00-07:00");
function game(id, away, home, kickoff, extras={}) {
  return {canonical_game_id:id, game_uuid:id, sport:"NFL", away, home,
    away_team_id: extras.away_team_id || away.slice(0,3).toUpperCase(),
    home_team_id: extras.home_team_id || home.slice(0,3).toUpperCase(),
    season_type:extras.season_type || "PRE", week:extras.week || "1",
    kickoff, status:extras.status || "SCHEDULED", last_activity:extras.last_activity || null,
    completion_timestamp:extras.completion_timestamp || null,
    buys:extras.buys || {}, search_aliases:extras.search_aliases || ""};
}
const steelers = game("NFL-2026-PRE-W1-PIT-BAL", "Pittsburgh Steelers", "Baltimore Ravens", "2026-08-06T17:00:00-07:00", {away_team_id:"PIT",home_team_id:"BAL"});
const cowboys = game("NFL-2026-HOF-WHOF-DAL-LAC", "Dallas Cowboys", "Los Angeles Chargers", "2026-08-06T20:00:00-07:00", {away_team_id:"DAL",home_team_id:"LAC",season_type:"HOF",week:"HOF",status:"LIVE",last_activity:"2026-08-06T23:30:00Z",buys:{DAL:[{amount_usd:100}],LAC:[{amount_usd:900}]}});
const future = game("NFL-2026-REG-W1-NYG-PHI", "New York Giants", "Philadelphia Eagles", "2026-09-10T17:00:00-07:00", {away_team_id:"NYG",home_team_id:"PHI",season_type:"REG"});
const final = game("NFL-2026-PRE-W0-GB-KC", "Green Bay Packers", "Kansas City Chiefs", "2026-08-05T17:00:00-07:00", {away_team_id:"GB",home_team_id:"KC",status:"FINAL",completion_timestamp:"2026-08-06T04:00:00Z"});
const mlb = {...game("mlb-sd-az", "San Diego Padres", "Arizona Diamondbacks", "2026-08-06T18:00:00-07:00"), sport:"MLB", kind:"mlb",season_type:"",week:"",event_slug:"mlb-sd-az"};
const games=[future,final,steelers,cowboys,mlb];

test("team, city, nickname, abbreviation, matchup, case, and whitespace search",()=>{
  for(const query of ["Steelers","Pittsburgh","PIT","Steelers @ Ravens","  pItTsBuRg   STEELERS  "])
    assert.deepEqual(Flow.filterGames(games,{...Flow.defaultState(),q:query},NOW).map(g=>g.game_uuid),[steelers.game_uuid]);
  assert.deepEqual(Flow.filterGames(games,{...Flow.defaultState(),q:"Cowboys Chargers"},NOW).map(g=>g.game_uuid),[cowboys.game_uuid]);
});

test("no results and empty search",()=>{
  assert.equal(Flow.filterGames(games,{...Flow.defaultState(),q:"not-a-team"},NOW).length,0);
  assert.equal(Flow.filterGames(games,{...Flow.defaultState(),q:"   "},NOW).length,games.length);
});

test("sport, season, week, status, and date filters",()=>{
  assert.equal(Flow.filterGames(games,{...Flow.defaultState(),sport:"mlb"},NOW).length,1);
  assert.deepEqual(Flow.filterGames(games,{...Flow.defaultState(),season_type:"hof"},NOW).map(g=>g.game_uuid),[cowboys.game_uuid]);
  assert.equal(Flow.filterGames(games,{...Flow.defaultState(),week:"HOF"},NOW).length,1);
  assert.deepEqual(Flow.filterGames(games,{...Flow.defaultState(),status:"live"},NOW).map(g=>g.game_uuid),[cowboys.game_uuid]);
  assert.equal(Flow.filterGames(games,{...Flow.defaultState(),date:"today"},NOW).length,3);
  assert.deepEqual(Flow.filterGames(games,{...Flow.defaultState(),date:"completed"},NOW).map(g=>g.game_uuid),[final.game_uuid]);
});

test("quick views and clear-all default",()=>{
  assert.equal(Flow.applyQuickView(Flow.defaultState(),"today").date,"today");
  const pre=Flow.applyQuickView(Flow.defaultState(),"preseason"); assert.equal(pre.sport,"nfl");assert.equal(pre.season_type,"pre");
  assert.equal(Flow.applyQuickView(Flow.defaultState(),"live").status,"live");
  assert.equal(Flow.applyQuickView(Flow.defaultState(),"finals").status,"final");
  assert.deepEqual(Flow.applyQuickView({...Flow.defaultState(),q:"x"},"all"),Flow.defaultState());
});

test("smart order is deterministic and stable across refreshes",()=>{
  const state=Flow.defaultState();
  const expected=[cowboys.game_uuid,steelers.game_uuid,mlb.game_uuid,future.game_uuid,final.game_uuid];
  assert.deepEqual(Flow.selectGames(games,state,NOW).map(g=>g.game_uuid),expected);
  assert.deepEqual(Flow.selectGames([...games].reverse(),state,NOW).map(g=>g.game_uuid),expected);
});

test("kickoff, activity, largest buy, and alphabetical sorts",()=>{
  const ids=sort=>Flow.sortGames(games,{...Flow.defaultState(),sort,live_first:false},NOW).map(g=>g.game_uuid);
  assert.equal(ids("kickoff")[0],final.game_uuid); assert.equal(ids("kickoff-desc")[0],future.game_uuid);
  assert.equal(ids("activity")[0],cowboys.game_uuid); assert.equal(ids("largest-buy")[0],cowboys.game_uuid);
  assert.equal(ids("matchup")[0],cowboys.game_uuid); assert.equal(ids("matchup-desc")[0],mlb.game_uuid);
});

test("live-first overrides non-alphabetical sorts but not alphabetical",()=>{
  assert.equal(Flow.sortGames(games,{...Flow.defaultState(),sort:"kickoff",live_first:true},NOW)[0].game_uuid,cowboys.game_uuid);
  assert.equal(Flow.sortGames(games,{...Flow.defaultState(),sort:"matchup",live_first:true},NOW)[0].game_uuid,cowboys.game_uuid);
});

test("URL parsing, invalid fallback, serialization, and preference precedence",()=>{
  const state=Flow.parseState("?sport=nfl&season_type=pre&status=upcoming&sort=kickoff&q=steelers",{sort:"activity",live_first:false});
  assert.equal(state.sort,"kickoff"); assert.equal(state.live_first,false); assert.equal(state.q,"steelers");
  const invalid=Flow.parseState("?sport=soccer&sort=random&status=broken",{sort:"activity",live_first:false});
  assert.equal(invalid.sport,"all"); assert.equal(invalid.sort,"activity"); assert.equal(invalid.status,"all");
  const roundTrip=Flow.parseState(Flow.serializeState(state),{}); assert.equal(roundTrip.sport,"nfl");assert.equal(roundTrip.q,"steelers");
  assert.equal(Flow.parseState("?sort=smart&live_first=1",{sort:"activity",live_first:false}).sort,"smart");
});

test("result count and loaded-data options",()=>{
  assert.equal(Flow.selectGames(games,{...Flow.defaultState(),sport:"nfl"},NOW).length,4);
  const options=Flow.deriveOptions(games,"nfl"); assert.ok(options.weeks.includes("HOF")); assert.ok(options.season_types.includes("reg"));
});

test("UI contains no-results copy, accessibility labels, URL/local state, refresh preservation, and mobile wrapping",()=>{
  const html=fs.readFileSync("game_flow_dashboard.html","utf8");
  const ui=fs.readFileSync("game_flow_ui.js","utf8");
  assert.match(html,/Search team or matchup\.\.\./); assert.match(html,/aria-label="Game Flow navigation"/);
  assert.match(html,/aria-label="Clear game search"/); assert.match(html,/@media\(max-width:720px\)/);
  assert.match(html,/\.quick-views,\.filters,\.active-state\{[^}]*flex-wrap:wrap/); assert.match(ui,/No Game Flow games match your search\./);
  assert.match(ui,/localStorage\.getItem/); assert.match(ui,/history\[push \? "pushState" : "replaceState"\]/);
  assert.match(ui,/addEventListener\("popstate"/); assert.match(ui,/window\.scrollY/); assert.match(ui,/expandedKeys\(\)/);
  assert.match(ui,/Showing \$\{showing\} of \$\{total\} games/);
});
