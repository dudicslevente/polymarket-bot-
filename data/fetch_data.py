"""
Data fetcher for downloading real historical data for backtesting.

This script downloads:
1. Binance BTC/USDT 1-minute candles (free, no API key needed)
2. Polymarket market data via CLOB API (real historical data)

Usage:
    python3 data/fetch_data.py --days 30
    python3 data/fetch_data.py --start 2024-01-01 --end 2024-03-01
    
For Polymarket data, you need polymarket_markets.csv from Polymarket export.
Run separately:
    python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv --days 30
"""

import os
import sys
import csv
import time
import argparse
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple

# Output paths
DATA_FOLDER = os.path.dirname(os.path.abspath(__file__))
BINANCE_OUTPUT = os.path.join(DATA_FOLDER, "binance_1m.csv")
POLYMARKET_OUTPUT = os.path.join(DATA_FOLDER, "polymarket_15m.csv")

# API endpoints
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"


def timestamp_to_ms(dt: datetime) -> int:
    """Convert datetime to Unix timestamp in milliseconds."""
    return int(dt.timestamp() * 1000)


def ms_to_datetime(ms: int) -> datetime:
    """Convert Unix timestamp in milliseconds to datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def fetch_binance_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    start_time: datetime = None,
    end_time: datetime = None,
    limit: int = 1000
) -> List[Dict]:
    """
    Fetch kline/candlestick data from Binance.
    
    Args:
        symbol: Trading pair (default BTCUSDT)
        interval: Candle interval (1m, 5m, 15m, 1h, etc.)
        start_time: Start datetime
        end_time: End datetime
        limit: Max candles per request (max 1000)
    
    Returns:
        List of candle dictionaries
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    
    if start_time:
        params["startTime"] = timestamp_to_ms(start_time)
    if end_time:
        params["endTime"] = timestamp_to_ms(end_time)
    
    try:
        response = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        candles = []
        for k in data:
            candles.append({
                "timestamp": k[0],  # Open time in ms
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
                "quote_volume": float(k[7]),
                "trades": k[8]
            })
        
        return candles
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Binance API error: {e}")
        return []


