"""
Strategy module for trade decision logic.

This module handles:
- Signal analysis and bias detection
- Fair probability estimation
- Edge calculation
- Trade filtering and validation

The strategy is deliberately CONSERVATIVE:
- We don't try to predict BTC with high accuracy
- We look for small edges with reasonable probability
- We skip trades when uncertain
"""

from typing import Optional, Tuple
from dataclasses import dataclass

import config
from market import Market, PolymarketClient
from price_feed import BinanceClient, get_btc_bias


@dataclass
class TradeSignal:
    """
    Represents a potential trade opportunity with all relevant data.
    
    Contains all information needed to decide whether to trade.
    """
    market: Market
    side: str  # "UP" or "DOWN" (which outcome to bet on)
    market_odds: float  # Current market price for our side
    fair_probability: float  # Our estimated fair probability
    edge: float  # fair_probability - market_odds
    btc_price: float  # BTC price when signal was generated
    btc_change_percent: float  # BTC % change that triggered signal
    bias_strength: str  # "MILD" or "STRONG"
    skip_reason: Optional[str] = None  # If set, trade should be skipped


def estimate_fair_probability(
    bias: str, 
    change_percent: float
) -> Tuple[float, str]:
    """
    Estimate the fair probability of a BTC Up/Down market based on current bias.
    
    This is the CORE of our strategy and is deliberately conservative.
    
    We do NOT assume we can predict BTC price movement with high accuracy.
    Instead, we estimate a slight edge based on short-term momentum.
    
    Logic:
    - Mild bias (0.10% - 0.20% move): ~52-53% fair probability
      Why: Small momentum may continue, but not a strong signal
      
    - Strong bias (> 0.20% move): ~54-56% fair probability
      Why: Stronger momentum has slightly higher continuation probability
    
    These estimates are CONSERVATIVE because:
    1. BTC is highly efficient and hard to predict
    2. 15-minute windows have significant randomness
    3. We'd rather skip trades than overestimate our edge
    
    Args:
        bias: "UP" or "DOWN"
        change_percent: The BTC percentage change that triggered the bias
    
    Returns:
        Tuple of (fair_probability, bias_strength)
    """
    abs_change = abs(change_percent)
    
    # Determine bias strength
    if abs_change >= config.STRONG_BIAS_THRESHOLD_PERCENT:
        # Strong momentum - slightly higher probability
        fair_prob = config.STRONG_BIAS_FAIR_PROB
        strength = "STRONG"
    else:
        # Mild momentum - conservative probability
        fair_prob = config.MILD_BIAS_FAIR_PROB
        strength = "MILD"
    
    # Sanity check: never estimate > 60% or < 45%
    # Higher estimates would imply prediction accuracy we don't have
    fair_prob = max(0.45, min(0.60, fair_prob))
    
    return fair_prob, strength


def calculate_edge(fair_probability: float, market_odds: float) -> float:
    """
    Calculate the edge of a trade.
    
    Edge = fair_probability - market_odds
    
    Example:
    - We estimate 53% fair probability for UP
    - Market offers UP at $0.49 (49%)
    - Edge = 0.53 - 0.49 = 0.04 (4%)
    
    Positive edge means the market is underpricing our side.
    Negative edge means we shouldn't trade.
    
    Note: This edge is BEFORE fees and slippage.
    We need sufficient edge to cover those costs.
    """
    return fair_probability - market_odds


def get_market_odds_for_side(market: Market, side: str) -> float:
    """
    Get the current market odds for a specific side using cached market prices.
    
    WARNING: This uses cached prices from when the market was fetched, which may be
    several seconds old. For execution decisions, use get_realtime_odds_for_side().
    
    Args:
        market: The market object
        side: "UP" or "DOWN"
    
    Returns:
        The market price (0.0 - 1.0) for that side
    
    Note on Polymarket Up/Down markets:
    - "Yes" typically corresponds to "Up" (price goes higher)
    - "No" typically corresponds to "Down" (price goes lower)
    - But this can vary by market question wording
    """
    # Determine which token corresponds to our side
    # This depends on how the market question is phrased
    if side == "UP":
        # For "Will BTC go up?" markets, Up = Yes
        return market.yes_price
    else:
        # For "Will BTC go up?" markets, Down = No
        # But the No price is 1 - Yes price
        # We want to buy No if we think price goes down
        return market.no_price


def get_realtime_odds_for_side(
    market: Market, 
    side: str, 
    polymarket_client: PolymarketClient
) -> tuple[float, float]:
    """
    Get REAL-TIME market odds by fetching fresh orderbook data.
    
    This should be used for actual trading decisions to avoid using stale prices.
    The cached market.yes_price/no_price can be several seconds old.
    
    Args:
        market: The market object
        side: "UP" or "DOWN"
        polymarket_client: Client to fetch orderbook
    
    Returns:
        Tuple of (best_bid, best_ask) for the side, or (0, 0) if unavailable
    """
    side_normalized = "up" if side == "UP" else "down"
    
    prices = polymarket_client.get_best_prices(market, side_normalized)
    
    if prices is None or prices.get("is_fallback", True):
        # Fall back to cached prices if orderbook unavailable
        cached_price = get_market_odds_for_side(market, side)
        return (cached_price, cached_price)
    
    return (prices.get("bid", 0), prices.get("ask", 0))


