"""Final check on the one intriguing subgroup: the 25-50c price bucket, matched controls.

No new thresholds and no new methodology. The two existing event definitions (frozen fill level and
the post-specification sweep cluster), the existing size cohorts (>= $1k, $100-1k, $5-100), the
existing pregame-only kickoff-censored horizons, the existing same-side price path.

Two market treatments are printed:
  ALL MARKETS  - identical to how the controls were measured in the main tables.
  SAME MARKETS - restricted to the markets that hold a >= $1k event in this bucket, so market mix
                 cannot explain a difference. Labelled separately; it narrows, it does not retune.
"""
import sqlite3
import statistics
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUCKET = (0.25, 0.50)
HORIZONS = (15, 30, 60)
COHORTS = (("large >=$1k", 1000.0, float("inf")), ("ctrl $100-1k", 100.0, 1000.0),
           ("ctrl $5-100", 5.0, 100.0))


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
VIEWS = (("frozen fill level", fill_events), ("sweep cluster (post-spec)", sweep_events))


def cohort(evs, lo, hi, markets=None):
    return [e for e in evs
            if e["pregame"] == "PREGAME" and lo <= e["size"] < hi
            and BUCKET[0] <= e["p0"] < BUCKET[1]
            and e["slug"] in kick and e["t0"] < kick[e["slug"]]
            and (markets is None or e["slug"] in markets)]


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


def line(label, evs, horizon):
    vals = [v for v in (measure(e, horizon) for e in evs) if v is not None]
    cells = label.ljust(14) + ("+" + str(horizon) + "m").rjust(6) + str(len(evs)).rjust(7)
    if not vals:
        return cells + "      0   0.0" + "        (none measurable)"
    q = statistics.quantiles(vals, n=4) if len(vals) >= 4 else [float("nan")] * 3
    p = statistics.quantiles(vals, n=20) if len(vals) >= 20 else None
    return (cells + str(len(vals)).rjust(7)
            + "{:.1f}".format(100 * len(vals) / len(evs)).rjust(6)
            + "{:.2f}".format(statistics.median(vals)).rjust(8)
            + "{:.2f}".format(statistics.fmean(vals)).rjust(8)
            + "{:.2f}".format(q[0]).rjust(8) + "{:.2f}".format(q[2]).rjust(8)
            + ("{:.2f}".format(p[0]) if p else "n/a").rjust(8)
            + ("{:.2f}".format(p[-1]) if p else "n/a").rjust(8)
            + "{:.2f}".format(min(vals)).rjust(9) + "{:.2f}".format(max(vals)).rjust(9)
            + "{:.1f}".format(100 * sum(v > 0 for v in vals) / len(vals)).rjust(7)
            + "{:.1f}".format(100 * sum(v == 0 for v in vals) / len(vals)).rjust(7)
            + "{:.1f}".format(100 * sum(v < 0 for v in vals) / len(vals)).rjust(7)
            + str(len({e["slug"] for e in evs})).rjust(6))


HEAD = ("cohort".ljust(14) + "hzn".rjust(6) + "elig".rjust(7) + "n".rjust(7) + "cov%".rjust(6)
        + "med".rjust(8) + "mean".rjust(8) + "q1".rjust(8) + "q3".rjust(8) + "p5".rjust(8)
        + "p95".rjust(8) + "min".rjust(9) + "max".rjust(9) + "pos%".rjust(7) + "zero%".rjust(7)
        + "neg%".rjust(7) + "mkts".rjust(6))

print("=" * 130)
print("25-50c PRICE BUCKET, MATCHED CONTROLS - pregame-only, kickoff-censored, same-side path")
print("cents on the side bought; existing definitions and cohorts only, nothing retuned")
print("=" * 130)
for vname, evs in VIEWS:
    big_markets = {e["slug"] for e in cohort(evs, 1000.0, float("inf"))}
    for treatment, markets in (("ALL MARKETS", None), ("SAME MARKETS as the >= $1k events", big_markets)):
        print("\n--- {} | {} ({} markets) ---".format(vname, treatment, len(big_markets)
                                                      if markets else len({e["slug"] for e in evs})))
        print(HEAD)
        for cname, lo, hi in COHORTS:
            sub = cohort(evs, lo, hi, markets)
            for horizon in HORIZONS:
                print(line(cname, sub, horizon))
