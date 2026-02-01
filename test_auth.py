#!/usr/bin/env python3
"""
Test script for verifying the auth module works correctly.

Run with:
    python test_auth.py

This tests both TEST_MODE and simulated LIVE mode with mock credentials.
"""

import os
import sys


def test_test_mode():
    """Test that auth works in TEST_MODE."""
    print("\n" + "="*60)
    print("TEST 1: Auth in TEST_MODE")
    print("="*60)
    
    # Ensure TEST_MODE is true
    os.environ['TEST_MODE'] = 'true'
    
    # Need fresh imports
    from auth import PolymarketAuth, AuthLevel, reset_auth
    reset_auth()
    
    auth = PolymarketAuth()
    
    # In TEST_MODE, everything should be "ready" (simulated)
    assert auth.is_ready(AuthLevel.L1), "L1 should be ready in TEST_MODE"
    assert auth.is_ready(AuthLevel.L2), "L2 should be ready in TEST_MODE"
    
    # Headers should be minimal
    headers = auth.get_l1_headers("GET", "/test")
    assert headers == {"Content-Type": "application/json"}, "Headers should be minimal in TEST_MODE"
    
    # Sign order should return mock signature
    sig = auth.sign_order({"token_id": "test"})
    assert sig.startswith("0x"), "Mock signature should start with 0x"
    assert len(sig) == 132, f"Mock signature should be 132 chars (got {len(sig)})"
    
    print("✅ TEST_MODE tests passed!")
    return True


def test_live_mode_no_credentials():
    """Test that auth properly fails without credentials in LIVE mode."""
    print("\n" + "="*60)
    print("TEST 2: Auth in LIVE mode (no credentials)")
    print("="*60)
    
    # Clear any existing credentials
    for key in ['POLYMARKET_API_KEY', 'POLYMARKET_API_SECRET', 'POLYMARKET_PASSPHRASE', 
                'WALLET_ADDRESS', 'WALLET_PRIVATE_KEY']:
        os.environ.pop(key, None)
    
    os.environ['TEST_MODE'] = 'false'
    
    # Reload config to pick up new env vars
    import importlib
    import config
    importlib.reload(config)
    
    from auth import PolymarketAuth, AuthLevel, reset_auth
    reset_auth()
    
    auth = PolymarketAuth()
    
    # Without credentials, nothing should be ready
    assert not auth.is_ready(AuthLevel.L1), "L1 should NOT be ready without credentials"
    assert not auth.is_ready(AuthLevel.L2), "L2 should NOT be ready without credentials"
    
    # Validation should fail with specific errors
    is_valid, errors = auth.validate_credentials()
    assert not is_valid, "Credentials should be invalid"
    assert len(errors) == 5, f"Should have 5 errors (got {len(errors)})"
    
    print("✅ No-credentials tests passed!")
    return True


