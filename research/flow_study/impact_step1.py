"""Read-only step 1 of Impact + Persistence: base dataset, execution clusters, sample sizes.

Fill level:    every exchange fill stands alone.
Cluster level: fills sharing canonical market, side, execution price and the exact exchange
               timestamp are summed. A cluster is NOT claimed to be one submitted order.

Only legacy_incomplete = 0 rows are used. Nothing is written; the journal is untouched.
"""
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LARGE = 1000.0


def ro(name):
    return sqlite3.connect((ROOT / name).resolve().as_uri() + "?mode=ro", uri=True)


def ts(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


con = ro("mlb_research.db")
FIELDS = ("uuid", "slug", "game", "side", "selection", "contracts", "price", "risk",
          "trade_ts", "pregame", "start_time")
rows = [dict(zip(FIELDS, r)) for r in con.execute(
    "select observation_uuid, market_slug, canonical_game_uuid, selected_side, raw_selection, "
    "contracts, execution_price, risk_usd, trade_timestamp_utc, pregame_classification, "
    "source_market_start_time from mlb_trade_observations where legacy_incomplete = 0")]
for r in rows:
    r["t"] = ts(r["trade_ts"])
rows.sort(key=lambda r: (r["slug"], r["t"]))

print(f"live rows {len(rows)}; markets {len({r['slug'] for r in rows})}; "
      f"games {len({r['game'] for r in rows if r['game']})}; "
      f"trade times {min(r['t'] for r in rows):%Y-%m-%d %H:%M}Z .. {max(r['t'] for r in rows):%Y-%m-%d %H:%M}Z")
print(f"selected_side values {dict(Counter(r['side'] for r in rows))}")
print(f"pregame_classification {dict(Counter(r['pregame'] for r in rows))}")
print(f"rows with no canonical game link: {sum(1 for r in rows if not r['game'])}")

# ---------------------------------------------------------------- execution clusters
clusters = defaultdict(list)
for r in rows:
    clusters[(r["slug"], r["side"], r["price"], r["trade_ts"])].append(r)
sizes = Counter(len(v) for v in clusters.values())
multi = {k: v for k, v in clusters.items() if len(v) > 1}
print(f"\nclusters {len(clusters)}; multi-fill clusters {len(multi)} covering "
      f"{sum(len(v) for v in multi.values())} rows "
      f"({sum(len(v) for v in multi.values()) / len(rows):.1%} of fills); "
      f"fills per cluster {dict(sorted(sizes.items()))}")

for label, keep in (("all trades", lambda r: True), ("pregame only", lambda r: r["pregame"] == "PREGAME")):
    sub = [r for r in rows if keep(r)]
    sub_clusters = defaultdict(list)
    for r in sub:
        sub_clusters[(r["slug"], r["side"], r["price"], r["trade_ts"])].append(r)
    fills_large = [r for r in sub if (r["risk"] or 0) >= LARGE]
    cl_large = {k: v for k, v in sub_clusters.items() if sum(x["risk"] or 0 for x in v) >= LARGE}
    new_events = {k: v for k, v in cl_large.items() if max(x["risk"] or 0 for x in v) < LARGE}
    collapsed = {k: v for k, v in cl_large.items() if sum(1 for x in v if (x["risk"] or 0) >= LARGE) > 1}
    print(f"\n=== {label}: large-buy sample at >= ${LARGE:g} ===")
    print(f"  fill level   : {len(fills_large)} events")
    print(f"  cluster level: {len(cl_large)} events")
    print(f"    of those, only visible once fills are summed (every fill < ${LARGE:g}): {len(new_events)}")
    print(f"    clusters holding more than one >= ${LARGE:g} fill (fill level counts them separately): "
          f"{len(collapsed)}")
    if new_events:
        tot = sorted((sum(x["risk"] or 0 for x in v), len(v)) for v in new_events.values())
        print(f"    newly qualifying cluster totals: min ${tot[0][0]:,.0f} ({tot[0][1]} fills), "
              f"median ${statistics.median(t[0] for t in tot):,.0f}, max ${tot[-1][0]:,.0f} "
              f"({tot[-1][1]} fills)")
    sizes_l = sorted((sum(x["risk"] or 0 for x in v)) for v in cl_large.values())
    if sizes_l:
        print(f"    cluster-level sizes: median ${statistics.median(sizes_l):,.0f}, max ${sizes_l[-1]:,.0f}")

# ------------------------------------------------- price normalization and bid/ask bounce
def long_price(r):
    """Price of the LONG side implied by this fill, if selected_side tells us the direction."""
    if r["side"] == "LONG":
        return r["price"]
    if r["side"] == "SHORT":
        return 1.0 - r["price"]
    return None

pairs, same_side, opp_side = [], [], []
by_market = defaultdict(list)
for r in rows:
    by_market[r["slug"]].append(r)
for market, rs in by_market.items():
    for a, b in zip(rs, rs[1:]):
        gap = (b["t"] - a["t"]).total_seconds()
        if gap > 60 or gap < 0:
            continue
        pa, pb = long_price(a), long_price(b)
        if pa is None or pb is None:
            continue
        if a["side"] != b["side"]:
            pairs.append(a["price"] + b["price"])
            opp_side.append(abs(pb - pa))
        else:
            same_side.append(abs(pb - pa))
print(f"\nprice checks on consecutive fills in one market within 60s:")
if pairs:
    print(f"  opposite-side pairs {len(pairs)}: paid_long + paid_short median {statistics.median(pairs):.4f} "
          f"(1.0 + spread expected), 10th/90th pct "
          f"{statistics.quantiles(pairs, n=10)[0]:.4f}/{statistics.quantiles(pairs, n=10)[-1]:.4f}")
    print(f"  |change| in LONG-equivalent price: opposite-side median {statistics.median(opp_side):.4f}, "
          f"same-side median {statistics.median(same_side):.4f} "
          f"({len(same_side)} same-side pairs) <- bid/ask bounce vs real moves")
