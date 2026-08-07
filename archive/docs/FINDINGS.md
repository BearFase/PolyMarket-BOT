# France vs England Market Hunt - Findings

## Date: 2026-07-18
## Task: Find France vs England 3rd place market on Polymarket

## Key Discovery: Markets API Doesn't Return World Cup Data

### Evidence:
1. **Bear has an active World Cup position:**
   - Market: "Spain vs. Argentina"
   - Outcome: Argentina
   - Position: 116.38 contracts (SHORT)
   - Market Slug: `aadc-fwc-esp-arg-2026-07-19-to-advance`
   - Event Slug: `fwc-esp-arg-2026-07-19`
   - Event ID: 52846

2. **But `/v1/markets` API doesn't return ANY World Cup markets:**
   - Tried `limit=2000` - only returns NFL/NBA
   - Tried `category=sports` - only NFL/NBA
   - Tried `league=fwc` - still returns NFL/NBA (filter ignored)
   - Tried `eventSlug=fwc-esp-arg-2026-07-19` - returns NFL/NBA (filter ignored)
   - Tried filtering by date `2026-07-18` - zero results
   - Tried filtering by date `2026-07-19` - zero results

3. **Direct market access fails:**
   - `/v1/markets/aadc-fwc-esp-arg-2026-07-19-to-advance` → 404
   - `/v1/events/fwc-esp-arg-2026-07-19` → 404
   - No individual market/event endpoints work

### Conclusion:
The Polymarket US API **does not expose World Cup markets via the `/v1/markets` endpoint**, even though:
- Bear can trade them on the web interface
- They show up in `/v1/portfolio/positions`
- They exist and are active

## Next Steps Needed:

### Option 1: Use CLOB API (Different System)
Polymarket has a separate CLOB (Central Limit Order Book) API that might have different market data:
- Endpoint: `https://clob.polymarket.com/`
- May require different auth
- Could have access to World Cup markets

### Option 2: Scrape from Web Interface
If API doesn't work, could:
- Use browser automation to get France vs England odds
- Extract from https://polymarket.com directly

### Option 3: Ask Bear for Market URL
If he can see it, he can share the direct link:
- `https://polymarket.com/event/...`
- We can extract market ID/slug from URL

## Argentina Position Issue:
Bear says he's LONG Argentina, but API shows:
- `netPosition`: -116 (negative = SHORT)
- `qtySold`: 116
- `qtyBought`: 0

This is either:
1. API displaying inverted (YES/NO confusion)
2. Bear misremembering his position
3. Position interpretation issue

**Need to investigate:** Does "Argentina to advance" mean he sold NO (betting Argentina wins) or sold YES (betting they lose)?

## Impact:
**Cannot complete primary task** - France vs England market not accessible via standard API.

## Bear's ETA:
Back from walking dog soon - need to ask him:
1. Can you send the France vs England market URL from Polymarket web?
2. Are you sure you're LONG Argentina? (You sold 116 contracts of "Argentina to advance")
3. How did you place the World Cup bets? (Web interface? Mobile app?)
