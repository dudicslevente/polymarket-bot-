# Polymarket BTC 15-Minute Bot - Backtesting Guide

## 📋 Overview

This guide explains how to use the backtesting module to test the Polymarket BTC 15-minute prediction bot against **real historical data**. The backtest uses:

- **Binance BTCUSDT 1-minute candles** - Real price data for technical analysis
- **Polymarket CLOB timeseries** - Real historical market prices from Polymarket's API

> ⚠️ **Important**: The backtest module is designed to use **REAL DATA ONLY**. Synthetic/simulated data is deprecated and disabled by default.

---

## 🏗️ Architecture

```
backtest/
├── backtest.py           # Main backtesting engine
├── data_loader.py        # Loads Binance + Polymarket data
├── execution_realism.py  # Latency, slippage, liquidity caps, outlier filtering
├── fetch_polymarket.py   # Fetches real data from Polymarket CLOB API
├── metrics.py            # Calculates performance metrics
├── reporter.py           # Generates backtest reports
├── utils.py              # Timestamp and utility functions
└── __init__.py

data/
├── kaggle_data/
│   ├── polymarket_markets.csv   # Market metadata from Kaggle
│   └── polymarket_events.csv    # Event metadata from Kaggle
├── binance_1m.csv               # Binance 1m candles (auto-downloaded)
└── polymarket_15m.csv           # Real Polymarket 15m prices (fetched via API)
```

---

## 🚀 Quick Start (RECOMMENDED)

### Step 1: Fetch Real Polymarket Data (Auto Mode)

The `--auto` flag automatically detects the date range from your Binance data and fetches matching Polymarket markets:

```bash
# Recommended: Auto-detect date range from Binance data
python3 -m backtest.fetch_polymarket \
    --markets-csv data/kaggle_data/polymarket_markets.csv \
    --auto \
    --limit 200
```

### Step 2: Run the Backtest

```bash
# Run backtest with real data
python3 -m backtest.backtest
```

### Step 3: View Results

Results are printed to console with full trade details:
- Win/Loss per trade
- Edge percentage
- Running balance
- Final metrics (win rate, drawdown, etc.)

---

## 📖 Detailed Usage

### 1. Fetching Real Polymarket Data

The `fetch_polymarket.py` module downloads real historical prices from Polymarket's CLOB (Central Limit Order Book) API.

#### Data Source

**Polymarket CLOB Timeseries API**
- Endpoint: `https://clob.polymarket.com/prices-history`
- Documentation: https://docs.polymarket.com/developers/CLOB/timeseries

#### CLI Options

```bash
python3 -m backtest.fetch_polymarket [OPTIONS]

Options:
  --markets-csv PATH    Path to polymarket_markets.csv (Kaggle dataset)
  --output PATH         Output CSV path (default: data/polymarket_15m.csv)
  --limit N             Max number of markets to fetch (default: all)
  --days N              Days of history to fetch per market (default: 7)
  --start YYYY-MM-DD    Start date filter
  --end YYYY-MM-DD      End date filter  
  --auto                Auto-detect date range from Binance data (RECOMMENDED)
  --quiet               Less verbose output
```

#### Examples

```bash
# RECOMMENDED: Auto-detect date range, fetch 200 markets
python3 -m backtest.fetch_polymarket \
    --markets-csv data/kaggle_data/polymarket_markets.csv \
    --auto --limit 200

# Manual date range
python3 -m backtest.fetch_polymarket \
    --markets-csv data/kaggle_data/polymarket_markets.csv \
    --start 2025-12-01 --end 2025-12-31

# Quick test with 50 markets
python3 -m backtest.fetch_polymarket \
    --markets-csv data/kaggle_data/polymarket_markets.csv \
    --auto --limit 50
```

#### Output Format

The fetcher creates `data/polymarket_15m.csv` with columns:

