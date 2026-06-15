import unittest

from price_feed import BinanceClient


class FakeBinanceClient(BinanceClient):
    def _make_request(self, endpoint, params=None, retries=2):
        params = params or {}
        target_time_ms = 1_000_000

        if endpoint == "/api/v3/time":
            return {"serverTime": target_time_ms + 180_000}

        if endpoint == "/api/v3/ticker/price":
            return {"symbol": "BTCUSDT", "price": "102.0"}

        if endpoint == "/api/v3/aggTrades":
            start_time = params.get("startTime")
            end_time = params.get("endTime")

            if end_time == target_time_ms:
                return [{"p": "100.0", "T": target_time_ms - 500}]

            if start_time == target_time_ms:
                return [{"p": "101.0", "T": target_time_ms + 800}]

        return None


class PriceFeedTests(unittest.TestCase):
    def test_calculate_price_change_uses_nearest_trade_to_exact_lookback(self):
        client = FakeBinanceClient()

        change = client.calculate_price_change(3)

        self.assertIsNotNone(change)
        self.assertEqual(change.start_price, 100.0)
        self.assertEqual(change.end_price, 102.0)
        self.assertAlmostEqual(change.change_percent, 2.0)


if __name__ == "__main__":
    unittest.main()
