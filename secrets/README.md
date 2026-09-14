# secrets/

Private key material lives here. Everything in this directory is ignored by
Git except this file and `.gitignore` — the deny-all rule matches any filename,
not just known extensions, so a key saved as `kalshi key (1)` is covered too.

Nothing here is ever committed, pasted into a chat, included in a screenshot,
or attached to an issue. If a credential is exposed, revoking it at the
provider is what invalidates it; creating a replacement does not disable the
old one, and a successful connection test is not evidence a credential is
uncompromised.

## Kalshi

Kalshi signs requests with an RSA key pair, so it needs a **file**, not just an
environment variable. Two pieces:

| Piece | Where it goes |
|---|---|
| Key ID (a UUID) | `KALSHI_API_KEY_ID` in `.env` |
| RSA private key (PEM) | `secrets/kalshi_private_key.pem` |

Create the pair in your Kalshi account's API settings. The private key is
downloaded once, at creation — Kalshi keeps only the public half. If you lose
it, delete the key and create another.

Requests carry three headers: `KALSHI-ACCESS-KEY` (the key ID),
`KALSHI-ACCESS-TIMESTAMP`, and `KALSHI-ACCESS-SIGNATURE` (the timestamp, method
and path signed with the private key).

Save the file with the PEM wrapper intact:

```
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

## Polymarket US

Polymarket US uses a base64 Ed25519 secret rather than a key file, so both of
its values live in `.env` and nothing for it belongs in this directory. See
[`../SETUP_API_KEYS.md`](../SETUP_API_KEYS.md).

## Checking that Git is ignoring a file

```powershell
git check-ignore -v secrets\kalshi_private_key.pem
```

Output naming a rule means it is ignored. **No output means it is NOT ignored**
— stop and fix that before committing anything.
