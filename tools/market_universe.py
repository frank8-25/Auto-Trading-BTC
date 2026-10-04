"""Public stock discovery. Does not use account credentials or place orders."""
import math
import re
from datetime import datetime, timedelta, timezone

import requests


def fetch_json(url, params=None):
    response = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    return response.json()


def value(raw):
    try:
        result = float(str(raw).replace(",", ""))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def interleave(groups, limit):
    result, seen = [], set()
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index >= len(group):
                continue
            item = group[index]
            key = (item["Market"], item["Symbol"])
            if key not in seen:
                result.append(item)
                seen.add(key)
            if len(result) == limit:
                return result
    return result


def candidate(market, symbol, name, source, date):
    return {"Market": market, "Symbol": symbol, "Name": name,
            "Binance Symbol": "", "Notes": "", "候選來源": source, "候選資料日期": date}


def discover_us(limit):
    groups, warnings = [], []
    for screen, label in [("most_actives", "成交活躍"), ("day_gainers", "漲幅榜"), ("day_losers", "跌幅榜")]:
        try:
            payload = fetch_json("https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved",
                                 {"scrIds": screen, "count": 100, "formatted": "false"})
            quotes = payload["finance"]["result"][0]["quotes"]
            group = []
            for quote in quotes:
                price, volume = value(quote.get("regularMarketPrice")), value(quote.get("regularMarketVolume"))
                timestamp = value(quote.get("regularMarketTime"))
                symbol = quote.get("symbol", "")
                if (quote.get("quoteType") != "EQUITY" or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol)
                        or quote.get("exchange") not in {"NYQ", "NMS", "NGM", "NCM", "ASE", "BTS"}
                        or price is None or volume is None or price < 5 or price * volume < 20_000_000
                        or timestamp is None):
                    continue
                date = datetime.fromtimestamp(timestamp, timezone.utc)
                age = datetime.now(timezone.utc) - date
                if age > timedelta(days=5) or age < -timedelta(minutes=5):
                    continue
                group.append(candidate("US", symbol, quote.get("shortName") or symbol,
                                       f"API：Yahoo美股{label}", date.isoformat()))
            if not group:
                warnings.append(f"美股{label}無符合流動性／時效條件的候選")
            groups.append(group)
        except Exception as exc:
            warnings.append(f"美股{label}來源失敗：{type(exc).__name__}")
    return interleave(groups, limit), warnings


def discover_tw(limit):
    data = fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    eligible = []
    today = datetime.now(timezone(timedelta(hours=8))).date()
    for row in data:
        code = str(row.get("Code", ""))
        price, turnover, change = value(row.get("ClosingPrice")), value(row.get("TradeValue")), value(row.get("Change"))
        if not re.fullmatch(r"[1-9]\d{3}", code) or price is None or turnover is None or change is None:
            continue
        if price < 10 or turnover < 100_000_000 or price - change <= 0:
            continue
        try:
            raw_date = str(row["Date"])
            date = datetime(int(raw_date[:3]) + 1911, int(raw_date[3:5]), int(raw_date[5:7])).date()
        except (KeyError, ValueError):
            continue
        if not 0 <= (today - date).days <= 5:
            continue
        eligible.append((row, turnover, change / (price - change) * 100, date.isoformat()))
    groups = []
    for label, key, reverse in [("成交額榜", 1, True), ("漲幅榜", 2, True), ("跌幅榜", 2, False)]:
        ordered = sorted(eligible, key=lambda item: item[key], reverse=reverse)
        groups.append([candidate("TW", item[0]["Code"] + ".TW", item[0]["Name"],
                                 f"API：證交所上市{label}", item[3]) for item in ordered
                       if key != 2 or (item[2] > 0 if reverse else item[2] < 0)])
    result = interleave(groups, limit)
    return result, [] if result else ["台灣上市資料無符合流動性／時效條件的候選"]


def discover_candidates(limit=30):
    if not 1 <= limit <= 100:
        raise ValueError("discovery-per-market must be between 1 and 100")
    candidates, warnings = [], []
    for label, discover in [("US", discover_us), ("TW", discover_tw)]:
        try:
            items, notices = discover(limit)
            candidates.extend(items)
            warnings.extend(notices)
        except Exception as exc:
            warnings.append(f"{label}動態來源失敗：{type(exc).__name__}")
    return candidates, warnings


def merge_candidates(watchlist, discovered):
    merged = {}
    for item in watchlist:
        merged[(item["Market"], item["Symbol"])] = {**item, "候選來源": "自選追蹤", "候選資料日期": ""}
    for item in discovered:
        key = (item["Market"], item["Symbol"])
        if key in merged:
            merged[key]["候選來源"] += "；" + item["候選來源"]
            merged[key]["候選資料日期"] = item["候選資料日期"]
        else:
            merged[key] = dict(item)
    return list(merged.values())
