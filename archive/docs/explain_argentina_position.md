# Argentina Position - What Does It Mean?

## Raw Position Data:
```json
{
  "netPosition": "-116",
  "qtyBought": "0",
  "qtySold": "116",
  "cost": {
    "value": "49.9980",
    "currency": "USD"
  },
  "marketMetadata": {
    "title": "Spain vs. Argentina",
    "outcome": "Argentina",
    "eventSlug": "fwc-esp-arg-2026-07-19"
  },
  "cashValue": {
    "value": "48.0649",
    "currency": "USD"
  },
  "avgPx": {
    "value": "0.4300",
    "currency": "USD"
  }
}
```

## Interpretation:

### What Bear Did:
- **Sold 116 contracts** of "Argentina to advance"
- **Average price:** 43¢ (0.43 USD)
- **Total received:** ~$50 (116 × 0.43)
- **Current value:** $48.06
- **Unrealized P&L:** -$1.93

### What This Means:

#### If "Argentina to advance" is a YES/NO market:
- **YES** = Argentina advances (beats Spain)
- **NO** = Argentina doesn't advance (Spain wins)

Bear **sold** "Argentina" contracts at 43¢.

This could mean either:
1. **He sold YES shares** → Betting AGAINST Argentina (SHORT)
2. **He sold NO shares** → Betting FOR Argentina (LONG)

### The Confusion:
On Polymarket, when you **sell YES shares**, you're effectively buying NO (betting against the outcome).

But the API shows:
- `outcome: "Argentina"` 
- `qtySold: 116`

Does this mean:
- He sold 116 YES shares on "Argentina" (betting Spain wins)?
- Or he sold 116 NO shares (betting Argentina wins)?

### Most Likely Scenario:
Given typical Polymarket behavior:
- **qtySold > 0** = You sold YES shares
- **Outcome: "Argentina"** = The specific team/outcome
- **Average price: 0.43** = He sold when Argentina was trading at 43¢

**Conclusion:** Bear is **SHORT Argentina** (betting Spain wins).

If Argentina advances: He loses $50  
If Spain advances: He keeps his $50

### Current Odds Imply:
- Argentina currently trading at ~41¢ (based on $48.06 / 116)
- Market thinks Argentina has ~41% chance to advance
- Bear sold at 43¢, now 41¢ → small paper loss

## Action Items:

1. **Verify with Bear:** Did you bet FOR or AGAINST Argentina?
2. **Check market structure:** Is this "Argentina to advance" or "Spain to advance"?
3. **Fix `get_positions.py`** to correctly label based on:
   - If netPosition < 0 and outcome = X, you're SHORT on X
   - Add a note explaining what SHORT means in this context

## Fixed Labeling:
```python
# Current (wrong):
print(f"Side: {'LONG' if net_pos > 0 else 'SHORT'}")

# Should be:
if net_pos > 0:
    print(f"Position: LONG {outcome} (you win if {outcome} occurs)")
else:
    print(f"Position: SHORT {outcome} (you win if {outcome} does NOT occur)")
```
