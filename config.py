"""
Configuration module for Polymarket BTC 15-minute trading bot.

This module handles:
- Environment variable loading
- Global settings and thresholds
- Test mode configuration

All secrets are loaded from .env file - NEVER hardcode credentials.
"""

import os
from dotenv import load_dotenv
from typing import Optional

# Load environment variables from .env file
load_dotenv()


# ────────────────────────────────────────────────────────────────────────────────
# CRITICAL: TEST MODE TOGGLE
# ────────────────────────────────────────────────────────────────────────────────
# When True: Uses virtual balance, simulates trades, NO real transactions
# When False: Executes real trades on Polymarket with real money
# ALWAYS start with TEST_MODE = True until you fully understand the bot's behavior
TEST_MODE: bool = os.getenv("TEST_MODE", "true").lower() == "true"


# ────────────────────────────────────────────────────────────────────────────────
# API CREDENTIALS (loaded from .env)
# ────────────────────────────────────────────────────────────────────────────────

# Polymarket API credentials
POLYMARKET_API_KEY: Optional[str] = os.getenv("POLYMARKET_API_KEY")
POLYMARKET_API_SECRET: Optional[str] = os.getenv("POLYMARKET_API_SECRET")
POLYMARKET_PASSPHRASE: Optional[str] = os.getenv("POLYMARKET_PASSPHRASE")

# Wallet private key for signing transactions (Polygon network)
# WARNING: Never share or expose this key
WALLET_PRIVATE_KEY: Optional[str] = os.getenv("WALLET_PRIVATE_KEY")
WALLET_ADDRESS: Optional[str] = os.getenv("WALLET_ADDRESS")

# Binance API (optional - public endpoints work without auth for price data)
BINANCE_API_KEY: Optional[str] = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET: Optional[str] = os.getenv("BINANCE_API_SECRET")


# ────────────────────────────────────────────────────────────────────────────────
# VIRTUAL BALANCE FOR TEST MODE
# ────────────────────────────────────────────────────────────────────────────────
# Starting balance when running in TEST_MODE
# This simulates a $100 bankroll for paper trading
INITIAL_VIRTUAL_BALANCE: float = float(os.getenv("INITIAL_VIRTUAL_BALANCE", "100.0"))


# ────────────────────────────────────────────────────────────────────────────────
# MARKET FILTERS
# ────────────────────────────────────────────────────────────────────────────────

# Only trade markets that opened within this many seconds
# Why 180s: Fresh markets have better opportunities before odds stabilize
# 3 minutes gives enough time to catch the market after it opens
MAX_MARKET_AGE_SECONDS: int = int(os.getenv("MAX_MARKET_AGE_SECONDS", "180"))

# Minimum liquidity required in the market (in USD)
# Why: Low liquidity markets have high slippage and can't absorb our orders
MIN_LIQUIDITY_USD: float = float(os.getenv("MIN_LIQUIDITY_USD", "500.0"))

# Maximum combined bid/ask spread (Yes + No prices)
# Why: If Yes + No > 1.05, the spread is too wide, edge gets eaten by fees
# A fair market has Yes + No close to 1.00 (accounting for vig)
MAX_SPREAD_COMBINED: float = float(os.getenv("MAX_SPREAD_COMBINED", "1.05"))


# ────────────────────────────────────────────────────────────────────────────────
# SIGNAL THRESHOLDS
# ────────────────────────────────────────────────────────────────────────────────

# BTC price change threshold to detect directional bias
# Why 0.10%: Small enough to catch momentum, large enough to filter noise
# BTC up >= +0.10% in 3 min → UP bias
# BTC down <= -0.10% in 3 min → DOWN bias
BTC_BIAS_THRESHOLD_PERCENT: float = float(os.getenv("BTC_BIAS_THRESHOLD_PERCENT", "0.10"))

# Lookback period in minutes for calculating BTC price change
BTC_LOOKBACK_MINUTES: int = int(os.getenv("BTC_LOOKBACK_MINUTES", "3"))


