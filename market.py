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
                # Reduced timeout from 5s to 10s for some slower endpoints
                timeout = 10
                method_upper = method.upper()
                if method_upper == "GET":
                    response = requests.get(url, params=params, headers=headers, timeout=timeout)
                elif method_upper == "POST":
                    response = requests.post(url, json=data, headers=headers, timeout=timeout)
                elif method_upper == "DELETE":
                    response = requests.delete(url, headers=headers, timeout=timeout)
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
                # Return special dict for 404 errors to allow caller to handle them
                if response.status_code == 404:
                    print(f"⚠️ HTTP error 404: {e}")
                    return {"_error": "not_found", "_status_code": 404}
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
                # Don't create fake placeholder tokens - they won't work for trading
                print(f"⚠️ Could not fetch real token IDs for market: {slug}")
                if not config.TEST_MODE:
                    print("   LIVE trading requires real token IDs from Polymarket API")
                tokens = {}  # Empty tokens will be validated later
            
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
        
        result = self._make_request("GET", url, params=params)
        
        if config.VERBOSE_LOGGING and result:
            bids = result.get("bids", [])
            asks = result.get("asks", [])
            print(f"📖 Orderbook response: {len(bids)} bids, {len(asks)} asks")
            
            # Show actual best prices (sorted correctly)
            if asks:
                ask_prices = [float(a["price"]) for a in asks]
                best_ask = min(ask_prices)
                worst_ask = max(ask_prices)
                print(f"   Asks range: {best_ask:.4f} (best) to {worst_ask:.4f} (worst)")
            if bids:
                bid_prices = [float(b["price"]) for b in bids]
                best_bid = max(bid_prices)
                worst_bid = min(bid_prices)
                print(f"   Bids range: {best_bid:.4f} (best) to {worst_bid:.4f} (worst)")
        
        return result
    
    def get_best_prices(self, market: Market, side: str) -> Optional[Dict[str, float]]:
        """
        Get the best available prices for a market side.
        
        Args:
            market: The market to query
            side: "yes" or "no" or "up" or "down"
        
        Returns:
            Dict with 'bid', 'ask', 'mid' prices, or None on error
        """
        token_id = market.tokens.get(side.lower())
        if not token_id:
            print(f"⚠️ No token ID found for side '{side}'. Available: {list(market.tokens.keys())}")
            return None
        
        # Check if token_id looks like a real token (not a placeholder)
        if "-up" in token_id or "-down" in token_id:
            print(f"⚠️ Invalid token ID (placeholder): {token_id}")
            print("   Real token IDs should be numeric strings like '79488316806456...'")
            # Fall back to using market's quoted prices
            return self._get_fallback_prices(market, side)
        
        orderbook = self.fetch_market_orderbook(token_id)
        if not orderbook:
            print(f"⚠️ Could not fetch order book for token: {token_id[:20]}...")
            return self._get_fallback_prices(market, side)
        
        try:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            if config.VERBOSE_LOGGING:
                print(f"📖 Order book for {side}: {len(bids)} bids, {len(asks)} asks")
            
            # If no asks available, can't place a market buy order
            if not asks:
                print(f"⚠️ No asks in order book for {side} - market has no sell-side liquidity")
                return self._get_fallback_prices(market, side)
            
            # ─────────────────────────────────────────────────────────────────
            # IMPORTANT: Order book sorting
            # ─────────────────────────────────────────────────────────────────
            # The CLOB API may return bids/asks in different sort orders.
            # - Best BID = HIGHEST bid price (someone willing to pay the most)
            # - Best ASK = LOWEST ask price (someone willing to sell cheapest)
            # 
            # We need to sort to find the true best prices.
            # ─────────────────────────────────────────────────────────────────
            
            # Parse all prices and sort to find best ones
            bid_prices = [float(b["price"]) for b in bids] if bids else [0.0]
            ask_prices = [float(a["price"]) for a in asks]
            
            best_bid = max(bid_prices) if bid_prices else 0.0  # Highest bid
            best_ask = min(ask_prices)  # Lowest ask
            
            if config.VERBOSE_LOGGING:
                print(f"   Best bid (highest): {best_bid:.4f}")
                print(f"   Best ask (lowest): {best_ask:.4f}")
                print(f"   Spread: {(best_ask - best_bid):.4f}")
            
            # Validate ask price is reasonable
            if best_ask <= 0 or best_ask >= 1.0:
                print(f"⚠️ Invalid ask price: {best_ask}")
                return self._get_fallback_prices(market, side)
            
            # ─────────────────────────────────────────────────────────────────
            # Check for wide spread (illiquid market)
            # ─────────────────────────────────────────────────────────────────
            spread = best_ask - best_bid
            if spread > 0.50:  # Spread > 50% is not a healthy market
                side_lower = side.lower()
                quoted_price = market.yes_price if side_lower in ["up", "yes"] else market.no_price
                print(f"⚠️ Order book spread too wide ({spread:.2f})")
                print(f"   Bid: {best_bid:.4f}, Ask: {best_ask:.4f}")
                print(f"   Quoted market price: {quoted_price:.4f}")
                
                # Check if ask price is way off from quoted price (indicates near resolution)
                price_diff = abs(best_ask - quoted_price)
                if price_diff > 0.30:  # Ask differs from quoted by more than 30%
                    print(f"⚠️ Order book ask ({best_ask:.4f}) differs significantly from quoted price ({quoted_price:.4f})")
                    print("   Market may be near resolution or illiquid - using quoted prices")
                    return self._get_fallback_prices(market, side)
            
            # Calculate mid price - if no bids, use ask as reference
            if best_bid > 0:
                mid = (best_bid + best_ask) / 2
            else:
                mid = best_ask  # Use ask as mid if no bids
            
            return {
                "bid": best_bid,
                "ask": best_ask,
                "mid": mid,
                "is_fallback": False  # Real order book prices
            }
        except (IndexError, KeyError, TypeError) as e:
            print(f"⚠️ Error parsing order book: {e}")
            return self._get_fallback_prices(market, side)
    
    def _get_fallback_prices(self, market: Market, side: str) -> Optional[Dict[str, float]]:
        """
        Get fallback prices from the market's quoted prices when order book is unavailable.
        
        IMPORTANT: These are INDICATIVE prices only - they may not have real liquidity!
        Orders placed at these prices may sit unfilled on the order book.
        
        The caller should check the 'is_fallback' flag and handle accordingly.
        """
        side_lower = side.lower()
        
        # Get the quoted price for this side
        if side_lower in ["up", "yes"]:
            quoted_price = market.yes_price
        elif side_lower in ["down", "no"]:
            quoted_price = market.no_price
        else:
            print(f"⚠️ Unknown side for fallback: {side}")
            return None
        
        if quoted_price <= 0 or quoted_price >= 1.0:
            print(f"⚠️ Invalid quoted price for {side}: {quoted_price}")
            return None
        
        print(f"📊 Using quoted market price as fallback: {quoted_price:.4f}")
        print(f"⚠️ WARNING: Fallback prices may not have real liquidity!")
        
        # Use quoted price as both bid and ask (tight spread assumption)
        # Add small buffer for ask to account for spread
        ask_price = min(quoted_price * 1.005, 0.99)  # 0.5% buffer
        
        return {
            "bid": quoted_price,
            "ask": ask_price,
            "mid": quoted_price,
            "is_fallback": True,  # Flag to indicate these are fallback prices
        }
    
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
        
        # Validate token ID is a real token (not a placeholder)
        if not token_id.isdigit() or len(token_id) < 10:
            print(f"❌ Invalid token ID format: {token_id}")
            print("   Real token IDs should be long numeric strings (e.g., '79488316806456...')")
            print("   This usually means the Polymarket API didn't return real token IDs.")
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
        
        # ─────────────────────────────────────────────────────────────────────
        # REJECT ORDERS WITH FALLBACK PRICES (NO REAL LIQUIDITY)
        # ─────────────────────────────────────────────────────────────────────
        # If we're using fallback prices (from wide-spread order book), the order
        # will likely sit unfilled on the book. Better to skip this market.
        if prices.get("is_fallback"):
            print("❌ Market has no executable liquidity at quoted price")
            print("   Order book spread is too wide - cannot guarantee fill")
            print("   Skipping this market to avoid unfilled orders")
            return None
        
        # Calculate order price with slippage protection
        order_price = self._calculate_order_price(prices, max_slippage_percent)
        if order_price is None:
            print("❌ Could not calculate valid order price")
            return None
        
        # ─────────────────────────────────────────────────────────────────────
        # MAX BUY PRICE CHECK - Reject orders above configured threshold
        # ─────────────────────────────────────────────────────────────────────
        max_buy_price = getattr(config, 'MAX_BUY_PRICE', 0.57)
        if order_price > max_buy_price:
            print(f"❌ Order price ${order_price:.4f} exceeds MAX_BUY_PRICE ${max_buy_price:.2f}")
            print(f"   Skipping trade to avoid buying at high prices")
            print(f"   Adjust MAX_BUY_PRICE in config.py or .env if you want to allow higher prices")
            return None
        
        # Calculate number of shares to buy
        # shares = amount_usd / price (since each share pays $1 on win)
        shares = amount_usd / order_price
        
        # Round shares to reasonable precision (Polymarket uses 2 decimals typically)
        shares = round(shares, 2)
        
        # ─────────────────────────────────────────────────────────────────────
        # POLYMARKET MINIMUM ORDER SIZE: 5 SHARES
        # ─────────────────────────────────────────────────────────────────────
        MIN_SHARES = 5.0
        if shares < MIN_SHARES:
            # Calculate the minimum USD needed to meet the 5 share minimum
            min_usd_needed = MIN_SHARES * order_price
            print(f"⚠️ Order size ({shares:.2f} shares) below minimum ({MIN_SHARES} shares)")
            print(f"   Need at least ${min_usd_needed:.2f} at price {order_price:.4f}")
            
            # Check if we can afford the minimum (within reason - up to 3x intended or $5, whichever is higher)
            max_allowed = max(amount_usd * 3, 5.0)  # Allow up to 3x or $5 minimum
            if min_usd_needed <= max_allowed:
                # Increase to minimum if affordable
                shares = MIN_SHARES
                amount_usd = min_usd_needed
                print(f"   📈 Increasing order to minimum: {shares:.2f} shares (${amount_usd:.2f})")
            else:
                print(f"❌ Cannot meet minimum order size - need ${min_usd_needed:.2f} (max allowed: ${max_allowed:.2f})")
                return None
        
        if shares <= 0:
            print(f"❌ Invalid share calculation: {shares}")
            return None
        
        # ─────────────────────────────────────────────────────────────────────
        # USE OFFICIAL py-clob-client FOR ORDER CREATION AND SUBMISSION
        # ─────────────────────────────────────────────────────────────────────
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
            from py_clob_client.constants import POLYGON
            
            # Initialize the official CLOB client
            creds = ApiCreds(
                api_key=config.POLYMARKET_API_KEY,
                api_secret=config.POLYMARKET_API_SECRET,
                api_passphrase=config.POLYMARKET_PASSPHRASE,
            )
            
            clob_client = ClobClient(
                host=self.clob_url,
                key=config.WALLET_PRIVATE_KEY,
                chain_id=POLYGON,
                creds=creds,
            )
            
            # Log order details before submission
            if config.VERBOSE_LOGGING:
                print(f"📤 Submitting order via py-clob-client:")
                print(f"   Token: {token_id[:16]}...")
                print(f"   Side: BUY {side.upper()}")
                print(f"   Amount: ${amount_usd:.2f}")
                print(f"   Price: {order_price:.4f}")
                print(f"   Shares: {shares:.2f}")
            
            # Create the order using the official client
            order_args = OrderArgs(
                price=round(order_price, 2),  # Price must be rounded to tick size
                size=shares,
                side="BUY",  # We're always buying the outcome we want
                token_id=token_id,
            )
            
            # Create and sign the order
            signed_order = clob_client.create_order(order_args)
            
            # Post the order to the CLOB with retry logic for network timeouts
            result = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    result = clob_client.post_order(signed_order, orderType=OrderType.GTC)
                    break  # Success, exit retry loop
                except Exception as retry_error:
                    error_str = str(retry_error).lower()
                    is_timeout = "timeout" in error_str or "readtimeout" in error_str or "request exception" in error_str
                    
                    if is_timeout and attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # 2s, 4s exponential backoff
                        print(f"⚠️ Order submission timeout (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        raise  # Re-raise if not a timeout or last attempt
            
            if config.VERBOSE_LOGGING:
                print(f"📥 Order response: {result}")
            
            # Parse the response
            if result and isinstance(result, dict):
                if result.get("success") or result.get("orderID") or result.get("order_id"):
                    order_id = result.get("orderID") or result.get("order_id") or result.get("id")
                    print(f"✅ Order placed successfully!")
                    print(f"   Order ID: {order_id}")
                    self.mark_as_traded(market)
                    return {
                        "success": True,
                        "order_id": order_id,
                        "status": result.get("status", "SUBMITTED"),
                        "amount_usd": amount_usd,
                        "price": order_price,
                        "shares": shares,
                        "raw_response": result,
                    }
                else:
                    error_msg = result.get("error") or result.get("message") or str(result)
                    print(f"❌ Order placement failed: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg,
                        "raw_response": result,
                    }
            else:
                print(f"❌ Unexpected response format: {result}")
                return None
                
        except ImportError as e:
            print(f"❌ py-clob-client not installed: {e}")
            print("   Install with: pip install py-clob-client")
            return None
        except Exception as e:
            print(f"❌ Order submission error: {e}")
            if config.VERBOSE_LOGGING:
                import traceback
                traceback.print_exc()
            return None
    
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
        Cancel an open order using the CLOB API.
        
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
            # Use _make_request with authenticated=True (it uses L2 headers correctly)
            result = self._make_request("DELETE", url, authenticated=True)
            
            if result and (result.get("success") or result.get("status") == "CANCELLED"):
                print(f"✅ Order {order_id} cancelled")
                return True
            
            # If result is None but we're here, it might have failed
            # or already been cancelled/filled. Check status.
            status_data = self.get_order_status(order_id)
            if status_data:
                status = self._parse_order_status(status_data)
                if status in ["CANCELLED", "FILLED", "MATCHED"]:
                    return True
            
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
        poll_interval: float = 2.0,
        token_id: Optional[str] = None
    ) -> Dict:
        """
        Wait for an order to be filled, with timeout.
        
        Polls the order status until it's filled, cancelled, or timeout.
        Falls back to checking positions if order status endpoint returns 404.
        
        Args:
            order_id: The order ID to monitor
            max_wait_seconds: Maximum time to wait for fill
            poll_interval: Time between status checks
            token_id: Optional token ID to check positions as fallback
            
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
        consecutive_404s = 0
        max_consecutive_404s = 5  # After 5 consecutive 404s, try alternate methods
        
        while (time.time() - start_time) < max_wait_seconds:
            try:
                status_data = self.get_order_status(order_id)
                
                # Handle 404 errors specifically
                if status_data is not None and status_data.get("_error") == "not_found":
                    consecutive_404s += 1
                    if consecutive_404s >= max_consecutive_404s:
                        print(f"⚠️ Order status endpoint returning 404 consistently")
                        # NOTE: Polymarket order status API often returns 404 for orders that
                        # actually filled. This is a known issue. We MUST check positions
                        # with retries and delays to account for data API propagation time.
                        if token_id:
                            print(f"   Checking positions for token {token_id[:16]}...")
                            print(f"   (Note: Data API may have a 5-15 second propagation delay)")
                            # Use multiple retries with delays - positions often take time to appear
                            filled = self._check_position_for_fill(token_id, retries=5, delay_seconds=3.0)
                            if filled:
                                print(f"✅ Found position - order appears to have filled!")
                                return {
                                    "success": True,
                                    "status": "FILLED_VIA_POSITION",
                                    "filled_price": filled.get("avg_price", 0.0),
                                    "filled_shares": filled.get("size", 0.0),
                                    "order_id": order_id,
                                    "error": None
                                }
                        # If no position found after extensive retries, check user's trade history
                        # as another fallback
                        print(f"⚠️ No position found via data API - checking trade history...")
                        if token_id:
                            trade_found = self._check_trades_for_fill(token_id)
                            if trade_found:
                                print(f"✅ Found trade in history - order appears to have filled!")
                                return {
                                    "success": True,
                                    "status": "FILLED_VIA_TRADES",
                                    "filled_price": trade_found.get("price", 0.0),
                                    "filled_shares": trade_found.get("size", 0.0),
                                    "order_id": order_id,
                                    "error": None
                                }
                        # If still no position found, the order likely wasn't matched
                        print(f"⚠️ No position or trade found - order may not have been matched")
                        return {
                            "success": False,
                            "status": "NOT_FOUND",
                            "filled_price": 0.0,
                            "filled_shares": 0.0,
                            "order_id": order_id,
                            "error": "Order not found - likely not matched (illiquid market)"
                        }
                    time.sleep(poll_interval)
                    continue
                
                # Reset 404 counter if we get a valid response
                consecutive_404s = 0
                
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
        if final_status and not final_status.get("_error"):
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
        
        # Final fallback: check positions with extended retries
        if token_id:
            print(f"   Final check: looking for position with extended wait...")
            filled = self._check_position_for_fill(token_id, retries=3, delay_seconds=3.0)
            if filled:
                print(f"✅ Found position in final check - order filled!")
                return {
                    "success": True,
                    "status": "FILLED_VIA_POSITION",
                    "filled_price": filled.get("avg_price", 0.0),
                    "filled_shares": filled.get("size", 0.0),
                    "order_id": order_id,
                    "error": None
                }
            
            # Also try trade history as last resort
            trade_found = self._check_trades_for_fill(token_id)
            if trade_found:
                print(f"✅ Found trade in history in final check - order filled!")
                return {
                    "success": True,
                    "status": "FILLED_VIA_TRADES",
                    "filled_price": trade_found.get("price", 0.0),
                    "filled_shares": trade_found.get("size", 0.0),
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
    
    def _check_position_for_fill(self, token_id: str, retries: int = 3, delay_seconds: float = 2.0) -> Optional[Dict]:
        """
        Check if we have a position for the given token, indicating a filled order.
        
        This is a fallback method when the order status endpoint returns 404.
        If we have shares of the token, the order must have filled.
        
        NOTE: The data API can have a delay before showing new positions.
        We retry with increasing delays to account for this propagation delay.
        
        Args:
            token_id: The token ID to look for in positions
            retries: Number of times to retry if position not found (default 3)
            delay_seconds: Base delay between retries (increases each retry)
            
        Returns:
            Position dict if found, None otherwise
        """
        for attempt in range(retries):
            try:
                # Wait before checking (longer delay on subsequent attempts)
                if attempt > 0:
                    wait_time = delay_seconds * (attempt + 1)
                    if config.VERBOSE_LOGGING:
                        print(f"   Waiting {wait_time:.1f}s for position data to propagate (attempt {attempt + 1}/{retries})...")
                    time.sleep(wait_time)
                
                positions = self.get_open_positions()
                if not positions:
                    continue
                
                for pos in positions:
                    # Check various possible field names for token ID
                    pos_token = (
                        pos.get("token_id") or 
                        pos.get("tokenId") or 
                        pos.get("asset") or
                        ""
                    )
                    
                    # Debug log to help diagnose token ID mismatches
                    if config.VERBOSE_LOGGING and attempt == retries - 1:
                        # On last attempt, show what tokens we found
                        print(f"   Position token: {pos_token[:20] if pos_token else 'None'}... size: {pos.get('size', 0)}")
                    
                    if pos_token == token_id:
                        size = float(pos.get("size") or pos.get("shares") or 0)
                        if size > 0:
                            if config.VERBOSE_LOGGING:
                                print(f"   ✓ Found matching position with {size} shares")
                            return pos
                
            except Exception as e:
                if config.VERBOSE_LOGGING:
                    print(f"⚠️ Error checking position (attempt {attempt + 1}): {e}")
                continue
        
        return None
    
    def _check_trades_for_fill(self, token_id: str) -> Optional[Dict]:
        """
        Check user's recent trades as a fallback to verify if an order was filled.
        
        This is a secondary fallback when both order status API returns 404
        and the positions data API doesn't show the position yet.
        
        Args:
            token_id: The token ID to look for in recent trades
            
        Returns:
            Trade dict if found, None otherwise
        """
        try:
            # Use the data-api trades endpoint
            wallet_address = config.WALLET_ADDRESS
            if not wallet_address:
                return None
            
            data_api_url = "https://data-api.polymarket.com"
            url = f"{data_api_url}/trades"
            params = {
                "user": wallet_address.lower(),
                "limit": 20,  # Check last 20 trades
            }
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            trades = response.json()
            
            if not isinstance(trades, list):
                trades = trades.get("trades", []) if isinstance(trades, dict) else []
            
            # Look for a recent trade with our token
            for trade in trades:
                trade_token = (
                    trade.get("asset") or 
                    trade.get("token_id") or 
                    trade.get("tokenId") or
                    ""
                )
                if trade_token == token_id:
                    # Found a matching trade!
                    return {
                        "token_id": trade_token,
                        "size": float(trade.get("size") or trade.get("amount") or 0),
                        "price": float(trade.get("price") or 0),
                        "timestamp": trade.get("timestamp") or trade.get("createdAt"),
                    }
            
            return None
            
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"⚠️ Error checking trades: {e}")
            return None
    
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
        
        # Get all positions and filter for this market
        positions = self.get_open_positions()
        
        if not positions:
            return None
        
        # Look for position matching this market's tokens
        for pos in positions:
            token_id = pos.get("token_id")
            if token_id and hasattr(market, 'tokens') and market.tokens:
                if token_id in market.tokens.values():
                    return pos
            # Also check by condition_id/market_id
            if pos.get("market_id") == market.condition_id:
                return pos
        
        return None

    def get_user_trades(self, limit: int = 50, market: Optional[str] = None) -> List[Dict]:
        """
        Get user's trade history from the CLOB API.
        
        Args:
            limit: Maximum number of trades to return
            market: Optional condition_id to filter by market
            
        Returns:
            List of trade dicts
        """
        if config.TEST_MODE:
            return []
        
        if not self._auth.is_ready(AuthLevel.L2):
            print("❌ Cannot fetch trades: L2 authentication required")
            return []
        
        try:
            url = f"{self.clob_url}/data/trades"
            
            # Build headers for authenticated request
            headers = self._auth.get_l2_headers("GET", "/data/trades")
            
            params = {}
            if market:
                params["market"] = market
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            trades = []
            
            # Handle paginated response
            if isinstance(result, dict):
                trades = result.get("data", [])
            elif isinstance(result, list):
                trades = result
            
            # Limit results
            return trades[:limit] if len(trades) > limit else trades
            
        except Exception as e:
            print(f"⚠️ Error fetching user trades: {e}")
            return []

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
        
        NOTE: Uses the Polymarket data-api for positions (not CLOB API).
        The data-api provides comprehensive position data including
        P&L, redeemable status, and market metadata.
        
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
            # Use Polymarket data-api for positions - this is the correct endpoint
            # The CLOB API does NOT have a /positions endpoint
            wallet_address = config.WALLET_ADDRESS
            if not wallet_address:
                print("❌ WALLET_ADDRESS not configured")
                return None
            
            # Data API endpoint for user positions
            data_api_url = "https://data-api.polymarket.com"
            url = f"{data_api_url}/positions"
            params = {"user": wallet_address.lower()}
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            positions = []
            
            # Handle the data-api response format
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        parsed = self._parse_data_api_position(item)
                        # Only include positions with actual shares
                        if parsed.get("size", 0) > 0:
                            positions.append(parsed)
            elif isinstance(result, dict):
                if "positions" in result:
                    for item in result["positions"]:
                        parsed = self._parse_data_api_position(item)
                        if parsed.get("size", 0) > 0:
                            positions.append(parsed)
            
            if config.VERBOSE_LOGGING:
                if positions:
                    print(f"📋 Found {len(positions)} open positions")
                    # Count winning vs losing positions based on current_price
                    winning = [p for p in positions if p.get("current_price", 0) >= 0.90]
                    losing = [p for p in positions if p.get("current_price", 0) < 0.10]
                    pending = [p for p in positions if 0.10 <= p.get("current_price", 0) < 0.90]
                    if winning:
                        print(f"   💰 {len(winning)} WINNING positions to redeem!")
                    if losing:
                        print(f"   ❌ {len(losing)} LOSING positions (no value)")
                    if pending:
                        print(f"   ⏳ {len(pending)} positions still pending")
                else:
                    print("ℹ️ No open positions found")
            
            return positions
            
        except requests.exceptions.HTTPError as e:
            # Try alternate method if data-api fails
            print(f"⚠️ Data API positions endpoint error: {e}")
            return self._get_positions_from_trades()
        except Exception as e:
            print(f"❌ Error fetching positions: {e}")
            return self._get_positions_from_trades()
    
    def _parse_data_api_position(self, data: Dict) -> Dict:
        """
        Parse a position from the data-api response format.
        
        The data-api provides rich position data including P&L and redeemable status.
        
        Args:
            data: Raw position data from data-api
            
        Returns:
            Standardized position dict
        """
        return {
            "token_id": data.get("asset"),
            "size": float(data.get("size") or 0),
            "avg_price": float(data.get("avgPrice") or 0),
            "market_id": data.get("conditionId"),
            "condition_id": data.get("conditionId"),  # Also store as condition_id for redemption
            "side": data.get("outcome"),
            "title": data.get("title"),
            "slug": data.get("slug"),
            "current_price": float(data.get("curPrice") or 0),
            "current_value": float(data.get("currentValue") or 0),
            "initial_value": float(data.get("initialValue") or 0),
            "cash_pnl": float(data.get("cashPnl") or 0),
            "percent_pnl": float(data.get("percentPnl") or 0),
            "redeemable": data.get("redeemable", False),
            "end_date": data.get("endDate"),
            "raw": data  # Keep raw data for debugging
        }
    
    def _get_positions_from_trades(self) -> List[Dict]:
        """
        Fallback method to get positions by checking recent trades.
        
        If the Gamma API positions endpoint doesn't work, we can
        derive positions from trade history + balance checks.
        
        Returns:
            List of position dicts
        """
        try:
            # Get recent trades from CLOB API
            trades = self.get_user_trades(limit=50)
            
            if not trades:
                return []
            
            # Group by token_id and calculate net position
            positions_map = {}
            
            for trade in trades:
                token_id = trade.get("asset_id") or trade.get("token_id")
                if not token_id:
                    continue
                
                side = trade.get("side", "").upper()
                size = float(trade.get("size") or trade.get("amount") or 0)
                price = float(trade.get("price") or 0)
                
                if token_id not in positions_map:
                    positions_map[token_id] = {
                        "token_id": token_id,
                        "size": 0,
                        "avg_price": 0,
                        "total_cost": 0,
                        "market_id": trade.get("market") or trade.get("condition_id"),
                    }
                
                # Adjust position based on trade side
                if side == "BUY":
                    positions_map[token_id]["size"] += size
                    positions_map[token_id]["total_cost"] += size * price
                elif side == "SELL":
                    positions_map[token_id]["size"] -= size
            
            # Calculate average prices and filter out zero positions
            positions = []
            for token_id, pos in positions_map.items():
                if pos["size"] > 0.001:  # Small threshold to avoid dust
                    if pos["size"] > 0:
                        pos["avg_price"] = pos["total_cost"] / pos["size"]
                    del pos["total_cost"]
                    positions.append(pos)
            
            return positions
            
        except Exception as e:
            print(f"⚠️ Error getting positions from trades: {e}")
            return []
    
    def _parse_position(self, data: Dict) -> Dict:
        """
        Parse a position from API response into standardized format.
        
        Args:
            data: Raw position data from API
            
        Returns:
            Standardized position dict
        """
        return {
            "token_id": data.get("token_id") or data.get("tokenId") or data.get("asset_id") or data.get("asset"),
            "size": float(data.get("size") or data.get("shares") or data.get("balance") or 0),
            "avg_price": float(data.get("avg_price") or data.get("avgPrice") or data.get("average_price") or 0),
            "current_price": float(data.get("current_price") or data.get("curPrice") or 0),
            "market_id": data.get("market_id") or data.get("marketId") or data.get("condition_id") or data.get("conditionId"),
            "condition_id": data.get("condition_id") or data.get("conditionId") or data.get("market_id"),
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
        Redeem winning shares on-chain via the CTF (Conditional Token Framework) contract.
        
        After a market resolves, winning shares can be redeemed for USDC by calling
        the `redeemPositions` function on the CTF contract. This burns the conditional
        tokens and returns the underlying USDC collateral.
        
        Args:
            token_id: The token ID of the winning position
            shares: Number of shares to redeem (ignored - all shares are redeemed)
            max_retries: Number of retry attempts on failure
            
        Returns:
            Dict with redemption info:
            {
                "success": True,
                "amount_usdc": float,
                "shares_redeemed": float,
                "tx_hash": str (if on-chain redemption successful)
            }
            
        Example:
            >>> result = client.redeem_winning_shares("abc123", shares=10.5)
            >>> if result and result["success"]:
            ...     print(f"Redeemed! TX: {result.get('tx_hash')}")
        """
        if config.TEST_MODE:
            return {
                "success": True,
                "amount_usdc": shares or 10.0,
                "shares_redeemed": shares or 10.0,
                "simulated": True
            }
        
        if not token_id:
            print("❌ Cannot redeem: No token ID provided")
            return None
        
        # Get current position status
        position = self.get_position_for_token(token_id)
        
        if position is None or position.get("size", 0) == 0:
            # Position is gone - already redeemed or never existed
            if config.VERBOSE_LOGGING:
                print("ℹ️ Position already redeemed or no longer held")
            return {
                "success": True,
                "amount_usdc": shares or 0,
                "shares_redeemed": shares or 0,
                "method": "already_redeemed",
                "message": "Position no longer held - likely already redeemed"
            }
        
        # Position still exists - check if market is resolved
        current_shares = position.get("size", 0)
        cur_price = position.get("current_price", 0)
        condition_id = position.get("condition_id") or position.get("market_id")
        
        # If current price is 0.0, it's a losing position (no redemption needed)
        if cur_price == 0:
            return {
                "success": True,
                "amount_usdc": 0,
                "shares_redeemed": 0,
                "method": "losing_position",
                "message": "Losing position - no redemption value"
            }
        
        # If current price is 1.0, it's a winning position - attempt on-chain redemption
        if cur_price == 1.0 or cur_price >= 0.99:
            estimated_value = current_shares * 1.0
            print(f"💰 Winning position found: {current_shares:.4f} shares (~${estimated_value:.2f})")
            
            # Try on-chain redemption
            if condition_id:
                for attempt in range(max_retries):
                    try:
                        result = self._execute_onchain_redemption(condition_id, token_id, current_shares)
                        if result and result.get("success"):
                            return result
                        if attempt < max_retries - 1:
                            print(f"⚠️ Redemption attempt {attempt + 1} failed, retrying in 15s...")
                            time.sleep(15)  # Longer delay to avoid rate limits
                    except Exception as e:
                        print(f"❌ Redemption error (attempt {attempt + 1}): {e}")
                        if attempt < max_retries - 1:
                            time.sleep(15)  # Longer delay to avoid rate limits
            
            # If on-chain redemption failed, notify user
            print(f"   ℹ️ Automatic redemption failed. Please redeem manually.")
            print(f"   👉 Visit: https://polymarket.com/portfolio")
            
            return {
                "success": True,  # Not a failure, just needs manual action
                "amount_usdc": estimated_value,
                "shares_redeemed": 0,  # Not actually redeemed yet
                "needs_manual_redemption": True,
                "method": "manual_required",
                "message": f"Please redeem ${estimated_value:.2f} at polymarket.com/portfolio"
            }
        
        # Position exists with non-conclusive price - market may not be resolved yet
        return {
            "success": True,
            "amount_usdc": 0,
            "shares_redeemed": 0,
            "method": "market_not_resolved",
            "message": f"Market may not be resolved yet (price: {cur_price})"
        }
    
    def _execute_onchain_redemption(
        self, 
        condition_id: str, 
        token_id: str,
        shares: float
    ) -> Optional[Dict]:
        """
        Execute on-chain redemption via the CTF contract.
        
        Calls `redeemPositions` on the Conditional Token Framework (CTF) contract
        to burn winning outcome tokens and receive USDC collateral.
        
        Args:
            condition_id: The condition ID of the resolved market
            token_id: The token ID (used for logging)
            shares: Number of shares being redeemed
            
        Returns:
            Dict with redemption result including tx_hash on success
        """
        try:
            from web3 import Web3
            from web3.middleware import ExtraDataToPOAMiddleware
            import os
            
            # Contract addresses (Polygon Mainnet)
            CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
            USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
            
            # CTF redeemPositions ABI
            CTF_ABI = [
                {
                    "inputs": [
                        {"name": "collateralToken", "type": "address"},
                        {"name": "parentCollectionId", "type": "bytes32"},
                        {"name": "conditionId", "type": "bytes32"},
                        {"name": "indexSets", "type": "uint256[]"}
                    ],
                    "name": "redeemPositions",
                    "outputs": [],
                    "stateMutability": "nonpayable",
                    "type": "function"
                }
            ]
            
            # Get wallet credentials
            private_key = config.WALLET_PRIVATE_KEY
            wallet_address = config.WALLET_ADDRESS
            
            if not private_key or not wallet_address:
                print("❌ Cannot redeem: WALLET_PRIVATE_KEY and WALLET_ADDRESS required")
                return None
            
            # Connect to Polygon
            rpc_url = getattr(config, 'POLYGON_RPC_URL', "https://polygon-bor-rpc.publicnode.com")
            web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 60}))
            web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            
            if not web3.is_connected():
                print("❌ Cannot redeem: Failed to connect to Polygon network")
                return None
            
            wallet_address = web3.to_checksum_address(wallet_address)
            
            # Create CTF contract instance
            ctf_contract = web3.eth.contract(
                address=web3.to_checksum_address(CTF_ADDRESS),
                abi=CTF_ABI
            )
            
            # Format condition_id as bytes32
            # If it starts with 0x, use as-is; otherwise, pad it
            if condition_id.startswith("0x"):
                condition_id_bytes = bytes.fromhex(condition_id[2:].zfill(64))
            else:
                condition_id_bytes = bytes.fromhex(condition_id.zfill(64))
            
            # Parent collection ID is null (bytes32 zero) for Polymarket
            parent_collection_id = bytes(32)
            
            # Index sets: [1, 2] represents YES and NO outcomes
            # The contract will only pay out for winning outcomes
            index_sets = [1, 2]
            
            print(f"   🔗 Executing on-chain redemption...")
            print(f"      Condition ID: {condition_id[:16]}...")
            print(f"      Shares: {shares:.4f}")
            
            # Build transaction
            nonce = web3.eth.get_transaction_count(wallet_address)
            gas_price = web3.eth.gas_price
            
            tx = ctf_contract.functions.redeemPositions(
                web3.to_checksum_address(USDC_ADDRESS),
                parent_collection_id,
                condition_id_bytes,
                index_sets
            ).build_transaction({
                'from': wallet_address,
                'nonce': nonce,
                'gas': 200000,  # Estimate, will be adjusted
                'gasPrice': gas_price,
                'chainId': 137  # Polygon Mainnet
            })
            
            # Estimate gas
            try:
                gas_estimate = web3.eth.estimate_gas(tx)
                tx['gas'] = int(gas_estimate * 1.2)  # Add 20% buffer
            except Exception as e:
                print(f"   ⚠️ Gas estimation failed: {e}")
                # Continue with default gas
            
            # Sign and send transaction
            signed_tx = web3.eth.account.sign_transaction(tx, private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()
            
            print(f"   📤 Transaction sent: {tx_hash_hex}")
            print(f"   ⏳ Waiting for confirmation...")
            
            # Wait for transaction receipt
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] == 1:
                print(f"   ✅ Redemption successful!")
                print(f"      TX: https://polygonscan.com/tx/{tx_hash_hex}")
                
                return {
                    "success": True,
                    "amount_usdc": shares,  # Winning shares = USDC
                    "shares_redeemed": shares,
                    "method": "onchain_redemption",
                    "tx_hash": tx_hash_hex,
                    "gas_used": receipt['gasUsed']
                }
            else:
                print(f"   ❌ Transaction failed (reverted)")
                return None
                
        except ImportError:
            print("❌ web3 package not installed. Install with: pip install web3")
            return None
        except Exception as e:
            print(f"❌ On-chain redemption error: {e}")
            return None
    
    def _execute_redemption(self, token_id: str, shares: Optional[float]) -> Optional[Dict]:
        """
        DEPRECATED: Polymarket redemption is on-chain, not via API.
        
        This method is kept for backwards compatibility but now just
        redirects to the position check logic.
        
        Args:
            token_id: Token to check
            shares: Number of shares
            
        Returns:
            Result dict indicating manual redemption is needed
        """
        # Just check if position still exists
        return self._check_auto_redemption(token_id, shares)
    
    def _try_redeem_endpoint(self, token_id: str, shares: Optional[float]) -> Optional[Dict]:
        """
        DEPRECATED: The /redeem endpoint does not exist in Polymarket CLOB API.
        Redemption happens on-chain via smart contracts.
        
        This method is kept for backwards compatibility but always returns None.
        """
        if config.VERBOSE_LOGGING:
            print("ℹ️ Note: Polymarket redemption is on-chain, not via REST API")
        return None
    
    def _try_claim_endpoint(self, token_id: str, shares: Optional[float]) -> Optional[Dict]:
        """
        DEPRECATED: The /claim endpoint does not exist in Polymarket CLOB API.
        Redemption happens on-chain via smart contracts.
        
        This method is kept for backwards compatibility but always returns None.
        """
        if config.VERBOSE_LOGGING:
            print("ℹ️ Note: Polymarket claims are on-chain, not via REST API")
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
        Attempt to redeem all WINNING positions on-chain.
        
        IMPORTANT: Only redeems positions where current_price >= 0.90 (winning).
        Positions with current_price ~= 0 are LOSING positions and are skipped.
        
        For each winning position, this method calls the CTF contract's
        `redeemPositions` function to burn tokens and receive USDC.
        
        Returns:
            Dict with summary of redemption results
        """
        if config.TEST_MODE:
            return {
                "total_redeemed": 0,
                "positions_processed": 0,
                "winning_positions": 0,
                "losing_positions": 0,
                "onchain_redeemed": 0,
                "already_redeemed": 0,
                "needs_manual_redemption": 0,
                "failed": [],
                "simulated": True
            }
        
        print("🔍 Checking positions for redemption...")
        
        positions = self.get_open_positions()
        
        if not positions:
            print("ℹ️ No open positions found")
            return {
                "total_redeemed": 0,
                "positions_processed": 0,
                "winning_positions": 0,
                "losing_positions": 0,
                "onchain_redeemed": 0,
                "already_redeemed": 0,
                "needs_manual_redemption": 0,
                "failed": []
            }
        
        total_redeemed = 0.0
        onchain_redeemed = 0
        already_redeemed = 0
        needs_manual = 0
        failed = []
        winning_positions = 0
        losing_positions = 0
        unresolved_positions = 0
        positions_needing_redemption = []
        
        print(f"📋 Found {len(positions)} open positions")
        
        for pos in positions:
            token_id = pos.get("token_id")
            shares = pos.get("size", 0)
            cur_price = pos.get("current_price", 0)
            title = pos.get("title", "Unknown")[:40]
            
            if not token_id or shares <= 0:
                continue
            
            # ════════════════════════════════════════════════════════════════
            # CRITICAL: Only redeem WINNING positions (price >= 0.90)
            # Losing positions have price ~= 0.0 and should be SKIPPED
            # ════════════════════════════════════════════════════════════════
            
            if cur_price < 0.10:
                # This is a LOSING position (resolved to ~0) - no value to redeem
                losing_positions += 1
                if config.VERBOSE_LOGGING:
                    print(f"   ❌ LOSS: {title}... ({shares:.2f} shares @ ${cur_price:.2f}) - skipping")
                continue
            elif cur_price < 0.90:
                # Market not yet resolved or mid-priced - skip for now
                unresolved_positions += 1
                if config.VERBOSE_LOGGING:
                    print(f"   ⏳ PENDING: {title}... ({shares:.2f} shares @ ${cur_price:.2f}) - not resolved")
                continue
            
            # ════════════════════════════════════════════════════════════════
            # This is a WINNING position (price >= 0.90) - attempt redemption
            # ════════════════════════════════════════════════════════════════
            winning_positions += 1
            estimated_value = shares * cur_price
            print(f"\n   💰 WIN: {title}...")
            print(f"      {shares:.4f} shares @ ${cur_price:.2f} (~${estimated_value:.2f})")
            
            # Attempt redemption
            result = self.redeem_winning_shares(token_id, shares)
            
            if result:
                if result.get("method") == "onchain_redemption":
                    # Successfully redeemed on-chain
                    onchain_redeemed += 1
                    amount = result.get("amount_usdc", 0)
                    total_redeemed += amount
                    print(f"      ✅ Redeemed ${amount:.2f} on-chain")
                elif result.get("method") == "already_redeemed":
                    already_redeemed += 1
                    print(f"      ✅ Already redeemed")
                elif result.get("needs_manual_redemption"):
                    needs_manual += 1
                    value = result.get("amount_usdc", 0)
                    positions_needing_redemption.append({
                        "token_id": token_id[:16] + "...",
                        "shares": shares,
                        "value": value
                    })
                    failed.append(token_id)
                    print(f"      ⚠️ Needs manual redemption")
        
        summary = {
            "total_redeemed": total_redeemed,
            "positions_processed": len(positions),
            "winning_positions": winning_positions,
            "losing_positions": losing_positions,
            "unresolved_positions": unresolved_positions,
            "onchain_redeemed": onchain_redeemed,
            "already_redeemed": already_redeemed,
            "needs_manual_redemption": needs_manual,
            "failed": failed
        }
        
        print(f"\n📊 Redemption Summary:")
        print(f"   Total positions: {len(positions)}")
        print(f"   ❌ Losing (skipped): {losing_positions}")
        print(f"   ⏳ Unresolved: {unresolved_positions}")
        print(f"   💰 Winning: {winning_positions}")
        if winning_positions > 0:
            print(f"      On-chain redeemed: {onchain_redeemed} (${total_redeemed:.2f})")
            print(f"      Already redeemed: {already_redeemed}")
        
        if needs_manual > 0:
            print(f"\n   ⚠️ Manual redemption needed: {needs_manual}")
            print(f"   👉 Visit https://polymarket.com/portfolio to redeem:")
            for pos in positions_needing_redemption:
                print(f"      • {pos['shares']:.4f} shares (~${pos['value']:.2f})")
        
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
