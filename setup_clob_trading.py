#!/usr/bin/env python3
"""
POLYMARKET CLOB TRADING SETUP

This script sets up your wallet for CLOB API trading by:
1. Setting token allowances (approving USDC and CTF for the exchange contracts)
2. Checking your balances

REQUIREMENTS:
- POL (formerly MATIC) in your wallet for gas fees (~0.5 POL should be enough)
- USDC.e on Polygon in your wallet for trading
  IMPORTANT: Use USDC.e (0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174), NOT regular USDC!

HOW TO GET USDC.e INTO YOUR WALLET:
1. On Polymarket website, go to your Portfolio/Wallet
2. Click "Withdraw" 
3. Withdraw USDC to your wallet address: 0x7cB0618b6BA21cD0E09c8e8F9A80E8833090C084
4. This will give you USDC.e that the CLOB API can use

NOTE: The $10 you have on Polymarket website is in a PROXY wallet, not directly 
accessible by the CLOB API. You need to withdraw it to your EOA wallet first.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

def check_requirements():
    """Check if required packages are installed."""
    try:
        from web3 import Web3
        from web3.constants import MAX_INT
        from web3.middleware import ExtraDataToPOAMiddleware
        return True
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("Install with: pip install web3")
        return False

def get_balances(web3, wallet_address):
    """Check POL and USDC.e balances."""
    # USDC.e contract
    usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    usdc_abi = '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]'
    
    usdc = web3.eth.contract(address=web3.to_checksum_address(usdc_address), abi=usdc_abi)
    
    pol_balance = web3.eth.get_balance(wallet_address)
    usdc_balance = usdc.functions.balanceOf(wallet_address).call()
    
    return {
        'pol': web3.from_wei(pol_balance, 'ether'),
        'usdc': usdc_balance / 1_000_000  # USDC has 6 decimals
    }

def set_allowances(dry_run=False):
    """Set token allowances for Polymarket CLOB trading."""
    from web3 import Web3
    from web3.constants import MAX_INT
    from web3.middleware import ExtraDataToPOAMiddleware
    
    # Configuration
    rpc_url = "https://polygon-rpc.com"
    priv_key = os.getenv('WALLET_PRIVATE_KEY')
    pub_key = os.getenv('WALLET_ADDRESS')
    chain_id = 137
    
    if not priv_key or not pub_key:
        print("ERROR: WALLET_PRIVATE_KEY and WALLET_ADDRESS must be set in .env file")
        return False
    
    # Contract ABIs
    erc20_approve = """[{"constant": false,"inputs": [{"name": "_spender","type": "address" },{ "name": "_value", "type": "uint256" }],"name": "approve","outputs": [{ "name": "", "type": "bool" }],"payable": false,"stateMutability": "nonpayable","type": "function"}]"""
    erc1155_set_approval = """[{"inputs": [{ "internalType": "address", "name": "operator", "type": "address" },{ "internalType": "bool", "name": "approved", "type": "bool" }],"name": "setApprovalForAll","outputs": [],"stateMutability": "nonpayable","type": "function"}]"""
    
    # Token addresses
    usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
    ctf_address = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"   # Conditional Tokens
    
    # Exchange contracts to approve
    exchanges = [
        ("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", "CTF Exchange"),
        ("0xC5d563A36AE78145C45a50134d48A1215220f80a", "Neg Risk CTF Exchange"),
        ("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296", "Neg Risk Adapter"),
    ]
    
    print("=" * 60)
    print("POLYMARKET CLOB TRADING SETUP")
    print("=" * 60)
    print()
    
    # Connect to Polygon
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    
    if not web3.is_connected():
        print("ERROR: Could not connect to Polygon network")
        return False
    
    pub_key = web3.to_checksum_address(pub_key)
    print(f"Wallet Address: {pub_key}")
    print()
    
    # Check balances
    balances = get_balances(web3, pub_key)
    print(f"POL Balance: {balances['pol']:.4f} POL (for gas)")
    print(f"USDC.e Balance: ${balances['usdc']:.2f} (for trading)")
    print()
    
    if balances['pol'] < 0.01:
        print("⚠️  WARNING: You need POL for gas fees!")
        print("   Send at least 0.5 POL to your wallet")
        print()
    
    if balances['usdc'] < 1:
        print("⚠️  WARNING: You have very little USDC.e!")
        print("   Withdraw USDC from Polymarket website to your wallet")
        print()
    
    if dry_run:
        print("DRY RUN MODE - Not executing transactions")
        print()
        print("Would approve the following:")
        for exchange_addr, exchange_name in exchanges:
            print(f"  - USDC.e for {exchange_name}")
            print(f"  - CTF for {exchange_name}")
        return True
    
    # Create contract instances
    usdc = web3.eth.contract(address=web3.to_checksum_address(usdc_address), abi=erc20_approve)
    ctf = web3.eth.contract(address=web3.to_checksum_address(ctf_address), abi=erc1155_set_approval)
    
    def send_and_wait(raw_tx, description, retries=3):
        """Sign and send a transaction, wait for receipt."""
        import time
        for attempt in range(retries):
            try:
                signed_tx = web3.eth.account.sign_transaction(raw_tx, private_key=priv_key)
                tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
                print(f"  Sent: {tx_hash.hex()[:20]}...")
                receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                if receipt.status == 1:
                    print(f"  ✅ {description} - Success!")
                    return True
                else:
                    print(f"  ❌ {description} - Failed!")
                    return False
            except Exception as e:
                error_msg = str(e)
                if 'rate limit' in error_msg.lower() or '-32090' in error_msg:
                    wait_time = 15 * (attempt + 1)
                    print(f"  ⏳ Rate limited, waiting {wait_time}s... (attempt {attempt + 1}/{retries})")
                    time.sleep(wait_time)
                else:
                    print(f"  ❌ {description} - Error: {e}")
                    return False
        print(f"  ❌ {description} - Failed after {retries} retries")
        return False
    
    print("Setting allowances (6 transactions)...")
    print("Note: Adding delays between transactions to avoid rate limits")
    print()
    
    import time
    success_count = 0
    nonce = web3.eth.get_transaction_count(pub_key)
    
    for i, (exchange_addr, exchange_name) in enumerate(exchanges):
        print(f"📋 {exchange_name}:")
        
        # USDC.e approve
        try:
            raw_tx = usdc.functions.approve(
                exchange_addr, int(MAX_INT, 0)
            ).build_transaction({
                "chainId": chain_id,
                "from": pub_key,
                "nonce": nonce,
                "gasPrice": web3.eth.gas_price
            })
            if send_and_wait(raw_tx, "USDC.e approve"):
                success_count += 1
            nonce += 1
            time.sleep(5)  # Wait between transactions
        except Exception as e:
            print(f"  ❌ USDC.e approve error: {e}")
        
        # CTF setApprovalForAll
        try:
            raw_tx = ctf.functions.setApprovalForAll(
                exchange_addr, True
            ).build_transaction({
                "chainId": chain_id,
                "from": pub_key,
                "nonce": nonce,
                "gasPrice": web3.eth.gas_price
            })
            if send_and_wait(raw_tx, "CTF approve"):
                success_count += 1
            nonce += 1
            time.sleep(5)  # Wait between transactions
        except Exception as e:
            print(f"  ❌ CTF approve error: {e}")
        
        print()
        
        # Extra delay between exchange approvals
        if i < len(exchanges) - 1:
            print("  ⏳ Waiting 10s before next exchange...")
            time.sleep(10)
    
    print("=" * 60)
    print(f"COMPLETE: {success_count}/6 approvals successful")
    print("=" * 60)
    
    if success_count == 6:
        print()
        print("✅ Your wallet is now set up for CLOB trading!")
        print()
        print("NEXT STEPS:")
        print("1. Make sure you have USDC.e in your wallet")
        print("   (Withdraw from Polymarket website if needed)")
        print("2. Run the bot: python3 main.py")
    else:
        print()
        print("⚠️  Some approvals failed. Check your POL balance and try again.")
    
    return success_count == 6

def check_clob_status():
    """Check current CLOB balance and allowance status."""
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        
        private_key = os.getenv('WALLET_PRIVATE_KEY')
        if not private_key:
            print("ERROR: WALLET_PRIVATE_KEY not set")
            return
        
        client = ClobClient(
            host='https://clob.polymarket.com',
            chain_id=137,
            key=private_key,
        )
        client.set_api_creds(client.create_or_derive_api_creds())
        
        print("=" * 60)
        print("CLOB STATUS CHECK")
        print("=" * 60)
        print()
        print(f"Wallet: {client.get_address()}")
        print()
        
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        result = client.get_balance_allowance(params)
        
        balance = int(result.get('balance', 0)) / 1_000_000
        print(f"CLOB Balance: ${balance:.2f} USDC")
        print()
        
        print("Allowances:")
        allowances = result.get('allowances', {})
        exchange_names = {
            '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E': 'CTF Exchange',
            '0xC5d563A36AE78145C45a50134d48A1215220f80a': 'Neg Risk CTF Exchange', 
            '0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296': 'Neg Risk Adapter',
        }
        
        all_approved = True
        for addr, amount in allowances.items():
            name = exchange_names.get(addr, addr[:20] + "...")
            approved = int(amount) > 0
            status = "✅ Approved" if approved else "❌ Not approved"
            print(f"  {name}: {status}")
            if not approved:
                all_approved = False
        
        print()
        if balance > 0 and all_approved:
            print("✅ Ready to trade!")
        elif not all_approved:
            print("❌ Run 'python3 setup_clob_trading.py approve' to set allowances")
        elif balance == 0:
            print("❌ No CLOB balance. Withdraw USDC from Polymarket website to your wallet.")
            
    except Exception as e:
        print(f"Error checking CLOB status: {e}")

def main():
    if not check_requirements():
        return
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == 'approve':
            set_allowances(dry_run=False)
        elif command == 'dry-run':
            set_allowances(dry_run=True)
        elif command == 'status':
            check_clob_status()
        else:
            print(f"Unknown command: {command}")
            print("Usage: python3 setup_clob_trading.py [approve|dry-run|status]")
    else:
        print("POLYMARKET CLOB TRADING SETUP")
        print("=" * 40)
        print()
        print("Commands:")
        print("  python3 setup_clob_trading.py status   - Check current status")
        print("  python3 setup_clob_trading.py dry-run  - Preview what will be done")
        print("  python3 setup_clob_trading.py approve  - Set allowances (requires POL for gas)")
        print()
        
        # Show status by default
        check_clob_status()

if __name__ == "__main__":
    main()
