"""Turn the research outputs into a public project record; no private journals read."""
from pathlib import Path
import json
import pandas as pd

ROOT=Path(__file__).resolve().parent
rows=pd.read_csv(ROOT/'results/comparison.csv')
session=json.loads((ROOT/'results/session_review.json').read_text(encoding='utf-8'))
names={'baseline':'EMA 基準','adx25':'ADX＋同向斜率','adx25_atr':'ADX＋同向斜率＋ATR 出場'}
windows={'development':'2025/10–2026/03','validation':'2026/04–06','historical_check':'2026/07/01–09/27','diagnostic_week':'2026/09/28–10/04'}
text='''# 2026-10-06｜最近一輪交易檢討與策略比較

這次先從最近完整的測試網 session（9 月 28 日至 10 月 4 日）檢查問題，再用一年公開行情比較原有規則與兩種改法。正式盤交易檔沒有成交紀錄，因此本次不把測試網結果描述成正式盤績效。

## 這輪交易出了什麼問題

'''
text+=f"這輪共 {session['trades']} 筆平倉，{session['gross_wins']} 筆毛利為正、{session['gross_losses']} 筆毛利為負，毛利勝率 {session['gross_win_rate_pct']:.2f}%，毛利 Profit Factor 約 {session['gross_profit_factor']:.2f}。5 筆是停利出場，9 筆是 EMA 反向出場。毛利合計已為負，不能只把結果歸因於手續費。\n\n"
text+=f"同期間帳戶報表裡，手續費約相當於帳戶淨虧損的 {session['commission_share_of_account_net_loss_pct']:.1f}%。這讓我優先檢查交易頻率與單次目標相對成本是否合理。不過這是帳戶層級資料，可能包含其他交易；逐筆 CSV 則是毛利，兩者不能直接混作每筆策略淨利。公開文件只保留摘要，不放帳戶餘額、訂單編號與原始交易紀錄。\n\n"
text+='''## 為什麼先試這兩種修改

現有架構是 1 小時 EMA 判斷方向、15 分鐘 EMA 交叉進場。EMA 方向一致不一定代表趨勢夠強，所以第一個版本加上 ADX14 ≥ 25 與同向均線斜率，希望少做較弱的交叉。第二個版本再用 ATR 設定停損和 2R 目標，檢查固定 0.3% 停利是否太容易被成本侵蝕。

ADX 和 ATR 的用途參考 [Fidelity 的 ADX 說明](https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX)及 [ATR 說明](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr)。這些資料說明指標用途，沒有證明這組設定在 BTC 有效。三個版本的具體条件、成本與成交假設見 [研究方法](../research/README.md)。

## 含成本比較結果

每段都以 10,000 模擬資金獨立起算，使用同一套部位規則、費率、滑價及歷史資金費。數字是標準化模擬結果，不是我的帳戶報酬，也不是測試網逐筆重播。表中日期為 UTC，與 session 的本機起迄時間不同。

| 區間 | 版本 | 交易數 | 模擬淨報酬 | 收盤最大回撤 |
|---|---|---:|---:|---:|
'''
for row in rows[rows.cost_factor==1].itertuples():
    text+=f'| {windows[row.window]} | {names[row.variant]} | {row.trades} | {row.return_pct:+.2f}% | {row.max_close_drawdown_pct:.2f}% |\n'
text+='''
ADX 版本在較長的三段期間減少了交易與回撤，但報酬仍全部為負。ATR 版本沒有一致優於只加 ADX 的版本：某些期間少虧一些，另一些期間反而更差。因此這次沒有把「虧損縮小」寫成「已找到有獲利能力的策略」。

最近一週兩個候選版本都沒有交易。零交易不能用來證明訊號準確，更不能把已經看過的這週紀錄當成獨立樣本外驗證。

## 把成本加倍後再看一次

下表只列較後段歷史檢查（2026/07/01–09/27），費率與滑價皆為基本假設的兩倍；資金費仍按歷史實際費率計入。

| 版本 | 模擬淨報酬 | 收盤最大回撤 |
|---|---:|---:|
'''
for row in rows[(rows.window=='historical_check')&(rows.cost_factor==2)].itertuples():
    text+=f'| {names[row.variant]} | {row.return_pct:+.2f}% | {row.max_close_drawdown_pct:.2f}% |\n'
text+='''
成本提高後，兩個候選版本仍無法通過正報酬要求。所有分段、成本情境均保留於 [比較表](../research/results/comparison.csv)，沒有只挑最好的一段呈現。

## 這次實際改了什麼

新增獨立研究引擎，提供原有 EMA 規則的標準化基準、ADX 過濾與 ATR 出場兩個候選版本；資料下載、指標、下一根開盤成交、資金費、費用與滑價都有明確實作。研究程式與正在執行的交易程式分開，沒有更動 live/testnet 的進出場參數，也沒有向交易所送單。

檢查包含未來 K 線擾動不影響先前指標、未完成小時不提前進入 1h 特徵、資料缺口、停損停利同根觸及、開盤跳空、資金費與現金對帳，以及每日額度限制。這些是程式行為測試，不能代替策略績效驗證。

## 採用決定與下一步

**本次沒有候選版本通過採用條件，因此不部署到交易程式。** 判斷紀錄保存在 [decision.json](../research/results/decision.json)。ADX 可以保留作為下一輪研究的方向，但目前只證明它在這份歷史資料上減少部分虧損，沒有證明未來也會如此。

下一輪先用未見資料的紙上觀察累積淨損益和訊號分布，並核對公開行情模擬與測試網撮合的差異。若要改成更慢的進場週期或其他策略，應另立比較版本，不持續在這批結果上調到好看為止。[Bailey 與 López de Prado 的研究](https://arxiv.org/abs/1408.1159)也提醒，反覆用歷史結果校準可能造成過度擬合。

回測仍受 K 線內成交順序、滑價與執行模型影響。這次採用下一根開盤成交、同根先停損的假設，並公開與實際機器人的差異；方法參考 [Freqtrade 的回測說明](https://www.freqtrade.io/en/stable/backtesting/)。並未宣稱已執行 Freqtrade 的檢查命令。

重現方式、公開行情快照及來源連結見 [research/README.md](../research/README.md)。
'''
destination=ROOT.parent/'docs/strategy_review_20261006.md'
destination.parent.mkdir(parents=True,exist_ok=True)
destination.write_text(text.replace('条件','條件'),encoding='utf-8')
print('Wrote docs/strategy_review_20261006.md')
