#!/usr/bin/env python3
"""
POLYMARKET POSITION REDEMPTION SCRIPT

This script redeems all winning positions by calling the CTF contract
on Polygon. After a market resolves, winning shares can be exchanged
for pUSD on-chain.

REQUIREMENTS:
- POL in wallet for gas fees (~0.01-0.05 POL per redemption)
- Winning positions to redeem
- WALLET_PRIVATE_KEY set in .env

USAGE:
    python3 redeem_positions.py           # Check positions and redeem
    python3 redeem_positions.py --dry-run # Just check, don't redeem
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from market import PolymarketClient


def main():
    """Main entry point for redemption script."""
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    
    print("\n" + "="*70)
    print("💰 POLYMARKET POSITION REDEMPTION")
    print("="*70)
    
    wallet = os.getenv("WALLET_ADDRESS")
    if not wallet:
        print("\n❌ ERROR: WALLET_ADDRESS not set in .env")
        sys.exit(1)
    
    print(f"\n🔑 Wallet: {wallet}")
    
    # Check for private key (needed for on-chain redemption)
    private_key = os.getenv("WALLET_PRIVATE_KEY")
    if not private_key:
        print("\n⚠️ WARNING: WALLET_PRIVATE_KEY not set")
        print("   On-chain redemption requires your private key.")
        print("   Manual redemption link will be provided instead.")
    
    # Initialize client (set TEST_MODE=False for real redemption)
    config.TEST_MODE = False
    client = PolymarketClient()
    
    # Get current positions
    print("\n" + "-"*50)
    print("📋 CHECKING POSITIONS")
    print("-"*50)
    
    positions = client.get_open_positions(for_redemption=True)
    
    if positions is None:
        print("\n⚠️ Could not fetch positions from Polymarket Data API.")
        print("   No redemption transaction was attempted. Please retry in a moment.")
        return

    if not positions:
        print("\n✅ No positions found. Nothing to redeem!")
        return
    
    # Find winning positions. The data-api returns curPrice=null for many
    # resolved markets (e.g. 15-minute Bitcoin Up/Down), so current_price
    # parses to 0.0 and misses real winners. A true winner needs BOTH:
    #   - redeemable is True : the market has resolved (NOT just live).
    #     redeemable=False means unresolved — redeeming it reverts on-chain.
    #   - current_value > 0.01: the position resolved IN OUR FAVOR.
    #     Losers are also marked redeemable=True but have value 0.
    winning_positions = []
    for pos in positions:
        shares = pos.get("size", 0)
        cur_price = pos.get("current_price", 0)
        cur_value = pos.get("current_value", 0)
        redeemable = pos.get("redeemable")
        is_winner = (redeemable is True and cur_value > 0.01) or cur_price >= 0.90
        if is_winner and shares > 0:
            winning_positions.append(pos)
    
    if not winning_positions:
        print("\n✅ No winning positions to redeem.")
        print("   (Positions either already redeemed or market not yet resolved)")
        return
    
    # Display winning positions
    print(f"\n💰 Found {len(winning_positions)} winning position(s):\n")
    
    total_value = 0.0
    for i, pos in enumerate(winning_positions, 1):
        token_id = pos.get("token_id", "")[:16]
        shares = pos.get("size", 0)
        title = pos.get("title", "Unknown")[:50]
        condition_id = pos.get("condition_id", "N/A")
        # Use the API's current_value (authoritative mark-to-market) when
        # available; fall back to shares*price for markets that report a price.
        cur_value = pos.get("current_value", 0)
        cur_price = pos.get("current_price", 0)
        value = cur_value if cur_value > 0 else shares * cur_price
        total_value += value
        
        print(f"  {i}. {title}...")
        print(f"     Shares: {shares:.4f}")
        print(f"     Value: ${value:.2f}")
        print(f"     Token: {token_id}...")
        print(f"     Condition: {condition_id[:16] if condition_id else 'N/A'}...")
        print()
    
    print(f"  📊 Total redeemable value: ${total_value:.2f}")
    
    if dry_run:
        print("\n🔍 DRY RUN MODE - No redemption will be attempted")
        print("   Run without --dry-run to redeem positions.")
        return
    
    # Confirm redemption
    print("\n" + "-"*50)
    print("⚠️ REDEMPTION CONFIRMATION")
    print("-"*50)
    print(f"\nYou are about to redeem ${total_value:.2f} worth of positions into pUSD.")
    print("This will execute blockchain transactions (requires gas).\n")
    
    confirm = input("Type 'REDEEM' to proceed: ")
    
    if confirm.strip().upper() != "REDEEM":
        print("\n❌ Redemption cancelled.")
        return
    
    # Execute redemption
    print("\n" + "-"*50)
    print("🔄 EXECUTING REDEMPTIONS")
    print("-"*50)
    
    result = client.redeem_all_winning_positions()
    
    # Summary
    print("\n" + "="*70)
    print("📊 REDEMPTION COMPLETE")
    print("="*70)
    
    if result.get("onchain_redeemed", 0) > 0:
        print(f"\n✅ Successfully redeemed: ${result.get('total_redeemed', 0):.2f}")
    
    if result.get("needs_manual_redemption", 0) > 0:
        print(f"\n⚠️ Manual redemption required for {result.get('needs_manual_redemption')} position(s)")
        print("   👉 Visit: https://polymarket.com/portfolio")
    
    if result.get("already_redeemed", 0) > 0:
        print(f"\nℹ️ {result.get('already_redeemed')} position(s) were already redeemed")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
