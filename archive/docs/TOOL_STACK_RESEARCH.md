# Tool Stack Research - 2026-07-18

## Executive Summary

Current stack (all free-tier) has gotten us to +$27.25 in real money, but it's **sloppy, manual, and unreliable**. We need:
1. Real-time data (not 14h stale)
2. Automated alerts (no manual checks)
3. Proper position tracking (paper vs real, zero confusion)
4. Professional infrastructure (database, not JSON files)

**Philosophy:** Start with free where it's good enough, pay where it matters.

---

## Category 1: Polymarket Data & Trading

### Current: Manual HTTP requests to public API
**Problems:**
- No real-time updates
- Manual polling wastes API calls
- No authentication for private data
- Can't place trades programmatically

### Options:

#### 🥇 **RECOMMENDED: py-clob-client (Official Python SDK)**
- **Cost:** FREE (MIT license)
- **Pros:**
  - Official Polymarket Python client
  - Trading support (place/cancel/modify orders)
  - Wallet signing built-in
  - Order book access
  - Position tracking
- **Cons:**
  - Requires API key (free but needs approval)
  - Learning curve for order signing
- **Use for:** Trading automation, position management
- **Setup:** `pip install py-clob-client`
- **Docs:** https://github.com/Polymarket/py-clob-client

#### 🥈 **Polymarket WebSocket (RTDS)**
- **Cost:** FREE
- **Endpoint:** `wss://ws-live-data.polymarket.com`
- **Pros:**
  - Real-time price updates
  - No polling needed
  - Crypto price feed
  - Comments stream
- **Cons:**
  - Requires `PING` every 5s to keep alive
  - TypeScript client more mature than Python
  - User-specific data needs `gamma_auth`
- **Use for:** Real-time price monitoring, alerts
- **Client:** https://github.com/Polymarket/real-time-data-client (TypeScript)

#### 💰 **Polifly.io (Premium Data Service)**
- **Cost:** $1 first week, then ~$20-50/mo (estimate based on site)
- **Pros:**
  - Custom dashboards
  - Advanced analytics
  - Pre-built visualizations
  - Historical data
- **Cons:**
  - Monthly cost
  - Less control than DIY
  - Vendor lock-in
- **Use for:** If you want turnkey analytics without coding
- **Skip for now:** We can build what we need cheaper

#### 📊 **The Graph (Historical On-Chain Data)**
- **Cost:** FREE for queries, paid for indexing (not needed)
- **Endpoint:** Polymarket subgraph via GraphQL
- **Pros:**
  - Historical trades
  - On-chain settlement data
  - Backtesting data source
- **Cons:**
  - Complex GraphQL queries
  - Overkill for current needs
- **Use for:** Later, if we want historical backtesting

---

## Category 2: Alerts & Notifications

### Current: Terminal output, no alerts
**Problems:**
- Miss opportunities while sleeping/at school
- No mobile notifications
- Manual dashboard checking

### Options:

#### 🥇 **RECOMMENDED: python-telegram-bot**
- **Cost:** FREE (Telegram API is free)
- **Pros:**
  - Native Telegram integration
  - Rich message formatting (buttons, inline keyboards)
  - File/image sending
  - Bidirectional (send commands back)
  - Mature library (14k+ GitHub stars)
- **Cons:**
  - Requires bot token from BotFather
  - Need to learn API
- **Use for:** Morning reports, trade alerts, position updates
- **Setup:** `pip install python-telegram-bot`
- **Docs:** https://python-telegram-bot.org/
- **Example use:**
  ```python
  import asyncio
  from telegram import Bot
  
  async def send_alert(message):
      bot = Bot(token="YOUR_BOT_TOKEN")
      await bot.send_message(chat_id=YOUR_CHAT_ID, text=message)
  
  asyncio.run(send_alert("🚨 New edge found: Argentina +8.3%"))
  ```

#### 🥈 **Twilio (SMS Alerts)**
- **Cost:** ~$1/mo for phone number + $0.0075 per SMS
- **Pros:**
  - True SMS (works when Telegram down)
  - No app required
  - Reliable delivery
- **Cons:**
  - Costs money per message
  - Character limits
  - No rich formatting
- **Use for:** Critical alerts only (e.g., position at risk)
- **Skip for now:** Telegram is free and better

#### 💰 **PagerDuty / Opsgenie (Professional Alerting)**
- **Cost:** $19-39/user/month
- **Pros:**
  - Enterprise-grade alerting
  - Escalation policies
  - On-call scheduling
  - Incident management
- **Cons:**
  - Way overkill for solo trading
  - Expensive
- **Use for:** Never (unless you have a team)

---

## Category 3: Database & Storage

### Current: JSON files (paper_state.json, etc.)
**Problems:**
- No concurrent access safety
- Manual schema management
- Hard to query/analyze
- Doesn't scale

### Options:

#### 🥇 **RECOMMENDED: PostgreSQL + SQLAlchemy**
- **Cost:** FREE (open source)
- **Pros:**
  - Industry standard
  - ACID compliance
  - Great Python support (SQLAlchemy ORM)
  - JSON column support (best of both worlds)
  - Easy local dev, scales to cloud
