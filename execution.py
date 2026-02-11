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
    # LIVE mode fields
    order_id: Optional[str] = None  # Polymarket order ID
    order_status: Optional[str] = None  # Order status from CLOB
    filled_price: Optional[float] = None  # Actual fill price
    filled_shares: Optional[float] = None  # Actual shares filled
    # Token tracking for redemption (CRITICAL for LIVE mode)
    token_id: Optional[str] = None  # Token ID we bought - needed for redemption
    condition_id: Optional[str] = None  # Market condition ID for resolution
    redemption_status: Optional[str] = None  # "PENDING", "REDEEMED", "FAILED"
    redemption_amount: Optional[float] = None  # Amount redeemed in USDC


@dataclass
class ExecutionState:
    """
    Tracks the current state of the execution engine.
    
    Maintains virtual balance, active trades, and cooldown timers.
    
    Balance tracking:
    - `balance`: The actual available balance for trading (deducted when bet placed)
    - `resolved_balance`: Balance after all resolved trades (used for CSV logging)
    
    This ensures balance_before/balance_after in CSV form a consistent sequential
    chain based on resolution order, not entry order.
    """
    balance: float = config.INITIAL_VIRTUAL_BALANCE
    resolved_balance: float = config.INITIAL_VIRTUAL_BALANCE  # Balance after resolved trades (for CSV)
    session_starting_balance: float = config.INITIAL_VIRTUAL_BALANCE  # Balance when bot started
    trades: List[Trade] = field(default_factory=list)
    active_trades: Dict[str, Trade] = field(default_factory=dict)
    last_trade_time: Optional[datetime] = None
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    
    # Daily tracking (resets at midnight UTC)
    daily_starting_balance: float = config.INITIAL_VIRTUAL_BALANCE
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    daily_pnl: float = 0.0
    daily_reset_date: Optional[datetime] = None
    
    # Streak tracking
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    
    # Safety limits
    trading_paused: bool = False
    pause_reason: Optional[str] = None
    pause_until: Optional[datetime] = None


