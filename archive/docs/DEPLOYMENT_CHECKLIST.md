# Historical deployment checklist

This archived checklist documented the early real-position dashboard,
Polymarket US API synchronization, position-direction interpretation, and
optional Telegram setup.

All embedded operational identifiers have been removed:

```env
POLYMARKET_API_KEY=<REDACTED>
POLYMARKET_API_SECRET=<REDACTED>
POLYMARKET_WALLET=<REDACTED>
TELEGRAM_BOT_TOKEN=<REDACTED>
TELEGRAM_CHAT_ID=<REDACTED>
```

The active deployment path is now `Open Dashboard.cmd`, `bot_launcher.py`,
`nfl_daily_update.py`, `health_check.py`, and the supported Task Scheduler
installer. Refer to the root `README.md` for current instructions.
