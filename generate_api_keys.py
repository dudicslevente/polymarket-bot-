import os
try:
    from py_clob_client_v2 import ClobClient
except ImportError:
    from py_clob_client import ClobClient
from dotenv import load_dotenv
# Load the environment variables from the .env file
load_dotenv()
def main():
    host = "https://clob.polymarket.com"
    key = os.getenv("WALLET_PRIVATE_KEY")
    chain_id = 137  # Polygon Mainnet chain ID
    signature_type = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))
    funder = (
        os.getenv("POLYMARKET_FUNDER_ADDRESS")
        or os.getenv("POLYMARKET_DEPOSIT_WALLET_ADDRESS")
        or os.getenv("DEPOSIT_WALLET_ADDRESS")
        or os.getenv("WALLET_ADDRESS")
    )
    # Ensure the private key is loaded correctly
    if not key:
        raise ValueError("Private key not found. Please set WALLET_PRIVATE_KEY in the environment variables.")
    # Initialize the client with your private key
    client = ClobClient(
        host,
        chain_id=chain_id,
        key=key,
        signature_type=signature_type,
        funder=funder,
    )
    # Create or derive API credentials (this is where the API key, secret, and passphrase are generated)
    try:
        api_creds = client.derive_api_key()
        print("API Key:", api_creds.api_key)
        print("Secret:", api_creds.api_secret)
        print("Passphrase:", api_creds.api_passphrase)
        # You should now save these securely (e.g., store them in your .env file)
    except Exception as e:
        print("Error creating or deriving API credentials:", e)
if __name__ == "__main__":
    main()
