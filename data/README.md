# Historical Data for Backtesting

This folder contains historical data files for backtesting the Polymarket BTC 15-minute trading bot.

## Required Files

### 1. `binance_1m.csv` - BTC 1-Minute Candles

Source: Binance API or Binance Data monthly CSVs

**Columns:**
- `timestamp` - Unix timestamp in milliseconds (e.g., 1705315800000)
- `open` - Opening price
- `high` - Highest price
- `low` - Lowest price  
- `close` - Closing price
- `volume` - Trading volume in BTC

**Example:**
```csv
timestamp,open,high,low,close,volume
1705315800000,42000.50,42100.00,41950.00,42050.25,150.5
1705315860000,42050.25,42080.00,42000.00,42030.10,120.3
```

**How to get this data:**

1. **Binance API:**
   ```python
   import requests
   
   url = "https://api.binance.com/api/v3/klines"
   params = {
       "symbol": "BTCUSDT",
       "interval": "1m",
       "startTime": 1705315800000,  # Your start time
       "limit": 1000
   }
   response = requests.get(url, params=params)
   ```

2. **Binance Data Archive:**
   Download from: https://data.binance.vision/
   Look for: `data/spot/monthly/klines/BTCUSDT/1m/`

### 2. `polymarket_15m.csv` - Polymarket Market Snapshots

Source: Polymarket API or DeltaBase exports

**Columns:**
- `interval_start` - ISO 8601 timestamp (e.g., 2024-01-15T10:00:00Z)
- `market_id` - Unique market identifier
- `outcome_yes_price` - Price of "Yes" (Up) outcome at interval start
- `outcome_no_price` - Price of "No" (Down) outcome at interval start
- `resolved_outcome` - Actual resolution: "UP" or "DOWN"
- `volume` - Trading volume in USD
- `liquidity` - Market liquidity in USD (optional)

**Example:**
```csv
interval_start,market_id,outcome_yes_price,outcome_no_price,resolved_outcome,volume,liquidity
2024-01-15T10:00:00Z,BTC-15M-001,0.52,0.48,UP,5000.00,1500.00
2024-01-15T10:15:00Z,BTC-15M-002,0.49,0.51,DOWN,4200.00,1400.00
```

**How to get this data:**

1. **Polymarket API:**
   ```python
   import requests
   
   # Get price history
   url = "https://clob.polymarket.com/prices-history"
   params = {
       "market": "your-market-id",
       "interval": "15m"
   }
   response = requests.get(url, params=params)
   ```

2. **DeltaBase (third-party):**
   Some community tools export historical Polymarket data.

## Generating Sample Data

If you don't have real historical data, you can generate sample data for testing:

```bash
# From the project root
python -m backtest.backtest --create-sample-data
```

This creates 7 days of synthetic data with realistic price movements.

## Data Quality Notes

1. **Timezone:** All timestamps should be in UTC
2. **Alignment:** Ensure BTC candles and Polymarket snapshots are time-aligned
3. **Gaps:** Missing data will be skipped during backtesting
4. **Volume:** If volume/liquidity data isn't available, use placeholder values

## File Size Estimates

- 1 day of 1-min BTC candles: ~1,440 rows (~100 KB)
- 1 week: ~10,080 rows (~700 KB)
- 1 month: ~43,200 rows (~3 MB)
- 1 year: ~525,600 rows (~35 MB)

## Recommended Data Range

For meaningful backtest results, we recommend at least:
- **Minimum:** 1 week (672 15-min intervals)
- **Recommended:** 1-3 months
- **Ideal:** 6-12 months (captures various market conditions)
