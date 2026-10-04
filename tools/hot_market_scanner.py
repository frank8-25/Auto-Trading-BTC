from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

import ccxt
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.market_advice import (EXTRA_FIELDS, describe_advice, load_previous_rows,
                                add_comparison, add_last_direction_change)
from tools.market_universe import discover_candidates, merge_candidates


WATCHLIST_PATH = Path("watchlists/hot_market_watchlist.csv")
REPORT_DIR = Path("reports/hot_markets")
OUTPUT_FIELDS = [
    "Rank",
    "Market",
    "Symbol",
    "Name",
    "近期趨勢",
    "上期排名",
    "比較日期",
    "白話結論",
    "方向",
    "操作方式",
    "機器人",
    "Bias",
    "Suggested Mode",
    "Binance",
    "Binance Symbol",
    "Notes",
    "Score",
    "R5%",
    "R20%",
    "ATR%",
    "VolX",
    "Trend Strength %",
    "Run Date",
    "Last Timestamp",
    "Last Price",
    "EMA20",
    "EMA60",
    "Error",
]
OUTPUT_FIELDS += EXTRA_FIELDS
OUTPUT_FIELDS += ["候選來源", "候選資料日期", "掃描範圍", "來源狀態"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan hot US/TW stocks and Binance futures candidates.")
    parser.add_argument("--watchlist", default=str(WATCHLIST_PATH), help="CSV watchlist path.")
    parser.add_argument("--days", type=int, default=30, help="History request buffer; scoring uses fixed 5/20-day windows. Default: 30")
    parser.add_argument("--top", type=int, default=30, help="Rows to print after ranking. Default: 30")
    parser.add_argument("--universe", choices=["hybrid", "watchlist", "discovery"], default="hybrid",
                        help="hybrid: watchlist + API stocks; discovery: API stocks only")
    parser.add_argument("--discovery-per-market", type=int, choices=range(1, 101), metavar="1-100", default=30,
                        help="Maximum API stock candidates per market (US/TW). Default: 30")
    args = parser.parse_args()

    run_scan(Path(args.watchlist), args.days, args.top, print_progress=True,
             universe=args.universe, discovery_per_market=args.discovery_per_market)


def run_scan(
    watchlist_path: Path = WATCHLIST_PATH,
    days: int = 30,
    top: int = 30,
    print_progress: bool = True,
    universe: str = "watchlist",
    discovery_per_market: int = 30,
) -> Path:
    if universe not in {"hybrid", "watchlist", "discovery"}:
        raise ValueError("Unknown universe mode")
    watchlist = read_watchlist(watchlist_path) if universe != "discovery" else []
    discovered, notices = discover_candidates(discovery_per_market) if universe != "watchlist" else ([], [])
    watchlist = merge_candidates(watchlist, discovered)
    if universe == "discovery" and not discovered:
        raise RuntimeError("Dynamic stock discovery unavailable; no report produced")
    scope = (f"{universe}：共{len(watchlist)}個候選；API候選{len(discovered)}個；"
             "台灣僅上市普通股，美股僅供應商活躍／漲跌幅榜；非全市場完整排名")
    source_status = "；".join(notices) or ("動態來源完成" if discovered else "僅自選清單")
    if print_progress:
        print(scope)
        print(source_status)
    binance_markets = load_binance_usdt_futures()

    rows = []
    for item in watchlist:
        try:
            frame = fetch_history(item["Market"], item["Symbol"], days)
            metrics = calculate_metrics(frame)
            rows.append(build_row(item, metrics, binance_markets))
            if print_progress:
                print(f"OK {item['Market']} {item['Symbol']}")
        except Exception as exc:
            rows.append(error_row(item, str(exc), binance_markets))
            if print_progress:
                print(f"ERR {item['Market']} {item['Symbol']}: {exc}")
        rows[-1].update({key: item.get(key, "") for key in ("候選來源", "候選資料日期")})
        rows[-1].update({"掃描範圍": scope, "來源狀態": source_status})

    if not rows or all(row.get("Error") for row in rows):
        raise RuntimeError("No usable market data; previous reports were preserved")
    rows.sort(key=lambda row: (not bool(row.get("Error")), safe_float(row["Score"])), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["Rank"] = str(rank)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    scanned_at = datetime.now()
    stamp = scanned_at.strftime("%Y%m%d_%H%M%S_%f")
    output_path = REPORT_DIR / f"hot_markets_{stamp}.csv"
    text_output_path = output_path.with_suffix(".txt")
    previous, comparison_date = load_previous_rows(REPORT_DIR, output_path)
    previous_ranks = {key: int(row["Rank"]) for key, row in previous.items()
                      if row.get("Rank", "").isdigit() and not row.get("Error")}
    add_recent_trend(rows, previous_ranks, comparison_date, hot_rank_limit=10)
    for row in rows:
        row["Run Timestamp"] = scanned_at.isoformat(timespec="seconds")
        describe_advice(row)
    add_comparison(rows, previous, comparison_date)
    add_last_direction_change(rows, REPORT_DIR, output_path)
    csv_staging = output_path.with_suffix(".csv.tmp")
    text_staging = text_output_path.with_suffix(".txt.tmp")
    write_csv(csv_staging, rows)
    write_text_table(text_staging, rows)
    text_staging.replace(text_output_path)
    csv_staging.replace(output_path)  # Only complete reports become comparison candidates.

    if print_progress:
        print("")
        print(f"Wrote {output_path}")
        print(f"Wrote {text_output_path}")
        print("")
        for rank, row in enumerate(rows[:top], start=1):
            print(
                f"{rank}. {row['Market']} {row['Symbol']} | {row['白話結論']} | "
                f"{row['方向變化']} | 較上次 {row['較上次漲跌%'] or '無資料'}%"
            )
    return output_path


def read_watchlist(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return [
            {
                "Market": row.get("Market", "").strip().upper(),
                "Symbol": row.get("Symbol", "").strip(),
                "Name": row.get("Name", "").strip(),
                "Binance Symbol": row.get("Binance Symbol", "").strip(),
                "Notes": row.get("Notes", "").strip(),
            }
            for row in csv.DictReader(handle)
            if row.get("Symbol", "").strip()
        ]


def fetch_history(market: str, symbol: str, days: int) -> pd.DataFrame:
    if market == "CRYPTO":
        return fetch_binance_ohlcv(symbol, max(days + 70, 100))
    return fetch_yahoo_daily(symbol, max(days + 70, 100))


def fetch_yahoo_daily(symbol: str, range_days: int) -> pd.DataFrame:
    query = urllib.parse.urlencode(
        {
            "interval": "1d",
            "range": f"{range_days}d",
            "includePrePost": "false",
            "events": "div,splits",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("chart", {}).get("result")
    if not result:
        raise RuntimeError(payload.get("chart", {}).get("error") or "Yahoo returned no data")
    data = result[0]
    quote = (data.get("indicators", {}).get("quote") or [{}])[0]
    frame = normalize_ohlcv(data.get("timestamp") or [], quote)
    # Exclude the active regular session rather than calling its partial volume final.
    session = data.get("meta", {}).get("currentTradingPeriod", {}).get("regular", {})
    now = pd.Timestamp.now(tz="UTC")
    status = "未確認收盤"
    if session.get("start") and session.get("end"):
        start = pd.Timestamp(session["start"], unit="s", tz="UTC")
        end = pd.Timestamp(session["end"], unit="s", tz="UTC")
        if now < end:
            frame = frame.loc[frame["timestamp"] < start].copy()
        status = "已收盤"
    if not frame.empty and now - frame["timestamp"].iloc[-1] > pd.Timedelta(days=5):
        status = "資料過期"
    frame.attrs["資料狀態"] = status
    return frame


def fetch_binance_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    exchange = ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "future"}})
    rows = exchange.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna().sort_values("timestamp").reset_index(drop=True)
    now = pd.Timestamp.now(tz="UTC")
    frame = frame.loc[frame["timestamp"] + pd.Timedelta(days=1) <= now].copy()
    frame.attrs["資料狀態"] = "已收盤"
    if not frame.empty and now - frame["timestamp"].iloc[-1] > pd.Timedelta(days=2):
        frame.attrs["資料狀態"] = "資料過期"
    return frame


def normalize_ohlcv(timestamps: list[int], quote: dict) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps, unit="s", utc=True),
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", []),
        }
    )
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna().sort_values("timestamp").reset_index(drop=True)


