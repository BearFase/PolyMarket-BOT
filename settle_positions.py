"""
Auto-settlement for tracked positions that vanish from the Polymarket US
positions response.

Why: sync_positions_api.py rebuilds the "positions" list from the API on every
sync. When a market resolves (or the user closes the position in the app) the
position simply disappears from /v1/portfolio/positions — and before this
module existed, the sync silently dropped it. Now the sync calls
settle_missing() first, which moves the vanished position into "closed" in
real_positions.json with a result (WIN / LOSS / CLOSED / UNKNOWN) and a
realized P&L.

Position semantics (do not re-derive — verified July 2026 against fill
records, see README "A note on position direction" and the docstrings in
sync_positions_api.py):
  - marketMetadata.outcome names the team/outcome the money is ON. Every
    position backs its named outcome. The sign of netPosition is instrument
    bookkeeping, NOT bet direction.
  - pnl = cashValue - cost, always. If the named outcome wins the shares pay
    qty * $1; if it loses they expire worthless.

How a missing position is classified (in order):
  1. RESOLUTION RECORD (authoritative). /v1/portfolio/activities returns
     ACTIVITY_TYPE_POSITION_RESOLUTION entries whose beforePosition carries
     the same marketMetadata (eventSlug + outcome) as the position we
     tracked. The exchange's realized P&L delta (afterPosition.realized -
     beforePosition.realized) is positive exactly when the backed outcome
     won (payout qty * $1) and negative when it lost (stake gone). We use
     the delta only for its SIGN; the booked pnl uses our tracked cost so
     it stays consistent with the open-position convention
     (pnl = cashValue - cost, fees included in cost):
        WIN  -> pnl = qty * $1 - cost
        LOSS -> pnl = -cost
     (The exchange "realized" figure excludes entry fees — it is baseCost
     based — so it is recorded in the notes for audit, not booked.)
     NOTE: positionResolution.side (POSITION_RESOLUTION_SIDE_LONG/SHORT) is
     instrument bookkeeping like the netPosition sign. Verified against real
     data: a straightforward "bought Yes" position resolved with
     side=SHORT. Never use it for direction.
  2. MANUAL CLOSE. Trade activities that REDUCE a position carry a
     realizedPnl field (opening fills don't — verified against real July
     2026 fills). If we find realizedPnl-bearing fills for the position's
     market and no resolution record, the user closed it in the app: book
     the summed realized P&L from the fills, result CLOSED.
  3. PRICE TIEBREAKER (fallback when activities are unavailable or have no
     trace). Use the position's last known current_price:
        >= 0.95 -> WIN  (pnl = qty * $1 - cost)
        <= 0.05 -> LOSS (pnl = -cost)
        else    -> UNKNOWN: book last known unrealized pnl
                   (current_value - cost) and flag for human review.

Never double-settles: a position whose (event_slug, outcome) already appears
in "closed" is skipped. (event_slug alone would wrongly block the second of
two same-event positions, e.g. a moneyline and a totals bet on one game.)

Read-only: this module only ever GETs. It never places orders.
"""

import os
import time
import base64
import urllib.parse
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives.asymmetric import ed25519

load_dotenv()

API_BASE = "https://api.polymarket.us"
GATEWAY_BASE = "https://gateway.polymarket.us"
ACTIVITIES_PATH = "/v1/portfolio/activities"
MAX_ACTIVITY_PAGES = 5

WIN_PRICE_THRESHOLD = 0.95
LOSS_PRICE_THRESHOLD = 0.05


def fetch_market_settlement(market_slug):
    """Return the official instrument settlement (0 or 1), else None."""
    if not market_slug:
        return None
    response = requests.get(
        f"{GATEWAY_BASE}/v1/markets/{market_slug}/settlement", timeout=15)
    if response.status_code != 200:
        return None
    value = response.json().get("settlement")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value in (0.0, 1.0) else None


# ---------------------------------------------------------------------------
# Activities fetch (read-only GET, same auth pattern as sync_positions_api)
# ---------------------------------------------------------------------------

def _auth_headers(method, path):
    """Signed headers for the Polymarket US API.

    IMPORTANT: the signature message must use the BARE path — no query
    string. Signing the path including "?cursor=..." returns 401
    (verified live 2026-07-18).
    """
    key_id = os.getenv("POLYMARKET_API_KEY")
    secret = os.getenv("POLYMARKET_API_SECRET")
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(secret)[:32])
    timestamp = str(int(time.time() * 1000))
    signature = base64.b64encode(
        private_key.sign(f"{timestamp}{method}{path}".encode())).decode()
    return {
        "X-PM-Access-Key": key_id,
        "X-PM-Timestamp": timestamp,
        "X-PM-Signature": signature,
    }


