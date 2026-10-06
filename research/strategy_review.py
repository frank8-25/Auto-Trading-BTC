"""Offline research only: closed-candle signals, next-open fills, explicit costs.

No account credentials, exchange orders, or imports from the running trading bot.
Run download_data.py once, then run this file from the repository root.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Variant:
    name: str
    adx_min: float = 0
    atr_exit: bool = False


VARIANTS = [Variant('baseline'), Variant('adx25', 25), Variant('adx25_atr', 25, True)]
WINDOWS = [
    ('development', '2025-10-01', '2026-04-01'),
    ('validation', '2026-04-01', '2026-07-01'),
    ('historical_check', '2026-07-01', '2026-09-28'),
    ('diagnostic_week', '2026-09-28', '2026-10-05'),
]


def wilder(series, period=14):
    """SMA seed followed by Wilder smoothing; no backward fill."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    seed = series.rolling(period).mean().to_numpy()
    state = np.nan
    for i, value in enumerate(values):
        if not np.isfinite(value):
            state = np.nan
        elif not np.isfinite(state):
            state = seed[i]
        else:
            state = (state * (period - 1) + value) / period
        out[i] = state
    return pd.Series(out, index=series.index)


def volatility(frame):
    prev = frame.close.shift(1)
    tr = pd.concat([frame.high-frame.low, (frame.high-prev).abs(),
                    (frame.low-prev).abs()], axis=1).max(axis=1)
    atr = wilder(tr)
    up, down = frame.high.diff(), -frame.low.diff()
    plus = wilder(up.where((up > down) & (up > 0), 0.0)) / atr * 100
    minus = wilder(down.where((down > up) & (down > 0), 0.0)) / atr * 100
    denominator = plus + minus
    dx = (100 * (plus-minus).abs() / denominator.replace(0, np.nan)).where(denominator != 0, 0.0)
    return atr, wilder(dx)


def features(candles):
    f = candles.copy().sort_index()
    if f.index.tz is None or not f.index.is_unique:
        raise ValueError('Unique timezone-aware candle opens required')
    if len(f) < 400 or not (f.index.to_series().diff().dropna() == pd.Timedelta(minutes=15)).all():
        raise ValueError('Need at least 400 continuous 15m candles')
    if not np.isfinite(f[['open','high','low','close','volume']].to_numpy()).all():
        raise ValueError('Non-finite market data')
    if (f[['open','high','low','close']] <= 0).any().any() or (f.volume < 0).any():
        raise ValueError('Invalid price or volume')
    if ((f.high < f[['open','close','low']].max(axis=1)) |
        (f.low > f[['open','close','high']].min(axis=1))).any():
        raise ValueError('Invalid OHLC range')
    f['ema5'] = f.close.ewm(span=5, adjust=False, min_periods=5).mean()
    f['ema20'] = f.close.ewm(span=20, adjust=False, min_periods=20).mean()
    f['atr'], _ = volatility(f)
    f['cross'] = np.select([(f.ema5>f.ema20)&(f.ema5.shift(1)<=f.ema20.shift(1)),
                            (f.ema5<f.ema20)&(f.ema5.shift(1)>=f.ema20.shift(1))], [1,-1], default=0)
    h = f.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    h = h[f.close.resample('1h').count() == 4].copy()
    h['fast'] = h.close.ewm(span=20, adjust=False, min_periods=20).mean()
    h['slow'] = h.close.ewm(span=60, adjust=False, min_periods=60).mean()
    _, h['adx'] = volatility(h)
    h['slope'] = h.fast.diff(3)
    h['bias'] = np.sign(h.fast-h.slow)
    h.index += pd.Timedelta(hours=1)  # Hour becomes available only at its close.
    f.index += pd.Timedelta(minutes=15)  # 15m signal's availability, not candle open.
    return pd.merge_asof(f, h[['bias','adx','slope']], left_index=True,
                         right_index=True, direction='backward')


def entry_side(signal, variant, execution_price):
    side = int(signal['cross'])
    if not side or signal['bias'] != side:
        return 0
    # Original side-specific extension rule, evaluated against next open.
    if side * (execution_price / signal['ema20'] - 1) > 0.0015:
        return 0
    if variant.adx_min and (not np.isfinite(signal['adx']) or signal['adx'] < variant.adx_min
                            or not np.isfinite(signal['slope']) or side*signal['slope'] <= 0):
        return 0
    return side


