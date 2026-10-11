import unittest
import pandas as pd
from unittest.mock import patch
from research.signal_quality import analyze
from research.signal_quality import forward_return, funding_cash, eligible_times, block_interval


class SignalQualityTests(unittest.TestCase):
    def test_event_uses_signal_time_open_and_future_open(self):
        times = pd.date_range('2026-01-01', periods=12, freq='15min', tz='UTC')
        candles = pd.DataFrame(dict(open=[100+i for i in range(12)], close=[900]*12), index=times)
        signals = pd.DataFrame(dict(atr=1., close=100., adx=20., cross=0, bias=1, ema20=100.), index=times)
        signals.loc[times[0], 'cross'] = 1
        funding = pd.DataFrame(dict(time=pd.to_datetime([], utc=True), rate=[], mark_price=[]))
        with patch('research.signal_quality.features', return_value=signals), patch(
                'research.signal_quality.PERIODS', [('development', '2026-01-01', '2026-01-01 03:00')]):
            events, _, _ = analyze(candles, funding)
        self.assertEqual(len(events), 3)
        for row, expected in zip(events.itertuples(), [100., 200., 400.]):
            self.assertAlmostEqual(row.gross_bp, expected)

    def test_flat_market_costs_and_direction(self):
        for side in (1, -1):
            gross, net = forward_return(100, 100, side)
            self.assertEqual(gross, 0)
            self.assertAlmostEqual(net, -15)
            self.assertAlmostEqual(forward_return(100, 100, side, cost_factor=2)[1], -30)
        self.assertAlmostEqual(forward_return(100, 101, 1)[0], 100)
        self.assertAlmostEqual(forward_return(100, 101, -1)[0], -100)

    def test_funding_entry_excluded_exit_included(self):
        times = pd.date_range('2026-01-01', periods=3, freq='15min', tz='UTC')
        frame = pd.DataFrame(dict(time=times, rate=[.001]*3, mark_price=[100]*3))
        self.assertAlmostEqual(funding_cash(frame, times[0], times[1], 1), -.1)
        self.assertAlmostEqual(funding_cash(frame, times[0], times[1], -1), .1)

    def test_labels_cannot_cross_period_boundary(self):
        frame = pd.DataFrame(index=pd.date_range('2026-01-01', periods=20, freq='15min', tz='UTC'))
        times = eligible_times(frame, '2026-01-01', '2026-01-01 02:00')
        self.assertEqual(len(times), 4)
        self.assertLess(times[-1] + pd.Timedelta(minutes=60), pd.Timestamp('2026-01-01 02:00', tz='UTC'))

    def test_bootstrap_reproducible_and_short_sample_not_certified(self):
        frame = pd.DataFrame(dict(time=pd.date_range('2026-01-01', periods=40, freq='D', tz='UTC'), gross_bp=[2.]*40))
        self.assertEqual(block_interval(frame, 'gross_bp', '2026-01-01', '2026-02-15'), (2., 2.))
        self.assertEqual(block_interval(frame.iloc[:7], 'gross_bp', '2026-01-01', '2026-01-08'), (None, None))


if __name__ == '__main__':
    unittest.main()
