"""
Market module for Polymarket API interactions.

This module handles:
- Fetching active BTC 15-minute Up/Down markets
- Fetching current odds
- Fetching account balance (LIVE mode)
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
from auth import get_auth, AuthLevel, AuthError


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
    
    Handles authentication, market fetching, balance queries, and order placement.
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
        
        # Auth module for authenticated requests
        self._auth = get_auth()
    
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
            # Cap maximum wait time to 10 seconds to prevent long stalls
            sleep_time = min(sleep_time, 10)
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
        authenticated: bool = False,
        retries: int = 2
    ) -> Optional[Dict]:
        """
        Make an HTTP request with error handling, rate limiting, and retries.
        
        Args:
            method: HTTP method (GET, POST)
            url: Full URL to request
            params: Query parameters for GET requests
            data: JSON body for POST requests
            authenticated: Whether to use L2 auth headers
            retries: Number of retry attempts
        
        Returns None on error (never crashes).
        """
        last_error = None
        
        for attempt in range(retries + 1):
            self._rate_limit_check()
            
            # Get headers - use auth module if authenticated
            if authenticated and not config.TEST_MODE:
                try:
                    # Extract path from URL for auth signature
                    # IMPORTANT: Sign only the base path, NOT including query parameters
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    path = parsed.path  # Don't include query params in signature
                    
                    body_str = json.dumps(data) if data else ""
                    # Use L2 headers for authenticated requests (HMAC-based)
                    headers = self._auth.get_l2_headers(method, path, body_str)
                except AuthError as e:
                    print(f"❌ Authentication error: {e}")
                    return None
            else:
                headers = {"Content-Type": "application/json"}
            
            try:
                # Reduced timeout from 10s to 5s for faster failure detection
                timeout = 5
                if method.upper() == "GET":
                    response = requests.get(url, params=params, headers=headers, timeout=timeout)
                elif method.upper() == "POST":
                    response = requests.post(url, json=data, headers=headers, timeout=timeout)
                else:
                    print(f"❌ Unsupported HTTP method: {method}")
                    return None
                
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.Timeout:
                last_error = "timeout"
                if attempt < retries:
                    time.sleep(1)  # Brief wait before retry
                    continue
            except requests.exceptions.ConnectionError:
                last_error = "connection"
                if attempt < retries:
                    time.sleep(2)  # Slightly longer wait for connection issues
                    continue
            except requests.exceptions.HTTPError as e:
                if config.VERBOSE_LOGGING:
                    print(f"⚠️ HTTP error {response.status_code}: {e}")
                return None
            except json.JSONDecodeError:
                if config.VERBOSE_LOGGING:
                    print(f"⚠️ Invalid JSON response from: {url}")
                return None
            except Exception as e:
                print(f"❌ Unexpected error in API request: {e}")
                return None
        
        # All retries exhausted
        if last_error and config.VERBOSE_LOGGING:
            print(f"⚠️ Request failed ({last_error}): {url}")
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
                timeout=5,  # Reduced from 10s to 5s
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
        
        IMPORTANT: This method also fetches real token IDs from the API,
        which are required for placing orders in LIVE mode.
        """
        try:
            # Extract timestamp from slug
            match = re.search(r'btc-updown-15m-(\d+)', slug)
            if not match:
                return None
            
            timestamp = int(match.group(1))
            start_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            end_time = datetime.fromtimestamp(timestamp + 900, tz=timezone.utc)  # 15 minutes later
            
            # Fetch current prices AND token IDs from Gamma API
            market_info = self._fetch_market_info_for_slug(slug)
            
            up_price = 0.5
            down_price = 0.5
            tokens = {}
            
            if market_info:
                up_price = market_info.get("up_price", 0.5)
                down_price = market_info.get("down_price", 0.5)
                tokens = market_info.get("tokens", {})
            
            # Validate tokens for LIVE mode
            if not config.TEST_MODE and (not tokens.get("up") or not tokens.get("down")):
                print(f"⚠️ WARNING: No valid token IDs found for {slug}")
                print(f"   LIVE trading will not work without token IDs")
                # Still return market for logging purposes, but trading will fail
            
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
                tokens=tokens
            )
            
        except Exception as e:
            print(f"⚠️ Error constructing market from slug: {e}")
            return None
    
    def _fetch_market_info_for_slug(self, slug: str) -> Optional[Dict]:
        """
        Fetch full market info including token IDs for a market slug.
        
        Returns dict with 'up_price', 'down_price', and 'tokens' dict.
        This is essential for LIVE trading as we need real token IDs.
        """
        try:
            # Try to get full market data from Gamma API
            url = f"{self.gamma_url}/markets"
            params = {"slug": slug}
            
            response = self._make_request("GET", url, params=params)
            
            if response and isinstance(response, list) and len(response) > 0:
                market_data = response[0]
                
                # Extract prices
                up_price = 0.5
                down_price = 0.5
                outcome_prices = market_data.get("outcomePrices", [])
                
                # Handle JSON-encoded string
                if isinstance(outcome_prices, str):
                    outcome_prices = json.loads(outcome_prices)
                
                if len(outcome_prices) >= 2:
                    up_price = float(outcome_prices[0])
                    down_price = float(outcome_prices[1])
                
                # Extract token IDs - CRITICAL for LIVE trading
                tokens = {}
                clob_token_ids = market_data.get("clobTokenIds", [])
                if isinstance(clob_token_ids, str):
                    clob_token_ids = json.loads(clob_token_ids)
                
                outcomes = market_data.get("outcomes", ["Up", "Down"])
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)
                
                # Map outcomes to tokens
                if len(clob_token_ids) >= 2 and len(outcomes) >= 2:
                    for i, outcome in enumerate(outcomes):
                        if i < len(clob_token_ids):
                            tokens[outcome.lower()] = clob_token_ids[i]
                
                if config.VERBOSE_LOGGING:
                    print(f"   Token IDs fetched: {list(tokens.keys())}")
                
                return {
                    "up_price": up_price,
                    "down_price": down_price,
                    "tokens": tokens
                }
            
            return None
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Error fetching market info: {e}")
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
        side: str,  # "yes" or "no" (or "up" / "down" for BTC markets)
        amount_usd: float,
        order_type: str = "market",
        max_slippage_percent: float = 2.0
    ) -> Optional[Dict]:
        """
        Place an order on Polymarket CLOB (LIVE MODE ONLY).
        
        This method handles the full order flow:
        1. Validates inputs and authentication
        2. Fetches current orderbook prices
        3. Applies slippage protection
        4. Signs the order with wallet
        5. Submits to CLOB API
        6. Returns order confirmation
        
        In TEST_MODE, this should not be called - use execution.py simulation instead.
        
        Args:
            market: Market to trade
            side: "yes"/"no" or "up"/"down" for BTC markets
            amount_usd: Amount in USD to spend
            order_type: "market" or "limit" (only market supported in v1)
            max_slippage_percent: Maximum allowed slippage (default 2%)
        
        Returns:
            Order confirmation dict with order_id, status, etc. or None on error
            
        Example:
            >>> result = client.place_order(market, "up", 10.0)
            >>> if result:
            ...     print(f"Order placed: {result['order_id']}")
        """
        if config.TEST_MODE:
            print("❌ place_order called in TEST_MODE - this should not happen")
            return None
        
        # Validate authentication
        if not self._auth.is_ready(AuthLevel.L2):
            print("❌ Cannot place order: L2 authentication (wallet) not configured")
            return None
        
        # Normalize side for BTC up/down markets
        side_normalized = self._normalize_side(side)
        
        # Get token ID for the side we want to buy
        token_id = market.tokens.get(side_normalized)
        if not token_id:
            print(f"❌ No token ID found for side: {side} (normalized: {side_normalized})")
            print(f"   Available tokens: {list(market.tokens.keys())}")
            return None
        
        # Validate amount
        if amount_usd <= 0:
            print(f"❌ Invalid order amount: ${amount_usd}")
            return None
        
        if amount_usd < config.MIN_BET_SIZE_USD:
            print(f"❌ Order amount ${amount_usd:.2f} below minimum ${config.MIN_BET_SIZE_USD:.2f}")
            return None
        
        # Verify we have sufficient balance
        if not self.verify_sufficient_balance(amount_usd):
            return None
        
        # Get current market prices
        prices = self.get_best_prices(market, side_normalized)
        if not prices:
            print("❌ Could not fetch current market prices")
            return None
        
        # Calculate order price with slippage protection
        order_price = self._calculate_order_price(prices, max_slippage_percent)
        if order_price is None:
            print("❌ Could not calculate valid order price")
            return None
        
        # Calculate number of shares to buy
        # shares = amount_usd / price (since each share pays $1 on win)
        shares = amount_usd / order_price
        
        # Round shares to reasonable precision (Polymarket uses 2 decimals typically)
        shares = round(shares, 4)
        
        if shares <= 0:
            print(f"❌ Invalid share calculation: {shares}")
            return None
        
        # Generate unique nonce for replay protection
        nonce = int(time.time() * 1000)
        
        # Build order data
        order_data = {
            "token_id": token_id,
            "side": "BUY",
            "size": str(shares),
            "price": str(round(order_price, 4)),
            "nonce": nonce,
            "expiration": 0,  # No expiration (GTC)
            "order_type": "GTC",
        }
        
        # Sign the order using L2 auth
        try:
            signature = self._auth.sign_order(order_data)
            order_data["signature"] = signature
        except AuthError as e:
            print(f"❌ Failed to sign order: {e}")
            return None
        
        # Add wallet address
        wallet_address = self._auth.get_wallet_address()
        if wallet_address:
            order_data["maker"] = wallet_address
        
        # Log order details before submission
        if config.VERBOSE_LOGGING:
            print(f"📤 Submitting order:")
            print(f"   Token: {token_id[:16]}...")
            print(f"   Side: BUY {side.upper()}")
            print(f"   Amount: ${amount_usd:.2f}")
            print(f"   Price: {order_price:.4f}")
            print(f"   Shares: {shares:.4f}")
        
        # Submit order to CLOB
        url = f"{self.clob_url}/order"
        result = self._make_request("POST", url, data=order_data, authenticated=True)
        
        if result is None:
            print("❌ Order submission failed - no response from API")
            return None
        
        # Parse and validate response
        order_result = self._parse_order_response(result, order_data, amount_usd)
        
        if order_result and order_result.get("success"):
            print(f"✅ Order placed successfully!")
            print(f"   Order ID: {order_result.get('order_id', 'N/A')}")
            print(f"   Status: {order_result.get('status', 'N/A')}")
            self.mark_as_traded(market)
        else:
            error_msg = order_result.get("error", "Unknown error") if order_result else "No response"
            print(f"❌ Order placement failed: {error_msg}")
        
        return order_result
    
    def _normalize_side(self, side: str) -> str:
        """
        Normalize the side string to match token keys.
        
        Handles both Yes/No and Up/Down market conventions.
        """
        side_lower = side.lower().strip()
        
        # Map common variations
        side_map = {
            "yes": "yes",
            "no": "no",
            "up": "up",
            "down": "down",
            "higher": "up",
            "lower": "down",
            "buy": "yes",
            "sell": "no",
        }
        
        return side_map.get(side_lower, side_lower)
    
    def _calculate_order_price(
        self, 
        prices: Dict[str, float], 
        max_slippage_percent: float
    ) -> Optional[float]:
        """
        Calculate the order price with slippage protection.
        
        For market buy orders, we use the ask price plus a small buffer.
        
        Args:
            prices: Dict with 'bid', 'ask', 'mid' prices
            max_slippage_percent: Maximum allowed slippage
            
        Returns:
            Order price, or None if slippage too high
        """
        ask_price = prices.get("ask", 0)
        mid_price = prices.get("mid", 0)
        
        if ask_price <= 0 or ask_price >= 1.0:
            print(f"⚠️ Invalid ask price: {ask_price}")
            return None
        
        if mid_price <= 0:
            mid_price = ask_price
        
        # Calculate slippage from mid to ask
        slippage = ((ask_price - mid_price) / mid_price) * 100 if mid_price > 0 else 0
        
        if slippage > max_slippage_percent:
            print(f"⚠️ Slippage too high: {slippage:.2f}% > {max_slippage_percent}%")
            return None
        
        # Use ask price for immediate fill
        # Add small buffer (0.1%) to ensure fill
        order_price = min(ask_price * 1.001, 0.99)  # Cap at 0.99
        
        return round(order_price, 4)
    
    def _parse_order_response(
        self, 
        response: Dict, 
        order_data: Dict,
        amount_usd: float
    ) -> Dict:
        """
        Parse the order response from the CLOB API.
        
        Handles different response formats and extracts key information.
        
        Args:
            response: Raw API response
            order_data: The order data we submitted
            amount_usd: Original order amount
            
        Returns:
            Standardized order result dict
        """
        result = {
            "success": False,
            "order_id": None,
            "status": None,
            "filled_size": 0,
            "filled_price": 0,
            "amount_usd": amount_usd,
            "error": None,
            "raw_response": response,
        }
        
        try:
            # Check for error responses
            if "error" in response:
                result["error"] = response["error"]
                return result
            
            if "message" in response and "error" in response.get("message", "").lower():
                result["error"] = response["message"]
                return result
            
            # Extract order ID (various possible field names)
            order_id = (
                response.get("orderID") or 
                response.get("order_id") or 
                response.get("id") or
                response.get("orderId")
            )
            result["order_id"] = order_id
            
            # Extract status
            status = (
                response.get("status") or 
                response.get("orderStatus") or
                "SUBMITTED"
            )
            result["status"] = status.upper() if isinstance(status, str) else status
            
            # Check if order was accepted
            if order_id or status in ["SUBMITTED", "OPEN", "PENDING", "FILLED", "PARTIAL"]:
                result["success"] = True
            
            # Extract fill information if available
            if "filledSize" in response:
                result["filled_size"] = float(response["filledSize"])
            if "avgPrice" in response or "averagePrice" in response:
                result["filled_price"] = float(
                    response.get("avgPrice") or response.get("averagePrice") or 0
                )
            
            # For immediate fills
            if response.get("filled") or status == "FILLED":
                result["filled_size"] = float(order_data.get("size", 0))
                result["filled_price"] = float(order_data.get("price", 0))
            
        except Exception as e:
            result["error"] = f"Error parsing response: {e}"
        
        return result

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: The order ID to cancel
            
        Returns:
            True if cancelled successfully, False otherwise
        """
        if config.TEST_MODE:
            return True
        
        if not self._auth.is_ready(AuthLevel.L2):
            print("❌ Cannot cancel order: L2 authentication not configured")
            return False
        
        url = f"{self.clob_url}/order/{order_id}"
        
        try:
            # DELETE request for cancellation
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path
            
            headers = self._auth.get_l1_headers("DELETE", path)
            
            response = requests.delete(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            print(f"✅ Order {order_id} cancelled")
            return True
            
        except requests.exceptions.HTTPError as e:
            print(f"❌ Failed to cancel order: {e}")
            return False
        except Exception as e:
            print(f"❌ Error cancelling order: {e}")
            return False

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Get the current status of an order.
        
        Args:
            order_id: The order ID to check
            
        Returns:
            Order status dict or None on error
        """
        if config.TEST_MODE:
            return {"order_id": order_id, "status": "FILLED"}
        
        if not self._auth.is_ready(AuthLevel.L1):
            return None
        
        url = f"{self.clob_url}/order/{order_id}"
        return self._make_request("GET", url, authenticated=True)

    def wait_for_order_fill(
        self,
        order_id: str,
        max_wait_seconds: int = 60,
        poll_interval: float = 2.0
    ) -> Dict:
        """
        Wait for an order to be filled, with timeout.
        
        Polls the order status until it's filled, cancelled, or timeout.
        
        Args:
            order_id: The order ID to monitor
            max_wait_seconds: Maximum time to wait for fill
            poll_interval: Time between status checks
            
        Returns:
            Dict with:
                - success: bool - Whether order was filled
                - status: str - Final order status
                - filled_price: float - Average fill price (if filled)
                - filled_shares: float - Number of shares filled
                - order_id: str - The order ID
                - error: str - Error message (if any)
                
        Example:
            >>> result = client.wait_for_order_fill("order-123", max_wait_seconds=30)
            >>> if result["success"]:
            ...     print(f"Filled {result['filled_shares']} @ ${result['filled_price']}")
        """
        if config.TEST_MODE:
            # In test mode, simulate instant fill
            return {
                "success": True,
                "status": "FILLED",
                "filled_price": 0.50,
                "filled_shares": 10.0,
                "order_id": order_id,
                "error": None
            }
        
        if config.VERBOSE_LOGGING:
            print(f"⏳ Waiting for order {order_id} to fill...")
        
        start_time = time.time()
        last_status = None
        
        while (time.time() - start_time) < max_wait_seconds:
            try:
                status_data = self.get_order_status(order_id)
                
                if status_data is None:
                    print(f"⚠️ Could not fetch order status, retrying...")
                    time.sleep(poll_interval)
                    continue
                
                status = self._parse_order_status(status_data)
                
                if status != last_status and config.VERBOSE_LOGGING:
                    print(f"   Order status: {status}")
                    last_status = status
                
                # Check for terminal states
                if status in ["FILLED", "MATCHED"]:
                    fill_info = self._extract_fill_info(status_data)
                    if config.VERBOSE_LOGGING:
                        print(f"✅ Order filled! {fill_info['filled_shares']:.2f} shares @ ${fill_info['filled_price']:.4f}")
                    return {
                        "success": True,
                        "status": status,
                        "filled_price": fill_info["filled_price"],
                        "filled_shares": fill_info["filled_shares"],
                        "order_id": order_id,
                        "error": None
                    }
                
                elif status in ["CANCELLED", "CANCELED", "EXPIRED", "REJECTED"]:
                    reason = status_data.get("reason") or status_data.get("message") or "Unknown"
                    print(f"❌ Order {status}: {reason}")
                    return {
                        "success": False,
                        "status": status,
                        "filled_price": 0.0,
                        "filled_shares": 0.0,
                        "order_id": order_id,
                        "error": f"Order {status}: {reason}"
                    }
                
                elif status == "PARTIAL":
                    # Partially filled - keep waiting or handle partial
                    fill_info = self._extract_fill_info(status_data)
                    if config.VERBOSE_LOGGING:
                        print(f"   Partial fill: {fill_info['filled_shares']:.2f} shares...")
                
                # Still pending/open, keep waiting
                time.sleep(poll_interval)
                
            except Exception as e:
                print(f"⚠️ Error checking order status: {e}")
                time.sleep(poll_interval)
        
        # Timeout reached
        elapsed = time.time() - start_time
        print(f"⚠️ Order fill timeout after {elapsed:.0f}s")
        
        # Try one final status check
        final_status = self.get_order_status(order_id)
        if final_status:
            status = self._parse_order_status(final_status)
            if status in ["FILLED", "MATCHED"]:
                fill_info = self._extract_fill_info(final_status)
                return {
                    "success": True,
                    "status": status,
                    "filled_price": fill_info["filled_price"],
                    "filled_shares": fill_info["filled_shares"],
                    "order_id": order_id,
                    "error": None
                }
        
        return {
            "success": False,
            "status": "TIMEOUT",
            "filled_price": 0.0,
            "filled_shares": 0.0,
            "order_id": order_id,
            "error": f"Order fill timeout after {max_wait_seconds}s"
        }
    
    def _parse_order_status(self, status_data: Dict) -> str:
        """
        Parse order status from API response.
        
        Handles various API response formats.
        """
        # Try different possible field names
        status = (
            status_data.get("status") or
            status_data.get("orderStatus") or
            status_data.get("state") or
            "UNKNOWN"
        )
        return str(status).upper()
    
    def _extract_fill_info(self, status_data: Dict) -> Dict:
        """
        Extract fill price and shares from order status.
        
        Returns:
            Dict with 'filled_price' and 'filled_shares'
        """
        filled_price = 0.0
        filled_shares = 0.0
        
        try:
            # Try different possible field names
            filled_shares = float(
                status_data.get("filledAmount") or
                status_data.get("filled_amount") or
                status_data.get("matchedAmount") or
                status_data.get("size_matched") or
                status_data.get("filledSize") or
                0.0
            )
            
            # Average fill price
            filled_price = float(
                status_data.get("avgPrice") or
                status_data.get("average_price") or
                status_data.get("matchedPrice") or
                status_data.get("price") or
                0.0
            )
            
            # If we have total cost and shares, calculate price
            if filled_shares > 0 and filled_price == 0:
                total_cost = float(status_data.get("totalCost") or status_data.get("cost") or 0)
                if total_cost > 0:
                    filled_price = total_cost / filled_shares
                    
        except (ValueError, TypeError) as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Error extracting fill info: {e}")
        
        return {
            "filled_price": filled_price,
            "filled_shares": filled_shares
        }
    
    def cancel_order_if_unfilled(
        self,
        order_id: str,
        wait_seconds: int = 10
    ) -> bool:
        """
        Wait briefly for fill, then cancel if not filled.
        
        Useful for time-sensitive orders where we don't want to
        wait indefinitely for a fill.
        
        Args:
            order_id: The order to monitor/cancel
            wait_seconds: How long to wait before cancelling
            
        Returns:
            True if order was filled, False if cancelled/failed
        """
        if config.TEST_MODE:
            return True  # Simulate filled
        
        # Quick check first
        result = self.wait_for_order_fill(order_id, max_wait_seconds=wait_seconds, poll_interval=1.0)
        
        if result["success"]:
            return True
        
        # Not filled - try to cancel
        if result["status"] not in ["CANCELLED", "CANCELED", "EXPIRED", "REJECTED"]:
            print(f"⏰ Order not filled after {wait_seconds}s, cancelling...")
            cancelled = self.cancel_order(order_id)
            if cancelled:
                print("✅ Order cancelled successfully")
            else:
                print("⚠️ Could not cancel order (may have filled)")
                # Re-check status
                final = self.get_order_status(order_id)
                if final and self._parse_order_status(final) in ["FILLED", "MATCHED"]:
                    return True
        
        return False

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

    # ═══════════════════════════════════════════════════════════════════════════════
    # BALANCE & ACCOUNT METHODS (LIVE MODE)
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_usdc_balance(self) -> Optional[float]:
        """
        Get the user's USDC balance on Polymarket.
        
        This queries the CLOB API for the current available balance.
        In TEST_MODE, returns None (use virtual balance instead).
        
        Returns:
            USDC balance as float, or None if error/TEST_MODE
            
        Example:
            >>> client = get_client()
            >>> balance = client.get_usdc_balance()
            >>> if balance is not None:
            ...     print(f"Balance: ${balance:.2f}")
        """
        if config.TEST_MODE:
            if config.VERBOSE_LOGGING:
                print("ℹ️ get_usdc_balance called in TEST_MODE - returning None")
            return None
        
        # Check if auth is ready - need L2 for balance-allowance endpoint
        if not self._auth.is_ready(AuthLevel.L2):
            print("❌ Cannot fetch balance: Authentication not configured (L2 required)")
            return None
        
        try:
            # Polymarket CLOB API endpoint for balance-allowance
            # This is the correct endpoint as per py-clob-client
            # Parameters: asset_type=COLLATERAL for USDC balance
            url = f"{self.clob_url}/balance-allowance?asset_type=COLLATERAL&signature_type=0"
            
            result = self._make_request("GET", url, authenticated=True)
            
            if result is None:
                print("❌ Failed to fetch balance from API")
                return None
            
            # Parse the balance response
            # The API may return balance in different formats
            balance = self._parse_balance_response(result)
            
            if balance is not None and config.VERBOSE_LOGGING:
                print(f"💰 USDC Balance: ${balance:.2f}")
            
            return balance
            
        except Exception as e:
            print(f"❌ Error fetching balance: {e}")
            return None
    
    def _parse_balance_response(self, response: Dict) -> Optional[float]:
        """
        Parse the balance response from the CLOB API.
        
        Handles different response formats that Polymarket might use.
        
        Args:
            response: Raw API response dict
            
        Returns:
            Balance as float, or None if parsing fails
        """
        try:
            # Try different possible response formats
            
            # Format 1: Direct balance field
            if "balance" in response:
                balance_raw = response["balance"]
                # Balance might be in smallest units (6 decimals for USDC)
                if isinstance(balance_raw, str):
                    balance_raw = float(balance_raw)
                # Check if balance is in micro-units (> 1000 suggests smallest units)
                if balance_raw > 10000:
                    return balance_raw / 1_000_000  # USDC has 6 decimals
                return float(balance_raw)
            
            # Format 2: USDC specific field
            if "usdc" in response:
                return float(response["usdc"])
            
            # Format 3: Available balance
            if "available" in response:
                return float(response["available"])
            
            # Format 4: Nested balance object
            if "balances" in response:
                balances = response["balances"]
                if isinstance(balances, dict):
                    # Look for USDC balance
                    for key in ["USDC", "usdc", "usd"]:
                        if key in balances:
                            return float(balances[key])
                elif isinstance(balances, list):
                    # Find USDC in list of balances
                    for bal in balances:
                        if bal.get("asset", "").upper() == "USDC":
                            return float(bal.get("amount", 0))
            
            # Format 5: Collateral balance (Polymarket specific)
            if "collateral" in response:
                return float(response["collateral"])
            
            print(f"⚠️ Unknown balance response format: {list(response.keys())}")
            return None
            
        except (ValueError, TypeError, KeyError) as e:
            print(f"⚠️ Error parsing balance response: {e}")
            return None
    
    def get_all_balances(self) -> Optional[Dict[str, float]]:
        """
        Get all token balances for the user's account.
        
        Returns:
            Dict mapping token/asset names to balances, or None on error
        """
        if config.TEST_MODE:
            return None
        
        if not self._auth.is_ready(AuthLevel.L2):
            print("❌ Cannot fetch balances: Authentication not configured (L2 required)")
            return None
        
        try:
            # Use balance-allowance endpoint for COLLATERAL (USDC)
            url = f"{self.clob_url}/balance-allowance?asset_type=COLLATERAL&signature_type=0"
            result = self._make_request("GET", url, authenticated=True)
            
            if result is None:
                return None
            
            # Parse into a simple dict
            balances = {}
            
            # The response should contain balance field
            if isinstance(result, dict):
                if "balance" in result:
                    balances["USDC"] = float(result["balance"])
                for key, value in result.items():
                    try:
                        balances[key] = float(value)
                    except (ValueError, TypeError):
                        continue
            elif isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        asset = item.get("asset", item.get("token", "unknown"))
                        amount = item.get("amount", item.get("balance", 0))
                        try:
                            balances[asset] = float(amount)
                        except (ValueError, TypeError):
                            continue
            
            return balances if balances else None
            
        except Exception as e:
            print(f"❌ Error fetching balances: {e}")
            return None
    
    def verify_sufficient_balance(self, required_amount: float) -> bool:
        """
        Verify that the account has sufficient USDC balance for a trade.
        
        Args:
            required_amount: Amount in USD needed for the trade
            
        Returns:
            True if balance is sufficient, False otherwise
        """
        if config.TEST_MODE:
            # In test mode, assume we have enough
            return True
        
        balance = self.get_usdc_balance()
        
        if balance is None:
            print("⚠️ Could not verify balance - assuming insufficient")
            return False
        
        # Include buffer for fees
        required_with_buffer = required_amount * 1.02  # 2% buffer for fees
        
        if balance < required_with_buffer:
            print(f"❌ Insufficient balance: ${balance:.2f} < ${required_with_buffer:.2f} needed")
            return False
        
        return True

    # ═══════════════════════════════════════════════════════════════════════════════
    # POSITION TRACKING METHODS (LIVE MODE)
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_open_positions(self) -> Optional[List[Dict]]:
        """
        Get all open positions for the user.
        
        This retrieves all tokens/shares currently held in the account,
        including unredeemed winning positions.
        
        Returns:
            List of position dicts with token_id, size, market info, etc.
            Returns None on error, empty list if no positions.
            
        Example:
            >>> positions = client.get_open_positions()
            >>> for pos in positions:
            ...     print(f"Token: {pos['token_id']}, Shares: {pos['size']}")
        """
        if config.TEST_MODE:
            return []
        
        if not self._auth.is_ready(AuthLevel.L1):
            print("❌ Cannot fetch positions: Authentication not configured")
            return None
        
        try:
            url = f"{self.clob_url}/positions"
            result = self._make_request("GET", url, authenticated=True)
            
            if result is None:
                return None
            
            positions = []
            
            # Handle different response formats
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        positions.append(self._parse_position(item))
            elif isinstance(result, dict):
                # Single position or wrapped response
                if "positions" in result:
                    for item in result["positions"]:
                        positions.append(self._parse_position(item))
                else:
                    positions.append(self._parse_position(result))
            
            if config.VERBOSE_LOGGING and positions:
                print(f"📋 Found {len(positions)} open positions")
            
            return positions
            
        except Exception as e:
            print(f"❌ Error fetching positions: {e}")
            return None
    
    def _parse_position(self, data: Dict) -> Dict:
        """
        Parse a position from API response into standardized format.
        
        Args:
            data: Raw position data from API
            
        Returns:
            Standardized position dict
        """
        return {
            "token_id": data.get("token_id") or data.get("tokenId") or data.get("asset_id"),
            "size": float(data.get("size") or data.get("shares") or data.get("balance") or 0),
            "avg_price": float(data.get("avg_price") or data.get("avgPrice") or data.get("average_price") or 0),
            "market_id": data.get("market_id") or data.get("marketId") or data.get("condition_id"),
            "side": data.get("side") or data.get("outcome"),
            "unrealized_pnl": float(data.get("unrealized_pnl") or data.get("unrealizedPnl") or 0),
            "raw": data  # Keep raw data for debugging
        }
    
    def get_position_for_token(self, token_id: str) -> Optional[Dict]:
        """
        Get position information for a specific token.
        
        Args:
            token_id: The token ID to look up
            
        Returns:
            Position dict if found, None otherwise
        """
        positions = self.get_open_positions()
        
        if positions is None:
            return None
        
        for pos in positions:
            if pos.get("token_id") == token_id:
                return pos
        
        return None

    # ═══════════════════════════════════════════════════════════════════════════════
    # SHARE REDEMPTION METHODS (CRITICAL FOR LIVE TRADING)
    # ═══════════════════════════════════════════════════════════════════════════════

    def redeem_winning_shares(
        self, 
        token_id: str,
        shares: Optional[float] = None,
        max_retries: int = 3
    ) -> Optional[Dict]:
        """
        Redeem winning shares for USDC after market resolution.
        
        CRITICAL: Polymarket does NOT automatically credit winnings.
        After a market resolves, winning shares must be explicitly
        redeemed to convert them back to USDC.
        
        Args:
            token_id: The token ID of the winning position
            shares: Number of shares to redeem (None = all available)
            max_retries: Number of retry attempts on failure
            
        Returns:
            Dict with redemption info on success:
            {
                "success": True,
                "amount_usdc": float,  # Amount credited
                "shares_redeemed": float,
                "tx_hash": str (if available)
            }
            Returns None on failure.
            
        Example:
            >>> result = client.redeem_winning_shares("abc123", shares=10.5)
            >>> if result and result["success"]:
            ...     print(f"Redeemed ${result['amount_usdc']:.2f}")
        """
        if config.TEST_MODE:
            return {
                "success": True,
                "amount_usdc": shares or 10.0,
                "shares_redeemed": shares or 10.0,
                "simulated": True
            }
        
        if not self._auth.is_ready(AuthLevel.L2):
            print("❌ Cannot redeem: L2 authentication (wallet) required")
            return None
        
        if not token_id:
            print("❌ Cannot redeem: No token ID provided")
            return None
        
        # If shares not specified, get current position
        if shares is None:
            position = self.get_position_for_token(token_id)
            if position:
                shares = position.get("size", 0)
            else:
                # Try to redeem anyway - API might know the balance
                shares = 0  # Will be filled by API
        
        if shares is not None and shares <= 0:
            if config.VERBOSE_LOGGING:
                print("ℹ️ No shares to redeem (already redeemed or zero balance)")
            return {
                "success": True,
                "amount_usdc": 0,
                "shares_redeemed": 0,
                "message": "No shares to redeem"
            }
        
        # Attempt redemption with retries
        for attempt in range(max_retries):
            try:
                result = self._execute_redemption(token_id, shares)
                
                if result and result.get("success"):
                    return result
                
                if attempt < max_retries - 1:
                    print(f"⚠️ Redemption attempt {attempt + 1} failed, retrying...")
                    time.sleep(2)
                    
            except Exception as e:
                print(f"❌ Redemption error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        
        print(f"❌ Redemption failed after {max_retries} attempts")
        return None
    
    def _execute_redemption(self, token_id: str, shares: Optional[float]) -> Optional[Dict]:
        """
        Execute the actual redemption API call.
        
        Polymarket's redemption can work in different ways:
        1. Direct redemption endpoint
        2. Claiming via condition ID
        3. Automatic redemption on market close
        
        This method tries multiple approaches.
        
        Args:
            token_id: Token to redeem
            shares: Number of shares (None = all)
            
        Returns:
            Redemption result dict or None
        """
        result = {
            "success": False,
            "amount_usdc": 0,
            "shares_redeemed": 0,
            "method": None
        }
        
        # Method 1: Try the redeem endpoint
        redemption_result = self._try_redeem_endpoint(token_id, shares)
        if redemption_result:
            return redemption_result
        
        # Method 2: Try the claim endpoint
        claim_result = self._try_claim_endpoint(token_id, shares)
        if claim_result:
            return claim_result
        
        # Method 3: Check if auto-redeemed (balance should reflect it)
        # Some markets auto-redeem on resolution
        auto_result = self._check_auto_redemption(token_id, shares)
        if auto_result:
            return auto_result
        
        return None
    
    def _try_redeem_endpoint(self, token_id: str, shares: Optional[float]) -> Optional[Dict]:
        """
        Try to redeem via the /redeem endpoint.
        """
        try:
            url = f"{self.clob_url}/redeem"
            
            redeem_data = {
                "token_id": token_id,
            }
            
            if shares is not None and shares > 0:
                redeem_data["amount"] = str(shares)
            
            # Sign the redemption request
            try:
                signature = self._auth.sign_order({
                    "token_id": token_id,
                    "side": "REDEEM",
                    "size": str(shares or 0),
                    "price": "1.0",
                    "nonce": int(time.time() * 1000)
                })
                redeem_data["signature"] = signature
            except Exception as e:
                if config.VERBOSE_LOGGING:
                    print(f"⚠️ Could not sign redemption: {e}")
            
            response = self._make_request("POST", url, data=redeem_data, authenticated=True)
            
            if response:
                # Check for success indicators
                if response.get("success") or response.get("redeemed") or "tx" in response:
                    amount = float(response.get("amount") or response.get("redeemed_amount") or shares or 0)
                    return {
                        "success": True,
                        "amount_usdc": amount,
                        "shares_redeemed": shares or amount,
                        "method": "redeem_endpoint",
                        "tx_hash": response.get("tx") or response.get("txHash") or response.get("transaction_hash"),
                        "raw_response": response
                    }
            
            return None
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Redeem endpoint error: {e}")
            return None
    
    def _try_claim_endpoint(self, token_id: str, shares: Optional[float]) -> Optional[Dict]:
        """
        Try to claim/redeem via the /claim endpoint.
        
        Some Polymarket implementations use a claim endpoint instead of redeem.
        """
        try:
            url = f"{self.clob_url}/claim"
            
            claim_data = {
                "token_id": token_id,
            }
            
            if shares is not None and shares > 0:
                claim_data["amount"] = str(shares)
            
            response = self._make_request("POST", url, data=claim_data, authenticated=True)
            
            if response:
                if response.get("success") or response.get("claimed"):
                    amount = float(response.get("amount") or response.get("claimed_amount") or shares or 0)
                    return {
                        "success": True,
                        "amount_usdc": amount,
                        "shares_redeemed": shares or amount,
                        "method": "claim_endpoint",
                        "raw_response": response
                    }
            
            return None
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Claim endpoint error: {e}")
            return None
    
    def _check_auto_redemption(self, token_id: str, expected_shares: Optional[float]) -> Optional[Dict]:
        """
        Check if shares were auto-redeemed by comparing balances.
        
        Some Polymarket markets auto-redeem winning positions.
        We can detect this by checking if the position is gone
        but our USDC balance increased.
        """
        try:
            # Check current position
            position = self.get_position_for_token(token_id)
            
            if position and position.get("size", 0) > 0:
                # Still have shares - not auto-redeemed
                return None
            
            # Position is gone or empty - might be auto-redeemed
            # We can't verify the USDC credit easily, so assume success
            # if the position is gone
            if position is None or position.get("size", 0) == 0:
                if config.VERBOSE_LOGGING:
                    print("ℹ️ Position appears to be redeemed (no longer held)")
                
                return {
                    "success": True,
                    "amount_usdc": expected_shares or 0,
                    "shares_redeemed": expected_shares or 0,
                    "method": "auto_redemption",
                    "message": "Position no longer held - likely auto-redeemed"
                }
            
            return None
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Auto-redemption check error: {e}")
            return None
    
    def redeem_all_winning_positions(self) -> Dict[str, Any]:
        """
        Attempt to redeem all winning positions in the account.
        
        This is useful for cleanup after multiple trades or
        if any redemptions were missed.
        
        Returns:
            Dict with summary:
            {
                "total_redeemed": float,
                "positions_processed": int,
                "positions_redeemed": int,
                "failed": List[str]  # token IDs that failed
            }
        """
        if config.TEST_MODE:
            return {
                "total_redeemed": 0,
                "positions_processed": 0,
                "positions_redeemed": 0,
                "failed": [],
                "simulated": True
            }
        
        print("🔍 Checking for unredeemed winning positions...")
        
        positions = self.get_open_positions()
        
        if not positions:
            print("ℹ️ No open positions found")
            return {
                "total_redeemed": 0,
                "positions_processed": 0,
                "positions_redeemed": 0,
                "failed": []
            }
        
        total_redeemed = 0
        positions_redeemed = 0
        failed = []
        
        for pos in positions:
            token_id = pos.get("token_id")
            shares = pos.get("size", 0)
            
            if not token_id or shares <= 0:
                continue
            
            print(f"   Attempting to redeem {shares:.4f} shares of {token_id[:16]}...")
            
            result = self.redeem_winning_shares(token_id, shares)
            
            if result and result.get("success"):
                amount = result.get("amount_usdc", 0)
                total_redeemed += amount
                positions_redeemed += 1
                print(f"   ✅ Redeemed ${amount:.2f}")
            else:
                failed.append(token_id)
                print(f"   ❌ Failed to redeem")
        
        summary = {
            "total_redeemed": total_redeemed,
            "positions_processed": len(positions),
            "positions_redeemed": positions_redeemed,
            "failed": failed
        }
        
        print(f"\n📊 Redemption Summary:")
        print(f"   Positions processed: {summary['positions_processed']}")
        print(f"   Successfully redeemed: {summary['positions_redeemed']}")
        print(f"   Total USDC: ${summary['total_redeemed']:.2f}")
        
        if failed:
            print(f"   ⚠️ Failed redemptions: {len(failed)}")
        
        return summary

    # ═══════════════════════════════════════════════════════════════════════════════
    # MARKET RESOLUTION METHODS (LIVE MODE)
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_market_resolution(
        self, 
        market_id: str,
        condition_id: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get the resolution status and outcome of a market.
        
        This queries both the Gamma API and CLOB API to determine
        if a market has resolved and what the winning outcome was.
        
        Args:
            market_id: The market ID or slug
            condition_id: Optional condition ID for direct lookup
            
        Returns:
            Dict with resolution info:
            {
                "resolved": bool,
                "winning_outcome": str or None,  # "up", "down", "yes", "no"
                "winning_token_id": str or None,
                "resolution_time": datetime or None,
                "payout_per_share": float  # Usually 1.0 for winners
            }
            Returns None on error.
            
        Example:
            >>> result = client.get_market_resolution("btc-updown-15m-1234567890")
            >>> if result and result["resolved"]:
            ...     print(f"Winner: {result['winning_outcome']}")
        """
        if config.TEST_MODE:
            if config.VERBOSE_LOGGING:
                print("ℹ️ get_market_resolution called in TEST_MODE - returning None")
            return None
        
        # Try multiple approaches to get resolution
        result = None
        
        # Approach 1: Query Gamma API for market details
        result = self._get_resolution_from_gamma(market_id, condition_id)
        if result and result.get("resolved"):
            return result
        
        # Approach 2: Query CLOB API for market status
        if condition_id:
            result = self._get_resolution_from_clob(condition_id)
            if result and result.get("resolved"):
                return result
        
        # Market not resolved yet or error
        return result or {"resolved": False}
    
    def _get_resolution_from_gamma(
        self, 
        market_id: str,
        condition_id: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get market resolution from the Gamma API.
        
        The Gamma API provides market metadata including resolution status.
        """
        try:
            # Try to fetch market by ID or condition ID
            lookup_id = condition_id or market_id
            url = f"{self.gamma_url}/markets/{lookup_id}"
            
            response = self._make_request("GET", url)
            
            if response is None:
                # Try with different endpoint
                url = f"{self.gamma_url}/markets"
                params = {"id": market_id}
                response = self._make_request("GET", url, params=params)
                
                if isinstance(response, list) and len(response) > 0:
                    response = response[0]
            
            if response is None:
                return None
            
            return self._parse_gamma_resolution(response)
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Error fetching resolution from Gamma: {e}")
            return None
    
    def _parse_gamma_resolution(self, market_data: Dict) -> Dict:
        """
        Parse market resolution data from Gamma API response.
        
        Args:
            market_data: Raw market data from Gamma API
            
        Returns:
            Standardized resolution dict
        """
        result = {
            "resolved": False,
            "winning_outcome": None,
            "winning_token_id": None,
            "resolution_time": None,
            "payout_per_share": 0.0,
            "raw_data": market_data,
        }
        
        try:
            # Check if market is closed/resolved
            is_closed = market_data.get("closed", False)
            is_resolved = market_data.get("resolved", False)
            resolution_source = market_data.get("resolutionSource")
            
            # Different ways Polymarket might indicate resolution
            if not (is_closed or is_resolved):
                # Check for end time past
                end_date = market_data.get("endDate") or market_data.get("end_date_iso")
                if end_date:
                    try:
                        if "T" in str(end_date):
                            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                        else:
                            end_dt = datetime.fromtimestamp(int(end_date) / 1000, tz=timezone.utc)
                        
                        if end_dt < datetime.now(timezone.utc):
                            # Market should be resolved, but API might not reflect it yet
                            result["market_ended"] = True
                    except (ValueError, TypeError):
                        pass
                
                return result
            
            result["resolved"] = True
            
            # Parse resolution time
            res_time = market_data.get("resolutionTime") or market_data.get("resolution_time")
            if res_time:
                try:
                    if isinstance(res_time, str) and "T" in res_time:
                        result["resolution_time"] = datetime.fromisoformat(res_time.replace("Z", "+00:00"))
                    elif isinstance(res_time, (int, float)):
                        result["resolution_time"] = datetime.fromtimestamp(res_time / 1000, tz=timezone.utc)
                except (ValueError, TypeError):
                    pass
            
            # Determine winning outcome
            # Polymarket uses outcomePrices where winner = 1.0
            outcome_prices = market_data.get("outcomePrices", [])
            outcomes = market_data.get("outcomes", [])
            
            if isinstance(outcome_prices, str):
                import json
                outcome_prices = json.loads(outcome_prices)
            if isinstance(outcomes, str):
                import json
                outcomes = json.loads(outcomes)
            
            # Find the winning outcome (price = 1.0 or close to it)
            for i, price in enumerate(outcome_prices):
                try:
                    price_float = float(price)
                    if price_float >= 0.99:  # Winner
                        if i < len(outcomes):
                            result["winning_outcome"] = outcomes[i].lower()
                            result["payout_per_share"] = 1.0
                            
                            # Get winning token ID
                            token_ids = market_data.get("clobTokenIds", [])
                            if isinstance(token_ids, str):
                                token_ids = json.loads(token_ids)
                            if i < len(token_ids):
                                result["winning_token_id"] = token_ids[i]
                        break
                except (ValueError, TypeError):
                    continue
            
            # Alternative: Check winner field directly
            if not result["winning_outcome"]:
                winner = market_data.get("winner") or market_data.get("winningOutcome")
                if winner:
                    result["winning_outcome"] = str(winner).lower()
                    result["payout_per_share"] = 1.0
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Error parsing resolution: {e}")
        
        return result
    
    def _get_resolution_from_clob(self, condition_id: str) -> Optional[Dict]:
        """
        Get market resolution from the CLOB API.
        
        The CLOB API might have different resolution data available.
        """
        try:
            url = f"{self.clob_url}/markets/{condition_id}"
            response = self._make_request("GET", url)
            
            if response is None:
                return None
            
            result = {
                "resolved": False,
                "winning_outcome": None,
                "winning_token_id": None,
                "resolution_time": None,
                "payout_per_share": 0.0,
            }
            
            # Check various resolution indicators
            if response.get("closed") or response.get("resolved"):
                result["resolved"] = True
                
                # Try to get winner
                winner = response.get("winner") or response.get("winningOutcome")
                if winner:
                    result["winning_outcome"] = str(winner).lower()
                    result["payout_per_share"] = 1.0
            
            return result
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Error fetching resolution from CLOB: {e}")
            return None
    
    def get_market_by_id(self, market_id: str) -> Optional[Dict]:
        """
        Fetch market information by ID.
        
        This is useful for checking market status, resolution, and other details.
        
        Args:
            market_id: The market ID or slug
            
        Returns:
            Dict with market info or None on error
        """
        try:
            # Try Gamma API first
            url = f"{self.gamma_url}/markets"
            params = {"slug": market_id} if "btc-updown" in market_id else {"id": market_id}
            
            response = self._make_request("GET", url, params=params)
            
            if response and isinstance(response, list) and len(response) > 0:
                market_data = response[0]
                
                # Extract relevant resolution info
                resolved = market_data.get("resolved", False)
                outcome = None
                
                if resolved:
                    # Try to determine winning outcome
                    outcomes = market_data.get("outcomes", [])
                    outcome_prices = market_data.get("outcomePrices", [])
                    
                    if isinstance(outcomes, str):
                        outcomes = json.loads(outcomes)
                    if isinstance(outcome_prices, str):
                        outcome_prices = json.loads(outcome_prices)
                    
                    # The winning outcome typically has price = 1.0
                    for i, price in enumerate(outcome_prices):
                        try:
                            if float(price) >= 0.99:
                                outcome = outcomes[i] if i < len(outcomes) else None
                                break
                        except (ValueError, TypeError):
                            continue
                
                return {
                    "market_id": market_data.get("id", market_id),
                    "question": market_data.get("question", ""),
                    "resolved": resolved,
                    "outcome": outcome,
                    "active": market_data.get("active", False),
                    "end_date": market_data.get("endDate"),
                    "resolution_source": market_data.get("resolutionSource", ""),
                }
            
            return None
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Error fetching market by ID: {e}")
            return None
    
    def check_trade_resolution(
        self, 
        market_id: str,
        traded_side: str,
        condition_id: Optional[str] = None,
        max_wait_seconds: int = 120
    ) -> str:
        """
        Check if a trade won or lost based on market resolution.
        
        This is a convenience method that combines market resolution
        lookup with trade outcome determination.
        
        Args:
            market_id: The market ID
            traded_side: The side we traded ("up", "down", "yes", "no")
            condition_id: Optional condition ID
            max_wait_seconds: Maximum time to wait for resolution
            
        Returns:
            "WIN", "LOSS", or "PENDING" if not yet resolved
        """
        if config.TEST_MODE:
            return "PENDING"
        
        traded_side_normalized = self._normalize_side(traded_side)
        
        # Poll for resolution with timeout
        start_time = time.time()
        poll_interval = 10  # Check every 10 seconds
        
        while (time.time() - start_time) < max_wait_seconds:
            resolution = self.get_market_resolution(market_id, condition_id)
            
            if resolution is None:
                print("⚠️ Error fetching resolution, retrying...")
                time.sleep(poll_interval)
                continue
            
            if resolution.get("resolved"):
                winning_side = resolution.get("winning_outcome", "").lower()
                
                if not winning_side:
                    print("⚠️ Market resolved but winner unknown")
                    return "PENDING"
                
                # Compare our side to the winner
                if traded_side_normalized == winning_side:
                    if config.VERBOSE_LOGGING:
                        print(f"🎉 Trade resolved: {traded_side.upper()} = {winning_side.upper()} → WIN")
                    return "WIN"
                else:
                    if config.VERBOSE_LOGGING:
                        print(f"😞 Trade resolved: {traded_side.upper()} ≠ {winning_side.upper()} → LOSS")
                    return "LOSS"
            
            # Check if market should have ended
            if resolution.get("market_ended"):
                elapsed = time.time() - start_time
                if config.VERBOSE_LOGGING:
                    print(f"⏳ Market ended, waiting for resolution... ({elapsed:.0f}s)")
            
            time.sleep(poll_interval)
        
        # Timeout reached
        print(f"⚠️ Resolution timeout after {max_wait_seconds}s")
        return "PENDING"
    
    def wait_for_market_resolution(
        self,
        market: 'Market',
        traded_side: str,
        timeout_buffer_seconds: int = 300
    ) -> str:
        """
        Wait for a market to resolve and return the outcome.
        
        This calculates the expected resolution time based on the market's
        end time and waits until resolution is available.
        
        Args:
            market: The Market object
            traded_side: The side we traded
            timeout_buffer_seconds: Extra time to wait after market ends
            
        Returns:
            "WIN", "LOSS", or "PENDING"
        """
        if config.TEST_MODE:
            return "PENDING"
        
        now = datetime.now(timezone.utc)
        
        # Calculate how long until market ends
        if hasattr(market, 'end_time') and market.end_time:
            time_until_end = (market.end_time - now).total_seconds()
            
            if time_until_end > 0:
                wait_time = min(time_until_end + 30, 900)  # Cap at 15 min + 30s
                if config.VERBOSE_LOGGING:
                    print(f"⏳ Waiting {wait_time:.0f}s for market to end...")
                time.sleep(wait_time)
        
        # Now check for resolution
        return self.check_trade_resolution(
            market_id=market.market_id,
            traded_side=traded_side,
            condition_id=market.condition_id,
            max_wait_seconds=timeout_buffer_seconds
        )


# Singleton client instance
_client: Optional[PolymarketClient] = None


def get_client() -> PolymarketClient:
    """Get or create the Polymarket client singleton."""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client
