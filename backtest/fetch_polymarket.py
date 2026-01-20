"""
Polymarket CLOB Timeseries Fetcher

Fetches REAL historical price data from Polymarket's CLOB API.
This replaces synthetic/simulated market data with actual historical snapshots.

API Documentation: https://docs.polymarket.com/developers/CLOB/timeseries

Usage:
    # Fetch data for markets in your CSV
    python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv --days 30
    
    # Fetch with date range
    python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv \\
        --start 2025-11-01 --end 2025-12-01
    
    # Test with small sample first
    python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv --limit 10

Output:
    data/polymarket_15m.csv - Real historical Polymarket market snapshots
"""

import os
import sys
import csv
import json
import time
import argparse
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from time import sleep

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# API Endpoints (per Polymarket docs)
CLOB_API_BASE = "https://clob.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"

# Timeseries endpoint (documented at https://docs.polymarket.com/developers/CLOB/timeseries)
TIMESERIES_ENDPOINT = "/prices-history"

# Output paths
DATA_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUTPUT_FILE = os.path.join(DATA_FOLDER, "polymarket_15m.csv")

# Request settings
USER_AGENT = "polymarket-backtest-fetcher/1.0"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 5
BASE_BACKOFF = 1.0
REQUEST_DELAY = 0.4  # Seconds between requests (be polite)

# Granularity: 15 minutes = 900 seconds
INTERVAL_SECONDS = 900


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MarketInfo:
    """Information about a Polymarket market."""
    market_id: str
    token_id: str  # CLOB token ID for API calls
    question: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    resolved_outcome: Optional[str]
    condition_id: Optional[str] = None


@dataclass
class PricePoint:
    """A single price point from the timeseries."""
    timestamp: datetime
    yes_price: float
    no_price: float
    volume: Optional[float] = None


@dataclass 
class FetchStats:
    """Statistics for the fetch operation."""
    markets_processed: int = 0
    markets_with_data: int = 0
    markets_failed: int = 0
    total_price_points: int = 0
    total_intervals: int = 0
    api_calls: int = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


