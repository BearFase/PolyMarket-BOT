# MLB flow study — do large pregame buys precede persistent price movement?

Read-only analysis of the buy-only MLB journal. Nothing here writes to a journal, changes the
canonical Polymarket US data path, or places or simulates an order.

## Data

`mlb_research.db` → `mlb_trade_observations`, **`legacy_incomplete = 0` only**. That filter is not
optional. `big_money_tape` calls `mlb_research.migrate_legacy` when the tape starts and every 30
minutes, copying the pruned display table in as `LEGACY_INCOMPLETE` rows; as of 2026-09-12 all 1,064
checked duplicated a live row. Because the display keeps each event's five largest trades, those
duplicates concentrate in large buys: counting them inflated the large pregame cohort from 122 to
211 in an earlier pass.

The journal is buy-only by construction — taker BUY_LONG / BUY_SHORT on moneylines at or above the
$5 display threshold. Sells, undefined intents, run lines and totals never reached it.

Every file in `results/` is a dated snapshot of a journal that keeps growing, and each prints its own
row count and date range. The primary tables use 119,419 live rows, 72 markets, 2026-09-09 05:14Z to
2026-09-12 09:13Z.

## Pre-registered method

Fixed before any result was computed, so no definition could be chosen for flattering the hypothesis.

- **Two event definitions, always reported side by side.** *Fill level*: every exchange fill alone.
  *Execution cluster*: fills sharing canonical market, side/intent, execution price and the exact
  exchange timestamp, summed. A cluster is never called one submitted order — trade messages carry
  no participant id, so that is unprovable.
- **t0** is the trade's own fill price. A cluster has a single price by definition.
- **Same-side price path.** Both sides of a market trade as two asks: `paid_long + paid_short` has a
  median of 1.0050 across 38,273 opposite-side consecutive pairs, so the spread is about half a cent
  and the tick is 0.5¢. Consecutive opposite-side fills move the converted price by a median of 0.5¢
  — pure bid/ask bounce — while consecutive same-side fills move it 0.0¢. The path is therefore the
  same-side series, which is also what a follower would actually pay.
- **Impact** = first same-side fill strictly after t0, minus t0, in cents, signed in the buyer's
  direction. **Persistence** = last same-side fill at or before t0 + 5 / 15 / 30 / 60 minutes.
- **Pregame only, censored at first pitch.** When first pitch falls at or before a horizon, that
  horizon is unavailable rather than measured through live-game information. Crossed-kickoff
  behaviour is reported separately and is never the primary.
- **Controls measured identically**: $100–$1,000 and $5–$100 flow, same markets, same pregame windows.
- **Overlap sensitivity**: a de-clustered view keeping the first qualifying event per market per
  5 minutes, so repeated executions in one burst cannot pose as independent evidence.
- **Strata**: t0 price buckets 0–25¢, 25–50¢, 50–75¢, 75–100¢.
- Distributions, not only medians. No threshold, window, grouping rule or exclusion was changed
  after results were seen.

## What the definition change does to the sample

Pregame ≥ $1,000: **196 fill-level events against 194 execution clusters.** The near-equal totals
hide roughly 7% turnover in composition — 12 clusters qualify only once fills are summed (the
largest is 19 fills totalling $2,417), while 11 clusters hold more than one large fill and absorb 14
events the fill view counts separately. Across all trades: 1,185 against 1,115, with 156 newly
qualifying.

## Frozen primary results

Cents on the side bought; + means that side got more expensive. Median is **0.00 in every cell**.
Full tables in `results/impact_persistence_raw_2026-09-12.txt`.

| horizon | n fill / cluster | coverage % | mean fill / cluster | positive % fill / cluster |
| --- | --- | --- | --- | --- |
| impact | 196 / 193 | 100.0 / 99.5 | −0.10 / −0.10 | 5.6 / 4.7 |
| +5m | 163 / 161 | 83.2 / 83.0 | −0.00 / −0.03 | 12.9 / 11.2 |
| +15m | 139 / 139 | 70.9 / 71.6 | 0.15 / 0.11 | 20.1 / 19.4 |
| +30m | 111 / 113 | 56.6 / 58.2 | 0.25 / 0.18 | 26.1 / 24.8 |
| +60m | 89 / 89 | 45.4 / 45.9 | 0.32 / 0.23 | 30.3 / 28.1 |

