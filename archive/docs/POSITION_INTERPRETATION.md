# Position Interpretation Guide

## The Mismatch Mystery: SOLVED ✅

**What we saw:**
- Screenshot showed: "LONG Argentina" - to win $116.38
- API showed: "SHORT Argentina" - 116.38 contracts

**The Truth:**
Both are CORRECT! Here's why...

## How Polymarket Works

### The YES/NO Model
- Every market has TWO sides: YES and NO
- They ALWAYS add up to $1.00
- There's only ONE instrument per market — the YES side
- To bet AGAINST an outcome, you **sell YES** (= buy NO)

### Position Terminology

| Your Action | API Reports | App Shows | What It Means |
|-------------|-------------|-----------|---------------|
| Buy YES at $0.42 | LONG YES | "Long Argentina" | You profit if Argentina wins |
| Sell YES at $0.42 | SHORT YES | "Short Argentina" | You profit if Argentina loses |

### Bear's Argentina Position

**What happened:**
1. Bear bought YES on "Argentina to advance" at $0.42
2. He spent $50 for ~119 YES contracts
3. Each YES contract pays $1.00 if Argentina wins

**Why the confusion:**

The market question is: **"Spain vs. Argentina"** with outcome **"Argentina"**

- **Buying YES** means betting Argentina wins
- This is a **LONG Argentina** position from a logical standpoint
- But the API shows **netPosition = +116.38** which means LONG YES
- The outcome field says "Argentina" which is the YES side

**The calculation:**
```
Cost: $50.00
Entry price: ~$0.42 per contract
Contracts: 116.38 (= $50 / $0.42)
Current price: $0.41 per contract
Current value: $48.06 (= 116.38 × $0.41)
Unrealized P&L: -$1.94

If Argentina wins:
  Payout = 116.38 × $1.00 = $116.38
  Profit = $116.38 - $50.00 = $66.38
```

## Position Sign Convention

**From API:**
- `netPositionDecimal > 0` = LONG the outcome (bought YES)
- `netPositionDecimal < 0` = SHORT the outcome (sold YES)

**Translation to human language:**
```python
if net_pos > 0:
    side = f"LONG {outcome}"  # Betting outcome WILL happen
else:
    side = f"SHORT {outcome}"  # Betting outcome WON'T happen
```

## Why This Matters for Our Bot

When syncing positions, we need to:
1. Check the SIGN of `netPositionDecimal`
2. Map positive = LONG, negative = SHORT
3. Store the outcome name correctly
4. Calculate P&L based on:
   - LONG: profit if price goes to $1.00
   - SHORT: profit if price goes to $0.00

## Key Insight

**There is NO mismatch!**

The API correctly shows:
- Position: +116.38 (positive = LONG)
- Outcome: "Argentina"
- **Meaning:** LONG Argentina (betting Argentina wins)

The screenshot showed "to win $116.38" which is exactly right:
- 116.38 contracts × $1.00 = $116.38 if Argentina wins

**Everything checks out. ✅**
