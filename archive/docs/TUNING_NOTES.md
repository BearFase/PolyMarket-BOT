# Parameter Tuning - 2026-07-16

## Problem
Original parameters were too strict for current market activity:
- Only 2 of 21 top whales active in 72h
- Requiring 3-whale consensus = zero signals
- Missing legitimate opportunities (e.g., $81k Hantavirus position)

## New Parameters

### Cron Schedule
- **Before:** Every 6 hours (too frequent)
- **After:** 2x daily at 8am + 8pm PDT
- **Reasoning:** Whale activity is slow; morning + evening checks capture opportunities without spam

### Whale Consensus
- **min_whale_overlap:** 3 → **2**
  - Market too quiet for 3-whale consensus
  - 2 whales with conviction beats waiting forever

- **min_whale_position_size:** NEW - **$50,000**
  - Filters out noise/testing positions
  - Only tracks real conviction bets

- **min_edge:** 5% → **10%**
  - Higher bar for entry vs whale average
  - Protects against chasing positions

- **time_window_hours:** 24-72h → **168h (7 days)**
  - Wider window catches more signals in quiet markets
  - Still focuses on recent activity, not ancient history

### Trade Sizing (unchanged)
- **max_position_size:** $100
- **max_total_exposure:** $500
- **auto_trade:** false (still manual approval)

## Expected Outcomes
- **Before:** 0 signals, market too strict
- **After:** 1-2 high-quality signals per week
- **Goal:** Simple 2-min check 2x/day, find weekly opportunities

## Reality Check for School
- **NOT** 1-2 trades per day (too ambitious for whale consensus alone)
- **Realistic:** 1-2 trades per week from whale signals
- **Time commitment:** <5 min/day checking dashboard
- **Compatible with 3.8 GPA:** Yes, if kept simple

## Next Steps
1. ✅ Update paper_config.json with new parameters
2. ✅ Update cron jobs to 2x/day (8am, 8pm)
3. ⏳ Monitor for 1 week to validate signal quality
4. ⏳ Consider adding single-whale alerts for positions >$100k (different notification tier)

## Code Changes Needed
- [ ] Update `auto_trader.py` to respect `min_whale_position_size` filter
- [ ] Update `check_whale_positions.py` to use 7-day window by default
- [ ] Update dashboard to show "Last 7 days" in whale tab header
