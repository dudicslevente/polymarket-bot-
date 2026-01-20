"""
Plotting module for backtest visualization.

This module provides functions to visualize backtest results:
- Equity curve over time
- Drawdown chart
- Win/loss distribution
- Trade edge vs outcome scatter

All plotting functions are optional and require matplotlib.
The backtest can run without this module if matplotlib is not installed.
"""

import os
from datetime import datetime
from typing import List, Optional, Tuple, Dict
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.utils import BacktestTrade, calculate_drawdown

# Check if matplotlib is available
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("⚠️ matplotlib not installed. Plotting functions will be disabled.")


def check_matplotlib():
    """Check if matplotlib is available and raise helpful error if not."""
    if not MATPLOTLIB_AVAILABLE:
        raise ImportError(
            "matplotlib is required for plotting. "
            "Install with: pip install matplotlib"
        )


def plot_equity_curve(
    trades: List[BacktestTrade],
    starting_balance: float = 100.0,
    title: str = "Backtest Equity Curve",
    save_path: Optional[str] = None,
    show: bool = True
) -> Optional[str]:
    """
    Plot the equity curve over time.
    
    Args:
        trades: List of BacktestTrade objects
        starting_balance: Initial balance
        title: Chart title
        save_path: Path to save the figure (optional)
        show: Whether to display the plot
    
    Returns:
        Path to saved figure, or None if not saved
    """
    check_matplotlib()
    
    if not trades:
        print("⚠️ No trades to plot.")
        return None
    
    # Build equity curve data
    dates = [trades[0].interval_start]
    balances = [starting_balance]
    
    for trade in trades:
        dates.append(trade.interval_start)
        balances.append(trade.balance_after)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Plot equity curve
    ax.plot(dates, balances, 'b-', linewidth=1.5, label='Balance')
    ax.fill_between(dates, starting_balance, balances, alpha=0.3, color='blue')
    
    # Add horizontal line at starting balance
    ax.axhline(y=starting_balance, color='gray', linestyle='--', alpha=0.5, label='Starting Balance')
    
    # Formatting
    ax.set_xlabel('Date')
    ax.set_ylabel('Balance ($)')
    ax.set_title(title)
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    
    # Format x-axis dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45)
    
    # Format y-axis as currency
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'${x:,.0f}'))
    
    plt.tight_layout()
    
    # Save if requested
    saved_path = None
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        saved_path = save_path
        print(f"📊 Saved equity curve to {save_path}")
    
    if show:
        plt.show()
    else:
        plt.close()
    
    return saved_path


def plot_drawdown(
    trades: List[BacktestTrade],
    starting_balance: float = 100.0,
    title: str = "Drawdown Over Time",
    save_path: Optional[str] = None,
    show: bool = True
) -> Optional[str]:
    """
    Plot drawdown chart showing decline from peaks.
    
    Args:
        trades: List of BacktestTrade objects
        starting_balance: Initial balance
        title: Chart title
        save_path: Path to save the figure (optional)
        show: Whether to display the plot
    
    Returns:
        Path to saved figure, or None if not saved
    """
    check_matplotlib()
    
    if not trades:
        print("⚠️ No trades to plot.")
        return None
    
    # Build equity curve
    dates = [trades[0].interval_start]
    balances = [starting_balance]
    
    for trade in trades:
        dates.append(trade.interval_start)
        balances.append(trade.balance_after)
    
    # Calculate drawdown at each point
    peak = balances[0]
    drawdowns = []
    
    for balance in balances:
        if balance > peak:
            peak = balance
        dd_pct = (peak - balance) / peak * 100 if peak > 0 else 0
        drawdowns.append(-dd_pct)  # Negative for visual
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 4))
    
    # Plot drawdown
    ax.fill_between(dates, 0, drawdowns, color='red', alpha=0.5)
    ax.plot(dates, drawdowns, 'r-', linewidth=1)
    
    # Formatting
    ax.set_xlabel('Date')
    ax.set_ylabel('Drawdown (%)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    
    # Format x-axis dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45)
    
    # Set y-axis to show negative values
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:.1f}%'))
    
    plt.tight_layout()
    
    # Save if requested
    saved_path = None
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        saved_path = save_path
        print(f"📊 Saved drawdown chart to {save_path}")
    
    if show:
        plt.show()
    else:
        plt.close()
    
    return saved_path


