#!/usr/bin/env python3
"""
POLYMARKET CLOB TRADING SETUP

This script sets up your wallet for CLOB API trading by:
1. Wrapping legacy USDC.e into pUSD when needed
2. Setting token allowances (approving pUSD and CTF for the exchange contracts)
3. Checking your balances

REQUIREMENTS:
- POL (formerly MATIC) in your wallet for gas fees (~0.5 POL should be enough)
- pUSD on Polygon in your wallet for trading
  Legacy USDC.e must be wrapped into pUSD before the CLOB reports buying power.

HOW TO MIGRATE LEGACY USDC.e:
1. Keep USDC.e on Polygon in your bot wallet
2. Run: python3 setup_clob_trading.py wrap all
3. Run: python3 setup_clob_trading.py approve
"""

import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

USDCE_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
PUSD_ADDRESS = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
NATIVE_USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
COLLATERAL_ONRAMP_ADDRESS = "0x93070a847efEf7F70739046A929D47a521F5B8ee"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

EXCHANGES = [
    ("0xE111180000d2663C0091e4f400237545B87B996B", "CTF Exchange V2"),
    ("0xe2222d279d744050d28e00520010520000310F59", "Neg Risk CTF Exchange V2"),
    ("0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296", "Neg Risk Adapter"),
]

ERC20_ABI = """[
{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},
{"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"remaining","type":"uint256"}],"type":"function"}
]"""

ERC1155_SET_APPROVAL_ABI = """[
{"inputs":[{"internalType":"address","name":"operator","type":"address"},{"internalType":"bool","name":"approved","type":"bool"}],"name":"setApprovalForAll","outputs":[],"stateMutability":"nonpayable","type":"function"},
{"inputs":[{"internalType":"address","name":"account","type":"address"},{"internalType":"address","name":"operator","type":"address"}],"name":"isApprovedForAll","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"view","type":"function"}
]"""

ONRAMP_ABI = """[{"inputs":[{"internalType":"address","name":"_asset","type":"address"},{"internalType":"address","name":"_to","type":"address"},{"internalType":"uint256","name":"_amount","type":"uint256"}],"name":"wrap","outputs":[],"stateMutability":"nonpayable","type":"function"}]"""

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

def connect_polygon():
    """Connect to Polygon using configured RPC plus public fallbacks."""
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware
    import config

    rpc_urls = [
        config.POLYGON_RPC_URL,
        "https://polygon-bor-rpc.publicnode.com",
        "https://polygon-rpc.com",
        "https://rpc.ankr.com/polygon",
    ]
    for rpc_url in [url for url in rpc_urls if url]:
        candidate = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
        candidate.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        if candidate.is_connected():
            print(f"Connected to Polygon RPC: {rpc_url}")
            return candidate

    print("ERROR: Could not connect to Polygon network")
    print("Tried:")
    for rpc_url in [url for url in rpc_urls if url]:
        print(f"  - {rpc_url}")
    return None

def get_balances(web3, wallet_address):
    """Check POL, pUSD, USDC.e, and native USDC balances."""
    tokens = {
        "pusd": PUSD_ADDRESS,
        "usdce": USDCE_ADDRESS,
        "native_usdc": NATIVE_USDC_ADDRESS,
    }

    pol_balance = web3.eth.get_balance(wallet_address)
    balances = {
        'pol': web3.from_wei(pol_balance, 'ether'),
    }
    for name, address in tokens.items():
        token = web3.eth.contract(address=web3.to_checksum_address(address), abi=ERC20_ABI)
        balances[name] = token.functions.balanceOf(wallet_address).call() / 1_000_000
    return balances

