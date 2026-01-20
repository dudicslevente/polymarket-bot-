def find_current_btc_15min_market() -> str:
    """
    Find the current active BTC 15min market on Polymarket.
    
    Searches for markets matching the pattern 'btc-updown-15m-<timestamp>'
    and returns the slug of the most recent/active market.
    """
    logger.info("Searching for current BTC 15min market...")
    
    try:
        # Search on Polymarket's crypto 15min page
        page_url = "https://polymarket.com/crypto/15M"
        resp = httpx.get(page_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        
        # Find the BTC market slug in the HTML
        pattern = r'btc-updown-15m-(\d+)'
        matches = re.findall(pattern, resp.text)
        
        if not matches:
            raise RuntimeError("No active BTC 15min market found")
        
        # Prefer the most recent timestamp that is still OPEN.
        # 15min markets close 900s after the timestamp in the slug.
        now_ts = int(datetime.now().timestamp())
        all_ts = sorted((int(ts) for ts in matches), reverse=True)
        open_ts = [ts for ts in all_ts if now_ts < (ts + 900)]
        chosen_ts = open_ts[0] if open_ts else all_ts[0]
        slug = f"btc-updown-15m-{chosen_ts}"
        
        logger.info(f"✅ Market found: {slug}")
        return slug
        
    except Exception as e:
        logger.error(f"Error searching for BTC 15min market: {e}")
        # Fallback: try with the last known one
        logger.warning("Using default market from configuration...")
        raise
