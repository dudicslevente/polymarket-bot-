"""
Price Feed module for Binance BTC data.

This module handles:
- Fetching current BTC spot price
- Fetching historical price data (1m, 3m, 5m lookback)
- Calculating price changes over time periods

Uses Binance public API (no authentication required for price data).
"""

import time
import requests
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone

import config


@dataclass
class PriceData:
    """Represents BTC price data at a point in time."""
    price: float
    timestamp: datetime
    volume: float = 0.0


@dataclass
class PriceChange:
    """Represents a price change over a time period."""
    start_price: float
    end_price: float
    change_absolute: float
    change_percent: float
    period_minutes: int


class BinanceClient:
    """
    Client for fetching BTC price data from Binance.
    
    Uses public endpoints - no API keys required.
    """
    
    def __init__(self):
        self.base_url = config.BINANCE_API_URL
        self._last_prices: List[PriceData] = []
        self._api_calls: List[float] = []
    
    def _rate_limit_check(self):
        """Ensure we don't exceed Binance rate limits."""
        now = time.time()
        # Remove timestamps older than 60 seconds
        self._api_calls = [t for t in self._api_calls if now - t < 60]
        
        # Binance allows 1200 requests per minute, we stay well below
        if len(self._api_calls) >= 60:
            sleep_time = 60 - (now - self._api_calls[0]) + 1
            # Cap maximum wait time to 10 seconds
            sleep_time = min(sleep_time, 10)
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        self._api_calls.append(time.time())
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None, retries: int = 2) -> Optional[Dict]:
        """
        Make a GET request to Binance API with error handling and retries.
        
        Returns None on error (never crashes).
        """
        last_error = None
        
        for attempt in range(retries + 1):
            self._rate_limit_check()
            
            url = f"{self.base_url}{endpoint}"
            
            try:
                # Reduced timeout from 10s to 5s
                response = requests.get(url, params=params, timeout=5)
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.Timeout:
                last_error = "timeout"
                if attempt < retries:
                    time.sleep(1)
                    continue
            except requests.exceptions.ConnectionError:
                last_error = "connection"
                if attempt < retries:
                    time.sleep(2)
                    continue
            except requests.exceptions.HTTPError as e:
                if config.VERBOSE_LOGGING:
                    print(f"⚠️ Binance HTTP error: {e}")
                return None
            except Exception as e:
                print(f"❌ Unexpected Binance API error: {e}")
                return None
        
        # All retries exhausted
        if last_error and config.VERBOSE_LOGGING:
            print(f"⚠️ Binance API failed ({last_error}): {endpoint}")
        return None
    
    def get_btc_price(self) -> Optional[float]:
        """
        Fetch the current BTC/USDT spot price.
        
        Returns the price as a float, or None on error.
        """
        data = self._make_request("/api/v3/ticker/price", {"symbol": "BTCUSDT"})
        
        if not data:
            return None
        
        try:
            price = float(data.get("price", 0))
            if price > 0:
                # Cache the price
                self._last_prices.append(PriceData(
                    price=price,
                    timestamp=datetime.now(timezone.utc)
                ))
                # Keep only last 10 minutes of prices
                self._cleanup_price_cache()
                return price
        except (ValueError, TypeError):
            pass
        
        return None
    
    def _cleanup_price_cache(self):
        """Remove prices older than 10 minutes from cache."""
        now = datetime.now(timezone.utc)
        self._last_prices = [
            p for p in self._last_prices
            if (now - p.timestamp).total_seconds() < 600
        ]
    
    def get_klines(
        self, 
        interval: str = "1m", 
        limit: int = 10
    ) -> Optional[List[Dict]]:
        """
        Fetch candlestick (kline) data for BTCUSDT.
        
        Args:
            interval: Candle interval (1m, 3m, 5m, etc.)
            limit: Number of candles to fetch
        
        Returns:
            List of candle data dicts, or None on error
        """
        params = {
            "symbol": "BTCUSDT",
            "interval": interval,
            "limit": limit
        }
        
        data = self._make_request("/api/v3/klines", params)
        
        if not data or not isinstance(data, list):
            return None
        
        klines = []
        for candle in data:
            try:
                klines.append({
                    "open_time": candle[0],
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                    "close_time": candle[6],
                })
            except (IndexError, ValueError, TypeError):
                continue
        
        return klines if klines else None
    
    def get_price_n_minutes_ago(self, minutes: int) -> Optional[float]:
        """
        Get the BTC price from N minutes ago.
        
        Uses kline data to find historical price.
        """
        # Fetch enough candles to cover the time period
        # Add a buffer for safety
        klines = self.get_klines(interval="1m", limit=minutes + 2)
        
        if not klines or len(klines) < minutes:
            return None
        
        try:
            # Index from the end: -1 is current, -N is N minutes ago
            # But klines are ordered oldest to newest
            # So index 0 is oldest
            target_index = max(0, len(klines) - minutes - 1)
            return klines[target_index]["close"]
        except (IndexError, KeyError):
            return None
    
    def calculate_price_change(self, minutes: int) -> Optional[PriceChange]:
        """
        Calculate BTC price change over the last N minutes.
        
        Args:
            minutes: Lookback period in minutes
        
        Returns:
            PriceChange object with absolute and percentage change,
            or None if data is unavailable.
        """
        current_price = self.get_btc_price()
        if current_price is None:
            return None
        
        past_price = self.get_price_n_minutes_ago(minutes)
        if past_price is None:
            return None
        
        if past_price == 0:
            return None
        
        change_absolute = current_price - past_price
        change_percent = (change_absolute / past_price) * 100
        
        return PriceChange(
            start_price=past_price,
            end_price=current_price,
            change_absolute=change_absolute,
            change_percent=change_percent,
            period_minutes=minutes
        )
    
    def get_btc_bias(self) -> Tuple[Optional[str], Optional[float], Optional[float]]:
        """
        Determine the current BTC directional bias based on recent price action.
        
        Returns:
            Tuple of (bias, change_percent, current_price):
            - bias: "UP", "DOWN", or None (flat/no signal)
            - change_percent: The percentage change that triggered the signal
            - current_price: Current BTC price
        
        Bias is determined by:
        - UP: BTC up >= +0.10% in last 3 minutes
        - DOWN: BTC down <= -0.10% in last 3 minutes
        - None: Price change within ±0.10% (flat market, no trade)
        """
        change = self.calculate_price_change(config.BTC_LOOKBACK_MINUTES)
        
        if change is None:
            if config.VERBOSE_LOGGING:
                print("⚠️ Could not calculate BTC price change")
            return None, None, None
        
        current_price = change.end_price
        change_percent = change.change_percent
        threshold = config.BTC_BIAS_THRESHOLD_PERCENT
        
        if config.VERBOSE_LOGGING:
            direction = "↑" if change_percent >= 0 else "↓"
            print(f"📈 BTC: ${current_price:,.2f} | {config.BTC_LOOKBACK_MINUTES}m change: {direction}{abs(change_percent):.3f}%")
        
        # Determine bias based on threshold
        if change_percent >= threshold:
            return "UP", change_percent, current_price
        elif change_percent <= -threshold:
            return "DOWN", change_percent, current_price
        else:
            # Flat market - no clear bias
            return None, change_percent, current_price
    
    def get_volatility_indicator(self) -> Optional[float]:
        """
        Calculate a simple volatility indicator using recent price range.
        
        Returns the average high-low range as a percentage of price.
        Higher values = more volatile market.
        
        This can be used to adjust position sizing or skip trades
        during unusually volatile or quiet periods.
        """
        klines = self.get_klines(interval="1m", limit=5)
        
        if not klines or len(klines) < 3:
            return None
        
        ranges = []
        for candle in klines:
            try:
                high = candle["high"]
                low = candle["low"]
                mid = (high + low) / 2
                if mid > 0:
                    range_pct = ((high - low) / mid) * 100
                    ranges.append(range_pct)
            except (KeyError, ZeroDivisionError):
                continue
        
        if not ranges:
            return None
        
        return sum(ranges) / len(ranges)


# Singleton client instance
_client: Optional[BinanceClient] = None


def get_client() -> BinanceClient:
    """Get or create the Binance client singleton."""
    global _client
    if _client is None:
        _client = BinanceClient()
    return _client


def get_btc_price() -> Optional[float]:
    """Convenience function to get current BTC price."""
    return get_client().get_btc_price()


def get_btc_bias() -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """Convenience function to get current BTC bias."""
    return get_client().get_btc_bias()
