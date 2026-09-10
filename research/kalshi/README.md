# Kalshi — quarantined research area

An **audit**, not an integration. It establishes whether Kalshi exposes clean
NFL/MLB straight moneyline contracts that could be linked deterministically to
our canonical registries and priced from executable depth. Nothing here is
imported, launched, scheduled or routed by production, and nothing here writes
to project state.

Findings and the recommendation are in
[`integration_notes.md`](integration_notes.md). Captured schema and aggregates
are in [`sample_schema.json`](sample_schema.json).

## Headline results

| | |
|---|---|
| Clean game series | `KXNFLGAME`, `KXMLBGAME`, isolated by `product_metadata.competition_scope == "Game"` |
| Clean markets found | 31 NFL events, 35 MLB events (2 markets each) |
| Canonical linkage | **66 / 66 EXACT**, 0 ambiguous, 0 unmatched |
| Order book | bids only; `YES ask = 1 − best NO bid`, **24/24 confirmed** |
| Two-sided books | **66 / 66** |
| Spread (median) | NFL **0.01**, MLB **0.07** |
| Blocking gap | Kalshi fee schedule is **not** in the API and is unretrieved |
| Rule equivalence | every sampled pair is **PROBABLE**, not EXACT |

## Why it is quarantined

Kalshi is a second venue with its own schedules, teams, prices and settlement
rules. Left unfenced it could quietly become a competing source of truth beside
the canonical registries — the exact failure the NFL registry was built to
prevent. So:

| Fence | How |
|---|---|
| No production reachability | No project module imports anything under `research/` |
| Registries are read-only | `--verify-linkage` opens SQLite via `mode=ro` URIs, SELECT only |
| No new source of truth | The probe writes one JSON summary and nothing else |
| No credential exposure | Key id and PEM are read, used to sign, never printed, logged or hashed for display |
| Not committed | `secrets/`, caches and runtime files stay gitignored |

It reuses the project venv — `requests`, `cryptography` and `python-dotenv` are
already pinned in `requirements.txt`, so unlike the nflverse audit no separate
environment is needed.

## Run

```bash
cd "D:\Bear\BearHandzAI\Projects\PolyMarket-BOT" && ./.venv/Scripts/python.exe research/kalshi/kalshi_probe.py --verify-linkage
```

| Flag | Effect |
|---|---|
| `--verify-linkage` | Read-only canonical registry join, plus the offset assertion |
| `--sport nfl\|mlb\|both` | Which sport to audit (default both) |
| `--books N` | Order books to fetch per sport (default 12) |

Requests are GET-only and paced at 4/second. Rewrites `sample_schema.json`.

Expected output:

```
[NFL] 31 scope=Game events, 12 books, links={'EXACT': 31}, transform={'CONFIRMED': 12}, offset=STABLE
[MLB] 35 scope=Game events, 12 books, links={'EXACT': 35}, transform={'CONFIRMED': 12}, offset=STABLE
```

**`offset=DRIFTED` means stop.** Kalshi's `occurrence_datetime` runs exactly 3
hours ahead of true scheduled start; the probe corrects for it and re-asserts
it every run. If that ever changes, matching would silently bind markets to the
wrong game rather than fail — so the assertion is the safety net, not a
diagnostic.

## Credentials

Reads `KALSHI_API_KEY_ID` from `.env` and the RSA private key from the path in
`KALSHI_PRIVATE_KEY_PATH` (`secrets/kalshi_private_key.pem`). See
[`../../secrets/README.md`](../../secrets/README.md). Requests are signed
RSA-PSS / SHA-256 / MGF1, salt length = digest length, base64, over
`timestamp_ms + METHOD + path`.

## What this folder must not become

- A **second schedule or results source**. The canonical registries stay
  authoritative; Kalshi attaches to an existing `game_uuid` or is rejected.
- A place where **PROBABLE pairs get treated as EXACT**. Only EXACT may ever
  enter an arbitrage calculation, and today nothing qualifies.
- A source of **net-arb numbers before the fee schedule is read**. Confident
  wrong numbers are worse than none.

## `fixtures/`

Trimmed, sanitized samples of public market data — one NFL game event, one MLB
game event, one order book summary — for reasoning and future deterministic
tests without re-hitting the API. No credentials, no account data. 17 KB total.