# ─────────────────────────────────────────────────────────────────────────────
# API FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def call_api(
    base_url: str,
    path: str,
    params: Dict[str, Any] = None,
    timeout: int = REQUEST_TIMEOUT
) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Make an API call with retry logic and backoff.
    
    Returns:
        Tuple of (response_data, error_message)
    """
    url = base_url.rstrip("/") + path
    headers = {"User-Agent": USER_AGENT}
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            
            if response.status_code == 200:
                return response.json(), None
            
            # Rate limited or server error - retry with backoff
            if response.status_code in (429, 500, 502, 503, 504):
                backoff = BASE_BACKOFF * (2 ** attempt)
                print(f"   ⚠️ Status {response.status_code}, retrying in {backoff:.1f}s...")
                sleep(backoff)
                continue
            
            # Other error
            return None, f"HTTP {response.status_code}: {response.text[:200]}"
            
        except requests.exceptions.Timeout:
            backoff = BASE_BACKOFF * (2 ** attempt)
            print(f"   ⏱️ Timeout, retrying in {backoff:.1f}s...")
            sleep(backoff)
            continue
            
        except requests.exceptions.RequestException as e:
            return None, f"Request error: {str(e)}"
    
    return None, f"Max retries ({MAX_RETRIES}) exceeded"


def fetch_timeseries(
    token_id: str,
    start_ts: int = None,
    end_ts: int = None,
    fidelity: int = INTERVAL_SECONDS
) -> Tuple[List[PricePoint], Optional[str]]:
    """
    Fetch price timeseries from CLOB API.
    
    Per docs: GET /prices-history?market={token_id}&interval={interval}&fidelity={fidelity}
    
    Args:
        token_id: The CLOB token ID (not market ID)
        start_ts: Start timestamp (Unix seconds)
        end_ts: End timestamp (Unix seconds) 
        fidelity: Granularity in seconds (900 = 15 min)
    
    Returns:
        Tuple of (list of PricePoint, error message)
    """
    params = {
        "market": token_id,
        "fidelity": fidelity
    }
    
    # Only add time constraints if reasonable range (API may reject wide ranges)
    if start_ts and end_ts:
        # Check range isn't too wide (max ~30 days seems reasonable)
        max_range_days = 30
        if end_ts - start_ts > max_range_days * 24 * 3600:
            # Too wide - don't pass timestamps, let API return what it has
            pass
        else:
            params["startTs"] = start_ts
            params["endTs"] = end_ts
    elif start_ts:
        params["startTs"] = start_ts
    elif end_ts:
        params["endTs"] = end_ts
    
    data, err = call_api(CLOB_API_BASE, TIMESERIES_ENDPOINT, params)
    
    if err:
        return [], err
    
    if not data:
        return [], "Empty response"
    
    # Parse response - format varies, handle multiple shapes
    price_points = []
    
    # Try different response formats
    history = None
    if isinstance(data, list):
        history = data
    elif isinstance(data, dict):
        # Try known keys
        for key in ("history", "prices", "data", "series", "timeseries"):
            if key in data and isinstance(data[key], list):
                history = data[key]
                break
        # Maybe the dict itself has timestamp keys
        if not history and "t" in data or "timestamp" in data:
            history = [data]
    
    if not history:
        # Empty history is valid - market just had no trades
        return [], None
    
    for point in history:
        try:
            # Parse timestamp (could be 't', 'timestamp', 'time', or Unix int)
            ts = None
            for key in ("t", "timestamp", "time", "ts"):
                if key in point:
                    ts_val = point[key]
                    if isinstance(ts_val, (int, float)):
                        # Could be seconds or milliseconds
                        if ts_val > 1e12:  # Milliseconds
                            ts = datetime.fromtimestamp(ts_val / 1000, tz=timezone.utc)
                        else:  # Seconds
                            ts = datetime.fromtimestamp(ts_val, tz=timezone.utc)
                    elif isinstance(ts_val, str):
                        ts = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
                    break
            
            if not ts:
                continue
            
            # Parse prices
            yes_price = None
            no_price = None
            
            for key in ("p", "price", "yesPrice", "yes_price", "outcomeYesPrice"):
                if key in point:
                    yes_price = float(point[key])
                    break
            
            # If we have yes price, no price is 1 - yes (assuming binary market)
            if yes_price is not None:
                no_price = 1.0 - yes_price
            
            # Try explicit no price
            for key in ("noPrice", "no_price", "outcomeNoPrice"):
                if key in point:
                    no_price = float(point[key])
                    break
            
            if yes_price is None:
                continue
            
            # Parse volume if available
            volume = None
            for key in ("v", "volume", "vol"):
                if key in point:
                    volume = float(point[key])
                    break
            
            price_points.append(PricePoint(
                timestamp=ts,
                yes_price=yes_price,
                no_price=no_price if no_price else 1.0 - yes_price,
                volume=volume
            ))
            
        except (ValueError, TypeError, KeyError) as e:
            continue
    
    return price_points, None


def parse_date_flexible(date_str: str) -> Optional[datetime]:
    """Parse dates in various formats."""
    if not date_str:
        return None
    date_str = date_str.strip()
    
    # Try various formats
    formats = [
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d',
    ]
    
    # Clean timezone info
    clean = date_str.rstrip('Z').split('+')[0]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except:
            pass
    return None


def load_markets_from_csv(
    markets_csv: str,
    date_range_start: datetime = None,
    date_range_end: datetime = None,
    limit: int = None
) -> List[MarketInfo]:
    """
    Load ALL markets from CSV that overlap with the given date range.
    
    This loads ANY market (not just BTC 15-min) to get real Polymarket 
    price dynamics for backtesting.
    
    Args:
        markets_csv: Path to markets CSV (from Kaggle/Polymarket export)
        date_range_start: Only include markets that end AFTER this date
        date_range_end: Only include markets that end BEFORE this date
        limit: Max markets to return
    
    Returns:
        List of MarketInfo objects
    """
    markets = []
    
    if not markets_csv or not os.path.exists(markets_csv):
        print(f"❌ Markets CSV not found: {markets_csv}")
        return markets
    
    print(f"📂 Loading markets from {markets_csv}...")
    if date_range_start and date_range_end:
        print(f"   Filtering for markets ending between {date_range_start.date()} and {date_range_end.date()}")
    
    try:
        with open(markets_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Parse end date - we want markets that resolved in our range
                end_time = parse_date_flexible(row.get("endDateIso") or row.get("endDate") or "")
                
                # Filter by date range (market must end within our Binance data period)
                if date_range_start and date_range_end:
                    if not end_time:
                        continue
                    if end_time < date_range_start or end_time > date_range_end:
                        continue
                
                # Get token ID (critical for API calls)
                token_id = None
                clob_ids = row.get("clobTokenIds", "")
                
                # Parse clobTokenIds - could be JSON array string
                if clob_ids and clob_ids not in ('', '[]', 'null'):
                    try:
                        if clob_ids.startswith("["):
                            ids = json.loads(clob_ids)
                            if ids and isinstance(ids, list) and len(ids) > 0:
                                # Verify it's a valid token ID (long numeric string)
                                candidate = str(ids[0])
                                if len(candidate) > 10:
                                    token_id = candidate
                        else:
                            token_id = clob_ids.split(",")[0].strip()
                    except:
                        pass
                
                # Skip if no valid token ID
                if not token_id or len(token_id) < 10:
                    continue
                
                # Parse start date
                start_time = parse_date_flexible(
                    row.get("startDateIso") or row.get("startDate") or row.get("createdAt") or ""
                )
                
                # Parse resolved outcome from final prices
                resolved = None
                outcome_prices = row.get("outcomePrices", "")
                if outcome_prices:
                    try:
                        prices = json.loads(outcome_prices)
                        if len(prices) >= 2:
                            # Check which outcome won (price ~1.0)
                            yes_final = float(str(prices[0]).strip('"'))
                            no_final = float(str(prices[1]).strip('"'))
                            if yes_final > 0.9:
                                resolved = "UP"  
                            elif no_final > 0.9:
                                resolved = "DOWN"
                    except:
                        pass
                
                markets.append(MarketInfo(
                    market_id=row.get("id") or token_id,
                    token_id=token_id,
                    question=row.get("question") or row.get("title") or "",
                    start_time=start_time,
                    end_time=end_time,
                    resolved_outcome=resolved,
                    condition_id=row.get("conditionId")
                ))
                
                if limit and len(markets) >= limit:
                    break
                    
    except Exception as e:
        print(f"⚠️ Error reading CSV: {e}")
    
    print(f"   Found {len(markets)} markets matching criteria")
    return markets


def discover_btc_markets(
    markets_csv: str = None,
    search_term: str = "btc",
    limit: int = None,
    date_range_start: datetime = None,
    date_range_end: datetime = None
) -> List[MarketInfo]:
    """
    Discover markets from CSV or API.
    
    If date_range is provided, returns ALL markets in that range.
    Otherwise, filters for BTC 15-minute markets specifically.
    
    Args:
        markets_csv: Path to markets CSV (from Polymarket export)
        search_term: Term to filter markets (default: btc)
        limit: Max markets to return
        date_range_start: Start of date range filter
        date_range_end: End of date range filter
    
    Returns:
        List of MarketInfo objects
    """
    # If date range is provided, use the new loader that gets ALL markets
    if date_range_start and date_range_end and markets_csv:
        return load_markets_from_csv(
            markets_csv=markets_csv,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            limit=limit
        )
    
    # Legacy behavior: filter for BTC 15-minute markets
    markets = []
    
    # Try loading from CSV first (preferred - has more complete data)
    if markets_csv and os.path.exists(markets_csv):
        print(f"📂 Loading markets from {markets_csv}...")
        
        try:
            with open(markets_csv, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    # Get question/title
                    question = (
                        row.get("question") or 
                        row.get("title") or 
                        row.get("description") or 
                        ""
                    ).lower()
                    
                    # Filter for BTC 15-minute markets
                    is_btc = "btc" in question or "bitcoin" in question
                    is_15min = (
                        "15" in question or 
                        "fifteen" in question or
                        "15-min" in question or
                        "15 min" in question
                    )
                    
                    if not (is_btc and is_15min):
                        continue
                    
                    # Get token ID (critical for API calls)
                    token_id = None
                    clob_ids = row.get("clobTokenIds", "")
                    
                    # Parse clobTokenIds - could be JSON array string
                    if clob_ids:
                        try:
                            if clob_ids.startswith("["):
                                ids = json.loads(clob_ids)
                                if ids:
                                    token_id = str(ids[0])
                            else:
                                token_id = clob_ids.split(",")[0].strip()
                        except:
                            pass
                    
                    # Fallback to other ID fields
                    if not token_id:
                        token_id = (
                            row.get("conditionId") or
                            row.get("id") or
                            row.get("marketId")
                        )
                    
                    if not token_id:
                        continue
                    
                    # Parse dates
                    start_time = None
                    end_time = None
                    
                    for key in ("startDate", "startDateIso", "createdAt"):
                        if row.get(key):
                            try:
                                start_time = datetime.fromisoformat(
                                    row[key].replace("Z", "+00:00")
                                )
                                break
                            except:
                                pass
                    
                    for key in ("endDate", "endDateIso", "closedTime"):
                        if row.get(key):
                            try:
                                end_time = datetime.fromisoformat(
                                    row[key].replace("Z", "+00:00")
                                )
                                break
                            except:
                                pass
                    
                    # Parse resolved outcome
                    resolved = None
                    outcome_prices = row.get("outcomePrices", "")
                    if outcome_prices:
                        try:
                            prices = json.loads(outcome_prices)
                            if len(prices) >= 2:
                                # Check which outcome won (price ~1.0)
                                yes_final = float(prices[0].strip('"'))
                                no_final = float(prices[1].strip('"'))
                                if yes_final > 0.9:
                                    resolved = "UP"
                                elif no_final > 0.9:
                                    resolved = "DOWN"
                        except:
                            pass
                    
                    markets.append(MarketInfo(
                        market_id=row.get("id") or token_id,
                        token_id=token_id,
                        question=row.get("question") or row.get("title") or "",
                        start_time=start_time,
                        end_time=end_time,
                        resolved_outcome=resolved,
                        condition_id=row.get("conditionId")
                    ))
                    
                    if limit and len(markets) >= limit:
                        break
                        
        except Exception as e:
            print(f"⚠️ Error reading CSV: {e}")
    
    # If no CSV or no markets found, try Gamma API
    if not markets:
        print("🌐 Discovering markets from Gamma API...")
        
        params = {
            "closed": "true",
            "limit": limit or 100,
            "order": "endDate",
            "ascending": "false"
        }
        
        data, err = call_api(GAMMA_API_BASE, "/markets", params)
        
        if data and not err:
            for market in data:
                question = market.get("question", "").lower()
                
                is_btc = "btc" in question or "bitcoin" in question
                is_15min = "15" in question or "fifteen" in question
                
                if not (is_btc and is_15min):
                    continue
                
                # Get token ID from clobTokenIds
                token_id = None
                clob_ids = market.get("clobTokenIds", [])
                if isinstance(clob_ids, str):
                    try:
                        clob_ids = json.loads(clob_ids)
                    except:
                        clob_ids = []
                
                if clob_ids:
                    token_id = str(clob_ids[0])
                else:
                    token_id = market.get("conditionId") or market.get("id")
                
                if not token_id:
                    continue
                
                # Parse dates
                start_time = None
                end_time = None
                
                if market.get("startDate"):
                    try:
                        start_time = datetime.fromisoformat(
                            market["startDate"].replace("Z", "+00:00")
                        )
                    except:
                        pass
                
                if market.get("endDate"):
                    try:
                        end_time = datetime.fromisoformat(
                            market["endDate"].replace("Z", "+00:00")
                        )
                    except:
                        pass
                
                markets.append(MarketInfo(
                    market_id=market.get("id") or token_id,
                    token_id=token_id,
                    question=market.get("question", ""),
                    start_time=start_time,
                    end_time=end_time,
                    resolved_outcome=None,
                    condition_id=market.get("conditionId")
                ))
                
                if limit and len(markets) >= limit:
                    break
    
    print(f"   Found {len(markets)} BTC 15-minute markets")
    return markets


def align_to_15min(dt: datetime) -> datetime:
    """Align a datetime to the nearest 15-minute boundary (floor)."""
    minute = (dt.minute // 15) * 15
    return dt.replace(minute=minute, second=0, microsecond=0)


def aggregate_to_intervals(
    price_points: List[PricePoint],
    market: MarketInfo,
    start_dt: datetime = None,
    end_dt: datetime = None
) -> List[Dict]:
    """
    Aggregate price points to 15-minute interval snapshots.
    
    Uses the price at the START of each interval (when bot would trade).
    
    Returns:
        List of interval dicts ready for CSV output
    """
    if not price_points:
        return []
    
    # Sort by timestamp
    price_points.sort(key=lambda p: p.timestamp)
    
    # Determine range
    if not start_dt:
        start_dt = align_to_15min(price_points[0].timestamp)
    if not end_dt:
        end_dt = align_to_15min(price_points[-1].timestamp) + timedelta(minutes=15)
    
    # Build lookup by aligned timestamp
    price_lookup = {}
    for p in price_points:
        aligned = align_to_15min(p.timestamp)
        # Use the first (earliest) price in each interval
        if aligned not in price_lookup:
            price_lookup[aligned] = p
    
    # Generate intervals
    intervals = []
    current = align_to_15min(start_dt)
    
    while current < end_dt:
        if current in price_lookup:
            p = price_lookup[current]
            
            intervals.append({
                "interval_start": current.isoformat(),
                "market_id": market.market_id,
                "outcome_yes_price": round(p.yes_price, 6),
                "outcome_no_price": round(p.no_price, 6),
                "resolved_outcome": market.resolved_outcome or "UNKNOWN",
                "volume": round(p.volume, 2) if p.volume else 0,
                "liquidity": 1000.0  # Default if not available
            })
        
        current += timedelta(minutes=15)
    
    return intervals


def get_binance_date_range() -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Read the Binance CSV to get the date range of available data.
    
    Returns:
        Tuple of (start_date, end_date) or (None, None) if file not found
    """
    binance_path = os.path.join(DATA_FOLDER, "binance_1m.csv")
    
    if not os.path.exists(binance_path):
        return None, None
    
    try:
        with open(binance_path, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
            if not rows:
                return None, None
            
            # Get first and last timestamp
            first_ts = int(rows[0].get('timestamp', 0))
            last_ts = int(rows[-1].get('timestamp', 0))
            
            if first_ts > 1e12:  # Milliseconds
                first_ts //= 1000
                last_ts //= 1000
            
            start = datetime.fromtimestamp(first_ts, tz=timezone.utc)
            end = datetime.fromtimestamp(last_ts, tz=timezone.utc)
            
            return start, end
            
    except Exception as e:
        print(f"⚠️ Could not read Binance date range: {e}")
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN FETCH FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def fetch_polymarket_data(
    markets_csv: str = None,
    output_file: str = OUTPUT_FILE,
    start_date: datetime = None,
    end_date: datetime = None,
    limit_markets: int = None,
    verbose: bool = True,
    auto_detect_range: bool = False
) -> FetchStats:
    """
    Fetch real Polymarket timeseries data and write to CSV.
    
    Args:
        markets_csv: Path to markets CSV (polymarket_markets.csv)
        output_file: Output CSV path
        start_date: Filter - only fetch data after this date
        end_date: Filter - only fetch data before this date
        limit_markets: Limit number of markets (for testing)
        verbose: Print progress
        auto_detect_range: Auto-detect date range from Binance data
    
    Returns:
        FetchStats with results
    """
    stats = FetchStats()
    all_intervals = []
    
    print("\n" + "=" * 60)
    print("🎯 POLYMARKET CLOB TIMESERIES FETCHER")
    print("=" * 60)
    print("Data source: Polymarket CLOB API (REAL historical data)")
    print("API docs: https://docs.polymarket.com/developers/CLOB/timeseries")
    print("=" * 60)
    
    # Auto-detect date range from Binance data if requested
    if auto_detect_range and (not start_date or not end_date):
        binance_start, binance_end = get_binance_date_range()
        if binance_start and binance_end:
            print(f"\n🔍 Auto-detected Binance data range:")
            print(f"   {binance_start.strftime('%Y-%m-%d')} to {binance_end.strftime('%Y-%m-%d')}")
            if not start_date:
                start_date = binance_start
            if not end_date:
                end_date = binance_end
    
    # Discover markets with date range filter
    markets = discover_btc_markets(
        markets_csv=markets_csv, 
        limit=limit_markets,
        date_range_start=start_date,
        date_range_end=end_date
    )
    
    if not markets:
        print("❌ No BTC 15-minute markets found!")
        print("   Make sure polymarket_markets.csv contains BTC 15-min markets")
        stats.errors.append("No markets found")
        return stats
    
    # Calculate date range
    start_ts = None
    end_ts = None
    
    if start_date:
        start_ts = int(start_date.timestamp())
    if end_date:
        end_ts = int(end_date.timestamp())
    
    print(f"\n📊 Fetching timeseries for {len(markets)} markets...")
    if start_date:
        print(f"   From: {start_date.strftime('%Y-%m-%d %H:%M')} UTC")
    if end_date:
        print(f"   To:   {end_date.strftime('%Y-%m-%d %H:%M')} UTC")
    print()
    
    # Fetch each market
    for i, market in enumerate(markets):
        stats.markets_processed += 1
        
        if verbose:
            print(f"[{i+1}/{len(markets)}] {market.market_id[:20]}... ", end="", flush=True)
        
        # For each market, fetch the 7 days BEFORE its end date
        # This gives us the most relevant price data before resolution
        if market.end_time:
            m_end = int(market.end_time.timestamp())
            m_start = m_end - (7 * 24 * 3600)  # 7 days before end
        else:
            # Fallback to global date range
            m_end = end_ts
            m_start = m_end - (7 * 24 * 3600) if m_end else None
        
        # Fetch timeseries
        price_points, err = fetch_timeseries(
            token_id=market.token_id,
            start_ts=m_start,
            end_ts=m_end,
            fidelity=INTERVAL_SECONDS
        )
        stats.api_calls += 1
        
        if err:
            if verbose:
                print(f"❌ {err[:50]}")
            stats.markets_failed += 1
            stats.errors.append(f"{market.market_id}: {err}")
            sleep(REQUEST_DELAY)
            continue
        
        if not price_points:
            if verbose:
                print("⚠️ No data")
            stats.markets_failed += 1
            sleep(REQUEST_DELAY)
            continue
        
        stats.markets_with_data += 1
        stats.total_price_points += len(price_points)
        
        # Aggregate to intervals - use price points' own range, not global range
        # This ensures we capture all available price data for each market
        intervals = aggregate_to_intervals(
            price_points,
            market,
            start_dt=None,  # Let function use price points' range
            end_dt=None     # Let function use price points' range
        )
        
        stats.total_intervals += len(intervals)
        all_intervals.extend(intervals)
        
        if verbose:
            print(f"✅ {len(price_points)} points → {len(intervals)} intervals")
        
        # Rate limiting
        sleep(REQUEST_DELAY)
    
    # Sort by interval start
    all_intervals.sort(key=lambda x: x["interval_start"])
    
    # Remove duplicates (same interval_start)
    seen = set()
    unique_intervals = []
    for interval in all_intervals:
        key = interval["interval_start"]
        if key not in seen:
            seen.add(key)
            unique_intervals.append(interval)
    
    # Write output
    if unique_intervals:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        fieldnames = [
            "interval_start", "market_id", "outcome_yes_price",
            "outcome_no_price", "resolved_outcome", "volume", "liquidity"
        ]
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(unique_intervals)
        
        print(f"\n💾 Saved {len(unique_intervals)} intervals to {output_file}")
    else:
        print("\n❌ No intervals to save!")
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 FETCH SUMMARY")
    print("=" * 60)
    print(f"Markets processed:   {stats.markets_processed}")
    print(f"Markets with data:   {stats.markets_with_data}")
    print(f"Markets failed:      {stats.markets_failed}")
    print(f"Total price points:  {stats.total_price_points}")
    print(f"Total intervals:     {stats.total_intervals}")
    print(f"Unique intervals:    {len(unique_intervals)}")
    print(f"API calls made:      {stats.api_calls}")
    
    if stats.errors:
        print(f"\n⚠️ {len(stats.errors)} errors (first 5):")
        for err in stats.errors[:5]:
            print(f"   - {err[:80]}")
    
    print("=" * 60)
    
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch REAL Polymarket historical data from CLOB API"
    )
    
    parser.add_argument(
        "--markets-csv",
        type=str,
        default="polymarket_markets.csv",
        help="Path to Polymarket markets CSV export"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=OUTPUT_FILE,
        help=f"Output CSV path (default: {OUTPUT_FILE})"
    )
    
    parser.add_argument(
        "--days",
        type=int,
        help="Fetch data for the last N days"
    )
    
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of markets (for testing)"
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Less verbose output"
    )
    
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-detect date range from Binance data (recommended)"
    )
    
    args = parser.parse_args()
    
    # Calculate date range
    start_date = None
    end_date = None
    
    if args.start:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    
    if args.days:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=args.days)
    
    # Run fetcher
    stats = fetch_polymarket_data(
        markets_csv=args.markets_csv,
        output_file=args.output,
        start_date=start_date,
        end_date=end_date,
        limit_markets=args.limit,
        verbose=not args.quiet,
        auto_detect_range=args.auto
    )
    
    if stats.markets_with_data > 0:
        print("\n✅ Polymarket data fetch complete!")
        print(f"   Now run backtest: python3 -m backtest.backtest")
        return 0
    else:
        print("\n❌ No data fetched. Check your markets CSV and date range.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
