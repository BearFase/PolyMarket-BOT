# Historical platform summary

This archived note described the early Polymarket bot setup, position syncing,
dashboard, and API diagnostics before the canonical NFL research platform was
established.

The original note included machine-specific paths and operational identifiers.
Those values have been removed. Historical configuration examples are retained
only as placeholders:

```env
POLYMARKET_API_KEY=<REDACTED>
POLYMARKET_API_SECRET=<REDACTED>
POLYMARKET_WALLET=<REDACTED>
```

The active equivalents are now `sync_positions_api.py`, `bot_launcher.py`,
`health_check.py`, and the canonical NFL workflow. Current setup instructions
live in the root `README.md` and `.env.example`.

Never commit `.env`, share API secrets, or include credentials in screenshots.
Rotate any credential that may have been exposed historically.