def calculate_metrics(frame: pd.DataFrame) -> dict[str, float | str]:
    if len(frame) < 65:
        raise RuntimeError(f"not enough candles: {len(frame)}")
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"]

    last_price = float(close.iloc[-1])
    if last_price <= 0 or (close <= 0).any() or not math.isfinite(last_price):
        raise ValueError("invalid historical prices")
    if float(volume.tail(25).head(20).mean()) <= 0:
        raise ValueError("insufficient historical volume")
    return_5d = percent_change(close, 5)
    return_20d = percent_change(close, 20)
    volume_ratio = float(volume.tail(5).mean() / volume.tail(25).head(20).mean())

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_pct = float(true_range.rolling(14).mean().iloc[-1] / last_price * 100)

    ema20_series = close.ewm(span=20, adjust=False, min_periods=20).mean()
    ema20 = float(ema20_series.iloc[-1])
    ema60 = float(close.ewm(span=60, adjust=False, min_periods=60).mean().iloc[-1])
    trend_bias = "LONG" if ema20 > ema60 else "SHORT" if ema20 < ema60 else "NONE"
    trend_strength = abs(ema20 / ema60 - 1) * 100 if ema60 else 0.0
    hot_score = (
        abs(return_20d) * 1.3
        + abs(return_5d) * 0.8
        + atr_pct * 1.8
        + max(volume_ratio - 1, 0) * 12
        + trend_strength * 2
    )

    levels = {"資料狀態": frame.attrs.get("資料狀態", "未確認收盤"),
              "距EMA20%": (last_price / ema20 - 1) * 100}
    # Prior three candles only: a declining close touching EMA20, followed by
    # today's bullish close above yesterday's high. Proximity alone is not a rebound.
    pullback = ((close.diff() < 0) & (low <= ema20_series)
                & (high >= ema20_series)).iloc[-4:-1].any()
    rebound = last_price > float(high.iloc[-2]) and last_price > float(frame["open"].iloc[-1])
    prior_volume = float(volume.iloc[-21:-1].mean())
    levels.update({"回檔確認": "是" if pullback and rebound else "否",
                   "EMA20上升": "是" if ema20 > float(ema20_series.iloc[-2]) else "否",
                   "當日量比": float(volume.iloc[-1]) / prior_volume if prior_volume > 0 else float("nan")})
    for period in (20, 60):
        previous = frame.iloc[-period - 1:-1]
        prior_high, prior_low = float(previous["high"].max()), float(previous["low"].min())
        if prior_high <= 0 or prior_low <= 0:
            raise ValueError("invalid historical high/low")
        levels.update({f"前{period}日高": prior_high, f"前{period}日低": prior_low,
                       f"距前{period}日高%": (last_price / prior_high - 1) * 100,
                       f"距前{period}日低%": (last_price / prior_low - 1) * 100})
    return {
        **levels,
        "Last Timestamp": frame["timestamp"].iloc[-1].strftime("%Y-%m-%d"),
        "Last Price": last_price,
        "Return 5D %": return_5d,
        "Return 20D %": return_20d,
        "Volume Ratio 20D": volume_ratio,
        "ATR 14D %": atr_pct,
        "EMA20": ema20,
        "EMA60": ema60,
        "Trend Bias": trend_bias,
        "Trend Strength %": trend_strength,
        "Hot Score": hot_score,
    }


