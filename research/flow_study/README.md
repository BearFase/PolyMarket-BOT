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

## What this does not show

No claim of predictive value or profitability is made or supported. A follower pays the Polymarket US
fee (coefficient 0.06, roughly 1.3¢ at typical prices) and cannot size the trade, because no order
book depth is published. The tape is buys-only, so "subsequent flow" here excludes sells and fills
under $5 — that is precisely what the full-flow journals in `trade_journal.py` were built to fix, and
the Leadership question belongs to them, not to this history.

## Conclusion, narrowly

In this sample, large pregame MLB buys show **no meaningful immediate price impact**: the median is
0.00¢ at every horizon under both definitions. There is modest later positive drift, but ordinary
$100–$1,000 flow drifts nearly as much (+0.28 against +0.32 at +60m), so **trade size alone has not
demonstrated a distinct price-moving effect here**. The 25–50¢ bucket is the only subgroup with a
visibly larger drift and is recorded as a lead requiring a matched control, not as a finding.

## Files

| file | what it is |
| --- | --- |
| `impact_step1.py` | base dataset, execution clusters, sample-change and price-structure checks used to fix the method |
| `impact_persistence.py` | the frozen pre-registered primary analysis |
| `results/definition_comparison_2026-09-12.txt` | output of `impact_step1.py` |
| `results/impact_persistence_raw_2026-09-12.txt` | output of `impact_persistence.py` — all frozen tables |
