"""
Execution module for trade placement and simulation.

This module handles:
- Trade execution (simulated in TEST_MODE, real in LIVE mode)
- Position tracking
- Balance management
- Trade outcome simulation

The execution logic is deliberately simple:
- Market orders only (no limit orders)
- No early exits or hedging
- Wait for market resolution
"""

import random
import time
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import config
from market import Market, PolymarketClient
from strategy import TradeSignal


class TradeStatus(Enum):
    """Status of a trade."""
    PENDING = "pending"
    EXECUTED = "executed"
    RESOLVED_WIN = "resolved_win"
    RESOLVED_LOSS = "resolved_loss"
    FAILED = "failed"


@dataclass
class Trade:
    """
    Represents an executed trade with all tracking information.
    """
    trade_id: str
    market_id: str
    market_question: str
    side: str  # "UP" or "DOWN"
    entry_odds: float
    fair_probability: float
    edge: float
    btc_price_at_entry: float
    bet_size: float
    balance_before: float
    balance_after: float
    status: TradeStatus
    entry_time: datetime
    resolution_time: Optional[datetime] = None
    outcome: Optional[str] = None  # "WIN" or "LOSS"
    payout: float = 0.0
    mode: str = "TEST"


@dataclass
class ExecutionState:
    """
    Tracks the current state of the execution engine.
    
    Maintains virtual balance, active trades, and cooldown timers.
    """
    balance: float = config.INITIAL_VIRTUAL_BALANCE
    trades: List[Trade] = field(default_factory=list)
    active_trades: Dict[str, Trade] = field(default_factory=dict)
    last_trade_time: Optional[datetime] = None
    total_trades: int = 0
    wins: int = 0
    losses: int = 0


