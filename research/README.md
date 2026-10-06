# BTC 策略檢討與比較

這個資料夾只做研究，不連接帳戶、不下單，也不修改正在執行的交易設定。研究起點是最近一輪測試網紀錄（2026-09-28 至 2026-10-04），並以公開 BTCUSDT 永續合約行情比較三個固定版本。

## 比較版本

| 名稱 | 進場 | 出場 |
|---|---|---|
| `baseline` | 1h EMA20／60 方向與 15m EMA5／20 交叉一致；延續原有 0.15% 防追價條件 | 0.5% 停損、0.3% 停利、反向交叉 |
| `adx25` | 基準條件，再要求 1h ADX14 ≥ 25，且 EMA20 相較三小時前的斜率與進場同向 | 同基準 |
| `adx25_atr` | 同 ADX 版本 | 停損取 1.5 倍 15m ATR14 與價格 0.3% 較大者；若超過 1% 則跳過；目標 2R，保留反向交叉出場 |

先固定以上三個版本再進行第一次比較，沒有針對結果做參數網格搜尋。ADX 25 與 ATR 倍數是研究起點，不是被證實的最佳參數。ADX 只衡量強弱，方向仍由 EMA 判斷；斜率、距離上下限、2R 目標是本專案的實驗設計，不是文獻對 BTC 的推薦。

## 重現結果

Python 3.10 以上，依根目錄 `requirements.txt` 安裝套件。在儲存庫根目錄執行：

```bash
python -m zipfile -e research/market_data_snapshot.zip research/data
python research/strategy_review.py
python -m unittest discover -s tests -v
```

快照只含公開行情、資金費及資料雜湊，不含交易帳戶資料。若想重新向資料源取得同一日期範圍，可執行：

```bash
python research/download_data.py
```

重新下載的行情若有供應商修訂，結果可能改變，請比較 `research/data/manifest.json` 中的 SHA-256。`strategy_review.py` 會產生比較表、各版本模擬交易及權益曲線、候選採用判斷。GitHub 收錄的 `research/results/` 是此次研究結果；模擬交易數字不是個人帳戶交易紀錄。

`review_session.py` 可在持有私人測試網 CSV 的本機執行，用於重算近期 session 的摘要；儲存庫不附私人 CSV，單獨下載本儲存庫不能重算該部分。合成資料測試會檢查此摘要程式的行為。

## 資料與比較方式

- 市場資料：Binance BTCUSDT USDT-M 永續合約，15 分鐘 K 線。下載範圍 2025-09-20 至 2026-10-05（結束不含），共 36,480 根，前段作為指標暖機；資金費共 1,140 筆。
- 2025-10-01 至 2026-04-01：開發比較區間；2026-04-01 至 07-01：驗證比較；07-01 至 09-28：較後段歷史檢查；09-28 至 10-05：已用來診斷問題的一週。
- 日期範圍均為 UTC、結束不含；私人 session 紀錄是本機時間，起迄也不同，因此最近一週模擬不是那 14 筆交易的逐筆重播。
- 每個區間獨立從 10,000 模擬資金開始，沒有跨區間持倉。這是標準化比較，不是實際帳戶餘額。
- 三個版本都以相同風險設定比較：單筆預估風險 1%，每日已實現損失預算 2%，名目部位最多為現金的 2 倍，數量向下取到 0.001 BTC。
- 費用假設每邊 0.05%，滑價每邊 0.025%；另外把兩者同時加倍。這不是帳戶實際費率的校準值。依持倉方向、數量、資金費時點的 mark price 納入實際歷史 funding rate；正費率由多方支付。費率不因成本壓力測試倍增。
- ATR、ADX 使用 Wilder 平滑，先以簡單平均初始化；1h 指標只在完整四根 15m K 線收盤後可用。訊號在收盤可得，最早以次根開盤價加不利滑價成交。
- 停損與停利同根觸及時採停損先發生；開盤跳空穿過停損則使用較差的開盤價。資金費在 K 線開盤先向已有部位結算，再處理交易。區間結束的持倉以最後收盤價、扣費及滑價結算。

## 與現行機器人的差異

這個引擎比較的是標準化的策略規則，不能宣稱完整重現測試網。原機器人逐分鐘輪詢、可能在同一已收盤訊號的後續輪詢中才符合追價限制；本引擎只在下一根開盤評估一次。市場 OHLC 與測試網撮合不同，且本引擎採 K 線內假設成交、沒有模擬 API 失敗、殘倉、流動性、強制平倉、交易所歷史數量限制變化，或原程式的獲利回吐限制及獲利後降風險。EMA 出場可在同一開盤反手，但停損／停利不在同根重新進場。

最大回撤按每根 K 線收盤的未實現損益及費用計算，不是盤中最大回撤；日風控按已實現金額計算，不保證跳空時不超額。資金費與資料完整性已檢查，但不代表外部供應商的資料一定無誤。

## 如何決定是否採用

`decision.json` 使用透明的初步篩選條件：驗證及較後段歷史區間，在基本／加倍成本下皆有至少 30 筆交易、正報酬、Profit Factor > 1.1，且收盤最大回撤不高於基準。這只是此次報告採用的研究篩選門檻，不是正式統計檢定或預先註冊的研究。

即使通過，也不自動切換交易程式，仍需之後未見資料的紙上交易確認。本次三個版本的歷史結果不足以支持上線；不因某一週零交易、零虧損就宣布策略有效。

## 參考資料

- [Fidelity：ADX](https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX)：趨勢強弱的解讀。
- [Fidelity：ATR](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr)：波動度與隨波動調整的停損。
- [Freqtrade：Backtesting](https://www.freqtrade.io/en/stable/backtesting/)：K 線回測需要明確的成交順序與價格假設。本專案使用自建引擎，不是 Freqtrade 執行結果。
- [Freqtrade：Lookahead analysis](https://www.freqtrade.io/en/latest/lookahead-analysis/)：留意指標與訊號使用未來資料；本次以截斷／擾動測試檢查自建特徵，未宣稱已跑過 Freqtrade 的 lookahead 命令。
- [Bailey & López de Prado：Determining Optimal Trading Rules without Backtesting](https://arxiv.org/abs/1408.1159)：歷史校準可能造成過度擬合，不能直接推論未來結果。
- [Binance：Kline data](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/market-data/rest-api/Kline-Candlestick-Data)、[USD-M 市場資料](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)：使用 `/fapi/v1/klines` 及 `/fapi/v1/fundingRate`。

資料查閱與研究日期：2026-10-06。