def distances(signal, variant, price):
    if not variant.atr_exit:
        return 0.005, 0.003
    raw = 1.5 * signal['atr'] / price
    if not np.isfinite(raw) or raw > 0.01:
        return None  # Don't silently clip a volatile market to an undersized stop.
    stop = max(0.003, raw)
    return stop, 2*stop


def barrier_exit(side, entry, stop_fraction, target_fraction, bar):
    stop = entry*(1-side*stop_fraction)
    target = entry*(1+side*target_fraction)
    # Opening gaps are known before the within-bar range.
    if side*(bar['open']-stop) <= 0:
        return bar['open'], 'STOP_GAP'
    if side*(bar['open']-target) >= 0:
        return target, 'TARGET_GAP'  # Conservative target fill.
    hit_stop = bar['low'] <= stop if side == 1 else bar['high'] >= stop
    hit_target = bar['high'] >= target if side == 1 else bar['low'] <= target
    if hit_stop:
        return stop, 'STOP'  # Both touched: assume stop first.
    if hit_target:
        return target, 'TARGET'
    return None


def run(candles, signals, funding, variant, start, end, cost_factor=1):
    start, end = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    bars = candles[(candles.index>=start)&(candles.index<end)]
    if bars.empty:
        raise ValueError('Empty evaluation window')
    fee, slip = 0.0005*cost_factor, 0.00025*cost_factor
    cash, position, peak, drawdown = 10000.0, None, 10000.0, 0.0
    day, day_start, daily_net = None, cash, 0.0
    trades, curve = [], []
    signal_map = signals.to_dict('index')
    fund = funding[(funding.time>=start)&(funding.time<end)].sort_values('time').to_dict('records')
    fi = 0

    def close(price, when, reason):
        nonlocal cash, position, daily_net
        p=position
        fill=price*(1-p['side']*slip)
        gross=p['side']*p['quantity']*(fill-p['entry'])
        exit_fee=p['quantity']*fill*fee
        cash+=gross-exit_fee
        daily_net+=gross-exit_fee
        trades.append(dict(entry_time=p['time'],exit_time=when,side=p['side'],
                           gross=gross,fees=p['entry_fee']+exit_fee,funding=p['funding'],
                           net=gross-p['entry_fee']-exit_fee+p['funding'],reason=reason))
        position=None

    for when, bar in zip(bars.index, bars.to_dict('records')):
        if day != when.date():
            day=when.date(); day_start=cash; daily_net=0.0
        # Funding at candle-open timestamp is charged only to a pre-existing position.
        while fi<len(fund) and fund[fi]['time']<=when:
            event=fund[fi]
            if position and event['time']>position['time']:
                amount=-position['side']*position['quantity']*event['mark_price']*event['rate']
                cash+=amount; daily_net+=amount; position['funding']+=amount
            fi+=1
        signal=signal_map.get(when)
        exited=False
        if position:
            gap = barrier_exit(position['side'],position['entry'],position['stop'],position['target'],
                               dict(open=bar['open'],high=bar['open'],low=bar['open']))
            if gap:
                close(gap[0], when, gap[1]); exited=True
            elif signal and signal['cross']==-position['side']:
                close(bar['open'],when,'EMA_EXIT')  # Aligned reversal can open at this same timestamp.
        if not position and not exited and signal and cash>0:
            side=entry_side(signal,variant,bar['open'])
            distance=distances(signal,variant,bar['open'])
            remaining=max(0.0,day_start*0.02+min(daily_net,0))
            budget=min(cash*0.01,remaining)
            if side and distance and budget>0:
                stop,target=distance
                entry=bar['open']*(1+side*slip)
                notional=min(cash*2,budget/(stop+2*fee+2*slip))
                quantity=np.floor(notional/entry*1000)/1000  # Research assumes 0.001 BTC step.
                if quantity>=0.001:
                    entry_fee=quantity*entry*fee
                    position=dict(side=side,entry=entry,quantity=quantity,stop=stop,target=target,
                                  entry_fee=entry_fee,funding=0.0,time=when)
                    cash-=entry_fee; daily_net-=entry_fee
        if position:
            hit=barrier_exit(position['side'],position['entry'],position['stop'],position['target'],bar)
            if hit:
                close(hit[0],when+pd.Timedelta(minutes=15),hit[1])
        mark=cash if not position else cash+position['side']*position['quantity']*(bar['close']-position['entry'])
        peak=max(peak,mark); drawdown=max(drawdown,(peak-mark)/peak)
        curve.append({'time':when+pd.Timedelta(minutes=15),'equity':mark})
    if position:
        close(bars.close.iloc[-1],end,'WINDOW_END')
        peak=max(peak,cash);drawdown=max(drawdown,(peak-cash)/peak)
        curve[-1]['equity']=cash
    net=np.array([t['net'] for t in trades])
    wins=net[net>0].sum();loss=-net[net<0].sum()
    summary=dict(variant=variant.name,start=str(start),end=str(end),cost_factor=cost_factor,
                 trades=len(trades),win_rate_pct=float((net>0).mean()*100) if len(net) else 0,
                 return_pct=(cash/10000-1)*100,max_close_drawdown_pct=drawdown*100,
                 profit_factor=float(wins/loss) if loss else None,
                 fees=sum(t['fees'] for t in trades),funding=sum(t['funding'] for t in trades),
                 final_equity=cash)
    return summary,trades,curve


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,default=Path('research/data'))
    parser.add_argument('--output',type=Path,default=Path('research/results'))
    args=parser.parse_args()
    manifest=json.loads((args.data_dir/'manifest.json').read_text(encoding='utf-8'))
    for name in ('btc_15m.csv','funding.csv'):
        if hashlib.sha256((args.data_dir/name).read_bytes()).hexdigest()!=manifest['sha256'][name]:
            raise ValueError(f'Data hash mismatch: {name}')
    candles=pd.read_csv(args.data_dir/'btc_15m.csv',parse_dates=['time']).set_index('time')
    candles.index=pd.to_datetime(candles.index,utc=True)
    funding=pd.read_csv(args.data_dir/'funding.csv',parse_dates=['time'])
    funding['time']=pd.to_datetime(funding.time,utc=True)
    sig=features(candles)
    args.output.mkdir(parents=True,exist_ok=True)
    summaries=[]
    for label,start,end in WINDOWS:
        for variant in VARIANTS:
            for cost in (1,2):
                result,trades,curve=run(candles,sig,funding,variant,start,end,cost)
                result['window']=label;summaries.append(result)
                stem=f'{label}_{variant.name}_cost{cost}'
                pd.DataFrame(trades).to_csv(args.output/f'{stem}_trades.csv',index=False)
                pd.DataFrame(curve).to_csv(args.output/f'{stem}_equity.csv',index=False)
    pd.DataFrame(summaries).to_csv(args.output/'comparison.csv',index=False)
    (args.output/'comparison.json').write_text(json.dumps(summaries,indent=2,allow_nan=False),encoding='utf-8')
    accepted=[]
    for variant in VARIANTS[1:]:
        checks=[r for r in summaries if r['variant']==variant.name and r['window'] in ('validation','historical_check')]
        passes=True
        for row in checks:
            baseline=next(b for b in summaries if b['variant']=='baseline' and b['window']==row['window'] and b['cost_factor']==row['cost_factor'])
            passes &= (row['trades']>=30 and row['return_pct']>0 and (row['profit_factor'] or 0)>1.1
                       and row['max_close_drawdown_pct']<=baseline['max_close_drawdown_pct'])
        if passes:accepted.append(variant.name)
    decision=dict(accepted_candidates=accepted,live_deployment=False,
                  explanation='Historical comparison is not prospective evidence. No automatic deployment.',
                  criteria='Both validation and historical_check, base and doubled costs: >=30 trades, positive return, PF>1.1, drawdown<=baseline.')
    (args.output/'decision.json').write_text(json.dumps(decision,indent=2),encoding='utf-8')
    print(pd.DataFrame(summaries)[['window','variant','cost_factor','trades','return_pct','max_close_drawdown_pct']].to_string(index=False))


if __name__=='__main__':
    main()
