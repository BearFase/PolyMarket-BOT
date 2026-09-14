"""POST-SPECIFICATION SENSITIVITY ANALYSIS prompted by observed multi-price same-timestamp executions.

Sweep cluster = all observations sharing canonical market, buyer side/intent and the exact exchange
timestamp, at any execution price, with every underlying exchange id preserved. Aggregate executed
dollars decide the >= $1,000 cohort; t0_price is the size-weighted average execution price (VWAP).
This is a same-instant execution sweep, NOT a single submitted parent order.

Impact compares against the first same-side fill strictly after the sweep timestamp, so no fill
belonging to the sweep counts as post-t0 movement. Persistence keeps the pre-registered pregame-only
+5/+15/+30/+60 method with kickoff censoring, the same 5-minute de-clustering, and the same price
buckets (by sweep VWAP).

The frozen fill-level and original execution-cluster analyses are NOT modified here. They are
recomputed only to count how many of their events a sweep absorbs.
"""
import sqlite3
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LARGE = 1000.0
HORIZONS = (5, 15, 30, 60)
BUCKETS = (("0-25c", 0.0, 0.25), ("25-50c", 0.25, 0.50), ("50-75c", 0.50, 0.75), ("75-100c", 0.75, 1.01))
CLASSES = (("large >=$1k", LARGE, float("inf")), ("ctrl $100-1k", 100.0, LARGE), ("ctrl $5-100", 5.0, 100.0))


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

dev = max(abs((r["risk"] or 0) - (r["contracts"] or 0) * (r["price"] or 0)) for r in rows)
print("=" * 118)
print("POST-SPECIFICATION SENSITIVITY ANALYSIS - same-instant execution sweeps")
print("prompted by observed multi-price same-timestamp executions; frozen analyses unchanged")
print("=" * 118)
print("risk_usd vs contracts x execution_price: max deviation {:.6f} -> VWAP = sum(price*contracts)/"
      "sum(contracts) is exact".format(dev))

# ------------------------------------------------------------------------ build the three views
sweeps = defaultdict(list)
for r in rows:
    sweeps[(r["slug"], r["side"], r["trade_ts"])].append(r)

sweep_events = []
for (slug, side, trade_ts), g in sweeps.items():
    qty = sum(x["contracts"] or 0 for x in g)
    dollars = sum(x["risk"] or 0 for x in g)
    vwap = sum((x["price"] or 0) * (x["contracts"] or 0) for x in g) / qty if qty else g[0]["price"]
    prices = [x["price"] for x in g]
    sweep_events.append({"slug": slug, "side": side, "t0": g[0]["t"], "p0": vwap, "size": dollars,
                         "fills": len(g), "pregame": g[0]["pregame"], "span": (max(prices) - min(prices)) * 100,
                         "max_fill": max(x["risk"] or 0 for x in g), "members": g})
sweep_events.sort(key=lambda e: e["t0"])

fill_events = [{"slug": r["slug"], "side": r["side"], "t0": r["t"], "p0": r["price"],
                "size": r["risk"] or 0, "pregame": r["pregame"], "ts": r["trade_ts"]} for r in rows]
orig = defaultdict(list)
for r in rows:
    orig[(r["slug"], r["side"], r["price"], r["trade_ts"])].append(r)
orig_events = [{"slug": k[0], "side": k[1], "t0": g[0]["t"], "p0": k[2],
                "size": sum(x["risk"] or 0 for x in g), "pregame": g[0]["pregame"], "ts": k[3]}
               for k, g in orig.items()]


def pregame(evs, lo, hi):
    return [e for e in evs if e["pregame"] == "PREGAME" and lo <= e["size"] < hi
            and e["slug"] in kick and e["t0"] < kick[e["slug"]]]


def measure(ev, horizon):
    key = (ev["slug"], ev["side"])
    arr = times.get(key)
    if not arr:
        return None, "no series"
    ko = kick.get(ev["slug"])
    if horizon is None:
        i = bisect_right(arr, ev["t0"])           # strictly after the whole timestamp
        if i >= len(arr):
            return None, "no later fill"
        t, p = series[key][i]
        if ko and t >= ko:
            return None, "kickoff"
        return (p - ev["p0"]) * 100.0, "ok"
    end = ev["t0"] + timedelta(minutes=horizon)
    if ko and ko <= end:
        return None, "kickoff"
    i = bisect_right(arr, end) - 1
    if i < 0:
        return None, "no later fill"
    t, p = series[key][i]
    if t <= ev["t0"]:
        return None, "no fill in window"
    return (p - ev["p0"]) * 100.0, "ok"