| Column | Description |
|--------|-------------|
| `interval_start` | ISO timestamp of the 15-minute interval |
| `market_id` | Polymarket market ID |
| `outcome_yes_price` | YES token price (0.0 - 1.0) |
| `outcome_no_price` | NO token price (0.0 - 1.0) |
| `resolved_outcome` | Market outcome (UP/DOWN) if resolved |
| `volume` | Trading volume (if available) |
| `liquidity` | Market liquidity (if available) |

---

### 1.1 What does `--limit 200` actually mean?

When you run the fetcher with, for example:

```bash
python3 -m backtest.fetch_polymarket \
  --markets-csv data/kaggle_data/polymarket_markets.csv \
  --auto --limit 200
```

the `--limit 200` flag means:

- **200 = 200 distinct Polymarket markets**, selected from `polymarket_markets.csv`
- It does **not** mean 200 days, minutes, or 15-minute intervals

For each of those 200 markets:

- We call the Polymarket CLOB timeseries API to get that market's **full price history** around its end date (last ~7 days by default)
- That raw history is then aggregated into 15-minute intervals and written to `data/polymarket_15m.csv`

So the total number of 15-minute rows in `polymarket_15m.csv` is roughly:

> (number of selected markets) × (number of 15-minute buckets with price data)

and not simply equal to the `--limit` value.

---

### 2. Running the Backtest

The `backtest.py` module simulates the trading strategy against historical data.

#### CLI Options

```bash
python3 -m backtest.backtest [OPTIONS]

Options:
  --start-date YYYY-MM-DD    Start date for backtest
  --end-date YYYY-MM-DD      End date for backtest
  --initial-balance FLOAT    Starting balance in USDC (default: 10000)
  --position-size FLOAT      Position size per trade (default: 100)
  --quiet                    Suppress verbose output
  --allow-synthetic          Allow fallback to synthetic data (NOT recommended)
```

#### Examples

```bash
# Run full backtest with real data
python3 -m backtest.backtest

# Run with custom parameters
python3 -m backtest.backtest --initial-balance 5000 --position-size 50

# Run for specific date range
python3 -m backtest.backtest --start-date 2024-06-01 --end-date 2024-12-31

# Quiet mode (less output)
python3 -m backtest.backtest --quiet
```

---

### 3. Understanding the Backtest Logic

#### Data Flow

```
1. Binance 1m candles  →  Technical analysis (15min OHLC, indicators)
                              ↓
2. Strategy decision   →  BUY YES or BUY NO signal
                              ↓
3. Polymarket prices   →  Entry price from real market data
                              ↓
4. Market resolution   →  Exit at 1.0 (win) or 0.0 (lose)
```

#### Strategy Replication

The backtest uses the **exact same strategy** as the live bot:

1. **Aggregate 15 candles** of 1-minute Binance data into one 15-minute candle
2. **Calculate indicators**: RSI, MACD, Bollinger Bands, Volume analysis
3. **Generate signal**: UP (buy YES) or DOWN (buy NO)
4. **Simulate entry**: Use real Polymarket YES/NO prices at that timestamp
5. **Simulate exit**: When market resolves, payout is 1.0 (correct) or 0.0 (wrong)

#### How the 15-minute Polymarket prices are chosen

The Polymarket API returns a **time series of prices** (timestamp → price), not ready-made "15-minute candles". The backtester converts that into 15-minute intervals as follows:

- The whole timeline is split into 15-minute buckets: `[T, T+15m)`, `[T+15m, T+30m)`, ...
- For each bucket, we look at all Polymarket price points **at or before the bucket start** time
- We then use the **latest price at or before the start** of the bucket as the entry price for that interval

In other words:

- The backtest entry odds for a 15-minute interval are the odds you would have seen **right at the start of that 15-minute window**, based on the last known Polymarket price before that time
- If there was no trade exactly at the boundary, we use the most recent trade before it, which is the best approximation available from the CLOB timeseries

This is what drives the `outcome_yes_price` / `outcome_no_price` columns in `data/polymarket_15m.csv`, and those are the prices the strategy trades against in the backtest.

#### Profit Calculation

For each trade:

```
Entry Cost = position_size × entry_price
Payout = position_size × (1.0 if correct else 0.0)
Profit = Payout - Entry Cost
```

