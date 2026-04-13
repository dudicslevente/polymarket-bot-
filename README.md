# Polymarket BTC 15-Minute Trading Bot

A **production-ready** Python trading bot for Polymarket BTC 15-minute Up/Down prediction markets.

---

## 📑 Table of Contents

1. [What This Bot Does](#-what-this-bot-does)
2. [Quick Start (5 Minutes)](#-quick-start-5-minutes)
3. [How the Strategy Works](#-how-the-strategy-works)
4. [Running Modes Explained](#-running-modes-explained)
5. [Step-by-Step: Going Live](#-step-by-step-going-live)
   - [CLOB Setup & Wallet Funding](#step-5-fund-your-wallet--set-up-clob-trading)
6. [🛡️ Safe Live Trading Tutorial](#️-safe-live-trading-tutorial)
7. [Configuration Reference](#-configuration-reference)
8. [Understanding the Code](#-understanding-the-code)
9. [Safety Features](#-safety-features)
10. [💰 Live Deployment: Automatic Redemption System](#-live-deployment-automatic-redemption-system)
11. [Troubleshooting](#-troubleshooting)
12. [FAQ](#-faq)

---

## 🎯 What This Bot Does

This bot automatically trades on Polymarket's BTC 15-minute prediction markets:

```
"Will BTC go UP or DOWN in the next 15 minutes?"
```

**How it works:**
1. 📊 Monitors real-time BTC price from Binance
2. 📈 Detects if BTC is trending UP or DOWN
3. 🎲 Compares market odds to estimated fair probability
4. 💰 Places a bet if there's a profitable edge
5. ⏰ Waits for 15-minute market to resolve
6. 📝 Logs the result and updates balance

**Key Features:**
- ✅ Fully automated trading
- ✅ Conservative bet sizing (3% per trade)
- ✅ Daily loss limits for protection
- ✅ Works in TEST mode (paper trading) or LIVE mode
- ✅ Detailed trade logging to CSV

---

## 🚀 Quick Start (5 Minutes)

### Step 1: Install

```bash
# Clone the repository
git clone <your-repo-url>
cd polymarket-bot

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure

```bash
# Copy example config
cp .env.example .env

# For TEST mode, no changes needed!
# The default .env.example has TEST_MODE=true
```

### Step 3: Run

```bash
# Run in test mode (paper trading)
python main.py

# Or run simulation (faster, for quick testing)
python main.py --simulate
```

**That's it!** The bot will start scanning for markets and making simulated trades.

---

## 🧠 How the Strategy Works

### The Trading Logic (Step-by-Step)

```
┌─────────────────────────────────────────────────────────────┐
│  1. GET BTC PRICE                                           │
│     └─> Fetch current BTC price from Binance                │
│                                                             │
│  2. DETECT BIAS                                             │
│     └─> Compare price now vs 3 minutes ago                  │
│     └─> If BTC moved ≥0.10% → We have a bias (UP or DOWN)   │
│     └─> If BTC moved <0.10% → No trade (sideways market)    │
│                                                             │
│  3. ESTIMATE FAIR PROBABILITY                               │
│     └─> Mild bias (0.10-0.20%): 52% chance of continuing    │
│     └─> Strong bias (>0.20%): 55% chance of continuing      │
│                                                             │
│  4. CALCULATE EDGE                                          │
│     └─> Edge = Fair Probability - Market Odds               │
│     └─> Example: 55% fair - 50% market = 5% edge            │
│     └─> Only trade if edge > 2% (after fees)                │
│                                                             │
│  5. PLACE BET                                               │
│     └─> Bet 3% of current balance                           │
│     └─> Maximum $10 per trade                               │
│                                                             │
│  6. WAIT FOR RESOLUTION                                     │
│     └─> Market resolves after 15 minutes                    │
│     └─> WIN: Get ~2x your bet back                          │
│     └─> LOSS: Lose your bet                                 │
└─────────────────────────────────────────────────────────────┘
```

### Example Trade

```
BTC Price 3 min ago:  $50,000
BTC Price now:        $50,150  (+0.30% = STRONG UP bias)

Market odds for UP:   48% (meaning payout is ~2.08x)
Our fair estimate:    55% (strong bias = 55% continuation)
Edge:                 55% - 48% = 7% edge ✅

Decision: BET on UP
Bet size: $3.00 (3% of $100 balance)

If WIN:  Get $6.25 back (profit: $3.25)
If LOSS: Lose $3.00
```

### Why This Strategy?

| Principle | Explanation |
|-----------|-------------|
| **Small edge, many trades** | 2-5% edge per trade, compounded over many trades |
| **Momentum continuation** | BTC trends tend to continue short-term |
| **Conservative sizing** | 3% bets survive 10+ loss streaks |
| **No prediction wizardry** | We don't predict BTC, just follow momentum |

---

## 🎮 Running Modes Explained

### TEST Mode (Default) 🧪

**What it does:**
- Uses virtual balance ($100 default)
- Simulates trade execution (instant fill)
- Simulates win/loss based on probability
- Logs trades to `trades.csv`
- **NO real money involved**

**When to use:**
- First time running the bot
- Testing configuration changes
- Understanding how the bot works

```bash
# Run in test mode
python main.py
```

### Simulation Mode 🎯

**What it does:**
- Same as TEST mode but faster
- Creates fake markets every few seconds
- Good for quick strategy testing
- Runs through many trades quickly

```bash
# Run simulation
python main.py --simulate
```

### LIVE Mode 💰

**What it does:**
- Uses real USDC from your wallet
- Places real orders on Polymarket
- Real wins/losses affect your balance
- **REAL MONEY AT RISK**

**Requirements:**
- Polymarket account with API credentials
- Wallet with USDC on Polygon network
- Wallet private key for signing orders

```bash
# Run live (after configuration)
python main.py --live
```

### Analyze Mode 📊

**What it does:**
- Analyzes your trade history from `trades.csv`
- Shows win rate, profit/loss, statistics
- Generates performance charts

```bash
# Analyze trades
python main.py --analyze
```

---

## 🔑 Step-by-Step: Going Live

> ⚠️ **WARNING**: Live trading involves real money. Only proceed if you understand the risks and have tested thoroughly in TEST mode.

### Prerequisites Checklist

- [ ] Ran bot in TEST mode for at least a few hours
- [ ] Understand how the strategy works
- [ ] Have a Polymarket account
- [ ] Have a wallet (MetaMask) connected to Polymarket
- [ ] Wallet has USDC on Polygon network
- [ ] Wallet has small amount of MATIC for gas

### Step 1: Get Polymarket API Credentials

1. Go to [polymarket.com](https://polymarket.com) and log in
2. Click on your profile → **Settings**
3. Navigate to **API** section
4. Click **Create API Key**
5. Save these three values:
   - `API Key` (looks like: `abc123...`)
   - `API Secret` (looks like: `base64encodedstring==`)
   - `Passphrase` (you created this)

### Step 2: Get Your Wallet Private Key

> ⚠️ **NEVER share your private key with anyone!**

**From MetaMask:**
1. Open MetaMask
2. Click the three dots menu → **Account Details**
3. Click **Show Private Key**
4. Enter your password
5. Copy the private key (starts with `0x`)

**Also get your wallet address:**
- It's shown at the top of MetaMask (starts with `0x`)
- Click to copy it

### Step 3: Configure .env File

Edit your `.env` file with these values:

```bash
# ═══════════════════════════════════════════════════════
# LIVE TRADING CONFIGURATION
# ═══════════════════════════════════════════════════════

# Switch to live mode
TEST_MODE=false

# Your Polymarket API credentials (from Step 1)
POLYMARKET_API_KEY=your_api_key_here
POLYMARKET_API_SECRET=your_api_secret_here
POLYMARKET_PASSPHRASE=your_passphrase_here

# Your wallet credentials (from Step 2)
WALLET_ADDRESS=0xYourWalletAddressHere
WALLET_PRIVATE_KEY=0xYourPrivateKeyHere

# ═══════════════════════════════════════════════════════
# RECOMMENDED SAFETY SETTINGS FOR FIRST TIME
# ═══════════════════════════════════════════════════════

# Start with small bets
MAX_BET_SIZE_USD=5.0

# Tight daily loss limit (10%)
DAILY_LOSS_LIMIT_PERCENT=0.10

# Pause after 5 consecutive losses
MAX_CONSECUTIVE_LOSSES=5

# Maximum 20 trades per day initially
MAX_TRADES_PER_DAY=20
```

### Step 4: Verify Your Setup

Run the authentication test:

```bash
python test_auth.py
```

Expected output:
```
✅ TEST_MODE tests passed!
✅ No-credentials tests passed!
✅ With-credentials tests passed!
✅ Signature consistency tests passed!
🎉 ALL TESTS PASSED!
```

### Step 5: Fund Your Wallet & Set Up CLOB Trading

> ⚠️ **IMPORTANT**: The Polymarket CLOB API trades directly from your wallet, NOT from your Polymarket website balance. These are separate systems!

#### Understanding Polymarket's Two Systems

| System | Description | Used By |
|--------|-------------|---------|
| **Website (Proxy Wallet)** | Polymarket holds funds for you | Website trading |
| **CLOB API (Your Wallet)** | Funds stay in YOUR wallet | This bot |

#### What You Need in Your Wallet

| Token | Amount | Purpose |
|-------|--------|---------|
| **USDC.e** | $20-50+ | Trading capital |
| **POL** | 0.5+ POL | Gas fees (~$0.01-0.05 per trade) |

> **⚠️ CRITICAL**: You must have **USDC.e** (contract: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`), NOT regular USDC! Polymarket only accepts USDC.e.

#### How to Get USDC.e

**Option 1: Withdraw from Polymarket Website (Easiest)**
1. Go to https://polymarket.com
2. Click **Portfolio** → **Wallet** → **Withdraw**
3. Withdraw to your wallet address
4. This automatically gives you USDC.e

**Option 2: Swap on DEX**
- If you have regular USDC on Polygon, swap it to USDC.e on [Uniswap](https://app.uniswap.org) or [QuickSwap](https://quickswap.exchange)

**Option 3: Bridge from Ethereum**
- Use the [Polygon Bridge](https://wallet.polygon.technology/) to bridge USDC from Ethereum (becomes USDC.e)

#### Set Up CLOB Trading Allowances

Before the bot can trade, you must approve Polymarket's contracts to access your USDC.e:

```bash
# Check your current status
python setup_clob_trading.py status

# Set up allowances (one-time setup, requires POL for gas)
python setup_clob_trading.py approve
```

Expected output after successful setup:
```
============================================================
CLOB STATUS CHECK
============================================================

Wallet: 0xYourWalletAddress

CLOB Balance: $XX.XX USDC

Allowances:
  CTF Exchange: ✅ Approved
  Neg Risk CTF Exchange: ✅ Approved
  Neg Risk Adapter: ✅ Approved

✅ Ready to trade!
```

#### Gas Fees (POL)

Every trade requires a small amount of POL for gas:

| Action | Approx Cost |
|--------|-------------|
| Place order | $0.01-0.05 |
| Cancel order | $0.005-0.02 |
| Claim winnings | $0.01-0.05 |

With **0.5 POL**, you can make **hundreds of trades**. Polygon gas is very cheap!

### Step 6: Start Live Trading

```bash
python main.py
```

The bot will:
1. Connect to Polymarket
2. Verify your credentials
3. Check your balance
4. Start scanning for markets
5. Place trades when opportunities arise

### Step 7: Monitor Your Trades

- Watch the console output for trade activity
- Check `trades.csv` for trade history
- Run `python main.py --analyze` for statistics

---

## 🛡️ Safe Live Trading Tutorial

> **This section is your complete guide to running the bot with real money safely.**
> Follow each step carefully. Skipping steps could result in financial losses.

### Phase 1: Preparation (Before You Risk Any Money)

#### 1.1 Run TEST Mode for at Least 24 Hours

Before touching real money, you MUST run the bot in TEST mode:

```bash
# Run in test mode (default)
python main.py --mode SIM
```

**What to observe:**
- ✅ Bot finds markets correctly
- ✅ Trades are being placed (check console)
- ✅ Win rate is reasonable (45-60%)
- ✅ No crashes or errors
- ✅ Balance increases over time (if strategy works)

**Minimum requirements before going live:**
| Metric | Target |
|--------|--------|
| Test duration | 24+ hours |
| Total trades | 20+ trades |
| Win rate | 45%+ |
| No crashes | ✅ |

#### 1.2 Analyze Your Test Results

```bash
python main.py --analyze
```

Review the output:
- **Win Rate**: Should be above 50% for profitability
- **Average Edge**: Should be positive (>0)
- **Max Drawdown**: Understand how much you could lose
- **Consecutive Losses**: Know the worst streak

#### 1.3 Set Your Risk Budget

**Ask yourself these questions:**

1. **How much can I AFFORD TO LOSE completely?**
   - This is your maximum deposit
   - Never deposit more than this
   
2. **How much am I comfortable losing per day?**
   - This becomes your `DAILY_LOSS_LIMIT_USD`
   
3. **How much per trade?**
   - Start with 2-5% of your total balance
   - Use `BET_SIZE_PERCENT` to set this

**Example Risk Budget:**
```
Total I can lose: $100
Daily loss limit: $20 (20% of total)
Per-trade size: $3-5 (3-5% of total)
```

---

### Phase 2: Configuration (Safety First)

#### 2.1 Create Your Safe Configuration

Edit your `.env` file with these **conservative** settings:

```bash
# ═══════════════════════════════════════════════════════
# SAFE LIVE TRADING CONFIGURATION
# Use these settings for your first week of live trading
# ═══════════════════════════════════════════════════════

# --- Mode: LIVE ---
TEST_MODE=false

# --- API Credentials (required) ---
POLYMARKET_API_KEY=your_key_here
POLYMARKET_API_SECRET=your_secret_here
POLYMARKET_PASSPHRASE=your_passphrase_here
POLYMARKET_WALLET_ADDRESS=0xYourAddress
POLYMARKET_PRIVATE_KEY=your_private_key

# --- CONSERVATIVE BET SIZING ---
# Start SMALL - you can always increase later
BET_SIZE_PERCENT=0.03          # 3% of balance per trade
MIN_BET_SIZE_USD=3.0           # Minimum $3 per trade (Polymarket requires 5 shares minimum!)
MAX_BET_SIZE_USD=5.0           # Maximum $5 per trade (KEEP LOW!)

# --- STRICT SAFETY LIMITS ---
DAILY_LOSS_LIMIT_PERCENT=0.15  # Stop if down 15% for the day
DAILY_LOSS_LIMIT_USD=15.0      # Or stop if down $15
MAX_CONSECUTIVE_LOSSES=4       # Pause after 4 losses in a row
MAX_TRADES_PER_DAY=25          # Max 25 trades per day
LOSS_LIMIT_COOLDOWN_SECONDS=1800  # 30 min cooldown after hitting limits

# --- CONSERVATIVE STRATEGY ---
MIN_EDGE=0.03                  # Only trade if 3%+ edge
TRADE_COOLDOWN_SECONDS=120     # Wait 2 min between trades

# --- KEEP RESERVE ---
MIN_BALANCE_TO_TRADE=10.0      # Always keep $10 in reserve
```

#### 2.2 Understand Each Safety Setting

| Setting | What It Does | Why It Matters |
|---------|--------------|----------------|
| `MAX_BET_SIZE_USD=5.0` | Caps each trade at $5 | Limits damage from any single bad trade |
| `DAILY_LOSS_LIMIT_PERCENT=0.15` | Stops trading if down 15% | Prevents catastrophic daily losses |
| `MAX_CONSECUTIVE_LOSSES=4` | Pauses after 4 losses | Stops the bleeding during losing streaks |
| `MIN_EDGE=0.03` | Only trades with 3%+ edge | Avoids marginal/risky trades |
| `TRADE_COOLDOWN_SECONDS=120` | Waits 2 min between trades | Prevents overtrading |
| `MIN_BALANCE_TO_TRADE=10.0` | Keeps $10 reserve | Ensures you never go to zero |

---

### Phase 3: First Live Trades (Baby Steps)

#### 3.1 Fund Your Account Minimally

**Start with $50-100 USDC maximum.**

Why so little?
- Your first live trades are learning experiences
- Mistakes happen - limit their cost
- You can always add more later

**How to fund:**
1. Send USDC to Polygon network (use a bridge if needed)
2. Deposit USDC into Polymarket
3. Verify balance shows in your account

#### 3.2 Verify Everything Works

Run the authentication test:
```bash
python test_auth.py
```

You should see:
```
✅ L1 Authentication: OK
✅ L2 Signing: OK
✅ Balance Check: OK
✅ Ready for trading!
```

If any check fails, DO NOT proceed. Fix the issue first.

#### 3.3 Your First Live Session

**When to start:**
- During active trading hours (avoid weekends initially)
- When you can monitor the bot
- When you have 30+ minutes to watch

**Start the bot:**
```bash
python main.py
```

**You will see a confirmation prompt:**
```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!! WARNING: LIVE TRADING MODE !!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

You are about to trade with REAL MONEY on Polymarket.
...

Type 'I UNDERSTAND THE RISKS' to continue:
```

**Type exactly:** `I UNDERSTAND THE RISKS`

#### 3.4 Monitor Your First 10 Trades

**Stay at your computer for the first 10 trades!**

Watch for:
- ✅ Orders are being placed
- ✅ Orders are being filled (not timing out)
- ✅ Resolutions are being detected (WIN/LOSS)
- ✅ Balance is updating correctly
- ❌ Any errors in the console

**If you see errors:**
1. Press `Ctrl+C` to stop the bot
2. Check the error message
3. Fix the issue before restarting

#### 3.5 Check Your Trades

After a few trades, check `trades.csv`:

```bash
tail -10 trades.csv
```

Verify:
- Trades are being logged
- Balance changes make sense
- Entry prices are reasonable

---

### Phase 4: Scaling Up (Only After Success)

#### 4.1 The 10-10-10 Rule

Only increase your risk after meeting ALL of these:

| Milestone | Requirement |
|-----------|-------------|
| 10 days | Run for 10 consecutive days |
| 10% profit | Be up at least 10% overall |
| 100 trades | Execute at least 100 trades |

#### 4.2 Gradual Increase

**Week 1:** 
- $5 max per trade
- $50-100 total balance

**Week 2-3 (if profitable):**
- $10 max per trade
- $100-200 total balance

**Month 2+ (if still profitable):**
- $20 max per trade
- $200-500 total balance

**Never increase more than 2x at once!**

#### 4.3 When to STOP and Reassess

**Stop immediately if:**
- ❌ Win rate drops below 45%
- ❌ You hit daily loss limit 3 days in a row
- ❌ You lose more than 30% of your balance
- ❌ The strategy stops making sense

**Action plan:**
1. Stop the bot
2. Analyze what changed
3. Go back to TEST mode
4. Only return to LIVE after fixing issues

---

### Phase 5: Ongoing Monitoring

#### 5.1 Daily Checklist

Every day, check:
- [ ] Bot is still running
- [ ] Today's P&L (should be within limits)
- [ ] Win rate for the day
- [ ] Any errors in logs

```bash
# Quick daily check
python main.py --analyze
```

#### 5.2 Weekly Review

Every week:
- [ ] Review overall performance
- [ ] Check if strategy is still profitable
- [ ] Verify balance matches expectations
- [ ] Consider adjusting bet sizes (up or down)

#### 5.3 Monthly Assessment

Every month:
- [ ] Full performance review
- [ ] Compare to expectations
- [ ] Decide: continue, pause, or stop
- [ ] Update configuration if needed

---

### Quick Reference: Emergency Commands

| Situation | Command |
|-----------|---------|
| Stop the bot immediately | `Ctrl+C` |
| Check recent trades | `tail -20 trades.csv` |
| Analyze performance | `python main.py --analyze` |
| Switch to TEST mode | Set `TEST_MODE=true` in `.env` |
| Check wallet balance | Log into Polymarket website |

---

### ⚠️ Golden Rules of Live Trading

1. **Start SMALL** - You can always add more money
2. **Monitor actively** - At least for the first week
3. **Set strict limits** - They exist to protect you
4. **Don't chase losses** - If limits hit, STOP
5. **Take profits** - Withdraw some gains periodically
6. **Stay humble** - Past performance ≠ future results
7. **Have an exit plan** - Know when to walk away

---

## ⚙️ Configuration Reference

All settings are in your `.env` file.

### Core Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `TEST_MODE` | `true` | `true` = paper trading, `false` = real money |
| `INITIAL_VIRTUAL_BALANCE` | `100.0` | Starting balance for test mode |
| `VERBOSE_LOGGING` | `true` | Show detailed console output |

### Bet Sizing

| Setting | Default | Description |
|---------|---------|-------------|
| `BET_SIZE_PERCENT` | `0.03` | Bet 3% of balance per trade |
| `MIN_BET_SIZE_USD` | `3.0` | Minimum bet size (**must be ≥$2.50 to meet Polymarket's 5 share minimum**) |
| `MAX_BET_SIZE_USD` | `10.0` | Maximum bet size |
| `MIN_BALANCE_TO_TRADE` | `10.0` | Stop trading below this balance |

> ⚠️ **Important:** Polymarket requires a **minimum of 5 shares per order**. At typical prices (~$0.50), this means a minimum bet of ~$2.50. The default `MIN_BET_SIZE_USD=3.0` ensures this requirement is met.

### Strategy Parameters

| Setting | Default | Description |
|---------|---------|-------------|
| `BTC_BIAS_THRESHOLD_PERCENT` | `0.10` | Min % move to detect bias |
| `BTC_LOOKBACK_MINUTES` | `3` | How far back to measure price change |
| `MIN_EDGE_THRESHOLD` | `0.02` | Minimum 2% edge required to trade |
| `MILD_BIAS_FAIR_PROB` | `0.52` | Fair probability for mild bias |
| `STRONG_BIAS_FAIR_PROB` | `0.55` | Fair probability for strong bias |

### Price Source for Edge Calculation

| Setting | Default | Description |
|---------|---------|-------------|
| `EDGE_PRICE_SOURCE` | `CLOB` | Which price source to use for edge calculation |

**Options for `EDGE_PRICE_SOURCE`:**

| Value | Source | Description |
|-------|--------|-------------|
| `CLOB` | Order Book | Real-time bid/ask prices from the CLOB API. Most accurate but requires more API calls. **Recommended for live trading.** |
| `GAMMA` | Gamma API | Cached market prices (`outcomePrices`). Faster with fewer API calls, but prices may be stale by several seconds. Good for testing or when hitting rate limits. |

**When to use each:**
- **Live Trading**: Use `CLOB` for accurate edge detection. Stale prices can lead to false signals.
- **Testing/Backtesting**: Use `GAMMA` to reduce API load and avoid rate limits.
- **Rate Limit Issues**: Switch to `GAMMA` if you're hitting API limits frequently.

### Safety Limits

| Setting | Default | Description |
|---------|---------|-------------|
| `DAILY_LOSS_LIMIT_PERCENT` | `0.20` | Pause if daily loss exceeds 20% |
| `DAILY_LOSS_LIMIT_USD` | `0.0` | Alternative USD limit (0 = disabled) |
| `MAX_CONSECUTIVE_LOSSES` | `10` | Pause after 10 consecutive losses |
| `MAX_TRADES_PER_DAY` | `100` | Maximum trades allowed per day |
| `LOSS_LIMIT_COOLDOWN_SECONDS` | `3600` | Cooldown after hitting limit (1 hour) |

### Timing

| Setting | Default | Description |
|---------|---------|-------------|
| `SCAN_INTERVAL_SECONDS` | `3` | How often to scan for markets |
| `TRADE_COOLDOWN_SECONDS` | `60` | Wait between trades |
| `MAX_MARKET_AGE_SECONDS` | `180` | Only trade markets < 3 min old |
| `ORDER_FILL_TIMEOUT` | `60` | Max seconds to wait for order fill |
| `REDEMPTION_CHECK_INTERVAL` | `300` | Seconds between redemption safety checks |

### API Credentials (LIVE mode only)

| Setting | Description |
|---------|-------------|
| `POLYMARKET_API_KEY` | Your Polymarket API key |
| `POLYMARKET_API_SECRET` | Your Polymarket API secret |
| `POLYMARKET_PASSPHRASE` | Your Polymarket passphrase |
| `WALLET_ADDRESS` | Your wallet address (0x...) |
| `WALLET_PRIVATE_KEY` | Your wallet private key (0x...) |

---

## 📂 Understanding the Code

### File Structure

```
polymarket-bot/
│
├── main.py           # 🚀 Entry point - run this to start the bot
├── config.py         # ⚙️ Configuration loading from .env
├── auth.py           # 🔐 Polymarket API authentication (L1 & L2)
├── market.py         # 🏪 Polymarket interactions, orders, redemption
├── price_feed.py     # 📊 BTC price data from Binance
├── strategy.py       # 🧠 Trading strategy logic
├── execution.py      # 💱 Trade execution, resolution, redemption
├── logger.py         # 📝 Trade logging to CSV
│
├── .env              # 🔒 Your secret configuration (don't commit!)
├── .env.example      # 📋 Template for .env file
├── requirements.txt  # 📦 Python dependencies
├── trades.csv        # 📈 Trade history log (with redemption data)
│
├── test_auth.py      # 🧪 Authentication tests
└── test_live_features.py  # 🧪 Live deployment feature tests
```

### How Data Flows

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  price_feed  │────▶│   strategy   │────▶│  execution   │
│  (BTC price) │     │ (decisions)  │     │   (trades)   │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       │                    │                    ▼
       ▼                    ▼              ┌──────────────┐
┌──────────────┐     ┌──────────────┐     │  redemption  │
│   Binance    │     │    market    │◀────│   (USDC)     │
│     API      │     │ (Polymarket) │     └──────────────┘
└──────────────┘     └──────────────┘           │
                            │                   ▼
                            │            ┌──────────────┐
                            └───────────▶│    logger    │
                                         │  (CSV file)  │
                                         └──────────────┘
```

### Key Classes and Functions

**`auth.py`** - Authentication
```python
from auth import get_auth, AuthLevel

auth = get_auth()
auth.is_ready(AuthLevel.L1)  # API key auth (read)
auth.is_ready(AuthLevel.L2)  # Wallet auth (write/trade)
auth.sign_order(order_data)  # Sign orders for CLOB
```

**`market.py`** - Market Operations
```python
from market import get_client

client = get_client()

# Balance & Positions
client.get_usdc_balance()          # Get wallet USDC balance
client.get_open_positions()        # Get all open positions
client.get_position_for_token(id)  # Get specific position

# Trading
client.place_order(...)            # Place a trade
client.wait_for_order_fill(...)    # Wait for execution
client.cancel_order(order_id)      # Cancel unfilled order

# Resolution & Redemption
client.get_market_resolution(...)  # Check if market resolved
client.check_trade_resolution(...) # Check WIN/LOSS
client.redeem_winning_shares(...)  # Convert shares to USDC ⭐
client.redeem_all_winning_positions()  # Batch redemption ⭐
```

**`execution.py`** - Trade Engine
```python
from execution import ExecutionEngine

engine = ExecutionEngine(client)

# Trading
engine.can_trade(5.0)           # Check if trading allowed
engine.execute_trade(...)       # Execute a trade
engine.is_in_cooldown()         # Check cooldown status

# Resolution & Redemption
engine.check_and_resolve_trades()    # Resolve completed trades
engine.check_and_redeem_positions()  # Safety redemption check ⭐
engine.refresh_balance()             # Sync balance from API

# Statistics
engine.get_daily_stats()        # Get daily statistics
engine.get_stats()              # Get overall statistics
engine.print_stats()            # Print to console
```

**`strategy.py`** - Strategy Logic
```python
from strategy import analyze_trade_opportunity, should_trade, calculate_bet_size

signal = analyze_trade_opportunity(market, polymarket, binance)
if should_trade(signal):
    bet_size = calculate_bet_size(balance)
```

---

## 🛡️ Safety Features

### Daily Loss Limit

The bot automatically pauses trading if you lose too much in one day.

```
Example:
- Starting balance: $100
- Daily loss limit: 20%
- After losing $20 → Bot pauses until midnight UTC
```

### Consecutive Loss Protection

Pauses trading after too many losses in a row.

```
Example:
- Max consecutive losses: 10
- After 10 losses in a row → Bot pauses for 1 hour
```

### Maximum Trade Limit

Prevents overtrading by capping daily trades.

```
Example:
- Max trades per day: 100
- After 100 trades → No more trades until midnight UTC
```

### Order Timeout Protection

Cancels orders that take too long to fill.

```
Example:
- Order fill timeout: 60 seconds
- If order not filled in 60s → Cancel and skip trade
```

### How to Check Safety Status

```python
from execution import ExecutionEngine
from market import get_client

engine = ExecutionEngine(get_client())
stats = engine.get_daily_stats()

print(f"Daily PnL: ${stats['daily_pnl']:+.2f}")
print(f"Trades today: {stats['trades']}")
print(f"Consecutive losses: {stats['consecutive_losses']}")
print(f"Trading paused: {stats['trading_paused']}")
```

---

## 💰 Live Deployment: Automatic Redemption System

> **CRITICAL**: This section explains how the bot handles winning share redemption - a feature that is **essential** for live trading with real money.

### Understanding Polymarket's Payout System

When you win a trade on Polymarket, your winnings are **NOT automatically credited** to your USDC balance. Instead:

1. You receive **winning shares** (tokens)
2. These shares must be **redeemed** to convert back to USDC
3. Without redemption, your winnings stay locked as tokens!

**This bot handles redemption automatically.** Here's how:

### How Automatic Redemption Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRADE LIFECYCLE (LIVE MODE)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. TRADE EXECUTION                                              │
│     ├─> Place order on Polymarket                                │
│     ├─> Store token_id (CRITICAL for redemption)                 │
│     ├─> Store condition_id (for resolution tracking)             │
│     └─> Sync balance from API                                    │
│                                                                  │
│  2. WAIT FOR MARKET RESOLUTION (15 minutes)                      │
│     └─> Bot continues running, checking other opportunities      │
│                                                                  │
│  3. RESOLUTION CHECK                                             │
│     ├─> Query Polymarket API for market outcome                  │
│     └─> Determine if our position WON or LOST                    │
│                                                                  │
│  4. IF WIN: AUTOMATIC REDEMPTION                                 │
│     ├─> Call redeem_winning_shares(token_id)                     │
│     ├─> Convert winning shares → USDC                            │
│     ├─> Update redemption_status = "REDEEMED"                    │
│     ├─> Record redemption_amount in trade log                    │
│     └─> Sync balance from API to confirm credit                  │
│                                                                  │
│  5. IF LOSS: No redemption needed                                │
│     └─> Mark redemption_status = "N/A"                           │
│                                                                  │
│  6. PERIODIC SAFETY CHECK (every 5 minutes)                      │
│     ├─> Scan for any unredeemed winning positions                │
│     └─> Attempt redemption of any missed shares                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Features of the Redemption System

#### 1. Token ID Tracking

Every trade stores the `token_id` of the purchased position:

```python
# When executing a live trade:
trade.token_id = market.tokens.get("up")  # or "down"
trade.condition_id = market.condition_id
```

This is **essential** because without the token ID, we cannot redeem!

#### 2. Automatic Redemption on WIN

When a trade resolves as WIN, the bot automatically:

```python
# Inside _resolve_trade_with_outcome():
if outcome == "WIN" and not config.TEST_MODE:
    redemption_result = self._redeem_winning_shares(trade)
    trade.redemption_status = "REDEEMED"
    trade.redemption_amount = redemption_result["amount_usdc"]
```

#### 3. Balance Synchronization

After redemption, the bot syncs with Polymarket:

```python
# Ensures internal balance matches actual USDC:
self._sync_balance_after_resolution()
```

#### 4. Periodic Redemption Safety Net

Every 5 minutes (configurable), the bot checks for missed redemptions:

```python
# In main trading loop:
if time_since_last_check >= REDEMPTION_CHECK_INTERVAL:
    engine.check_and_redeem_positions()
```

### Trade CSV Logging (New Fields)

All trades now log additional fields for live deployment:

| Column | Description | Example |
|--------|-------------|---------|
| `token_id` | Token purchased | `21742633...` |
| `condition_id` | Market condition | `0x8f3e...` |
| `redemption_status` | Redemption state | `REDEEMED`, `PENDING`, `N/A`, `FAILED` |
| `redemption_amount` | USDC redeemed | `12.50` |
| `order_id` | Polymarket order ID | `abc123...` |
| `filled_price` | Actual fill price | `0.4825` |
| `filled_shares` | Shares purchased | `20.7254` |

### Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `REDEMPTION_CHECK_INTERVAL` | `300` | Seconds between redemption safety checks |
| `ORDER_FILL_TIMEOUT` | `60` | Max seconds to wait for order fill |

### Manual Redemption Commands

If needed, you can manually trigger redemption:

```python
from market import get_client

client = get_client()

# Redeem a specific token
result = client.redeem_winning_shares(
    token_id="21742633...",
    shares=10.5
)
print(f"Redeemed: ${result['amount_usdc']:.2f}")

# Redeem ALL unredeemed positions
summary = client.redeem_all_winning_positions()
print(f"Total redeemed: ${summary['total_redeemed']:.2f}")
```

### Verifying Redemption Worked

After a winning trade, verify in your logs:

```bash
# Check recent trades
tail -5 trades.csv | cut -d',' -f1,13,20,21,22

# Expected output for a WIN:
# timestamp,outcome,token_id,redemption_status,redemption_amount
# 2026-02-05T12:00:00,WIN,21742...,REDEEMED,12.50
```

Also verify on Polymarket:
1. Log into [polymarket.com](https://polymarket.com)
2. Check your USDC balance
3. Confirm it increased after the winning trade

### Troubleshooting Redemption Issues

#### "Redemption failed" in logs

**Cause:** API error or network issue

**Solution:**
1. Check if you still hold the winning shares on Polymarket
2. Run manual redemption: `client.redeem_all_winning_positions()`
3. If still failing, redeem manually on the Polymarket website

#### "No token_id stored" error

**Cause:** Trade was executed before the token tracking update

**Solution:**
1. Old trades cannot be auto-redeemed
2. Check Polymarket website for unredeemed positions
3. Redeem manually on the website

#### Balance not updating after WIN

**Cause:** Redemption might have failed silently

**Solution:**
1. Check `trades.csv` for `redemption_status`
2. If `FAILED` or `PENDING`, run manual redemption
3. Verify on Polymarket website

### Position Tracking API

View your current open positions:

```python
from market import get_client

client = get_client()
positions = client.get_open_positions()

for pos in positions:
    print(f"Token: {pos['token_id'][:16]}...")
    print(f"Shares: {pos['size']:.4f}")
    print(f"Avg Price: ${pos['avg_price']:.4f}")
    print("---")
```

---

## 🔧 Troubleshooting

### Common Issues

#### "Size lower than the minimum: 5" (Order Rejected)

**Cause:** Polymarket CLOB requires a **minimum of 5 shares** per order.

**Explanation:**
- Polymarket enforces a minimum order size of **5 shares**
- At $0.50 price per share, that's a minimum of **$2.50** per order
- Small bets (e.g., $1.41) result in only ~2.8 shares, which is rejected

**Solution:**
1. **Increase `MIN_BET_SIZE_USD`** in your `.env` or `config.py`:
   ```bash
   # Minimum $3.00 ensures at least 5 shares at ~$0.50 prices
   MIN_BET_SIZE_USD=3.0
   ```

2. **Or increase your bet percentage**:
   ```bash
   # 5% of balance instead of 3%
   BET_SIZE_PERCENT=0.05
   ```

3. **Ensure adequate balance**: With a $50 balance at 3% bet size = $1.50 bet, which is too small. Either:
   - Increase balance to $100+ (3% = $3.00 ✅)
   - Or increase bet percentage

> **Note:** The bot automatically adjusts orders up to 5 shares when possible, but the initial bet size must be close enough to afford this adjustment.

#### "Order book spread too wide" / "Slippage too high: 98%"

**Cause:** The market's order book has no liquidity at competitive prices.

**Explanation:**
- Polymarket order books can show extreme spreads (bid: $0.01, ask: $0.99)
- This happens when:
  - The market is near resolution (outcome is nearly certain)
  - No market makers are providing liquidity at fair prices
- The bot correctly rejects these illiquid conditions

**Solution:**
- Wait for fresh markets (the bot does this automatically)
- The bot uses `MAX_MARKET_AGE_SECONDS=180` to only trade young markets
- If you see this consistently, the markets may have structural liquidity issues

#### "No BTC 15-min markets found"

**Cause:** Polymarket may not have active 15-minute BTC markets.

**Solution:** Wait for new markets to open. They typically run every 15 minutes.

#### "Insufficient balance"

**Cause:** Wallet doesn't have enough USDC.

**Solution:** 
1. Check your Polymarket wallet balance
2. Deposit more USDC if needed
3. Ensure you're on Polygon network

#### "Authentication failed"

**Cause:** Invalid API credentials or wallet key.

**Solution:**
1. Double-check your API key, secret, and passphrase
2. Ensure wallet address and private key match
3. Run `python test_auth.py` to diagnose

#### "eth-account package not installed" (Live Trading)

**Cause:** The `eth-account` package is required for wallet verification in LIVE trading mode but is not installed.

**Solution:**
```bash
# Install the missing package
pip install eth-account

# Or reinstall all requirements (recommended)
pip install -r requirements.txt
```

> **Note:** This package is only required when `TEST_MODE=false`. Test mode (paper trading) does not require wallet verification.

#### "CLOB Balance shows $0" (But I Have Money on Polymarket!)

**Cause:** Your funds are in Polymarket's **website proxy wallet**, not in your **direct wallet** where the CLOB API trades from.

**Explanation:**
- **Polymarket Website** = Funds held by Polymarket (proxy wallet)
- **CLOB API** = Trades from YOUR wallet directly

**Solution:**
1. Withdraw funds from Polymarket website to your wallet:
   - Go to https://polymarket.com → Portfolio → Wallet → Withdraw
   - Send to your wallet address
2. Run `python setup_clob_trading.py status` to verify

#### "not enough balance / allowance"

**Cause:** Either you don't have USDC.e, or you haven't approved the CLOB contracts.

**Solution:**
```bash
# Check your status
python setup_clob_trading.py status

# If allowances show ❌, run:
python setup_clob_trading.py approve
```

#### "Wrong USDC Type" / Balance Not Detected

**Cause:** You have regular **USDC** instead of **USDC.e**.

**Explanation:**
- USDC.e: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` ✅ (Polymarket uses this)
- USDC: `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` ❌ (NOT used by Polymarket)

**Solution:**
1. Swap USDC → USDC.e on [Uniswap](https://app.uniswap.org) or [QuickSwap](https://quickswap.exchange)
2. Or withdraw from Polymarket website (gives you USDC.e automatically)

#### "Rate limit exhausted" During Setup

**Cause:** The Polygon RPC is rate-limiting your requests.

**Solution:**
```bash
# Wait 30 seconds, then try again
sleep 30 && python setup_clob_trading.py approve
```

#### "Order fill timeout"

**Cause:** Market moved or low liquidity.

**Solution:** This is normal occasionally. The bot will auto-cancel and try again next opportunity.

#### "Trading paused"

**Cause:** Safety limit triggered.

**Solution:**
1. Check daily stats: `engine.get_daily_stats()`
2. Wait for cooldown to expire, or
3. Wait for midnight UTC reset, or
4. Adjust safety limits in `.env`

### Debug Mode

For more detailed output:

```bash
# In .env, ensure:
VERBOSE_LOGGING=true
```

### Log Files

- **Console output**: Real-time bot activity
- **trades.csv**: Complete trade history
- Check for Python errors in console

---

## ❓ FAQ

### Is this bot guaranteed to make money?

**No.** This bot implements a probabilistic strategy with a small edge. You can still lose money, especially during unusual market conditions.

### How much money do I need to start?

We recommend at least **$50-100** for live trading. This allows for proper bet sizing and surviving drawdowns.

### How many trades does the bot make?

Typically **10-50 trades per day**, depending on market conditions and BTC volatility.

### What's the expected win rate?

Target win rate is **52-55%**. Combined with the payout odds, this creates a small positive edge.

### Can I run this 24/7?

Yes, but we recommend monitoring it regularly, especially when first starting.

### What happens if my internet disconnects?

The bot will lose connection and stop trading. Active trades will still resolve on Polymarket. Restart the bot when connection is restored.

### Can I modify the strategy?

Yes! The strategy is in `strategy.py`. Test any changes thoroughly in simulation mode first.

### Is my private key safe?

Your private key is stored in `.env` locally. Never commit this file to git. The key is used only for signing orders and is never sent to any server.

### Why can't the bot use my Polymarket website balance?

The CLOB API trades directly from your wallet, not from Polymarket's proxy wallet. This is actually more secure because:
- **You keep control** of your funds at all times
- **Non-custodial** - Polymarket never holds your money
- Funds stay in YOUR wallet until a trade executes

To use your website balance, withdraw it to your wallet first.

### What's the difference between USDC and USDC.e?

| Token | Contract | Used By |
|-------|----------|---------|
| **USDC.e** | `0x2791Bca1...` | ✅ Polymarket |
| **USDC** | `0x3c499c54...` | ❌ Not Polymarket |

USDC.e is "bridged USDC" from Ethereum. Polymarket only accepts USDC.e.

### How do I get USDC.e?

1. **Withdraw from Polymarket website** (automatically gives USDC.e)
2. **Swap on DEX** (Uniswap/QuickSwap: USDC → USDC.e)
3. **Bridge from Ethereum** (Polygon Bridge converts to USDC.e)

### Does every trade cost gas (POL)?

Yes, but it's very cheap on Polygon:
- ~$0.01-0.05 per trade
- 0.5 POL = hundreds of trades
- You'll rarely need to top up

---

## 📊 Trade Logging

All trades are logged to `trades.csv` with:

### Core Trade Fields

| Column | Description |
|--------|-------------|
| `timestamp` | When the trade was placed (ISO format) |
| `trade_id` | Unique trade identifier |
| `market_id` | Polymarket market ID |
| `market_question` | Market question text |
| `side` | UP or DOWN |
| `entry_odds` | Price paid (e.g., 0.48 = 48%) |
| `fair_probability` | Our estimated fair probability |
| `edge` | Calculated edge percentage |
| `btc_price` | BTC price at trade time |
| `bet_size` | Amount bet in USD |
| `balance_before` | Balance before trade |
| `balance_after` | Balance after resolution |
| `outcome` | WIN, LOSS, or PENDING |
| `payout` | Amount received if won |
| `profit_loss` | Net profit or loss |
| `mode` | TEST or LIVE |

### Live Trading Fields

| Column | Description |
|--------|-------------|
| `order_id` | Polymarket CLOB order ID |
| `filled_price` | Actual fill price received |
| `filled_shares` | Number of shares purchased |
| `token_id` | Token ID (needed for redemption) |
| `condition_id` | Market condition ID |
| `redemption_status` | REDEEMED, PENDING, FAILED, or N/A |
| `redemption_amount` | USDC amount redeemed |

### Example CSV Row

```csv
timestamp,trade_id,market_id,side,entry_odds,outcome,payout,token_id,redemption_status,redemption_amount
2026-02-05T14:30:00,T1234567,btc-updown-15m-123,UP,0.4800,WIN,12.50,217426...,REDEEMED,12.50
```

---

## 📈 Performance Expectations

With default settings:

| Metric | Expected Range |
|--------|----------------|
| Win rate | 52-55% |
| Edge per trade | 2-5% |
| Trades per day | 10-50 |
| Daily variance | ±10-20% |
| Monthly expectation | +5-15% (highly variable) |

### Realistic Expectations

- 📉 **You will have losing days** - This is normal
- 📈 **Edge compounds over time** - Many small wins add up
- ⏳ **Patience required** - Results show over weeks, not days
- 🎲 **Variance is high** - Short-term results are mostly luck

---

## ⚠️ Risk Disclosure

1. **This is gambling** - Prediction markets are speculative
2. **You can lose money** - Past performance doesn't guarantee future results
3. **Strategy may fail** - Market conditions change
4. **Technical risks** - Bugs, API outages, network issues
5. **Regulatory risks** - Check your local laws regarding prediction markets

**Only trade with money you can afford to lose.**

---

## 📝 License

MIT License - Use at your own risk.

---

## 🙏 Acknowledgments

- [Polymarket](https://polymarket.com) - Prediction market platform
- [Binance](https://binance.com) - BTC price data

---

**Questions?** Open an issue on GitHub.

**Last updated:** February 2026
