"""
Logger module for trade logging.

This module handles:
- CSV trade logging with all required fields
- Human-readable log formatting
- Log file management

All trades are logged for later analysis and performance tracking.
"""

import csv
import os
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

import config
from execution import Trade


# CSV column headers for trade log
TRADE_LOG_COLUMNS = [
    "timestamp",
    "trade_id",
    "market_id",
    "market_question",
    "side",
    "entry_odds",
    "fair_probability",
    "edge",
    "btc_price",
    "bet_size",
    "balance_before",
    "balance_after",
    "outcome",
    "payout",
    "profit_loss",
    "mode"
]


class TradeLogger:
    """
    Handles logging trades to CSV file.
    
    Creates a human-readable CSV log that can be analyzed in Excel,
    Google Sheets, or Python for performance tracking.
    """
    
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file or config.TRADE_LOG_FILE
        self._ensure_log_file_exists()
    
    def _ensure_log_file_exists(self):
        """Create the log file with headers if it doesn't exist."""
        if not os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(TRADE_LOG_COLUMNS)
                print(f"📝 Created trade log: {self.log_file}")
            except Exception as e:
                print(f"❌ Failed to create log file: {e}")
    
    def log_trade(self, trade: Trade):
        """
        Log a completed trade to CSV.
        
        Should be called after trade resolution when all data is available.
        
        Args:
            trade: The Trade object to log
        """
        try:
            # Calculate profit/loss
            if trade.outcome == "WIN":
                profit_loss = trade.payout - trade.bet_size
            elif trade.outcome == "LOSS":
                profit_loss = -trade.bet_size
            else:
                profit_loss = 0.0
            
            row = [
                trade.entry_time.isoformat(),
                trade.trade_id,
                trade.market_id,
                trade.market_question[:50],  # Truncate long questions
                trade.side,
                f"{trade.entry_odds:.4f}",
                f"{trade.fair_probability:.4f}",
                f"{trade.edge:.4f}",
                f"{trade.btc_price_at_entry:.2f}",
                f"{trade.bet_size:.2f}",
                f"{trade.balance_before:.2f}",
                f"{trade.balance_after:.2f}",
                trade.outcome or "PENDING",
                f"{trade.payout:.2f}",
                f"{profit_loss:.2f}",
                trade.mode
            ]
            
            with open(self.log_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row)
            
            if config.VERBOSE_LOGGING:
                print(f"📝 Logged trade: {trade.trade_id}")
                
        except Exception as e:
            print(f"❌ Failed to log trade: {e}")
    
    def log_event(self, event_type: str, message: str, data: Optional[Dict] = None):
        """
        Log a general event (not a trade).
        
        Useful for logging errors, restarts, configuration changes, etc.
        """
        timestamp = datetime.now().isoformat()
        log_line = f"[{timestamp}] [{event_type}] {message}"
        
        if data:
            log_line += f" | Data: {data}"
        
        if config.VERBOSE_LOGGING:
            print(f"📋 {log_line}")
        
        # Could also write to separate events log file
        # For v1, just console output


class PerformanceAnalyzer:
    """
    Analyzes trade log data for performance metrics.
    
    Can be used to review historical performance.
    """
    
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file or config.TRADE_LOG_FILE
    
    def load_trades(self) -> list:
        """Load all trades from the log file."""
        trades = []
        
        if not os.path.exists(self.log_file):
            return trades
        
        try:
            with open(self.log_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
        except Exception as e:
            print(f"❌ Failed to load trades: {e}")
        
        return trades
    
    def calculate_stats(self) -> Dict[str, Any]:
        """
        Calculate performance statistics from trade log.
        
        Returns a dictionary with key metrics.
        """
        trades = self.load_trades()
        
        if not trades:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_profit": 0.0,
                "avg_profit_per_trade": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "avg_edge": 0.0
            }
        
        wins = sum(1 for t in trades if t.get("outcome") == "WIN")
        losses = sum(1 for t in trades if t.get("outcome") == "LOSS")
        total = wins + losses
        
        profits = []
        edges = []
        
        for t in trades:
            try:
                pl = float(t.get("profit_loss", 0))
                profits.append(pl)
                edge = float(t.get("edge", 0))
                edges.append(edge)
            except (ValueError, TypeError):
                continue
        
        total_profit = sum(profits) if profits else 0.0
        avg_profit = total_profit / len(profits) if profits else 0.0
        best = max(profits) if profits else 0.0
        worst = min(profits) if profits else 0.0
        avg_edge = sum(edges) / len(edges) if edges else 0.0
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / total * 100) if total > 0 else 0.0,
            "total_profit": total_profit,
            "avg_profit_per_trade": avg_profit,
            "best_trade": best,
            "worst_trade": worst,
            "avg_edge": avg_edge * 100  # Convert to percentage
        }
    
    def print_summary(self):
        """Print a summary of performance statistics."""
        stats = self.calculate_stats()
        
        print("\n" + "="*60)
        print("📊 TRADE LOG ANALYSIS")
        print("="*60)
        print(f"Total Trades:     {stats['total_trades']}")
        print(f"Wins:             {stats['wins']}")
        print(f"Losses:           {stats['losses']}")
        print(f"Win Rate:         {stats['win_rate']:.1f}%")
        print(f"Total Profit:     ${stats['total_profit']:.2f}")
        print(f"Avg Per Trade:    ${stats['avg_profit_per_trade']:.2f}")
        print(f"Best Trade:       ${stats['best_trade']:.2f}")
        print(f"Worst Trade:      ${stats['worst_trade']:.2f}")
        print(f"Avg Edge:         {stats['avg_edge']:.2f}%")
        print("="*60 + "\n")


def format_trade_summary(trade: Trade) -> str:
    """
    Format a trade for console output.
    
    Returns a human-readable single-line summary.
    """
    outcome_emoji = {
        "WIN": "🎉",
        "LOSS": "😞",
        "PENDING": "⏳"
    }
    
    emoji = outcome_emoji.get(trade.outcome or "PENDING", "❓")
    
    if trade.outcome == "WIN":
        profit = trade.payout - trade.bet_size
        return (
            f"{emoji} {trade.side} | "
            f"Bet: ${trade.bet_size:.2f} @ {trade.entry_odds:.2f} | "
            f"Profit: +${profit:.2f} | "
            f"Balance: ${trade.balance_after:.2f}"
        )
    elif trade.outcome == "LOSS":
        return (
            f"{emoji} {trade.side} | "
            f"Bet: ${trade.bet_size:.2f} @ {trade.entry_odds:.2f} | "
            f"Loss: -${trade.bet_size:.2f} | "
            f"Balance: ${trade.balance_after:.2f}"
        )
    else:
        return (
            f"{emoji} {trade.side} | "
            f"Bet: ${trade.bet_size:.2f} @ {trade.entry_odds:.2f} | "
            f"Awaiting resolution..."
        )


# Singleton logger instance
_logger: Optional[TradeLogger] = None


def get_logger() -> TradeLogger:
    """Get or create the trade logger singleton."""
    global _logger
    if _logger is None:
        _logger = TradeLogger()
    return _logger


def log_trade(trade: Trade):
    """Convenience function to log a trade."""
    get_logger().log_trade(trade)


def analyze_performance():
    """Convenience function to print performance analysis."""
    analyzer = PerformanceAnalyzer()
    analyzer.print_summary()