# ────────────────────────────────────────────────────────────────────────────────
# PROBABILITY & EDGE THRESHOLDS
# ────────────────────────────────────────────────────────────────────────────────

# Fair probability estimates based on detected bias strength
# These are CONSERVATIVE estimates - we don't assume we can predict BTC perfectly
# Mild bias (0.10% - 0.20% move): 52-53% fair probability
MILD_BIAS_FAIR_PROB: float = float(os.getenv("MILD_BIAS_FAIR_PROB", "0.52"))
# Strong bias (> 0.20% move): 54-56% fair probability
STRONG_BIAS_FAIR_PROB: float = float(os.getenv("STRONG_BIAS_FAIR_PROB", "0.55"))
# Threshold to distinguish mild vs strong bias
STRONG_BIAS_THRESHOLD_PERCENT: float = float(os.getenv("STRONG_BIAS_THRESHOLD_PERCENT", "0.20"))

# Minimum edge required to enter a trade
# edge = fair_probability - market_odds
# Why 1.5-2.0%: Accounts for fees, slippage, and estimation error
MIN_EDGE_THRESHOLD: float = float(os.getenv("MIN_EDGE_THRESHOLD", "0.02"))  # 2%


# ────────────────────────────────────────────────────────────────────────────────
# BET SIZING (CONSERVATIVE)
# ────────────────────────────────────────────────────────────────────────────────

# Bet size as percentage of current balance
# Why 2-5%: Survives losing streaks (even 10 losses only = 18-40% drawdown)
BET_SIZE_PERCENT: float = float(os.getenv("BET_SIZE_PERCENT", "0.03"))  # 3% default

# Absolute minimum bet size in USD
# Why: Polymarket requires minimum 5 shares per order
# At 50 cent prices, that's $2.50 minimum. We use $3.00 for safety buffer.
MIN_BET_SIZE_USD: float = float(os.getenv("MIN_BET_SIZE_USD", "3.0"))

# Absolute maximum bet size in USD (regardless of balance)
# Why: Cap exposure on any single trade for safety
MAX_BET_SIZE_USD: float = float(os.getenv("MAX_BET_SIZE_USD", "10.0"))

# Minimum balance required to trade
# Why: Stop trading before going broke, preserve capital for recovery
MIN_BALANCE_TO_TRADE: float = float(os.getenv("MIN_BALANCE_TO_TRADE", "10.0"))


# ────────────────────────────────────────────────────────────────────────────────
# SAFETY LIMITS (LIVE MODE)
# ────────────────────────────────────────────────────────────────────────────────

# Daily loss limit as percentage of starting daily balance
# Why: Prevents catastrophic losses in a single day due to strategy failure or tilt
# Set to 0 to disable daily loss limit
DAILY_LOSS_LIMIT_PERCENT: float = float(os.getenv("DAILY_LOSS_LIMIT_PERCENT", "0.20"))  # 20%

# Daily loss limit as absolute USD amount (applies if > 0)
# Use this instead of percentage for fixed dollar limits
# Set to 0 to use percentage-based limit only
DAILY_LOSS_LIMIT_USD: float = float(os.getenv("DAILY_LOSS_LIMIT_USD", "0.0"))  # Disabled by default

# Maximum consecutive losses before pausing trading
# Why: Losing streaks may indicate strategy issues or unusual market conditions
# Set to 0 to disable
MAX_CONSECUTIVE_LOSSES: int = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "10"))

# Cooldown period after hitting loss limit (in seconds)
# During this period, no new trades will be placed
LOSS_LIMIT_COOLDOWN_SECONDS: int = int(os.getenv("LOSS_LIMIT_COOLDOWN_SECONDS", "3600"))  # 1 hour

# Maximum trades per day (set to 0 to disable)
# Why: Prevents overtrading and excessive fees
MAX_TRADES_PER_DAY: int = int(os.getenv("MAX_TRADES_PER_DAY", "100"))


