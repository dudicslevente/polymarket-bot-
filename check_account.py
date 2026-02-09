#!/usr/bin/env python3
"""
Check Polymarket Account Status

This script helps you:
1. View your current USDC balance
2. View all open positions (shares you hold)
3. View your recent trade history
4. Identify any unredeemed winning positions

Use this to debug issues or recover trade history that wasn't logged.

Usage:
    python check_account.py
"""

import os
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Dict, List, Any

# Load environment
load_dotenv()

# Configuration
CLOB_API_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"  # Correct API for positions
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")


def get_usdc_balance() -> Optional[float]:
    """Get USDC balance from CLOB API."""
    try:
        # For balance, we need authentication
        # Simplified version using Gamma API
        if not WALLET_ADDRESS:
            print("❌ WALLET_ADDRESS not set in .env")
            return None
        
        # The balance is part of the positions data in Gamma
        # For a simpler check, you can view on Polymarket UI
        print(f"ℹ️ To check your exact USDC balance, visit:")
        print(f"   https://polymarket.com/portfolio")
        print(f"   Or check on Polygonscan:")
        print(f"   https://polygonscan.com/address/{WALLET_ADDRESS}")
        return None
        
    except Exception as e:
        print(f"❌ Error fetching balance: {e}")
        return None


def get_positions() -> List[Dict]:
    """Get all positions from Polymarket Data API."""
    if not WALLET_ADDRESS:
        print("❌ WALLET_ADDRESS not set in .env")
        return []
    
    try:
        # Use the data-api which has the positions endpoint
        url = f"{DATA_API_URL}/positions"
        params = {"user": WALLET_ADDRESS.lower()}
        
        print(f"📡 Fetching positions for {WALLET_ADDRESS[:10]}...")
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 404:
            print("⚠️ No positions found (or endpoint not available)")
            return []
        
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "positions" in data:
            return data["positions"]
        else:
            return []
            
    except requests.exceptions.HTTPError as e:
        print(f"⚠️ HTTP Error: {e}")
        return []
    except Exception as e:
        print(f"❌ Error fetching positions: {e}")
        return []


def get_positions_from_activity() -> List[Dict]:
    """Fallback: Get positions from activity endpoint."""
    if not WALLET_ADDRESS:
        return []
    
    try:
        url = f"{GAMMA_API_URL}/activity"
        params = {"user": WALLET_ADDRESS.lower(), "limit": 100}
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        activities = response.json()
        
        # Extract unique positions from activities
        positions_map = {}
        
        for act in activities:
            token_id = act.get("asset_id") or act.get("token_id")
            if not token_id:
                continue
            
            if token_id not in positions_map:
                market_info = act.get("market", {})
                positions_map[token_id] = {
                    "token_id": token_id,
                    "market_question": market_info.get("question", "Unknown"),
                    "outcome": act.get("outcome") or act.get("side", "Unknown"),
                    "activities": []
                }
            
            positions_map[token_id]["activities"].append({
                "type": act.get("type"),
                "side": act.get("side"),
                "size": act.get("size"),
                "price": act.get("price"),
                "timestamp": act.get("timestamp")
            })
        
        return list(positions_map.values())
        
    except Exception as e:
        print(f"❌ Error fetching activity: {e}")
        return []


def get_recent_activity(limit: int = 20) -> List[Dict]:
    """Get recent account activity from Gamma API."""
    if not WALLET_ADDRESS:
        print("❌ WALLET_ADDRESS not set in .env")
        return []
    
    try:
        url = f"{GAMMA_API_URL}/activity"
        params = {"user": WALLET_ADDRESS.lower(), "limit": limit}
        
        print(f"📡 Fetching recent activity...")
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 404:
            print("⚠️ Activity endpoint not available, trying trades...")
            return get_recent_trades(limit)
        
        response.raise_for_status()
        return response.json() if isinstance(response.json(), list) else []
        
    except Exception as e:
        print(f"⚠️ Error fetching activity: {e}")
        return get_recent_trades(limit)


def get_recent_trades(limit: int = 20) -> List[Dict]:
    """Get recent trades from CLOB API (requires authentication)."""
    # This would need L2 auth, so we'll show instructions instead
    print(f"\nℹ️ To view your complete trade history:")
    print(f"   1. Visit https://polymarket.com/portfolio")
    print(f"   2. Click on 'Activity' or 'History'")
    print(f"   3. Or check Polygonscan for transactions:")
    print(f"      https://polygonscan.com/address/{WALLET_ADDRESS}")
    return []