class ExecutionEngine:
    """
    Handles all trade execution logic.
    
    In TEST_MODE: Simulates trades and resolutions
    In LIVE mode: Places real orders on Polymarket
    """
    
    def __init__(self, polymarket_client: PolymarketClient):
        self.polymarket = polymarket_client
        self.state = ExecutionState()
        
        # Load starting balance
        if config.TEST_MODE:
            self.state.balance = config.INITIAL_VIRTUAL_BALANCE
            print(f"💰 Starting virtual balance: ${self.state.balance:.2f}")
        else:
            # In live mode, would fetch real balance from wallet
            # For now, use initial as placeholder
            self.state.balance = config.INITIAL_VIRTUAL_BALANCE
    
    def is_in_cooldown(self) -> bool:
        """
        Check if we're in cooldown period between trades.
        
        Cooldown prevents overtrading and ensures market conditions
        have time to change between trades.
        """
        if self.state.last_trade_time is None:
            return False
        
        now = datetime.now(timezone.utc)
        elapsed = (now - self.state.last_trade_time).total_seconds()
        
        if elapsed < config.TRADE_COOLDOWN_SECONDS:
            remaining = config.TRADE_COOLDOWN_SECONDS - elapsed
            if config.VERBOSE_LOGGING:
                print(f"⏳ Cooldown: {remaining:.0f}s remaining")
            return True
        
        return False
    
    def can_trade(self, bet_size: float) -> bool:
        """
        Check if we can execute a trade of the given size.
        
        Checks:
        1. Balance is sufficient
        2. Not in cooldown
        """
        if self.state.balance < config.MIN_BALANCE_TO_TRADE:
            print(f"❌ Balance too low: ${self.state.balance:.2f} < ${config.MIN_BALANCE_TO_TRADE:.2f}")
            return False
        
        if bet_size > self.state.balance:
            print(f"❌ Bet size ${bet_size:.2f} exceeds balance ${self.state.balance:.2f}")
            return False
        
        if self.is_in_cooldown():
            return False
        
        return True
    
    def execute_trade(
        self,
        signal: TradeSignal,
        bet_size: float
    ) -> Optional[Trade]:
        """
        Execute a trade based on the signal.
        
        In TEST_MODE: Simulates the trade
        In LIVE mode: Places real order on Polymarket
        
        Args:
            signal: The trade signal with all relevant data
            bet_size: Amount to bet in USD
        
        Returns:
            Trade object if successful, None if failed
        """
        if not self.can_trade(bet_size):
            return None
        
        # Create trade ID
        trade_id = f"T{int(time.time()*1000)}"
        
        # Record balance before trade
        balance_before = self.state.balance
        
        # Deduct bet from balance
        self.state.balance -= bet_size
        
        # Create trade record
        trade = Trade(
            trade_id=trade_id,
            market_id=signal.market.market_id,
            market_question=signal.market.question,
            side=signal.side,
            entry_odds=signal.market_odds,
            fair_probability=signal.fair_probability,
            edge=signal.edge,
            btc_price_at_entry=signal.btc_price,
            bet_size=bet_size,
            balance_before=balance_before,
            balance_after=self.state.balance,  # Will be updated at resolution
            status=TradeStatus.PENDING,
            entry_time=datetime.now(timezone.utc),
            mode="TEST" if config.TEST_MODE else "LIVE"
        )
        
        # Execute based on mode
        if config.TEST_MODE:
            success = self._simulate_execution(trade)
        else:
            success = self._execute_live(trade, signal)
        
        if success:
            trade.status = TradeStatus.EXECUTED
            self.state.active_trades[trade.trade_id] = trade
            self.state.trades.append(trade)
            self.state.total_trades += 1
            self.state.last_trade_time = datetime.now(timezone.utc)
            
            # Mark market as traded
            self.polymarket.mark_as_traded(signal.market)
            
            print(f"✅ Trade executed: {trade.side} ${bet_size:.2f} @ {trade.entry_odds:.3f}")
            print(f"   Balance: ${balance_before:.2f} → ${self.state.balance:.2f}")
            
            return trade
        else:
            # Refund on failure
            self.state.balance = balance_before
            trade.status = TradeStatus.FAILED
            print(f"❌ Trade execution failed")
            return None
    
    def _simulate_execution(self, trade: Trade) -> bool:
        """
        Simulate trade execution in TEST_MODE.
        
        Always succeeds instantly (no slippage simulation in v1).
        """
        # In simulation, trades always execute successfully
        if config.VERBOSE_LOGGING:
            print(f"🎮 [SIMULATION] Executing trade: {trade.side} ${trade.bet_size:.2f}")
        return True
    
    def _execute_live(self, trade: Trade, signal: TradeSignal) -> bool:
        """
        Execute a live trade on Polymarket.
        
        Returns True if order was placed successfully.
        """
        # Determine which side to buy
        # For "UP" bias, we buy the "yes" token
        # For "DOWN" bias, we buy the "no" token
        polymarket_side = "yes" if trade.side == "UP" else "no"
        
        result = self.polymarket.place_order(
            market=signal.market,
            side=polymarket_side,
            amount_usd=trade.bet_size
        )
        
        return result is not None
    
    def check_and_resolve_trades(self):
        """
        Check active trades and resolve any that have completed.
        
        In TEST_MODE: Simulates resolution based on the market's end time
        In LIVE mode: Would query Polymarket for actual resolution
        """
        now = datetime.now(timezone.utc)
        resolved_trades = []
        
        for trade_id, trade in list(self.state.active_trades.items()):
            # Find the market for this trade
            # In a real implementation, we'd track the market end time
            # For simulation, we'll resolve after 15 minutes (900 seconds)
            
            time_since_entry = (now - trade.entry_time).total_seconds()
            
            # Check if market should be resolved (15 min = 900 seconds)
            # Adding buffer for processing
            if time_since_entry >= 900:  # 15 minutes
                self._resolve_trade(trade)
                resolved_trades.append(trade_id)
        
        # Remove resolved trades from active
        for trade_id in resolved_trades:
            del self.state.active_trades[trade_id]
    
    def _resolve_trade(self, trade: Trade):
        """
        Resolve a trade and update balance.
        
        In TEST_MODE: Simulates win/loss probabilistically
        In LIVE mode: Would get actual resolution from Polymarket
        """
        if config.TEST_MODE:
            outcome = self._simulate_resolution(trade)
        else:
            outcome = self._get_live_resolution(trade)
        
        trade.resolution_time = datetime.now(timezone.utc)
        
        if outcome == "WIN":
            trade.outcome = "WIN"
            trade.status = TradeStatus.RESOLVED_WIN
            
            # Calculate payout (bet size / odds = shares, shares * 1 = payout on win)
            # Payout = bet_size / entry_odds (since we get $1 per share if win)
            payout = trade.bet_size / trade.entry_odds
            
            # Apply fee
            payout *= (1 - config.ESTIMATED_FEE_PERCENT)
            
            trade.payout = payout
            self.state.balance += payout
            self.state.wins += 1
            
            profit = payout - trade.bet_size
            print(f"🎉 WIN: {trade.side} | Profit: ${profit:.2f} | Balance: ${self.state.balance:.2f}")
            
        else:
            trade.outcome = "LOSS"
            trade.status = TradeStatus.RESOLVED_LOSS
            trade.payout = 0.0
            self.state.losses += 1
            
            print(f"😞 LOSS: {trade.side} | Lost: ${trade.bet_size:.2f} | Balance: ${self.state.balance:.2f}")
        
        trade.balance_after = self.state.balance
    
    def _simulate_resolution(self, trade: Trade) -> str:
        """
        Simulate trade resolution in TEST_MODE.
        
        Uses the estimated fair probability to determine win/loss.
        This gives realistic win rates based on our edge estimates.
        
        Note: In reality, markets are efficient and our estimated
        fair probability is just that - an estimate. This simulation
        assumes our estimates are somewhat accurate.
        """
        # Use fair probability as win chance
        # This is generous - in reality, we might overestimate our edge
        win_probability = trade.fair_probability
        
        # Add some noise to simulate uncertainty
        # Actual win rate might be slightly higher or lower
        noise = random.uniform(-0.05, 0.05)
        adjusted_probability = max(0.40, min(0.65, win_probability + noise))
        
        # Roll the dice
        roll = random.random()
        
        if roll < adjusted_probability:
            return "WIN"
        else:
            return "LOSS"
    
    def _get_live_resolution(self, trade: Trade) -> str:
        """
        Get actual resolution from Polymarket in LIVE mode.
        
        This would query the market for its resolution.
        For now, returns "UNKNOWN" - needs real API integration.
        """
        # In a real implementation:
        # 1. Query Polymarket API for market resolution
        # 2. Check if our position won or lost
        # 3. Return "WIN" or "LOSS"
        
        # Placeholder - would need actual API call
        print("⚠️ Live resolution check not fully implemented")
        return "LOSS"  # Conservative default
    
    def force_resolve_trade_for_simulation(self, trade: Trade, minutes_passed: float = 15.0):
        """
        Force resolve a trade for simulation purposes.
        
        Called when simulating fast-forward through market resolution.
        
        Args:
            trade: The trade to resolve
            minutes_passed: Simulated time passed since entry
        """
        if trade.status != TradeStatus.EXECUTED:
            return
        
        self._resolve_trade(trade)
        
        if trade.trade_id in self.state.active_trades:
            del self.state.active_trades[trade.trade_id]
    
    def get_stats(self) -> Dict:
        """
        Get current execution statistics.
        
        Returns a dictionary with key metrics.
        """
        win_rate = 0.0
        if self.state.total_trades > 0:
            win_rate = (self.state.wins / self.state.total_trades) * 100
        
        return {
            "balance": self.state.balance,
            "starting_balance": config.INITIAL_VIRTUAL_BALANCE,
            "total_trades": self.state.total_trades,
            "wins": self.state.wins,
            "losses": self.state.losses,
            "win_rate": win_rate,
            "active_trades": len(self.state.active_trades),
            "pnl": self.state.balance - config.INITIAL_VIRTUAL_BALANCE,
            "pnl_percent": ((self.state.balance / config.INITIAL_VIRTUAL_BALANCE) - 1) * 100
        }
    
    def print_stats(self):
        """Print current stats to console."""
        stats = self.get_stats()
        
        pnl_symbol = "+" if stats["pnl"] >= 0 else ""
        
        print("\n" + "─"*50)
        print("📊 EXECUTION STATS")
        print("─"*50)
        print(f"Balance:      ${stats['balance']:.2f}")
        print(f"P&L:          {pnl_symbol}${stats['pnl']:.2f} ({pnl_symbol}{stats['pnl_percent']:.1f}%)")
        print(f"Trades:       {stats['total_trades']} ({stats['wins']}W / {stats['losses']}L)")
        print(f"Win Rate:     {stats['win_rate']:.1f}%")
        print(f"Active:       {stats['active_trades']}")
        print("─"*50 + "\n")


def confirm_live_trading() -> bool:
    """
    Display warning and require confirmation for live trading.
    
    This is a safety feature to prevent accidental live trading.
    """
    print("\n" + "!"*60)
    print("!!! WARNING: LIVE TRADING MODE !!!")
    print("!"*60)
    print()
    print("You are about to trade with REAL MONEY on Polymarket.")
    print("This bot is experimental and may lose money.")
    print()
    print("By proceeding, you acknowledge:")
    print("1. You understand the risks of algorithmic trading")
    print("2. You can afford to lose your entire balance")
    print("3. This is not financial advice")
    print()
    
    confirmation = input("Type 'I UNDERSTAND THE RISKS' to continue: ")
    
    if confirmation.strip() == "I UNDERSTAND THE RISKS":
        print("\n✅ Live trading confirmed. Starting bot...\n")
        return True
    else:
        print("\n❌ Confirmation failed. Exiting.\n")
        return False
