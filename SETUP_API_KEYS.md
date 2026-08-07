# API configuration

Copy `.env.example` to `.env` and enter your own Polymarket US credentials and
wallet identifier. Never place real keys, secrets, tokens, or private wallet
information in source, tests, screenshots, logs, or commits.

```env
POLYMARKET_API_KEY=your-api-key-id
POLYMARKET_API_SECRET=your-api-secret
POLYMARKET_WALLET=your-wallet-identifier
```

Verify the read-only connection and position synchronization with:

```powershell
python test_all_systems.py
python sync_positions_api.py
python get_positions.py
```

The active platform reads credentials only from local `.env`, which is ignored
by Git. If a credential has ever been exposed in tracked documentation or a
shared screenshot, rotate it with the provider.
