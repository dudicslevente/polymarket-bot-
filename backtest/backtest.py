"""
Main backtesting module for Polymarket BTC 15-minute trading bot.

This module provides:
- Complete backtesting loop using live bot logic
- Simulated trade execution and resolution
- Performance tracking and reporting

The backtester imports and uses the actual bot code for all decision logic,
ensuring that backtest results accurately reflect live bot behavior.

NO LIVE API CONNECTIONS ARE MADE - all data comes from historical CSVs.

Usage:
    python -m backtest.backtest
    
    or:
    
    from backtest import run_backtest
    final_balance, trades = run_backtest(
        data_folder='data',
        starting_balance=100.0
    )
"""

import os
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import live bot modules (for decision logic)
import config
from strategy import (
    TradeSignal,
    estimate_fair_probability,
    calculate_edge,
    get_market_odds_for_side
)
from market import Market

# Import backtest modules
from backtest.data_loader import DataLoader, HistoricalInterval, create_sample_binance_csv, create_sample_polymarket_csv
from backtest.utils import (
    BacktestTrade,
    BacktestLogger,
    calculate_bet_size_backtest,
    calculate_drawdown,
    simulate_trade_outcome,
    get_btc_change_for_interval,
    format_backtest_trade
)
from backtest.execution_realism import (
    ExecutionRealismConfig,
    apply_all_realism_adjustments,
    determine_trade_outcome_realistic,
    RealismStats,
    DEFAULT_REALISM_CONFIG
)


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """
    Configuration for a backtest run.
    
    Allows overriding live bot settings for parameter sweeps.
    """
    # Data settings
    data_folder: str = "data"
    binance_file: str = "binance_1m.csv"
    polymarket_file: str = "polymarket_15m.csv"
    
    # Date range filters (optional)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    # Balance settings
    starting_balance: float = 100.0
    
    # Bet sizing (None = use config defaults)
    bet_size_percent: Optional[float] = None
    min_bet_size: Optional[float] = None
    max_bet_size: Optional[float] = None
    min_balance_to_trade: Optional[float] = None
    
    # Signal thresholds (None = use config defaults)
    btc_bias_threshold: Optional[float] = None
    min_edge_threshold: Optional[float] = None
    
    # Fees and slippage
    fee_percent: Optional[float] = None
    slippage_percent: Optional[float] = None
    
    # Cooldown (in number of intervals, 1 interval = 15 min)
    # 1 = one trade per interval (can trade every 15 min)
    # 4 = one trade per hour, etc.
    cooldown_intervals: int = 1  # Allow trading each 15-min interval
    
    # Output settings
    log_file: str = "backtest_results.csv"
    verbose: bool = True
    generate_plots: bool = True
    plot_folder: str = "backtest_plots"
    
    # Data source settings
    allow_synthetic: bool = False  # If False, require real Polymarket data
    
    # Execution Realism Settings
    # Set to None to disable realism, or provide config for realistic execution
    realism_config: Optional[ExecutionRealismConfig] = field(
        default_factory=lambda: ExecutionRealismConfig()
    )
    
    # Use real market outcomes (from resolved_outcome field in CSV)
    # If False, uses BTC price movement to determine outcome
    use_real_outcomes: bool = True


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    final_balance: float
    starting_balance: float
    total_pnl: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    max_drawdown: float
    max_drawdown_dollar: float
    avg_edge: float
    avg_pnl_per_trade: float
    best_trade: float
    worst_trade: float
    trades: List[BacktestTrade]
    
    # Time info
    data_start: Optional[datetime] = None
    data_end: Optional[datetime] = None
    intervals_processed: int = 0
    intervals_traded: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATED MARKET AND CLIENTS
# ─────────────────────────────────────────────────────────────────────────────