---

### 3.1 How realistic are the trades?

The backtest is designed to be **data-realistic** and now includes **execution realism** to provide conservative, real-world estimates.

#### ✅ What's Realistic (Enabled by Default)

| Feature | Description | Default Setting |
|---------|-------------|-----------------|
| **Real Binance data** | Uses actual BTCUSDT 1-minute candles | Always on |
| **Real Polymarket odds** | Uses historical CLOB timeseries prices | Always on |
| **Real market outcomes** | Fetches actual resolution from Polymarket API | `use_real_outcomes=True` |
| **Latency modeling** | Prices drift against you during execution delay | 8 seconds |
| **Adverse slippage** | Fill price is worse than quoted price | 0.8% + 15% of edge |
| **Liquidity caps** | Bet size limited to fraction of market depth | Max 5% of liquidity |
| **Outlier filtering** | Skips "too good to be true" opportunities | Odds 3%-97%, edge <25% |
| **Trade cadence** | Max one trade per 15-minute interval | Always enforced |

#### ⚠️ What's Simplified

- No orderbook queue position simulation
- No millisecond-level latency modeling
- Your trades don't move the market (no market impact)
- Assumes partial fills don't occur

---

## 🎯 Execution Realism (NEW)

The backtest includes a sophisticated **execution realism** module that makes results more conservative and realistic. This is **enabled by default**.

### Why Execution Realism Matters

Without realism adjustments, backtests are **too optimistic**:

| Optimistic Assumption | Reality | Realism Fix |
|----------------------|---------|-------------|
| Instant fills at snapshot price | 5-15 seconds to detect, compute, submit order | Latency-based pricing |
| Fill at exact quoted odds | Market moves against you when you trade | Adverse slippage |
| Can bet any amount | Large bets move the market | Liquidity caps |
| All opportunities are real | Some are stale quotes or illiquid | Outlier filtering |

### Realism Features Explained

#### 1. Latency-Based Pricing

**Problem**: You see a price at time T, but your order fills at T + 8 seconds. The price drifts against you.

**Solution**: We model price drift during the execution delay:

```
Adjusted Odds = Base Odds + (latency_seconds × drift_rate)
```

**Default**: 8 seconds latency → ~0.16% adverse drift

#### 2. Adverse Slippage

**Problem**: When you buy, you push the price up. Your fill is worse than the quote.

**Solution**: Two-component slippage model:

```
Fixed Slippage:        0.8% (always applied)
Proportional Slippage: 15% of your edge

Total = max(fixed, proportional)  # Whichever is worse
```

**Example**: If you have 6% edge and base odds of 0.45:
- Fixed slippage: 0.8% → fill at 0.458
- Proportional: 6% × 15% = 0.9% → fill at 0.459
- Result: You pay 0.459 instead of 0.45 (0.9% worse)

#### 3. Liquidity-Capped Bet Sizing

**Problem**: Betting $50 on a market with $200 liquidity would move the price significantly.

**Solution**: Cap bet size as fraction of market liquidity:

```
Max Bet = Market Liquidity × max_bet_fraction
Default: 5% of liquidity
```

**Example**: Market has $2,000 liquidity → max bet is $100

Also enforces:
- Minimum liquidity: $500 (skip illiquid markets)
- Minimum volume: Configurable (default: not required)

#### 4. Outlier Filtering

**Problem**: Extreme odds (YES at 2% or 98%) are often stale, illiquid, or data errors.

**Solution**: Skip trades that are "too good to be true":

| Filter | Default | Reason |
|--------|---------|--------|
| Min odds | 3% | Below this is likely illiquid/stale |
| Max odds | 97% | Above this is likely illiquid/stale |
| Max edge | 25% | Edge this high is unrealistic |
| High edge + low liquidity | Edge >15% needs $2000+ liquidity | Suspicious combination |

#### 5. Real Market Outcomes

**Problem**: Using BTC price movement to determine win/loss doesn't reflect actual Polymarket resolution.

**Solution**: Fetch real outcomes from Polymarket API:

```python
# The backtest uses the actual resolved_outcome from Polymarket
# Not just "did BTC go up or down?"
outcome = interval.resolved_outcome  # "UP" or "DOWN" from API
```

This accounts for cases where Polymarket resolution differs from simple price comparison (edge cases, resolution timing, etc.)

---

### Configuration Options

All realism parameters are configurable in `ExecutionRealismConfig`:

```python
from backtest.execution_realism import ExecutionRealismConfig

# Conservative settings (default)
config = ExecutionRealismConfig(
    # Latency
    enable_latency=True,
    latency_seconds=8.0,           # 8 second execution delay
    
    # Slippage
    enable_slippage=True,
    slippage_fixed=0.008,          # 0.8% fixed slippage
    slippage_proportional=0.15,    # 15% of edge lost to slippage
    
    # Liquidity
    enable_liquidity_cap=True,
    max_bet_liquidity_fraction=0.05,  # Max 5% of liquidity
    min_liquidity_usd=500.0,          # Skip if < $500 liquidity
    
    # Outlier filtering
    enable_outlier_filter=True,
    min_allowed_odds=0.03,         # Skip odds < 3%
    max_allowed_odds=0.97,         # Skip odds > 97%
    max_allowed_edge=0.25,         # Skip edge > 25%
)

# Aggressive settings (more trades, higher risk)
aggressive_config = ExecutionRealismConfig(
    latency_seconds=5.0,           # Faster execution
    slippage_fixed=0.005,          # Less slippage
    max_bet_liquidity_fraction=0.10,  # Allow 10% of liquidity
    min_allowed_odds=0.02,         # Accept more extreme odds
    max_allowed_odds=0.98,
)
```

---

### CLI Usage

#### Default (Realistic Mode)

```bash
# Recommended: Full realism enabled
python3 -m backtest.backtest

# Output shows realism status:
#    🎯 Execution realism: ENABLED
#       - Latency: 8.0s
#       - Slippage: 0.8% fixed
#       - Max bet: 5% of liquidity
#    ✅ Using REAL market outcomes
```

#### Disable Realism (Optimistic Mode)

```bash
# NOT recommended - results will be overly optimistic
python3 -m backtest.backtest --no-realism

# Output shows warning:
#    ⚠️ Execution realism: DISABLED (optimistic mode)
```

#### Use BTC Price for Outcomes

```bash
# Use BTC price movement instead of real Polymarket resolution
python3 -m backtest.backtest --btc-outcomes

# Output shows:
#    ⚠️ Using BTC price movement for outcomes
```

#### Full Options

```bash
python3 -m backtest.backtest [OPTIONS]

Realism Options:
  --no-realism      Disable execution realism (latency, slippage, caps)
  --btc-outcomes    Use BTC price movement instead of real market outcomes

Other Options:
  --data PATH       Path to data folder (default: data)
  --balance FLOAT   Starting balance (default: 100)
  --edge FLOAT      Minimum edge threshold (e.g., 0.02)
  --bet-size FLOAT  Bet size as fraction (e.g., 0.03)
  --no-plots        Skip generating plots
  --quiet           Less verbose output
```

---

### Realism Statistics

At the end of each backtest, you'll see a realism summary:

```
============================================================
📊 EXECUTION REALISM SUMMARY
============================================================
Trades considered:        201
Trades filtered:          0
------------------------------------------------------------
Filtered breakdown:
  - Extreme odds:         0
  - High edge:            0
  - High edge + low liq:  0
  - Low liquidity:        0
  - Low volume:           0
------------------------------------------------------------
Adjustments applied:
  - Latency adjusted:     201
  - Slippage applied:     201
  - Bet size capped:      0
------------------------------------------------------------
Avg odds adjustment:      +1.08% (against you)
============================================================
```

This tells you:
- How many trades were filtered out and why
- How many trades had adjustments applied
- The average adverse price adjustment per trade

---

### Comparing Realistic vs Optimistic Results

Here's a real comparison from the same dataset:

| Metric | Realistic (default) | Optimistic (`--no-realism`) |
|--------|--------------------|-----------------------------|
| Final Balance | $1,361.26 | $1,492.66 |
| Return | +1261% | +1393% |
| Trades | 201 | 206 |
| Win Rate | 84.6% | 85.0% |
| Avg P&L/Trade | $6.27 | $6.76 |

**Key Insight**: Realistic mode shows ~9% lower returns due to:
- 1.08% average adverse price adjustment per trade
- 5 fewer trades from outlier filtering

**Always use realistic mode** to set proper expectations for live trading.

---

### 3.2 Trade cadence: one decision per 15-minute interval

Time in the backtest is discretized into **15-minute intervals**. For each interval:

1. 15 × 1-minute Binance candles are aggregated into one 15-minute candle
2. The strategy runs **once** on that 15-minute candle
3. If there is a valid signal, the backtest opens **at most one trade** for that interval:
  - UP signal → buy YES at the 15-minute entry odds
  - DOWN signal → buy NO at the 15-minute entry odds

The backtest therefore **does not scalp multiple entries/exits inside a single 15-minute window**. It mirrors the intended behavior of a 15-minute decision cadence bot: one trade decision per bar, using the odds available at the start of that bar.

---

### 4. Backtest Output

#### Console Output

```
================================================================================
                         BACKTEST RESULTS SUMMARY
================================================================================
Period: 2024-01-01 to 2024-12-31
Initial Balance: $10,000.00
Final Balance: $12,345.67

PERFORMANCE METRICS
-------------------
Total Trades: 150
Win Rate: 58.67%
Total P/L: $2,345.67
Return: 23.46%

RISK METRICS
------------
Max Drawdown: 12.34%
Sharpe Ratio: 1.45
Profit Factor: 1.82
================================================================================
```

#### Generated Files

Results are saved to `backtest_results/`:

| File | Description |
|------|-------------|
| `summary.txt` | Text summary of results |
| `trades.csv` | All trades with entry/exit details |
| `equity_curve.csv` | Balance over time |
| `metrics.json` | All metrics in JSON format |

---

## ⚙️ Data Requirements

### Binance Data

Binance 1-minute candles are **automatically downloaded** if not present:

```bash
# Manual download (optional)
python3 -m data.fetch_data
```

### Polymarket Data

Real Polymarket data **must be fetched** before running the backtest:

```bash
# REQUIRED: Fetch real data
python3 -m backtest.fetch_polymarket --markets-csv data/kaggle_data/polymarket_markets.csv
```

### Required Files

| File | Source | Required? |
|------|--------|-----------|
| `data/btcusdt_1m.csv` | Binance API (auto-downloaded) | ✅ Yes |
| `data/polymarket_15m.csv` | Polymarket CLOB API | ✅ Yes |
| `data/kaggle_data/polymarket_markets.csv` | Kaggle dataset | ✅ Yes (for fetching) |

---

## 🔒 Synthetic Data Policy

**Synthetic data is DEPRECATED and DISABLED by default.**

If you try to run the backtest without real Polymarket data:

```
❌ ERROR: No real Polymarket data loaded!

Real Polymarket data is REQUIRED for accurate backtesting.
Synthetic data is deprecated and disabled by default.

To fix this:
  1. Run: python3 -m backtest.fetch_polymarket --markets-csv data/kaggle_data/polymarket_markets.csv
  2. Then run the backtest again

⚠️  To allow synthetic data (NOT recommended): --allow-synthetic
```

The `--allow-synthetic` flag exists for development/testing only and is **not recommended** for actual backtesting.

---

## 🔧 Troubleshooting

### Common Issues

#### "No real Polymarket data loaded"

**Solution**: Fetch real data first:
```bash
python3 -m backtest.fetch_polymarket --markets-csv data/kaggle_data/polymarket_markets.csv
```

#### "File not found: polymarket_markets.csv"

**Solution**: Download the Kaggle Polymarket dataset:
```bash
# Place files in data/kaggle_data/
# Files needed: polymarket_markets.csv, polymarket_events.csv
```

#### API rate limiting (HTTP 429)