def test_live_mode_with_credentials():
    """Test that auth works with mock credentials in LIVE mode."""
    print("\n" + "="*60)
    print("TEST 3: Auth in LIVE mode (with mock credentials)")
    print("="*60)
    
    # Set mock credentials
    os.environ['TEST_MODE'] = 'false'
    os.environ['POLYMARKET_API_KEY'] = 'test_api_key_12345'
    os.environ['POLYMARKET_API_SECRET'] = 'dGVzdF9zZWNyZXRfMTIzNDU='  # base64
    os.environ['POLYMARKET_PASSPHRASE'] = 'test_passphrase'
    os.environ['WALLET_ADDRESS'] = '0x742d35Cc6634C0532925a3b844Bc9e7595f3bD77'
    # Valid test private key (from eth-account docs, DO NOT use for real funds!)
    os.environ['WALLET_PRIVATE_KEY'] = '0x4c0883a69102937d6231471b5dbb6204fe512961708279a3d3d2a88c8b4c35d7'
    
    # Reload config
    import importlib
    import config
    importlib.reload(config)
    
    from auth import PolymarketAuth, AuthLevel, reset_auth
    reset_auth()
    
    auth = PolymarketAuth()
    
    # With credentials, should be ready
    assert auth.is_ready(AuthLevel.L1), "L1 should be ready with credentials"
    assert auth.is_ready(AuthLevel.L2), "L2 should be ready with credentials"
    
    # Validation should pass
    is_valid, errors = auth.validate_credentials()
    assert is_valid, f"Credentials should be valid (errors: {errors})"
    
    # Headers should include auth info
    headers = auth.get_l1_headers("GET", "/balance")
    assert "POLY-API-KEY" in headers, "Headers should include API key"
    assert "POLY-SIGNATURE" in headers, "Headers should include signature"
    assert "POLY-TIMESTAMP" in headers, "Headers should include timestamp"
    assert headers["POLY-API-KEY"] == "test_api_key_12345", "API key should match"
    
    # Wallet should be verified
    assert auth.verify_wallet_connection(), "Wallet should be verified"
    
    # Wallet address should be returned
    addr = auth.get_wallet_address()
    assert addr == '0x742d35Cc6634C0532925a3b844Bc9e7595f3bD77', "Wallet address should match"
    
    # Order signing should work
    order = {
        'token_id': '0x1234567890abcdef',
        'side': 'BUY',
        'size': '10.5',
        'price': '0.55',
        'nonce': 1234567890
    }
    sig = auth.sign_order(order)
    assert sig.startswith("0x"), "Signature should start with 0x"
    assert len(sig) > 100, "Signature should be a valid length"
    
    print("✅ With-credentials tests passed!")
    return True


def test_signature_consistency():
    """Test that signatures are consistent for the same input."""
    print("\n" + "="*60)
    print("TEST 4: Signature consistency")
    print("="*60)
    
    # Ensure credentials are set
    os.environ['TEST_MODE'] = 'false'
    os.environ['POLYMARKET_API_KEY'] = 'test_api_key'
    os.environ['POLYMARKET_API_SECRET'] = 'dGVzdF9zZWNyZXQ='
    os.environ['POLYMARKET_PASSPHRASE'] = 'test_pass'
    os.environ['WALLET_ADDRESS'] = '0x742d35Cc6634C0532925a3b844Bc9e7595f3bD77'
    os.environ['WALLET_PRIVATE_KEY'] = '0x4c0883a69102937d6231471b5dbb6204fe512961708279a3d3d2a88c8b4c35d7'
    
    import importlib
    import config
    importlib.reload(config)
    
    from auth import PolymarketAuth, reset_auth
    reset_auth()
    
    auth = PolymarketAuth()
    
    # Same order should produce same signature
    order = {
        'token_id': 'abc123',
        'side': 'SELL',
        'size': '5',
        'price': '0.75',
        'nonce': 999999,
        'expiration': 0
    }
    
    sig1 = auth.sign_order(order)
    sig2 = auth.sign_order(order)
    
    assert sig1 == sig2, "Same order should produce same signature"
    
    # Different order should produce different signature
    order2 = order.copy()
    order2['nonce'] = 888888
    sig3 = auth.sign_order(order2)
    
    assert sig1 != sig3, "Different orders should produce different signatures"
    
    print("✅ Signature consistency tests passed!")
    return True


def cleanup():
    """Reset environment to TEST_MODE."""
    os.environ['TEST_MODE'] = 'true'
    for key in ['POLYMARKET_API_KEY', 'POLYMARKET_API_SECRET', 'POLYMARKET_PASSPHRASE', 
                'WALLET_ADDRESS', 'WALLET_PRIVATE_KEY']:
        os.environ.pop(key, None)


def main():
    """Run all tests."""
    print("\n" + "#"*60)
    print("# AUTH MODULE TEST SUITE")
    print("#"*60)
    
    try:
        all_passed = True
        all_passed &= test_test_mode()
        all_passed &= test_live_mode_no_credentials()
        all_passed &= test_live_mode_with_credentials()
        all_passed &= test_signature_consistency()
        
        print("\n" + "="*60)
        if all_passed:
            print("🎉 ALL TESTS PASSED!")
        else:
            print("❌ SOME TESTS FAILED!")
            sys.exit(1)
        print("="*60 + "\n")
        
    finally:
        cleanup()


if __name__ == "__main__":
    main()
