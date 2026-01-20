"""
Backtesting module for Polymarket BTC 15-minute trading bot.

This module provides a complete backtesting framework that:
- Uses the live bot's strategy and execution logic
- Simulates trades on historical data
- Tracks performance metrics and drawdowns
- Outputs detailed logs for analysis

Usage:
    from backtest import run_backtest
    
    final_balance, trades = run_backtest(
        data_folder='data',
        starting_balance=100.0
    )

The module is designed to be:
- Safe: No live API connections, all simulated
- Accurate: Uses actual bot logic for decisions
- Modular: Easy to extend with new data sources
- Logged: Complete trade history for analysis
"""

from backtest.backtest import run_backtest, BacktestConfig, BacktestResult
from backtest.data_loader import DataLoader, HistoricalInterval
from backtest.utils import (
    align_timestamp_to_interval,
    calculate_drawdown,
    format_backtest_trade,
    BacktestLogger
)

__all__ = [
    'run_backtest',
    'BacktestConfig',
    'BacktestResult',
    'DataLoader',
    'HistoricalInterval',
    'align_timestamp_to_interval',
    'calculate_drawdown',
    'format_backtest_trade',
    'BacktestLogger'
]

__version__ = '1.0.0'
