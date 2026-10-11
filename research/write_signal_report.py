"""Render the checked-in event-study aggregates; no private inputs."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
rows = pd.read_csv(ROOT / 'research/signal_results_20261011/summary.csv')
labels = {'development':'2025/10–2026/03', 'validation':'2026/04–06',
          'historical_check':'2026/07/01–09/27', 'diagnostic_week':'2026/09/28–10/04',
          'new_period':'2026/10/05–10/11'}
table = ['| 期間 | 分鐘 | 訊號數 | 方向命中率 | 平均毛報酬 bp | 平均淨報酬 bp | 成本加倍淨報酬 bp |',
         '|---|---:|---:|---:|---:|---:|---:|']
intervals = ['| 期間 | 分鐘 | 毛報酬探索區間 bp | 淨報酬探索區間 bp |', '|---|---:|---:|---:|']
for r in rows[rows.group == 'all'].itertuples():
    table.append(f'| {labels[r.window]} | {r.horizon_minutes} | {r.signals} | {r.direction_hit_pct:.1f}% | {r.gross_mean_bp:+.2f} | {r.net_mean_bp:+.2f} | {r.stress_net_mean_bp:+.2f} |')
    if pd.notna(r.gross_ci_low_bp):
        intervals.append(f'| {labels[r.window]} | {r.horizon_minutes} | [{r.gross_ci_low_bp:.2f}, {r.gross_ci_high_bp:.2f}] | [{r.net_ci_low_bp:.2f}, {r.net_ci_high_bp:.2f}] |')

report = '''# 2026-10-11｜先檢查 EMA 進場後，價格到底有沒有照預期走

前一輪調整停利與出場確認，都只讓虧損稍微縮小。這次往前退一步：如果先不加出場規則，EMA 訊號出現後的價格，有沒有穩定朝預期方向走？

## 目前看到的結果

**在這份歷史資料、15／30／60 分鐘的固定觀察長度與既定成本假設下，還沒有看到穩定且足以支付成本的 EMA 進場優勢。** 手續費與滑價確實很重，但不能因此直接認定「策略本來有效，只要降低費用就能獲利」。

4–6 月的 15 分鐘平均毛報酬約 +2.83 bp，方向命中率 58.5%；到了 7–9 月，同樣長度的平均毛報酬變成 -0.86 bp。即使保留前一段的正值，也遠低於價格不動時約 15 bp 的基本來回成本。60 分鐘的結果也沒有穩定改善。

10/5 起的短週，15 分鐘方向命中率達 70%，但只有 10 個訊號，平均毛報酬約 +2.85 bp，淨報酬仍約 -12.15 bp。這說明方向猜對的比例，和扣費後有沒有剩下利潤，是兩件需要分開檢查的事。

## 怎麼比較

沿用原 EMA 進場條件，只讀已收盤 K 線，在下一根開盤評估進場，再看 15、30、60 分鐘後的開盤價格。三個長度使用同一批完整訊號，不加入停利、停損或資金配置。成本含每邊 0.05% 手續費、0.025% 滑價與持有期間的歷史資金費，另測試手續費和滑價加倍。

以下是**每個訊號、每單位進場名目金額**的平均報酬；1 bp = 0.01%。它不是帳戶績效，亦不能把有重疊的訊號報酬加總。最新區間截止於 10/11 13:15 UTC，終點不含。

TABLE

## 這些正負值有多可靠？

較長三段期間以連續 7 日區塊重抽樣，提供探索性的 95% 平均報酬區間。4–6 月的 15 分鐘毛報酬區間高於零，但這是多組檢查中的一組，沒有做多重比較校正，而且在後段沒有重現；不能單獨當成穩定優勢的證明。較長三段的淨報酬區間皆低於零。

INTERVALS

兩個短週樣本不足，不提供這類區間。前面的資料也已在舊研究中看過，所以本次是歷史診斷，不宣稱完成了新模型的獨立樣本外驗證。

## 分組與對照也保留

完整表另列多空、ADX 高低及波動高低分組。波動分界只用開發期間設定，沒有看到後段結果再調。整體另附按訊號多空比例加權的「所有合格時點」毛報酬對照，協助辨認市場本身方向的影響；它未配對其他條件，不是可直接交易的策略。

分組用途是找下一個值得驗證的問題，不是看到哪一格較好就立刻只交易那一格。全部結果與公開行情推導的逐訊號資料均保留，沒有只留下表現最好的一段。

## 接下來的決定

本次沒有接上機器學習，也沒有更改交易執行。先把訊號分析工具與結果留下，避免在進場品質還不清楚時繼續調出場參數。

若下一階段做簡單模型，應先固定預測目標、輸入與比較標準，再用後續未見資料檢查它是否能超過原 EMA 和簡單對照；同時報告交易頻率，不能只靠少做交易來宣稱改善。本次結果不支持直接增加部位，也不表示反向交易就會有效。

這項研究受到「先研究預測，再考慮交易」的方向啟發，並非複製 Alex Gerko 或 XTX 的專有策略。[XTX 官方研究團隊介紹](https://www.xtxmarkets.com/careers/)說明其使用統計模型與機器學習產生價格預測，但沒有提供足以重現其完整交易策略的細節。

- [完整方法與重現步驟](../research/SIGNAL_QUALITY.md)
- [全部分組結果](../research/signal_results_20261011/summary.csv)
- [公開行情推導的逐訊號資料](../research/signal_results_20261011/events.csv)
- [資料雜湊與設定](../research/signal_results_20261011/method.json)
'''
report = report.replace('TABLE', '\n'.join(table)).replace('INTERVALS', '\n'.join(intervals))
(ROOT / 'docs/signal_quality_20261011.md').write_text(report, encoding='utf-8')
print('Wrote docs/signal_quality_20261011.md')