Controls at +60m, same measurement: $100–$1,000 mean **0.28 / 0.24** (n 872 / 815); $5–$100 mean
**0.06 / 0.04** (n 11,341 / 10,609).

De-clustered view (fill n=140, cluster n=150): +60m means **−0.02 / +0.01**, medians 0.00.

Price buckets, fill level: 0–25¢ empty; 25–50¢ n=57, +60m mean 1.43 (n=22); 50–75¢ n=138, +60m mean
0.33 (n=66); 75–100¢ n=1.

## Coverage and data quality

- **Large buys sit close to first pitch** — median 48.5 minutes before (fill level), 52.7 (cluster).
  That is why +30m is unavailable for 42% of events and +60m for 54%.
- **First pitch** came from the canonical scheduled start for all 72 markets, and no market
  disagreed with the exchange's start time by more than a minute. No row labelled PREGAME fell at or
  after first pitch.
- **Zero-inflation**: impact is exactly 0.00 for 92.3% of large fills, with a 0.5¢ tick.
- **Tails come from two episodes.** The −24.50¢ floor is a market-open book-walk in
  `aec-mlb-sea-ath-2026-09-12`. The ±19.50¢ values are one genuine repricing in `aec-mlb-cle-bal`
  on 09-09 that moved $5 and $265 fills alike.
- **Two price strata are structurally empty.** Pregame prices paid run 0.245–0.850, median 0.535;
  exactly 1 of 20,220 pregame fills is under 25¢. Nothing in this sample was more lopsided than
  roughly 72/28.
- **Three quiet stretches over 20 minutes**, the longest 12.8h (a PC shutdown on 2026-09-10/11).
  Only 2 large events have one inside their 60-minute window.

## Post-specification sensitivity analysis prompted by observed multi-price same-timestamp executions

Not part of the pre-registration and not a replacement for it — the frozen results above are
unchanged. This view exists because the exchange showed that one aggressive execution can walk
several price levels inside a single timestamp: 4,655 instants (4.8%) carry fills at more than one
price, and 17 of the 196 pregame large fills sit inside one, 11 of them paying the sweep's top tick.
Treating a $17,289 execution as unrelated events because it printed at 49.5¢ and 50.0¢ would be
economically misleading.

**Sweep cluster**: all fills sharing canonical market, buyer side/intent and the exact exchange
timestamp, at any execution price, with every underlying exchange id preserved. Aggregate executed
dollars decide the ≥ $1,000 cohort, and t0 is the size-weighted average execution price (VWAP). This
is a *same-instant execution sweep*, never a single submitted order. Impact compares the first
same-side fill strictly after the whole timestamp, so walking the book is never counted as
post-trade impact.

Cohort: **192 sweep clusters**, absorbing all 196 fill-level and all 194 cluster-level events, with
**14 newly qualifying** because every component fill is under $1,000. 60 hold more than one fill but
only 13 span more than one price. Aggregate dollars: median $2,198, max $27,547.

| horizon | mean fill / cluster / sweep | median (all three) | n fill / cluster / sweep |
| --- | --- | --- | --- |
| impact | −0.10 / −0.10 / −0.06 | 0.00 | 196 / 193 / 191 |
| +5m | −0.00 / −0.03 / 0.01 | 0.00 | 163 / 161 / 159 |
| +15m | 0.15 / 0.11 / 0.15 | 0.00 | 139 / 139 / 137 |
| +30m | 0.25 / 0.18 / 0.23 | 0.00 | 111 / 113 / 111 |
| +60m | 0.32 / 0.23 / 0.29 | 0.00 | 89 / 89 / 88 |

The definition is not driving the outcome. Sweep controls at +60m: $100–$1,000 mean 0.25 and $5–$100
mean 0.04, against 0.29 for the large cohort.