def download_binance_data(
    start_date: datetime,
    end_date: datetime,
    output_file: str = BINANCE_OUTPUT
) -> int:
    """
    Download Binance 1-minute candles for a date range.
    
    Args:
        start_date: Start datetime
        end_date: End datetime
        output_file: Path to output CSV
    
    Returns:
        Number of candles downloaded
    """
    print(f"\n📥 Downloading Binance BTC/USDT 1-minute candles...")
    print(f"   From: {start_date.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"   To:   {end_date.strftime('%Y-%m-%d %H:%M')} UTC")
    
    all_candles = []
    current_start = start_date
    request_count = 0
    
    # Calculate total expected candles for progress
    total_minutes = int((end_date - start_date).total_seconds() / 60)
    
    while current_start < end_date:
        # Binance returns max 1000 candles per request
        # For 1m candles, that's ~16.6 hours
        batch_end = min(current_start + timedelta(minutes=999), end_date)
        
        candles = fetch_binance_klines(
            symbol="BTCUSDT",
            interval="1m",
            start_time=current_start,
            end_time=batch_end,
            limit=1000
        )
        
        if not candles:
            print(f"⚠️ No data returned for {current_start}")
            current_start = batch_end + timedelta(minutes=1)
            continue
        
        all_candles.extend(candles)
        request_count += 1
        
        # Progress update
        progress = len(all_candles) / total_minutes * 100
        print(f"   Downloaded {len(all_candles):,} candles ({progress:.1f}%)...", end="\r")
        
        # Move to next batch
        last_candle_time = ms_to_datetime(candles[-1]["timestamp"])
        current_start = last_candle_time + timedelta(minutes=1)
        
        # Rate limiting - Binance allows 1200 requests/min, we'll be conservative
        if request_count % 10 == 0:
            time.sleep(0.5)
    
    print(f"\n   ✅ Downloaded {len(all_candles):,} candles in {request_count} requests")
    
    # Write to CSV
    if all_candles:
        # Remove duplicates (by timestamp)
        seen = set()
        unique_candles = []
        for c in all_candles:
            if c["timestamp"] not in seen:
                seen.add(c["timestamp"])
                unique_candles.append(c)
        
        # Sort by timestamp
        unique_candles.sort(key=lambda x: x["timestamp"])
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            for c in unique_candles:
                writer.writerow([
                    c["timestamp"],
                    f"{c['open']:.2f}",
                    f"{c['high']:.2f}",
                    f"{c['low']:.2f}",
                    f"{c['close']:.2f}",
                    f"{c['volume']:.8f}"
                ])
        
        print(f"   💾 Saved to {output_file}")
        return len(unique_candles)
    
    return 0


def fetch_polymarket_btc_markets() -> List[Dict]:
    """
    Attempt to fetch BTC 15-minute markets from Polymarket.
    
    Note: Polymarket's historical data availability varies.
    This function tries multiple endpoints.
    """
    markets = []
    
    # Try the Gamma API for market discovery
    try:
        # Search for BTC markets
        url = f"{POLYMARKET_GAMMA_URL}/markets"
        params = {
            "closed": "true",
            "limit": 100,
            "order": "endDate",
            "ascending": "false"
        }
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            # Filter for BTC 15-minute markets
            for market in data:
                question = market.get("question", "").lower()
                if "btc" in question and ("15" in question or "fifteen" in question):
                    markets.append(market)
        
    except Exception as e:
        print(f"⚠️ Polymarket API error: {e}")
    
    return markets


def generate_polymarket_from_btc(
    binance_file: str = BINANCE_OUTPUT,
    output_file: str = POLYMARKET_OUTPUT
) -> int:
    """
    Generate SYNTHETIC Polymarket-style market data from BTC candles.
    
    ⚠️ WARNING: This creates SIMULATED data, NOT real Polymarket history!
    Use this only for testing the backtest framework, not for actual strategy validation.
    
    For REAL Polymarket data, use:
        python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv
    
    The market odds are simulated to be realistic:
    - Base odds around 50/50
    - Slight random variation to simulate market inefficiency
    - Resolved outcome based on actual BTC price movement
    
    Args:
        binance_file: Path to Binance candles CSV
        output_file: Path to output Polymarket CSV
    
    Returns:
        Number of intervals created
    """
    import random
    
    print(f"\n⚠️ GENERATING SYNTHETIC POLYMARKET DATA (NOT REAL!)")
    print(f"   For real data, run:")
    print(f"   python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv")
    print()
    
    if not os.path.exists(binance_file):
        print(f"❌ Binance data not found: {binance_file}")
        return 0
    
    # Load Binance candles
    candles = {}
    with open(binance_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(row['timestamp'])
            candles[ts] = {
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume'])
            }
    
    if not candles:
        print("❌ No candles loaded")
        return 0
    
    # Get sorted timestamps
    timestamps = sorted(candles.keys())
    
    # Find 15-minute interval boundaries
    # Align to 15-minute marks (00, 15, 30, 45)
    first_ts = ms_to_datetime(timestamps[0])
    last_ts = ms_to_datetime(timestamps[-1])
    
    # Align to next 15-min boundary
    minute = first_ts.minute
    aligned_minute = (minute // 15) * 15
    interval_start = first_ts.replace(minute=aligned_minute, second=0, microsecond=0)
    if aligned_minute < minute:
        interval_start += timedelta(minutes=15)
    
    markets = []
    market_id = 0
    
    while interval_start + timedelta(minutes=15) <= last_ts:
        interval_end = interval_start + timedelta(minutes=15)
        
        start_ms = timestamp_to_ms(interval_start)
        end_ms = timestamp_to_ms(interval_end)
        
        # Get candles in this interval
        interval_candles = [
            candles[ts] for ts in timestamps
            if start_ms <= ts < end_ms and ts in candles
        ]
        
        if len(interval_candles) >= 10:  # Need at least 10 of 15 candles
            # Calculate interval OHLCV
            open_price = interval_candles[0]['open']
            close_price = interval_candles[-1]['close']
            high_price = max(c['high'] for c in interval_candles)
            low_price = min(c['low'] for c in interval_candles)
            volume = sum(c['volume'] for c in interval_candles)
            
            # Determine actual outcome
            price_went_up = close_price > open_price
            resolved_outcome = "UP" if price_went_up else "DOWN"
            
            # Generate realistic market odds
            # In efficient markets, odds should be close to 50/50
            # Add small random variation to simulate market inefficiency
            base_yes = 0.50 + random.gauss(0, 0.02)  # Slight random bias
            base_yes = max(0.45, min(0.55, base_yes))  # Clamp
            
            # Simulate a small vig (market maker spread)
            vig = random.uniform(0.01, 0.03)
            yes_price = round(base_yes, 4)
            no_price = round(1.0 - base_yes - vig, 4)
            
            # Simulate volume and liquidity
            market_volume = random.uniform(2000, 15000)
            liquidity = random.uniform(800, 3000)
            
            market_id += 1
            markets.append({
                'interval_start': interval_start.isoformat(),
                'market_id': f"BTC-15M-{market_id:06d}",
                'outcome_yes_price': yes_price,
                'outcome_no_price': no_price,
                'resolved_outcome': resolved_outcome,
                'volume': market_volume,
                'liquidity': liquidity,
                'btc_open': open_price,
                'btc_close': close_price
            })
        
        interval_start = interval_end
    
    # Write to CSV
    if markets:
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'interval_start', 'market_id', 'outcome_yes_price', 
                'outcome_no_price', 'resolved_outcome', 'volume', 'liquidity'
            ])
            
            for m in markets:
                writer.writerow([
                    m['interval_start'],
                    m['market_id'],
                    f"{m['outcome_yes_price']:.4f}",
                    f"{m['outcome_no_price']:.4f}",
                    m['resolved_outcome'],
                    f"{m['volume']:.2f}",
                    f"{m['liquidity']:.2f}"
                ])
        
        print(f"   ✅ Generated {len(markets)} market intervals")
        print(f"   💾 Saved to {output_file}")
        
        # Print some stats
        ups = sum(1 for m in markets if m['resolved_outcome'] == 'UP')
        downs = len(markets) - ups
        print(f"   📈 Outcomes: {ups} UP ({ups/len(markets)*100:.1f}%) / {downs} DOWN ({downs/len(markets)*100:.1f}%)")
        
        return len(markets)
    
    return 0


def print_data_summary(binance_file: str, polymarket_file: str):
    """Print summary of downloaded data."""
    print("\n" + "="*60)
    print("📊 DATA SUMMARY")
    print("="*60)
    
    # Binance data
    if os.path.exists(binance_file):
        with open(binance_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        if rows:
            first_ts = ms_to_datetime(int(rows[0]['timestamp']))
            last_ts = ms_to_datetime(int(rows[-1]['timestamp']))
            
            print(f"\n📈 Binance BTC/USDT 1-minute candles:")
            print(f"   File: {binance_file}")
            print(f"   Candles: {len(rows):,}")
            print(f"   From: {first_ts.strftime('%Y-%m-%d %H:%M')} UTC")
            print(f"   To:   {last_ts.strftime('%Y-%m-%d %H:%M')} UTC")
            print(f"   Price range: ${float(rows[0]['open']):,.2f} to ${float(rows[-1]['close']):,.2f}")
    else:
        print(f"\n❌ Binance data not found: {binance_file}")
    
    # Polymarket data
    if os.path.exists(polymarket_file):
        with open(polymarket_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if rows:
            print(f"\n🎯 Polymarket 15-minute markets:")
            print(f"   File: {polymarket_file}")
            print(f"   Markets: {len(rows):,}")
            print(f"   From: {rows[0]['interval_start']}")
            print(f"   To:   {rows[-1]['interval_start']}")
            
            ups = sum(1 for r in rows if r['resolved_outcome'] == 'UP')
            print(f"   Outcomes: {ups} UP / {len(rows) - ups} DOWN")
    else:
        print(f"\n❌ Polymarket data not found: {polymarket_file}")
    
    print("\n" + "="*60)


def main():
    parser = argparse.ArgumentParser(
        description="Download real historical data for backtesting"
    )
    
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of data to download (default: 30)"
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
        "--binance-only",
        action="store_true",
        help="Only download Binance data"
    )
    
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show summary of existing data"
    )
    
    args = parser.parse_args()
    
    # Just show summary
    if args.summary:
        print_data_summary(BINANCE_OUTPUT, POLYMARKET_OUTPUT)
        return 0
    
    # Calculate date range
    if args.start and args.end:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=args.days)
    
    print("\n" + "="*60)
    print("📥 HISTORICAL DATA DOWNLOADER")
    print("="*60)
    print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Duration: {(end_date - start_date).days} days")
    print("="*60)
    
    # Download Binance data
    candle_count = download_binance_data(start_date, end_date, BINANCE_OUTPUT)
    
    if candle_count == 0:
        print("❌ Failed to download Binance data")
        return 1
    
    # Generate Polymarket data from BTC candles (synthetic - for testing only)
    if not args.binance_only:
        print("\n" + "="*60)
        print("📢 POLYMARKET DATA OPTIONS")
        print("="*60)
        print("")
        print("Option 1: REAL Polymarket data (recommended)")
        print("   Run this command to fetch actual historical Polymarket odds:")
        print("   python -m backtest.fetch_polymarket --markets-csv polymarket_markets.csv")
        print("")
        print("Option 2: Synthetic data (for testing only)")
        print("   Generating synthetic market data from BTC candles...")
        print("   ⚠️ This is NOT real Polymarket data and should not be used")
        print("   for strategy validation!")
        print("")
        
        market_count = generate_polymarket_from_btc(BINANCE_OUTPUT, POLYMARKET_OUTPUT)
    
    # Print summary
    print_data_summary(BINANCE_OUTPUT, POLYMARKET_OUTPUT)
    
    print("\n✅ Data download complete!")
    print("   Run backtest with: python3 -m backtest.backtest")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