def plot_trade_distribution(
    trades: List[BacktestTrade],
    title: str = "Trade P&L Distribution",
    save_path: Optional[str] = None,
    show: bool = True
) -> Optional[str]:
    """
    Plot histogram of trade profit/loss.
    
    Args:
        trades: List of BacktestTrade objects
        title: Chart title
        save_path: Path to save the figure (optional)
        show: Whether to display the plot
    
    Returns:
        Path to saved figure, or None if not saved
    """
    check_matplotlib()
    
    if not trades:
        print("⚠️ No trades to plot.")
        return None
    
    # Extract P&L values
    pnls = [t.profit_loss for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Plot histogram
    bins = 30
    ax.hist(wins, bins=bins, alpha=0.7, color='green', label=f'Wins ({len(wins)})')
    ax.hist(losses, bins=bins, alpha=0.7, color='red', label=f'Losses ({len(losses)})')
    
    # Add vertical line at 0
    ax.axvline(x=0, color='black', linestyle='-', linewidth=1)
    
    # Formatting
    ax.set_xlabel('Profit/Loss ($)')
    ax.set_ylabel('Frequency')
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save if requested
    saved_path = None
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        saved_path = save_path
        print(f"📊 Saved P&L distribution to {save_path}")
    
    if show:
        plt.show()
    else:
        plt.close()
    
    return saved_path


def plot_edge_vs_outcome(
    trades: List[BacktestTrade],
    title: str = "Edge vs Trade Outcome",
    save_path: Optional[str] = None,
    show: bool = True
) -> Optional[str]:
    """
    Scatter plot of edge at entry vs trade outcome.
    
    Args:
        trades: List of BacktestTrade objects
        title: Chart title
        save_path: Path to save the figure (optional)
        show: Whether to display the plot
    
    Returns:
        Path to saved figure, or None if not saved
    """
    check_matplotlib()
    
    if not trades:
        print("⚠️ No trades to plot.")
        return None
    
    # Separate wins and losses
    win_edges = [t.edge * 100 for t in trades if t.outcome == "WIN"]
    win_pnls = [t.profit_loss for t in trades if t.outcome == "WIN"]
    loss_edges = [t.edge * 100 for t in trades if t.outcome == "LOSS"]
    loss_pnls = [t.profit_loss for t in trades if t.outcome == "LOSS"]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Scatter plots
    ax.scatter(win_edges, win_pnls, c='green', alpha=0.6, label='Wins', s=50)
    ax.scatter(loss_edges, loss_pnls, c='red', alpha=0.6, label='Losses', s=50)
    
    # Add horizontal line at 0
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    
    # Formatting
    ax.set_xlabel('Edge at Entry (%)')
    ax.set_ylabel('Profit/Loss ($)')
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save if requested
    saved_path = None
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        saved_path = save_path
        print(f"📊 Saved edge vs outcome to {save_path}")
    
    if show:
        plt.show()
    else:
        plt.close()
    
    return saved_path


def plot_win_streaks(
    trades: List[BacktestTrade],
    title: str = "Win/Loss Streaks",
    save_path: Optional[str] = None,
    show: bool = True
) -> Optional[str]:
    """
    Plot win/loss streaks over time.
    
    Args:
        trades: List of BacktestTrade objects
        title: Chart title
        save_path: Path to save the figure (optional)
        show: Whether to display the plot
    
    Returns:
        Path to saved figure, or None if not saved
    """
    check_matplotlib()
    
    if not trades:
        print("⚠️ No trades to plot.")
        return None
    
    # Calculate cumulative win count (resets on loss)
    streaks = []
    current_streak = 0
    
    for trade in trades:
        if trade.outcome == "WIN":
            current_streak = max(0, current_streak) + 1
        else:
            current_streak = min(0, current_streak) - 1
        streaks.append(current_streak)
    
    dates = [t.interval_start for t in trades]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 5))
    
    # Color based on positive/negative
    colors = ['green' if s > 0 else 'red' for s in streaks]
    
    ax.bar(range(len(streaks)), streaks, color=colors, alpha=0.7, width=1.0)
    
    # Formatting
    ax.set_xlabel('Trade Number')
    ax.set_ylabel('Streak Length')
    ax.set_title(title)
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    
    # Save if requested
    saved_path = None
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        saved_path = save_path
        print(f"📊 Saved win streaks to {save_path}")
    
    if show:
        plt.show()
    else:
        plt.close()
    
    return saved_path


