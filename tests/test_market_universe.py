import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tools import market_universe as universe
from tools import hot_market_scanner as scanner


class UniverseTests(unittest.TestCase):
    def test_merge_keeps_watchlist_contract_mapping(self):
        original = {"Market": "US", "Symbol": "ARM", "Name": "Arm", "Binance Symbol": "ARM/USDT:USDT"}
        new = universe.candidate("US", "ARM", "Arm", "API list", "today")
        merged = universe.merge_candidates([original], [new])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["Binance Symbol"], "ARM/USDT:USDT")
        self.assertIn("API list", merged[0]["候選來源"])
        self.assertNotIn("候選來源", original)

    def test_interleaving_deduplicates_and_keeps_multiple_categories(self):
        def stock(symbol):
            return universe.candidate("US", symbol, symbol, "api", "today")
        rows = universe.interleave([[stock("A"), stock("B")], [stock("A"), stock("C")], [stock("D")]], 3)
        self.assertEqual([r["Symbol"] for r in rows], ["A", "D", "B"])

    def test_us_filters_illiquid_stale_and_non_equities(self):
        good = {"symbol": "TEST", "quoteType": "EQUITY", "exchange": "NMS", "regularMarketPrice": 100,
                "regularMarketVolume": 1_000_000, "regularMarketTime": datetime.now(timezone.utc).timestamp()}
        quotes = [good, {**good, "symbol": "CHEAP", "regularMarketPrice": 1},
                  {**good, "symbol": "STALE", "regularMarketTime": 0}, {**good, "symbol": "FUND", "quoteType": "ETF"}]
        with patch.object(universe, "fetch_json", return_value={"finance": {"result": [{"quotes": quotes}]}}):
            rows, warnings = universe.discover_us(30)
        self.assertEqual([r["Symbol"] for r in rows], ["TEST"])
        self.assertEqual(warnings, [])

    def test_tw_filters_etf_and_small_turnover(self):
        now = datetime.now(timezone(timedelta(hours=8)))
        date = f"{now.year - 1911:03d}{now.month:02d}{now.day:02d}"
        good = {"Code": "2330", "Name": "TSMC", "ClosingPrice": "100", "Change": "2",
                "TradeValue": "200,000,000", "Date": date}
        with patch.object(universe, "fetch_json", return_value=[good, {**good, "Code": "0050"},
                    {**good, "Code": "1234", "TradeValue": "100"}, {**good, "Code": "2345", "Date": "1000101"}]):
            rows, warnings = universe.discover_tw(30)
        self.assertEqual([r["Symbol"] for r in rows], ["2330.TW"])
        self.assertEqual(warnings, [])

    def test_partial_failure_is_visible(self):
        with patch.object(universe, "discover_tw", side_effect=RuntimeError("offline")), \
             patch.object(universe, "discover_us", return_value=([{"Symbol": "A"}], [])):
            rows, warnings = universe.discover_candidates(30)
        self.assertEqual(len(rows), 1)
        self.assertIn("TW", warnings[0])

    def test_dynamic_only_failure_does_not_read_watchlist(self):
        with patch.object(scanner, "discover_candidates", return_value=([], ["offline"])), \
             patch.object(scanner, "read_watchlist") as read:
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                scanner.run_scan(universe="discovery", print_progress=False)
        read.assert_not_called()

    def test_dynamic_stock_does_not_invent_contract(self):
        stock = universe.candidate("US", "NEW", "New", "API list", "today")
        self.assertEqual(scanner.binance_tradable(stock, {"NEW/USDT:USDT"}), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
