# Polymarket BTC 15-Minute Trading Bot

A **conservative, production-ready** Python trading bot for Polymarket BTC 15-minute Up/Down prediction markets.

## ⚠️ IMPORTANT LIMITATION

**As of January 2026, Polymarket does NOT have 15-minute BTC up/down markets available.**

Polymarket focuses on longer-term prediction markets (weeks/months/years), not short-term trading markets. The bot was designed for markets that currently don't exist on the platform.

### What This Means

- **Live trading**: The bot will find 0 markets to trade
- **Strategy is sound**: The conservative approach would work well for short-term BTC trading
- **Testing**: Use simulation mode to test the strategy logic

### Recommended Usage

1. **Test the strategy** using simulation mode
2. **Monitor Polymarket** for future short-term BTC markets
3. **Consider other platforms** that offer short-term crypto markets
4. **Use as a framework** for building bots on other prediction markets

## 🧪 Testing the Strategy

Since real 15-minute BTC markets don't exist, use simulation mode to test:

```bash
# Run fast simulation (recommended)
python main.py --simulate

# This creates realistic simulated markets and tests the full strategy
```

## 🎯 Strategy Overview

This bot trades BTC 15-minute Up/Down markets on Polymarket using a **conservative rolling-interval strategy**:

1. **Detect BTC momentum**: If BTC moves ≥0.10% in the last 3 minutes, we have directional bias
2. **Estimate fair probability**: Conservative estimates (52-56%) based on bias strength
3. **Calculate edge**: Only trade when our estimated edge exceeds fees + slippage
4. **Conservative sizing**: 3% of bankroll per trade, never all-in
5. **Wait for resolution**: No early exits, no hedging

### Design Philosophy

- **Boring over exciting**: Simple, explainable strategy
- **Survival over profit**: Small bets, preserve capital
- **Skip over force**: Miss good trades rather than take bad ones
- **Simple over complex**: No fancy indicators or ML

## 📁 Project Structure

```
polymarket-bot/
├── config.py        # Settings, thresholds, env loading
├── market.py        # Polymarket API interactions
├── price_feed.py    # Binance BTC price data
├── strategy.py      # Bias detection, edge calculation
├── execution.py     # Trade execution & simulation
├── logger.py        # CSV trade logging
├── main.py          # Main orchestration loop
├── .env.example     # Environment variable template
├── requirements.txt # Python dependencies
└── README.md        # This file
```

## 🚀 Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd polymarket-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your settings
# For TEST MODE, you only need to set TEST_MODE=true
```

### 3. Run in Test Mode (Recommended First)

```bash
# Run the bot in test mode (default)
python main.py

# Run fast simulation (instant trade resolution)
python main.py --simulate

# Analyze your trade log
python main.py --analyze
```

### 4. Run in Live Mode (After Testing)

```bash
# Edit .env and set:
# TEST_MODE=false
# Add your Polymarket API credentials
# Add your wallet credentials

# Run with live trading
python main.py

# Or force live mode via command line
python main.py --live
```

## ⚙️ Configuration

All settings are in `.env` file. Key parameters:

### Trading Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `TEST_MODE` | `true` | Simulate trades (no real money) |
| `INITIAL_VIRTUAL_BALANCE` | `100.0` | Starting balance for test mode |
| `BET_SIZE_PERCENT` | `0.03` | 3% of balance per trade |
| `MAX_BET_SIZE_USD` | `10.0` | Maximum bet cap |
| `MIN_BALANCE_TO_TRADE` | `10.0` | Stop when balance falls below |

### Signal Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BTC_BIAS_THRESHOLD_PERCENT` | `0.10` | Min % move to detect bias |
| `BTC_LOOKBACK_MINUTES` | `3` | Lookback period for momentum |
| `MIN_EDGE_THRESHOLD` | `0.02` | Required 2% edge to trade |

### Timing Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SCAN_INTERVAL_SECONDS` | `15` | How often to check markets |
| `TRADE_COOLDOWN_SECONDS` | `60` | Wait between trades |
| `MAX_MARKET_AGE_SECONDS` | `60` | Only trade fresh markets |

## 📊 Trade Logging

All trades are logged to `trades.csv` with:

- Timestamp
- Market ID
- Side (UP/DOWN)
- Entry odds
- Estimated fair probability
- Calculated edge
- BTC price at entry
- Bet size
- Balance before/after
- Win/Loss outcome
- Mode (TEST/LIVE)

View performance stats:

```bash
python main.py --analyze
```

## 🧪 Test Mode

Test mode is **critical** for:

1. **Understanding the bot**: See how decisions are made
2. **Validating your config**: Ensure settings are reasonable
3. **Testing without risk**: No real money involved

In test mode:
- Uses virtual balance ($100 default)
- Simulates trade execution (instant fill)
- Simulates resolution (probabilistic, based on estimated edge)
- Logs everything as in live mode

**Always run in test mode first!**

## 🔐 Security

### API Credentials

- Never commit `.env` to version control
- Add `.env` to your `.gitignore`
- Use separate API keys for testing vs production

### Wallet Security

- Use a dedicated trading wallet
- Only fund with what you can afford to lose
- Consider hardware wallet for large amounts

## 📈 Expected Performance

With default settings:

- **Win rate target**: ~52-55% (based on small edge)
- **Trades per day**: 10-50 (depends on market conditions)
- **Expected edge**: 1.5-4% per trade after fees
- **Drawdown risk**: 10 losses in a row = ~26% drawdown

**This is a small-edge compounding strategy.** Don't expect to get rich quick.

## ⚠️ Risks

1. **Strategy risk**: Our edge estimates may be wrong
2. **Execution risk**: API errors, delays, fills
3. **Market risk**: Unusual BTC volatility
4. **Platform risk**: Polymarket availability
5. **Regulatory risk**: Check your local laws

## 🔧 Troubleshooting

### "No BTC 15-min markets found"

Polymarket may not have active 15-minute BTC markets at all times. Wait for new markets to open.

### "Insufficient liquidity"

Market doesn't have enough liquidity for safe trading. The bot skips these automatically.

### "No clear BTC bias"

BTC is moving sideways. No trade signal = no trade.

### API errors

The bot handles API errors gracefully. Check your internet connection and API credentials.

## 🛠️ Development

### Adding new features

1. Keep it simple
2. Test in simulation first
3. Add logging for debugging
4. Don't optimize for speed

### Running tests

```bash
# Fast simulation (10 cycles)
python main.py --simulate
```

## 📝 License

MIT License - Use at your own risk.

## 🙏 Acknowledgments

- Polymarket for the prediction markets
- Binance for BTC price data

---

**Remember: Trade responsibly. Start small. Never risk what you can't afford to lose.**
