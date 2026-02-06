#!/usr/bin/env python3
"""
Enable CLOB Trading on Polymarket

This script helps you enable CLOB (API) trading by approving USDC for the exchange.
Run this if your CLOB balance shows $0 but you have funds in your wallet.
"""

import os
from dotenv import load_dotenv

load_dotenv()

def main():
    from py_clob_client.client import ClobClient
    
    private_key = os.getenv('WALLET_PRIVATE_KEY')
    if not private_key:
        print("ERROR: WALLET_PRIVATE_KEY not found in .env file")
        return
    
    print("=" * 50)
    print("POLYMARKET CLOB TRADING SETUP")
    print("=" * 50)
    print()
    
    # Initialize client
    client = ClobClient(
        host='https://clob.polymarket.com',
        chain_id=137,
        key=private_key,
    )
    
    # Get API credentials
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    
    print(f"Wallet Address: {client.get_address()}")
    print()
    
    # Check current allowance
    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
    
    try:
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        result = client.get_balance_allowance(params)
        print(f"Current CLOB Balance: ${int(result.get('balance', 0)) / 1_000_000:.2f} USDC")
        
        allowances = result.get('allowances', {})
        has_allowance = any(int(v) > 0 for v in allowances.values())
        print(f"USDC Approved for Trading: {'Yes' if has_allowance else 'No'}")
        print()
        
        if not has_allowance:
            print("=" * 50)
            print("NEXT STEPS:")
            print("=" * 50)
            print()
            print("Your wallet needs USDC approved for CLOB trading.")
            print()
            print("Option 1 - Via Polymarket Website (EASIEST):")
            print("  1. Go to https://polymarket.com")
            print("  2. Connect your wallet")
            print("  3. Go to Wallet/Deposit")
            print("  4. Look for 'Enable API Trading' or similar")
            print()
            print("Option 2 - Transfer funds from Web Exchange to CLOB:")
            print("  1. On Polymarket website, go to Wallet")
            print("  2. Look for 'Transfer to API' option")
            print("  3. Transfer your $10 to the CLOB system")
            print()
            print("Option 3 - Direct Polygon USDC deposit:")
            print("  1. Send USDC on Polygon network to your wallet")
            print("  2. The bot will detect and use it")
        else:
            print("=" * 50)
            print("STATUS: Ready to trade!")
            print("=" * 50)
            if int(result.get('balance', 0)) == 0:
                print()
                print("NOTE: You have USDC approved but $0 balance.")
                print("Transfer funds from the Polymarket website or")
                print("deposit USDC to your wallet on Polygon network.")
                
    except Exception as e:
        print(f"Error checking balance: {e}")

if __name__ == "__main__":
    main()
