"""Explain scanner observations; never sends orders or assumes a position."""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path


ADVICE_VERSION = "2"
EXTRA_FIELDS = [
    "本次建議", "建議原因", "上次建議", "建議變化", "上次方向", "方向變化",
    "上次價格", "較上次漲跌%", "排名變化", "分數變化", "上次行情日期",
    "空手時", "持有多單時", "持有空單時", "交易管道", "資料狀態",
    "前20日高", "距前20日高%", "前20日低", "距前20日低%",
    "前60日高", "距前60日高%", "前60日低", "距前60日低%",
    "距EMA20%", "位置狀態", "最近翻向", "最近翻向日期", "Run Timestamp", "Advice Version",
    "進場型態", "加碼判斷", "回檔確認", "當日量比", "EMA20上升",
]


def number(row, name):
    try:
        value = float(row[name])
        return value if math.isfinite(value) else None
    except (KeyError, ValueError, TypeError):
        return None


def direction(value):
    return {"LONG": "偏多", "SHORT": "偏空", "NONE": "方向不明"}.get(value, "無資料")


def describe_advice(row):
    bias = row.get("Bias", "")
    price, ema = number(row, "Last Price"), number(row, "EMA20")
    atr, volume = number(row, "ATR%"), number(row, "VolX")
    high, low = number(row, "前20日高"), number(row, "前20日低")
    extension = number(row, "距EMA20%")
    advice, reason, position = "再觀察", "條件尚未明確", "資料不足"
    setup = "未成立"
    if row.get("Error") or any(value is None for value in (price, ema, atr, volume, high, low, extension)):
        reason = "行情或前高前低資料不足，暫不判斷買賣"
    elif min(price, ema, atr, high, low) <= 0 or volume < 0 or high < low:
        reason = "行情數值異常，暫不判斷買賣"
    elif row.get("資料狀態") != "已收盤":
        reason = "行情未確認收盤或已過期，等資料確認"
    else:
        position = "突破前20日高" if price > high else "跌破前20日低" if price < low else "區間內"
        # Transparent experimental rules, not calibrated probabilities.
        if bias == "SHORT" and price < ema:
            advice, reason = "建議減碼／賣出", "趨勢偏空，價格也低於近期平均；持有多單先評估減碼"
        elif bias == "LONG" and price >= ema and price > high and volume >= 1.2 and 0 <= extension <= 2 * atr and atr <= 8:
            advice, reason = "買進候選", "偏多、突破前高且放量，離均線未超過兩倍日常波動"
            setup = "突破買進"
        elif (bias == "LONG" and price >= ema and price <= high and 0 <= extension <= atr and atr <= 8
              and row.get("回檔確認") == "是" and row.get("EMA20上升") == "是"
              and (number(row, "當日量比") or 0) >= 1):
            advice, reason = "買進候選", "偏多回檔觸及均線後，收盤突破昨日高點；均線上升、量能確認且未遠離均線"
            setup = "回檔止穩"
        elif bias == "LONG" and extension > 2 * atr:
            reason = "雖然偏多，但已離均線太遠；等價格回來，不急著追"
        elif bias == "LONG" and price < ema:
            reason = "中期偏多，但價格已跌回均線下方，先等止穩"
        elif bias == "SHORT":
            reason = "中期偏空，但價格正在反彈；先看是否轉強"
        elif bias == "LONG" and atr > 8:
            reason = "日常波動超過8%，等待波動收斂"
        elif bias == "LONG" and price <= high:
            reason = "方向偏多；突破前高與回檔止穩進場條件都尚未完整成立"
        elif bias == "LONG":
            reason = "已突破，但量能或波動條件尚未通過"
    row.update({"本次建議": advice, "建議原因": reason, "位置狀態": position,
                "Advice Version": ADVICE_VERSION, "進場型態": setup})
    valid = row.get("資料狀態") == "已收盤" and not row.get("Error") and position != "資料不足"
    row["空手時"] = "可考慮小量買進，先設定停損" if advice == "買進候選" else "先不進場，等待條件成立"
    row["持有多單時"] = "可續抱觀察，保留停損" if valid and bias == "LONG" and price >= ema else "檢查停損，評估減碼"
    row["加碼判斷"] = "暫不加碼" if valid else "資料不足，暫不判斷"
    if advice == "買進候選":
        row["加碼判斷"] = "加碼候選（待持倉風險確認）"
        row["持有多單時"] = "加碼候選：僅在原倉有浮盈、已設定停損且加碼後總風險未超過原定上限時評估小量加碼；未確認前續抱觀察"
    row["持有空單時"] = "偏多不利空單，評估回補或減碼" if valid and bias == "LONG" else "檢查停損，持續觀察"
    if not valid:
        row["持有多單時"] = row["持有空單時"] = "資料不足，依原停損管理，不依此報告調倉"
    row["交易管道"] = {"YES": "Binance 有對應合約", "NO": "Binance 無對應合約",
                          "UNKNOWN": "Binance 對應合約未確認"}.get(row.get("Binance"), "未確認")
    row["機器人"] = row["交易管道"]
    row["方向"] = direction(bias)
    row["白話結論"] = f"{advice}｜{direction(bias)}｜{reason}"


