# Historical critical issues

This archived investigation covered discrepancies between a displayed
Polymarket position and the wallet queried by an early API integration. It
considered wallet mismatch, platform differences, settlement timing, and stale
manual data.

The original wallet identifier has been removed:

```env
POLYMARKET_WALLET=<REDACTED>
```

The issue was superseded by the read-only real-position synchronization and
canonical paper-accounting work. This document is provenance, not current
operating guidance.
