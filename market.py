"""
Market module for Polymarket API interactions.

This module handles:
- Fetching active BTC 15-minute Up/Down markets
- Fetching current odds
- Placing trades (in live mode)
- Market filtering and validation

Polymarket uses a Central Limit Order Book (CLOB) for trading.
BTC 15-minute markets are found at https://polymarket.com/crypto/15M
"""

import time
import re
import requests
import httpx
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json

import config


@dataclass
class Market:
    """Represents a Polymarket market with relevant trading data."""
    market_id: str
    condition_id: str
    question: str
    asset: str  # BTC, ETH, etc.
    duration_minutes: int
    start_time: datetime
    end_time: datetime
    yes_price: float  # Current Yes odds (0.0 - 1.0)
    no_price: float   # Current No odds (0.0 - 1.0)
    liquidity: float  # Total liquidity in USD
    volume: float     # Trading volume
    is_active: bool
    tokens: Dict[str, str]  # Token IDs for Yes/No positions


class PolymarketClient:
    """
    Client for interacting with Polymarket CLOB API.
    
    Handles authentication, market fetching, and order placement.
    """
    
    def __init__(self):
        self.clob_url = config.POLYMARKET_API_URL
        self.gamma_url = config.POLYMARKET_GAMMA_API_URL
        self.api_key = config.POLYMARKET_API_KEY
        self.api_secret = config.POLYMARKET_API_SECRET
        self.passphrase = config.POLYMARKET_PASSPHRASE
        
        # Track API calls for rate limiting
        self._api_calls: List[float] = []
        
        # Cache for already-traded markets (prevent duplicate trades)
        self.traded_markets: set = set()
    
    def _rate_limit_check(self):
        """
        Ensure we don't exceed rate limits.
        Clears old timestamps and waits if necessary.
        """
        now = time.time()
        # Remove timestamps older than 60 seconds
        self._api_calls = [t for t in self._api_calls if now - t < 60]
        
        if len(self._api_calls) >= config.MAX_API_CALLS_PER_MINUTE:
            # Wait until oldest call is more than 60 seconds old
            sleep_time = 60 - (now - self._api_calls[0]) + 1
            if sleep_time > 0:
                print(f"⏳ Rate limit reached, waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)
        
        self._api_calls.append(time.time())
    
    def _make_request(
        self, 
        method: str, 
        url: str, 
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        authenticated: bool = False
    ) -> Optional[Dict]:
        """
        Make an HTTP request with error handling and rate limiting.
        
        Returns None on error (never crashes).
        """
        self._rate_limit_check()
        
        headers = {"Content-Type": "application/json"}
        
        # Add authentication headers if needed (for live trading)
        if authenticated and self.api_key and self.api_secret:
            timestamp = str(int(time.time() * 1000))
            headers.update({
                "POLY-API-KEY": self.api_key,
                "POLY-TIMESTAMP": timestamp,
                "POLY-PASSPHRASE": self.passphrase or "",
            })
            # Add signature if secret is available
            if self.api_secret:
                message = timestamp + method.upper() + url
                if data:
                    message += json.dumps(data)
                signature = hmac.new(
                    self.api_secret.encode(),
                    message.encode(),
                    hashlib.sha256
                ).hexdigest()
                headers["POLY-SIGNATURE"] = signature
        
        try:
            if method.upper() == "GET":
                response = requests.get(url, params=params, headers=headers, timeout=10)
            elif method.upper() == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=10)
            else:
                print(f"❌ Unsupported HTTP method: {method}")
                return None
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            print(f"⚠️ Request timeout: {url}")
            return None
        except requests.exceptions.ConnectionError:
            print(f"⚠️ Connection error: {url}")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"⚠️ HTTP error {response.status_code}: {e}")
            return None
        except json.JSONDecodeError:
            print(f"⚠️ Invalid JSON response from: {url}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error in API request: {e}")
            return None
    
    def fetch_btc_15min_markets(self) -> List[Market]:
        """
        Fetch all active BTC 15-minute Up/Down markets.

        Uses a fast predictive approach - markets start every 15 minutes
        at :00, :15, :30, :45, so we calculate the expected slug and query directly.

        Returns a list of Market objects that match our criteria.
        """
        markets = []

        # Fast path: calculate expected market slugs based on current time
        market_slugs = self._calculate_current_market_slugs()
        
        for slug in market_slugs:
            market = self._fetch_market_by_slug(slug)
            if market and market.is_active:
                markets.append(market)
                break  # Found an active market, no need to check more
        
        if not markets:
            # Fallback: scrape the page (slower but more reliable)
            market_slug = self._find_current_btc_15min_market_from_page()
            if market_slug:
                market = self._fetch_market_by_slug(market_slug)
                if market:
                    markets.append(market)

        if config.VERBOSE_LOGGING:
            if markets:
                print(f"📊 Found {len(markets)} valid BTC 15-min markets")
            else:
                print("📭 No BTC 15-minute markets found on Polymarket")

        return markets
    
    def _calculate_current_market_slugs(self) -> List[str]:
        """
        Calculate the expected market slugs based on current time.
        
        BTC 15-minute markets start every 15 minutes at :00, :15, :30, :45.
        Returns a list of possible slugs (current and previous interval).
        """
        now = datetime.now(timezone.utc)
        now_ts = int(now.timestamp())
        
        # Round down to nearest 15-minute interval
        # 15 minutes = 900 seconds
        current_interval_ts = (now_ts // 900) * 900
        previous_interval_ts = current_interval_ts - 900
        
        slugs = [
            f"btc-updown-15m-{current_interval_ts}",
            f"btc-updown-15m-{previous_interval_ts}",
        ]
        
        if config.VERBOSE_LOGGING:
            age_current = now_ts - current_interval_ts
            print(f"🔍 Checking market slugs (current interval age: {age_current}s)")
        
        return slugs
    
    def _find_current_btc_15min_market_from_page(self) -> Optional[str]:
        """
        Fallback: Find the current active BTC 15min market by scraping the page.
        
        This is slower but more reliable if the predictive approach fails.
        """
        if config.VERBOSE_LOGGING:
            print("🔍 Fallback: Scraping Polymarket page for market...")
        
        try:
            # Search on Polymarket's crypto 15min page
            page_url = "https://polymarket.com/crypto/15M"
            resp = httpx.get(
                page_url, 
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                timeout=10,
                follow_redirects=True
            )
            resp.raise_for_status()
            
            # Find the BTC market slug in the HTML
            pattern = r'btc-updown-15m-(\d+)'
            matches = re.findall(pattern, resp.text)
            
            if not matches:
                if config.VERBOSE_LOGGING:
                    print("⚠️ No BTC 15min market slugs found in page HTML")
                return None
            
            # Prefer the most recent timestamp that is still OPEN.
            # 15min markets close 900s (15 minutes) after the timestamp in the slug.
            now_ts = int(datetime.now().timestamp())
            all_ts = sorted((int(ts) for ts in matches), reverse=True)
            
            # Find open markets (within 900 seconds of start time)
            open_ts = [ts for ts in all_ts if now_ts < (ts + 900)]
            
            if not open_ts:
                # All markets closed, use the most recent one anyway
                chosen_ts = all_ts[0]
                if config.VERBOSE_LOGGING:
                    print(f"⚠️ All markets closed, using most recent: {chosen_ts}")
            else:
                chosen_ts = open_ts[0]
            
            slug = f"btc-updown-15m-{chosen_ts}"
            
            if config.VERBOSE_LOGGING:
                print(f"✅ Market found: {slug}")
            
            return slug
            
        except httpx.TimeoutException:
            print("⚠️ Timeout fetching Polymarket crypto page")
            return None
        except httpx.HTTPError as e:
            print(f"⚠️ HTTP error fetching crypto page: {e}")
            return None
        except Exception as e:
            print(f"❌ Error searching for BTC 15min market: {e}")
            return None
    
    def _fetch_market_by_slug(self, slug: str) -> Optional['Market']:
        """
        Fetch detailed market data using the market slug.
        
        Args:
            slug: Market slug like 'btc-updown-15m-1735689600'
        
        Returns:
            Market object or None if not found
        """
        try:
            # Try Gamma API first - it has detailed market info
            url = f"{self.gamma_url}/markets"
            params = {"slug": slug}
            
            response = self._make_request("GET", url, params=params)
            
            if response and isinstance(response, list) and len(response) > 0:
                market_data = response[0]
                return self._parse_market_from_slug_data(market_data, slug)
            
            # Fallback: construct market from slug timestamp
            return self._construct_market_from_slug(slug)
            
        except Exception as e:
            print(f"⚠️ Error fetching market by slug: {e}")
            return self._construct_market_from_slug(slug)
    
    def _construct_market_from_slug(self, slug: str) -> Optional['Market']:
        """
        Construct a Market object from the slug timestamp.
        
        The slug format is 'btc-updown-15m-<timestamp>' where timestamp
        is the Unix epoch when the market started.
        """
        try:
            # Extract timestamp from slug
            match = re.search(r'btc-updown-15m-(\d+)', slug)
            if not match:
                return None
            
            timestamp = int(match.group(1))
            start_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            end_time = datetime.fromtimestamp(timestamp + 900, tz=timezone.utc)  # 15 minutes later
            
            # Fetch current prices from Gamma API
            prices = self._fetch_prices_for_slug(slug)
            up_price = prices.get("up", 0.5) if prices else 0.5
            down_price = prices.get("down", 0.5) if prices else 0.5
            
            return Market(
                market_id=slug,
                condition_id=slug,
                question=f"BTC Up or Down? (Started at {start_time.strftime('%H:%M:%S UTC')})",
                asset="BTC",
                duration_minutes=15,
                start_time=start_time,
                end_time=end_time,
                yes_price=up_price,  # Up = Yes
                no_price=down_price,  # Down = No
                liquidity=1000.0,  # Default estimate
                volume=0.0,
                is_active=True,
                tokens={"up": f"{slug}-up", "down": f"{slug}-down"}
            )
            
        except Exception as e:
            print(f"⚠️ Error constructing market from slug: {e}")
            return None
    
    def _fetch_prices_for_slug(self, slug: str) -> Optional[Dict[str, float]]:
        """
        Fetch current Yes/No prices for a market slug.
        
        Returns dict with 'up' and 'down' prices, or None on error.
        Note: BTC 15min markets use Up/Down, not Yes/No.
        """
        try:
            # Try to get prices from Gamma API
            url = f"{self.gamma_url}/markets"
            params = {"slug": slug}
            
            response = self._make_request("GET", url, params=params)
            
            if response and isinstance(response, list) and len(response) > 0:
                market_data = response[0]
                outcome_prices = market_data.get("outcomePrices", [])
                
                # Handle JSON-encoded string
                if isinstance(outcome_prices, str):
                    outcome_prices = json.loads(outcome_prices)
                
                if len(outcome_prices) >= 2:
                    return {
                        "up": float(outcome_prices[0]),
                        "down": float(outcome_prices[1])
                    }
            
            return None
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Error fetching prices: {e}")
            return None
    
    def _parse_market_from_slug_data(self, data: Dict, slug: str) -> Optional['Market']:
        """
        Parse market data fetched by slug into a Market object.
        
        BTC 15min markets use Up/Down outcomes (not Yes/No).
        """
        try:
            # Extract timestamp from slug for timing
            match = re.search(r'btc-updown-15m-(\d+)', slug)
            timestamp = int(match.group(1)) if match else int(time.time())
            
            start_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            end_time = datetime.fromtimestamp(timestamp + 900, tz=timezone.utc)
            
            # Extract prices - may be JSON-encoded string
            up_price = 0.5
            down_price = 0.5
            outcome_prices = data.get("outcomePrices", [])
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            
            if len(outcome_prices) >= 2:
                try:
                    up_price = float(outcome_prices[0])
                    down_price = float(outcome_prices[1])
                except (ValueError, TypeError):
                    pass
            
            # Extract token IDs - may be JSON-encoded string
            tokens = {}
            clob_token_ids = data.get("clobTokenIds", [])
            if isinstance(clob_token_ids, str):
                clob_token_ids = json.loads(clob_token_ids)
            
            outcomes = data.get("outcomes", ["Up", "Down"])
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            
            # Map outcomes to tokens (Up/Down for BTC markets)
            if len(clob_token_ids) >= 2 and len(outcomes) >= 2:
                for i, outcome in enumerate(outcomes):
                    if i < len(clob_token_ids):
                        # Normalize to lowercase for consistency
                        tokens[outcome.lower()] = clob_token_ids[i]
            else:
                tokens = {"up": f"{slug}-up", "down": f"{slug}-down"}
            
            return Market(
                market_id=data.get("id", slug),
                condition_id=data.get("conditionId", slug),
                question=data.get("question", f"BTC 15-min Up/Down ({slug})"),
                asset="BTC",
                duration_minutes=15,
                start_time=start_time,
                end_time=end_time,
                yes_price=up_price,  # Up = Yes (price will be higher)
                no_price=down_price,  # Down = No (price will not be higher)
                liquidity=float(data.get("liquidity", 1000) or 1000),
                volume=float(data.get("volume", 0) or data.get("volume24hr", 0) or 0),
                is_active=data.get("active", True),
                tokens=tokens
            )
            
        except Exception as e:
            print(f"⚠️ Error parsing market data: {e}")
            return None
    
    def _fetch_markets_from_gamma_api(self) -> List['Market']:
        """
        Fallback method to fetch markets from Gamma API.
        
        Searches for BTC 15-minute markets using the traditional API approach.
        """
        markets = []
        
        url = f"{self.gamma_url}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": 100,
        }

        response = self._make_request("GET", url, params=params)

        if not response:
            return markets

        # Process each market
        for market_data in response if isinstance(response, list) else []:
            try:
                market = self._parse_market(market_data)
                if market and self._is_valid_btc_15min_market(market):
                    markets.append(market)
            except Exception as e:
                if config.VERBOSE_LOGGING:
                    print(f"⚠️ Error parsing market: {e}")
                continue

        return markets
    
    def _parse_market(self, data: Dict) -> Optional[Market]:
        """
        Parse raw market data into a Market object.
        
        Returns None if parsing fails or market is invalid.
        """
        try:
            # Extract market question/title to determine asset and type
            question = data.get("question", "").lower()
            description = data.get("description", "").lower()
            
            # Check if this is a BTC market
            if "btc" not in question and "bitcoin" not in question:
                return None
            
            # Check if this is an up/down market (not a price target market)
            if "up" not in question and "down" not in question:
                if "higher" not in question and "lower" not in question:
                    return None
            
            # Parse timestamps
            start_time_str = data.get("startDate") or data.get("start_date_iso")
            end_time_str = data.get("endDate") or data.get("end_date_iso")
            
            if not start_time_str or not end_time_str:
                return None
            
            # Handle different timestamp formats
            try:
                if "T" in str(start_time_str):
                    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                    end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                else:
                    start_time = datetime.fromtimestamp(int(start_time_str) / 1000, tz=timezone.utc)
                    end_time = datetime.fromtimestamp(int(end_time_str) / 1000, tz=timezone.utc)
            except (ValueError, TypeError):
                return None
            
            # Calculate duration in minutes
            duration = (end_time - start_time).total_seconds() / 60
            
            # Extract token IDs for Yes/No positions
            tokens = {}
            clob_token_ids = data.get("clobTokenIds", [])
            outcomes = data.get("outcomes", [])
            
            if len(clob_token_ids) >= 2 and len(outcomes) >= 2:
                for i, outcome in enumerate(outcomes):
                    if i < len(clob_token_ids):
                        tokens[outcome.lower()] = clob_token_ids[i]
            
            # Extract prices from outcomes or separate API call
            yes_price = 0.5
            no_price = 0.5
            outcome_prices = data.get("outcomePrices", [])
            if len(outcome_prices) >= 2:
                try:
                    yes_price = float(outcome_prices[0])
                    no_price = float(outcome_prices[1])
                except (ValueError, TypeError):
                    pass
            
            return Market(
                market_id=data.get("id", "") or data.get("condition_id", ""),
                condition_id=data.get("conditionId", "") or data.get("condition_id", ""),
                question=data.get("question", "Unknown"),
                asset="BTC",
                duration_minutes=int(duration),
                start_time=start_time,
                end_time=end_time,
                yes_price=yes_price,
                no_price=no_price,
                liquidity=float(data.get("liquidity", 0) or 0),
                volume=float(data.get("volume", 0) or data.get("volume24hr", 0) or 0),
                is_active=data.get("active", True),
                tokens=tokens
            )
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Market parsing error: {e}")
            return None
    
    def _is_valid_btc_15min_market(self, market: Market) -> bool:
        """
        Check if a market meets our trading criteria.
        
        Returns True only if ALL conditions are met.
        """
        # Check asset
        if market.asset != "BTC":
            return False
        
        # Check duration (allow small variance for 15-minute markets)
        if not (14 <= market.duration_minutes <= 16):
            return False
        
        # Check if market is active
        if not market.is_active:
            return False
        
        # Check if market has valid token IDs for trading
        if not market.tokens:
            return False
        
        return True
    
    def get_market_age_seconds(self, market: Market) -> float:
        """
        Calculate how many seconds ago the market started.
        
        Returns the age in seconds (positive = already started).
        """
        now = datetime.now(timezone.utc)
        age = (now - market.start_time).total_seconds()
        return age
    
    def is_market_fresh(self, market: Market) -> bool:
        """
        Check if a market is fresh enough to trade.
        
        Returns True if market age <= MAX_MARKET_AGE_SECONDS.
        """
        age = self.get_market_age_seconds(market)
        
        # Market hasn't started yet
        if age < 0:
            return False
        
        # Market is too old
        if age > config.MAX_MARKET_AGE_SECONDS:
            return False
        
        return True
    
    def has_sufficient_liquidity(self, market: Market) -> bool:
        """
        Check if market has enough liquidity for safe trading.
        
        Low liquidity = high slippage = bad fills.
        """
        return market.liquidity >= config.MIN_LIQUIDITY_USD
    
    def has_reasonable_spread(self, market: Market) -> bool:
        """
        Check if bid/ask spread is acceptable.
        
        In a fair market, Yes + No prices should be close to 1.0.
        Wide spreads indicate high vig or low liquidity.
        """
        combined = market.yes_price + market.no_price
        return combined <= config.MAX_SPREAD_COMBINED
    
    def was_already_traded(self, market: Market) -> bool:
        """
        Check if we've already traded this market.
        
        Prevents duplicate trades on the same market.
        """
        return market.market_id in self.traded_markets
    
    def mark_as_traded(self, market: Market):
        """Mark a market as traded to prevent duplicates."""
        self.traded_markets.add(market.market_id)
    
    def fetch_market_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Fetch the order book for a specific token.
        
        Returns best bid/ask and depth information.
        """
        url = f"{self.clob_url}/book"
        params = {"token_id": token_id}
        
        return self._make_request("GET", url, params=params)
    
    def get_best_prices(self, market: Market, side: str) -> Optional[Dict[str, float]]:
        """
        Get the best available prices for a market side.
        
        Args:
            market: The market to query
            side: "yes" or "no"
        
        Returns:
            Dict with 'bid', 'ask', 'mid' prices, or None on error
        """
        token_id = market.tokens.get(side.lower())
        if not token_id:
            return None
        
        orderbook = self.fetch_market_orderbook(token_id)
        if not orderbook:
            return None
        
        try:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            best_bid = float(bids[0]["price"]) if bids else 0.0
            best_ask = float(asks[0]["price"]) if asks else 1.0
            mid = (best_bid + best_ask) / 2
            
            return {
                "bid": best_bid,
                "ask": best_ask,
                "mid": mid
            }
        except (IndexError, KeyError, TypeError):
            return None
    
    def place_order(
        self,
        market: Market,
        side: str,  # "yes" or "no"
        amount_usd: float,
        order_type: str = "market"
    ) -> Optional[Dict]:
        """
        Place an order on Polymarket (LIVE MODE ONLY).
        
        In TEST_MODE, this should not be called - use execution.py simulation instead.
        
        Args:
            market: Market to trade
            side: "yes" or "no"
            amount_usd: Amount in USD to spend
            order_type: "market" (limit orders not supported in v1)
        
        Returns:
            Order confirmation dict or None on error
        """
        if config.TEST_MODE:
            print("❌ place_order called in TEST_MODE - this should not happen")
            return None
        
        token_id = market.tokens.get(side.lower())
        if not token_id:
            print(f"❌ No token ID found for side: {side}")
            return None
        
        # Get current price to calculate shares
        prices = self.get_best_prices(market, side)
        if not prices:
            print("❌ Could not fetch current prices")
            return None
        
        # For market orders, we buy at the ask price
        price = prices["ask"]
        if price <= 0:
            print("❌ Invalid ask price")
            return None
        
        # Calculate shares (amount / price)
        shares = amount_usd / price
        
        # Build order payload
        order_data = {
            "tokenID": token_id,
            "price": str(price),
            "size": str(shares),
            "side": "BUY",
            "orderType": "GTC",  # Good till cancelled
        }
        
        url = f"{self.clob_url}/order"
        
        result = self._make_request("POST", url, data=order_data, authenticated=True)
        
        if result:
            print(f"✅ Order placed: {side.upper()} ${amount_usd:.2f}")
            self.mark_as_traded(market)
        else:
            print("❌ Order placement failed")
        
        return result
    
    def get_position(self, market: Market) -> Optional[Dict]:
        """
        Get current position in a market.
        
        Returns position details or None if no position/error.
        """
        if config.TEST_MODE:
            return None
        
        # This would query the user's positions
        # Implementation depends on Polymarket API structure
        url = f"{self.clob_url}/positions"
        params = {"market": market.condition_id}
        
        return self._make_request("GET", url, params=params, authenticated=True)


# Singleton client instance
_client: Optional[PolymarketClient] = None


def get_client() -> PolymarketClient:
    """Get or create the Polymarket client singleton."""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client
