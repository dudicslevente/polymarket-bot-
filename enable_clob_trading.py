#!/usr/bin/env python3
"""
Enable CLOB Trading on Polymarket

Compatibility helper for CLOB setup checks.

Polymarket now uses pUSD as CLOB trading collateral. For wrapping and actual
allowance transactions, use setup_clob_trading.py.
"""

import os
from dotenv import load_dotenv

load_dotenv()

def main():
    from py_clob_client_v2 import ClobClient
    
    private_key = os.getenv('WALLET_PRIVATE_KEY')
    if not private_key:
        print("ERROR: WALLET_PRIVATE_KEY not found in .env file")
        return
    
    print("=" * 50)
    print("POLYMARKET CLOB TRADING SETUP")
    print("=" * 50)
    print()
    
    signature_type = int(os.getenv('POLYMARKET_SIGNATURE_TYPE', '0'))
    funder = (
        os.getenv('POLYMARKET_FUNDER_ADDRESS')
        or os.getenv('POLYMARKET_DEPOSIT_WALLET_ADDRESS')
        or os.getenv('DEPOSIT_WALLET_ADDRESS')
        or os.getenv('WALLET_ADDRESS')
    )

    # Initialize client
    client = ClobClient(
        host='https://clob.polymarket.com',
        chain_id=137,
        key=private_key,
        signature_type=signature_type,
        funder=funder,
    )
    
    # Get API credentials
    creds = client.derive_api_key()
    client.set_api_creds(creds)
    
    print(f"Wallet Address: {client.get_address()}")
    print()
    
    # Check current allowance
    from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
    
    try:
        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=signature_type,
        )
        try:
            client.update_balance_allowance(params)
        except Exception:
            pass
        result = client.get_balance_allowance(params)
        print(f"Current CLOB Balance: ${int(result.get('balance', 0)) / 1_000_000:.2f} pUSD")
        print(f"Signature Type: {signature_type}")
        print(f"Funder: {funder or 'N/A'}")
        
        allowances = result.get('allowances', {})
        has_allowance = any(int(v) > 0 for v in allowances.values())
        print(f"pUSD Approved for Trading: {'Yes' if has_allowance else 'No'}")
        print()
        
        if not has_allowance:
            print("=" * 50)
            print("NEXT STEPS:")
            print("=" * 50)
            print()
            print("Your wallet needs pUSD/CTF approvals for CLOB trading.")
            print()
            print("Option 1 - Via Polymarket Website (EASIEST):")
            print("  1. Go to https://polymarket.com")
            print("  2. Connect your wallet")
            print("  3. Go to Wallet/Deposit")
            print("  4. Look for 'Enable API Trading' or similar")
            print()
            print("Option 2 - Transfer funds from Polymarket to CLOB:")
            print("  1. On Polymarket website, go to Wallet")
            print("  2. Look for 'Transfer to API' or similar")
            print("  3. Transfer pUSD into the CLOB wallet/funder")
            print()
            print("Option 3 - Direct Polygon setup:")
            print("  1. Hold pUSD in your configured funder wallet")
            print("  2. Run: python3 setup_clob_trading.py approve")
        else:
            print("=" * 50)
            print("STATUS: Ready to trade!")
            print("=" * 50)
            if int(result.get('balance', 0)) == 0:
                print()
                print("NOTE: You have approvals but $0 pUSD CLOB balance.")
                print("Transfer funds into the Polymarket CLOB wallet/funder or")
                print("wrap legacy USDC.e with: python3 setup_clob_trading.py wrap all")
                
    except Exception as e:
        print(f"Error checking balance: {e}")

if __name__ == "__main__":
    main()
