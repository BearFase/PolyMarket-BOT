# API configuration

This platform authenticates against **Polymarket US** — `api.polymarket.us`
and `gateway.polymarket.us` — not the international `polymarket.com` stack.
Credentials issued by `polymarket.com` will not authenticate here.

Copy `.env.example` to `.env` and enter your own Polymarket US credentials.
Never place real keys, secrets, or tokens in source, tests, screenshots, logs,
or commits. `.env` is ignored by Git; `.env.example` is tracked, so it must
only ever contain placeholders.

## Creating credentials

Create and revoke keys at <https://polymarket.us/developer>. The portal names
the two values **Key ID** and **Secret Key**:

```env
POLYMARKET_API_KEY=your-key-id
POLYMARKET_API_SECRET=your-secret-key
```

The Secret Key is displayed **once**, at creation. Copy it before closing the
dialog — if it is lost, the only remedy is to revoke that key and create a new
one. It is a base64 Ed25519 private key: the client decodes it and signs every
request with it, so anyone holding it can act on the account.

## Rotating a compromised credential

Revoking is what invalidates a leaked key. Creating a replacement does not
disable the old one, and a leaked key keeps working normally until it is
revoked — so a successful connection test is not evidence that a credential is
uncompromised.

1. Revoke the affected key at <https://polymarket.us/developer>.
2. Create a new key and copy both values.
3. Update `POLYMARKET_API_KEY` and `POLYMARKET_API_SECRET` in `.env`.
4. Restart the dashboard so the new values are loaded:

   ```powershell
   .\.venv\Scripts\python.exe bot_launcher.py stop
   .\.venv\Scripts\python.exe bot_launcher.py task-start
   ```

   A restart is required: `load_dotenv()` does not override variables already
   present in a running process's environment.

## Verifying

```powershell
.\.venv\Scripts\python.exe test_all_systems.py
.\.venv\Scripts\python.exe sync_positions_api.py
.\.venv\Scripts\python.exe get_positions.py
```

These are read-only checks. `test_all_systems.py` masks every credential it
reports, so its output is safe to share.
