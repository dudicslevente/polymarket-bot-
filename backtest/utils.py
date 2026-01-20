"""
Utility functions for backtesting.

This module provides:
- Timestamp alignment functions
- Bet sizing calculations
- Drawdown calculations
- Logging helpers for backtest results

All functions are designed to work with the live bot's data structures.
"""

import csv
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


# ─────────────────────────────────────────────────────────────────────────────
# TIMESTAMP UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def align_timestamp_to_interval(
    timestamp: datetime, 
    interval_minutes: int = 15
) -> datetime:
    """
    Align a timestamp to the start of a 15-minute interval.
    
    Examples:
        10:07:23 → 10:00:00
        10:22:45 → 10:15:00
        10:31:00 → 10:30:00
    
    Args:
        timestamp: The timestamp to align
        interval_minutes: The interval size (default 15)
    
    Returns:
        The aligned timestamp at the start of the interval
    """
    # Ensure timezone-aware
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    
    # Calculate minutes since midnight
    minutes_since_midnight = timestamp.hour * 60 + timestamp.minute
    
    # Find the interval start
    interval_start_minutes = (minutes_since_midnight // interval_minutes) * interval_minutes
    
    # Create aligned timestamp
    aligned = timestamp.replace(
        hour=interval_start_minutes // 60,
        minute=interval_start_minutes % 60,
        second=0,
        microsecond=0
    )
    
    return aligned


def parse_timestamp(
    timestamp_str: str, 
    format_hint: Optional[str] = None
) -> Optional[datetime]:
    """
    Parse a timestamp string into a datetime object.
    
    Supports multiple common formats:
    - ISO 8601: 2024-01-15T10:30:00Z
    - Binance: 1705315800000 (milliseconds)
    - CSV: 2024-01-15 10:30:00
    
    Args:
        timestamp_str: The timestamp string to parse
        format_hint: Optional format string
    
    Returns:
        datetime object or None if parsing fails
    """
    if format_hint:
        try:
            dt = datetime.strptime(timestamp_str, format_hint)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    
    # Try common formats
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    
    # Clean up timezone suffix for parsing
    clean_str = timestamp_str.strip()
    if clean_str.endswith('+00:00'):
        clean_str = clean_str[:-6] + 'Z'  # Convert +00:00 to Z
    elif clean_str.endswith('-00:00'):
        clean_str = clean_str[:-6] + 'Z'
    
    # Check if it's a Unix timestamp (milliseconds)
    if clean_str.isdigit():
        try:
            ts = int(clean_str)
            # If > 10 billion, it's milliseconds
            if ts > 10_000_000_000:
                ts = ts / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            pass
    
    # Try each format
    for fmt in formats:
        try:
            dt = datetime.strptime(clean_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    
    # Try ISO format with fromisoformat (handles various timezone formats)
    try:
        # fromisoformat can handle +00:00 directly
        dt = datetime.fromisoformat(timestamp_str.strip().replace('Z', '+00:00'))
        return dt
    except (ValueError, TypeError):
        pass
    
    return None


def timestamp_to_ms(dt: datetime) -> int:
    """Convert a datetime to Unix timestamp in milliseconds."""
    return int(dt.timestamp() * 1000)


def ms_to_timestamp(ms: int) -> datetime:
    """Convert Unix timestamp in milliseconds to datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# BET SIZING
# ─────────────────────────────────────────────────────────────────────────────

def calculate_bet_size_backtest(
    current_balance: float,
    bet_percent: float = None,
    min_bet: float = None,
    max_bet: float = None,
    min_balance: float = None
) -> float:
    """
    Calculate bet size for backtesting.
    
    Uses the same logic as the live bot but allows parameter overrides.
    
    Args:
        current_balance: Current simulated balance
        bet_percent: Override for BET_SIZE_PERCENT (default from config)
        min_bet: Override for MIN_BET_SIZE_USD
        max_bet: Override for MAX_BET_SIZE_USD
        min_balance: Override for MIN_BALANCE_TO_TRADE
    
    Returns:
        Calculated bet size, or 0 if shouldn't bet
    """
    # Use config defaults if not overridden
    bet_percent = bet_percent if bet_percent is not None else config.BET_SIZE_PERCENT
    min_bet = min_bet if min_bet is not None else config.MIN_BET_SIZE_USD
    max_bet = max_bet if max_bet is not None else config.MAX_BET_SIZE_USD
    min_balance = min_balance if min_balance is not None else config.MIN_BALANCE_TO_TRADE
    
    # Check minimum balance
    if current_balance < min_balance:
        return 0.0
    
    # Calculate percentage-based bet
    bet = current_balance * bet_percent
    
    # Apply minimum
    if bet < min_bet:
        bet = min_bet
    
    # Apply maximum cap
    if bet > max_bet:
        bet = max_bet
    
    # Don't bet more than available
    if bet > current_balance:
        bet = current_balance * 0.5
    
    return round(bet, 2)


# ─────────────────────────────────────────────────────────────────────────────
# DRAWDOWN CALCULATIONS
# ─────────────────────────────────────────────────────────────────────────────

def calculate_drawdown(equity_curve: List[float]) -> Tuple[float, float, int]:
    """
    Calculate maximum drawdown from an equity curve.
    
    Args:
        equity_curve: List of balance values over time
    
    Returns:
        Tuple of:
        - max_drawdown: Maximum drawdown as a decimal (0.15 = 15%)
        - max_drawdown_dollar: Maximum drawdown in dollars
        - max_drawdown_duration: Duration in periods
    """
    if not equity_curve or len(equity_curve) < 2:
        return 0.0, 0.0, 0
    
    peak = equity_curve[0]
    max_dd_pct = 0.0
    max_dd_dollar = 0.0
    
    current_dd_start = 0
    max_dd_duration = 0
    current_duration = 0
    
    for i, balance in enumerate(equity_curve):
        if balance > peak:
            peak = balance
            current_dd_start = i
            current_duration = 0
        else:
            current_duration = i - current_dd_start
            
            # Calculate drawdown
            dd_dollar = peak - balance
            dd_pct = dd_dollar / peak if peak > 0 else 0
            
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_dollar = dd_dollar
                max_dd_duration = current_duration
    
    return max_dd_pct, max_dd_dollar, max_dd_duration


def calculate_sharpe_ratio(
    returns: List[float], 
    risk_free_rate: float = 0.0,
    periods_per_year: int = 35040  # 15-min intervals
) -> float:
    """
    Calculate the Sharpe ratio of returns.
    
    Args:
        returns: List of period returns (as decimals)
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of trading periods per year
    
    Returns:
        Annualized Sharpe ratio
    """
    if not returns or len(returns) < 2:
        return 0.0
    
    import statistics
    
    mean_return = statistics.mean(returns)
    std_return = statistics.stdev(returns)
    
    if std_return == 0:
        return 0.0
    
    # Annualize
    annualized_return = mean_return * periods_per_year
    annualized_std = std_return * (periods_per_year ** 0.5)
    
    sharpe = (annualized_return - risk_free_rate) / annualized_std
    
    return sharpe


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST TRADE FORMATTING
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestTrade:
    """Represents a single backtest trade with all tracking data."""
    trade_id: str
    interval_start: datetime
    entry_time: datetime
    seconds_into_interval: int
    market_id: str
    side: str  # "UP" or "DOWN"
    entry_odds: float
    fair_probability: float
    edge: float
    btc_price_at_entry: float
    btc_price_at_close: float
    bet_size: float
    balance_before: float
    balance_after: float
    outcome: str  # "WIN" or "LOSS"
    payout: float
    profit_loss: float
    resolved_outcome: str  # Actual market outcome from data
    mode: str = "BACKTEST"


def format_backtest_trade(trade: BacktestTrade) -> str:
    """
    Format a backtest trade for console output.
    
    Args:
        trade: The BacktestTrade to format
    
    Returns:
        Human-readable string
    """
    outcome_emoji = "🎉" if trade.outcome == "WIN" else "😞"
    
    return (
        f"{outcome_emoji} [{trade.interval_start.strftime('%Y-%m-%d %H:%M')}] "
        f"{trade.side} @ {trade.entry_odds:.3f} | "
        f"Edge: {trade.edge*100:.2f}% | "
        f"Bet: ${trade.bet_size:.2f} | "
        f"P/L: ${trade.profit_loss:+.2f} | "
        f"Balance: ${trade.balance_after:.2f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST LOGGING
# ─────────────────────────────────────────────────────────────────────────────

BACKTEST_LOG_COLUMNS = [
    "interval_start",
    "trade_id",
    "market_id",
    "side",
    "entry_odds",
    "fair_probability",
    "edge",
    "btc_price_entry",
    "btc_price_close",
    "bet_size",
    "balance_before",
    "balance_after",
    "outcome",
    "payout",
    "profit_loss",
    "resolved_outcome",
    "mode"
]


class BacktestLogger:
    """
    Logger for backtest results.
    
    Writes trades to a CSV file in a format compatible with the live bot logs.
    """
    
    def __init__(self, log_file: str = "backtest_results.csv"):
        self.log_file = log_file
        self.trades: List[BacktestTrade] = []
        self._initialized = False
    
    def _ensure_file_exists(self):
        """Create the log file with headers if needed."""
        if not self._initialized:
            # Create/truncate the file with headers
            with open(self.log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(BACKTEST_LOG_COLUMNS)
            self._initialized = True
    
    def log_trade(self, trade: BacktestTrade):
        """Log a single trade to CSV."""
        self._ensure_file_exists()
        
        row = [
            trade.interval_start.isoformat(),
            trade.trade_id,
            trade.market_id,
            trade.side,
            f"{trade.entry_odds:.4f}",
            f"{trade.fair_probability:.4f}",
            f"{trade.edge:.4f}",
            f"{trade.btc_price_at_entry:.2f}",
            f"{trade.btc_price_at_close:.2f}",
            f"{trade.bet_size:.2f}",
            f"{trade.balance_before:.2f}",
            f"{trade.balance_after:.2f}",
            trade.outcome,
            f"{trade.payout:.2f}",
            f"{trade.profit_loss:.2f}",
            trade.resolved_outcome,
            trade.mode
        ]
        
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(row)
        
        self.trades.append(trade)
    
    def log_skip(
        self, 
        interval_start: datetime, 
        reason: str, 
        details: Optional[Dict] = None
    ):
        """Log a skipped interval (optional, for debugging)."""
        # Can be extended to write to a separate skip log
        pass
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Generate summary statistics from logged trades.
        
        Returns:
            Dictionary with performance metrics
        """
        if not self.trades:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl_per_trade": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "avg_edge": 0.0,
                "max_drawdown": 0.0
            }
        
        wins = sum(1 for t in self.trades if t.outcome == "WIN")
        losses = sum(1 for t in self.trades if t.outcome == "LOSS")
        total = len(self.trades)
        
        pnls = [t.profit_loss for t in self.trades]
        edges = [t.edge for t in self.trades]
        
        # Build equity curve
        equity_curve = [self.trades[0].balance_before]
        for t in self.trades:
            equity_curve.append(t.balance_after)
        
        max_dd, max_dd_dollar, _ = calculate_drawdown(equity_curve)
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / total * 100) if total > 0 else 0.0,
            "total_pnl": sum(pnls),
            "avg_pnl_per_trade": sum(pnls) / total if total > 0 else 0.0,
            "best_trade": max(pnls) if pnls else 0.0,
            "worst_trade": min(pnls) if pnls else 0.0,
            "avg_edge": (sum(edges) / len(edges) * 100) if edges else 0.0,
            "max_drawdown": max_dd * 100,
            "max_drawdown_dollar": max_dd_dollar,
            "final_balance": self.trades[-1].balance_after if self.trades else 0.0,
            "starting_balance": self.trades[0].balance_before if self.trades else 0.0
        }
    
    def print_summary(self):
        """Print a formatted summary to console."""
        stats = self.get_summary()
        
        if stats["total_trades"] == 0:
            print("\n⚠️ No trades to summarize.")
            return
        
        pnl = stats["total_pnl"]
        pnl_symbol = "+" if pnl >= 0 else ""
        pnl_pct = (stats["final_balance"] / stats["starting_balance"] - 1) * 100 if stats["starting_balance"] > 0 else 0
        
        print("\n" + "="*60)
        print("📊 BACKTEST RESULTS SUMMARY")
        print("="*60)
        print(f"Starting Balance:     ${stats['starting_balance']:.2f}")
        print(f"Final Balance:        ${stats['final_balance']:.2f}")
        print(f"Total P&L:            {pnl_symbol}${pnl:.2f} ({pnl_symbol}{pnl_pct:.1f}%)")
        print("-"*60)
        print(f"Total Trades:         {stats['total_trades']}")
        print(f"Wins:                 {stats['wins']}")
        print(f"Losses:               {stats['losses']}")
        print(f"Win Rate:             {stats['win_rate']:.1f}%")
        print("-"*60)
        print(f"Avg P&L per Trade:    ${stats['avg_pnl_per_trade']:.2f}")
        print(f"Best Trade:           ${stats['best_trade']:.2f}")
        print(f"Worst Trade:          ${stats['worst_trade']:.2f}")
        print(f"Avg Edge:             {stats['avg_edge']:.2f}%")
        print("-"*60)
        print(f"Max Drawdown:         {stats['max_drawdown']:.1f}% (${stats['max_drawdown_dollar']:.2f})")
        print("="*60 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def simulate_trade_outcome(
    side: str,
    btc_price_at_entry: float,
    btc_price_at_close: float,
    entry_odds: float,
    bet_size: float,
    fee_percent: float = None
) -> Tuple[str, float, float]:
    """
    Determine trade outcome based on actual BTC price movement.
    
    Args:
        side: "UP" or "DOWN"
        btc_price_at_entry: BTC price when trade was entered
        btc_price_at_close: BTC price at interval close
        entry_odds: The odds at which we entered
        bet_size: Amount bet
        fee_percent: Fee to deduct from winnings
    
    Returns:
        Tuple of (outcome, payout, profit_loss)
    """
    fee_percent = fee_percent if fee_percent is not None else config.ESTIMATED_FEE_PERCENT
    
    # Determine if we won
    price_went_up = btc_price_at_close > btc_price_at_entry
    
    if side == "UP":
        won = price_went_up
    else:  # DOWN
        won = not price_went_up
    
    if won:
        # Payout = bet_size / odds (we get $1 per share, shares = bet/odds)
        payout = bet_size / entry_odds
        payout *= (1 - fee_percent)  # Apply fee
        profit_loss = payout - bet_size
        return "WIN", payout, profit_loss
    else:
        return "LOSS", 0.0, -bet_size


def get_btc_change_for_interval(
    btc_open: float,
    btc_close: float
) -> Tuple[str, float]:
    """
    Calculate BTC bias and change percent for an interval.
    
    Args:
        btc_open: Opening price
        btc_close: Closing price
    
    Returns:
        Tuple of (bias ("UP"/"DOWN"/None), change_percent)
    """
    if btc_open <= 0:
        return None, 0.0
    
    change_pct = ((btc_close - btc_open) / btc_open) * 100
    
    if abs(change_pct) < config.BTC_BIAS_THRESHOLD_PERCENT:
        return None, change_pct
    
    bias = "UP" if change_pct > 0 else "DOWN"
    return bias, change_pct