# ────────────────────────────────────────────────────────────────────────────────
# TIMING & RATE LIMITS
# ────────────────────────────────────────────────────────────────────────────────

# How often to scan for new markets (in seconds)
# Why 3s: With predictive slug calculation (no page scraping), we can scan faster
SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "3"))

# Cooldown between trades (in seconds)
# Why 60s: Prevents overtrading, allows market conditions to change
TRADE_COOLDOWN_SECONDS: int = int(os.getenv("TRADE_COOLDOWN_SECONDS", "60"))

# Rate limit protection - max API calls per minute
MAX_API_CALLS_PER_MINUTE: int = int(os.getenv("MAX_API_CALLS_PER_MINUTE", "30"))


# ────────────────────────────────────────────────────────────────────────────────
# FEES & SLIPPAGE
# ────────────────────────────────────────────────────────────────────────────────

# Estimated Polymarket fee per trade (as decimal)
# Currently Polymarket has ~0% maker fee but we budget for worst case
ESTIMATED_FEE_PERCENT: float = float(os.getenv("ESTIMATED_FEE_PERCENT", "0.01"))  # 1%

# Estimated slippage on market orders
ESTIMATED_SLIPPAGE_PERCENT: float = float(os.getenv("ESTIMATED_SLIPPAGE_PERCENT", "0.005"))  # 0.5%


# ────────────────────────────────────────────────────────────────────────────────
# ORDER EXECUTION (LIVE MODE)
# ────────────────────────────────────────────────────────────────────────────────

# Maximum time to wait for an order to fill (in seconds)
# Why 60s: BTC 15-min markets are time-sensitive, can't wait forever
ORDER_FILL_TIMEOUT: int = int(os.getenv("ORDER_FILL_TIMEOUT", "60"))

# Maximum slippage allowed when placing orders (as decimal)
# Why 2%: Allow some slippage for fills, but reject if price moves too much
MAX_ORDER_SLIPPAGE: float = float(os.getenv("MAX_ORDER_SLIPPAGE", "0.02"))  # 2%

# Maximum price the bot will pay for a position (as decimal, e.g., 0.57 = 57 cents)
# Why 0.57: Prevents buying at high prices that reduce potential profit
# If the best available fill price exceeds this, the order is rejected
MAX_BUY_PRICE: float = float(os.getenv("MAX_BUY_PRICE", "0.57"))

# Maximum price drift allowed between signal detection and order execution (as decimal)
# Why 0.03: If the market moves more than 3 cents against us since we detected the signal,
# the edge we calculated is no longer valid - reject the trade
# Example: Signal at 0.45, but by execution time ask is 0.49 → reject (0.04 drift > 0.03 max)
MAX_PRICE_DRIFT: float = float(os.getenv("MAX_PRICE_DRIFT", "0.03"))  # 3 cents

# Use real-time orderbook for signal detection (not cached market prices)
# Why True: Cached prices can be seconds old, causing false edge detection
# Set to False only for testing or if API rate limits are an issue
USE_REALTIME_ORDERBOOK_FOR_SIGNALS: bool = os.getenv("USE_REALTIME_ORDERBOOK_FOR_SIGNALS", "true").lower() == "true"

# ────────────────────────────────────────────────────────────────────────────────
# PRICE SOURCE FOR EDGE CALCULATION
# ────────────────────────────────────────────────────────────────────────────────
# Determines which price data source to use for calculating trading edge.
# Options:
#   "CLOB"  - Use real-time orderbook bid/ask prices from the CLOB API
#             More accurate but requires more API calls
#             Best for live trading where precision matters
#   "GAMMA" - Use cached market prices from the Gamma API (outcomePrices)
#             Faster but prices may be several seconds stale
#             Good for testing or when API rate limits are a concern
#
# Note: This setting overrides USE_REALTIME_ORDERBOOK_FOR_SIGNALS for edge calculation
EDGE_PRICE_SOURCE: str = os.getenv("EDGE_PRICE_SOURCE", "CLOB").upper()

