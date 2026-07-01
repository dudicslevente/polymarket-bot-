#!/usr/bin/env python3
"""Regression tests for live-trading safety edges."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import config
import execution
from execution import ExecutionEngine, Trade, TradeStatus
from market import Market, PolymarketClient
from strategy import analyze_trade_opportunity


class FakeExecutionClient:
    def __init__(self, balance=100.0):
        self.balance = balance
        self.traded_markets = set()

    def get_usdc_balance(self):
        return self.balance

    def mark_as_traded(self, market):
        self.traded_markets.add(market.market_id)


class LiveRegressionTests(unittest.TestCase):
    def setUp(self):
        self.original_test_mode = config.TEST_MODE
        self.original_verbose = config.VERBOSE_LOGGING
        self.original_wallet_address = config.WALLET_ADDRESS
        self.original_edge_price_source = config.EDGE_PRICE_SOURCE
        self.active_trades_dir = tempfile.TemporaryDirectory()
        self.active_trades_patch = patch.object(
            execution,
            "ACTIVE_TRADES_FILE",
            os.path.join(self.active_trades_dir.name, "active_trades.json"),
        )
        self.active_trades_patch.start()
        config.VERBOSE_LOGGING = False

    def tearDown(self):
        self.active_trades_patch.stop()
        self.active_trades_dir.cleanup()
        config.TEST_MODE = self.original_test_mode
        config.VERBOSE_LOGGING = self.original_verbose
        config.WALLET_ADDRESS = self.original_wallet_address
        config.EDGE_PRICE_SOURCE = self.original_edge_price_source

    def _sample_trade(self, market_id="market-1"):
        return Trade(
            trade_id="T1",
            market_id=market_id,
            market_question="BTC Up or Down?",
            side="UP",
            entry_odds=0.50,
            fair_probability=0.55,
            edge=0.05,
            btc_price_at_entry=100000.0,
            bet_size=5.0,
            balance_before=0.0,
            balance_after=0.0,
            status=TradeStatus.EXECUTED,
            entry_time=datetime.now(timezone.utc) - timedelta(minutes=5),
            mode="LIVE",
            order_id="order-1",
            filled_price=0.50,
            filled_shares=10.0,
            token_id="12345678901234567890",
            condition_id="0xabc",
        )

    def test_restart_restores_accounting_and_traded_markets(self):
        config.TEST_MODE = False
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "active_trades.json")
            with patch.object(execution, "ACTIVE_TRADES_FILE", state_path):
                first_client = FakeExecutionClient(balance=95.0)
                first = ExecutionEngine(first_client)
                trade = self._sample_trade("market-restart")
                first.state.active_trades[trade.trade_id] = trade
                first.state.resolved_balance = 101.25
                first.state.daily_pnl = 1.25
                first.state.daily_trades = 3
                first.state.consecutive_losses = 2
                first.state.last_trade_time = datetime.now(timezone.utc)
                first_client.traded_markets.add("older-market")
                first._save_active_trades()

                second_client = FakeExecutionClient(balance=92.0)
                second = ExecutionEngine(second_client)

                self.assertIn("T1", second.state.active_trades)
                self.assertEqual(second.state.resolved_balance, 101.25)
                self.assertEqual(second.state.daily_pnl, 1.25)
                self.assertEqual(second.state.daily_trades, 3)
                self.assertEqual(second.state.consecutive_losses, 2)
                self.assertEqual(second.state.balance, 92.0)
                self.assertIn("market-restart", second_client.traded_markets)
                self.assertIn("older-market", second_client.traded_markets)

    def test_pending_resolution_stays_active_without_accounting_mutation(self):
        config.TEST_MODE = False
        client = FakeExecutionClient(balance=100.0)
        engine = ExecutionEngine(client)
        trade = self._sample_trade("market-pending")
        trade.entry_time = datetime.now(timezone.utc) - timedelta(minutes=45)
        engine.state.active_trades[trade.trade_id] = trade
        engine.state.resolved_balance = 100.0

        with patch.object(engine, "_get_live_resolution", return_value="PENDING"), \
             patch.object(engine, "_force_resolution_check", return_value="PENDING"), \
             patch.object(engine, "_reconcile_live_order_for_trade", return_value={
                 "success": True,
                 "status": "FILLED",
                 "filled_shares": 10.0,
                 "filled_price": 0.5,
             }):
            resolved = engine.check_and_resolve_trades()

        self.assertEqual(resolved, [])
        self.assertIn(trade.trade_id, engine.state.active_trades)
        self.assertEqual(engine.state.resolved_balance, 100.0)
        self.assertEqual(engine.state.losses, 0)

    def test_live_win_books_redeemed_amount_not_odds_estimate(self):
        config.TEST_MODE = False
        client = FakeExecutionClient(balance=81.0)
        engine = ExecutionEngine(client)
        engine.state.resolved_balance = 100.0
        engine.state.daily_pnl = 0.0

        trade = self._sample_trade("market-redeemed")
        trade.bet_size = 19.0
        trade.entry_odds = 0.505
        trade.filled_price = 0.0
        trade.filled_shares = 35.82

        with patch.object(engine, "_redeem_winning_shares", return_value={
            "success": True,
            "amount_usdc": 35.82,
            "method": "onchain_redemption",
            "tx_hash": "0xabc",
        }), patch.object(engine, "_sync_balance_after_resolution"):
            engine._resolve_trade_with_outcome(trade, "WIN")

        self.assertAlmostEqual(trade.payout, 35.82)
        self.assertAlmostEqual(trade.payout - trade.bet_size, 16.82)
        self.assertAlmostEqual(engine.state.resolved_balance, 116.82)
        self.assertAlmostEqual(engine.state.daily_pnl, 16.82)
        self.assertEqual(trade.redemption_status, "REDEEMED")

    def test_resolution_sync_accepts_lower_api_balance(self):
        config.TEST_MODE = False
        client = FakeExecutionClient(balance=95.0)
        engine = ExecutionEngine(client)
        engine.state.balance = 100.0

        with patch("execution.time.sleep"):
            engine._sync_balance_after_resolution()

        self.assertEqual(engine.state.balance, 95.0)

    def test_strategy_skips_clob_fallback_prices(self):
        config.TEST_MODE = True
        config.EDGE_PRICE_SOURCE = "CLOB"
        market = Market(
            market_id="m1",
            condition_id="c1",
            question="BTC Up or Down?",
            asset="BTC",
            duration_minutes=15,
            start_time=datetime.now(timezone.utc) - timedelta(seconds=30),
            end_time=datetime.now(timezone.utc) + timedelta(minutes=14),
            yes_price=0.45,
            no_price=0.55,
            liquidity=1000.0,
            volume=100.0,
            is_active=True,
            tokens={"up": "12345678901234567890", "down": "22345678901234567890"},
        )

        class FakePolymarket:
            traded_markets = set()

            def is_market_fresh(self, _market): return True
            def get_market_age_seconds(self, _market): return 30
            def was_already_traded(self, _market): return False
            def has_sufficient_liquidity(self, _market): return True
            def has_reasonable_spread(self, _market): return True
            def get_best_prices(self, _market, _side):
                return {"bid": 0.45, "ask": 0.46, "mid": 0.455, "is_fallback": True}

        class FakeBinance:
            def get_btc_bias(self):
                return "UP", 0.25, 100000.0

        signal = analyze_trade_opportunity(market, FakePolymarket(), FakeBinance())
        self.assertEqual(signal.skip_reason, "No executable CLOB liquidity for edge calculation")

    def test_order_timeout_reconciles_open_order_without_failure(self):
        config.TEST_MODE = True
        client = PolymarketClient()
        client._check_position_for_fill = lambda *args, **kwargs: None
        client._check_trades_for_fill = lambda *args, **kwargs: None
        client._get_open_orders_for_token_compat = lambda *args, **kwargs: [
            {"id": "open-1", "status": "OPEN"}
        ]

        result = client._reconcile_order_submission_timeout(
            clob_client=object(),
            sdk={},
            token_id="12345678901234567890",
            amount_usd=5.0,
            order_price=0.5,
            shares=10.0,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["order_id"], "open-1")
        self.assertEqual(result["status"], "OPEN_POST_TIMEOUT")

    def test_redeem_sweep_uses_null_price_current_value_winner(self):
        config.TEST_MODE = False
        calls = []

        class FakeRedeemClient(PolymarketClient):
            def __init__(self):
                self.redeemed = []

            def get_open_positions(self, for_redemption=False):
                calls.append(("get_open_positions", for_redemption))
                return [{
                    "token_id": "12345678901234567890",
                    "size": 7.5,
                    "current_price": 0.0,
                    "current_value": 7.5,
                    "redeemable": True,
                    "title": "BTC Up",
                }]

            def redeem_winning_shares(self, token_id, shares, known_position=None):
                self.redeemed.append((token_id, shares, known_position))
                return {
                    "success": True,
                    "method": "onchain_redemption_negrisk",
                    "amount_usdc": 7.5,
                }

        client = FakeRedeemClient()
        result = client.redeem_all_winning_positions()

        self.assertEqual(result["winning_positions"], 1)
        self.assertEqual(result["onchain_redeemed"], 1)
        self.assertEqual(result["total_redeemed"], 7.5)
        self.assertEqual(client.redeemed[0][0], "12345678901234567890")
        self.assertEqual(calls, [("get_open_positions", True)])

    def test_unknown_negrisk_outcome_requires_manual_redemption(self):
        config.TEST_MODE = False
        config.WALLET_ADDRESS = "0xabc"

        class FakeClient(PolymarketClient):
            def __init__(self): pass

            def _execute_onchain_redemption(self, *args, **kwargs):
                raise AssertionError("should not attempt on-chain redemption without outcome_index")

        client = FakeClient()
        result = client.redeem_winning_shares(
            "12345678901234567890",
            shares=3.0,
            known_position={
                "token_id": "12345678901234567890",
                "size": 3.0,
                "current_price": 0.0,
                "current_value": 3.0,
                "redeemable": True,
                "negative_risk": True,
                "outcome_index": None,
                "condition_id": "0xabc",
                "owner": "0xabc",
            },
        )

        self.assertTrue(result["needs_manual_redemption"])
        self.assertEqual(result["method"], "manual_required_unknown_negrisk_outcome")

    def test_redemption_sweeps_enabled_by_default(self):
        self.assertTrue(config.ENABLE_REDEMPTION_IN_TRADING_LOOP)


if __name__ == "__main__":
    unittest.main()
