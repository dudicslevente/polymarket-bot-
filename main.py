"""
Main orchestration module for the Polymarket BTC 15-minute trading bot.

This is the entry point for the bot. It:
- Validates configuration
- Initializes all components
- Runs the main trading loop
- Handles graceful shutdown

Run with: python main.py
"""

import sys
import time
import signal
import argparse
from datetime import datetime, timezone
from typing import Optional

import config
from market import PolymarketClient, get_client as get_polymarket_client
from price_feed import BinanceClient, get_client as get_binance_client, get_btc_bias
from strategy import (
    analyze_trade_opportunity, 
    should_trade, 
    calculate_bet_size,
    format_skip_reason
)
from execution import ExecutionEngine, confirm_live_trading
from logger import get_logger, log_trade, analyze_performance


# Global flag for graceful shutdown
_shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    print("\n\n⚠️ Shutdown requested. Finishing current operation...")
    _shutdown_requested = True


def setup_signal_handlers():
    """Set up handlers for SIGINT and SIGTERM."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def print_startup_banner():
    """Print the startup banner."""
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     POLYMARKET BTC 15-MINUTE TRADING BOT v1.0                ║")
    print("║     Conservative Rolling-Interval Strategy                   ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def initialize_bot():
    """
    Initialize all bot components and validate configuration.
    
    Returns True if initialization succeeded, False otherwise.
    """
    print("🔧 Initializing bot components...")
    
    # Validate configuration
    if not config.validate_config():
        return False
    
    # Print config summary
    config.print_config_summary()
    
    # In LIVE mode, require confirmation
    if not config.TEST_MODE:
        if not confirm_live_trading():
            return False
    
    print("✅ Bot initialized successfully")
    return True


def run_trading_loop(
    polymarket: PolymarketClient,
    binance: BinanceClient,
    execution: ExecutionEngine
):
    """
    Main trading loop.
    
    Continuously:
    1. Scans for new BTC 15-minute markets
    2. Analyzes each for trade opportunities
    3. Executes trades when conditions are met
    4. Checks and resolves completed trades
    5. Logs everything
    
    Runs until shutdown is requested.
    """
    global _shutdown_requested
    
    logger = get_logger()
    scan_count = 0
    
    print("\n🚀 Starting trading loop...")
    print(f"   Scanning every {config.SCAN_INTERVAL_SECONDS} seconds")
    print(f"   Press Ctrl+C to stop\n")
    
    while not _shutdown_requested:
        try:
            scan_count += 1
            current_time = datetime.now(timezone.utc)
            
            if config.VERBOSE_LOGGING:
                print(f"\n{'─'*50}")
                print(f"🔍 Scan #{scan_count} | {current_time.strftime('%H:%M:%S')} UTC")
                print(f"{'─'*50}")
            
            # ─────────────────────────────────────────────────────────────────
            # STEP 1: Check and resolve any pending trades
            # ─────────────────────────────────────────────────────────────────
            if execution.state.active_trades:
                if config.VERBOSE_LOGGING:
                    print(f"📋 Checking {len(execution.state.active_trades)} active trades...")
                
                # In test mode with simulation, we need to simulate time passing
                # For real operation, trades resolve based on market end time
                if config.TEST_MODE:
                    # Simulate resolution for any trades older than 15 minutes
                    for trade_id, trade in list(execution.state.active_trades.items()):
                        time_since_entry = (current_time - trade.entry_time).total_seconds()
                        if time_since_entry >= 900:  # 15 minutes
                            execution.force_resolve_trade_for_simulation(trade)
                            log_trade(trade)
                else:
                    execution.check_and_resolve_trades()
            
            # ─────────────────────────────────────────────────────────────────
            # STEP 2: Check if we can trade (not in cooldown, have balance)
            # ─────────────────────────────────────────────────────────────────
            if execution.is_in_cooldown():
                if config.VERBOSE_LOGGING:
                    print("⏳ In cooldown, skipping scan")
                time.sleep(config.SCAN_INTERVAL_SECONDS)
                continue
            
            bet_size = calculate_bet_size(execution.state.balance)
            if bet_size <= 0:
                print("⚠️ Cannot calculate valid bet size, skipping")
                time.sleep(config.SCAN_INTERVAL_SECONDS)
                continue
            
            # ─────────────────────────────────────────────────────────────────
            # STEP 3: Fetch BTC 15-minute markets
            # ─────────────────────────────────────────────────────────────────
            markets = polymarket.fetch_btc_15min_markets()
            
            if not markets:
                if config.VERBOSE_LOGGING:
                    print("📭 No BTC 15-min markets found")
                time.sleep(config.SCAN_INTERVAL_SECONDS)
                continue
            
            if config.VERBOSE_LOGGING:
                print(f"📊 Found {len(markets)} potential markets")
            
            # ─────────────────────────────────────────────────────────────────
            # STEP 4: Analyze each market for trade opportunities
            # ─────────────────────────────────────────────────────────────────
            trade_executed = False
            
            for market in markets:
                if trade_executed:
                    # Only one trade per scan cycle
                    break
                
                if _shutdown_requested:
                    break
                
                # Analyze the opportunity
                signal = analyze_trade_opportunity(market, polymarket, binance)
                
                if not should_trade(signal):
                    if config.VERBOSE_LOGGING:
                        print(format_skip_reason(signal))
                    continue
                
                # ─────────────────────────────────────────────────────────────
                # STEP 5: Execute the trade
                # ─────────────────────────────────────────────────────────────
                print(f"\n🎯 TRADE OPPORTUNITY FOUND")
                print(f"   Market: {market.question[:50]}...")
                print(f"   Side: {signal.side}")
                print(f"   Odds: {signal.market_odds:.3f}")
                print(f"   Fair: {signal.fair_probability:.3f}")
                print(f"   Edge: {signal.edge*100:.2f}%")
                print(f"   BTC: ${signal.btc_price:,.2f}")
                print(f"   Bet: ${bet_size:.2f}")
                
                trade = execution.execute_trade(signal, bet_size)
                
                if trade:
                    trade_executed = True
                    
                    # In simulation mode, we can optionally fast-forward
                    # to resolution for testing purposes
                    # Uncomment below to auto-resolve immediately:
                    # if config.TEST_MODE:
                    #     execution.force_resolve_trade_for_simulation(trade)
                    #     log_trade(trade)
            
            # ─────────────────────────────────────────────────────────────────
            # STEP 6: Print periodic stats
            # ─────────────────────────────────────────────────────────────────
            if scan_count % 10 == 0:
                execution.print_stats()
            
            # ─────────────────────────────────────────────────────────────────
            # STEP 7: Sleep until next scan
            # ─────────────────────────────────────────────────────────────────
            if not _shutdown_requested:
                time.sleep(config.SCAN_INTERVAL_SECONDS)
                
        except KeyboardInterrupt:
            _shutdown_requested = True
            break
        except Exception as e:
            # Log error but don't crash
            print(f"❌ Error in trading loop: {e}")
            import traceback
            traceback.print_exc()
            
            # Wait before retrying
            time.sleep(config.SCAN_INTERVAL_SECONDS)


def create_simulated_btc_market(btc_price: float, bias: str, change_percent: float, cycle_num: int):
    """
    Create a realistic simulated 15-minute BTC market for testing.
    
    This simulates what a real Polymarket 15-minute BTC up/down market would look like.
    """
    from market import Market
    from datetime import datetime, timezone, timedelta
    
    now = datetime.now(timezone.utc)
    
    # Create market question
    question = f"Will BTC price be higher in 15 minutes? (15-min prediction)"
    
    # Simulate market odds based on current bias
    # In a real market, odds would reflect market sentiment
    base_probability = 0.50
    
    if bias == "UP":
        # Market thinks BTC will go up, so Yes (up) is favored
        market_bias = 0.52 + (abs(change_percent) * 0.1)  # Slight edge for momentum
    elif bias == "DOWN":
        # Market thinks BTC will go down, so No (down) is favored
        market_bias = 0.48 - (abs(change_percent) * 0.1)
    else:
        market_bias = 0.50
    
    # Add some market noise
    import random
    noise = random.uniform(-0.05, 0.05)
    market_bias = max(0.45, min(0.55, market_bias + noise))
    
    yes_price = market_bias
    no_price = 1.0 - market_bias
    
    # Ensure reasonable spread (not too wide)
    if abs(yes_price + no_price - 1.0) > 0.02:
        # Normalize to ensure Yes + No = 1.00 (minus vig)
        total = yes_price + no_price
        yes_price = yes_price / total * 0.98  # 2% vig
        no_price = no_price / total * 0.98
    
    # Create market object
    market = Market(
        market_id=f"SIM-BTC-{cycle_num}",
        condition_id=f"COND-BTC-{cycle_num}",
        question=question,
        asset="BTC",
        duration_minutes=15,
        start_time=now - timedelta(seconds=25 + (cycle_num * 5)),  # Vary age slightly
        end_time=now + timedelta(minutes=15),
        yes_price=yes_price,
        no_price=no_price,
        liquidity=1500.0 + (cycle_num * 100),  # Increasing liquidity
        volume=200.0 + (cycle_num * 50),
        is_active=True,
        tokens={"yes": f"token_yes_{cycle_num}", "no": f"token_no_{cycle_num}"}
    )
    
    # Add BTC price at creation time for reference
    market.btc_price_at_creation = btc_price
    
    return market


def run_simulation_mode():
    """
    Run an enhanced simulation to test the bot logic with realistic market conditions.
    
    This simulates the full trading process as if 15-minute BTC markets existed on Polymarket.
    """
    print("\n🎮 RUNNING ENHANCED SIMULATION MODE")
    print("   Simulating 15-minute BTC markets (not currently available on Polymarket)")
    print("   This tests the complete strategy with realistic market conditions.\n")
    
    polymarket = get_polymarket_client()
    binance = get_binance_client()
    execution = ExecutionEngine(polymarket)
    
    # Simulate 20 trading cycles with realistic conditions
    num_cycles = 20
    
    print("📊 Simulation will create realistic 15-minute BTC markets")
    print("   Each cycle: market discovery → analysis → potential trade → resolution")
    print("   Markets resolve based on BTC momentum and strategy edge\n")
    
    for i in range(num_cycles):
        if _shutdown_requested:
            break
            
        print(f"\n{'═'*60}")
        print(f"SIMULATION CYCLE {i+1}/{num_cycles}")
        print(f"{'═'*60}")
        
        # Get current BTC bias
        bias, change_percent, btc_price = get_btc_bias()
        
        if btc_price is None:
            print("⚠️ Could not fetch BTC price, skipping cycle")
            time.sleep(1)
            continue
        
        # Create a realistic simulated 15-minute BTC market
        simulated_market = create_simulated_btc_market(btc_price, bias or "NONE", change_percent or 0.0, i)
        
        print(f"🎯 Market: {simulated_market.question}")
        print(f"   BTC: ${simulated_market.btc_price_at_creation:,.2f} | Change: {change_percent:.3f}%")
        print(f"   Odds: Yes={simulated_market.yes_price:.3f} | No={simulated_market.no_price:.3f}")
        print(f"   Liquidity: ${simulated_market.liquidity:.2f}")
        
        # Check basic market filters
        if not polymarket.is_market_fresh(simulated_market):
            age = polymarket.get_market_age_seconds(simulated_market)
            print(f"⏭️ SKIP: Market too old ({age:.0f}s > {config.MAX_MARKET_AGE_SECONDS}s)")
            time.sleep(1)
            continue
            
        if not polymarket.has_sufficient_liquidity(simulated_market):
            print(f"⏭️ SKIP: Insufficient liquidity (${simulated_market.liquidity:.2f} < ${config.MIN_LIQUIDITY_USD:.2f})")
            time.sleep(1)
            continue
            
        if not polymarket.has_reasonable_spread(simulated_market):
            combined = simulated_market.yes_price + simulated_market.no_price
            print(f"⏭️ SKIP: Spread too wide ({combined:.3f} > {config.MAX_SPREAD_COMBINED})")
            time.sleep(1)
            continue
        
        # Analyze the opportunity
        signal = analyze_trade_opportunity(simulated_market, polymarket, binance)
        
        if not should_trade(signal):
            print(f"⏭️ SKIP: {format_skip_reason(signal).replace('⏭️ SKIP: ', '')}")
            time.sleep(1)
            continue
        
        # Calculate bet size
        bet_size = calculate_bet_size(execution.state.balance)
        if bet_size <= 0:
            print("⏭️ SKIP: Cannot calculate valid bet size")
            break
        
        # Execute the trade
        print(f"\n🎯 TRADE OPPORTUNITY FOUND")
        print(f"   Side: {signal.side} | Edge: {signal.edge*100:.2f}%")
        print(f"   Fair Prob: {signal.fair_probability:.3f} | Market Odds: {signal.market_odds:.3f}")
        print(f"   Bet Size: ${bet_size:.2f} ({bet_size/execution.state.balance*100:.1f}% of balance)")
        
        trade = execution.execute_trade(signal, bet_size)
        
        if trade:
            # Immediately resolve for simulation
            print("   ⏩ Fast-forwarding to market resolution...")
            time.sleep(1)
            execution.force_resolve_trade_for_simulation(trade)
            log_trade(trade)
            
            # Show result
            if trade.outcome == "WIN":
                profit = trade.payout - trade.bet_size
                print(f"   ✅ WIN: +${profit:.2f} | Balance: ${trade.balance_after:.2f}")
            else:
                print(f"   ❌ LOSS: -${trade.bet_size:.2f} | Balance: ${trade.balance_after:.2f}")
        
        time.sleep(1)
    
    # Print final comprehensive stats
    print("\n" + "="*60)
    print("📊 SIMULATION RESULTS")
    print("="*60)
    execution.print_stats()
    analyze_performance()
    
    print("\n" + "="*60)
    print("🎮 SIMULATION COMPLETE")
    print("="*60)
    print("This simulation demonstrates how the bot would perform with")
    print("real 15-minute BTC markets on Polymarket (when available).")
    print()
    print("Key takeaways:")
    print("- Conservative 3% bet sizing prevents ruin")
    print("- Small edge (2%+) compounds over time")
    print("- Strategy skips trades when uncertain")
    print("- Designed for survival, not maximum profit")
    print("="*60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket BTC 15-minute Trading Bot"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run fast simulation mode (instant trade resolution)"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analyze trade log and print performance stats"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Force LIVE mode (overrides TEST_MODE in .env)"
    )
    
    args = parser.parse_args()
    
    # Set up signal handlers
    setup_signal_handlers()
    
    # Print banner
    print_startup_banner()
    
    # Handle --analyze flag
    if args.analyze:
        analyze_performance()
        return 0
    
    # Override TEST_MODE if --live flag is used
    if args.live:
        config.TEST_MODE = False
        print("⚠️ LIVE mode enabled via command line flag")
    
    # Initialize bot
    if not initialize_bot():
        print("❌ Bot initialization failed. Exiting.")
        return 1
    
    # Create clients
    polymarket = get_polymarket_client()
    binance = get_binance_client()
    execution = ExecutionEngine(polymarket)
    
    # Run appropriate mode
    if args.simulate:
        run_simulation_mode()
    else:
        try:
            run_trading_loop(polymarket, binance, execution)
        except KeyboardInterrupt:
            pass
    
    # Shutdown
    print("\n🛑 Shutting down...")
    
    # Print final stats
    execution.print_stats()
    
    # Analyze trade log
    if execution.state.total_trades > 0:
        analyze_performance()
    
    print("👋 Bot stopped. Goodbye!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
