# Polymarket BTC 15-Minute Prediction Bot

A trading bot that bets on Polymarket's "Will Bitcoin go UP or DOWN in the next 15 minutes?" markets using Binance price data for prediction.

---

## Table of Contents

1. [What This Bot Does](#what-this-bot-does)
2. [Quick Start (5 Minutes)](#quick-start-5-minutes)
3. [How the Strategy Works](#how-the-strategy-works)
4. [Running Modes Explained](#running-modes-explained)
5. [Step-by-Step: Going Live](#step-by-step-going-live)
6. [Configuration Reference](#configuration-reference)
7. [Understanding the Code](#understanding-the-code)
8. [Safety Features](#safety-features)
9. [Troubleshooting](#troubleshooting)
10. [Safe Live Trading Tutorial](#️-safe-live-trading-tutorial) ⭐ NEW
11. [FAQ](#faq)

---

## What This Bot Does

### The Market
Polymarket offers binary prediction markets: "Will BTC go UP or DOWN in the next 15 minutes?"

- **UP Token**: Pays $1 if BTC goes up, $0 if it goes down
- **DOWN Token**: Pays $1 if BTC goes down, $0 if it goes up

### The Opportunity
If you can predict direction with >50% accuracy, you can profit. The bot uses Binance's real-time data to find edges.

### The Flow
```
Binance Price Data → Strategy Analysis → Edge Calculation → Bet on Polymarket → Wait for Resolution → Profit/Loss
```

---

## Quick Start (5 Minutes)

### Step 1: Install Dependencies
```bash
cd /path/to/polymarket-bot-
pip install -r requirements.txt
```

### Step 2: Create Your `.env` File
Copy the example and fill in your credentials:
```bash
cp .env.example .env
```

Edit `.env` with your values:
```env
# Required for LIVE trading
POLYMARKET_API_KEY=your-api-key-here
POLYMARKET_SECRET=your-secret-here
POLYMARKET_PASSPHRASE=your-passphrase-here
POLYMARKET_WALLET_ADDRESS=0xYourWalletAddress
POLYMARKET_PRIVATE_KEY=your-private-key-hex

# Required for market data
BINANCE_API_KEY=your-binance-key
BINANCE_SECRET=your-binance-secret

# Optional
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### Step 3: Run in Simulation Mode (Recommended First)
```bash
python main.py --mode SIM
```

This runs the bot without real money to verify everything works.

### Step 4: Run Backtest
```bash
python main.py --mode BACKTEST
```

See historical performance before risking real funds.

---

## How the Strategy Works

### The Core Idea
The bot looks at Binance's BTC price movements and calculates whether UP or DOWN is more likely in the next 15 minutes.

### Edge Calculation
```
Edge = (Predicted Win Rate × Payout) - (Predicted Loss Rate × Stake)
```

The bot only bets when the edge exceeds a minimum threshold (default: 2%).

---

## Running Modes Explained

### `LIVE` Mode
**Real money trading on Polymarket.**

```bash
python main.py --mode LIVE
```

What happens:
1. ✅ Connects to Polymarket with your API credentials
2. ✅ Checks your USDC balance before each trade
3. ✅ Places real orders with real money
4. ✅ Waits for order fills with timeout handling
5. ✅ Monitors market resolution
6. ✅ Enforces all safety limits

**Requirements:**
- All credentials in `.env`
- USDC in your Polymarket wallet
- Approved for CLOB trading

### `SIM` Mode
**Simulated trading with real market data.**

```bash
python main.py --mode SIM
```

What happens:
1. ✅ Connects to real Polymarket prices
2. ✅ Simulates order execution (no real trades)
3. ✅ Tracks virtual P&L
4. ❌ No real money at risk

**Use this to:**
- Test your setup
- Validate strategy in current market conditions
- Debug issues safely

### `BACKTEST` Mode
**Test strategy on historical data.**

```bash
python main.py --mode BACKTEST
```

What happens:
1. ✅ Loads historical price data
2. ✅ Runs strategy on past data
3. ✅ Generates performance metrics
4. ✅ Creates analysis plots

---

## Step-by-Step: Going Live

### Step 1: Get Your Polymarket API Credentials

1. Go to [Polymarket.com](https://polymarket.com)
2. Connect your wallet
3. Navigate to Settings → API → Create API Key
4. Save these values:
   - API Key
   - Secret
   - Passphrase

### Step 2: Export Your Wallet Private Key

**⚠️ SECURITY WARNING: Never share your private key!**

From MetaMask:
1. Click the three dots → Account Details
2. Click "Export Private Key"
3. Enter your password
4. Copy the hex string (starts with characters, not 0x)

### Step 3: Get Binance API Credentials

1. Go to [Binance.com](https://binance.com) → API Management
2. Create new API key
3. Enable "Read" permissions only (no trading needed)
4. Save API Key and Secret

### Step 4: Configure Your `.env` File

```env
# Polymarket CLOB API (get from polymarket.com/settings)
POLYMARKET_API_KEY=CLOB-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
POLYMARKET_SECRET=your-base64-encoded-secret
POLYMARKET_PASSPHRASE=your-passphrase

# Your wallet (the one connected to Polymarket)
POLYMARKET_WALLET_ADDRESS=0x1234567890abcdef1234567890abcdef12345678
POLYMARKET_PRIVATE_KEY=abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890

# Binance (for price data)
BINANCE_API_KEY=your-binance-api-key
BINANCE_SECRET=your-binance-secret
```

### Step 5: Fund Your Polymarket Account

1. Transfer USDC to Polygon network
2. Deposit USDC into Polymarket
3. Verify balance in your Polymarket wallet

### Step 6: Test Your Setup

```bash
# Verify credentials work
python test_auth.py

# Run simulation first
python main.py --mode SIM
```

Expected output:
```
✅ L1 Authentication: OK
✅ L2 Signing: OK
✅ Balance Check: OK
✅ Ready for trading!
```

### Step 7: Go Live

```bash
python main.py --mode LIVE
```

---

## Configuration Reference

### `config.py` - Core Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `MODE` | `SIM` | Trading mode: `LIVE`, `SIM`, or `BACKTEST` |
| `TRADE_SIZE` | `2.0` | USDC amount per trade |
| `MIN_EDGE` | `0.02` | Minimum edge to place bet (2%) |
| `SLIPPAGE_TOLERANCE` | `0.02` | Max price slippage allowed |

### `.env` - Credentials

| Variable | Required For | Description |
|----------|--------------|-------------|
| `POLYMARKET_API_KEY` | LIVE | Your CLOB API key |
| `POLYMARKET_SECRET` | LIVE | Your CLOB secret |
| `POLYMARKET_PASSPHRASE` | LIVE | Your CLOB passphrase |
| `POLYMARKET_WALLET_ADDRESS` | LIVE | Your Polygon wallet address |
| `POLYMARKET_PRIVATE_KEY` | LIVE | Your wallet's private key |
| `BINANCE_API_KEY` | All | Binance API key for price data |
| `BINANCE_SECRET` | All | Binance API secret |

### Safety Limits (in `config.py`)

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_DAILY_LOSS` | `20.0` | Stop trading if daily loss exceeds |
| `MAX_CONSECUTIVE_LOSSES` | `5` | Pause after N consecutive losses |
| `MAX_TRADES_PER_DAY` | `50` | Maximum trades per day |
| `COOLDOWN_MINUTES` | `30` | Cooldown after consecutive losses |

---

## Understanding the Code

### File Structure

```
polymarket-bot-/
│
├── main.py              # Entry point - starts the bot
├── config.py            # All configuration settings
├── auth.py              # Polymarket authentication (L1/L2)
├── market.py            # Market data, orders, balances
├── strategy.py          # Trading strategy logic
├── execution.py         # Trade execution engine
├── price_feed.py        # Binance price streaming
├── logger.py            # Logging configuration
│
├── backtest/            # Backtesting framework
│   ├── backtest.py      # Main backtesting logic
│   ├── data_loader.py   # Historical data loading
│   └── plots.py         # Performance charts
│
├── data/                # Historical data storage
│   ├── binance_1m.csv   # Binance minute data
│   └── polymarket_15m.csv
│
├── .env                 # Your credentials (create this!)
├── .env.example         # Template for .env
├── trades.csv           # Trade log
└── requirements.txt     # Python dependencies
```

### Key Functions

**`auth.py`**
- `PolymarketAuth.get_headers()` - Generate L1 authenticated headers
- `PolymarketAuth.sign_order()` - Sign orders with your private key (L2)

**`market.py`**
- `get_usdc_balance()` - Check your Polymarket wallet balance
- `place_order()` - Submit a signed order to Polymarket
- `wait_for_order_fill()` - Wait for order execution with timeout
- `get_market_resolution()` - Poll for market outcome

**`execution.py`**
- `execute_trade()` - Main trade execution with all safety checks
- `check_safety_limits()` - Verify within daily limits
- `update_daily_stats()` - Track wins/losses/P&L

**`strategy.py`**
- `calculate_edge()` - Compute expected edge for a bet
- `should_bet()` - Decision logic: bet or skip

---

## Safety Features

### 1. Daily Loss Limit
**Stops trading if you lose too much in one day.**
- `MAX_DAILY_LOSS = 20.0` (USD)
- Bot stops placing new trades when triggered
- Resumes next day

### 2. Consecutive Loss Protection
**Pauses after a losing streak.**
- `MAX_CONSECUTIVE_LOSSES = 5`
- `COOLDOWN_MINUTES = 30`
- Enters cooldown period when triggered

### 3. Trade Frequency Limit
**Prevents overtrading.**
- `MAX_TRADES_PER_DAY = 50`
- No more trades until next day

### 4. Balance Verification
**Checks balance before every trade.**
- Skips trade if insufficient funds

### 5. Slippage Protection
**Prevents bad fills.**
- `SLIPPAGE_TOLERANCE = 0.02` (2%)
- Orders cancelled if price moves too much

---

## Troubleshooting

### "Authentication Failed"
- Verify `.env` file exists and is readable
- Check API key format: `CLOB-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
- Ensure secret is base64 encoded
- Regenerate API key if expired

### "Insufficient Balance"
- Deposit USDC to Polymarket
- Check you're on Polygon network
- Verify wallet address in `.env`

### "Order Rejected"
- Check market is still open
- Verify price is within bounds (0.01 - 0.99)
- Ensure minimum order size met

### "No Trades Executing"
- Reduce `MIN_EDGE` if too conservative
- Check strategy parameters
- Verify market data is updating

---

## FAQ

**Q: Is this bot profitable?**
A: Past performance doesn't guarantee future results. Start small and test thoroughly.

**Q: How much money do I need to start?**
A: Minimum recommended: $50-100 USDC. This allows for proper bankroll management.

**Q: Can I run this 24/7?**
A: Yes, but monitor it. Use SIM mode first. Consider a VPS for reliability.

**Q: How do I change the trade size?**
A: Edit `TRADE_SIZE` in `config.py`

**Q: Where are my trade logs?**
A: All trades are logged to `trades.csv`

**Q: How do I analyze my performance?**
A: Run `python analyze_trades.py` - generates charts in `analyze_plots/`

---

## Disclaimer

**This software is for educational purposes only.**

- Trading involves significant risk of loss
- Past performance is not indicative of future results
- Never trade with money you can't afford to lose
- The authors are not responsible for any financial losses

**Use at your own risk.**

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
   - This becomes your DAILY_LOSS_LIMIT_USD
   
3. **How much per trade?**
   - Start with 2-5% of your total balance
   - Use BET_SIZE_PERCENT to set this

**Example Risk Budget:**
```
Total I can lose: $100
Daily loss limit: $20 (20% of total)
Per-trade size: $3-5 (3-5% of total)
```

---

### Phase 2: Configuration (Safety First)

#### 2.1 Create Your Safe Configuration

Edit your `.env` file with these **conservative** settings for your first week:

```bash
# SAFE LIVE TRADING CONFIGURATION

# Mode: LIVE
TEST_MODE=false

# API Credentials (required)
POLYMARKET_API_KEY=your_key_here
POLYMARKET_API_SECRET=your_secret_here
POLYMARKET_PASSPHRASE=your_passphrase_here
POLYMARKET_WALLET_ADDRESS=0xYourAddress
POLYMARKET_PRIVATE_KEY=your_private_key

# CONSERVATIVE BET SIZING
BET_SIZE_PERCENT=0.03          # 3% of balance per trade
MIN_BET_SIZE_USD=1.0           # Minimum $1 per trade
MAX_BET_SIZE_USD=5.0           # Maximum $5 per trade (KEEP LOW!)

# STRICT SAFETY LIMITS
DAILY_LOSS_LIMIT_PERCENT=0.15  # Stop if down 15% for the day
DAILY_LOSS_LIMIT_USD=15.0      # Or stop if down $15
MAX_CONSECUTIVE_LOSSES=4       # Pause after 4 losses in a row
MAX_TRADES_PER_DAY=25          # Max 25 trades per day
LOSS_LIMIT_COOLDOWN_SECONDS=1800  # 30 min cooldown

# CONSERVATIVE STRATEGY
MIN_EDGE=0.03                  # Only trade if 3%+ edge
TRADE_COOLDOWN_SECONDS=120     # Wait 2 min between trades

# KEEP RESERVE
MIN_BALANCE_TO_TRADE=10.0      # Always keep $10 in reserve
```

#### 2.2 Understand Each Safety Setting

| Setting | What It Does | Why It Matters |
|---------|--------------|----------------|
| MAX_BET_SIZE_USD=5.0 | Caps each trade at $5 | Limits damage from any single bad trade |
| DAILY_LOSS_LIMIT_PERCENT=0.15 | Stops trading if down 15% | Prevents catastrophic daily losses |
| MAX_CONSECUTIVE_LOSSES=4 | Pauses after 4 losses | Stops the bleeding during losing streaks |
| MIN_EDGE=0.03 | Only trades with 3%+ edge | Avoids marginal/risky trades |
| TRADE_COOLDOWN_SECONDS=120 | Waits 2 min between trades | Prevents overtrading |
| MIN_BALANCE_TO_TRADE=10.0 | Keeps $10 reserve | Ensures you never go to zero |

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
!!! WARNING: LIVE TRADING MODE !!!

You are about to trade with REAL MONEY on Polymarket.
Type 'I UNDERSTAND THE RISKS' to continue:
```

Type exactly: `I UNDERSTAND THE RISKS`

#### 3.4 Monitor Your First 10 Trades

**Stay at your computer for the first 10 trades!**

Watch for:
- ✅ Orders are being placed
- ✅ Orders are being filled (not timing out)
- ✅ Resolutions are being detected (WIN/LOSS)
- ✅ Balance is updating correctly
- ❌ Any errors in the console

**If you see errors:**
1. Press Ctrl+C to stop the bot
2. Check the error message
3. Fix the issue before restarting

#### 3.5 Check Your Trades

After a few trades, check trades.csv:

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
| Stop the bot immediately | Ctrl+C |
| Check recent trades | tail -20 trades.csv |
| Analyze performance | python main.py --analyze |
| Switch to TEST mode | Set TEST_MODE=true in .env |
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

