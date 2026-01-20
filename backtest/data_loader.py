"""
Data loader module for backtesting.

This module handles:
- Loading historical BTC candle data from Binance CSV
- Loading historical Polymarket 15-minute market data
- Merging data sources into unified intervals
- Handling missing data and edge cases

Data Sources:
- Binance: 1-minute BTCUSDT candles (data/binance_1m.csv)
- Polymarket: 15-minute market snapshots (data/polymarket_15m.csv)

Expected CSV Formats:

binance_1m.csv:
    timestamp,open,high,low,close,volume
    1705315800000,42000.50,42100.00,41950.00,42050.25,150.5
    ...

polymarket_15m.csv:
    interval_start,market_id,outcome_yes_price,outcome_no_price,resolved_outcome,volume
    2024-01-15T10:00:00Z,BTC-15M-001,0.52,0.48,UP,5000.00
    ...
"""

import csv
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple, Generator
from dataclasses import dataclass, field
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.utils import (
    align_timestamp_to_interval,
    parse_timestamp,
    ms_to_timestamp,
    timestamp_to_ms
)


@dataclass
class BTCCandle:
    """Represents a single BTC price candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class PolymarketSnapshot:
    """Represents a Polymarket 15-minute market snapshot."""
    interval_start: datetime
    market_id: str
    yes_price: float  # Price of "Up" outcome
    no_price: float   # Price of "Down" outcome
    resolved_outcome: str  # "UP", "DOWN", or "UNKNOWN"
    volume: float
    liquidity: float = 1000.0  # Default if not available


@dataclass
class HistoricalInterval:
    """
    Represents a complete 15-minute interval with all data needed for backtesting.
    
    This merges BTC candle data with Polymarket market data.
    """
    interval_start: datetime
    interval_end: datetime
    
    # BTC data (aggregated from 1-min candles)
    btc_open: float
    btc_high: float
    btc_low: float
    btc_close: float
    btc_volume: float
    
    # BTC price at ~3 minutes into interval (for signal generation)
    btc_price_at_signal: float
    btc_change_percent: float  # Change from open to signal time
    
    # Polymarket data
    market_id: str
    yes_price: float
    no_price: float
    resolved_outcome: str  # Actual outcome for validation
    market_volume: float
    market_liquidity: float
    
    # Calculated fields
    has_valid_data: bool = True
    skip_reason: Optional[str] = None


class DataLoader:
    """
    Loads and merges historical data for backtesting.
    
    Combines Binance 1-minute candles with Polymarket 15-minute market data.
    """
    
    def __init__(
        self,
        data_folder: str = "data",
        binance_file: str = "binance_1m.csv",
        polymarket_file: str = "polymarket_15m.csv"
    ):
        self.data_folder = data_folder
        self.binance_path = os.path.join(data_folder, binance_file)
        self.polymarket_path = os.path.join(data_folder, polymarket_file)
        
        # Cached data
        self._btc_candles: Dict[int, BTCCandle] = {}  # key = timestamp_ms
        self._polymarket_snapshots: Dict[str, PolymarketSnapshot] = {}  # key = interval_start ISO
        
        # Data stats
        self.btc_candle_count = 0
        self.polymarket_market_count = 0
        self.date_range: Optional[Tuple[datetime, datetime]] = None
    
    def load_binance_candles(self) -> int:
        """
        Load BTC 1-minute candles from CSV.
        
        Returns:
            Number of candles loaded
        """
        if not os.path.exists(self.binance_path):
            print(f"❌ Binance data file not found: {self.binance_path}")
            return 0
        
        count = 0
        
        try:
            with open(self.binance_path, 'r') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    try:
                        # Parse timestamp (could be ms or ISO format)
                        ts_str = row.get('timestamp', row.get('open_time', ''))
                        ts = parse_timestamp(str(ts_str))
                        
                        if ts is None:
                            continue
                        
                        candle = BTCCandle(
                            timestamp=ts,
                            open=float(row.get('open', 0)),
                            high=float(row.get('high', 0)),
                            low=float(row.get('low', 0)),
                            close=float(row.get('close', 0)),
                            volume=float(row.get('volume', 0))
                        )
                        
                        # Store by millisecond timestamp for fast lookup
                        self._btc_candles[timestamp_to_ms(ts)] = candle
                        count += 1
                        
                    except (ValueError, TypeError) as e:
                        continue
            
            self.btc_candle_count = count
            print(f"✅ Loaded {count} BTC candles from {self.binance_path}")
            
            # Update date range
            if self._btc_candles:
                timestamps = list(self._btc_candles.keys())
                self.date_range = (
                    ms_to_timestamp(min(timestamps)),
                    ms_to_timestamp(max(timestamps))
                )
                print(f"   Date range: {self.date_range[0].strftime('%Y-%m-%d')} to {self.date_range[1].strftime('%Y-%m-%d')}")
            
        except Exception as e:
            print(f"❌ Error loading Binance data: {e}")
        
        return count
    
    def load_polymarket_snapshots(self) -> int:
        """
        Load Polymarket 15-minute market snapshots from CSV.
        
        Returns:
            Number of snapshots loaded
        """
        if not os.path.exists(self.polymarket_path):
            print(f"❌ Polymarket data file not found: {self.polymarket_path}")
            return 0
        
        count = 0
        
        try:
            with open(self.polymarket_path, 'r') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    try:
                        # Parse interval start
                        ts_str = row.get('interval_start', '')
                        ts = parse_timestamp(ts_str)
                        
                        if ts is None:
                            continue
                        
                        snapshot = PolymarketSnapshot(
                            interval_start=ts,
                            market_id=row.get('market_id', f'PM-{count}'),
                            yes_price=float(row.get('outcome_yes_price', row.get('yes_price', 0.5))),
                            no_price=float(row.get('outcome_no_price', row.get('no_price', 0.5))),
                            resolved_outcome=row.get('resolved_outcome', 'UNKNOWN').upper(),
                            volume=float(row.get('volume', 0)),
                            liquidity=float(row.get('liquidity', 1000))
                        )
                        
                        # Store by ISO timestamp
                        key = ts.isoformat()
                        self._polymarket_snapshots[key] = snapshot
                        count += 1
                        
                    except (ValueError, TypeError) as e:
                        continue
            
            self.polymarket_market_count = count
            print(f"✅ Loaded {count} Polymarket snapshots from {self.polymarket_path}")
            
        except Exception as e:
            print(f"❌ Error loading Polymarket data: {e}")
        
        return count
    
    def load_all(self, require_real_polymarket: bool = True) -> bool:
        """
        Load all data sources.
        
        Args:
            require_real_polymarket: If True, fail if no real Polymarket data
        
        Returns:
            True if sufficient data was loaded
        """
        btc_count = self.load_binance_candles()
        pm_count = self.load_polymarket_snapshots()
        
        if btc_count == 0:
            print("❌ No BTC candle data loaded. Cannot proceed.")
            return False
        
        if pm_count == 0:
            if require_real_polymarket:
                print("❌ No Polymarket data loaded!")
                print("   To get REAL Polymarket data, run:")
                print("   python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv")
                print("")
                print("   If you want to use synthetic data (NOT recommended), run:")
                print("   python -m backtest.backtest --allow-synthetic")
                return False
            else:
                print("⚠️ WARNING: No Polymarket data loaded. Using SYNTHETIC market data.")
                print("   This means backtest results are SIMULATED, not based on real Polymarket odds!")
        else:
            # Validate that data is real (not synthetic)
            self._validate_polymarket_data()
        
        return True
    
    def _validate_polymarket_data(self) -> None:
        """Check if Polymarket data looks like real API data vs synthetic."""
        if not self._polymarket_snapshots:
            return
        
        synthetic_count = 0
        real_count = 0
        
        for key, snapshot in self._polymarket_snapshots.items():
            # Synthetic IDs typically start with SYN- or BTC-15M-
            if snapshot.market_id.startswith("SYN-") or snapshot.market_id.startswith("BTC-15M-"):
                synthetic_count += 1
            else:
                real_count += 1
        
        if synthetic_count > 0 and real_count == 0:
            print("⚠️ WARNING: Polymarket data appears to be SYNTHETIC (generated from BTC candles)")
            print("   For real backtesting, fetch actual Polymarket data:")
            print("   python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv")
        elif real_count > 0:
            print(f"✅ Polymarket data appears to be REAL API data ({real_count} intervals)")
    
    def get_btc_candles_for_interval(
        self, 
        interval_start: datetime,
        interval_minutes: int = 15
    ) -> List[BTCCandle]:
        """
        Get all 1-minute candles within a 15-minute interval.
        
        Args:
            interval_start: Start of the 15-minute interval
            interval_minutes: Duration of interval
        
        Returns:
            List of BTCCandle objects within the interval
        """
        candles = []
        
        start_ms = timestamp_to_ms(interval_start)
        end_ms = start_ms + (interval_minutes * 60 * 1000)
        
        for ms, candle in self._btc_candles.items():
            if start_ms <= ms < end_ms:
                candles.append(candle)
        
        # Sort by timestamp
        candles.sort(key=lambda c: c.timestamp)
        
        return candles
    
    def aggregate_candles_to_interval(
        self, 
        candles: List[BTCCandle]
    ) -> Optional[Dict[str, float]]:
        """
        Aggregate 1-minute candles into a single interval OHLCV.
        
        Args:
            candles: List of 1-minute candles
        
        Returns:
            Dictionary with open, high, low, close, volume or None if no data
        """
        if not candles:
            return None
        
        return {
            'open': candles[0].open,
            'high': max(c.high for c in candles),
            'low': min(c.low for c in candles),
            'close': candles[-1].close,
            'volume': sum(c.volume for c in candles)
        }
    
    def get_polymarket_snapshot(
        self, 
        interval_start: datetime
    ) -> Optional[PolymarketSnapshot]:
        """
        Get Polymarket market snapshot for an interval.
        
        Args:
            interval_start: Start of the 15-minute interval
        
        Returns:
            PolymarketSnapshot or None if not found
        """
        key = interval_start.isoformat()
        return self._polymarket_snapshots.get(key)
    
    def generate_synthetic_market(
        self,
        interval_start: datetime,
        btc_ohlcv: Dict[str, float]
    ) -> PolymarketSnapshot:
        """
        Generate synthetic Polymarket data when real data is unavailable.
        
        This simulates what market odds might have been based on BTC movement.
        
        Args:
            interval_start: Start of the interval
            btc_ohlcv: Aggregated BTC OHLCV data
        
        Returns:
            Synthetic PolymarketSnapshot
        """
        import random
        
        # Determine outcome based on actual BTC movement
        price_went_up = btc_ohlcv['close'] > btc_ohlcv['open']
        resolved_outcome = "UP" if price_went_up else "DOWN"
        
        # Simulate market odds (slight random bias)
        # In efficient markets, odds would be close to 50/50 at interval start
        base_yes = 0.50 + random.uniform(-0.03, 0.03)
        
        # Add some market noise but keep spreads reasonable
        yes_price = max(0.45, min(0.55, base_yes))
        no_price = 1.0 - yes_price - random.uniform(0.01, 0.03)  # Small vig
        
        return PolymarketSnapshot(
            interval_start=interval_start,
            market_id=f"SYN-{interval_start.strftime('%Y%m%d%H%M')}",
            yes_price=yes_price,
            no_price=no_price,
            resolved_outcome=resolved_outcome,
            volume=random.uniform(1000, 10000),
            liquidity=random.uniform(500, 2000)
        )
    
    def get_historical_interval(
        self, 
        interval_start: datetime,
        signal_offset_minutes: int = 3
    ) -> HistoricalInterval:
        """
        Get complete data for a single 15-minute interval.
        
        Args:
            interval_start: Start of the interval
            signal_offset_minutes: Minutes into interval to sample price for signal
        
        Returns:
            HistoricalInterval with all data
        """
        # Ensure aligned
        interval_start = align_timestamp_to_interval(interval_start)
        interval_end = interval_start + timedelta(minutes=15)
        
        # Get BTC candles
        candles = self.get_btc_candles_for_interval(interval_start)
        
        if not candles:
            return HistoricalInterval(
                interval_start=interval_start,
                interval_end=interval_end,
                btc_open=0,
                btc_high=0,
                btc_low=0,
                btc_close=0,
                btc_volume=0,
                btc_price_at_signal=0,
                btc_change_percent=0,
                market_id="",
                yes_price=0,
                no_price=0,
                resolved_outcome="UNKNOWN",
                market_volume=0,
                market_liquidity=0,
                has_valid_data=False,
                skip_reason="No BTC candle data for interval"
            )
        
        # Aggregate candles
        ohlcv = self.aggregate_candles_to_interval(candles)
        
        # Get price at signal time (e.g., 3 minutes into interval)
        signal_candle_idx = min(signal_offset_minutes, len(candles) - 1)
        btc_price_at_signal = candles[signal_candle_idx].close if candles else ohlcv['open']
        
        # Calculate change percent at signal time
        btc_change_percent = 0.0
        if ohlcv['open'] > 0:
            btc_change_percent = ((btc_price_at_signal - ohlcv['open']) / ohlcv['open']) * 100
        
        # Get Polymarket data (or generate synthetic)
        pm_snapshot = self.get_polymarket_snapshot(interval_start)
        
        if pm_snapshot is None:
            # Generate synthetic market data
            pm_snapshot = self.generate_synthetic_market(interval_start, ohlcv)
        
        return HistoricalInterval(
            interval_start=interval_start,
            interval_end=interval_end,
            btc_open=ohlcv['open'],
            btc_high=ohlcv['high'],
            btc_low=ohlcv['low'],
            btc_close=ohlcv['close'],
            btc_volume=ohlcv['volume'],
            btc_price_at_signal=btc_price_at_signal,
            btc_change_percent=btc_change_percent,
            market_id=pm_snapshot.market_id,
            yes_price=pm_snapshot.yes_price,
            no_price=pm_snapshot.no_price,
            resolved_outcome=pm_snapshot.resolved_outcome,
            market_volume=pm_snapshot.volume,
            market_liquidity=pm_snapshot.liquidity,
            has_valid_data=True
        )
    
    def iterate_intervals(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Generator[HistoricalInterval, None, None]:
        """
        Iterate over all 15-minute intervals in the data.
        
        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
        
        Yields:
            HistoricalInterval for each interval
        """
        if not self._btc_candles:
            print("❌ No data loaded. Call load_all() first.")
            return
        
        # Determine date range
        timestamps = list(self._btc_candles.keys())
        data_start = ms_to_timestamp(min(timestamps))
        data_end = ms_to_timestamp(max(timestamps))
        
        # Apply filters
        if start_date:
            data_start = max(data_start, start_date)
        if end_date:
            data_end = min(data_end, end_date)
        
        # Align to 15-minute intervals
        current = align_timestamp_to_interval(data_start)
        
        while current <= data_end:
            interval = self.get_historical_interval(current)
            yield interval
            current += timedelta(minutes=15)
    
    def get_interval_count(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """Get the total number of intervals available."""
        if not self._btc_candles:
            return 0
        
        timestamps = list(self._btc_candles.keys())
        data_start = ms_to_timestamp(min(timestamps))
        data_end = ms_to_timestamp(max(timestamps))
        
        if start_date:
            data_start = max(data_start, start_date)
        if end_date:
            data_end = min(data_end, end_date)
        
        total_minutes = (data_end - data_start).total_seconds() / 60
        return int(total_minutes // 15)


def create_sample_binance_csv(output_path: str, days: int = 7):
    """
    Create a sample Binance CSV file with random data for testing.
    
    Args:
        output_path: Path to write the CSV
        days: Number of days of data to generate
    """
    import random
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Start from 7 days ago
        start = datetime.now(timezone.utc) - timedelta(days=days)
        price = 95000.0  # Starting BTC price
        
        for i in range(days * 24 * 60):  # 1-minute intervals
            ts = start + timedelta(minutes=i)
            
            # Random walk with mean reversion
            change = random.gauss(0, 50)  # ~$50 std per minute
            price = max(90000, min(100000, price + change))
            
            open_price = price
            high_price = price + abs(random.gauss(0, 30))
            low_price = price - abs(random.gauss(0, 30))
            close_price = price + random.gauss(0, 20)
            volume = random.uniform(1, 100)
            
            writer.writerow([
                timestamp_to_ms(ts),
                f"{open_price:.2f}",
                f"{high_price:.2f}",
                f"{low_price:.2f}",
                f"{close_price:.2f}",
                f"{volume:.4f}"
            ])
            
            price = close_price
    
    print(f"✅ Created sample Binance CSV: {output_path}")


def create_sample_polymarket_csv(output_path: str, days: int = 7):
    """
    Create a sample Polymarket CSV file with random data for testing.
    
    Args:
        output_path: Path to write the CSV
        days: Number of days of data to generate
    """
    import random
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['interval_start', 'market_id', 'outcome_yes_price', 'outcome_no_price', 'resolved_outcome', 'volume', 'liquidity'])
        
        # Start from 7 days ago
        start = datetime.now(timezone.utc) - timedelta(days=days)
        start = align_timestamp_to_interval(start)
        
        for i in range(days * 24 * 4):  # 15-minute intervals
            ts = start + timedelta(minutes=i * 15)
            
            # Random market odds around 50/50
            yes_price = 0.50 + random.uniform(-0.05, 0.05)
            no_price = 1.0 - yes_price - random.uniform(0.01, 0.03)
            
            # Random outcome
            resolved = random.choice(["UP", "DOWN"])
            
            volume = random.uniform(1000, 10000)
            liquidity = random.uniform(500, 3000)
            
            writer.writerow([
                ts.isoformat(),
                f"BTC-15M-{i:05d}",
                f"{yes_price:.4f}",
                f"{no_price:.4f}",
                resolved,
                f"{volume:.2f}",
                f"{liquidity:.2f}"
            ])
    
    print(f"✅ Created sample Polymarket CSV: {output_path}")