def stats(vals):
    if not vals:
        return None
    q = statistics.quantiles(vals, n=4) if len(vals) >= 4 else [float("nan")] * 3
    p = statistics.quantiles(vals, n=20) if len(vals) >= 20 else None
    return {"n": len(vals), "med": statistics.median(vals), "mean": statistics.fmean(vals),
            "q1": q[0], "q3": q[2], "p5": p[0] if p else float("nan"),
            "p95": p[-1] if p else float("nan"), "lo": min(vals), "hi": max(vals),
            "pos": 100 * sum(v > 0 for v in vals) / len(vals),
            "zero": 100 * sum(v == 0 for v in vals) / len(vals),
            "neg": 100 * sum(v < 0 for v in vals) / len(vals)}


HEAD = ("horizon".rjust(8) + "elig".rjust(7) + "n".rjust(7) + "cov%".rjust(6) + "kick".rjust(6)
        + "nofill".rjust(7) + "med".rjust(8) + "mean".rjust(8) + "q1".rjust(8) + "q3".rjust(8)
        + "p5".rjust(8) + "p95".rjust(8) + "min".rjust(9) + "max".rjust(9)
        + "pos%".rjust(6) + "zero%".rjust(7) + "neg%".rjust(6))


def table(evs):
    print(HEAD)
    for horizon in (None,) + HORIZONS:
        label = "impact" if horizon is None else "+" + str(horizon) + "m"
        vals, why = [], Counter()
        for e in evs:
            d, status = measure(e, horizon)
            if status == "ok":
                vals.append(d)
            else:
                why[status] += 1
        s = stats(vals)
        nofill = why["no later fill"] + why["no fill in window"] + why["no series"]
        line = (label.rjust(8) + str(len(evs)).rjust(7) + str(len(vals)).rjust(7)
                + "{:.1f}".format(100 * len(vals) / len(evs) if evs else 0).rjust(6)
                + str(why["kickoff"]).rjust(6) + str(nofill).rjust(7))
        if s:
            for key, width, dec in (("med", 8, 2), ("mean", 8, 2), ("q1", 8, 2), ("q3", 8, 2),
                                    ("p5", 8, 2), ("p95", 8, 2), ("lo", 9, 2), ("hi", 9, 2),
                                    ("pos", 6, 1), ("zero", 7, 1), ("neg", 6, 1)):
                line += ("{:." + str(dec) + "f}").format(s[key]).rjust(width)
        else:
            line += "   (no measurable events)"
        print(line)


def decluster(evs, minutes=5):
    out, last = [], {}
    for e in sorted(evs, key=lambda e: e["t0"]):
        prev = last.get(e["slug"])
        if prev is None or (e["t0"] - prev).total_seconds() >= minutes * 60:
            out.append(e)
            last[e["slug"]] = e["t0"]
    return out


# ------------------------------------------------------------------------------- what changed
sw_large = pregame(sweep_events, LARGE, float("inf"))
fl_large = pregame(fill_events, LARGE, float("inf"))
or_large = pregame(orig_events, LARGE, float("inf"))
new_only = [e for e in sw_large if e["max_fill"] < LARGE]
sw_keys = {(e["slug"], e["side"], e["members"][0]["trade_ts"]) for e in sw_large}
absorbed_fills = [e for e in fl_large if (e["slug"], e["side"], e["ts"]) in sw_keys]
absorbed_orig = [e for e in or_large if (e["slug"], e["side"], e["ts"]) in sw_keys]
multi = [e for e in sw_large if e["fills"] > 1]
spanned = [e for e in sw_large if e["span"] > 0]

print("\n--- cohort changes, pregame >= $1k ---")
print("sweep clusters: {}".format(len(sw_large)))
print("  newly qualifying because every component fill is under $1k: {}".format(len(new_only)))
print("  frozen fill-level events they absorb: {} of {} (fill-level events not inside any qualifying "
      "sweep: {})".format(len(absorbed_fills), len(fl_large), len(fl_large) - len(absorbed_fills)))