def load_previous_rows(directory: Path, current_path: Path):
    # Exclude previews and future reports. Legacy daily files remain readable.
    pattern = re.compile(r"hot_markets_\d{8}(?:_\d{6}_\d{6})?\.csv$")
    candidates = sorted(p for p in directory.glob("hot_markets_*.csv")
                        if pattern.fullmatch(p.name) and p.name < current_path.name)
    if not candidates:
        return {}, ""
    previous = candidates[-1]
    with previous.open(encoding="utf-8-sig", newline="") as handle:
        rows = {(r["Market"], r["Symbol"]): r for r in csv.DictReader(handle)}
    stamp = previous.stem.removeprefix("hot_markets_")
    date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
    if len(stamp) > 8:
        date += f" {stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}"
    return rows, date


def add_comparison(rows, previous, comparison_date):
    for row in rows:
        old = previous.get((row["Market"], row["Symbol"]))
        row.update({"比較日期": comparison_date or "-", "上次建議": "無上期資料",
                    "上次方向": "無資料", "方向變化": "首次觀察", "建議變化": "首次觀察",
                    "上次價格": "", "較上次漲跌%": "", "排名變化": "", "分數變化": "",
                    "上次行情日期": "", "上期排名": "-"})
        if not old:
            continue
        old_bias, bias = old.get("Bias", ""), row.get("Bias", "")
        old_advice = old.get("本次建議") or ("舊版：" + old.get("白話結論", "未記錄"))
        row.update({"上次建議": old_advice, "上次方向": direction(old_bias),
                    "上次價格": old.get("Last Price", ""), "上期排名": old.get("Rank", "-"),
                    "上次行情日期": old.get("Last Timestamp", "")})
        valid = not row.get("Error") and not old.get("Error") and bias in {"LONG", "SHORT"} and old_bias in {"LONG", "SHORT"}
        confirmed = row.get("資料狀態") == "已收盤"
        if not valid:
            row["方向變化"] = "資料不足，無法比較"
        elif old_bias == bias:
            row["方向變化"] = f"維持{direction(bias)}"
        else:
            row["方向變化"] = "翻多：偏空 → 偏多" if bias == "LONG" else "翻空：偏多 → 偏空"
            if not confirmed:
                row["方向變化"] += "（待資料確認）"
            else:
                key = "持有空單時" if bias == "LONG" else "持有多單時"
                row[key] = "方向翻多，原空單評估回補／減碼；不直接反手追多" if bias == "LONG" else "方向翻空，原多單評估減碼／賣出；不直接反手放空"
        if old.get("Advice Version") != row.get("Advice Version"):
            row["建議變化"] = f"{old_advice} → {row['本次建議']}（規則版本不同）"
        elif old_advice == row["本次建議"]:
            row["建議變化"] = f"維持{row['本次建議']}"
        else:
            row["建議變化"] = f"{old_advice} → {row['本次建議']}"
        if row.get("Error") or old.get("Error"):
            continue
        for target, field, ratio in [("較上次漲跌%", "Last Price", True),
                                     ("分數變化", "Score", False), ("排名變化", "Rank", False)]:
            a, b = number(old, field), number(row, field)
            if a is not None and b is not None and (not ratio or a > 0):
                change = (b / a - 1) * 100 if ratio else a - b if field == "Rank" else b - a
                row[target] = f"{change:+.2f}"


def add_last_direction_change(rows, directory, current_path):
    """Retain the most recent observed flip even when consecutive scans agree."""
    history = []
    pattern = re.compile(r"hot_markets_\d{8}(?:_\d{6}_\d{6})?\.csv$")
    for path in sorted(directory.glob("hot_markets_*.csv")):
        if not pattern.fullmatch(path.name) or path.name >= current_path.name:
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            history.extend(csv.DictReader(handle))
    last, changes = {}, {}
    for row in [*history, *rows]:
        bias = row.get("Bias")
        if row.get("Error") or bias not in {"LONG", "SHORT"}:
            continue
        if row.get("資料狀態") not in (None, "", "已收盤"):
            continue
        key = (row["Market"], row["Symbol"])
        if key in last and last[key] != bias:
            changes[key] = (f"{direction(last[key])} → {direction(bias)}",
                            row.get("Run Timestamp") or row.get("Run Date", "日期未記錄"))
        last[key] = bias
    for row in rows:
        change, date = changes.get((row["Market"], row["Symbol"]), ("歷史報告未見翻向", "-"))
        row["最近翻向"], row["最近翻向日期"] = change, date
