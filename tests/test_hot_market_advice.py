import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tools import hot_market_scanner as scanner
from tools.market_advice import describe_advice, add_comparison, load_previous_rows, add_last_direction_change


class HotMarketAdviceTests(unittest.TestCase):
    def row(self, **changes):
        row = {"Market": "US", "Symbol": "ARM", "Name": "Arm", "Rank": "2",
               "Score": "100", "Bias": "LONG", "Last Price": "105", "EMA20": "100",
               "ATR%": "3", "VolX": "1.5", "前20日高": "104", "前20日低": "90",
               "距EMA20%": "5", "資料狀態": "已收盤", "Binance": "YES", "Error": ""}
        row.update(changes)
        return row

    def test_buy_candidate_and_stretched_wait(self):
        row = self.row()
        describe_advice(row)
        self.assertEqual(row["本次建議"], "買進候選")
        row["距EMA20%"] = "20"
        describe_advice(row)
        self.assertEqual(row["本次建議"], "再觀察")
        self.assertIn("不急著追", row["建議原因"])

    def test_old_arm_short_to_long_preserves_old_advice(self):
        row = self.row()
        describe_advice(row)
        old = self.row(Bias="SHORT", **{"Last Price": "100", "Rank": "8",
                       "白話結論": "做空｜短進短出｜可執行"})
        add_comparison([row], {("US", "ARM"): old}, "2026-09-20")
        self.assertEqual(row["方向變化"], "翻多：偏空 → 偏多")
        self.assertEqual(row["較上次漲跌%"], "+5.00")
        self.assertEqual(row["排名變化"], "+6.00")
        self.assertIn("做空", row["上次建議"])
        self.assertIn("規則版本不同", row["建議變化"])
        self.assertIn("不直接反手", row["持有空單時"])

    def test_pullback_entry_and_conditional_add(self):
        row = self.row(**{"Last Price": "101", "距EMA20%": "1",
                             "回檔確認": "是", "EMA20上升": "是", "當日量比": "1.1"})
        describe_advice(row)
        self.assertEqual(row["進場型態"], "回檔止穩")
        self.assertEqual(row["本次建議"], "買進候選")
        self.assertIn("待持倉風險確認", row["加碼判斷"])
        self.assertIn("原倉有浮盈", row["持有多單時"])
        for change in [{"回檔確認": "否"}, {"EMA20上升": "否"}, {"當日量比": "0.99"},
                       {"當日量比": ""}, {"當日量比": "nan"}, {"ATR%": "0"},
                       {"ATR%": "9"}, {"資料狀態": "資料過期"}, {"Error": "offline"},
                       {"距EMA20%": "4"}, {"Last Price": "99", "距EMA20%": "-1"}]:
            with self.subTest(change=change):
                candidate = dict(row, **change)
                describe_advice(candidate)
                self.assertEqual(candidate["本次建議"], "再觀察")
                self.assertNotIn("加碼候選", candidate["加碼判斷"])

    def test_legacy_data_cannot_invent_pullback(self):
        row = self.row(**{"Last Price": "101", "距EMA20%": "1"})
        describe_advice(row)
        self.assertEqual(row["本次建議"], "再觀察")
        row = self.row()
        describe_advice(row)
        self.assertEqual(row["進場型態"], "突破買進")
        self.assertIn("加碼候選", row["持有多單時"])

    def test_pullback_uses_previous_candles_and_rebound_confirmation(self):
        frame = self.frame()
        frame.loc[68, ["open", "high", "low", "close"]] = [100, 101, 98, 99]
        frame.loc[69, ["open", "high", "low", "close"]] = [100, 103, 100, 102]
        metrics = scanner.calculate_metrics(frame)
        self.assertEqual(metrics["回檔確認"], "是")
        self.assertEqual(metrics["EMA20上升"], "是")
        self.assertEqual(metrics["當日量比"], 1)
        frame.loc[69, "close"] = 101
        self.assertEqual(scanner.calculate_metrics(frame)["回檔確認"], "否")
        frame.loc[68, "close"] = 100
        frame.loc[69, ["low", "close"]] = [98, 102]
        self.assertEqual(scanner.calculate_metrics(frame)["回檔確認"], "否")

    def test_long_to_short_selling_does_not_mean_short_entry(self):
        row = self.row(Bias="SHORT", **{"Last Price": "95", "距EMA20%": "-5"})
        describe_advice(row)
        old = self.row()
        describe_advice(old)
        add_comparison([row], {("US", "ARM"): old}, "earlier")
        self.assertEqual(row["本次建議"], "建議減碼／賣出")
        self.assertIn("不直接反手放空", row["持有多單時"])
        self.assertIn("先不進場", row["空手時"])

    def test_unconfirmed_or_failed_data_cannot_recommend_buy(self):
        for changes in [{"資料狀態": "未確認收盤"}, {"資料狀態": "資料過期"},
                        {"Error": "network failure"}, {"前20日高": ""}]:
            row = self.row(**changes)
            describe_advice(row)
            self.assertEqual(row["本次建議"], "再觀察")
            self.assertIn("不依此報告調倉", row["持有多單時"])

    def test_previous_selection_same_day_and_future_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["hot_markets_20260920.csv", "hot_markets_20260924_120000_000001.csv",
                         "hot_markets_20260925.csv", "hot_markets_preview.csv"]:
                scanner.write_csv(root / name, [self.row()])
            previous, date = load_previous_rows(root, root / "hot_markets_20260924_130000_000001.csv")
            self.assertIn(("US", "ARM"), previous)
            self.assertEqual(date, "2026-09-24 12:00:00")

    def frame(self):
        return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=70, tz="UTC"),
                             "open": [100.] * 70, "close": [100.] * 69 + [110.],
                             "high": [101.] * 69 + [999.], "low": [99.] * 69 + [1.],
                             "volume": [100.] * 70})

    def test_prior_levels_exclude_current_candle(self):
        metrics = scanner.calculate_metrics(self.frame())
        self.assertEqual(metrics["前20日高"], 101)
        self.assertEqual(metrics["前60日低"], 99)
        self.assertAlmostEqual(metrics["距前20日高%"], (110 / 101 - 1) * 100)

    def test_recent_flip_remains_after_another_same_direction_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for date, bias in [("20260920", "SHORT"), ("20260924", "LONG")]:
                row = self.row(Bias=bias, **{"Run Date": date})
                scanner.write_csv(root / f"hot_markets_{date}.csv", [row])
            current = self.row()
            add_last_direction_change([current], root, root / "hot_markets_20260925.csv")
            self.assertEqual(current["最近翻向"], "偏空 → 偏多")
            self.assertEqual(current["最近翻向日期"], "20260924")

    def test_crypto_excludes_open_daily_candle(self):
        today = pd.Timestamp.now(tz="UTC").normalize()
        candles = [[int((today - pd.Timedelta(days=days)).timestamp() * 1000), 100, 101, 99, 100, 1]
                   for days in [2, 1, 0]]
        with patch.object(scanner.ccxt, "binanceusdm") as factory:
            factory.return_value.fetch_ohlcv.return_value = candles
            frame = scanner.fetch_binance_ohlcv("BTC/USDT:USDT", 100)
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["timestamp"].iloc[-1], today - pd.Timedelta(days=1))

    def test_total_fetch_failure_preserves_existing_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watch = [{"Market": "US", "Symbol": "ARM", "Name": "Arm", "Binance Symbol": "", "Notes": ""}]
            with patch.object(scanner, "REPORT_DIR", root), \
                 patch.object(scanner, "read_watchlist", return_value=watch), \
                 patch.object(scanner, "fetch_history", side_effect=RuntimeError("offline")), \
                 patch.object(scanner, "load_binance_usdt_futures", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "preserved"):
                    scanner.run_scan(print_progress=False)
            self.assertEqual(list(root.iterdir()), [])

    def test_repeat_scans_preserve_snapshots_and_write_readable_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            watch = [{"Market": "US", "Symbol": "ARM", "Name": "Arm", "Binance Symbol": "", "Notes": ""}]
            frame = self.frame()
            frame.attrs["資料狀態"] = "已收盤"
            with patch.object(scanner, "REPORT_DIR", root), \
                 patch.object(scanner, "read_watchlist", return_value=watch), \
                 patch.object(scanner, "fetch_history", return_value=frame), \
                 patch.object(scanner, "load_binance_usdt_futures", return_value=set()):
                first = scanner.run_scan(print_progress=False)
                second = scanner.run_scan(print_progress=False)
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            text = second.with_suffix(".txt").read_text(encoding="utf-8")
            self.assertIn("有空單", text)
            self.assertIn("較上次", text)
            self.assertIn("本次候選摘要", text)
            self.assertIn("加碼判斷", text)
            with second.open(encoding="utf-8-sig") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["較上次漲跌%"], "+0.00")
            self.assertEqual(row["前20日高"], "101.00")


if __name__ == "__main__":
    unittest.main()
