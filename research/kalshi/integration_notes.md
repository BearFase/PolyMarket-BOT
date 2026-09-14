# Kalshi integration notes

**Status: AUDITED, NOT INTEGRATED.** Probed 2026-09-10 against the Kalshi
production REST API. No production module imports anything here, no orders
were placed or simulated, and no arbitrage figure was computed.

---

## 1. Clean markets exist and are structurally separable

Two series carry straight game winners: **`KXNFLGAME`** ("Professional
Football Game") and **`KXMLBGAME`** ("Professional Baseball Game").

They do not have to be found by title matching. Every event carries
`product_metadata.competition_scope`, and it discriminates cleanly:

| Series | `competition_scope` |
|---|---|
| `KXNFLGAME` | `Game` |
| `KXMLBGAME` | `Game` |
| `KXNFL1H` | `1st Half Winner` |
| `KXLEADERNFLPYDS` | `League Leader` |
| `KXNFLOTWIN` | `null` |

Filtering on `competition_scope == "Game"` is the structured discriminator and
is what the probe uses. For scale: of 3,754 sports series, 355 mention NFL and
168 mention MLB, and almost all are props, futures, period markets, spreads or
totals. The first market encountered in an unfiltered `/markets` sweep was
`KXMVECROSSCATEGORY-…`, a multi-leg combo mixing team winners with player
props — precisely what must never reach a moneyline comparison.

**Counts on 2026-09-10:** 31 open NFL game events, 35 open MLB game events,
two markets each (one per team, `mutually_exclusive: true`).

## 2. Representation

| Concept | Kalshi field | Example |
|---|---|---|
| Series | `series_ticker` | `KXNFLGAME` |
| Event | `event_ticker` | `KXNFLGAME-26SEP10SFLAR` |
| Market | `ticker` | `KXNFLGAME-26SEP10SFLAR-LAR` |
| Team | `custom_strike.football_team` | stable UUID per team |
| Team code | market ticker suffix | `LAR`, `SF` |
| Scheduled start | `occurrence_datetime` | **offset, see §4** |
| Status | `status` | `active` |
| Tick | `price_ranges[].step` | `0.0100` |
| Contract value | `notional_value_dollars` | `1.0000` |
| Rules | `rules_primary`, `rules_secondary` | prose |
| Settlement source | event `settlement_sources` | NFL: nfl.com; MLB: ESPN, Fox Sports, mlb.com |

MLB event tickers embed the start time (`KXMLBGAME-26SEP10**1215**TBATL`);
NFL tickers do not.

`custom_strike.football_team` is a **stable team UUID** — across the sample, 32
distinct team codes with zero conflicting UUIDs. It is a better anchor for the
alias table than the abbreviation string. Its format resembles SportRadar's,
and Polymarket US exposes `sportradarGameId`, so a shared provider namespace is
plausible — **unverified, do not rely on it** without a SportRadar reference.

**Kalshi exposes no external game identifier.** No ESPN id, no SportRadar game
id, no league game id anywhere on the event or market. Linkage must therefore
be derived, which is what §3 and §4 are about.

## 3. Linkage is deterministic, with two required correctness inputs

Matching on canonical team pair plus scheduled start within the project's
existing 1800-second tolerance:

| Sport | Result |
|---|---|
| NFL | **31 / 31 EXACT**, 0 ambiguous, 0 unmatched |
| MLB | **35 / 35 EXACT**, 0 ambiguous, 0 unmatched |

Home/away orientation was verified independently: Kalshi's `sub_title` reads
`"AWAY vs HOME"` on all 29 initially-matched NFL events, with zero orientation
conflicts against the registry. The probe still checks it per event and emits
`ORIENTATION_CONFLICT` rather than assuming.

Two inputs are required to reach those numbers:

**A team alias table.** Kalshi uses `JAC` for Jacksonville where the registry
uses `JAX`, and `AZ` for Arizona where the registry uses `ARI`. Those two
entries were the *only* divergences; without them NFL matched 29/31 and MLB
failed outright. The table is explicit and reviewable in the probe. It is not a
fuzzy fallback and must never become one.

**A corrected start time.** See below.

## 4. `occurrence_datetime` is wrong by exactly three hours

Measured against the canonical registries:

```
MLB: kalshi occurrence_datetime − registry start = +3.00 h   × 35 of 35
NFL: kalshi occurrence_datetime − registry start = +3.00 h   × 29 of 29
```

Perfectly consistent, zero variance, n=64. Triangulated against a third
independent source: Polymarket US states the same SF@LAR game starts
`2026-09-11T00:35:00Z`, agreeing with our registry, while Kalshi reports
`03:35:00Z`.

This matters because a three-hour error blows straight through the 1800-second
kickoff tolerance. Using `occurrence_datetime` raw, MLB linkage collapsed to
26/35 with 7 ambiguous — consecutive games in a series share a UTC date, so a
date-only key cannot separate them either.

Two mitigations, both in the probe:

- MLB uses the **ticker-embedded local time read as US Eastern**, which is
  exact.
- NFL has no time in the ticker and uses `occurrence_datetime − 3h`.

The offset is **asserted, not trusted**. `check_occurrence_offset` recomputes
it every run and reports `DRIFTED` if the observed set is anything other than
exactly `[3.0]`. If Kalshi silently corrects this, a hardcoded constant would
keep matching and start binding markets to the *wrong game*; that failure must
be loud.

## 5. Order book: bids only, asks are derived

`/markets/{ticker}/orderbook` returns `orderbook_fp.yes_dollars` and
`no_dollars` — **resting bids on both sides, no asks**. Levels arrive ascending
by price, so the last entry is the best bid.

To buy YES you must lift the best NO bid, therefore:

```
YES ask = 1 − best NO bid
NO  ask = 1 − best YES bid
```

Verified against each market's own quoted `yes_ask_dollars` / `no_ask_dollars`:
**24 of 24 CONFIRMED**, zero mismatches. Worked example:

```
KXNFLGAME-26SEP10SFLAR-LAR
  best YES bid 0.64      best NO bid 0.35
  YES ask = 1 − 0.35 = 0.65      (matches quoted yes_ask_dollars 0.6500)
  NO  ask = 1 − 0.64 = 0.36      (matches quoted no_ask_dollars  0.3600)
  YES ask + NO ask = 1.01 — above 1 by the spread, as it must be
```

Within a single market the two asks always sum above $1. A sum below $1 can
only ever arise *across* venues, and only after fees.

**Do not use `liquidity_dollars`.** It read `0.0000` on markets whose books
held millions of contracts. Depth must come from the book itself.

**Quantity units are unconfirmed.** Levels are `[price, quantity]` and the
documentation calls the second element a contract quantity, but the field is
named `*_dollars`. A depth simulator must resolve this before sizing anything.

## 6. Liquidity is real for NFL and thin for MLB

Full sample, one market per event, depth 20:

| | NFL (31) | MLB (35) |
|---|---|---|
| Two-sided books | **31 / 31** | **35 / 35** |
| Empty on ≥1 side | 0 | 0 |
| Spread, median | **0.01** | **0.07** |
| Spread, max | 0.11 | 0.46 |
| Spread exactly 1¢ | 17 / 31 | 4 / 35 |
| Top-level qty, median | 399 | 987 |
| Top-level qty, min | **1** | **1** |
| Depth across top 5, median | 6,055 | 5,152 |

NFL is genuinely tight. **MLB's 7¢ median spread exceeds any plausible
cross-venue edge**, and would have to be crossed on the Kalshi leg. Some books
have a single contract at the top level, so top-of-book pricing overstates
executable size — the depth simulator is load-bearing, not a refinement.

## 7. Fees — the blocking gap

> **Corrected 2026-09-10.** The claim below that the API exposes no fee data
> was wrong. `GET /series/fee_changes` returns `fee_type` and
> `fee_multiplier` per series: `KXNFLGAME` is `quadratic_with_maker_fees` at
> multiplier 1.0, `KXMLBGAME` at 0.5. The model, the maker-fee flag and the
> multiplier are all machine-readable; only the **base constant** of the
> quadratic is not. See [`economics_notes.md`](economics_notes.md) §2.

**No fee field appears on the event or**
the market objects themselves. The base constant lives only in a PDF at
`kalshi.com/docs/kalshi-fee-schedule.pdf`, which returned HTTP 429 on two
attempts and remains **unretrieved**.

What is established from the help centre: fees are charged on *expected
earnings* rather than notional, so they are price-dependent and largest near
50¢ — exactly where sports moneylines sit. Maker fees exist on some markets.
Some markets carry schedules different from the default.

Polymarket US, by contrast, **does** expose a fee input: `feeCoefficient: 0.06`
on the moneyline market. So Polymarket US is not fee-free either.

Consequences for a future fee engine:

- It cannot self-update from the Kalshi API. The schedule must be transcribed,
  version-pinned, and re-checked on a cadence.
- Any net-arb figure computed before that PDF is read is unsound.
- Tick sizes differ — Kalshi `0.01`, Polymarket US `0.005` — so a Polymarket
  price may be unrepresentable on Kalshi.

## 8. Contract equivalence: one clean match, one hard divergence

All 31 NFL Kalshi games have a Polymarket US accepted link in the registry, so
overlap is total. Comparing actual rules text for `NFL-2026-REG-W1-SF-LAR`:

| Dimension | Kalshi | Polymarket US | Verdict |
|---|---|---|---|
| Winner | game winner | game winner | match |
| Tie | resolves **$0.50 each** | settles **$0.50** | match |
| Overtime | **not stated** | "Overtime is included if played" | **unstated on Kalshi** |
| Postponement tolerated | **48 hours** | **two weeks** | **DIVERGENT** |
| Beyond tolerance | "a fair market price" | "the last fair market price" | wording differs, mechanism unverified |
| Settlement source | the Governing League (nfl.com) | NFL | match |

MLB shows the same shape: Kalshi tolerates **two days**, Polymarket US **two
weeks**; Polymarket states "Extra innings are included if played" and cites
MLB, while Kalshi cites ESPN, Fox Sports and mlb.com.

### The failure this creates

A game postponed and replayed five days later:

```
Polymarket US   within two weeks  → settles on the real result   $1 or $0
Kalshi          beyond 48 hours   → settles to "fair market price"
```

A position built as "Poly YES + Kalshi NO" for a guaranteed $1.00 then pays
$1-or-$0 on one leg and a mark-to-market value on the other. The hedge is gone
and what remains is an unhedged directional position. This is the canonical
looks-like-free-money case, and it is invisible to any comparison that only
reads prices.

### Proposed classification

- **EXACT** — same winner definition, same tie treatment, same overtime/extra
  innings treatment, *same postponement tolerance*, same settlement source,
  and both legs linked to one canonical `game_uuid`. Only EXACT may ever enter
  an arbitrage calculation.
- **PROBABLE** — everything matches except a dimension that is unstated rather
  than contradictory. On today's evidence **every NFL pair lands here**,
  because Kalshi does not state overtime treatment and the postponement
  windows differ. Research and record only.
- **REJECTED** — a dimension is known to differ in a way that can change
  payout, or linkage is not EXACT.

**On today's data, the honest classification of every sampled NFL pair is
PROBABLE, not EXACT.** The 48-hour versus two-week divergence is real and
documented, not a wording artefact.

## 9. Other equivalence risks identified

- **Overtime.** Kalshi runs a separate `KXNFLOTWIN` series, implying the game
  market includes OT, but the game market's own rules never say so. Inference,
  not evidence.
- **"Fair market price" is undefined.** Both venues use the phrase for the
  abandonment case; neither defines the mechanism in the text retrieved. Two
  different mechanisms both called "fair market price" would not offset.
- **`can_close_early: true`** with `settlement_timer_seconds: 60`. A market can
  stop trading before its stated `close_time`, so one leg may become
  unhedgeable while the other still trades.
- **`close_time` is after the game.** For the SF@LAR game, start is
  `2026-09-11T00:35Z` but `close_time` is `2026-09-13T00:35Z` — the expiration
  window, not the trading deadline. Do not read it as either the start or the
  end of trading.
- **Multiple settlement sources on MLB.** Kalshi lists three (ESPN, Fox
  Sports, mlb.com) without stating precedence; Polymarket US cites MLB alone.
  Sources agreeing almost always is not the same as agreeing always.
- **Doubleheaders.** Handled today only because MLB tickers embed start time.
  Our registry models `doubleheader_code` / `game_number` explicitly; Kalshi
  does not, so a doubleheader whose start time shifts loses its discriminator.
- **Tie handling is a real NFL outcome**, not hypothetical, and both venues pay
  $0.50 — which means a "complete outcome" purchase returns $1.00 on a tie
  only if *both* legs honour it. They do here. That should be asserted, not
  assumed, per pair.

## 10. Verdict

**Technically viable, and not yet economically demonstrated.**

Viable because the two hard prerequisites are met: linkage is deterministic
(66/66 EXACT) and depth is real and readable (66/66 two-sided books, NFL median
spread 1¢). Those were the parts that could have been fatal, and neither is.

Not demonstrated because no net-arb number can be computed yet. The Kalshi fee
schedule is unread, `feeCoefficient` semantics on Polymarket US are
untranslated into a cost, quantity units in the book are unconfirmed, and every
sampled pair classifies as PROBABLE rather than EXACT on rules.

Nothing observed says there is free money here. What the audit establishes is
that the question is now *answerable* — which it was not before, because the
identity layer was unproven.

## 11. What to build next, in order

1. **Retrieve and transcribe the Kalshi fee schedule.** Everything downstream
   is unsound without it. Version-pin it; it is not machine-readable.
2. **Confirm order book quantity units.** One resolved ambiguity, blocking any
   sizing.
3. **Resolve the two unstated rule dimensions** — Kalshi overtime treatment and
   the definition of "fair market price" on both venues. This is what moves
   pairs from PROBABLE toward EXACT, and it is a documentation question, not a
   code one.
4. **Then, and only then**, an observation-only recorder writing the timeline
   the plan calls for: both books, derived asks, fees, net figure, depth, and
   opportunity duration — into its own store, never the production registry.

Steps 1–3 are reading, not building. Building before them produces confident
numbers that are wrong, which is worse than no numbers.

## 12. Explicitly not built

No arbitrage engine, no fee engine, no depth simulator, no order placement or
simulation, no dashboard integration, no Telegram notifications, no persistent
Kalshi database, no production code changes.