def percent_change(series: pd.Series, periods: int) -> float:
    if len(series) <= periods:
        return 0.0
    return float((series.iloc[-1] / series.iloc[-periods - 1] - 1) * 100)


def load_binance_usdt_futures() -> Optional[set[str]]:
    try:
        exchange = ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "future"}})
        markets = exchange.load_markets()
        return {symbol for symbol, market in markets.items() if market.get("swap") and market.get("quote") == "USDT"}
    except Exception:
        return None


def build_row(item: dict[str, str], metrics: dict[str, float | str], binance_markets: Optional[set[str]]) -> dict[str, str]:
    binance_symbol = item["Binance Symbol"]
    tradable = binance_tradable(item, binance_markets)
    suggested_mode = suggest_mode(metrics)
    readable = readable_advice(str(metrics["Trend Bias"]), suggested_mode, tradable)
    return {
        "Rank": "",
        "Run Date": datetime.now().strftime("%Y-%m-%d"),
        "Market": item["Market"],
        "Symbol": item["Symbol"],
        "Name": item["Name"],
        **readable,
        **{key: fmt(metrics[key]) for key in EXTRA_FIELDS if key in metrics},
        "Bias": str(metrics["Trend Bias"]),
        "Suggested Mode": suggested_mode,
        "Binance": tradable,
        "Binance Symbol": binance_symbol,
        "Notes": item["Notes"],
        "Score": fmt(metrics["Hot Score"]),
        "R5%": fmt(metrics["Return 5D %"]),
        "R20%": fmt(metrics["Return 20D %"]),
        "ATR%": fmt(metrics["ATR 14D %"]),
        "VolX": fmt(metrics["Volume Ratio 20D"]),
        "Trend Strength %": fmt(metrics["Trend Strength %"]),
        "Last Timestamp": str(metrics["Last Timestamp"]),
        "Last Price": fmt(metrics["Last Price"]),
        "EMA20": fmt(metrics["EMA20"]),
        "EMA60": fmt(metrics["EMA60"]),
        "Error": "",
    }


