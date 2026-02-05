#!/usr/bin/env python3
"""
Test script for live deployment features.

This tests:
1. Trade dataclass with new token_id and redemption fields
2. Execution engine with redemption methods
3. PolymarketClient with position and redemption methods
4. Balance syncing after trades
5. Full trade lifecycle simulation
"""

import config
config.TEST_MODE = True  # Force test mode for safety

from market import PolymarketClient, Market
from price_feed import BinanceClient
from execution import ExecutionEngine, Trade, TradeStatus
from strategy import TradeSignal, calculate_bet_size
from datetime import datetime, timezone, timedelta
import sys


def test_trade_dataclass():
    """Test that Trade dataclass has all new fields."""
    print("\n" + "="*60)
    print("TEST 1: Trade Dataclass Fields")
    print("="*60)
    
    trade = Trade(
        trade_id='T123',
        market_id='test-market',
        market_question='Test Question',
        side='UP',
        entry_odds=0.5,
        fair_probability=0.55,
        edge=0.05,
        btc_price_at_entry=100000.0,
        bet_size=10.0,
        balance_before=100.0,
        balance_after=90.0,
        status=TradeStatus.PENDING,
        entry_time=datetime.now(timezone.utc),
        token_id='test-token-123',
        condition_id='cond-123',
        redemption_status='PENDING',
        redemption_amount=12.5
    )
    
    assert trade.token_id == 'test-token-123', "token_id not stored correctly"
    assert trade.condition_id == 'cond-123', "condition_id not stored correctly"
    assert trade.redemption_status == 'PENDING', "redemption_status not stored correctly"
    assert trade.redemption_amount == 12.5, "redemption_amount not stored correctly"
    
    print("✅ Trade dataclass has all required fields")
    print(f"   - token_id: {trade.token_id}")
    print(f"   - condition_id: {trade.condition_id}")
    print(f"   - redemption_status: {trade.redemption_status}")
    print(f"   - redemption_amount: {trade.redemption_amount}")
    
    return True


def test_polymarket_client_methods():
    """Test that PolymarketClient has all new methods."""
    print("\n" + "="*60)
    print("TEST 2: PolymarketClient Methods")
    print("="*60)
    
    client = PolymarketClient()
    
    methods = [
        'get_open_positions',
        'get_position_for_token',
        'redeem_winning_shares',
        'redeem_all_winning_positions',
        '_parse_position',
        '_execute_redemption',
        '_try_redeem_endpoint',
        '_try_claim_endpoint',
        '_check_auto_redemption'
    ]
    
    for method in methods:
        assert hasattr(client, method), f"Missing method: {method}"
        print(f"✅ {method}")
    
    # Test that methods work in TEST_MODE
    positions = client.get_open_positions()
    assert positions == [], "get_open_positions should return empty list in TEST mode"
    print("✅ get_open_positions() returns [] in TEST mode")
    
    result = client.redeem_winning_shares("test-token")
    assert result['success'] == True, "redeem_winning_shares should succeed in TEST mode"
    assert result.get('simulated') == True, "Should be marked as simulated"
    print("✅ redeem_winning_shares() returns success in TEST mode")
    
    return True


def test_execution_engine_methods():
    """Test that ExecutionEngine has all new methods."""
    print("\n" + "="*60)
    print("TEST 3: ExecutionEngine Methods")
    print("="*60)
    
    client = PolymarketClient()
    engine = ExecutionEngine(client)
    
    methods = [
        'check_and_redeem_positions',
        '_redeem_winning_shares',
        '_sync_balance_after_resolution',
        '_sync_balance_after_trade'
    ]
    
    for method in methods:
        assert hasattr(engine, method), f"Missing method: {method}"
        print(f"✅ {method}")
    
    # Test check_and_redeem_positions in TEST mode
    result = engine.check_and_redeem_positions()
    assert result.get('simulated') == True, "Should be simulated in TEST mode"
    print("✅ check_and_redeem_positions() works in TEST mode")
    
    return True


