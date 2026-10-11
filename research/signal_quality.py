"""Fixed-horizon EMA event study; offline public data, no orders or fitted model."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.strategy_review import features, entry_side, Variant, WINDOWS

ROOT = Path(__file__).resolve().parent
HORIZONS = (15, 30, 60)
PERIODS = WINDOWS + [('new_period', '2026-10-05', '2026-10-11 13:15:00')]


def forward_return(entry, exit_price, side, funding_amount=0., cost_factor=1):
    """Basis points per raw entry notional; funding_amount is signed cash per BTC."""
    fee, slip = .0005 * cost_factor, .00025 * cost_factor
    entry_fill = entry * (1 + side * slip)
    exit_fill = exit_price * (1 - side * slip)
    gross = side * (exit_price / entry - 1) * 10000
    net = (side * (exit_fill - entry_fill) - fee * (entry_fill + exit_fill)
           + funding_amount) / entry * 10000
    return gross, net


def funding_cash(funding, start, end, side):
    # Same convention as the strategy engine: exclude entry, include exit timestamp.
    rows = funding[(funding.time > start) & (funding.time <= end)]
    return float((-side * rows.rate * rows.mark_price).sum())


def eligible_times(candles, start, end):
    start, end = pd.Timestamp(start, tz='UTC'), pd.Timestamp(end, tz='UTC')
    # A common 60-minute endpoint keeps the three horizon samples identical.
    return candles.index[(candles.index >= start) &
                         (candles.index + pd.Timedelta(minutes=60) < end) &
                         (candles.index + pd.Timedelta(minutes=60) <= candles.index[-1])]


def block_interval(events, column, start, end, repetitions=2000):
    """Exploratory 7-calendar-day moving-block bootstrap of the event-weighted mean."""
    days = pd.date_range(pd.Timestamp(start, tz='UTC').normalize(),
                         pd.Timestamp(end, tz='UTC').ceil('D'), freq='D', inclusive='left')
    if len(events) < 30 or len(days) < 28:
        return None, None
    grouped = events.groupby(pd.to_datetime(events.time, utc=True).dt.floor('D'))[column].agg(['sum', 'count'])
    daily = grouped.reindex(days, fill_value=0).to_numpy()
    rng = np.random.default_rng(20261011)
    starts = rng.integers(0, len(days)-6, size=(repetitions, int(np.ceil(len(days)/7))))
    indices = (starts[:, :, None] + np.arange(7)).reshape(repetitions, -1)[:, :len(days)]
    sums = daily[indices].sum(axis=1)
    means = sums[sums[:, 1] > 0, 0] / sums[sums[:, 1] > 0, 1]
    return tuple(float(x) for x in np.quantile(means, [.025, .975]))


def analyze(candles, funding):
    sig = features(candles)
    dev = sig.loc[(sig.index >= pd.Timestamp(PERIODS[0][1], tz='UTC')) &
                  (sig.index < pd.Timestamp(PERIODS[0][2], tz='UTC'))]
    volatility_cut = float((dev.atr / dev.close).median())
    events, controls = [], {}
    for label, start, end in PERIODS:
        times = eligible_times(candles, start, end)
        for horizon in HORIZONS:
            returns = (candles.loc[times + pd.Timedelta(minutes=horizon), 'open'].to_numpy()
                       / candles.loc[times, 'open'].to_numpy() - 1) * 10000
            controls[label, horizon] = float(returns.mean())
        for when in times:
            if when not in sig.index:
                continue
            signal = sig.loc[when]
            entry = float(candles.loc[when, 'open'])
            side = entry_side(signal, Variant('baseline'), entry)
            if not side:
                continue
            for horizon in HORIZONS:
                endpoint = when + pd.Timedelta(minutes=horizon)
                exit_price = float(candles.loc[endpoint, 'open'])
                cash = funding_cash(funding, when, endpoint, side)
                gross, net = forward_return(entry, exit_price, side, cash)
                _, stress = forward_return(entry, exit_price, side, cash, 2)
                events.append(dict(window=label, time=str(when), horizon_minutes=horizon,
                    side=side, regime='trend' if signal.adx >= 25 else 'range',
                    volatility='high' if signal.atr / signal.close >= volatility_cut else 'low',
                    gross_bp=gross, net_bp=net, stress_net_bp=stress,
                    funding_bp=cash / entry * 10000))
    frame = pd.DataFrame(events)
    rows = []
    for label, start, end in PERIODS:
        for horizon in HORIZONS:
            base = frame[(frame.window == label) & (frame.horizon_minutes == horizon)]
            groups = [('all', base)]
            for field, values in [('side', [1, -1]), ('regime', ['trend', 'range']),
                                   ('volatility', ['high', 'low'])]:
                groups += [(f'{field}={v}', base[base[field] == v]) for v in values]
            for name, group in groups:
                if group.empty:
                    continue
                lo, hi = block_interval(group, 'gross_bp', start, end) if name == 'all' else (None, None)
                nlo, nhi = block_interval(group, 'net_bp', start, end) if name == 'all' else (None, None)
                control = controls[label, horizon] * float(group.side.mean()) if name == 'all' else None
                rows.append(dict(window=label, horizon_minutes=horizon, group=name, signals=len(group),
                    gross_mean_bp=group.gross_bp.mean(), gross_median_bp=group.gross_bp.median(),
                    direction_hit_pct=(group.gross_bp > 0).mean()*100,
                    net_mean_bp=group.net_bp.mean(), stress_net_mean_bp=group.stress_net_bp.mean(),
                    net_positive_pct=(group.net_bp > 0).mean()*100,
                    gross_ci_low_bp=lo, gross_ci_high_bp=hi, net_ci_low_bp=nlo, net_ci_high_bp=nhi,
                    direction_mix_control_bp=control,
                    excess_over_control_bp=group.gross_bp.mean()-control if control is not None else None))
    return frame, pd.DataFrame(rows), volatility_cut


def main():
    data, output = ROOT / 'data_20261011', ROOT / 'signal_results_20261011'
    manifest = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['sha256'].items():
        if hashlib.sha256((data / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Snapshot hash mismatch: {name}')
    candles = pd.read_csv(data / 'btc_15m.csv', parse_dates=['time']).set_index('time')
    candles.index = pd.to_datetime(candles.index, utc=True)
    funding = pd.read_csv(data / 'funding.csv', parse_dates=['time'])
    funding.time = pd.to_datetime(funding.time, utc=True)
    events, summary, cut = analyze(candles, funding)
    output.mkdir(exist_ok=True)
    events.to_csv(output / 'events.csv', index=False)
    summary.to_csv(output / 'summary.csv', index=False)
    (output / 'method.json').write_text(json.dumps(dict(
        snapshot_sha256=manifest['sha256'], horizons_minutes=HORIZONS,
        development_atr_fraction_median=cut, fee_per_side=.0005, slippage_per_side=.00025,
        bootstrap_seed=20261011, bootstrap_repetitions=2000, bootstrap_block_days=7,
        historical_exploration=True, live_deployment=False), indent=2), encoding='utf-8')
    print(summary[summary.group == 'all'].to_string(index=False))


if __name__ == '__main__':
    main()