def error_row(item: dict[str, str], error: str, binance_markets: Optional[set[str]]) -> dict[str, str]:
    return {
        "Rank": "",
        "Run Date": datetime.now().strftime("%Y-%m-%d"),
        "Market": item["Market"],
        "Symbol": item["Symbol"],
        "Name": item["Name"],
        **readable_advice("NONE", "WAIT", binance_tradable(item, binance_markets)),
        "Bias": "",
        "Suggested Mode": "WAIT",
        "Binance": binance_tradable(item, binance_markets),
        "Binance Symbol": item["Binance Symbol"],
        "Notes": item["Notes"],
        "Score": "0.00",
        "R5%": "",
        "R20%": "",
        "ATR%": "",
        "VolX": "",
        "Trend Strength %": "",
        "Last Timestamp": "",
        "Last Price": "",
        "EMA20": "",
        "EMA60": "",
        "Error": error,
    }


def suggest_mode(metrics: dict[str, float | str]) -> str:
    bias = str(metrics["Trend Bias"])
    return_5d = float(metrics["Return 5D %"])
    return_20d = float(metrics["Return 20D %"])
    atr_pct = float(metrics["ATR 14D %"])
    trend_strength = float(metrics["Trend Strength %"])

    if bias == "NONE":
        return "WAIT"

    aligned = (bias == "LONG" and return_5d > 0 and return_20d > 0) or (bias == "SHORT" and return_5d < 0 and return_20d < 0)
    conflicted = (bias == "LONG" and return_5d < 0) or (bias == "SHORT" and return_5d > 0)

    if aligned and trend_strength >= 5 and atr_pct <= 8:
        return "TREND"
    if conflicted or atr_pct > 8:
        return "VOLATILE_TAKE_PROFIT"
    if trend_strength >= 3:
        return "VOLATILE_TAKE_PROFIT"
    return "WAIT"


def readable_advice(bias: str, mode: str, tradable: str) -> dict[str, str]:
    direction = {"LONG": "做多", "SHORT": "做空"}.get(bias, "方向不明")
    style = {
        "TREND": "波段",
        "VOLATILE_TAKE_PROFIT": "短進短出",
    }.get(mode, "觀望")
    bot = {"YES": "Binance 有對應合約", "NO": "Binance 無對應合約"}.get(tradable, "合約未確認")

    if mode == "WAIT":
        conclusion = f"{direction}｜目前觀望｜{bot}"
    else:
        conclusion = f"{direction}｜{style}｜{bot}"
    return {
        "白話結論": conclusion,
        "方向": direction,
        "操作方式": style,
        "機器人": bot,
    }


def binance_tradable(item: dict[str, str], binance_markets: Optional[set[str]]) -> str:
    symbol = item["Binance Symbol"]
    if not symbol:
        if item.get("候選來源", "").startswith("API"):
            return "UNKNOWN"  # A stock ticker does not establish a futures mapping.
        return "NO"
    if binance_markets is None:
        return "UNKNOWN"
    return "YES" if symbol in binance_markets else "NO"


def load_previous_ranks(current_path: Path) -> tuple[dict[tuple[str, str], int], str]:
    candidates = sorted(path for path in REPORT_DIR.glob("hot_markets_*.csv") if path != current_path)
    if not candidates:
        return {}, ""
    previous_path = candidates[-1]
    ranks: dict[tuple[str, str], int] = {}
    with previous_path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                ranks[(row["Market"], row["Symbol"])] = int(row["Rank"])
            except (KeyError, TypeError, ValueError):
                continue
    date_text = previous_path.stem.removeprefix("hot_markets_")
    if len(date_text) == 8:
        date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"
    return ranks, date_text


