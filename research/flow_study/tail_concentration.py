"""Concentration diagnostic for the one intriguing subgroup: 25-50c, >= $1k, at +15/+30/+60.

The cohort means there are driven by a minority of events, so this prints every measurable event and
checks how much of the drift rests on a single market. Same definitions and cohorts as the main
tables - nothing retuned. "Mean excluding the top contributing market" is a robustness diagnostic,
not an alternative result.
"""
import sqlite3
import statistics
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUCKET = (0.25, 0.50)
LARGE = 1000.0


def ro(name):
    return sqlite3.connect((ROOT / name).resolve().as_uri() + "?mode=ro", uri=True)


def ts(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None


con = ro("mlb_research.db")
gcols = [r[1] for r in con.execute("pragma table_info(mlb_games)")]
ucol = "game_uuid" if "game_uuid" in gcols else next(c for c in gcols if c.endswith("uuid"))
games = {gid: (ts(s), ts(a)) for gid, s, a in
         con.execute("select " + ucol + ", scheduled_start_utc, actual_start_utc from mlb_games")}

F = ("slug", "game", "side", "contracts", "price", "risk", "trade_ts", "pregame", "market_start")
rows = [dict(zip(F, r)) for r in con.execute(
    "select market_slug, canonical_game_uuid, selected_side, contracts, execution_price, risk_usd, "
    "trade_timestamp_utc, pregame_classification, source_market_start_time "
    "from mlb_trade_observations where legacy_incomplete = 0")]
for r in rows:
    r["t"] = ts(r["trade_ts"])
rows.sort(key=lambda r: r["t"])

first_row = {}
for r in rows:
    first_row.setdefault(r["slug"], r)
kick = {}
for slug, r in first_row.items():
    sched, actual = games.get(r["game"], (None, None))
    k = actual or sched or ts(r["market_start"])
    if k:
        kick[slug] = k

series, times = defaultdict(list), {}
for r in rows:
    series[(r["slug"], r["side"])].append((r["t"], r["price"]))
for k in series:
    series[k].sort()
    times[k] = [x[0] for x in series[k]]

fill_events = [{"slug": r["slug"], "side": r["side"], "t0": r["t"], "p0": r["price"],
                "size": r["risk"] or 0, "pregame": r["pregame"]} for r in rows]
sw = defaultdict(list)
for r in rows:
    sw[(r["slug"], r["side"], r["trade_ts"])].append(r)
sweep_events = []
for (slug, side, _), g in sw.items():
    qty = sum(x["contracts"] or 0 for x in g)
    sweep_events.append({"slug": slug, "side": side, "t0": g[0]["t"],
                         "p0": (sum((x["price"] or 0) * (x["contracts"] or 0) for x in g) / qty
                                if qty else g[0]["price"]),
                         "size": sum(x["risk"] or 0 for x in g), "pregame": g[0]["pregame"]})


def measure(ev, horizon):
    key = (ev["slug"], ev["side"])
    arr = times.get(key)
    if not arr:
        return None
    ko = kick.get(ev["slug"])
    end = ev["t0"] + timedelta(minutes=horizon)
    if ko and ko <= end:
        return None
    i = bisect_right(arr, end) - 1
    if i < 0:
        return None
    t, p = series[key][i]
    if t <= ev["t0"]:
        return None
    return (p - ev["p0"]) * 100.0


print("=" * 112)
print("CONCENTRATION DIAGNOSTIC - 25-50c bucket, >= $1k, pregame-only, kickoff-censored")
print("=" * 112)
for vname, evs in (("frozen fill level", fill_events), ("sweep cluster (post-spec)", sweep_events)):
    cohort = [e for e in evs if e["pregame"] == "PREGAME" and e["size"] >= LARGE
              and BUCKET[0] <= e["p0"] < BUCKET[1]
              and e["slug"] in kick and e["t0"] < kick[e["slug"]]]
    for horizon in (15, 30, 60):
        vals = [(measure(e, horizon), e) for e in cohort]
        vals = [(v, e) for v, e in vals if v is not None]
        if not vals:
            continue
        by_market = defaultdict(list)
        for v, e in vals:
            by_market[e["slug"]].append(v)
        top = max(by_market, key=lambda m: sum(by_market[m]))
        rest = [v for m, vs in by_market.items() if m != top for v in vs]
        print("\n--- {} | +{}m | n={} across {} markets ---".format(
            vname, horizon, len(vals), len(by_market)))
        print("    mean {:+.2f}c; largest contributing market {} ({} events, sum {:+.2f}c)".format(
            statistics.fmean(v for v, _ in vals), top, len(by_market[top]), sum(by_market[top])))
        print("    mean excluding that market: {:+.2f}c over n={} in {} markets".format(
            statistics.fmean(rest) if rest else float("nan"), len(rest), len(by_market) - 1))
        print("    markets with a positive mean: {} of {}".format(
            sum(1 for vs in by_market.values() if statistics.fmean(vs) > 0), len(by_market)))
        if horizon == 60:
            print("    every event at +60m, largest move first:")
            for v, e in sorted(vals, key=lambda x: -x[0]):
                print("      {:+7.2f}c  {} {} t0 {:.4f} ${:>8,.0f}  {:%m-%d %H:%M}Z".format(
                    v, e["slug"], e["side"], e["p0"], e["size"], e["t0"]))
