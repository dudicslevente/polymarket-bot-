"""
Authentication module for Polymarket CLOB API.

This module handles:
- API Key authentication (L1 Auth)
- Wallet-based EIP-712 signing for orders (L2 Auth)
- Request header generation
- Order signing for the CLOB

Polymarket uses a two-layer authentication system:
1. L1 Auth: API Key + Signature for account-level operations
2. L2 Auth: Wallet signature for order placement

References:
- https://docs.polymarket.com/#authentication
- https://github.com/Polymarket/py-clob-client
"""

import time
import hmac
import hashlib
import base64
from typing import Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

import config


class AuthError(Exception):
    """Raised when authentication fails."""
    pass


class AuthLevel(Enum):
    """Authentication levels for Polymarket API."""
    NONE = "none"           # Public endpoints (no auth needed)
    L1 = "l1"               # API Key auth (read operations)
    L2 = "l2"               # Wallet signature (write operations)


@dataclass
class AuthCredentials:
    """Stores authentication credentials."""
    api_key: str
    api_secret: str
    passphrase: str
    wallet_address: Optional[str] = None
    private_key: Optional[str] = None
    
    def is_valid_for_l1(self) -> bool:
        """Check if credentials are valid for L1 authentication."""
        return bool(self.api_key and self.api_secret and self.passphrase)
    
    def is_valid_for_l2(self) -> bool:
        """Check if credentials are valid for L2 authentication (orders)."""
        return self.is_valid_for_l1() and bool(self.wallet_address and self.private_key)


