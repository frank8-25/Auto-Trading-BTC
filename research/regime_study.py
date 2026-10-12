"""Fixed regime experiments and past-only monthly selection. Never places orders."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.strategy_review import features, volatility, entry_side, Variant, run

ROOT = Path(__file__).resolve().parent
NAMES = ['baseline', 'ema_atr', 'breakout20', 'breakout40', 'pullback',
         'range_reversion', 'switch20', 'switch40', 'cash']
PERIODS = [('development','2025-10-01','2026-04-01'),
           ('validation','2026-04-01','2026-07-01'),
           ('historical_check','2026-07-01','2026-09-28'),
           ('diagnostic','2026-09-28','2026-10-11 13:15:00')]


def regime_features(candles):
    f = features(candles)
    h = candles.resample('1h').agg(dict(open='first',high='max',low='min',close='last',volume='sum'))
    h = h[candles.close.resample('1h').count() == 4].copy()
    h['h_atr'], _ = volatility(h)
    fast = h.close.ewm(span=20,adjust=False,min_periods=20).mean()
    h['pullback_signal'] = np.select([
        (h.close > fast) & (h.close.shift(1) <= fast.shift(1)),
        (h.close < fast) & (h.close.shift(1) >= fast.shift(1))], [1,-1], default=0)
    for length in (10,20,40):
        high = h.high.shift(1).rolling(length).max()
        low = h.low.shift(1).rolling(length).min()
        h[f'breakout{length}'] = np.select([h.close > high,h.close < low],[1,-1],default=0)
    h.index += pd.Timedelta(hours=1)
    extra = h[['h_atr','pullback_signal','breakout10','breakout20','breakout40']]
    result = pd.merge_asof(f,extra,left_index=True,right_index=True,direction='backward')
    result['hour_event'] = result.index.minute == 0
    return result


class Policy:
    def __init__(self, name):
        if name not in NAMES:
            raise ValueError(name)
        self.name = name

    @staticmethod
    def regime(s):
        return 'unknown' if not np.isfinite(s['adx']) else ('trend' if s['adx'] >= 25 else
               'range' if s['adx'] < 20 else 'transition')

    def branch(self, s):
        if self.name.startswith('switch'):
            return 'breakout' + self.name[-2:] if self.regime(s) == 'trend' else 'range_reversion'
        return self.name

    def entry(self, s, price):
        name, regime = self.branch(s), self.regime(s)
        if name == 'cash':
            return 0
        if name == 'ema_atr':
            return entry_side(s,Variant('baseline'),price)
        if name == 'range_reversion':
            return int(s['range_signal']) if regime == 'range' else 0
        if regime != 'trend' or not s['hour_event']:
            return 0
        side = s['pullback_signal'] if name == 'pullback' else s[name]
        return int(side) if np.isfinite(side) and side == s['bias'] else 0

    def distance(self, s, price):
        name = self.branch(s)
        if name == 'cash':
            return None
        if name == 'ema_atr':
            raw, floor, cap, reward = 2*s['atr']/price,.004,.02,2.5
        elif name == 'range_reversion':
            raw, floor, cap, reward = 2*s['atr']/price,.004,.015,1.5
        elif name == 'pullback':
            raw, floor, cap, reward = 1.5*s['h_atr']/price,.005,.025,2.5
        else:
            raw, floor, cap, reward = 2*s['h_atr']/price,.006,.03,3
        if not np.isfinite(raw) or raw > cap:
            return None
        stop = max(raw,floor)
        return stop,stop*reward

    @staticmethod
    def exit_reason(s, p, when):
        # Use the entry branch, even if the current regime has changed.
        name, side = p['branch'],p['side']
        hours = 6 if name == 'range_reversion' else 48 if name.startswith('breakout') else 24
        if when - p['time'] >= pd.Timedelta(hours=hours):
            return 'TIME_EXIT'
        if name == 'range_reversion' and side*(s['rsi']-50) >= 0:
            return 'RSI_MID_EXIT'
        if name.startswith('breakout') and s['hour_event'] and s['breakout10'] == -side:
            return 'CHANNEL_EXIT'
        if name == 'pullback' and s['hour_event'] and s['bias'] == -side:
            return 'TREND_EXIT'
        return None


def choose_month(monthly, target):
    target = pd.Timestamp(target)
    start = target - pd.DateOffset(months=3)
    dates = pd.to_datetime(monthly.start,utc=True).dt.tz_localize(None)
    history = monthly[(dates >= start) & (dates < target)]
    choices = []
    for name in NAMES:
        if name == 'cash':
            continue
        scores = {}
        for cost in (1,2):
            group = history[(history.variant == name) & (history.cost_factor == cost)]
            if len(group) != 3:
                break
            gain, loss = group.positive_net.sum(),group.negative_net_abs.sum()
            pf = gain / loss if loss else np.inf if gain else 0
            total = float((1 + group.return_pct/100).prod()-1)
            if total <= 0 or pf <= 1.1 or group.trades.sum() < 20 or group.max_close_drawdown_pct.max() > 15:
                break
            scores[cost] = total
        if len(scores) == 2:
            choices.append((scores[2],name))
    choices.sort(key=lambda x:(-x[0],x[1]))
    return choices[0][1] if choices else 'cash', [name for _,name in choices]


def main():
    data, out = ROOT/'data_20261011',ROOT/'regime_results_20261012'
    manifest = json.loads((data/'manifest.json').read_text(encoding='utf-8'))
    for name,digest in manifest['sha256'].items():
        if hashlib.sha256((data/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Data hash mismatch')
    candles = pd.read_csv(data/'btc_15m.csv',parse_dates=['time']).set_index('time')
    candles.index = pd.to_datetime(candles.index,utc=True)
    funding = pd.read_csv(data/'funding.csv',parse_dates=['time'])
    funding.time = pd.to_datetime(funding.time,utc=True)
    signals = regime_features(candles)
    months = pd.date_range('2026-01-01','2026-10-01',freq='MS')
    periods = PERIODS + [(f'month_{start:%Y%m}',str(start.date()),str(end.date()))
                        for start,end in zip(months[:-1],months[1:])]
    out.mkdir(exist_ok=True)
    rows, trade_rows = [],[]
    for label,start,end in periods:
        subset = signals[(signals.index >= pd.Timestamp(start,tz='UTC')) & (signals.index < pd.Timestamp(end,tz='UTC'))]
        for name in NAMES:
            for cost in (1,2):
                result,trades,_ = run(candles,subset,funding,Variant(name),start,end,cost,
                                     policy=None if name == 'baseline' else Policy(name))
                result['window'] = label
                result['positive_net'] = sum(max(0,t['net']) for t in trades)
                result['negative_net_abs'] = sum(max(0,-t['net']) for t in trades)
                result['mean_holding_hours'] = float(np.mean([(t['exit_time']-t['entry_time']).total_seconds()/3600 for t in trades])) if trades else 0.
                rows.append(result)
                for t in trades:
                    if name == 'baseline':
                        t.update(entry_regime=Policy.regime(subset.loc[t['entry_time']]),branch='baseline')
                    trade_rows.append(dict(window=label,variant=name,cost_factor=cost,**t))
        print('Completed',label,flush=True)
    frame = pd.DataFrame(rows)
    base = frame[frame.variant == 'baseline'].set_index(['window','cost_factor']).trades
    frame['frequency_ratio'] = [r.trades/base.loc[r.window,r.cost_factor] if base.loc[r.window,r.cost_factor] else None for r in frame.itertuples()]
    frame.to_csv(out/'comparison.csv',index=False)
    trades = pd.DataFrame(trade_rows)
    trades.to_csv(out/'simulated_trades.csv',index=False)
    trades.groupby(['window','variant','cost_factor','entry_regime']).agg(
        trades=('net','size'),net=('net','sum'),gross_after_slippage=('gross','sum'),
        fees=('fees','sum'),funding=('funding','sum')).reset_index().to_csv(out/'regime_attribution.csv',index=False)
    monthly = frame[frame.window.str.startswith('month_')]
    selections = []
    for target in pd.date_range('2026-04-01','2026-09-01',freq='MS'):
        chosen,eligible = choose_month(monthly,target)
        row = dict(month=str(target.date()),selected=chosen,eligible=eligible)
        for cost in (1,2):
            result = monthly[(monthly.window == f'month_{target:%Y%m}') & (monthly.variant == chosen) & (monthly.cost_factor == cost)].iloc[0]
            row[f'return_cost{cost}_pct'] = float(result.return_pct)
        selections.append(row)
    rank = frame[(frame.window == 'development') & (frame.cost_factor == 2) & (frame.variant != 'cash')].sort_values(
        ['return_pct','max_close_drawdown_pct','variant'],ascending=[False,True,True])
    qualified = []
    for name in NAMES:
        group = frame[(frame.variant == name) & frame.window.isin(['development','validation','historical_check'])]
        if len(group) == 6 and ((group.return_pct > 0) & (group.profit_factor.fillna(0) > 1.1) &
                               (group.trades >= 30) & (group.max_close_drawdown_pct <= 15)).all():
            qualified.append(name)
    decision = dict(best_active_development=rank.iloc[0].variant,
        historical_qualified=qualified,live_deployment=False,prospective_evidence=False,
        monthly_selection=selections,snapshot_sha256=manifest['sha256'],
        selection_rule='Development doubled-cost return, then lower drawdown, then name; cash is a separate benchmark.')
    (out/'decision.json').write_text(json.dumps(decision,indent=2,allow_nan=False),encoding='utf-8')
    print(frame[~frame.window.str.startswith('month_')][['window','variant','cost_factor','trades','return_pct','max_close_drawdown_pct']].to_string(index=False))
    print(json.dumps(decision,indent=2))


if __name__ == '__main__':
    main()