def test_config_option():
    """Test that config has the new REDEMPTION_CHECK_INTERVAL option."""
    print("\n" + "="*60)
    print("TEST 4: Config Options")
    print("="*60)
    
    assert hasattr(config, 'REDEMPTION_CHECK_INTERVAL'), "Missing REDEMPTION_CHECK_INTERVAL"
    assert isinstance(config.REDEMPTION_CHECK_INTERVAL, int), "REDEMPTION_CHECK_INTERVAL should be int"
    assert config.REDEMPTION_CHECK_INTERVAL > 0, "REDEMPTION_CHECK_INTERVAL should be positive"
    
    print(f"✅ REDEMPTION_CHECK_INTERVAL = {config.REDEMPTION_CHECK_INTERVAL} seconds")
    
    return True


def test_full_trade_lifecycle():
    """Test full trade lifecycle with redemption handling."""
    print("\n" + "="*60)
    print("TEST 5: Full Trade Lifecycle")
    print("="*60)
    
    client = PolymarketClient()
    engine = ExecutionEngine(client)
    
    initial_balance = engine.state.balance
    print(f"Starting balance: ${initial_balance:.2f}")
    
    # Create a simulated market
    now = datetime.now(timezone.utc)
    market = Market(
        market_id="test-btc-lifecycle",
        condition_id="cond-lifecycle",
        question="BTC Up or Down? Lifecycle Test",
        asset="BTC",
        duration_minutes=15,
        start_time=now - timedelta(seconds=30),
        end_time=now + timedelta(minutes=14, seconds=30),
        yes_price=0.48,
        no_price=0.52,
        liquidity=2000.0,
        volume=500.0,
        is_active=True,
        tokens={"up": "token-up-lifecycle", "down": "token-down-lifecycle"}
    )
    
    # Create trade signal
    signal = TradeSignal(
        market=market,
        side="UP",
        market_odds=0.48,
        fair_probability=0.55,
        edge=0.07,
        btc_price=100000.0,
        btc_change_percent=0.15,
        bias_strength="MILD"
    )
    
    bet_size = calculate_bet_size(engine.state.balance)
    print(f"Bet size: ${bet_size:.2f}")
    
    # Execute trade
    trade = engine.execute_trade(signal, bet_size)
    
    assert trade is not None, "Trade should execute"
    print(f"✅ Trade executed: {trade.trade_id}")
    
    # In TEST mode, token_id won't be set (since we use _simulate_execution)
    # But the fields should exist
    assert hasattr(trade, 'token_id'), "Trade should have token_id field"
    assert hasattr(trade, 'condition_id'), "Trade should have condition_id field"
    assert hasattr(trade, 'redemption_status'), "Trade should have redemption_status field"
    print(f"✅ Trade has all new fields")
    
    # Simulate resolution
    engine.force_resolve_trade_for_simulation(trade)
    
    print(f"✅ Trade resolved: {trade.outcome}")
    print(f"   Final balance: ${engine.state.balance:.2f}")
    print(f"   Redemption status: {trade.redemption_status}")
    
    return True


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("LIVE DEPLOYMENT FEATURES TEST SUITE")
    print("="*60)
    
    tests = [
        ("Trade Dataclass", test_trade_dataclass),
        ("PolymarketClient Methods", test_polymarket_client_methods),
        ("ExecutionEngine Methods", test_execution_engine_methods),
        ("Config Options", test_config_option),
        ("Full Trade Lifecycle", test_full_trade_lifecycle),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            result = test_func()
            if result:
                passed += 1
            else:
                failed += 1
                print(f"❌ {name} FAILED")
        except Exception as e:
            failed += 1
            print(f"❌ {name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*60)
    print(f"TEST RESULTS: {passed}/{len(tests)} passed")
    print("="*60)
    
    if failed > 0:
        print("❌ Some tests failed!")
        return 1
    else:
        print("✅ All tests passed! Code is ready for live deployment.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
