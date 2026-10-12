import unittest
import numpy as np
import pandas as pd
from research.regime_study import Policy, regime_features, choose_month


class RegimeStudyTests(unittest.TestCase):
    def test_future_candles_do_not_change_available_features(self):
        x=np.arange(800); close=100+x*.02+np.sin(x/9)
        candles=pd.DataFrame(dict(open=close,close=close,high=close+1,low=close-1,volume=100),
                             index=pd.date_range('2026-01-01',periods=800,freq='15min',tz='UTC'))
        original=regime_features(candles)
        candles.iloc[603:,candles.columns.get_indexer(['open','high','low','close'])]*=2
        changed=regime_features(candles)
        pd.testing.assert_frame_equal(original.loc[:candles.index[603]],changed.loc[:candles.index[603]])

    def test_regime_boundary_and_hour_gate(self):
        s=dict(adx=25,hour_event=True,breakout20=1,bias=1,range_signal=-1)
        policy=Policy('switch20')
        self.assertEqual(policy.entry(s,100),1)
        self.assertEqual(policy.entry(dict(s,hour_event=False),100),0)
        for adx in (20,24.9,float('nan')):
            self.assertEqual(policy.entry(dict(s,adx=adx),100),0)
        self.assertEqual(policy.entry(dict(s,adx=19),100),-1)

    def test_exit_keeps_entry_branch_when_regime_changes(self):
        start=pd.Timestamp('2026-01-01',tz='UTC')
        p=dict(branch='breakout20',side=1,time=start)
        s=dict(adx=10,rsi=80,hour_event=True,breakout10=0)
        self.assertIsNone(Policy.exit_reason(s,p,start+pd.Timedelta(hours=1)))
        s['breakout10']=-1
        self.assertEqual(Policy.exit_reason(s,p,start+pd.Timedelta(hours=1)),'CHANNEL_EXIT')

    def test_maximum_holding_time(self):
        start=pd.Timestamp('2026-01-01',tz='UTC')
        p=dict(branch='ema_atr',side=1,time=start)
        self.assertIsNone(Policy.exit_reason({},p,start+pd.Timedelta(hours=23)))
        self.assertEqual(Policy.exit_reason({},p,start+pd.Timedelta(hours=24)),'TIME_EXIT')

    def test_excessive_volatility_is_rejected_not_clipped(self):
        policy=Policy('breakout20')
        self.assertIsNone(policy.distance(dict(adx=30,h_atr=2),100))
        stop,target=policy.distance(dict(adx=30,h_atr=.1),100)
        self.assertAlmostEqual(stop,.006)
        self.assertAlmostEqual(target,.018)

    def test_breakout_channel_excludes_current_hour(self):
        close=100+np.arange(800,dtype=float)
        candles=pd.DataFrame(dict(open=close,close=close,high=close+.1,low=close-.1,volume=100),
            index=pd.date_range('2026-01-01',periods=800,freq='15min',tz='UTC'))
        signal=regime_features(candles).loc[pd.Timestamp('2026-01-05',tz='UTC')]
        self.assertEqual(signal.breakout20,1)
        self.assertEqual(signal.breakout40,1)

    def test_month_selection_ignores_target_and_future_results(self):
        rows=[]
        for start in ['2026-01-01','2026-02-01','2026-03-01','2026-04-01','2026-05-01']:
            for cost in (1,2):
                rows.append(dict(start=start,variant='ema_atr',cost_factor=cost,positive_net=200,
                    negative_net_abs=100,return_pct=1,trades=10,max_close_drawdown_pct=2))
        frame=pd.DataFrame(rows)
        self.assertEqual(choose_month(frame,'2026-04-01')[0],'ema_atr')
        frame.loc[frame.start >= '2026-04-01',['return_pct','positive_net','negative_net_abs']]=-99999
        self.assertEqual(choose_month(frame,'2026-04-01')[0],'ema_atr')
        frame.loc[frame.start < '2026-04-01','return_pct']=-1
        self.assertEqual(choose_month(frame,'2026-04-01')[0],'cash')

    def test_incomplete_training_history_cannot_select(self):
        frame=pd.DataFrame([dict(start='2026-03-01',variant='ema_atr',cost_factor=1,
            positive_net=1000,negative_net_abs=1,return_pct=10,trades=100,max_close_drawdown_pct=1)])
        self.assertEqual(choose_month(frame,'2026-04-01')[0],'cash')


if __name__ == '__main__':
    unittest.main()
