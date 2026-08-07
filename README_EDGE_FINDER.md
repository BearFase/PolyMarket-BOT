# Canonical NFL Edge Scanner

The former title-matching sports scanner is retired. It could associate odds
and markets by partial team names without proving that they represented the
same contest. Its historical output must not be treated as authoritative.

The replacement is NFL-only and research-only. It reads the canonical sports
registry and requires all of the following before calculating an observation:

1. A verified canonical NFL game UUID exists.
2. An Odds API moneyline link has `match_status=ACCEPTED` for that UUID.
3. A Polymarket US moneyline link has `match_status=ACCEPTED` for that UUID.
4. Both links are fresh according to `sportsbook_quote_max_age_seconds`.
5. Both sources contain valid prices for both canonical teams.

The scanner never matches titles itself, never uses global Polymarket Gamma,
and never creates real orders, paper positions, or simulation selections.

## Run

Populate verified production links first, then calculate observations:

```powershell
python nfl_schedule.py link-odds --env production
python nfl_schedule.py link-polymarket --env production
python sports_edge_finder.py --env production
```

Output is written atomically to `sports_edges.json`. Every edge includes the
canonical game UUID, canonical game ID, Odds API event ID, Polymarket US event
and market IDs, source observation times, and the compared probabilities.

The configured threshold is `nfl_edge_minimum_percentage_points` in
`nfl_config.json`. It is a display/research threshold, not a validated strategy
rule or performance claim. Edge is defined as:

```text
bookmaker vig-free consensus probability - Polymarket US side price
```

and is displayed in percentage points.

## Tests

```powershell
python -m unittest test_canonical_edge_scanner.py
python -m unittest discover -p "test_*.py"
```