class SimulatedMarket(Market):
    """
    A Market object created from historical interval data.
    
    Behaves exactly like a real Market for strategy analysis.
    """
    
    def __init__(self, interval: HistoricalInterval):
        super().__init__(
            market_id=interval.market_id,
            condition_id=f"COND-{interval.market_id}",
            question=f"Will BTC price be higher at {interval.interval_end.strftime('%H:%M')} UTC?",
            asset="BTC",
            duration_minutes=15,
            start_time=interval.interval_start,
            end_time=interval.interval_end,
            yes_price=interval.yes_price,
            no_price=interval.no_price,
            liquidity=interval.market_liquidity,
            volume=interval.market_volume,
            is_active=True,
            tokens={"yes": f"token_yes_{interval.market_id}", "no": f"token_no_{interval.market_id}"}
        )
        
        # Store interval data for later
        self._interval = interval


class SimulatedPolymarketClient:
    """
    A simulated Polymarket client for backtesting.
    
    Provides the same interface as the live PolymarketClient but uses
    historical data instead of making API calls.
    """
    
    def __init__(self, bt_config: BacktestConfig):
        self.config = bt_config
        self.traded_markets: set = set()
    
    def is_market_fresh(self, market: Market) -> bool:
        """
        Check if market is fresh enough to trade.
        
        For backtesting, we assume all markets are fresh since we're
        simulating entry at the interval start.
        """
        return True
    
    def get_market_age_seconds(self, market: Market) -> float:
        """Get market age. For backtesting, assume 30 seconds old."""
        return 30.0
    
    def was_already_traded(self, market: Market) -> bool:
        """Check if we already traded this market."""
        return market.market_id in self.traded_markets
    
    def mark_as_traded(self, market: Market):
        """Mark market as traded."""
        self.traded_markets.add(market.market_id)
    
    def has_sufficient_liquidity(self, market: Market) -> bool:
        """Check if market has sufficient liquidity."""
        min_liq = self.config.min_bet_size or config.MIN_LIQUIDITY_USD
        return market.liquidity >= min_liq
    
    def has_reasonable_spread(self, market: Market) -> bool:
        """Check if market spread is reasonable."""
        combined = market.yes_price + market.no_price
        return combined <= config.MAX_SPREAD_COMBINED


class SimulatedBinanceClient:
    """
    A simulated Binance client for backtesting.
    
    Returns BTC price data from the historical interval.
    """
    
    def __init__(self, interval: HistoricalInterval):
        self._interval = interval
    
    def get_btc_price(self) -> Optional[float]:
        """Get current BTC price from interval data."""
        return self._interval.btc_price_at_signal
    
    def get_btc_price_change(self) -> Tuple[Optional[str], float, float]:
        """
        Get BTC bias from interval data.
        
        Returns:
            Tuple of (bias, change_percent, current_price)
        """
        bias, change_pct = get_btc_change_for_interval(
            self._interval.btc_open,
            self._interval.btc_price_at_signal
        )
        return bias, change_pct, self._interval.btc_price_at_signal


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST STRATEGY ADAPTER
# ─────────────────────────────────────────────────────────────────────────────