def format_position(pos: Dict) -> str:
    """Format a position for display."""
    lines = []
    
    # Handle data-api format
    title = pos.get("title") or "Unknown Market"
    outcome = pos.get("outcome") or pos.get("side", "N/A")
    size = float(pos.get("size") or 0)
    avg_price = float(pos.get("avgPrice") or pos.get("avg_price") or 0)
    current_value = float(pos.get("currentValue") or pos.get("current_value") or 0)
    cash_pnl = float(pos.get("cashPnl") or pos.get("cash_pnl") or 0)
    percent_pnl = float(pos.get("percentPnl") or pos.get("percent_pnl") or 0)
    redeemable = pos.get("redeemable", False)
    cur_price = float(pos.get("curPrice") or pos.get("current_price") or 0)
    
    # Determine status
    if redeemable and cur_price == 1:
        status = "✅ WON - REDEEMABLE"
    elif redeemable and cur_price == 0:
        status = "❌ LOST - RESOLVED"
    elif redeemable:
        status = "🔄 REDEEMABLE"
    else:
        status = "⏳ PENDING"
    
    lines.append(f"  📊 {title[:60]}...")
    lines.append(f"     Outcome: {outcome}")
    lines.append(f"     Shares: {size:.4f}")
    lines.append(f"     Avg Price: ${avg_price:.4f}")
    lines.append(f"     Cost Basis: ${size * avg_price:.2f}")
    lines.append(f"     Current Value: ${current_value:.2f}")
    
    # P&L formatting
    pnl_sign = "+" if cash_pnl >= 0 else ""
    lines.append(f"     P&L: {pnl_sign}${cash_pnl:.2f} ({pnl_sign}{percent_pnl:.1f}%)")
    lines.append(f"     Status: {status}")
    
    return "\n".join(lines)


def format_activity(act: Dict) -> str:
    """Format an activity for display."""
    market = act.get("market", {})
    question = market.get("question", "Unknown")[:40]
    act_type = act.get("type", "unknown")
    side = act.get("side", "N/A")
    size = act.get("size", 0)
    price = act.get("price", 0)
    timestamp = act.get("timestamp", "N/A")
    
    # Format timestamp
    if timestamp and timestamp != "N/A":
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp = dt.strftime("%Y-%m-%d %H:%M")
        except:
            pass
    
    return f"  [{timestamp}] {act_type.upper():10} {side:4} {size:>10} @ ${price:.4f}  | {question}..."


def main():
    """Main entry point."""
    print("\n" + "="*70)
    print("📊 POLYMARKET ACCOUNT CHECK")
    print("="*70)
    
    if not WALLET_ADDRESS:
        print("\n❌ ERROR: WALLET_ADDRESS not set in .env file")
        print("   Please set your wallet address to check your account.")
        sys.exit(1)
    
    print(f"\n🔑 Wallet: {WALLET_ADDRESS}")
    
    # Get balance info
    print("\n" + "-"*50)
    print("💰 BALANCE")
    print("-"*50)
    get_usdc_balance()
    
    # Get positions
    print("\n" + "-"*50)
    print("📋 OPEN POSITIONS")
    print("-"*50)
    
    positions = get_positions()
    
    # Calculate summary stats
    total_redeemable_value = 0
    total_wins = 0
    total_losses = 0
    total_invested = 0
    total_pnl = 0
    
    if positions:
        print(f"\nFound {len(positions)} position(s):\n")
        for i, pos in enumerate(positions, 1):
            print(f"\n{i}. " + "-"*40)
            print(format_position(pos))
            
            # Accumulate stats
            redeemable = pos.get("redeemable", False)
            cur_price = float(pos.get("curPrice") or pos.get("current_price") or 0)
            current_value = float(pos.get("currentValue") or pos.get("current_value") or 0)
            initial_value = float(pos.get("initialValue") or pos.get("initial_value") or 0)
            cash_pnl = float(pos.get("cashPnl") or pos.get("cash_pnl") or 0)
            
            total_invested += initial_value
            total_pnl += cash_pnl
            
            if redeemable and cur_price == 1:
                total_redeemable_value += current_value
                total_wins += 1
            elif redeemable and cur_price == 0:
                total_losses += 1
        
        # Print summary
        print("\n" + "="*50)
        print("📈 POSITION SUMMARY")
        print("="*50)
        print(f"  Total Positions: {len(positions)}")
        print(f"  Wins: {total_wins} | Losses: {total_losses}")
        print(f"  Total Invested: ${total_invested:.2f}")
        pnl_sign = "+" if total_pnl >= 0 else ""
        print(f"  Total P&L: {pnl_sign}${total_pnl:.2f}")
        
        if total_redeemable_value > 0:
            print(f"\n  💰 REDEEMABLE WINNINGS: ${total_redeemable_value:.2f}")
            print(f"     → Visit https://polymarket.com/portfolio to redeem!")
            print(f"     (Note: Redemption happens on-chain, not via API)")
    else:
        print("\nNo open positions found.")
        print("(Positions may be auto-redeemed after markets resolve)")
    
    # Get recent activity
    print("\n" + "-"*50)
    print("📜 RECENT ACTIVITY")
    print("-"*50)
    
    activities = get_recent_activity(20)
    
    if activities:
        print(f"\nLast {len(activities)} activities:\n")
        for act in activities:
            print(format_activity(act))
    else:
        print("\nNo recent activity found via API.")
    
    # Summary
    print("\n" + "="*70)
    print("📌 HELPFUL LINKS")
    print("="*70)
    print(f"\n  Portfolio: https://polymarket.com/portfolio")
    print(f"  Polygonscan: https://polygonscan.com/address/{WALLET_ADDRESS}")
    print(f"  USDC.e Token: https://polygonscan.com/token/0x2791bca1f2de4661ed88a30c99a7a9449aa84174?a={WALLET_ADDRESS}")
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