class PolymarketAuth:
    """
    Handles authentication for Polymarket CLOB API.
    
    This class provides methods to:
    1. Generate authenticated headers for API requests
    2. Sign orders for submission to the CLOB
    3. Validate credentials
    
    Usage:
        auth = PolymarketAuth()
        if auth.is_ready():
            headers = auth.get_l1_headers("GET", "/markets")
    """
    
    def __init__(self):
        """Initialize authentication with credentials from config."""
        self.credentials: Optional[AuthCredentials] = None
        self._eth_account = None  # Lazy-loaded eth_account
        
        # Only initialize credentials if not in test mode
        if not config.TEST_MODE:
            self._load_credentials()
    
    def _load_credentials(self):
        """Load credentials from config."""
        api_key = config.POLYMARKET_API_KEY or ""
        api_secret = config.POLYMARKET_API_SECRET or ""
        passphrase = config.POLYMARKET_PASSPHRASE or ""
        wallet_address = config.WALLET_ADDRESS or ""
        private_key = config.WALLET_PRIVATE_KEY or ""
        
        self.credentials = AuthCredentials(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            wallet_address=wallet_address,
            private_key=private_key
        )
        
        if config.VERBOSE_LOGGING:
            self._print_auth_status()
    
    def _print_auth_status(self):
        """Print authentication status for debugging."""
        if self.credentials is None:
            print("🔐 Auth: Not initialized")
            return
        
        l1_ready = self.credentials.is_valid_for_l1()
        l2_ready = self.credentials.is_valid_for_l2()
        
        if l2_ready:
            addr = self.credentials.wallet_address
            masked_addr = f"{addr[:6]}...{addr[-4:]}" if addr else "N/A"
            print(f"🔐 Auth: L2 Ready (wallet: {masked_addr})")
        elif l1_ready:
            print("🔐 Auth: L1 Ready (API key only)")
        else:
            print("🔐 Auth: Not configured - check .env file")
    
    def is_ready(self, level: AuthLevel = AuthLevel.L1) -> bool:
        """
        Check if authentication is ready for the specified level.
        
        Args:
            level: The authentication level to check
            
        Returns:
            True if credentials are valid for the specified level
        """
        if config.TEST_MODE:
            return True  # Always "ready" in test mode (simulated)
        
        if self.credentials is None:
            return False
        
        if level == AuthLevel.NONE:
            return True
        elif level == AuthLevel.L1:
            return self.credentials.is_valid_for_l1()
        elif level == AuthLevel.L2:
            return self.credentials.is_valid_for_l2()
        
        return False
    
    def validate_credentials(self) -> tuple[bool, list[str]]:
        """
        Validate that all required credentials are present.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        if self.credentials is None:
            return False, ["Credentials not loaded"]
        
        if not self.credentials.api_key:
            errors.append("POLYMARKET_API_KEY is missing")
        
        if not self.credentials.api_secret:
            errors.append("POLYMARKET_API_SECRET is missing")
        
        if not self.credentials.passphrase:
            errors.append("POLYMARKET_PASSPHRASE is missing")
        
        if not self.credentials.wallet_address:
            errors.append("WALLET_ADDRESS is missing")
        
        if not self.credentials.private_key:
            errors.append("WALLET_PRIVATE_KEY is missing")
        elif not self.credentials.private_key.startswith("0x"):
            errors.append("WALLET_PRIVATE_KEY should start with '0x'")
        
        return len(errors) == 0, errors
    
    def get_l1_headers(
        self,
        method: str,
        path: str,
        body: str = ""
    ) -> Dict[str, str]:
        """
        Generate L1 authenticated headers for API requests.
        
        L1 authentication is used for:
        - Creating/deriving API keys
        - Initial wallet authentication
        
        Uses EIP-712 signing for authentication.
        
        Args:
            method: HTTP method (GET, POST, DELETE)
            path: API path (e.g., "/auth/api-key")
            body: Request body as string (for POST requests)
            
        Returns:
            Dictionary of headers to include in the request
        """
        if config.TEST_MODE:
            return {"Content-Type": "application/json"}
        
        if not self.is_ready(AuthLevel.L1):
            raise AuthError("L1 authentication credentials not configured")
        
        # L1 headers use EIP-712 signature
        # This is used for initial API key creation/derivation
        timestamp = int(time.time())
        nonce = 0
        
        # Sign using EIP-712 format
        signature = self._sign_clob_auth_message(timestamp, nonce)
        
        return {
            "Content-Type": "application/json",
            "POLY_ADDRESS": self.credentials.wallet_address or "",
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": str(timestamp),
            "POLY_NONCE": str(nonce),
        }
    
    def get_l2_headers(
        self,
        method: str,
        path: str,
        body: str = ""
    ) -> Dict[str, str]:
        """
        Generate L2 authenticated headers for CLOB API requests.
        
        L2 authentication is used for:
        - Reading account balances
        - Checking positions
        - Getting order history
        - Placing orders
        
        Uses HMAC-SHA256 signature with API credentials.
        
        Args:
            method: HTTP method (GET, POST, DELETE)
            path: API path (e.g., "/balance-allowance") - should NOT include query params
            body: Request body as string (for POST requests)
            
        Returns:
            Dictionary of headers to include in the request
        """
        if config.TEST_MODE:
            return {"Content-Type": "application/json"}
        
        if not self.is_ready(AuthLevel.L2):
            raise AuthError("L2 authentication credentials not configured")
        
        # Timestamp in seconds (not milliseconds)
        timestamp = int(time.time())
        
        # Build HMAC signature following py-clob-client format
        # Format: timestamp + method + path + body
        # Note: path should NOT include query parameters
        message = str(timestamp) + str(method) + str(path)
        if body:
            # Replace single quotes with double quotes for consistency with Go/TypeScript
            message += str(body).replace("'", '"')
        
        # HMAC-SHA256 signature with base64-encoded result
        try:
            # Decode the base64 secret (urlsafe_b64decode handles both standard and URL-safe base64)
            decoded_secret = base64.urlsafe_b64decode(self.credentials.api_secret)
            signature = hmac.new(
                decoded_secret,
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
            # Base64 encode the signature (urlsafe)
            signature_b64 = base64.urlsafe_b64encode(signature).decode('utf-8')
        except Exception as e:
            raise AuthError(f"Failed to create HMAC signature: {e}")
        
        return {
            "Content-Type": "application/json",
            "POLY_ADDRESS": self.credentials.wallet_address or "",
            "POLY_SIGNATURE": signature_b64,
            "POLY_TIMESTAMP": str(timestamp),
            "POLY_API_KEY": self.credentials.api_key,
            "POLY_PASSPHRASE": self.credentials.passphrase,
        }
    
    def _sign_clob_auth_message(self, timestamp: int, nonce: int) -> str:
        """
        Sign a CLOB authentication message using EIP-712.
        
        This is used for L1 authentication (API key creation/derivation).
        
        Args:
            timestamp: Unix timestamp
            nonce: Nonce value
            
        Returns:
            Hex-encoded signature
        """
        try:
            from eth_account import Account
            from eth_account.messages import encode_structured_data
            
            # EIP-712 domain for CLOB authentication
            domain = {
                "name": "ClobAuthDomain",
                "version": "1",
                "chainId": 137,  # Polygon mainnet
            }
            
            # Message to sign
            message = {
                "address": self.credentials.wallet_address,
                "timestamp": str(timestamp),
                "nonce": nonce,
                "message": "This message attests that I control the given wallet",
            }
            
            # Full EIP-712 typed data
            typed_data = {
                "types": {
                    "EIP712Domain": [
                        {"name": "name", "type": "string"},
                        {"name": "version", "type": "string"},
                        {"name": "chainId", "type": "uint256"},
                    ],
                    "ClobAuth": [
                        {"name": "address", "type": "address"},
                        {"name": "timestamp", "type": "string"},
                        {"name": "nonce", "type": "uint256"},
                        {"name": "message", "type": "string"},
                    ],
                },
                "primaryType": "ClobAuth",
                "domain": domain,
                "message": message,
            }
            
            # Sign the typed data
            account = Account.from_key(self.credentials.private_key)
            signed = account.sign_message(encode_structured_data(typed_data))
            
            sig_hex = signed.signature.hex()
            if not sig_hex.startswith("0x"):
                sig_hex = "0x" + sig_hex
            return sig_hex
            
        except ImportError:
            raise AuthError(
                "eth-account package not installed. "
                "Install with: pip install eth-account"
            )
        except Exception as e:
            raise AuthError(f"Failed to sign auth message: {e}")
    
    def _get_eth_account(self):
        """
        Lazy-load eth_account module and create account from private key.
        
        This delays the eth_account import until it's actually needed,
        making the module work even if eth-account isn't installed.
        """
        if self._eth_account is None:
            if not self.credentials or not self.credentials.private_key:
                raise AuthError("Private key not configured")
            
            try:
                from eth_account import Account
                self._eth_account = Account.from_key(self.credentials.private_key)
            except ImportError:
                raise AuthError(
                    "eth-account package not installed. "
                    "Install with: pip install eth-account"
                )
            except Exception as e:
                raise AuthError(f"Invalid private key: {e}")
        
        return self._eth_account
    
    def sign_order(self, order_data: Dict[str, Any]) -> str:
        """
        Sign an order for submission to the CLOB.
        
        This creates an EIP-712 typed data signature that proves
        the order was authorized by the wallet owner.
        
        Args:
            order_data: Dictionary containing order parameters
                - token_id: The token to trade
                - side: "BUY" or "SELL"
                - size: Order size
                - price: Order price
                - nonce: Unique nonce for replay protection
                
        Returns:
            Hex-encoded signature string
        """
        if config.TEST_MODE:
            # Return a mock signature for test mode
            return "0x" + "00" * 65
        
        account = self._get_eth_account()
        
        # Create the order message to sign
        # This follows Polymarket's order format
        order_message = self._create_order_message(order_data)
        
        try:
            from eth_account.messages import encode_defunct
            message = encode_defunct(text=order_message)
            signed = account.sign_message(message)
            # Ensure signature has 0x prefix
            sig_hex = signed.signature.hex()
            if not sig_hex.startswith("0x"):
                sig_hex = "0x" + sig_hex
            return sig_hex
        except ImportError:
            raise AuthError(
                "eth-account package not installed. "
                "Install with: pip install eth-account"
            )
        except Exception as e:
            raise AuthError(f"Failed to sign order: {e}")
    
    def _create_order_message(self, order_data: Dict[str, Any]) -> str:
        """
        Create the message string to sign for an order.
        
        This creates a deterministic string representation of the order
        that can be verified by the CLOB.
        
        Args:
            order_data: Order parameters
            
        Returns:
            Message string to sign
        """
        # Polymarket CLOB order format
        # This may need adjustment based on actual API requirements
        token_id = order_data.get("token_id", "")
        side = order_data.get("side", "BUY")
        size = str(order_data.get("size", "0"))
        price = str(order_data.get("price", "0"))
        nonce = str(order_data.get("nonce", int(time.time() * 1000)))
        expiration = str(order_data.get("expiration", 0))
        
        # Create ordered message for signing
        message_parts = [
            f"token_id:{token_id}",
            f"side:{side}",
            f"size:{size}",
            f"price:{price}",
            f"nonce:{nonce}",
            f"expiration:{expiration}"
        ]
        
        return "|".join(message_parts)
    
    def get_wallet_address(self) -> Optional[str]:
        """Get the configured wallet address."""
        if self.credentials:
            return self.credentials.wallet_address
        return None
    
    def verify_wallet_connection(self) -> bool:
        """
        Verify that the wallet can be accessed and used for signing.
        
        Returns:
            True if wallet is ready for signing
        """
        if config.TEST_MODE:
            return True
        
        try:
            account = self._get_eth_account()
            # Verify we can get the address
            _ = account.address
            return True
        except Exception as e:
            if config.VERBOSE_LOGGING:
                print(f"❌ Wallet verification failed: {e}")
            return False


# Module-level singleton for convenience
_auth_instance: Optional[PolymarketAuth] = None


def get_auth() -> PolymarketAuth:
    """
    Get the global authentication instance.
    
    Creates a new instance if one doesn't exist.
    
    Returns:
        PolymarketAuth instance
    """
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = PolymarketAuth()
    return _auth_instance


def reset_auth():
    """Reset the global authentication instance (useful for testing)."""
    global _auth_instance
    _auth_instance = None


# Validation function for use during startup
def validate_live_auth() -> bool:
    """
    Validate authentication for live trading.
    
    This is called during startup when TEST_MODE=false to ensure
    all required credentials are configured.
    
    Returns:
        True if authentication is properly configured
    """
    if config.TEST_MODE:
        return True
    
    auth = get_auth()
    is_valid, errors = auth.validate_credentials()
    
    if not is_valid:
        print("\n❌ Authentication validation failed:")
        for error in errors:
            print(f"   • {error}")
        print("\nPlease check your .env file and ensure all credentials are set.")
        return False
    
    # Verify wallet can be used
    if not auth.verify_wallet_connection():
        print("\n❌ Wallet connection failed")
        print("   • Check that WALLET_PRIVATE_KEY is correct")
        print("   • Ensure eth-account package is installed: pip install eth-account")
        return False
    
    wallet_addr = auth.get_wallet_address()
    if wallet_addr:
        masked = f"{wallet_addr[:6]}...{wallet_addr[-4:]}"
        print(f"✅ Authentication validated for wallet: {masked}")
    
    return True