def add_recent_trend(
    rows: list[dict[str, str]],
    previous_ranks: dict[tuple[str, str], int],
    comparison_date: str,
    hot_rank_limit: int,
) -> None:
    for row in rows:
        previous_rank = previous_ranks.get((row["Market"], row["Symbol"]))
        current_rank = int(row["Rank"])
        if not comparison_date:
            recent_trend = "無上期資料"
        elif current_rank > hot_rank_limit:
            recent_trend = "本期未進前10"
        elif previous_rank is not None and previous_rank <= hot_rank_limit:
            recent_trend = "連續熱門"
        else:
            recent_trend = "本期新進"
        row["近期趨勢"] = recent_trend
        row["上期排名"] = str(previous_rank) if previous_rank is not None else "-"
        row["比較日期"] = comparison_date or "-"


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_text_table(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    lines = [f"Hot Markets - {datetime.now():%Y-%m-%d %H:%M:%S}",
             rows[0].get("掃描範圍", ""), rows[0].get("來源狀態", ""),
             "候選名單每次可能不同；排名變化不一定是股價轉強或轉弱。未入選不代表應賣出。",
             "排名是熱度，不是買進優先順序。買賣欄是規則候選；未連接持倉，不會自動調倉。",
             "進場分突破買進／回檔止穩；加碼候選須另確認原倉浮盈、停損及總風險上限。規則尚未經績效回測驗證。",
             "前高前低取當根以前的20／60根日K；距離為目前價÷參考價−1。",
             "較上次是兩次報告價格差，非含息報酬；各市場行情日期可能不同。",
             "舊版建議保留原文；規則版本不同時不把建議差異全歸因於行情。", ""]
    changes = [row for row in rows if row.get("方向變化", "").startswith(("翻多", "翻空"))]
    lines.append("本次候選摘要：")
    candidates = [row for row in rows if row.get("本次建議") == "買進候選"]
    for row in candidates:
        lines.append(f"- {row['Symbol']} {row['Name']}：{row.get('進場型態', '-')}；{row.get('加碼判斷', '-')}")
    if not candidates:
        lines.append("- 本次沒有符合完整條件的買進／加碼候選")
    lines.append("")
    lines.append("本次方向改變：")
    for row in changes:
        lines.append(f"- {row['Symbol']} {row['Name']}：{row['方向變化']}；{row['本次建議']}")
    if not changes:
        lines.append("- 沒有已知的多空翻轉")
    lines.append("")
    for row in rows:
        lines.extend([
            f"{row['Rank']}. {row['Name']} ({row['Symbol']})｜{row['本次建議']}｜{row['方向']}",
            f"   原因：{row['建議原因']}",
            f"   進場型態：{row.get('進場型態', '-')}；加碼判斷：{row.get('加碼判斷', '-')}",
            f"   入選來源：{row.get('候選來源', '自選追蹤')}；候選資料日期 {row.get('候選資料日期') or '-'}",
            f"   上次 → 這次：{row['上次方向']} → {row['方向']}；{row['方向變化']}",
            f"   建議對比：{row['建議變化']}",
            f"   最近一次方向改變：{row.get('最近翻向', '-')}（報告發現時間 {row.get('最近翻向日期', '-')}）",
            f"   上次 {row['比較日期']} 價格 {row['上次價格'] or '-'} → {row.get('Last Price') or '-'}；漲跌 {row['較上次漲跌%'] or '-'}%",
            f"   排名 {row['上期排名']} → {row['Rank']}；分數變化 {row['分數變化'] or '-'}",
            f"   空手：{row['空手時']}",
            f"   有多單：{row['持有多單時']}",
            f"   有空單：{row['持有空單時']}",
            f"   前20日高／低 {row.get('前20日高') or '-'}／{row.get('前20日低') or '-'}；距離 {row.get('距前20日高%') or '-'}%／{row.get('距前20日低%') or '-'}%",
            f"   前60日高／低 {row.get('前60日高') or '-'}／{row.get('前60日低') or '-'}；距離 {row.get('距前60日高%') or '-'}%／{row.get('距前60日低%') or '-'}%",
            f"   距EMA20 {row.get('距EMA20%') or '-'}%；{row['位置狀態']}",
            f"   行情日期 {row.get('Last Timestamp') or '-'}（上次 {row['上次行情日期'] or '-'}）；{row.get('資料狀態') or '無資料'}；{row['交易管道']}",
            "",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fit(value: str, width: int) -> str:
    text = str(value)
    if len(text) > width:
        return text[: max(width - 1, 0)] + "~"
    return text.ljust(width)


def fmt(value: float | str) -> str:
    if isinstance(value, str):
        return value
    if not math.isfinite(value):
        return ""
    return f"{value:.2f}"


def safe_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


if __name__ == "__main__":
    main()