def send_and_wait(web3, raw_tx, private_key, description, retries=3):
    """Sign and send a transaction, wait for receipt."""
    import time
    for attempt in range(retries):
        try:
            signed_tx = web3.eth.account.sign_transaction(raw_tx, private_key=private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            print(f"  Sent: {tx_hash.hex()[:20]}...")
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            if receipt.status == 1:
                print(f"  ✅ {description} - Success!")
                return True
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

def set_allowances(dry_run=False):
    """Set token allowances for Polymarket CLOB trading."""
    from web3.constants import MAX_INT
    
    priv_key = os.getenv('WALLET_PRIVATE_KEY')
    pub_key = os.getenv('WALLET_ADDRESS')
    funder = (
        os.getenv('POLYMARKET_FUNDER_ADDRESS')
        or os.getenv('POLYMARKET_DEPOSIT_WALLET_ADDRESS')
        or os.getenv('DEPOSIT_WALLET_ADDRESS')
        or pub_key
    )
    signature_type = int(os.getenv('POLYMARKET_SIGNATURE_TYPE', '0'))
    chain_id = 137
    
    if not priv_key or not pub_key:
        print("ERROR: WALLET_PRIVATE_KEY and WALLET_ADDRESS must be set in .env file")
        return False
    
    print("=" * 60)
    print("POLYMARKET CLOB TRADING SETUP")
    print("=" * 60)
    print()
    
    web3 = connect_polygon()
    if web3 is None:
        return False
    
    pub_key = web3.to_checksum_address(pub_key)
    funder = web3.to_checksum_address(funder) if funder else pub_key
    print(f"Wallet Address: {pub_key}")
    if funder != pub_key:
        print(f"Funder Address: {funder}")
    print()

    if funder != pub_key or signature_type == 3:
        print("⚠️  This direct approval helper only works when the signer wallet owns the funds.")
        print("   Your configuration uses a funder/deposit wallet, so approvals must be made")
        print("   from that wallet via Polymarket's deposit-wallet/relayer flow or website.")
        print("   The bot will still use this funder for CLOB trading once it is approved.")
        return False
    
    # Check balances
    balances = get_balances(web3, pub_key)
    print(f"POL Balance: {balances['pol']:.4f} POL (for gas)")
    print(f"pUSD Balance: ${balances['pusd']:.2f} (CLOB trading collateral)")
    print(f"USDC.e Balance: ${balances['usdce']:.2f} (legacy, wrap before trading)")
    print(f"Native USDC Balance: ${balances['native_usdc']:.2f}")
    print()
    
    if balances['pol'] < 0.01:
        print("⚠️  WARNING: You need POL for gas fees!")
        print("   Send at least 0.5 POL to your wallet")
        print()
    
    if balances['pusd'] < 1 and balances['usdce'] > 0:
        print("⚠️  WARNING: Your funds are still USDC.e, not pUSD.")
        print("   Run: python3 setup_clob_trading.py wrap all")
        print()
    elif balances['pusd'] < 1:
        print("⚠️  WARNING: You have very little pUSD!")
        print("   Deposit through Polymarket or wrap USDC.e into pUSD.")
        print()
    
    if dry_run:
        print("DRY RUN MODE - Not executing transactions")
        print()
        print("Would approve the following:")
        for exchange_addr, exchange_name in EXCHANGES:
            print(f"  - pUSD for {exchange_name}")
            print(f"  - CTF for {exchange_name}")
        return True
    
    # Create contract instances
    pusd = web3.eth.contract(address=web3.to_checksum_address(PUSD_ADDRESS), abi=ERC20_ABI)
    ctf = web3.eth.contract(address=web3.to_checksum_address(CTF_ADDRESS), abi=ERC1155_SET_APPROVAL_ABI)
    
    print("Setting allowances (6 transactions)...")
    print("Note: Adding delays between transactions to avoid rate limits")
    print()
    
    import time
    success_count = 0
    nonce = web3.eth.get_transaction_count(pub_key)
    max_int = int(MAX_INT, 0) if isinstance(MAX_INT, str) else int(MAX_INT)
    sufficient_allowance = max_int // 2
    
    for i, (exchange_addr, exchange_name) in enumerate(EXCHANGES):
        print(f"📋 {exchange_name}:")
        exchange_checksum = web3.to_checksum_address(exchange_addr)
        
        # pUSD approve
        try:
            pusd_allowance = pusd.functions.allowance(pub_key, exchange_checksum).call()
            if pusd_allowance >= sufficient_allowance:
                print("  ✅ pUSD approve - Already approved")
                success_count += 1
            else:
                raw_tx = pusd.functions.approve(
                    exchange_checksum, max_int
                ).build_transaction({
                    "chainId": chain_id,
                    "from": pub_key,
                    "nonce": nonce,
                    "gasPrice": web3.eth.gas_price
                })
                if send_and_wait(web3, raw_tx, priv_key, "pUSD approve"):
                    success_count += 1
                nonce += 1
                time.sleep(5)  # Wait between transactions
        except Exception as e:
            print(f"  ❌ pUSD approve error: {e}")
        
        # CTF setApprovalForAll
        try:
            ctf_approved = ctf.functions.isApprovedForAll(pub_key, exchange_checksum).call()
            if ctf_approved:
                print("  ✅ CTF approve - Already approved")
                success_count += 1
            else:
                raw_tx = ctf.functions.setApprovalForAll(
                    exchange_checksum, True
                ).build_transaction({
                    "chainId": chain_id,
                    "from": pub_key,
                    "nonce": nonce,
                    "gasPrice": web3.eth.gas_price
                })
                if send_and_wait(web3, raw_tx, priv_key, "CTF approve"):
                    success_count += 1
                nonce += 1
                time.sleep(5)  # Wait between transactions
        except Exception as e:
            print(f"  ❌ CTF approve error: {e}")
        
        print()
        
        # Extra delay between exchange approvals
        if i < len(EXCHANGES) - 1:
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
        print("1. Make sure you have pUSD in your wallet")
        print("   (Run 'python3 setup_clob_trading.py wrap all' if you still hold USDC.e)")
        print("2. Run the bot: python3 main.py")
    else:
        print()
        print("⚠️  Some approvals failed. Check your POL balance and try again.")
    
    return success_count == 6

def wrap_usdce_to_pusd(amount_arg=None):
    """Wrap USDC.e into pUSD through Polymarket's CollateralOnramp."""
    from web3.constants import MAX_INT

    priv_key = os.getenv('WALLET_PRIVATE_KEY')
    pub_key = os.getenv('WALLET_ADDRESS')
    chain_id = 137

    if not priv_key or not pub_key:
        print("ERROR: WALLET_PRIVATE_KEY and WALLET_ADDRESS must be set in .env file")
        return False

    web3 = connect_polygon()
    if web3 is None:
        return False

    pub_key = web3.to_checksum_address(pub_key)
    balances = get_balances(web3, pub_key)

    print("=" * 60)
    print("WRAP USDC.e → pUSD")
    print("=" * 60)
    print(f"Wallet Address: {pub_key}")
    print(f"POL Balance: {balances['pol']:.4f} POL (for gas)")
    print(f"Current pUSD: ${balances['pusd']:.6f}")
    print(f"Current USDC.e: ${balances['usdce']:.6f}")
    print()

    if balances['usdce'] <= 0:
        print("❌ No USDC.e available to wrap.")
        return False

    if amount_arg is None:
        print("Specify an amount to wrap, or use 'all'.")
        print("Example: python3 setup_clob_trading.py wrap all")
        print("Example: python3 setup_clob_trading.py wrap 100")
        return False

    if str(amount_arg).lower() == "all":
        amount_usdc = balances['usdce']
    else:
        try:
            amount_usdc = float(amount_arg)
        except ValueError:
            print(f"❌ Invalid wrap amount: {amount_arg}")
            return False

    if amount_usdc <= 0:
        print("❌ Wrap amount must be greater than zero.")
        return False
    if amount_usdc > balances['usdce']:
        print(f"❌ Wrap amount ${amount_usdc:.6f} exceeds USDC.e balance ${balances['usdce']:.6f}.")
        return False

    amount_units = int(amount_usdc * 1_000_000)
    usdce = web3.eth.contract(address=web3.to_checksum_address(USDCE_ADDRESS), abi=ERC20_ABI)
    onramp = web3.eth.contract(address=web3.to_checksum_address(COLLATERAL_ONRAMP_ADDRESS), abi=ONRAMP_ABI)

    print(f"Wrapping ${amount_usdc:.6f} USDC.e into pUSD...")
    print("This sends two on-chain transactions if approval is needed.")
    print()

    nonce = web3.eth.get_transaction_count(pub_key)
    allowance = usdce.functions.allowance(pub_key, web3.to_checksum_address(COLLATERAL_ONRAMP_ADDRESS)).call()

    if allowance < amount_units:
        print("Approving CollateralOnramp to spend USDC.e...")
        approve_tx = usdce.functions.approve(
            COLLATERAL_ONRAMP_ADDRESS,
            int(MAX_INT, 0),
        ).build_transaction({
            "chainId": chain_id,
            "from": pub_key,
            "nonce": nonce,
            "gasPrice": web3.eth.gas_price,
        })
        if not send_and_wait(web3, approve_tx, priv_key, "USDC.e onramp approve"):
            return False
        nonce += 1
        time.sleep(5)
    else:
        print("USDC.e onramp allowance already sufficient.")

    wrap_tx = onramp.functions.wrap(
        USDCE_ADDRESS,
        pub_key,
        amount_units,
    ).build_transaction({
        "chainId": chain_id,
        "from": pub_key,
        "nonce": nonce,
        "gasPrice": web3.eth.gas_price,
    })
    if not send_and_wait(web3, wrap_tx, priv_key, "USDC.e → pUSD wrap"):
        return False

    new_balances = get_balances(web3, pub_key)
    print()
    print(f"New pUSD Balance: ${new_balances['pusd']:.6f}")
    print(f"New USDC.e Balance: ${new_balances['usdce']:.6f}")
    print()
    print("Next: run python3 setup_clob_trading.py approve")
    return True

def check_clob_status():
    """Check current CLOB balance and allowance status."""
    try:
        try:
            from py_clob_client_v2 import ApiCreds, AssetType, BalanceAllowanceParams, ClobClient
        except ImportError:
            from py_clob_client import ApiCreds, AssetType, BalanceAllowanceParams, ClobClient
        
        private_key = os.getenv('WALLET_PRIVATE_KEY')
        if not private_key:
            print("ERROR: WALLET_PRIVATE_KEY not set")
            return
        
        signature_type = int(os.getenv('POLYMARKET_SIGNATURE_TYPE', '0'))
        funder = (
            os.getenv('POLYMARKET_FUNDER_ADDRESS')
            or os.getenv('POLYMARKET_DEPOSIT_WALLET_ADDRESS')
            or os.getenv('DEPOSIT_WALLET_ADDRESS')
            or os.getenv('WALLET_ADDRESS')
        )

        client = ClobClient(
            host='https://clob.polymarket.com',
            chain_id=137,
            key=private_key,
            signature_type=signature_type,
            funder=funder,
        )
        # Prefer existing API credentials from env to avoid unnecessary key creation.
        api_key = os.getenv('POLYMARKET_API_KEY')
        api_secret = os.getenv('POLYMARKET_API_SECRET')
        api_passphrase = os.getenv('POLYMARKET_PASSPHRASE')

        def load_creds(force_derive=False):
            if force_derive:
                client.set_api_creds(client.derive_api_key())
                return
            try:
                client.set_api_creds(client.derive_api_key())
            except Exception:
                if api_key and api_secret and api_passphrase:
                    client.set_api_creds(ApiCreds(
                        api_key=api_key,
                        api_secret=api_secret,
                        api_passphrase=api_passphrase,
                    ))
                else:
                    raise

        load_creds(force_derive=False)
        
        print("=" * 60)
        print("CLOB STATUS CHECK")
        print("=" * 60)
        print()
        print(f"Wallet: {client.get_address()}")
        print(f"Signature Type: {signature_type}")
        print(f"Funder: {funder or 'N/A'}")
        print()

        web3 = connect_polygon()
        onchain_balances = None
        if web3 is not None:
            onchain_balances = get_balances(web3, web3.to_checksum_address(funder))
            print("On-chain balances:")
            print(f"  pUSD: ${onchain_balances['pusd']:.6f}")
            print(f"  USDC.e: ${onchain_balances['usdce']:.6f}")
            print(f"  Native USDC: ${onchain_balances['native_usdc']:.6f}")
            print(f"  POL: {onchain_balances['pol']:.4f}")
            print()
        
        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=signature_type,
        )
        try:
            try:
                client.update_balance_allowance(params)
            except Exception as update_error:
                if "401" in str(update_error) or "Unauthorized" in str(update_error):
                    raise
            result = client.get_balance_allowance(params)
        except Exception as first_error:
            if "401" in str(first_error) or "Unauthorized" in str(first_error):
                print("⚠️ Stored API credentials were rejected; deriving fresh credentials...")
                load_creds(force_derive=True)
                try:
                    client.update_balance_allowance(params)
                except Exception:
                    pass
                result = client.get_balance_allowance(params)
            else:
                raise
        
        balance = int(result.get('balance', 0)) / 1_000_000
        print(f"CLOB Balance: ${balance:.2f} pUSD")
        print()
        
        print("Allowances:")
        allowances = result.get('allowances', {})
        exchange_names = {
            '0xe111180000d2663c0091e4f400237545b87b996b': 'CTF Exchange V2',
            '0xe2222d279d744050d28e00520010520000310f59': 'Neg Risk CTF Exchange V2',
            '0xd91e80cf2e7be2e162c6513ced06f1dd0da35296': 'Neg Risk Adapter',
        }
        
        all_approved = True
        normalized_allowances = {
            addr.lower(): int(amount)
            for addr, amount in allowances.items()
        }
        for expected_addr, expected_name in EXCHANGES:
            amount = normalized_allowances.get(expected_addr.lower(), 0)
            approved = amount > 0
            status = "✅ Approved" if approved else "❌ Not approved"
            print(f"  {expected_name}: {status}")
            if not approved:
                all_approved = False
        
        print()
        if balance > 0 and all_approved:
            print("✅ Ready to trade!")
        elif balance == 0:
            if onchain_balances and onchain_balances['usdce'] > 0 and onchain_balances['pusd'] <= 0:
                print("❌ CLOB balance is zero because funds are still legacy USDC.e.")
                print("   Run: python3 setup_clob_trading.py wrap all")
                print("   Then run: python3 setup_clob_trading.py approve")
            else:
                print("❌ No CLOB balance. Deposit or wrap funds into pUSD for the configured funder wallet.")
        elif not all_approved:
            print("❌ Run 'python3 setup_clob_trading.py approve' to set allowances")
            
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
        elif command == 'wrap':
            amount = sys.argv[2] if len(sys.argv) > 2 else None
            wrap_usdce_to_pusd(amount)
        else:
            print(f"Unknown command: {command}")
            print("Usage: python3 setup_clob_trading.py [approve|dry-run|status|wrap AMOUNT|wrap all]")
    else:
        print("POLYMARKET CLOB TRADING SETUP")
        print("=" * 40)
        print()
        print("Commands:")
        print("  python3 setup_clob_trading.py status   - Check current status")
        print("  python3 setup_clob_trading.py wrap all - Wrap legacy USDC.e into pUSD")
        print("  python3 setup_clob_trading.py dry-run  - Preview what will be done")
        print("  python3 setup_clob_trading.py approve  - Set pUSD/CTF allowances (requires POL for gas)")
        print()
        
        # Show status by default
        check_clob_status()

if __name__ == "__main__":
    main()
