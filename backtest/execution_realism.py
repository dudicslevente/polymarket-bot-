"""
Execution Realism Module for Backtesting.

This module provides realistic trade execution modeling:
- Latency-based pricing (use price at T + latency, not T)
- Adverse slippage (price moves against you)
- Liquidity-capped bet sizing
- Outlier filtering (skip "too good to be true" trades)

These features make backtests more conservative and realistic,
avoiding over-optimistic results that won't replicate in live trading.
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


# ─────────────────────────────────────────────────────────────────────────────
# REALISM CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExecutionRealismConfig:
    """
    Configuration for realistic execution modeling.
    
    All features are enabled by default with conservative settings.
    Set enable_* to False to disable specific features.
    """
    
    # ─────────────────────────────────────────────────────────────────────
    # LATENCY MODELING
    # ─────────────────────────────────────────────────────────────────────
    enable_latency: bool = True
    
    # Latency in seconds from interval start to order fill
    # Accounts for: signal computation, network, order matching
    latency_seconds: float = 8.0  # Conservative: 8 seconds
    
    # If True, skip trade if no price available at T + latency
    require_price_at_latency: bool = False  # False = use last known price
    
    # ─────────────────────────────────────────────────────────────────────
    # ADVERSE SLIPPAGE
    # ─────────────────────────────────────────────────────────────────────
    enable_slippage: bool = True
    
    # Fixed slippage in absolute probability points
    # E.g., 0.01 means if YES is 0.45, you pay 0.46
    slippage_fixed: float = 0.008  # 0.8% absolute slippage
    
    # Proportional slippage as fraction of edge
    # E.g., 0.1 means you lose 10% of your edge to slippage
    slippage_proportional: float = 0.15  # 15% of edge lost to slippage
    
    # Use the worse of fixed or proportional (True) or sum them (False)
    slippage_use_max: bool = True
    
    # ─────────────────────────────────────────────────────────────────────
    # LIQUIDITY CONSTRAINTS
    # ─────────────────────────────────────────────────────────────────────
    enable_liquidity_cap: bool = True
    
    # Maximum bet as fraction of market liquidity
    max_bet_liquidity_fraction: float = 0.05  # Max 5% of liquidity
    
    # Maximum bet as fraction of interval volume (if available)
    max_bet_volume_fraction: float = 0.10  # Max 10% of volume
    
    # Minimum liquidity to trade (in USD)
    min_liquidity_usd: float = 500.0
    
    # Minimum volume to trade (in USD, 0 = ignore volume)
    min_volume_usd: float = 0.0  # Don't require volume data
    
    # ─────────────────────────────────────────────────────────────────────
    # OUTLIER FILTERING
    # ─────────────────────────────────────────────────────────────────────
    enable_outlier_filter: bool = True
    
    # Reject trades with extreme odds (likely illiquid/stale)
    min_allowed_odds: float = 0.03  # Reject YES < 3% or NO < 3%
    max_allowed_odds: float = 0.97  # Reject YES > 97% or NO > 97%
    
    # Reject trades with suspiciously high edge
    max_allowed_edge: float = 0.25  # Reject edge > 25%
    
    # Reject trades where edge is too high relative to liquidity
    # (edge > threshold AND liquidity < limit → reject)
    high_edge_low_liquidity_threshold: float = 0.15  # 15% edge
    high_edge_min_liquidity: float = 2000.0  # $2000 liquidity required
    
    # ─────────────────────────────────────────────────────────────────────
    # TRADE CADENCE
    # ─────────────────────────────────────────────────────────────────────
    # Max one trade per interval is enforced at backtest level,
    # but we can add extra cadence constraints here
    
    # Minimum seconds between trades (across all markets)
    min_seconds_between_trades: float = 60.0  # 1 minute
    
    def __post_init__(self):
        """Validate configuration."""
        if self.min_allowed_odds >= self.max_allowed_odds:
            raise ValueError("min_allowed_odds must be < max_allowed_odds")
        if self.latency_seconds < 0:
            raise ValueError("latency_seconds must be >= 0")


# Default conservative config
DEFAULT_REALISM_CONFIG = ExecutionRealismConfig()


# ─────────────────────────────────────────────────────────────────────────────
# REALISM FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def apply_latency_to_odds(
    base_odds: float,
    side: str,
    latency_seconds: float,
    price_volatility: float = 0.002
) -> float:
    """
    Adjust odds to account for execution latency.
    
    During the latency period, prices tend to move against you
    (market makers react to order flow, prices drift toward fair value).
    
    Args:
        base_odds: The odds at interval start
        side: "UP" (buying YES) or "DOWN" (buying NO)
        latency_seconds: Seconds of latency
        price_volatility: Expected price movement per second
    
    Returns:
        Adjusted odds (worse for the trader)
    """
    if latency_seconds <= 0:
        return base_odds
    
    # Price drift during latency (against you)
    # More latency = more drift
    drift_factor = latency_seconds * price_volatility * 0.1
    
    # Drift makes your fill price worse
    if side == "UP":
        # Buying YES: price drifts up (you pay more)
        adjusted = base_odds + drift_factor
    else:
        # Buying NO: YES price drifts down = NO price drifts up (you pay more for NO)
        adjusted = base_odds + drift_factor
    
    # Clamp to valid range
    return max(0.01, min(0.99, adjusted))


def apply_adverse_slippage(
    base_odds: float,
    side: str,
    edge: float,
    config: ExecutionRealismConfig
) -> float:
    """
    Apply adverse slippage to entry odds.
    
    Slippage makes your fill price worse than the quoted price.
    
    Args:
        base_odds: The quoted odds
        side: "UP" (buying YES) or "DOWN" (buying NO)
        edge: The calculated edge for this trade
        config: Realism configuration
    
    Returns:
        Adjusted odds (worse for the trader)
    """
    if not config.enable_slippage:
        return base_odds
    
    # Calculate slippage amount
    fixed_slip = config.slippage_fixed
    prop_slip = abs(edge) * config.slippage_proportional
    
    if config.slippage_use_max:
        slippage = max(fixed_slip, prop_slip)
    else:
        slippage = fixed_slip + prop_slip
    
    # Apply slippage (always makes price worse for trader)
    # When buying YES or NO, you pay more
    adjusted = base_odds + slippage
    
    # Clamp to valid range
    return max(0.01, min(0.99, adjusted))


def cap_bet_size_by_liquidity(
    desired_bet: float,
    liquidity: float,
    volume: float,
    config: ExecutionRealismConfig
) -> Tuple[float, Optional[str]]:
    """
    Cap bet size based on market liquidity and volume.
    
    Args:
        desired_bet: The bet size we want to place
        liquidity: Market liquidity in USD
        volume: Market volume in USD (0 if unknown)
        config: Realism configuration
    
    Returns:
        Tuple of (capped_bet_size, skip_reason or None)
    """
    if not config.enable_liquidity_cap:
        return desired_bet, None
    
    # Check minimum liquidity
    if liquidity < config.min_liquidity_usd:
        return 0.0, f"Liquidity ${liquidity:.0f} < min ${config.min_liquidity_usd:.0f}"
    
    # Check minimum volume (if required)
    if config.min_volume_usd > 0 and volume < config.min_volume_usd:
        return 0.0, f"Volume ${volume:.0f} < min ${config.min_volume_usd:.0f}"
    
    # Cap by liquidity
    max_by_liquidity = liquidity * config.max_bet_liquidity_fraction
    
    # Cap by volume (if available)
    if volume > 0:
        max_by_volume = volume * config.max_bet_volume_fraction
        max_allowed = min(max_by_liquidity, max_by_volume)
    else:
        max_allowed = max_by_liquidity
    
    # Apply cap
    if desired_bet > max_allowed:
        return max_allowed, None
    
    return desired_bet, None


def filter_outlier_trade(
    odds: float,
    edge: float,
    liquidity: float,
    config: ExecutionRealismConfig
) -> Optional[str]:
    """
    Check if a trade should be filtered as an outlier.
    
    Args:
        odds: Entry odds
        edge: Calculated edge
        liquidity: Market liquidity
        config: Realism configuration
    
    Returns:
        Skip reason if trade should be filtered, None otherwise
    """
    if not config.enable_outlier_filter:
        return None
    
    # Check extreme odds
    if odds < config.min_allowed_odds:
        return f"Odds {odds:.3f} < min {config.min_allowed_odds:.3f} (likely illiquid)"
    
    if odds > config.max_allowed_odds:
        return f"Odds {odds:.3f} > max {config.max_allowed_odds:.3f} (likely illiquid)"
    
    # Check suspiciously high edge
    if edge > config.max_allowed_edge:
        return f"Edge {edge*100:.1f}% > max {config.max_allowed_edge*100:.1f}% (unrealistic)"
    
    # Check high edge with low liquidity
    if edge > config.high_edge_low_liquidity_threshold:
        if liquidity < config.high_edge_min_liquidity:
            return (
                f"High edge {edge*100:.1f}% with low liquidity ${liquidity:.0f} "
                f"(need ${config.high_edge_min_liquidity:.0f})"
            )
    
    return None


def apply_all_realism_adjustments(
    base_odds: float,
    side: str,
    edge: float,
    desired_bet: float,
    liquidity: float,
    volume: float,
    config: ExecutionRealismConfig = None
) -> Tuple[float, float, Optional[str]]:
    """
    Apply all realism adjustments to a potential trade.
    
    This is the main entry point for execution realism.
    
    Args:
        base_odds: Original entry odds
        side: "UP" or "DOWN"
        edge: Calculated edge (before adjustments)
        desired_bet: Desired bet size
        liquidity: Market liquidity
        volume: Market volume
        config: Realism config (uses default if None)
    
    Returns:
        Tuple of (adjusted_odds, adjusted_bet_size, skip_reason or None)
    """
    if config is None:
        config = DEFAULT_REALISM_CONFIG
    
    # Step 1: Check outliers first (before any adjustments)
    skip = filter_outlier_trade(base_odds, edge, liquidity, config)
    if skip:
        return base_odds, 0.0, skip
    
    # Step 2: Apply latency
    if config.enable_latency:
        adjusted_odds = apply_latency_to_odds(
            base_odds, side, config.latency_seconds
        )
    else:
        adjusted_odds = base_odds
    
    # Step 3: Apply slippage
    adjusted_odds = apply_adverse_slippage(adjusted_odds, side, edge, config)
    
    # Step 4: Recalculate edge with adjusted odds (for logging/validation)
    # Note: This doesn't change the trade decision, just for info
    
    # Step 5: Cap bet size by liquidity
    capped_bet, skip = cap_bet_size_by_liquidity(
        desired_bet, liquidity, volume, config
    )
    if skip:
        return adjusted_odds, 0.0, skip
    
    return adjusted_odds, capped_bet, None


# ─────────────────────────────────────────────────────────────────────────────
# OUTCOME RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def determine_trade_outcome_realistic(
    side: str,
    resolved_outcome: str,
    entry_odds: float,
    bet_size: float,
    fee_percent: float = None
) -> Tuple[str, float, float]:
    """
    Determine trade outcome using REAL market resolution.
    
    Unlike simulate_trade_outcome which uses BTC price movement,
    this uses the actual Polymarket market resolution.
    
    Args:
        side: "UP" or "DOWN" (what we bet on)
        resolved_outcome: Actual market resolution ("UP", "DOWN", or "UNKNOWN")
        entry_odds: The odds at which we entered (after slippage)
        bet_size: Amount bet
        fee_percent: Fee to deduct from winnings
    
    Returns:
        Tuple of (outcome, payout, profit_loss)
    """
    fee_percent = fee_percent if fee_percent is not None else config.ESTIMATED_FEE_PERCENT
    
    # Handle unknown resolution
    if resolved_outcome not in ("UP", "DOWN"):
        # Market didn't resolve clearly - assume loss (conservative)
        return "UNKNOWN", 0.0, -bet_size
    
    # Determine if we won
    won = (side == resolved_outcome)
    
    if won:
        # Payout = bet_size / odds (we get $1 per share, shares = bet/odds)
        payout = bet_size / entry_odds
        payout *= (1 - fee_percent)  # Apply fee
        profit_loss = payout - bet_size
        return "WIN", payout, profit_loss
    else:
        return "LOSS", 0.0, -bet_size


# ─────────────────────────────────────────────────────────────────────────────
# STATISTICS AND REPORTING
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RealismStats:
    """Statistics about realism adjustments applied during backtest."""
    
    total_trades_considered: int = 0
    
    # Outlier filtering
    filtered_extreme_odds: int = 0
    filtered_high_edge: int = 0
    filtered_high_edge_low_liquidity: int = 0
    filtered_low_liquidity: int = 0
    filtered_low_volume: int = 0
    
    # Adjustments
    trades_with_latency_adjustment: int = 0
    trades_with_slippage: int = 0
    trades_with_bet_cap: int = 0
    
    # Impact
    total_odds_adjustment: float = 0.0  # Sum of (adjusted - base)
    total_bet_reduction: float = 0.0  # Sum of (desired - capped)
    
    def filtered_total(self) -> int:
        return (
            self.filtered_extreme_odds +
            self.filtered_high_edge +
            self.filtered_high_edge_low_liquidity +
            self.filtered_low_liquidity +
            self.filtered_low_volume
        )
    
    def print_summary(self):
        """Print a summary of realism adjustments."""
        print("\n" + "="*60)
        print("📊 EXECUTION REALISM SUMMARY")
        print("="*60)
        print(f"Trades considered:        {self.total_trades_considered}")
        print(f"Trades filtered:          {self.filtered_total()}")
        print("-"*60)
        print("Filtered breakdown:")
        print(f"  - Extreme odds:         {self.filtered_extreme_odds}")
        print(f"  - High edge:            {self.filtered_high_edge}")
        print(f"  - High edge + low liq:  {self.filtered_high_edge_low_liquidity}")
        print(f"  - Low liquidity:        {self.filtered_low_liquidity}")
        print(f"  - Low volume:           {self.filtered_low_volume}")
        print("-"*60)
        print("Adjustments applied:")
        print(f"  - Latency adjusted:     {self.trades_with_latency_adjustment}")
        print(f"  - Slippage applied:     {self.trades_with_slippage}")
        print(f"  - Bet size capped:      {self.trades_with_bet_cap}")
        print("-"*60)
        if self.trades_with_slippage > 0:
            avg_slip = self.total_odds_adjustment / self.trades_with_slippage
            print(f"Avg odds adjustment:      +{avg_slip*100:.2f}% (against you)")
        if self.trades_with_bet_cap > 0:
            avg_cap = self.total_bet_reduction / self.trades_with_bet_cap
            print(f"Avg bet reduction:        ${avg_cap:.2f}")
        print("="*60 + "\n")