def get_price_for_edge_calculation(
    market: Market,
    side: str,
    polymarket_client: PolymarketClient
) -> tuple[float, str]:
    """
    Get the market price to use for edge calculation based on configured price source.
    
    This function allows switching between two price data sources:
    - CLOB: Real-time orderbook prices (more accurate, more API calls)
    - GAMMA: Cached market prices from Gamma API (faster, may be stale)
    
    The price source is configured via EDGE_PRICE_SOURCE in .env
    
    Args:
        market: The market object
        side: "UP" or "DOWN"
        polymarket_client: Client to fetch orderbook (used only for CLOB source)
    
    Returns:
        Tuple of (price, source_used) where:
        - price: The market odds for the specified side (0.0 - 1.0)
        - source_used: String indicating which source was used ("CLOB" or "GAMMA")
    """
    price_source = getattr(config, 'EDGE_PRICE_SOURCE', 'CLOB').upper()
    
    if price_source == "CLOB":
        # Use real-time orderbook prices
        best_bid, best_ask = get_realtime_odds_for_side(market, side, polymarket_client)
        
        # For buying, we care about the ASK price (what we'll actually pay)
        # Using bid would give us a false lower price
        market_odds = best_ask if best_ask > 0 else best_bid
        
        if config.VERBOSE_LOGGING and best_ask > 0:
            cached_price = get_market_odds_for_side(market, side)
            if abs(market_odds - cached_price) > 0.01:
                print(f"📊 CLOB vs Gamma price: {market_odds:.3f} vs {cached_price:.3f} (diff: {(market_odds - cached_price)*100:.1f}¢)")
        
        return (market_odds, "CLOB")
    
    elif price_source == "GAMMA":
        # Use cached prices from Gamma API
        market_odds = get_market_odds_for_side(market, side)
        
        if config.VERBOSE_LOGGING:
            print(f"📊 Using Gamma API price: {market_odds:.3f}")
        
        return (market_odds, "GAMMA")
    
    else:
        # Invalid source - fall back to CLOB with warning
        print(f"⚠️ Invalid EDGE_PRICE_SOURCE '{price_source}', defaulting to CLOB")
        best_bid, best_ask = get_realtime_odds_for_side(market, side, polymarket_client)
        market_odds = best_ask if best_ask > 0 else best_bid
        return (market_odds, "CLOB")