# Whether to cancel unfilled orders after timeout
# Why True: Don't leave stale orders that might fill unexpectedly later
CANCEL_UNFILLED_ORDERS: bool = os.getenv("CANCEL_UNFILLED_ORDERS", "true").lower() == "true"

# Interval for checking and redeeming winning positions (in seconds)
# This is a safety net to ensure no winning shares are left unredeemed
REDEMPTION_CHECK_INTERVAL: int = int(os.getenv("REDEMPTION_CHECK_INTERVAL", "300"))  # 5 minutes


# ────────────────────────────────────────────────────────────────────────────────
# LOGGING
# ────────────────────────────────────────────────────────────────────────────────

# File path for trade log CSV
TRADE_LOG_FILE: str = os.getenv("TRADE_LOG_FILE", "trades.csv")

# Enable verbose console output
VERBOSE_LOGGING: bool = os.getenv("VERBOSE_LOGGING", "true").lower() == "true"


# ────────────────────────────────────────────────────────────────────────────────
# API ENDPOINTS
# ────────────────────────────────────────────────────────────────────────────────

# Polymarket CLOB API
POLYMARKET_API_URL: str = "https://clob.polymarket.com"
POLYMARKET_GAMMA_API_URL: str = "https://gamma-api.polymarket.com"

# Binance public API (no auth needed for price data)
BINANCE_API_URL: str = "https://api.binance.com"


# ────────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ────────────────────────────────────────────────────────────────────────────────

def validate_config() -> bool:
    """
    Validate that required configuration is present.
    Returns True if config is valid, False otherwise.
    Prints warnings for missing optional config.
    """
    errors = []
    warnings = []
    
    # In TEST_MODE, we don't need real credentials
    if TEST_MODE:
        print("⚠️  Running in TEST MODE - no real trades will be executed")
        print(f"   Starting virtual balance: ${INITIAL_VIRTUAL_BALANCE:.2f}")
        return True
    
    # For LIVE mode, all credentials are required
    if not POLYMARKET_API_KEY:
        errors.append("POLYMARKET_API_KEY is required for live trading")
    if not POLYMARKET_API_SECRET:
        errors.append("POLYMARKET_API_SECRET is required for live trading")
    if not WALLET_PRIVATE_KEY:
        errors.append("WALLET_PRIVATE_KEY is required for live trading")
    if not WALLET_ADDRESS:
        errors.append("WALLET_ADDRESS is required for live trading")
    
    # Print all errors
    for error in errors:
        print(f"❌ ERROR: {error}")
    
    # Print warnings
    for warning in warnings:
        print(f"⚠️  WARNING: {warning}")
    
    if errors:
        print("\n❌ Configuration validation failed. Check your .env file.")
        return False
    
    print("✅ Configuration validated successfully for LIVE trading")
    print("⚠️  WARNING: You are about to trade with REAL MONEY")
    return True


def print_config_summary():
    """Print a summary of current configuration settings."""
    mode = "TEST" if TEST_MODE else "LIVE"
    print("\n" + "="*60)
    print(f"POLYMARKET BTC 15-MIN TRADING BOT - {mode} MODE")
    print("="*60)
    print(f"Market age limit:     {MAX_MARKET_AGE_SECONDS}s")
    print(f"Min liquidity:        ${MIN_LIQUIDITY_USD:.2f}")
    print(f"BTC bias threshold:   {BTC_BIAS_THRESHOLD_PERCENT}%")
    print(f"Min edge required:    {MIN_EDGE_THRESHOLD*100:.1f}%")
    print(f"Bet size:             {BET_SIZE_PERCENT*100:.1f}% of balance")
    print(f"Max bet:              ${MAX_BET_SIZE_USD:.2f}")
    print(f"Scan interval:        {SCAN_INTERVAL_SECONDS}s")
    print(f"Trade cooldown:       {TRADE_COOLDOWN_SECONDS}s")
    print("="*60 + "\n")