print("  frozen original-cluster events they absorb: {} of {}".format(len(absorbed_orig), len(or_large)))
print("  sweeps holding more than one fill: {}; spanning more than one price: {}".format(
    len(multi), len(spanned)))
sizes = sorted(e["size"] for e in sw_large)
print("  aggregate dollars: min ${:,.0f}, median ${:,.0f}, p90 ${:,.0f}, max ${:,.0f}".format(
    sizes[0], statistics.median(sizes), sizes[int(.9 * len(sizes))], sizes[-1]))
print("  fills per sweep: {}".format(dict(sorted(Counter(e["fills"] for e in sw_large).items()))))
spans = sorted(e["span"] for e in sw_large)
print("  execution-price span: 0c for {} sweeps; of the rest median {:.2f}c, max {:.2f}c".format(
    sum(1 for s in spans if s == 0), statistics.median([s for s in spans if s > 0] or [0]),
    spans[-1]))
print("  first same-side print in its market (structurally fragile t0): {}".format(
    sum(1 for e in sw_large if times[(e["slug"], e["side"])][0] == e["t0"])))

def fmt(pair):
    d, status = pair
    return "{:+.2f}c".format(d) if status == "ok" else "unavailable ({})".format(status)


print("\n--- every sea-ath sweep; the frozen -24.50c outlier is the one at 09-11 18:07:23Z ---")
for e in sw_large:
    if "sea-ath" in e["slug"]:
        top = max(e["members"], key=lambda x: x["price"])
        print("  sweep {} {} at {:%m-%d %H:%M:%S}Z: {} fills, ${:,.0f} aggregate, prices {} span {:.2f}c"
              .format(e["slug"], e["side"], e["t0"], e["fills"], e["size"],
                      sorted({x["price"] for x in e["members"]}), e["span"]))
        print("    frozen fill-level t0 {:.4f} (highest fill, ${:,.0f}) impact {}; sweep VWAP t0 {:.4f} "
              "impact {}".format(top["price"], top["risk"] or 0, fmt(measure(dict(e, p0=top["price"]), None)),
                                 e["p0"], fmt(measure(e, None))))

for name, lo, hi in CLASSES:
    evs = pregame(sweep_events, lo, hi)
    print("\n" + "=" * 118)
    print("SWEEP SENSITIVITY - pregame-only, {} (n={}) - cents on the side bought".format(name, len(evs)))
    print("=" * 118)
    table(evs)

evs = decluster(sw_large)
print("\n" + "=" * 118)
print("SWEEP SENSITIVITY - de-clustered (first qualifying sweep per market per 5 min) (n={})".format(len(evs)))
print("=" * 118)
table(evs)

for bname, blo, bhi in BUCKETS:
    evs = [e for e in sw_large if blo <= e["p0"] < bhi]
    print("\n" + "-" * 118)
    print("SWEEP SENSITIVITY - price bucket {} by sweep VWAP, >= $1k (n={})".format(bname, len(evs)))
    print("-" * 118)
    table(evs)

print("\n" + "=" * 118)
print("SIDE BY SIDE, pregame >= $1k: frozen fill / frozen original cluster / sweep sensitivity")
print("=" * 118)
print("horizon".rjust(8) + "n_fill".rjust(8) + "n_orig".rjust(8) + "n_swp".rjust(8)
      + "med_fill".rjust(10) + "med_orig".rjust(10) + "med_swp".rjust(10)
      + "mean_fill".rjust(11) + "mean_orig".rjust(11) + "mean_swp".rjust(11)
      + "pos_fill".rjust(10) + "pos_orig".rjust(10) + "pos_swp".rjust(10))
for horizon in (None,) + HORIZONS:
    label = "impact" if horizon is None else "+" + str(horizon) + "m"
    cells = []
    for evs in (fl_large, or_large, sw_large):
        vals = [d for d, st in (measure(e, horizon) for e in evs) if st == "ok"]
        cells.append(stats(vals))
    line = label.rjust(8)
    for c in cells:
        line += str(c["n"]).rjust(8)
    for c in cells:
        line += "{:.2f}".format(c["med"]).rjust(10)
    for c in cells:
        line += "{:.2f}".format(c["mean"]).rjust(11)
    for c in cells:
        line += "{:.1f}".format(c["pos"]).rjust(10)
    print(line)