The `sea-ath` outlier is now understood. That instant is 10 fills walking 0.595 → 0.850, $1,796
aggregate; a VWAP t0 of 0.7566 gives −15.16¢ where the frozen top-tick t0 of 0.8500 gave −24.50¢.
Part of the tail was the worst-tick choice, and the rest is a real adverse repricing to 0.605.

**Rate columns are not comparable across definitions.** A VWAP rarely lands on the 0.5¢ tick, so an
unchanged market registers as a sub-tick non-zero move: zero-movement at impact falls from 92.3% to
74.9% mechanically, and the 25–50¢ bucket shows a symmetric 21.1% positive / 21.1% negative at
impact. Compare medians and means across definitions; compare pos/zero/neg rates only within one.

## Final subgroup check: the 25–50¢ bucket

The one subgroup with a visibly larger drift, tested with the existing definitions and cohorts. No
new thresholds, windows or exclusions.

Matched controls at +60m, in cents, as sweep view / frozen fill view:

| cohort | all markets | same markets as the ≥ $1k events |
| --- | --- | --- |
| ≥ $1,000 | 1.10 (n=24) / 1.43 (n=22) | the same events |
| $100–$1,000 | 0.23 (n=184) / 0.30 (n=211) | 0.32 (n=144) / 0.37 (n=167) |
| $5–$100 | −0.04 (n=2,898) / −0.00 (n=3,199) | −0.05 (n=2,125) / −0.01 (n=2,348) |

The size ordering survives the match, so the remaining question is concentration — and it is
concentrated. **One game supplies the drift.** `aec-mlb-phi-atl-2026-09-12` contributes 4 of the 24
sweep events and +23.63¢ of the total, all SHORT buys between 03:33Z and 03:43Z. Excluding that one
market the mean falls to **+0.14¢ over n=20 in 15 markets**, and only 6 of 16 markets have a positive
mean. The frozen fill view agrees: excluding it, +0.06¢ at +60m, with 2 of 14 markets positive.

The 25–50¢ drift is therefore **one episode in one market, not a size effect**. It is not a finding,
and it is not worth pursuing further on this dataset.

## What this does not show

No claim of predictive value or profitability is made or supported. A follower pays the Polymarket US
fee (coefficient 0.06, roughly 1.3¢ at typical prices) and cannot size the trade, because no order
book depth is published. The tape is buys-only, so "subsequent flow" here excludes sells and fills
under $5 — that is precisely what the full-flow journals in `trade_journal.py` were built to fix, and
the Leadership question belongs to them, not to this history.

## Conclusion, narrowly

In this sample, large pregame MLB buys show **no meaningful immediate price impact**: the median is
0.00¢ at every horizon under all three definitions. There is modest later positive drift, but
ordinary $100–$1,000 flow drifts nearly as much (+0.28 against +0.32 at +60m), so **trade size alone
has not demonstrated a distinct price-moving effect here**. The 25–50¢ bucket looked like the
exception until the matched control and concentration check dissolved it into a single game.

Impact and Persistence are complete for this historical dataset, and were not extended after the
results were seen. The Leadership question — whether the market was already moving before a large
execution, or the execution came first — belongs to the accumulating full-flow journals, which record
sells, sub-$5 fills and the complete local sequence that this buy-only history cannot show.

## Files

| file | what it is |
| --- | --- |
| `impact_step1.py` | base dataset, execution clusters, sample-change and price-structure checks used to fix the method |
| `impact_persistence.py` | the frozen pre-registered primary analysis |
| `sweep_sensitivity.py` | post-specification sweep-cluster sensitivity analysis |
| `bucket_matched_control.py` | 25–50¢ matched controls, existing definitions only |
| `tail_concentration.py` | concentration diagnostic for the 25–50¢ cohort |
| `results/definition_comparison_2026-09-12.txt` | output of `impact_step1.py` |
| `results/impact_persistence_raw_2026-09-12.txt` | output of `impact_persistence.py` — all frozen tables |
| `results/sweep_sensitivity_raw_2026-09-12.txt` | output of `sweep_sensitivity.py` |
| `results/bucket_matched_control_2026-09-12.txt` | output of `bucket_matched_control.py` |
| `results/tail_concentration_2026-09-12.txt` | output of `tail_concentration.py` |