- **Cons:**
  - More complex than JSON files
  - Need to manage migrations
- **Use for:** Positions, trades, whale data, edges
- **Setup:** `pip install psycopg2-binary sqlalchemy`
- **Schema example:**
  ```sql
  CREATE TABLE positions (
      id SERIAL PRIMARY KEY,
      position_id VARCHAR(50) UNIQUE,
      market TEXT,
      outcome VARCHAR(10),
      entry_price DECIMAL(10,4),
      size DECIMAL(10,2),
      pnl DECIMAL(10,2),
      position_type VARCHAR(10), -- 'paper' or 'real'
      opened_at TIMESTAMP,
      closed_at TIMESTAMP,
      notes TEXT
  );
  ```

#### 💰 **TimescaleDB (Time-Series PostgreSQL Extension)**
- **Cost:** FREE self-hosted, $50-500/mo for cloud
- **Pros:**
  - Built on PostgreSQL (same tools)
  - Optimized for time-series (price data)
  - Continuous aggregates (automatic rollups)
  - Better performance for historical queries
- **Cons:**
  - Extra complexity
  - Overkill for current scale
- **Use for:** Later, if we store tick-by-tick prices
- **Cloud:** Timescale Cloud has free tier (30 days)

#### 🥈 **SQLite (Keep It Simple)**
- **Cost:** FREE (built into Python)
- **Pros:**
  - Zero setup
  - Single file
  - Good enough for current scale
  - Easy backups (copy file)
- **Cons:**
  - No concurrent writes (not an issue for solo bot)
  - Doesn't scale to high load
- **Use for:** Good bridge between JSON and Postgres
- **Decision:** Start here, migrate to Postgres later

---

## Category 4: Dashboard & Analytics

### Current: Terminal status.py + HTML dashboard
**Problems:**
- Static HTML (manual refresh)
- No historical charts
- No advanced analytics

### Options:

#### 🥇 **RECOMMENDED: Grafana + PostgreSQL**
- **Cost:** FREE (open source)
- **Pros:**
  - Professional dashboards
  - Real-time updates
  - Beautiful charts
  - Mobile-friendly
  - Template library
  - Alerting built-in
- **Cons:**
  - Requires database (Postgres)
  - Learning curve for queries
  - Overkill for MVP
- **Use for:** Phase 2 (after Postgres migration)
- **Setup:** Docker container easiest
- **Cloud:** Grafana Cloud free tier (10k series, 50GB logs)

#### 🥈 **Metabase (Business Intelligence)**
- **Cost:** FREE (open source)
- **Pros:**
  - User-friendly query builder
  - No SQL needed for basic queries
  - Clean interface
  - Scheduled reports
- **Cons:**
  - Less flexible than Grafana
  - Not built for real-time
- **Use for:** Weekly/monthly analysis, not live trading

#### 🥉 **Custom HTML + Chart.js (Current Approach)**
- **Cost:** FREE
- **Pros:**
  - Full control
  - No external dependencies
  - Works offline
- **Cons:**
  - Manual maintenance
  - Limited features
  - Reinventing the wheel
- **Decision:** Good for now, upgrade to Grafana later

---

## Category 5: Automation & Scheduling

### Current: OpenClaw cron jobs (2x daily)
**Problems:**
- Tied to OpenClaw uptime
- No distributed execution
- Manual cron management

### Options:

#### 🥇 **KEEP: OpenClaw Cron**
- **Cost:** FREE (built-in)
- **Pros:**
  - Already working
  - Telegram integration
  - Zero external dependencies
- **Cons:**
  - Single point of failure (your PC)
- **Use for:** Morning checks (8am), alerts
- **Keep using:** It works, don't over-engineer

#### 🥈 **GitHub Actions (Cloud CI/CD)**
- **Cost:** FREE (2000 min/month for private repos)
- **Pros:**
  - Cloud-based (runs even if PC off)
  - Version controlled
  - Can run on PRs for testing
- **Cons:**
  - Need to store secrets in GitHub
  - Cold start times
  - Not designed for trading (better for builds)
- **Use for:** Backup checks, historical analysis
- **Setup:** `.github/workflows/morning-check.yml`

#### 💰 **Render / Railway / Fly.io (PaaS)**
- **Cost:** $5-10/mo for always-on instance
- **Pros:**
  - Always running (cloud VM)
  - Persistent storage
  - Easy deploys
  - Better than local PC for reliability
- **Cons:**
  - Monthly cost
  - Need to manage deployments
- **Use for:** Phase 3 (if you want 24/7 automation)

---

## Category 6: Trading Execution

### Current: Manual (you place trades on Polymarket app)
**Problems:**
- Slow execution (minutes, not seconds)
- Can't trade while sleeping
- Human error risk

### Options:

#### 🥇 **RECOMMENDED: py-clob-client (Hybrid Mode)**
- **Cost:** FREE
- **Approach:** Bot finds signals → Telegram alert → You reply "execute" → Bot places trade
- **Pros:**
  - Human oversight
  - Fast execution once approved
  - Full automation possible later
