# 🎯 Polymarket Command Center

ESPN-style dashboard for tracking your Polymarket bets, whale signals, and live games.

## Quick Start

### 1. Launch Dashboard

**Windows:**
```cmd
cd dashboard
START_DASHBOARD.cmd
```

**Mac/Linux:**
```bash
cd dashboard
python serve.py
```

Dashboard will open at: **http://localhost:8080**

### 2. Add Your Wallet (Optional)

To track your REAL positions instead of demo data:

```bash
python serve.py --wallet 0xYourPolymarketWalletAddress
```

**Where to find your wallet:**
1. Go to Polymarket.com
2. Click your profile
3. Copy your wallet address (starts with `0x`)

## Features

### 🔴 Live Game Tab
- Your current active bet front and center
- Real-time P&L tracking
- Live odds for all outcomes
- Quick link to Polymarket

### 📊 Portfolio Tab
- All your open positions
- Entry price vs current price
- Unrealized P&L
- Sort by biggest winners/losers

### 🐋 Whale Signals Tab
- Live whale consensus alerts
- Shows when 2+ top traders agree on a market
- Edge calculation (your price vs whale average)
- One-click to view/trade

### 🔍 Markets Tab
- Trending high-volume markets
- Quick access to hot bets
- Volume and current odds

## Configuration

Edit `api.py` to customize:

```python
# Line 20: Set your default wallet
USER_WALLET = "0xYourAddressHere"

# Whale tracking settings (line 180)
run_consensus_check(
    hours=72,      # Look back 3 days
    pool=20,       # Check top 20 whales
    min_overlap=2  # Need 2+ whales agreeing
)
```

## Auto-Refresh

Dashboard updates every **30 seconds** automatically. No need to refresh!

## Troubleshooting

**"No positions showing"**
- Make sure you added your wallet address
- Check that you have open positions on Polymarket
- API might be slow - wait 30s for refresh

**"No whale signals"**
- Normal! Real consensus is rare
- Try running during major events (elections, World Cup)
- Lower `min_overlap` to 2 in api.py line 180

**"Dashboard won't load"**
- Check console for errors
- Make sure port 8080 isn't in use
- Try: `python serve.py --port 9000`

## What's Next

### Track Specific Games
Edit `get_live_game()` in `api.py` to prioritize specific markets:

```python
# Prioritize games ending soon
for p in positions:
    if p['current_price'] < 0.95:  # Still live
        return p
```

### Add Notifications
When whale consensus emerges, send yourself an alert:

```python
# In get_whale_signals()
if signals and len(signals) > 0:
    # TODO: Send Telegram/Discord message
    pass
```

### Paper Trading Integration
Link to the paper trader to simulate positions:

```python
# Show paper vs real positions side-by-side
```

## Files

- `index.html` - Dashboard UI
- `serve.py` - Combined web + API server
- `api.py` - Backend data fetching
- `START_DASHBOARD.cmd` - Windows launcher

---

**Enjoy the command center!** 🚀
