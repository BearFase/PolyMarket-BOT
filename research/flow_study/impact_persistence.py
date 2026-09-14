"""Read-only Impact + Persistence, pre-registered method plus the three safeguards.

Primary analysis is pregame-only: if first pitch falls at or before a horizon, that horizon is
UNAVAILABLE rather than measured through live-game information. Crossed-kickoff behaviour is
reported separately. Same-side price path only (own-side asks). legacy_incomplete = 0 only.
Nothing is written to any journal.
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

F = ("slug", "game", "side", "price", "risk", "trade_ts", "pregame", "market_start")
rows = [dict(zip(F, r)) for r in con.execute(
    "select market_slug, canonical_game_uuid, selected_side, execution_price, risk_usd, "
    "trade_timestamp_utc, pregame_classification, source_market_start_time "
    "from mlb_trade_observations where legacy_incomplete = 0")]
for r in rows:
    r["t"] = ts(r["trade_ts"])
rows.sort(key=lambda r: r["t"])

# ------------------------------------------------------------------ first pitch per market
first_row = {}
for r in rows:
    first_row.setdefault(r["slug"], r)
kick, kick_src, disagree = {}, {}, []
for slug, r in first_row.items():
    sched, actual = games.get(r["game"], (None, None))
    if actual:
        kick[slug], kick_src[slug] = actual, "canonical actual"
    elif sched:
        kick[slug], kick_src[slug] = sched, "canonical scheduled"
    elif ts(r["market_start"]):
        kick[slug], kick_src[slug] = ts(r["market_start"]), "exchange start"
    ms = ts(r["market_start"])
    if slug in kick and ms:
        delta = abs((kick[slug] - ms).total_seconds()) / 60.0
        if delta > 1:
            disagree.append((slug, kick_src[slug], round(delta, 1)))

series, times = defaultdict(list), {}
for r in rows:
    series[(r["slug"], r["side"])].append((r["t"], r["price"]))
for k in series:
    series[k].sort()
    times[k] = [x[0] for x in series[k]]

gaps = [(a["t"], b["t"]) for a, b in zip(rows, rows[1:]) if (b["t"] - a["t"]).total_seconds() > 1200]


def build(level):
    out = []
    if level == "fill":
        for r in rows:
            out.append({"slug": r["slug"], "side": r["side"], "t0": r["t"], "p0": r["price"],
                        "size": r["risk"] or 0, "pregame": r["pregame"], "fills": 1})
    else:
        groups = defaultdict(list)
        for r in rows:
            groups[(r["slug"], r["side"], r["price"], r["trade_ts"])].append(r)
        for (slug, side, price, _), g in groups.items():
            out.append({"slug": slug, "side": side, "t0": g[0]["t"], "p0": price,
                        "size": sum(x["risk"] or 0 for x in g), "pregame": g[0]["pregame"], "fills": len(g)})
    out.sort(key=lambda e: e["t0"])
    return out


EVENTS = {level: build(level) for level in ("fill", "cluster")}


def pregame_events(level, lo, hi):
    return [e for e in EVENTS[level]
            if e["pregame"] == "PREGAME" and lo <= e["size"] < hi
            and e["slug"] in kick and e["t0"] < kick[e["slug"]]]


def measure(ev, horizon, censor=True):
    """(delta_cents, status). horizon None = impact, the first same-side fill after t0."""
    key = (ev["slug"], ev["side"])
    arr = times.get(key)
    if not arr:
        return None, "no same-side series"
    ko = kick.get(ev["slug"])
    if horizon is None:
        i = bisect_right(arr, ev["t0"])
        if i >= len(arr):
            return None, "no later fill"
        t, p = series[key][i]
        if censor and ko and t >= ko:
            return None, "kickoff"
        return (p - ev["p0"]) * 100.0, "ok"
    end = ev["t0"] + timedelta(minutes=horizon)
    if censor and ko and ko <= end:
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


def table(evs, censor=True):
    print(HEAD)
    for horizon in (None,) + HORIZONS:
        label = "impact" if horizon is None else "+" + str(horizon) + "m"
        vals, why = [], Counter()
        for e in evs:
            d, status = measure(e, horizon, censor)
            if status == "ok":
                vals.append(d)
            else:
                why[status] += 1
        s = stats(vals)
        cov = 100 * len(vals) / len(evs) if evs else 0
        nofill = why["no later fill"] + why["no fill in window"] + why["no same-side series"]
        line = (label.rjust(8) + str(len(evs)).rjust(7) + str(len(vals)).rjust(7)
                + "{:.1f}".format(cov).rjust(6) + str(why["kickoff"]).rjust(6) + str(nofill).rjust(7))
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
    for e in evs:
        prev = last.get(e["slug"])
        if prev is None or (e["t0"] - prev).total_seconds() >= minutes * 60:
            out.append(e)
            last[e["slug"]] = e["t0"]
    return out


print("=" * 118)
print("DATA QUALITY AND COVERAGE")
print("=" * 118)
print("live rows {} (legacy_incomplete = 0); markets {}; {:%Y-%m-%d %H:%M}Z .. {:%Y-%m-%d %H:%M}Z".format(
    len(rows), len(first_row), min(r["t"] for r in rows), max(r["t"] for r in rows)))
print("first-pitch source: {}; markets with no first pitch: {}".format(
    dict(Counter(kick_src.values())), len(first_row) - len(kick)))
print("markets where canonical first pitch and the exchange start time differ by > 1 min: {}{}".format(
    len(disagree), " -> " + str(disagree[:5]) if disagree else ""))
conflict = sum(1 for r in rows if r["pregame"] == "PREGAME" and r["slug"] in kick and r["t"] >= kick[r["slug"]])
print("rows labelled PREGAME whose trade time is at/after first pitch (excluded): {}".format(conflict))
print("quiet stretches over 20 min in the tape: {}; longest {:.1f}h".format(
    len(gaps), max((b - a).total_seconds() / 3600 for a, b in gaps)))
for level in ("fill", "cluster"):
    large = pregame_events(level, LARGE, float("inf"))
    touched = sum(1 for e in large for a, b in gaps if a < e["t0"] + timedelta(minutes=60) and b > e["t0"])
    print("{:>8}-level pregame >= $1k events: {}; with a quiet stretch inside their 60-min window: {}".format(
        level, len(large), touched))
    print("         sizes: median ${:,.0f}, max ${:,.0f}; minutes before first pitch: median {:.1f}".format(
        statistics.median([e["size"] for e in large]), max(e["size"] for e in large),
        statistics.median([(kick[e["slug"]] - e["t0"]).total_seconds() / 60 for e in large])))

for level in ("fill", "cluster"):
    for name, lo, hi in CLASSES:
        evs = pregame_events(level, lo, hi)
        print("\n" + "=" * 118)
        print("PREGAME-ONLY, {} LEVEL, {} (n={}) - cents on the side bought, + = that side got dearer".format(
            level.upper(), name, len(evs)))
        print("=" * 118)
        table(evs)

for level in ("fill", "cluster"):
    evs = decluster(pregame_events(level, LARGE, float("inf")))
    print("\n" + "=" * 118)
    print("DE-CLUSTERED SENSITIVITY (first >= $1k event per market per 5 min), {} LEVEL (n={})".format(
        level.upper(), len(evs)))
    print("=" * 118)
    table(evs)

for level in ("fill", "cluster"):
    for bname, blo, bhi in BUCKETS:
        evs = [e for e in pregame_events(level, LARGE, float("inf")) if blo <= e["p0"] < bhi]
        print("\n" + "-" * 118)
        print("PRICE BUCKET {}, {} LEVEL, >= $1k (n={})".format(bname, level.upper(), len(evs)))
        print("-" * 118)
        table(evs)

for level in ("fill", "cluster"):
    evs = pregame_events(level, LARGE, float("inf"))
    print("\n" + "=" * 118)
    print("CROSSED-KICKOFF (path NOT censored at first pitch), {} LEVEL (n={}) - NOT the primary".format(
        level.upper(), len(evs)))
    print("=" * 118)
    table(evs, censor=False)