def analyze_interval_for_trade(
    interval: HistoricalInterval,
    polymarket_client: SimulatedPolymarketClient,
    bt_config: BacktestConfig
) -> TradeSignal:
    """
    Analyze a historical interval for trade opportunity.
    
    This mirrors the live bot's analyze_trade_opportunity() function
    but uses historical data instead of live API calls.
    
    Args:
        interval: The historical interval data
        polymarket_client: Simulated Polymarket client
        bt_config: Backtest configuration
    
    Returns:
        TradeSignal with analysis results
    """
    # Create a Market object from interval data
    market = SimulatedMarket(interval)
    
    # Initialize signal
    signal = TradeSignal(
        market=market,
        side="",
        market_odds=0.0,
        fair_probability=0.0,
        edge=0.0,
        btc_price=interval.btc_price_at_signal,
        btc_change_percent=interval.btc_change_percent,
        bias_strength="",
        skip_reason=None
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # FILTER 1: Valid Data Check
    # ─────────────────────────────────────────────────────────────────────
    if not interval.has_valid_data:
        signal.skip_reason = interval.skip_reason or "Invalid interval data"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────
    # FILTER 2: Already Traded (within this backtest)
    # ─────────────────────────────────────────────────────────────────────
    if polymarket_client.was_already_traded(market):
        signal.skip_reason = "Already traded this interval"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────
    # FILTER 3: Liquidity Check
    # ─────────────────────────────────────────────────────────────────────
    if not polymarket_client.has_sufficient_liquidity(market):
        signal.skip_reason = f"Insufficient liquidity (${market.liquidity:.2f})"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────
    # FILTER 4: Spread Check
    # ─────────────────────────────────────────────────────────────────────
    if not polymarket_client.has_reasonable_spread(market):
        combined = market.yes_price + market.no_price
        signal.skip_reason = f"Spread too wide ({combined:.3f})"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────
    # FILTER 5: BTC Bias Detection (using historical change)
    # ─────────────────────────────────────────────────────────────────────
    bias_threshold = bt_config.btc_bias_threshold or config.BTC_BIAS_THRESHOLD_PERCENT
    
    if abs(interval.btc_change_percent) < bias_threshold:
        signal.skip_reason = (
            f"No clear BTC bias (change: {interval.btc_change_percent:.3f}% "
            f"within ±{bias_threshold}%)"
        )
        return signal
    
    # Determine bias direction
    bias = "UP" if interval.btc_change_percent > 0 else "DOWN"
    signal.side = bias
    
    # ─────────────────────────────────────────────────────────────────────
    # FILTER 6: Fair Probability Estimation
    # ─────────────────────────────────────────────────────────────────────
    fair_prob, strength = estimate_fair_probability(bias, interval.btc_change_percent)
    signal.fair_probability = fair_prob
    signal.bias_strength = strength
    
    # ─────────────────────────────────────────────────────────────────────
    # FILTER 7: Get Market Odds
    # ─────────────────────────────────────────────────────────────────────
    market_odds = get_market_odds_for_side(market, bias)
    signal.market_odds = market_odds
    
    if market_odds <= 0 or market_odds >= 1:
        signal.skip_reason = f"Invalid market odds: {market_odds}"
        return signal
    
    # ─────────────────────────────────────────────────────────────────────
    # FILTER 8: Edge Calculation & Minimum Edge Check
    # ─────────────────────────────────────────────────────────────────────
    edge = calculate_edge(fair_prob, market_odds)
    signal.edge = edge
    
    # Get fee and slippage
    fee_pct = bt_config.fee_percent if bt_config.fee_percent is not None else config.ESTIMATED_FEE_PERCENT
    slip_pct = bt_config.slippage_percent if bt_config.slippage_percent is not None else config.ESTIMATED_SLIPPAGE_PERCENT
    min_edge = bt_config.min_edge_threshold if bt_config.min_edge_threshold is not None else config.MIN_EDGE_THRESHOLD
    
    # Net edge after costs
    net_edge = edge - fee_pct - slip_pct
    
    if net_edge < min_edge:
        signal.skip_reason = (
            f"Insufficient edge: {edge*100:.2f}% gross, {net_edge*100:.2f}% net "
            f"(need {min_edge*100:.1f}%)"
        )
        return signal
    
    # ─────────────────────────────────────────────────────────────────────
    # ALL FILTERS PASSED
    # ─────────────────────────────────────────────────────────────────────
    return signal


# ─────────────────────────────────────────────────────────────────────────────
# MAIN BACKTEST FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest(
    data_folder: str = "data",
    starting_balance: float = 100.0,
    config_override: Optional[BacktestConfig] = None,
    **kwargs
) -> Tuple[float, List[BacktestTrade]]:
    """
    Run a complete backtest on historical data.
    
    This function:
    1. Loads historical data (BTC candles + Polymarket markets)
    2. Iterates through all 15-minute intervals
    3. Uses live bot logic to analyze each interval
    4. Simulates trade execution and resolution
    5. Tracks and reports performance
    
    Args:
        data_folder: Path to folder containing historical CSVs
        starting_balance: Initial simulated balance
        config_override: Optional BacktestConfig to override defaults
        **kwargs: Additional config overrides
    
    Returns:
        Tuple of (final_balance, list of BacktestTrade objects)
    """
    print("\n" + "="*60)
    print("🔬 POLYMARKET BTC BACKTESTER")
    print("="*60)
    print("⚠️  SIMULATION MODE - No live API connections")
    print("="*60 + "\n")
    
    # Build configuration
    if config_override:
        bt_config = config_override
    else:
        bt_config = BacktestConfig(
            data_folder=data_folder,
            starting_balance=starting_balance,
            **kwargs
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # STEP 1: Load Historical Data
    # ─────────────────────────────────────────────────────────────────────
    print("📂 Loading historical data...")
    
    loader = DataLoader(
        data_folder=bt_config.data_folder,
        binance_file=bt_config.binance_file,
        polymarket_file=bt_config.polymarket_file
    )
    
    # Require real Polymarket data unless --allow-synthetic is passed
    require_real = not bt_config.allow_synthetic
    
    if not loader.load_all(require_real_polymarket=require_real):
        if not bt_config.allow_synthetic:
            print("\n❌ Cannot run backtest without real Polymarket data!")
            print("   To fetch real data, run:")
            print("   python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv")
            print("")
            print("   Or use --allow-synthetic to run with simulated data (not recommended)")
            return bt_config.starting_balance, []
        
        # Try to create sample data for testing (only if allow_synthetic)
        print("\n⚠️ Data not found. Creating sample data for testing...")
        
        binance_path = os.path.join(bt_config.data_folder, bt_config.binance_file)
        polymarket_path = os.path.join(bt_config.data_folder, bt_config.polymarket_file)
        
        create_sample_binance_csv(binance_path, days=7)
        create_sample_polymarket_csv(polymarket_path, days=7)
        
        # Try loading again
        if not loader.load_all(require_real_polymarket=False):
            print("❌ Failed to load data. Exiting.")
            return bt_config.starting_balance, []
    
    # ─────────────────────────────────────────────────────────────────────
    # STEP 2: Initialize Backtest State
    # ─────────────────────────────────────────────────────────────────────
    balance = bt_config.starting_balance
    trades: List[BacktestTrade] = []
    trade_count = 0
    
    # Cooldown tracking
    intervals_since_last_trade = bt_config.cooldown_intervals  # Start ready to trade
    
    # Create logger
    logger = BacktestLogger(bt_config.log_file)
    
    # Create simulated clients
    polymarket_client = SimulatedPolymarketClient(bt_config)
    
    # Get total intervals for progress
    total_intervals = loader.get_interval_count(bt_config.start_date, bt_config.end_date)
    
    print(f"\n📊 Starting backtest:")
    print(f"   Starting balance: ${bt_config.starting_balance:.2f}")
    print(f"   Total intervals:  {total_intervals}")
    print(f"   Cooldown:         {bt_config.cooldown_intervals} intervals ({bt_config.cooldown_intervals * 15} min)")
    print()
    
    # ─────────────────────────────────────────────────────────────────────
    # STEP 3: Main Backtest Loop
    # ─────────────────────────────────────────────────────────────────────
    processed = 0
    skipped_count = 0
    
    # Initialize realism stats
    realism_stats = RealismStats()
    
    # Print realism status
    if bt_config.realism_config:
        print("   🎯 Execution realism: ENABLED")
        print(f"      - Latency: {bt_config.realism_config.latency_seconds}s")
        print(f"      - Slippage: {bt_config.realism_config.slippage_fixed*100:.1f}% fixed")
        print(f"      - Max bet: {bt_config.realism_config.max_bet_liquidity_fraction*100:.0f}% of liquidity")
    else:
        print("   ⚠️ Execution realism: DISABLED (optimistic mode)")
    
    if bt_config.use_real_outcomes:
        print("   ✅ Using REAL market outcomes")
    else:
        print("   ⚠️ Using BTC price movement for outcomes")
    print()
    
    for interval in loader.iterate_intervals(bt_config.start_date, bt_config.end_date):
        processed += 1
        
        # Progress indicator
        if bt_config.verbose and processed % 100 == 0:
            pct = (processed / total_intervals) * 100 if total_intervals > 0 else 0
            print(f"   Processing... {processed}/{total_intervals} ({pct:.1f}%)")
        
        # Check cooldown
        if intervals_since_last_trade < bt_config.cooldown_intervals:
            intervals_since_last_trade += 1
            continue
        
        # Check minimum balance
        if balance < (bt_config.min_balance_to_trade or config.MIN_BALANCE_TO_TRADE):
            if bt_config.verbose:
                print(f"⚠️ Balance ${balance:.2f} below minimum. Stopping.")
            break
        
        # Analyze interval for trade opportunity
        signal = analyze_interval_for_trade(interval, polymarket_client, bt_config)
        
        if signal.skip_reason:
            skipped_count += 1
            continue
        
        # ─────────────────────────────────────────────────────────────────
        # EXECUTE SIMULATED TRADE (with execution realism)
        # ─────────────────────────────────────────────────────────────────
        
        # Calculate initial bet size
        bet_size = calculate_bet_size_backtest(
            balance,
            bt_config.bet_size_percent,
            bt_config.min_bet_size,
            bt_config.max_bet_size,
            bt_config.min_balance_to_trade
        )
        
        if bet_size <= 0:
            continue
        
        # Apply execution realism adjustments
        entry_odds = signal.market_odds
        
        if bt_config.realism_config:
            realism_stats.total_trades_considered += 1
            
            adjusted_odds, adjusted_bet, skip_reason = apply_all_realism_adjustments(
                base_odds=signal.market_odds,
                side=signal.side,
                edge=signal.edge,
                desired_bet=bet_size,
                liquidity=interval.market_liquidity,
                volume=interval.market_volume,
                config=bt_config.realism_config
            )
            
            if skip_reason:
                # Track filtered trades
                if "odds" in skip_reason.lower():
                    realism_stats.filtered_extreme_odds += 1
                elif "edge" in skip_reason.lower() and "liquidity" in skip_reason.lower():
                    realism_stats.filtered_high_edge_low_liquidity += 1
                elif "edge" in skip_reason.lower():
                    realism_stats.filtered_high_edge += 1
                elif "liquidity" in skip_reason.lower():
                    realism_stats.filtered_low_liquidity += 1
                elif "volume" in skip_reason.lower():
                    realism_stats.filtered_low_volume += 1
                
                if bt_config.verbose:
                    print(f"   ⚠️ Filtered: {skip_reason}")
                skipped_count += 1
                continue
            
            # Track adjustments
            if adjusted_odds != signal.market_odds:
                realism_stats.trades_with_latency_adjustment += 1
                realism_stats.trades_with_slippage += 1
                realism_stats.total_odds_adjustment += (adjusted_odds - signal.market_odds)
            
            if adjusted_bet < bet_size:
                realism_stats.trades_with_bet_cap += 1
                realism_stats.total_bet_reduction += (bet_size - adjusted_bet)
            
            entry_odds = adjusted_odds
            bet_size = adjusted_bet
        
        if bet_size <= 0:
            continue
        
        # Deduct bet from balance
        balance_before = balance
        balance -= bet_size
        
        # Determine outcome
        if bt_config.use_real_outcomes and interval.resolved_outcome in ("UP", "DOWN"):
            # Use REAL market resolution
            outcome, payout, profit_loss = determine_trade_outcome_realistic(
                side=signal.side,
                resolved_outcome=interval.resolved_outcome,
                entry_odds=entry_odds,
                bet_size=bet_size,
                fee_percent=bt_config.fee_percent
            )
        else:
            # Fallback: use BTC price movement
            outcome, payout, profit_loss = simulate_trade_outcome(
                side=signal.side,
                btc_price_at_entry=interval.btc_open,
                btc_price_at_close=interval.btc_close,
                entry_odds=entry_odds,
                bet_size=bet_size,
                fee_percent=bt_config.fee_percent
            )
        
        # Update balance
        balance += payout

        # Compute simulated entry timing (seconds into the 15-min interval)
        latency_seconds = 0
        if bt_config.realism_config is not None:
            try:
                latency_seconds = int(bt_config.realism_config.latency_seconds or 0)
            except Exception:
                latency_seconds = 0

        entry_time = interval.interval_start + timedelta(seconds=latency_seconds)
        seconds_into_interval = int((entry_time - interval.interval_start).total_seconds())
        
        # Create trade record
        trade_count += 1
        trade = BacktestTrade(
            trade_id=f"BT-{trade_count:05d}",
            interval_start=interval.interval_start,
            entry_time=entry_time,
            seconds_into_interval=seconds_into_interval,
            market_id=interval.market_id,
            side=signal.side,
            entry_odds=entry_odds,  # Use adjusted odds
            fair_probability=signal.fair_probability,
            edge=signal.edge,
            btc_price_at_entry=interval.btc_open,
            btc_price_at_close=interval.btc_close,
            bet_size=bet_size,
            balance_before=balance_before,
            balance_after=balance,
            outcome=outcome,
            payout=payout,
            profit_loss=profit_loss,
            resolved_outcome=interval.resolved_outcome
        )
        
        trades.append(trade)
        logger.log_trade(trade)
        
        # Mark as traded and reset cooldown
        polymarket_client.mark_as_traded(signal.market)
        intervals_since_last_trade = 0
        
        # Print trade if verbose
        if bt_config.verbose:
            print(format_backtest_trade(trade))
    
    # ─────────────────────────────────────────────────────────────────────
    # STEP 4: Generate Results
    # ─────────────────────────────────────────────────────────────────────
    
    print(f"\n✅ Backtest complete!")
    print(f"   Intervals processed: {processed}")
    print(f"   Intervals skipped:   {skipped_count}")
    print(f"   Trades executed:     {len(trades)}")
    
    # Print realism stats if enabled
    if bt_config.realism_config and realism_stats.total_trades_considered > 0:
        realism_stats.print_summary()
    
    # Print summary
    logger.print_summary()
    
    # Generate plots if requested
    if bt_config.generate_plots and trades:
        try:
            from backtest.plots import plot_all
            plot_all(trades, bt_config.starting_balance, bt_config.plot_folder, show=False)
        except ImportError:
            print("⚠️ matplotlib not installed. Skipping plots.")
        except Exception as e:
            print(f"⚠️ Error generating plots: {e}")
    
    return balance, trades


def run_parameter_sweep(
    data_folder: str = "data",
    starting_balance: float = 100.0,
    edge_thresholds: List[float] = None,
    bet_sizes: List[float] = None
) -> List[Dict[str, Any]]:
    """
    Run multiple backtests with different parameters.
    
    Useful for finding optimal settings.
    
    Args:
        data_folder: Path to data folder
        starting_balance: Initial balance
        edge_thresholds: List of edge thresholds to test
        bet_sizes: List of bet size percentages to test
    
    Returns:
        List of result dictionaries
    """
    if edge_thresholds is None:
        edge_thresholds = [0.01, 0.02, 0.03, 0.04, 0.05]
    
    if bet_sizes is None:
        bet_sizes = [0.02, 0.03, 0.05, 0.07, 0.10]
    
    results = []
    total_runs = len(edge_thresholds) * len(bet_sizes)
    run_num = 0
    
    print(f"\n🔬 PARAMETER SWEEP: {total_runs} combinations\n")
    
    for edge in edge_thresholds:
        for bet_pct in bet_sizes:
            run_num += 1
            print(f"\n[{run_num}/{total_runs}] Edge: {edge*100:.1f}% | Bet: {bet_pct*100:.1f}%")
            
            bt_config = BacktestConfig(
                data_folder=data_folder,
                starting_balance=starting_balance,
                min_edge_threshold=edge,
                bet_size_percent=bet_pct,
                verbose=False,
                generate_plots=False,
                log_file=f"sweep_edge{edge:.2f}_bet{bet_pct:.2f}.csv"
            )
            
            final_balance, trades = run_backtest(config_override=bt_config)
            
            wins = sum(1 for t in trades if t.outcome == "WIN")
            
            result = {
                "edge_threshold": edge,
                "bet_percent": bet_pct,
                "final_balance": final_balance,
                "pnl": final_balance - starting_balance,
                "pnl_pct": ((final_balance / starting_balance) - 1) * 100,
                "total_trades": len(trades),
                "win_rate": (wins / len(trades) * 100) if trades else 0
            }
            
            results.append(result)
            
            print(f"   → P&L: ${result['pnl']:.2f} ({result['pnl_pct']:.1f}%)")
            print(f"   → Trades: {result['total_trades']} | Win Rate: {result['win_rate']:.1f}%")
    
    # Print summary table
    print("\n" + "="*70)
    print("📊 PARAMETER SWEEP RESULTS")
    print("="*70)
    print(f"{'Edge':<10} {'Bet %':<10} {'Final Bal':<12} {'P&L':<12} {'Trades':<10} {'Win %':<10}")
    print("-"*70)
    
    for r in sorted(results, key=lambda x: x['pnl'], reverse=True):
        print(f"{r['edge_threshold']*100:>5.1f}%    {r['bet_percent']*100:>5.1f}%    "
              f"${r['final_balance']:>8.2f}    ${r['pnl']:>8.2f}    "
              f"{r['total_trades']:>6}    {r['win_rate']:>5.1f}%")
    
    print("="*70)
    
    return results


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND LINE INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Command line interface for the backtester."""
    parser = argparse.ArgumentParser(
        description="Backtest the Polymarket BTC 15-minute trading strategy"
    )
    
    parser.add_argument(
        "--data",
        type=str,
        default="data",
        help="Path to folder containing historical CSVs (default: data)"
    )
    
    parser.add_argument(
        "--balance",
        type=float,
        default=100.0,
        help="Starting balance in USD (default: 100)"
    )
    
    parser.add_argument(
        "--edge",
        type=float,
        default=None,
        help="Minimum edge threshold (e.g., 0.02 for 2%%)"
    )
    
    parser.add_argument(
        "--bet-size",
        type=float,
        default=None,
        help="Bet size as fraction of balance (e.g., 0.03 for 3%%)"
    )
    
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run parameter sweep across multiple settings"
    )
    
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip generating plots"
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce output verbosity"
    )
    
    parser.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="Allow synthetic Polymarket data (NOT recommended for accurate backtesting)"
    )
    
    parser.add_argument(
        "--create-sample-data",
        action="store_true",
        help="Create sample data files for testing"
    )
    
    parser.add_argument(
        "--no-realism",
        action="store_true",
        help="Disable execution realism (latency, slippage, liquidity caps) - NOT recommended"
    )
    
    parser.add_argument(
        "--btc-outcomes",
        action="store_true",
        help="Use BTC price movement for outcomes instead of real market resolution"
    )
    
    args = parser.parse_args()
    
    # Create sample data if requested
    if args.create_sample_data:
        print("📝 Creating sample data files...")
        create_sample_binance_csv(os.path.join(args.data, "binance_1m.csv"), days=7)
        create_sample_polymarket_csv(os.path.join(args.data, "polymarket_15m.csv"), days=7)
        print("✅ Sample data created. Run backtest without --create-sample-data")
        return 0
    
    # Run parameter sweep if requested
    if args.sweep:
        results = run_parameter_sweep(
            data_folder=args.data,
            starting_balance=args.balance
        )
        return 0
    
    # Build config
    bt_config = BacktestConfig(
        data_folder=args.data,
        starting_balance=args.balance,
        min_edge_threshold=args.edge,
        bet_size_percent=args.bet_size,
        verbose=not args.quiet,
        generate_plots=not args.no_plots,
        allow_synthetic=args.allow_synthetic,
        realism_config=None if args.no_realism else ExecutionRealismConfig(),
        use_real_outcomes=not args.btc_outcomes
    )
    
    # Run backtest
    final_balance, trades = run_backtest(config_override=bt_config)
    
    print(f"\n💰 Final Balance: ${final_balance:.2f}")
    pnl = final_balance - args.balance
    print(f"📈 Total P&L: ${pnl:+.2f} ({(pnl/args.balance)*100:+.1f}%)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