**Solution**: The fetcher has built-in rate limiting. If errors persist:
```bash
# Reduce the number of markets
python3 -m backtest.fetch_polymarket --markets-csv data/kaggle_data/polymarket_markets.csv --limit 20
```

#### Some markets fail with HTTP 400

**Cause**: Some markets have invalid time ranges or metadata
**Solution**: This is expected. The fetcher will skip failed markets and continue. 70%+ success rate is normal.

---

## 📊 Example Workflow

Complete workflow from start to finish:

```bash
# 1. Navigate to project
cd /path/to/polymarket-bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Fetch real Polymarket data (auto-detects date range from Binance data)
python3 -m backtest.fetch_polymarket \
    --markets-csv data/kaggle_data/polymarket_markets.csv \
    --auto --limit 200

# 4. Run the backtest
python3 -m backtest.backtest

# 5. View results in console output
```

### Example Output

```
============================================================
📊 BACKTEST RESULTS SUMMARY
============================================================
Starting Balance:     $100.00
Final Balance:        $1659.74
Total P&L:            +$1559.74 (+1559.7%)
------------------------------------------------------------
Total Trades:         219
Wins:                 189
Losses:               30
Win Rate:             86.3%
------------------------------------------------------------
Avg P&L per Trade:    $7.12
Best Trade:           $12.30
Worst Trade:          $-10.00
Avg Edge:             5.55%
------------------------------------------------------------
Max Drawdown:         8.3% ($50.00)
============================================================
```

---

## 🔗 Data Sources

| Source | URL | Description |
|--------|-----|-------------|
| Polymarket CLOB API | https://clob.polymarket.com/prices-history | Real-time and historical prices |
| Polymarket Docs | https://docs.polymarket.com/developers/CLOB/timeseries | API documentation |
| Binance API | https://api.binance.com | BTCUSDT price data |
| Kaggle Dataset | [Polymarket Markets Dataset] | Market metadata |

---

## 📁 File Reference

### Input Files

| File | Purpose |
|------|---------|
| `data/kaggle_data/polymarket_markets.csv` | Market IDs, token IDs, dates |
| `data/kaggle_data/polymarket_events.csv` | Event metadata |
| `config.py` | Bot configuration |
| `strategy.py` | Trading strategy |

### Generated Files

| File | Purpose |
|------|---------|
| `data/binance_1m.csv` | Binance 1m candles |
| `data/polymarket_15m.csv` | Real Polymarket 15m prices |

---

## 🎯 Key Points

1. **Always use `--auto` flag** - Auto-detects date range from Binance data
2. **Fetch before backtest** - Run `fetch_polymarket.py` first
3. **Same strategy as live** - Backtest uses identical logic to the live bot
4. **Real data only** - Synthetic data is deprecated and disabled by default
5. **Execution realism ON by default** - Latency, slippage, and liquidity caps are enabled
6. **Real outcomes by default** - Uses actual Polymarket resolution, not just BTC price
7. **Use `--no-realism` sparingly** - Only for comparison, not for setting expectations

---

## 📋 Quick Reference

### Realism Defaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| `latency_seconds` | 8.0 | Execution delay in seconds |
| `slippage_fixed` | 0.8% | Fixed adverse slippage |
| `slippage_proportional` | 15% | Fraction of edge lost to slippage |
| `max_bet_liquidity_fraction` | 5% | Max bet as % of liquidity |
| `min_liquidity_usd` | $500 | Skip markets below this |
| `min_allowed_odds` | 3% | Skip extreme low odds |
| `max_allowed_odds` | 97% | Skip extreme high odds |
| `max_allowed_edge` | 25% | Skip unrealistic edge |

### Common Commands

```bash
# Recommended: Full realistic backtest
python3 -m backtest.backtest

# Compare with optimistic (for analysis only)
python3 -m backtest.backtest --no-realism

# Quick quiet run
python3 -m backtest.backtest --quiet --no-plots

# Custom parameters
python3 -m backtest.backtest --edge 0.03 --bet-size 0.05 --balance 1000
```

---

*Last updated: January 2026*
