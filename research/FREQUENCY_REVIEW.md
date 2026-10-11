# 2026-10-11：相似交易頻率比較方法

本次先固定版本、參數與相似頻率範圍，再執行比較；沒有看完結果後增加參數搜尋。相似頻率定義為同區間模擬交易數落在基準的 75%–125%，以基本與加倍成本分別檢查。這是工程篩選標準，不是統計顯著性檢定。

## 版本

| 版本 | 與基準的差異 |
|---|---|
| baseline | 原有 EMA 規則的標準化模擬，停利 0.3%、停損 0.5%、單次反向交叉退出 |
| adx25 | 保留上次固定的 ADX≥25／同向 EMA 斜率版本，觀察新增期間表現 |
| target45 | 只把停利改為 0.45%；進場、停損與反向交叉退出不變 |
| exit_confirm2 | 只把 EMA 出場改成 EMA5 在 EMA20 反方向連續兩根已收盤 K 線；硬停損及停利仍立即依 K 線觸價處理 |
| bb_rsi_range | 1h ADX14<25；15m 收盤從布林20／2標準差的外側回到帶內，回下帶且 RSI14<45 做多，回上帶且 RSI14>55 做空；0.5% 停損、0.45% 停利，或 RSI 回到50時退出；不套用原 EMA 方向及追價限制 |

布林標準差採母體標準差（ddof=0），RSI 用 Wilder 平滑。震盪版本是以指標用途設計的研究候選，不是複製已獲利策略，也不是來源文件對 BTC 的參數推薦。

## 資料與分段

沿用舊快照 2025-09-20 至 2026-10-05，僅追加公開資料至 **2026-10-11 13:15 UTC，結束不含**。先前快照和 10/6 的報告不覆寫。合計 37,109 根 15m K 線、1,160 筆資金費。

- 開發比較：2025-10-01 至 2026-04-01。
- 驗證比較：2026-04-01 至 2026-07-01。
- 較後段歷史檢查：2026-07-01 至 2026-09-28。
- 新增期間：2026-10-05 至 2026-10-11 13:15 UTC。

新期間包含已檢視的交易結果，所以新設計版本不能將它當作未見樣本。ADX 是前次已固定的候選，但同樣只是歷史延伸觀察。模擬新期間比私人 session 更早開始；所有版本在區間結束時強制結算，實際 session 則尚有多單，兩者不是逐筆交易重播。

原有費率、滑價、資金費、暖機、下一根開盤成交及保守的同根停損順序均沿用 [前次方法](README.md)。比較引擎的每日風險、兩倍名目曝險上限與其他執行限制也相同；不以加槓桿改善結果。

採用條件：驗證和較後段歷史區間、基本和加倍成本下，皆須正報酬、Profit Factor>1.1、至少30筆交易、收盤最大回撤不高於基準，並符合75%–125%交易數要求。最新一週只作診斷，不可獨自決定採用。

## 重現

在儲存庫根目錄執行：

```bash
python -m zipfile -e research/market_data_20261011.zip research/data_20261011
python research/frequency_review.py
python research/write_frequency_report.py
python -m unittest discover -s tests -v
```

如需重新下載新增期間，先解壓前次的 `market_data_snapshot.zip` 至 `research/data`，再執行 `python research/frequency_review.py --download`。快照可能受資料源修訂影響，請核對 SHA-256。

`session_diagnostics.py` 需在含私人交易、事件與分鐘監控 CSV 的本機執行。GitHub 僅附去識別彙總，未附私人輸入；取樣浮盈不是逐筆或每秒的真正最高浮盈，沒有用它反推一定能成交的保本價。

## 參考

- [Fidelity：RSI](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI)：RSI 可能在強趨勢中長時間停留極端區，不能看到超買超賣就直接逆勢交易。
- [Fidelity：Bollinger Bands](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/bollinger-bands)：價格與波動帶的關係；本次用回帶內而非僅碰到帶緣作為候選訊號。

資料查閱日期：2026-10-11。來源只支持指標用途，不支持候選策略的績效結論。
