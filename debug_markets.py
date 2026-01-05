#!/usr/bin/env python3
"""
Debug script to test Polymarket API and see what markets are available.
"""

import requests
import json
from datetime import datetime, timezone

def test_polymarket_api():
    """Test the Polymarket Gamma API to see what markets are available."""

    print("🔍 Testing Polymarket API...")

    # Polymarket Gamma API endpoint
    url = "https://gamma-api.polymarket.com/markets"

    params = {
        "active": "true",
        "closed": "false",
        "limit": 100,
    }

    try:
        print(f"📡 Fetching from: {url}")
        print(f"   Params: {params}")

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        print(f"✅ API call successful")
        print(f"   Response type: {type(data)}")

        if isinstance(data, list):
            print(f"   Found {len(data)} markets")

            # Look for BTC markets
            btc_markets = []
            short_term_markets = []
            crypto_markets = []
            minute_markets = []

            for market in data:
                question = market.get("question", "").lower()

                # Check for BTC markets
                if "btc" in question or "bitcoin" in question:
                    btc_markets.append(market)

                # Check for crypto markets
                if any(word in question for word in ["btc", "bitcoin", "eth", "ethereum", "crypto"]):
                    crypto_markets.append(market)

                # Check for minute/hour markets
                if any(word in question for word in ["minute", "hour", "min", "hr", "15", "30", "60"]):
                    minute_markets.append(market)

                # Check for short-term markets (under 24 hours)
                start_str = market.get('startDate')
                end_str = market.get('endDate')

                if start_str and end_str:
                    try:
                        if "T" in str(start_str):
                            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                        else:
                            start = datetime.fromtimestamp(int(start_str) / 1000, tz=timezone.utc)
                            end = datetime.fromtimestamp(int(end_str) / 1000, tz=timezone.utc)

                        duration_min = (end - start).total_seconds() / 60

                        if duration_min <= 1440:  # Under 24 hours
                            short_term_markets.append((market, duration_min))
                    except:
                        pass

            print(f"   BTC markets found: {len(btc_markets)}")
            print(f"   Crypto markets found: {len(crypto_markets)}")
            print(f"   Minute/hour markets found: {len(minute_markets)}")
            print(f"   Short-term markets (<24h): {len(short_term_markets)}")

            # Show minute/hour markets
            if minute_markets:
                print("\n   ⏰ MINUTE/HOUR MARKETS:")
                for market in minute_markets[:10]:  # Show first 10
                    print(f"     {market.get('question', 'N/A')}")
            else:
                print("   ❌ No minute/hour markets found")

            # Show short-term markets
            if short_term_markets:
                print("\n   📅 SHORT-TERM MARKETS (<24h):")
                for market, duration in short_term_markets[:10]:  # Show first 10
                    hours = duration / 60
                    print(f"     {market.get('question', 'N/A')} ({hours:.1f}h)")
            else:
                print("   ❌ No short-term markets found")

            # Show details of BTC markets
            if btc_markets:
                print("\n   ₿ BTC MARKETS:")
                for i, market in enumerate(btc_markets[:5]):  # Show first 5
                    print(f"\n   BTC Market {i+1}:")
                    print(f"     ID: {market.get('id', 'N/A')}")
                    print(f"     Question: {market.get('question', 'N/A')}")
                    print(f"     Active: {market.get('active', 'N/A')}")
                    print(f"     Start Date: {market.get('startDate', 'N/A')}")
                    print(f"     End Date: {market.get('endDate', 'N/A')}")
                    print(f"     Outcomes: {market.get('outcomes', 'N/A')}")
                    print(f"     Outcome Prices: {market.get('outcomePrices', 'N/A')}")

                    # Check duration
                    start_str = market.get('startDate')
                    end_str = market.get('endDate')

                    if start_str and end_str:
                        try:
                            if "T" in str(start_str):
                                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                                end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                            else:
                                start = datetime.fromtimestamp(int(start_str) / 1000, tz=timezone.utc)
                                end = datetime.fromtimestamp(int(end_str) / 1000, tz=timezone.utc)

                            duration_min = (end - start).total_seconds() / 60
                            print(f"     Duration: {duration_min:.1f} minutes")

                            if 14 <= duration_min <= 16:
                                print("     ✅ 15-minute market!")
                            else:
                                print("     ❌ Not 15-minute")
                        except Exception as e:
                            print(f"     ❌ Duration parsing error: {e}")

        else:
            print(f"   Unexpected response format: {data}")

    except Exception as e:
        print(f"❌ API call failed: {e}")

if __name__ == "__main__":
    test_polymarket_api()
