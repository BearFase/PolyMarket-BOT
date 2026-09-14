# Cross-venue arbitrage economics — Polymarket US ↔ Kalshi

**Status: MEASURED. Not viable under the currently observed NFL market structure and available APIs.** Probed 2026-09-10 on 25 NFL games
quoted live on both venues. Read-only: no orders placed, no fills simulated,
nothing integrated.

> **After all fees, spreads and execution constraints, do genuinely executable
> Polymarket ↔ Kalshi arbitrage opportunities exist often enough to justify
> building the integration?**
>
> **Not under the market structure and APIs observed today — and not marginally.** One game in 25 showed any gross edge at all
> (0.50¢). Break-even needs 2.1–3.6¢. Even setting Kalshi's fees to **zero**,
> that single opportunity loses money, because Polymarket's own fee alone
> exceeds the entire gross edge.

Reproduce with `arb_economics_probe.py`.

---

## 1. Gross, before any fee is applied

Cost to buy the complete outcome — one side on each venue, guaranteed $1.00
payout — taking the cheaper of the two directions per game:

| | |
|---|---|
| Minimum | **0.9950** |
| Median | **1.0050** |
| Maximum | 1.0200 |
| Games below $1.00 | **1 / 25** |

The median game costs **half a cent more than it pays**. The distribution sits
above parity, which is what a functioning pair of markets should look like.

## 2. Fees

### Kalshi — model and multiplier resolved, base constant not

The fee schedule PDF (`kalshi.com/docs/kalshi-fee-schedule.pdf`) returned HTTP
429 on every attempt and the browser received a download dialog rather than a
page. The CFTC rulebook filing is CID-font encoded — `"Kalshi"` appears zero
times in 405,333 extracted characters, so stdlib extraction cannot read it.

What **was** resolved, from authoritative sources:

| Fact | Value | Source |
|---|---|---|
| Fee model | `quadratic_with_maker_fees` | Kalshi API, `/series/fee_changes` |
| `fee_multiplier`, `KXNFLGAME` | **1.0** (eff. 2026-01-01) | same |
| `fee_multiplier`, `KXMLBGAME` | **0.5** (eff. 2026-08-07) | same |
| Rounding | `ceil` to **$0.000001** | `docs.kalshi.com/getting_started/fee_rounding` |
| Fee basis | expected earnings, not notional | Kalshi help centre |
| Maker fees | charged; enum name confirms | Kalshi API |

`quadratic` confirms the fee tracks `P × (1 − P)` — largest at 50¢, which is
where sports moneylines live. MLB currently runs at **half** NFL's multiplier.

**The base constant remains UNRESOLVED and is deliberately not guessed.**
Third-party sites assert `0.07`, but the same sources give `0.035` for
INX/Nasdaq — which proves the constant is *per-market*, so carrying a blog's
number onto sports would be exactly the unfounded assumption to avoid. It is
swept as a parameter instead.

Two of those third-party claims are also demonstrably wrong: they state
rounding is "up to the penny", where Kalshi's own documentation says
`ceil_6dp` to $0.000001.

### Polymarket US — published, semantics unconfirmed

`feeCoefficient: 0.06` appears directly on the moneyline market. Polymarket US
is **not** fee-free. The exact shape is unconfirmed; applied here on the same
expected-earnings form and reported as its own term so a correction changes one
line rather than the conclusion.

## 3. Net — the conclusion is robust to the unresolved constant

Friction per contract at median leg prices, and how many of the 25 games clear
it:

| Kalshi base | Median friction | Games net > 0 |
|---|---|---|
| **0.000** (fees off) | 0.01327 | **0 / 25** |
| 0.035 | 0.02123 | **0 / 25** |
| 0.070 | 0.02919 | **0 / 25** |
| 0.100 | 0.03602 | **0 / 25** |

**Zero games are profitable even with Kalshi's fee set to zero.** Polymarket's
0.06 coefficient alone costs ~1.33¢ per contract, against a best observed gross
edge of 0.50¢. The missing PDF cannot rescue this: it only makes a negative
number more negative.

Required gross edge to break even, median leg prices:

| Kalshi base | Break-even |
|---|---|
| 0.035 | **2.12¢** |
| 0.070 | **2.92¢** |
| 0.100 | **3.60¢** |

Best observed: **0.50¢** — four to seven times short.

## 4. The one candidate, sized

`NFL-2026-REG-W2-CLE-TB`, the only game below parity:

```
Polymarket CLE ask        0.2650
Kalshi     TB  ask        0.7300   (derived: 1 − best NO bid 0.2700)
complete outcome          0.9950   gross edge +0.50c

max size                  5,558 contracts   (Kalshi depth at that level)
capital deployed          $5,530.50
gross profit              $27.79

Polymarket fee            $64.96
Kalshi base 0.000         $0.00     ->  NET  −$37.17   (−0.672%)
Kalshi base 0.035         $38.34    ->  NET  −$75.51   (−1.365%)
Kalshi base 0.070         $76.69    ->  NET  −$113.85  (−2.059%)
```

The best opportunity in the sample loses **$37 at minimum** and realistically
**$114**, on $5,530 of deployed capital, with both legs filling perfectly.

## 5. Minimum depth required before a quoted edge is tradable

Break-even size is not the binding constraint — no size is profitable at a
0.50¢ edge against ≥1.33¢ of friction. Restated as a requirement:

**A tradable opportunity needs gross edge > ~2.1–3.6¢ per contract**, i.e. a
complete-outcome cost below roughly **0.964–0.979**. Nothing in the sample came
within 1.6¢ of the easiest version of that threshold.

Depth then bounds size *after* that gate is passed. Kalshi publishes full L2,
median 399 contracts at top of book and ~6,055 across the top five levels, with
some books holding a single contract at the best price.

## 6. Polymarket US publishes no depth at all

`bestBidQuote` and `bestAskQuote` carry a price and no size. There is no order
book endpoint, no quantity at any level, no aggregate liquidity figure — the
complete field list contains only `orderPriceMinTickSize` (0.005) and
`minimumTradeQty` (0.01).

**One of the two legs cannot be sized from the API.** Any depth simulator would
be modelling Kalshi precisely and Polymarket by assumption. That is a hard
blocker independent of the fee question.

## 7. Leg risk

Both legs are taker fills against resting orders on separate venues with no
atomicity. Concretely:

- **Kalshi can close early.** `can_close_early: true` with
  `settlement_timer_seconds: 60`. A market may stop trading before its stated
  `close_time`, stranding the other leg.
- **Tick mismatch.** Kalshi quotes on a 1¢ grid, Polymarket on 0.005. A
  Polymarket price can be unrepresentable on Kalshi, so a hedge may be
  unavailable at the required price even when one exists in principle.
- **Unsized Polymarket leg.** Partial fill there cannot be anticipated, only
  discovered.

A single unhedged leg at ~0.27 or ~0.73 carries roughly ±$0.73 or ±$0.27 of
exposure per contract — **two orders of magnitude larger than the 0.50¢ edge
being chased**. One mis-sequenced fill erases hundreds of perfect executions.

## 8. A price-reading trap that manufactures fake edges

This is the most dangerous finding, and it would silently defeat a naive
scanner.

Polymarket US publishes a moneyline as one market with two `outcomes` labels
and an `outcomePrices` array. **`outcomePrices` is `[bestBidQuote,
bestAskQuote]` of a single side — 25 of 25 games — and the labels do not track
the prices.**

Measured against Kalshi as an independent reference:

```
|poly_outcomePrices[0] − kalshi AWAY ask|   median 0.010
|poly_outcomePrices[0] − kalshi HOME ask|   median 0.345
```

Both published numbers describe the **away** team. Worked example:

```
ATL @ PIT
  Polymarket says   [Falcons] 0.315   [Steelers] 0.320
  Kalshi says        ATL 0.33          PIT 0.69

  0.315 and 0.320 are Atlanta's bid and ask.
  The "Steelers" label sits on Atlanta's ask.
```

Reading the second entry as the second team gives *Poly Steelers 0.320 + Kalshi
ATL 0.33 = 0.65* — **a fictitious 35¢ arbitrage**. The label ordering is also
inconsistent across games (`BAL-IND` labels Baltimore's price "Colts"), so
correcting by position alone is not safe either.

The only sound reading: take Polymarket's quote as one side's bid/ask, identify
that side against an independent reference, and derive the other side as
`1 − price`. Never read the second label.

This is the same class of defect that produced 25 fictional 40–69pp edges in
the Polymarket-only scanner, and the coherence guard added there
(`incoherent_prices`, requiring both sides to sum to 1.0 ± 0.03) would catch it.

## 9. Verdict

**Not viable under the currently observed NFL market structure and available APIs, so the integration should not be built now.**

The identity layer is sound — 66/66 deterministic linkage, verified twice. That
was worth establishing and it holds. But the economics are not close:

- 1 of 25 games shows any gross edge, at 0.50¢
- break-even is 2.1–3.6¢
- the sole candidate loses money with Kalshi's fees set to zero
- one leg cannot be sized at all
- unhedged leg risk is ~100× the edge being chased

The markets are efficient against each other at the top of book, which is the
expected outcome and the one that should have been assumed absent evidence.
Nothing here says a different sport, venue pair, or market type is equally
closed — only that this pair, on straight NFL moneylines, is — today. Fees, depth publication and API response shapes can all change, and §10 lists what would have to change first.

## 10. If this is revisited

Preconditions, in order. Each is cheap and each can independently kill it
again:

1. **A venue that publishes depth on both legs.** Without it there is no
   sizing, whatever the edge looks like.
2. **The Kalshi base constant**, from the fee schedule PDF or a CFTC filing
   read with a real PDF library. Needed for absolute numbers, though not to
   reach today's conclusion.
3. **Confirmation of Polymarket's `feeCoefficient` semantics.** Today it is the
   single largest friction term and its exact form is assumed.
4. **A wider sample over time.** 25 games at one instant is a snapshot, not a
   frequency estimate. The observation-only recorder in the original plan is
   the right instrument — but it should only be built if (1) is solved, since
   recording unsizable opportunities answers nothing.

MLB is worth one look before abandoning the idea entirely: its Kalshi fee
multiplier is **0.5**, half of NFL's. Its median spread was 7¢ against NFL's
1¢, which likely more than cancels the fee advantage — but that is a
measurement, not yet measured.

## 11. Explicitly not built

No arbitrage engine, no fee engine, no depth simulator, no order submission or
simulation, no dashboard or Telegram surface, no Kalshi database, and no change
to the canonical Polymarket US data path.