def analyze_trade_opportunity(
    market: Market,
    polymarket_client: PolymarketClient,
    binance_client: BinanceClient
) -> TradeSignal:
    """
    Analyze a market to determine if there's a valid trade opportunity.
    
    This function runs ALL trade filters and returns a TradeSignal.
    If any filter fails, the signal will have a skip_reason set.
    
    Filter order (fail-fast):
    1. Market freshness (age <= 60 seconds)
    2. Already traded check
    3. Liquidity check
    4. Spread check
    5. BTC bias detection
    6. Fair probability estimation
    7. Edge calculation
    8. Minimum edge check
    
    Args:
        market: The market to analyze
        polymarket_client: Polymarket API client
        binance_client: Binance API client
    
    Returns:
        TradeSignal object with all relevant data
    """
    # Initialize with placeholder values
    signal = TradeSignal(
        market=market,
        side="",
        market_odds=0.0,
        fair_probability=0.0,
        edge=0.0,
        btc_price=0.0,
        btc_change_percent=0.0,
        bias_strength="",
        skip_reason=None
    )
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 1: Market Freshness
    # ─────────────────────────────────────────────────────────────────────────
    if not polymarket_client.is_market_fresh(market):
        age = polymarket_client.get_market_age_seconds(market)
        signal.skip_reason = f"Market too old ({age:.0f}s > {config.MAX_MARKET_AGE_SECONDS}s)"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 2: Already Traded
    # ─────────────────────────────────────────────────────────────────────────
    if polymarket_client.was_already_traded(market):
        signal.skip_reason = "Already traded this market"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 3: Liquidity Check
    # ─────────────────────────────────────────────────────────────────────────
    if not polymarket_client.has_sufficient_liquidity(market):
        signal.skip_reason = f"Insufficient liquidity (${market.liquidity:.2f} < ${config.MIN_LIQUIDITY_USD:.2f})"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 4: Spread Check
    # ─────────────────────────────────────────────────────────────────────────
    if not polymarket_client.has_reasonable_spread(market):
        combined = market.yes_price + market.no_price
        signal.skip_reason = f"Spread too wide ({combined:.3f} > {config.MAX_SPREAD_COMBINED})"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 5: BTC Bias Detection
    # ─────────────────────────────────────────────────────────────────────────
    bias, change_percent, btc_price = get_btc_bias()
    
    if btc_price:
        signal.btc_price = btc_price
    if change_percent is not None:
        signal.btc_change_percent = change_percent
    
    if bias is None:
        if change_percent is None:
            signal.skip_reason = "Could not calculate BTC price change"
        else:
            signal.skip_reason = f"No clear BTC bias (change: {change_percent:.3f}% within ±{config.BTC_BIAS_THRESHOLD_PERCENT}%)"
        return signal
    
    signal.side = bias  # "UP" or "DOWN"
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 6: Fair Probability Estimation
    # ─────────────────────────────────────────────────────────────────────────
    fair_prob, strength = estimate_fair_probability(bias, change_percent)
    signal.fair_probability = fair_prob
    signal.bias_strength = strength
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 7: Get Market Odds for Edge Calculation
    # ─────────────────────────────────────────────────────────────────────────
    # The price source is configurable via EDGE_PRICE_SOURCE in .env:
    # - "CLOB": Real-time orderbook prices (recommended for live trading)
    # - "GAMMA": Cached market prices (faster, but may be stale)
    
    market_odds, price_source = get_price_for_edge_calculation(market, bias, polymarket_client)
    
    signal.market_odds = market_odds
    
    if market_odds <= 0 or market_odds >= 1:
        signal.skip_reason = f"Invalid market odds: {market_odds}"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 7.5: CRITICAL - Only bet when we can buy CHEAP (market_odds < fair_prob)
    # ─────────────────────────────────────────────────────────────────────────
    # We want to BUY when the market is pricing the outcome LOWER than our fair value.
    # Example: If we think UP has 55% fair probability, we should only buy if market price < 55%
    #          Buying at 77% means we're OVERPAYING (negative edge!)
    if market_odds >= fair_prob:
        signal.skip_reason = (
            f"Market price too high: {market_odds*100:.1f}% >= fair {fair_prob*100:.1f}% "
            f"(need to buy BELOW fair value)"
        )
        return signal
    
    # ─────────────────────────────────────────────────────────────────────────
    # FILTER 8: Edge Calculation & Minimum Edge Check
    # ─────────────────────────────────────────────────────────────────────────
    edge = calculate_edge(fair_prob, market_odds)
    signal.edge = edge
    
    # Account for fees and slippage
    net_edge = edge - config.ESTIMATED_FEE_PERCENT - config.ESTIMATED_SLIPPAGE_PERCENT
    
    if net_edge < config.MIN_EDGE_THRESHOLD:
        signal.skip_reason = (
            f"Insufficient edge: {edge*100:.2f}% gross, {net_edge*100:.2f}% net "
            f"(need {config.MIN_EDGE_THRESHOLD*100:.1f}%)"
        )
        return signal
    
    # ─────────────────────────────────────────────────────────────────────────
    # ALL FILTERS PASSED - Valid trade opportunity
    # ─────────────────────────────────────────────────────────────────────────
    if config.VERBOSE_LOGGING:
        print(f"✅ Trade signal: {bias} | Odds: {market_odds:.3f} | "
              f"Fair: {fair_prob:.3f} | Edge: {edge*100:.2f}%")
    
    return signal


def should_trade(signal: TradeSignal) -> bool:
    """
    Simple helper to check if a signal is tradeable.
    
    Returns True if no skip_reason is set.
    """
    return signal.skip_reason is None


def calculate_bet_size(current_balance: float) -> float:
    """
    Calculate the appropriate bet size based on current balance.
    
    Uses Kelly-inspired fractional betting with hard caps.
    
    Rules:
    1. Bet a fixed percentage of current balance (default 3%)
    2. Never bet less than MIN_BET_SIZE_USD
    3. Never bet more than MAX_BET_SIZE_USD
    4. Never bet if balance < MIN_BALANCE_TO_TRADE
    
    This ensures survival through losing streaks.
    
    With 3% bet sizing:
    - 10 consecutive losses = 26% drawdown
    - 20 consecutive losses = 46% drawdown
    - Still have capital to recover
    
    Args:
        current_balance: Current account balance in USD
    
    Returns:
        Bet size in USD, or 0 if should not bet
    """
    # Check minimum balance
    if current_balance < config.MIN_BALANCE_TO_TRADE:
        if config.VERBOSE_LOGGING:
            print(f"⚠️ Balance ${current_balance:.2f} below minimum ${config.MIN_BALANCE_TO_TRADE:.2f}")
        return 0.0
    
    # Calculate percentage-based bet
    bet = current_balance * config.BET_SIZE_PERCENT
    
    # Apply minimum
    if bet < config.MIN_BET_SIZE_USD:
        bet = config.MIN_BET_SIZE_USD
    
    # Apply maximum cap
    if bet > config.MAX_BET_SIZE_USD:
        bet = config.MAX_BET_SIZE_USD
    
    # Final sanity check: don't bet more than available
    if bet > current_balance:
        bet = current_balance * 0.5  # Emergency cap at 50%
    
    return round(bet, 2)


def format_skip_reason(signal: TradeSignal) -> str:
    """Format a skip reason for logging."""
    if signal.skip_reason:
        return f"⏭️ SKIP: {signal.skip_reason}"
    return "✅ TRADE: All filters passed"