class ExecutionEngine:
    """
    Handles all trade execution logic.
    
    In TEST_MODE: Simulates trades and resolutions
    In LIVE mode: Places real orders on Polymarket
    """
    
    def __init__(self, polymarket_client: PolymarketClient):
        self.polymarket = polymarket_client
        self.state = ExecutionState()
        
        # Initialize daily tracking
        now = datetime.now(timezone.utc)
        self.state.daily_reset_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Load starting balance
        if config.TEST_MODE:
            self.state.balance = config.INITIAL_VIRTUAL_BALANCE
            self.state.resolved_balance = config.INITIAL_VIRTUAL_BALANCE
            self.state.session_starting_balance = config.INITIAL_VIRTUAL_BALANCE
            self.state.daily_starting_balance = config.INITIAL_VIRTUAL_BALANCE
            print(f"💰 Starting virtual balance: ${self.state.balance:.2f}")
        else:
            # In LIVE mode, fetch real balance from Polymarket
            self._initialize_live_balance()
    
    def _initialize_live_balance(self):
        """
        Initialize balance from Polymarket in LIVE mode.
        
        Fetches real USDC balance and validates it meets minimum requirements.
        Raises RuntimeError if balance cannot be fetched or is too low.
        """
        print("💰 Fetching live balance from Polymarket...")
        
        real_balance = self.polymarket.get_usdc_balance()
        
        if real_balance is None:
            raise RuntimeError(
                "❌ Could not fetch wallet balance from Polymarket.\n"
                "   Please check:\n"
                "   1. Your API credentials are correct\n"
                "   2. Your wallet is connected to Polymarket\n"
                "   3. You have internet connectivity"
            )
        
        if real_balance < config.MIN_BALANCE_TO_TRADE:
            raise RuntimeError(
                f"❌ Insufficient balance for trading.\n"
                f"   Current balance: ${real_balance:.2f}\n"
                f"   Minimum required: ${config.MIN_BALANCE_TO_TRADE:.2f}\n"
                f"   Please deposit more USDC to your Polymarket account."
            )
        
        self.state.balance = real_balance
        self.state.resolved_balance = real_balance
        self.state.session_starting_balance = real_balance
        self.state.daily_starting_balance = real_balance
        
        print(f"✅ Live wallet balance: ${real_balance:.2f}")
    
    def refresh_balance(self) -> bool:
        """
        Refresh the balance from Polymarket.
        
        Useful to sync balance after trades or to verify funds are still available.
        
        Returns:
            True if balance was refreshed successfully, False otherwise
        """
        if config.TEST_MODE:
            # In test mode, balance is managed internally
            return True
        
        new_balance = self.polymarket.get_usdc_balance()
        
        if new_balance is None:
            print("⚠️ Could not refresh balance from API")
            return False
        
        old_balance = self.state.balance
        self.state.balance = new_balance
        
        # Only update resolved_balance if no active trades
        # (active trades will update it upon resolution)
        if not self.state.active_trades:
            self.state.resolved_balance = new_balance
        
        if config.VERBOSE_LOGGING:
            diff = new_balance - old_balance
            if abs(diff) > 0.01:
                print(f"💰 Balance updated: ${old_balance:.2f} → ${new_balance:.2f} ({diff:+.2f})")
        
        return True

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
        1. Trading not paused (safety limits)
        2. Daily reset check
        3. Balance is sufficient
        4. Not in cooldown
        5. Daily loss limit not exceeded
        6. Consecutive loss limit not exceeded
        7. Daily trade limit not exceeded
        """
        # Check if trading is paused
        if self.state.trading_paused:
            if self.state.pause_until:
                now = datetime.now(timezone.utc)
                if now >= self.state.pause_until:
                    # Pause expired, resume trading
                    self._resume_trading()
                else:
                    remaining = (self.state.pause_until - now).total_seconds()
                    print(f"⛔ Trading paused: {self.state.pause_reason}")
                    print(f"   Resumes in {remaining/60:.0f} minutes")
                    return False
            else:
                print(f"⛔ Trading paused: {self.state.pause_reason}")
                return False
        
        # Check for daily reset (midnight UTC)
        self._check_daily_reset()
        
        # Check balance
        if self.state.balance < config.MIN_BALANCE_TO_TRADE:
            print(f"❌ Balance too low: ${self.state.balance:.2f} < ${config.MIN_BALANCE_TO_TRADE:.2f}")
            return False
        
        if bet_size > self.state.balance:
            print(f"❌ Bet size ${bet_size:.2f} exceeds balance ${self.state.balance:.2f}")
            return False
        
        # Check cooldown
        if self.is_in_cooldown():
            return False
        
        # Check daily loss limit
        if not self._check_daily_loss_limit():
            return False
        
        # Check consecutive losses
        if not self._check_consecutive_losses():
            return False
        
        # Check daily trade limit
        if not self._check_daily_trade_limit():
            return False
        
        return True
    
    def _check_daily_reset(self):
        """
        Check if we've crossed midnight UTC and reset daily counters.
        """
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if self.state.daily_reset_date is None or self.state.daily_reset_date < today:
            # New day - reset daily counters
            if self.state.daily_reset_date is not None:
                print(f"📅 New day detected - resetting daily counters")
                print(f"   Yesterday: {self.state.daily_trades} trades, "
                      f"PnL: ${self.state.daily_pnl:+.2f}")
            
            self.state.daily_reset_date = today
            self.state.daily_starting_balance = self.state.balance
            self.state.daily_trades = 0
            self.state.daily_wins = 0
            self.state.daily_losses = 0
            self.state.daily_pnl = 0.0
            
            # Resume trading if paused for daily limit
            if self.state.trading_paused and "daily" in (self.state.pause_reason or "").lower():
                self._resume_trading()
    
    def _check_daily_loss_limit(self) -> bool:
        """
        Check if daily loss limit has been exceeded.
        
        Returns:
            True if we can trade, False if limit exceeded
        """
        # Calculate current daily loss
        daily_loss = -self.state.daily_pnl if self.state.daily_pnl < 0 else 0
        
        # Check percentage-based limit
        if config.DAILY_LOSS_LIMIT_PERCENT > 0:
            max_loss = self.state.daily_starting_balance * config.DAILY_LOSS_LIMIT_PERCENT
            if daily_loss >= max_loss:
                self._pause_trading(
                    f"Daily loss limit ({config.DAILY_LOSS_LIMIT_PERCENT*100:.0f}%) exceeded: "
                    f"${daily_loss:.2f} >= ${max_loss:.2f}",
                    cooldown_seconds=config.LOSS_LIMIT_COOLDOWN_SECONDS
                )
                return False
        
        # Check absolute USD limit
        if config.DAILY_LOSS_LIMIT_USD > 0:
            if daily_loss >= config.DAILY_LOSS_LIMIT_USD:
                self._pause_trading(
                    f"Daily loss limit exceeded: ${daily_loss:.2f} >= ${config.DAILY_LOSS_LIMIT_USD:.2f}",
                    cooldown_seconds=config.LOSS_LIMIT_COOLDOWN_SECONDS
                )
                return False
        
        return True
    
    def _check_consecutive_losses(self) -> bool:
        """
        Check if we've hit the consecutive loss limit.
        
        Returns:
            True if we can trade, False if limit exceeded
        """
        if config.MAX_CONSECUTIVE_LOSSES <= 0:
            return True  # Disabled
        
        if self.state.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
            self._pause_trading(
                f"Consecutive loss limit ({config.MAX_CONSECUTIVE_LOSSES}) reached",
                cooldown_seconds=config.LOSS_LIMIT_COOLDOWN_SECONDS
            )
            return False
        
        return True
    
    def _check_daily_trade_limit(self) -> bool:
        """
        Check if we've hit the daily trade limit.
        
        Returns:
            True if we can trade, False if limit exceeded
        """
        if config.MAX_TRADES_PER_DAY <= 0:
            return True  # Disabled
        
        if self.state.daily_trades >= config.MAX_TRADES_PER_DAY:
            print(f"⚠️ Daily trade limit reached: {self.state.daily_trades} >= {config.MAX_TRADES_PER_DAY}")
            return False
        
        return True
    
    def _pause_trading(self, reason: str, cooldown_seconds: int = 0):
        """
        Pause trading with a reason and optional cooldown.
        
        Args:
            reason: Why trading was paused
            cooldown_seconds: How long to pause (0 = until manual resume or daily reset)
        """
        self.state.trading_paused = True
        self.state.pause_reason = reason
        
        if cooldown_seconds > 0:
            self.state.pause_until = datetime.now(timezone.utc) + \
                                     __import__('datetime').timedelta(seconds=cooldown_seconds)
            print(f"⛔ TRADING PAUSED: {reason}")
            print(f"   Will auto-resume in {cooldown_seconds/60:.0f} minutes")
        else:
            self.state.pause_until = None
            print(f"⛔ TRADING PAUSED: {reason}")
            print(f"   Will resume at next daily reset (midnight UTC)")
    
    def _resume_trading(self):
        """
        Resume trading after a pause.
        """
        if self.state.trading_paused:
            print(f"✅ Trading resumed (was paused: {self.state.pause_reason})")
        
        self.state.trading_paused = False
        self.state.pause_reason = None
        self.state.pause_until = None
    
    def get_daily_stats(self) -> Dict:
        """
        Get current daily trading statistics.
        
        Returns:
            Dict with daily stats
        """
        self._check_daily_reset()
        
        return {
            "date": self.state.daily_reset_date,
            "starting_balance": self.state.daily_starting_balance,
            "current_balance": self.state.balance,
            "daily_pnl": self.state.daily_pnl,
            "daily_pnl_percent": (self.state.daily_pnl / self.state.daily_starting_balance * 100) 
                                 if self.state.daily_starting_balance > 0 else 0,
            "trades": self.state.daily_trades,
            "wins": self.state.daily_wins,
            "losses": self.state.daily_losses,
            "win_rate": (self.state.daily_wins / self.state.daily_trades * 100) 
                        if self.state.daily_trades > 0 else 0,
            "consecutive_losses": self.state.consecutive_losses,
            "consecutive_wins": self.state.consecutive_wins,
            "trading_paused": self.state.trading_paused,
            "pause_reason": self.state.pause_reason,
        }
    
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
        
        # Store actual balance before deduction for restoration on failure
        actual_balance_before = self.state.balance
        
        # Deduct bet from actual trading balance
        # Note: resolved_balance is NOT modified here - only at resolution time
        # This ensures balance_before/balance_after form a correct chain in CSV
        self.state.balance -= bet_size
        
        # Create trade record
        # balance_before and balance_after will be set at resolution time
        # This ensures correct sequential tracking even when trades overlap
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
            balance_before=0.0,  # Will be set at resolution time
            balance_after=0.0,   # Will be set at resolution time
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
            
            # If bet_size was adjusted (e.g., to meet minimum share requirements),
            # update the balance to reflect the actual amount spent
            if trade.bet_size != bet_size:
                # Restore the original deduction and apply the correct one
                self.state.balance = actual_balance_before - trade.bet_size
            
            print(f"✅ Trade executed: {trade.side} ${trade.bet_size:.2f} @ {trade.entry_odds:.3f}")
            print(f"   Available balance: ${self.state.balance:.2f}")
            
            return trade
        else:
            # Refund on failure - restore actual balance
            self.state.balance = actual_balance_before
            trade.status = TradeStatus.FAILED
            print(f"❌ Trade execution failed - balance restored to ${actual_balance_before:.2f}")
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
        
        This method:
        1. Determines the correct side to buy
        2. Stores token ID for later redemption
        3. Places the order via the CLOB API
        4. Waits for order to be filled
        5. Stores order information in the trade object
        6. Syncs balance after execution
        7. Returns success/failure status
        
        Args:
            trade: The Trade object to execute
            signal: The TradeSignal with market information
            
        Returns:
            True if order was filled, False otherwise
        """
        # Determine which side to buy based on our prediction
        # For BTC 15-min markets:
        #   - "UP" prediction = buy the "up" token
        #   - "DOWN" prediction = buy the "down" token
        # 
        # Note: BTC markets use "up"/"down", not "yes"/"no"
        polymarket_side = trade.side.lower()  # "up" or "down"
        
        # CRITICAL: Store token ID and condition ID for later redemption
        if hasattr(signal.market, 'tokens') and signal.market.tokens:
            trade.token_id = signal.market.tokens.get(polymarket_side)
            if not trade.token_id:
                print(f"❌ No token ID found for side: {polymarket_side}")
                print(f"   Available tokens: {list(signal.market.tokens.keys())}")
                return False
        else:
            print("❌ Market has no token information - cannot execute LIVE trade")
            return False
        
        # Store condition ID for resolution checking
        trade.condition_id = signal.market.condition_id
        
        if config.VERBOSE_LOGGING:
            print(f"📋 Token ID stored for redemption: {trade.token_id[:16]}...")
        
        # ─────────────────────────────────────────────────────────────────────
        # PRE-EXECUTION PRICE DRIFT CHECK
        # ─────────────────────────────────────────────────────────────────────
        # Re-fetch current prices just before order placement to catch any
        # significant market movement since the signal was detected.
        # This prevents buying at much higher prices than the signal indicated.
        current_prices = self.polymarket.get_best_prices(signal.market, polymarket_side)
        if current_prices and not current_prices.get("is_fallback", True):
            current_ask = current_prices.get("ask", 0)
            signal_price = signal.market_odds
            
            # Check if price has drifted up significantly
            price_drift = current_ask - signal_price
            max_drift = getattr(config, 'MAX_PRICE_DRIFT', 0.03)  # Default 3 cents
            
            if price_drift > max_drift:
                print(f"⚠️ PRICE DRIFT TOO HIGH - Order rejected")
                print(f"   Signal price: {signal_price:.4f}")
                print(f"   Current ask:  {current_ask:.4f}")
                print(f"   Drift: {price_drift:.4f} (max allowed: {max_drift:.4f})")
                print(f"   Market moved against us - edge is no longer valid")
                return False
            elif price_drift > 0.01 and config.VERBOSE_LOGGING:
                # Log warning for smaller drift
                print(f"📊 Price drift since signal: {signal_price:.4f} → {current_ask:.4f} ({price_drift*100:.1f}¢)")
        
        # Place the order
        result = self.polymarket.place_order(
            market=signal.market,
            side=polymarket_side,
            amount_usd=trade.bet_size,
            max_slippage_percent=2.0  # 2% max slippage
        )
        
        if result is None:
            print("❌ Order placement returned None")
            return False
        
        # Check if order was accepted
        if not result.get("success", False):
            error = result.get("error", "Unknown error")
            print(f"❌ Order rejected: {error}")
            return False
        
        order_id = result.get("order_id")
        trade.order_id = order_id
        
        # IMPORTANT: Update bet_size if it was adjusted to meet minimum share requirements
        # Polymarket requires minimum 5 shares, so the actual amount may be higher
        actual_amount = result.get("amount_usd")
        if actual_amount and actual_amount != trade.bet_size:
            old_bet_size = trade.bet_size
            trade.bet_size = actual_amount
            print(f"📈 Bet size adjusted for minimum shares: ${old_bet_size:.2f} → ${actual_amount:.2f}")
        
        if config.VERBOSE_LOGGING:
            print(f"📋 Order placed: {order_id}")
            print(f"   Waiting for fill confirmation...")
        
        # Wait for order to be filled
        # Pass token_id for fallback position checking if order status returns 404
        fill_result = self.polymarket.wait_for_order_fill(
            order_id=order_id,
            max_wait_seconds=config.ORDER_FILL_TIMEOUT if hasattr(config, 'ORDER_FILL_TIMEOUT') else 60,
            poll_interval=2.0,
            token_id=trade.token_id
        )
        
        if not fill_result["success"]:
            # Order was not filled - handle failure
            error_msg = fill_result.get("error", "Unknown")
            trade.order_status = fill_result["status"]
            
            if fill_result["status"] == "NOT_FOUND":
                # Order status endpoint returned 404 and no position found
                # This usually means the limit order wasn't matched (illiquid market)
                print(f"⚠️ Order not matched - market may be illiquid at quoted price")
                print(f"   The order was placed but there were no matching counterparties")
                # Try to cancel the order just in case it's still open
                self.polymarket.cancel_order(order_id)
                return False
            
            if fill_result["status"] == "TIMEOUT":
                # Try to cancel the unfilled order
                print(f"⚠️ Order fill timeout, attempting to cancel...")
                cancelled = self.polymarket.cancel_order(order_id)
                if cancelled:
                    print("✅ Unfilled order cancelled")
                else:
                    print("⚠️ Could not cancel order - may have filled")
                    # Re-check status
                    final_check = self.polymarket.get_order_status(order_id)
                    if final_check and not final_check.get("_error"):
                        status = self.polymarket._parse_order_status(final_check)
                        if status in ["FILLED", "MATCHED"]:
                            # Actually it filled!
                            fill_info = self.polymarket._extract_fill_info(final_check)
                            trade.order_status = status
                            trade.filled_price = fill_info["filled_price"]
                            trade.filled_shares = fill_info["filled_shares"]
                            trade.entry_odds = trade.filled_price or trade.entry_odds
                            print(f"✅ Order actually filled: {trade.filled_shares:.2f} shares @ ${trade.filled_price:.4f}")
                            # Sync balance after successful trade
                            self._sync_balance_after_trade()
                            return True
            
            print(f"❌ Order not filled: {error_msg}")
            return False
        
        # Order was filled successfully
        trade.order_status = fill_result["status"]
        trade.filled_price = fill_result["filled_price"]
        trade.filled_shares = fill_result["filled_shares"]
        
        # Update entry odds with actual fill price
        if trade.filled_price and trade.filled_price > 0:
            old_odds = trade.entry_odds
            trade.entry_odds = trade.filled_price
            if config.VERBOSE_LOGGING and old_odds != trade.filled_price:
                print(f"   Fill price adjusted: {old_odds:.4f} → {trade.filled_price:.4f}")
        
        if config.VERBOSE_LOGGING:
            print(f"✅ Order filled successfully:")
            print(f"   Order ID: {trade.order_id}")
            print(f"   Status: {trade.order_status}")
            print(f"   Shares: {trade.filled_shares:.4f}")
            print(f"   Price: ${trade.filled_price:.4f}")
            print(f"   Token: {trade.token_id[:16]}... (stored for redemption)")
        
        # Sync balance after successful trade
        self._sync_balance_after_trade()
        
        return True
    
    def _sync_balance_after_trade(self):
        """
        Sync balance from Polymarket after a live trade.
        
        This ensures our internal balance tracking stays accurate
        with the actual USDC balance on Polymarket.
        """
        if config.TEST_MODE:
            return
        
        # Wait a moment for the trade to settle on Polymarket
        time.sleep(2)
        
        # Refresh balance from API
        success = self.refresh_balance()
        if success:
            if config.VERBOSE_LOGGING:
                print(f"💰 Balance synced: ${self.state.balance:.2f}")
        else:
            print("⚠️ Could not sync balance - using internal tracking")
    
    def check_and_resolve_trades(self) -> List[Trade]:
        """
        Check active trades and resolve any that have completed.
        
        In TEST_MODE: Simulates resolution based on the market's end time
        In LIVE mode: Queries Polymarket for actual resolution
        
        Returns:
            List of resolved Trade objects (for logging)
        """
        now = datetime.now(timezone.utc)
        resolved_trades = []
        pending_trades = []

        for trade_id, trade in list(self.state.active_trades.items()):
            time_since_entry = (now - trade.entry_time).total_seconds()

            # Only check resolution after market should have ended
            # 15 min = 900 seconds + 60 seconds buffer for resolution propagation
            if time_since_entry >= 960:  # 16 minutes
                if config.TEST_MODE:
                    # In test mode, resolve immediately
                    self._resolve_trade(trade)
                    resolved_trades.append(trade)
                else:
                    # In LIVE mode, try to get actual resolution
                    outcome = self._get_live_resolution(trade)
                    
                    if outcome == "PENDING":
                        # Still pending - track for retry
                        pending_trades.append(trade)
                        
                        # If it's been way too long (>30 min), force resolution
                        if time_since_entry > 1800:  # 30 minutes
                            print(f"⚠️ Trade {trade.trade_id} pending too long, forcing resolution check...")
                            # Try one more aggressive check
                            outcome = self._force_resolution_check(trade)
                            if outcome != "PENDING":
                                self._resolve_trade_with_outcome(trade, outcome)
                                resolved_trades.append(trade)
                            else:
                                # Really can't determine - mark as unknown loss
                                print(f"❌ Could not determine resolution for {trade.trade_id} after 30min")
                                self._resolve_trade_with_outcome(trade, "UNKNOWN")
                                resolved_trades.append(trade)
                    else:
                        # Got a definitive resolution
                        self._resolve_trade_with_outcome(trade, outcome)
                        resolved_trades.append(trade)
        
        # Log pending trades count
        if pending_trades and config.VERBOSE_LOGGING:
            print(f"⏳ {len(pending_trades)} trades still pending resolution...")
        
        # Remove resolved trades from active
        for trade in resolved_trades:
            if trade.trade_id in self.state.active_trades:
                del self.state.active_trades[trade.trade_id]
        
        return resolved_trades
    
    def _resolve_trade(self, trade: Trade):
        """
        Resolve a trade and update balance.
        
        In TEST_MODE: Simulates win/loss probabilistically
        In LIVE mode: Gets actual resolution from Polymarket and redeems winning shares
        
        Also updates:
        - Daily PnL tracking
        - Win/loss streaks
        - Daily trade counters
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
            
            # ════════════════════════════════════════════════════════════════
            # CRITICAL: Redeem winning shares in LIVE mode
            # ════════════════════════════════════════════════════════════════
            if not config.TEST_MODE and trade.token_id:
                print(f"💰 Redeeming winning shares for trade {trade.trade_id}...")
                redemption_result = self._redeem_winning_shares(trade)
                
                if redemption_result:
                    trade.redemption_status = "REDEEMED"
                    trade.redemption_amount = redemption_result.get("amount_usdc", payout)
                    print(f"✅ Shares redeemed: ${trade.redemption_amount:.2f} USDC")
                else:
                    trade.redemption_status = "FAILED"
                    print(f"⚠️ Redemption may have failed - check Polymarket manually")
                    print(f"   Token ID: {trade.token_id}")
                    print(f"   Shares: {trade.filled_shares}")
            
            # Update actual balance (for bot's internal tracking)
            self.state.balance += payout
            
            # ════════════════════════════════════════════════════════════════
            # CSV Balance Tracking (sequential chain based on resolution order)
            # ════════════════════════════════════════════════════════════════
            # Set balance_before to the resolved_balance BEFORE this trade resolves
            trade.balance_before = self.state.resolved_balance
            
            # Calculate profit and update resolved_balance
            profit = payout - trade.bet_size
            self.state.resolved_balance += profit
            
            # Set balance_after to the new resolved_balance
            trade.balance_after = self.state.resolved_balance
            
            self.state.wins += 1
            
            # Update daily stats
            self.state.daily_wins += 1
            self.state.daily_pnl += profit
            
            # Update streaks
            self.state.consecutive_wins += 1
            self.state.consecutive_losses = 0
            
            print(f"🎉 WIN: {trade.side} | Profit: ${profit:.2f} | Balance: ${self.state.resolved_balance:.2f}")
            
            # Sync balance from Polymarket after redemption
            if not config.TEST_MODE:
                self._sync_balance_after_resolution()
            
        else:
            trade.outcome = "LOSS"
            trade.status = TradeStatus.RESOLVED_LOSS
            trade.payout = 0.0
            trade.redemption_status = "N/A"  # No redemption needed for losses
            
            # ════════════════════════════════════════════════════════════════
            # CSV Balance Tracking (sequential chain based on resolution order)
            # ════════════════════════════════════════════════════════════════
            # Set balance_before to the resolved_balance BEFORE this trade resolves
            trade.balance_before = self.state.resolved_balance
            
            # Update resolved_balance (deduct bet, no payout)
            self.state.resolved_balance -= trade.bet_size
            
            # Set balance_after to the new resolved_balance
            trade.balance_after = self.state.resolved_balance
            
            self.state.losses += 1
            
            # Update daily stats
            self.state.daily_losses += 1
            self.state.daily_pnl -= trade.bet_size
            
            # Update streaks
            self.state.consecutive_losses += 1
            self.state.consecutive_wins = 0
            
            print(f"😞 LOSS: {trade.side} | Lost: ${trade.bet_size:.2f} | Balance: ${self.state.resolved_balance:.2f}")
            
            # Check if we should pause (will be evaluated on next can_trade call)
            if config.MAX_CONSECUTIVE_LOSSES > 0:
                if self.state.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
                    print(f"⚠️ {self.state.consecutive_losses} consecutive losses - trading will pause")
        
        # Update daily trade counter
        self.state.daily_trades += 1
    
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
        Get actual resolution from Polymarket in LIVE mode (NON-BLOCKING).
        
        This queries the Polymarket API to determine if the market
        has resolved and whether our position won or lost.
        
        Args:
            trade: The trade to check resolution for
            
        Returns:
            "WIN", "LOSS", or "PENDING"
        """
        if config.VERBOSE_LOGGING:
            print(f"🔍 Checking resolution for trade {trade.trade_id}...")
        
        # Use the market client to check resolution
        # Use short timeout - we don't want to block the main loop
        outcome = self.polymarket.check_trade_resolution(
            market_id=trade.market_id,
            traded_side=trade.side,
            max_wait_seconds=10  # Short non-blocking check
        )
        
        if outcome == "PENDING":
            # Resolution not available yet - don't default to loss!
            # The calling code will handle pending trades
            if config.VERBOSE_LOGGING:
                print(f"⏳ Resolution pending for {trade.trade_id}")
            return "PENDING"
        
        return outcome
    
    def _force_resolution_check(self, trade: Trade) -> str:
        """
        Force a more aggressive resolution check for stuck trades.
        
        Tries multiple methods to determine the outcome.
        
        Args:
            trade: The trade to check
            
        Returns:
            "WIN", "LOSS", or "PENDING"
        """
        print(f"🔄 Force checking resolution for {trade.trade_id}...")
        
        # Try with longer timeout
        outcome = self.polymarket.check_trade_resolution(
            market_id=trade.market_id,
            traded_side=trade.side,
            max_wait_seconds=30  # Longer wait for forced check
        )
        
        if outcome != "PENDING":
            return outcome
        
        # Try checking via different API endpoint (if available)
        # This is a fallback for when the main resolution API is slow
        try:
            market_info = self.polymarket.get_market_by_id(trade.market_id)
            if market_info:
                resolved = market_info.get("resolved", False)
                if resolved:
                    resolution_source = market_info.get("resolution_source", "")
                    outcome_value = market_info.get("outcome", "")
                    
                    # Determine if our side won
                    our_side = trade.side.upper()
                    winning_side = outcome_value.upper() if outcome_value else ""
                    
                    if winning_side and our_side == winning_side:
                        return "WIN"
                    elif winning_side:
                        return "LOSS"
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Fallback resolution check failed: {e}")
        
        return "PENDING"
    
    def _resolve_trade_with_outcome(self, trade: Trade, outcome: str):
        """
        Resolve a trade with a known outcome.
        
        Similar to _resolve_trade but uses a provided outcome instead
        of determining it.
        
        For LIVE mode winning trades, this also triggers redemption
        of the winning shares to convert them back to USDC.
        
        Args:
            trade: The trade to resolve
            outcome: "WIN", "LOSS", or "UNKNOWN"
        """
        trade.resolution_time = datetime.now(timezone.utc)
        
        if outcome == "WIN":
            trade.outcome = "WIN"
            trade.status = TradeStatus.RESOLVED_WIN
            
            # Calculate payout
            payout = trade.bet_size / trade.entry_odds
            payout *= (1 - config.ESTIMATED_FEE_PERCENT)
            trade.payout = payout
            
            # ════════════════════════════════════════════════════════════════
            # CRITICAL: Redeem winning shares in LIVE mode
            # ════════════════════════════════════════════════════════════════
            if not config.TEST_MODE and trade.token_id:
                print(f"💰 Redeeming winning shares for trade {trade.trade_id}...")
                redemption_result = self._redeem_winning_shares(trade)
                
                if redemption_result:
                    trade.redemption_status = "REDEEMED"
                    trade.redemption_amount = redemption_result.get("amount_usdc", payout)
                    print(f"✅ Shares redeemed: ${trade.redemption_amount:.2f} USDC")
                else:
                    trade.redemption_status = "FAILED"
                    print(f"⚠️ Redemption may have failed - check Polymarket manually")
                    print(f"   Token ID: {trade.token_id}")
                    print(f"   Shares: {trade.filled_shares}")
            
            # Update actual balance
            self.state.balance += payout
            
            # CSV Balance Tracking (sequential chain based on resolution order)
            trade.balance_before = self.state.resolved_balance
            profit = payout - trade.bet_size
            self.state.resolved_balance += profit
            trade.balance_after = self.state.resolved_balance
            
            self.state.wins += 1
            self.state.daily_wins += 1
            self.state.daily_pnl += profit
            self.state.consecutive_wins += 1
            self.state.consecutive_losses = 0
            
            print(f"🎉 WIN: {trade.side} | Profit: ${profit:.2f} | Balance: ${self.state.resolved_balance:.2f}")
            
            # Sync balance from Polymarket after redemption
            if not config.TEST_MODE:
                self._sync_balance_after_resolution()
            
        elif outcome == "LOSS":
            trade.outcome = "LOSS"
            trade.status = TradeStatus.RESOLVED_LOSS
            trade.payout = 0.0
            trade.redemption_status = "N/A"  # No redemption needed for losses
            
            # CSV Balance Tracking (sequential chain based on resolution order)
            trade.balance_before = self.state.resolved_balance
            self.state.resolved_balance -= trade.bet_size
            trade.balance_after = self.state.resolved_balance
            
            self.state.losses += 1
            self.state.daily_losses += 1
            self.state.daily_pnl -= trade.bet_size
            self.state.consecutive_losses += 1
            self.state.consecutive_wins = 0
            
            print(f"😞 LOSS: {trade.side} | Lost: ${trade.bet_size:.2f} | Balance: ${self.state.resolved_balance:.2f}")
            
            if config.MAX_CONSECUTIVE_LOSSES > 0:
                if self.state.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
                    print(f"⚠️ {self.state.consecutive_losses} consecutive losses - trading will pause")
                    
        else:  # UNKNOWN
            # Treat unknown as loss for accounting safety
            trade.outcome = "UNKNOWN"
            trade.status = TradeStatus.RESOLVED_LOSS
            trade.payout = 0.0
            trade.redemption_status = "UNKNOWN"
            
            # CSV Balance Tracking (sequential chain based on resolution order)
            trade.balance_before = self.state.resolved_balance
            self.state.resolved_balance -= trade.bet_size
            trade.balance_after = self.state.resolved_balance
            
            self.state.losses += 1
            self.state.daily_losses += 1
            self.state.daily_pnl -= trade.bet_size
            
            print(f"❓ UNKNOWN: {trade.side} | Assuming loss: ${trade.bet_size:.2f} | Balance: ${self.state.resolved_balance:.2f}")
        
        # Update daily trade counter
        self.state.daily_trades += 1
    
    def _redeem_winning_shares(self, trade: Trade) -> Optional[Dict]:
        """
        Check winning shares redemption status for a resolved trade.
        
        IMPORTANT: Polymarket redemption happens ON-CHAIN via smart contracts,
        NOT via REST API. This method checks the status and notifies the user
        if manual redemption is needed.
        
        Args:
            trade: The winning trade with token_id and filled_shares
            
        Returns:
            Dict with redemption info if successful, None otherwise
        """
        if config.TEST_MODE:
            return {"success": True, "amount_usdc": trade.payout, "simulated": True}
        
        if not trade.token_id:
            print(f"❌ Cannot check redemption: No token ID stored for trade {trade.trade_id}")
            return None
        
        # Use the Polymarket client to check redemption status
        result = self.polymarket.redeem_winning_shares(
            token_id=trade.token_id,
            shares=trade.filled_shares
        )
        
        # Handle the new response format
        if result and result.get("needs_manual_redemption"):
            trade.redemption_status = "PENDING_MANUAL"
            trade.redemption_amount = result.get("amount_usdc", 0)
            # Don't log error - manual redemption is expected
        
        return result
    
    def _sync_balance_after_resolution(self):
        """
        Sync balance from Polymarket after trade resolution.
        
        This is especially important after winning trades where
        redemption should have credited USDC to our account.
        """
        if config.TEST_MODE:
            return
        
        # Wait for redemption to process
        time.sleep(3)
        
        # Refresh balance from API
        new_balance = self.polymarket.get_usdc_balance()
        
        if new_balance is not None:
            old_balance = self.state.balance
            
            # If API balance is higher than our tracking, use API balance
            # (This catches any redemption amounts we might have missed)
            if new_balance > self.state.balance:
                self.state.balance = new_balance
                diff = new_balance - old_balance
                print(f"💰 Balance synced from API: ${old_balance:.2f} → ${new_balance:.2f} (+${diff:.2f})")
            elif config.VERBOSE_LOGGING:
                print(f"💰 Balance verified: ${new_balance:.2f}")
        else:
            print("⚠️ Could not sync balance from API")
    
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
        
        starting = self.state.session_starting_balance
        pnl_percent = ((self.state.balance / starting) - 1) * 100 if starting > 0 else 0
        
        return {
            "balance": self.state.balance,
            "starting_balance": starting,
            "total_trades": self.state.total_trades,
            "wins": self.state.wins,
            "losses": self.state.losses,
            "win_rate": win_rate,
            "active_trades": len(self.state.active_trades),
            "pnl": self.state.balance - starting,
            "pnl_percent": pnl_percent
        }
    
    def check_and_redeem_positions(self) -> Dict:
        """
        Check for and redeem any unredeemed winning positions.
        
        This is a safety net that runs periodically to ensure
        no winning positions are left unredeemed.
        
        Returns:
            Dict with redemption summary
        """
        if config.TEST_MODE:
            return {"simulated": True, "total_redeemed": 0}
        
        print("\n🔍 Running periodic redemption check...")
        result = self.polymarket.redeem_all_winning_positions()
        
        # If we redeemed anything, sync balance
        if result.get("total_redeemed", 0) > 0:
            self.refresh_balance()
        
        return result
    
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