def plot_all(
    trades: List[BacktestTrade],
    starting_balance: float = 100.0,
    output_folder: str = "backtest_plots",
    show: bool = False
) -> List[str]:
    """
    Generate all plots and save to a folder.
    
    Args:
        trades: List of BacktestTrade objects
        starting_balance: Initial balance
        output_folder: Folder to save plots
        show: Whether to display plots
    
    Returns:
        List of saved file paths
    """
    check_matplotlib()
    
    os.makedirs(output_folder, exist_ok=True)
    saved_files = []
    
    # Generate each plot
    plots = [
        ("equity_curve.png", lambda: plot_equity_curve(
            trades, starting_balance,
            save_path=os.path.join(output_folder, "equity_curve.png"),
            show=show
        )),
        ("drawdown.png", lambda: plot_drawdown(
            trades, starting_balance,
            save_path=os.path.join(output_folder, "drawdown.png"),
            show=show
        )),
        ("pnl_distribution.png", lambda: plot_trade_distribution(
            trades,
            save_path=os.path.join(output_folder, "pnl_distribution.png"),
            show=show
        )),
        ("edge_vs_outcome.png", lambda: plot_edge_vs_outcome(
            trades,
            save_path=os.path.join(output_folder, "edge_vs_outcome.png"),
            show=show
        )),
        ("win_streaks.png", lambda: plot_win_streaks(
            trades,
            save_path=os.path.join(output_folder, "win_streaks.png"),
            show=show
        )),
    ]
    
    for name, plot_func in plots:
        try:
            result = plot_func()
            if result:
                saved_files.append(result)
        except Exception as e:
            print(f"⚠️ Error generating {name}: {e}")
    
    print(f"\n📁 Saved {len(saved_files)} plots to {output_folder}/")
    return saved_files


def plot_monthly_returns(
    trades: List[BacktestTrade],
    starting_balance: float = 100.0,
    title: str = "Monthly Returns",
    save_path: Optional[str] = None,
    show: bool = True
) -> Optional[str]:
    """
    Plot monthly returns as a bar chart.
    
    Args:
        trades: List of BacktestTrade objects
        starting_balance: Initial balance
        title: Chart title
        save_path: Path to save the figure (optional)
        show: Whether to display the plot
    
    Returns:
        Path to saved figure, or None if not saved
    """
    check_matplotlib()
    
    if not trades:
        print("⚠️ No trades to plot.")
        return None
    
    # Group trades by month
    monthly_pnl: Dict[str, float] = {}
    
    for trade in trades:
        month_key = trade.interval_start.strftime('%Y-%m')
        if month_key not in monthly_pnl:
            monthly_pnl[month_key] = 0.0
        monthly_pnl[month_key] += trade.profit_loss
    
    months = list(monthly_pnl.keys())
    pnls = list(monthly_pnl.values())
    colors = ['green' if p > 0 else 'red' for p in pnls]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 5))
    
    ax.bar(months, pnls, color=colors, alpha=0.7)
    
    # Formatting
    ax.set_xlabel('Month')
    ax.set_ylabel('P&L ($)')
    ax.set_title(title)
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax.grid(True, alpha=0.3, axis='y')
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    # Save if requested
    saved_path = None
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        saved_path = save_path
        print(f"📊 Saved monthly returns to {save_path}")
    
    if show:
        plt.show()
    else:
        plt.close()
    
    return saved_path