def fetch_activities(max_pages=MAX_ACTIVITY_PAGES):
    """Fetch recent activity records (trades, position resolutions).

    Follows nextCursor pagination up to max_pages or eof. Returns a list of
    raw activity dicts, newest first (API order). Raises on a failed first
    page; a mid-pagination failure returns what was collected so far.
    """
    activities = []
    cursor = None
    for page in range(max_pages):
        url = API_BASE + ACTIVITIES_PATH
        if cursor:
            url += "?cursor=" + urllib.parse.quote(cursor, safe="")
        response = requests.get(
            url, headers=_auth_headers("GET", ACTIVITIES_PATH), timeout=30)
        if response.status_code != 200:
            if page == 0:
                raise Exception(
                    f"Activities API error: {response.status_code} - "
                    f"{response.text[:200]}")
            break  # keep what we have
        data = response.json()
        activities.extend(data.get("activities", []))
        cursor = data.get("nextCursor")
        if data.get("eof") or not cursor:
            break
    return activities


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _money(value):
    """Parse an API money dict ({'value': '49.9980', ...}) or scalar -> float."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
        if value is None:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm(s):
    return (s or "").strip().lower()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _open_keys_from_api(api_positions):
    """Set of (event_slug, outcome) pairs still open per the API response.

    api_positions is the raw dict from /v1/portfolio/positions
    ({marketSlug: position}); tolerates None/empty.
    """
    keys = set()
    for pos in (api_positions or {}).values():
        meta = pos.get("marketMetadata", {}) or {}
        keys.add((_norm(meta.get("eventSlug")), _norm(meta.get("outcome"))))
    return keys


def _already_closed(closed_entries, event_slug, outcome):
    """True if this (event_slug, outcome) was already booked in closed."""
    for entry in closed_entries:
        if _norm(entry.get("event_slug")) != _norm(event_slug):
            continue
        # Entries missing an outcome are treated as a match (conservative:
        # never double-book).
        if "outcome" not in entry or _norm(entry.get("outcome")) == _norm(outcome):
            return True
    return False


def _find_resolution(activities, event_slug, outcome):
    """Latest ACTIVITY_TYPE_POSITION_RESOLUTION matching this position.

    Primary match: beforePosition.marketMetadata eventSlug + outcome.
    Fallback: market slug embeds the event slug (real slugs look like
    "aadc-fwc-esp-arg-2026-07-19-to-advance" for event
    "fwc-esp-arg-2026-07-19") — only used when metadata is absent.
    """
    matches = []
    for act in activities or []:
        if act.get("type") != "ACTIVITY_TYPE_POSITION_RESOLUTION":
            continue
        res = act.get("positionResolution", {}) or {}
        before = res.get("beforePosition", {}) or {}
        meta = before.get("marketMetadata", {}) or {}
        if meta.get("eventSlug"):
            if (_norm(meta.get("eventSlug")) == _norm(event_slug)
                    and _norm(meta.get("outcome")) == _norm(outcome)):
                matches.append(res)
        elif event_slug and _norm(event_slug) in _norm(res.get("marketSlug")):
            matches.append(res)
    if not matches:
        return None
    return max(matches, key=lambda r: r.get("updateTime") or "")


def _closing_fills(activities, event_slug, market_slug=None):
    """Trade fills that reduced/closed this position (they carry realizedPnl).

    Matched by exact marketSlug when known (from a resolution record),
    otherwise by the market slug embedding the event slug.
    """
    fills = []
    for act in activities or []:
        if act.get("type") != "ACTIVITY_TYPE_TRADE":
            continue
        trade = act.get("trade", {}) or {}
        slug = trade.get("marketSlug") or ""
        if market_slug:
            if _norm(slug) != _norm(market_slug):
                continue
        elif not event_slug or _norm(event_slug) not in _norm(slug):
            continue
        realized = _money(trade.get("realizedPnl"))
        if realized is None:
            realized = _money(trade.get("effectiveRealizedPnl"))
        if realized is not None:
            fills.append((trade, realized))
    return fills


def _entry_time_from_fills(activities, market_slug, fallback):
    """Earliest opening fill (a trade WITHOUT realizedPnl) on this market."""
    times = []
    for act in activities or []:
        if act.get("type") != "ACTIVITY_TYPE_TRADE":
            continue
        trade = act.get("trade", {}) or {}
        if _norm(trade.get("marketSlug")) != _norm(market_slug):
            continue
        if _money(trade.get("realizedPnl")) is not None:
            continue
        if trade.get("createTime"):
            times.append(trade["createTime"])
    return min(times) if times else fallback


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

def _build_closed_entry(position, result, pnl, exit_price, exit_time,
                        notes, settlement_source, entry_time=None):
    """Closed-position record matching the existing shape in
    real_positions.json "closed" (plus event_slug/contracts/settlement for
    dedup and audit)."""
    return {
        "id": position.get("id", ""),
        "market": position.get("market", "Unknown"),
        "outcome": position.get("outcome", "Unknown"),
        "entry_price": position.get("entry_price", 0),
        "exit_price": round(exit_price, 4) if exit_price is not None else None,
        "size": position.get("size", position.get("cost_basis", 0)),
        "pnl": round(pnl, 2),
        "entry_time": entry_time or position.get("last_updated", ""),
        "exit_time": exit_time or _now_iso(),
        "notes": notes,
        "result": result,
        "event_slug": position.get("event_slug", "unknown"),
        "contracts": position.get("contracts", 0),
        "settlement": settlement_source,
    }


def _settle_one(position, activities,
                fetch_settlement_fn=fetch_market_settlement):
    """Classify one vanished position -> closed entry dict."""
    event_slug = position.get("event_slug", "")
    outcome = position.get("outcome", "Unknown")
    instrument_outcome = position.get("instrument_outcome", outcome)
    qty = float(position.get("contracts", 0) or 0)
    cost = float(position.get("cost_basis", position.get("size", 0)) or 0)
    current_price = float(position.get("current_price", 0) or 0)
    current_value = float(position.get("current_value", 0) or 0)

    win_pnl = qty * 1.00 - cost
    loss_pnl = -cost

    # 0) Authoritative market settlement. This remains available even when
    # the portfolio activities endpoint temporarily omits the resolution.
    market_slug = position.get("market_slug", "")
    try:
        official = fetch_settlement_fn(market_slug)
    except Exception:
        official = None
    if official is not None:
        selected_side = str(position.get("selected_side") or outcome).lower()
        chose_short = selected_side in ("no", "short")
        won = (official == 0.0) if chose_short else (official == 1.0)
        return _build_closed_entry(
            position, "WIN" if won else "LOSS",
            win_pnl if won else loss_pnl, 1.0 if won else 0.0, _now_iso(),
            f"Auto-settled from official market settlement ({market_slug}="
            f"{official:g}). {outcome} {'won' if won else 'lost'}.",
            "official_market_settlement")

    # 1) Authoritative: the exchange's own resolution record.
    resolution = _find_resolution(activities, event_slug, instrument_outcome)
    if resolution is not None:
        before = resolution.get("beforePosition", {}) or {}
        after = resolution.get("afterPosition", {}) or {}
        realized_before = _money(before.get("realized")) or 0.0
        realized_after = _money(after.get("realized"))
        market_slug = resolution.get("marketSlug", "")
        entry_time = _entry_time_from_fills(
            activities, market_slug, position.get("last_updated", ""))
        exit_time = resolution.get("updateTime") or _now_iso()
        if realized_after is not None:
            delta = realized_after - realized_before
            if delta > 0:
                return _build_closed_entry(
                    position, "WIN", win_pnl, 1.0, exit_time,
                    f"Auto-settled from exchange resolution record "
                    f"({market_slug}). {outcome} won; payout "
                    f"{qty:.2f} x $1. Exchange realized delta "
                    f"${delta:+.2f} (excludes entry fees; booked P&L uses "
                    f"tracked cost incl. fees).",
                    "resolution", entry_time)
            if delta < 0:
                return _build_closed_entry(
                    position, "LOSS", loss_pnl, 0.0, exit_time,
                    f"Auto-settled from exchange resolution record "
                    f"({market_slug}). {outcome} lost; shares expired "
                    f"worthless. Exchange realized delta ${delta:+.2f}.",
                    "resolution", entry_time)
        # delta == 0 or missing realized: fall through to the tiebreaker.

    # 2) Manual close in the app: fills carrying realizedPnl.
    fills = _closing_fills(activities, event_slug)
    if fills:
        realized_total = sum(realized for _, realized in fills)
        closed_qty = sum(_money(t.get("qtyDecimal")) or _money(t.get("qty")) or 0
                         for t, _ in fills)
        basis_total = sum(_money(t.get("costBasis")) or 0 for t, _ in fills)
        times = [t.get("createTime") for t, _ in fills if t.get("createTime")]
        exit_time = max(times) if times else _now_iso()
        slugs = sorted({t.get("marketSlug", "") for t, _ in fills})
        # Effective exit price on OUR side of the market: proceeds per share.
        # (Fill 'price' is instrument-side and can be the other team's price.)
        if closed_qty > 0 and basis_total > 0:
            exit_price = max(0.0, (basis_total + realized_total) / closed_qty)
        else:
            exit_price = current_price
        entry_time = _entry_time_from_fills(
            activities, slugs[0] if len(slugs) == 1 else "",
            position.get("last_updated", ""))
        qty_note = ""
        if qty and abs(closed_qty - qty) > max(0.02 * qty, 0.02):
            qty_note = (f" NOTE: closing qty {closed_qty:.2f} != tracked "
                        f"{qty:.2f} — verify.")
        return _build_closed_entry(
            position, "CLOSED", realized_total, exit_price, exit_time,
            f"Manually closed in app ({', '.join(slugs)}); booked exchange "
            f"realized P&L from {len(fills)} closing fill(s).{qty_note}",
            "manual_close", entry_time)

    # 3) Fallback: last-known-price tiebreaker.
    if current_price >= WIN_PRICE_THRESHOLD:
        return _build_closed_entry(
            position, "WIN", win_pnl, 1.0, None,
            f"Position gone from API; no activity record found. Last price "
            f"{current_price:.3f} >= {WIN_PRICE_THRESHOLD} -> settled as WIN "
            f"(payout {qty:.2f} x $1).",
            "price_tiebreaker")
    if current_price <= LOSS_PRICE_THRESHOLD:
        return _build_closed_entry(
            position, "LOSS", loss_pnl, 0.0, None,
            f"Position gone from API; no activity record found. Last price "
            f"{current_price:.3f} <= {LOSS_PRICE_THRESHOLD} -> settled as "
            f"LOSS (stake lost).",
            "price_tiebreaker")
    return _build_closed_entry(
        position, "UNKNOWN", current_value - cost, current_price, None,
        f"NEEDS REVIEW: position gone from API but no resolution/close "
        f"record found and last price {current_price:.3f} is inconclusive. "
        f"Booked last known unrealized P&L (cashValue - cost). Verify the "
        f"real result in the app and correct pnl/result by hand.",
        "price_tiebreaker")


def settle_missing(existing_data, api_positions, fetch_activities_fn=fetch_activities,
                   fetch_settlement_fn=fetch_market_settlement):
    """Settle tracked positions that no longer appear in the API response.

    Pure-ish core of the auto-settlement flow (no file or network I/O except
    via the injected fetch_activities_fn, which is only called when at least
    one position is actually missing).

    Args:
      existing_data: parsed real_positions.json dict ({"positions": [...],
        "closed": [...], ...}). MUTATED: settled entries are appended to
        existing_data["closed"].
      api_positions: raw positions dict from /v1/portfolio/positions
        ({marketSlug: position}); {} / None means nothing is open.
      fetch_activities_fn: () -> list of raw activity dicts. Injected for
        tests. Failures are tolerated (falls back to the price tiebreaker).

    Returns:
      List of the newly appended closed entries (empty if nothing settled).
      Never raises: a failure while settling one position skips it (it stays
      missing and is retried on the next sync) without affecting the others.
    """
    settled = []
    try:
        tracked = list((existing_data or {}).get("positions", []) or [])
        if not tracked:
            return settled
        closed = existing_data.setdefault("closed", [])
        open_keys = _open_keys_from_api(api_positions)

        missing = [
            p for p in tracked
            if (_norm(p.get("event_slug")),
                _norm(p.get("instrument_outcome", p.get("outcome")))) not in open_keys
        ]
        if not missing:
            return settled

        try:
            activities = fetch_activities_fn()
        except Exception:
            activities = []  # tiebreaker path still books a result

        for position in missing:
            try:
                if _already_closed(closed, position.get("event_slug"),
                                   position.get("outcome")):
                    continue
                entry = _settle_one(position, activities, fetch_settlement_fn)
                closed.append(entry)
                settled.append(entry)
            except Exception:
                # Never let one bad position break the sync; it will be
                # retried (still missing) on the next run.
                continue
    except Exception:
        pass
    return settled
