"""Offline synthetic scenarios; no network calls or account data."""
from pathlib import Path
from tools.market_advice import describe_advice


def main():
    base = {"Bias": "LONG", "Last Price": "105", "EMA20": "100",
            "ATR%": "3", "VolX": "1.5", "前20日高": "104", "前20日低": "90",
            "距EMA20%": "5", "資料狀態": "已收盤", "Binance": "UNKNOWN", "Error": ""}
    cases = [
        ("突破成立", {}),
        ("回檔止穩", {"Last Price": "101", "距EMA20%": "1", "回檔確認": "是",
                       "EMA20上升": "是", "當日量比": "1.1"}),
        ("價格過熱", {"Last Price": "120", "距EMA20%": "20"}),
        ("趨勢偏空", {"Bias": "SHORT", "Last Price": "95", "距EMA20%": "-5"}),
        ("未確認收盤", {"資料狀態": "未確認收盤"}),
        ("資料缺漏", {"前20日高": ""}),
    ]
    lines = ["# 離線規則展示（合成資料）", "",
             "以下價格與指標為人工設定的測試情境，不是真實行情、回測或交易績效。",
             "回檔確認等欄位在此直接設定；正式掃描時由日 K 計算，其計算另有測試。", "",
             "| 情境 | 判斷 | 進場型態 | 加碼判斷 | 原因 |", "|---|---|---|---|---|"]
    for title, changes in cases:
        row = dict(base, **changes)
        describe_advice(row)
        lines.append("| " + " | ".join([title, row["本次建議"], row["進場型態"], row["加碼判斷"], row["建議原因"]]) + " |")
    lines += ["", "加碼候選仍須另確認原倉浮盈、停損及總風險；本程式不讀取持倉，也不下單。", ""]
    destination = Path(__file__).resolve().parent / "examples" / "demo_report.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")
    print("Generated examples/demo_report.md (synthetic data; no network)")


if __name__ == "__main__":
    main()