- **Cons:**
  - Requires API key
  - Wallet private key in code (security risk)
- **Implementation:**
  ```python
  from py_clob_client.client import ClobClient
  
  client = ClobClient(host="https://clob.polymarket.com", key="YOUR_KEY")
  
  # Place order
  order = client.create_order(
      token_id="...",
      price=0.45,
      size=100,
      side="BUY"
  )
  ```

#### 🥈 **Keep Manual (Current)**
- **Cost:** FREE
- **Pros:**
  - Zero risk of automation failure
  - Full control
  - No API keys needed
- **Cons:**
  - Slow
  - Can't scale
- **Use for:** Now, while learning

---

## RECOMMENDED STACK (Phased Approach)

### Phase 1: Fix the Sloppiness (THIS WEEK)
**Goal:** Stop being sloppy with $0 extra cost

1. **Data Source:** 
   - Keep current HTTP requests to Gamma API
   - Add py-clob-client for wallet checking
   
2. **Storage:** 
   - Migrate from JSON to **SQLite**
   - Separate `paper_positions` and `real_positions` tables
   
3. **Alerts:** 
   - Add **python-telegram-bot** for morning reports
   - 8am automated message with edges + positions
   
4. **Dashboard:** 
   - Keep HTML dashboard (it's actually good)
   - Add auto-generated daily reports
   
5. **Execution:** 
   - Keep manual for now
   - Document every trade in SQLite

**Cost:** $0  
**Time:** 1-2 days to implement

---

### Phase 2: Real-Time & Automation (AFTER 2 WEEKS)
**Goal:** Real-time monitoring + semi-automated trading

1. **Data Source:** 
   - Add **WebSocket (RTDS)** for real-time prices
   - Keep API for historical/reference data
   
2. **Storage:** 
   - Migrate SQLite → **PostgreSQL**
   - Add price history table
   
3. **Alerts:** 
   - Add price movement alerts (e.g., Argentina drops >5%)
   - Position P&L updates (hourly during finals, 2x daily normally)
   
4. **Dashboard:** 
   - Add **Grafana** with Postgres data source
   - Historical charts, performance analytics
   
5. **Execution:** 
   - Implement **hybrid mode** (alert → approve → execute)
   - py-clob-client integration

**Cost:** $0 (everything is free/open source)  
**Time:** 2-3 days to implement

---

### Phase 3: Production-Ready (AFTER 1 MONTH)
**Goal:** 24/7 cloud operation, full automation

1. **Hosting:** 
   - Move to **Render/Railway** ($7/mo)
   - Always-on monitoring
   
2. **Database:** 
   - Keep Postgres, consider **TimescaleDB** for price data
   
3. **Monitoring:** 
   - Add uptime checks
   - Error alerting via Telegram
   
4. **Execution:** 
   - Optional: Full automation with risk limits
   - Emergency kill switch via Telegram

**Cost:** ~$10/mo  
**Time:** 1 week to implement + test

---

## Budget Summary

### Phase 1 (Now)
- **Total:** $0/month
- All free/open source

### Phase 2 (Week 3-4)
- **Total:** $0/month
- Still all free

### Phase 3 (Month 2+)
- **Hosting:** $7/month (Render/Railway)
- **Optional Twilio:** $1/month (critical SMS alerts)
- **Total:** ~$10/month

### Optional Premium (If Scaling)
- **TimescaleDB Cloud:** $50/month (if high-frequency data)
- **Grafana Cloud Pro:** $49/month (better dashboards)
- **Polifly.io:** $50/month (if you hate building)
- **Total:** $150/month (only if managing >$10k portfolio)

---

## Action Items for Bear

1. **Approve Phase 1 plan** - migrate JSON to SQLite, add Telegram bot
2. **Get Telegram bot token** - message @BotFather on Telegram
3. **Test py-clob-client** - verify your wallet is recognized
4. **Review PostgreSQL option** - OK with Docker? Or stick with SQLite longer?

---

## Tools to Install (Phase 1)

```bash
# Python packages
pip install python-telegram-bot
pip install py-clob-client
pip install sqlalchemy

# For Windows SQLite (already included in Python)
# No additional installs needed
```

---

## References

- py-clob-client: https://github.com/Polymarket/py-clob-client
- python-telegram-bot: https://python-telegram-bot.org/
- Polymarket RTDS: https://docs.polymarket.com/market-data/websocket/rtds
- Polymarket API Guide: https://polifly.io/blog/polymarket-api-guide-developers
- Grafana: https://grafana.com/
- TimescaleDB: https://www.timescale.com/

---

**Bottom Line:**

We can fix 90% of the sloppiness with **$0 investment** by:
1. SQLite database (stop using JSON)
2. Telegram alerts (automated morning reports)
3. Proper position tracking (paper vs real separation)

Then upgrade to Postgres + Grafana + WebSocket when we're consistently profitable and managing >$1000.

Pay for cloud hosting (~$10/mo) only when we want 24/7 operation.

**Don't pay for premium services until we're making >$500/month in profit.**
