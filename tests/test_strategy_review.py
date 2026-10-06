import unittest
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from research.strategy_review import Variant, features, barrier_exit, entry_side, distances, run
from research.review_session import review


class StrategyResearchTests(unittest.TestCase):
    def test_private_review_handles_mixed_dates_without_exporting_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            pd.DataFrame([
                dict(Timestamp='2025-12-01 10:00',Symbol='BTC',Reason='old',**{'PnL USDT':999}),
                dict(Timestamp='2026-01-01 10:01:03',Symbol='BTC',Reason='EMA_EXIT order_id=secret basis=EXECUTED_GROSS',**{'PnL USDT':-1}),
                dict(Timestamp='2026-01-01 11:00',Symbol='SESSION_SUMMARY',Reason='start=2026-01-01 10:00:00 trades=1',**{'PnL USDT':-1})
            ]).to_csv(root/'testnet_trade_history.csv',index=False)
            pd.DataFrame([dict(Start='2026-01-01T10:00:00',End='2026-01-01T11:00:00',Status='CONFIRMED',
                               **{'Realized Gross USDT':-1,'Commission USDT':-.2,'Funding USDT':-.1,'Net USDT':-1.3})]).to_csv(root/'testnet_trade_history_income.csv',index=False)
            result=review(root)
            self.assertEqual(result['trades'],1)
            self.assertNotIn('secret',str(result))
            self.assertEqual(result['gross_losses'],1)

    def candles(self, size=800):
        x=np.arange(size)
        close=100+x*.02+np.sin(x/9)
        return pd.DataFrame(dict(open=close,high=close+1,low=close-1,close=close,volume=100),
                            index=pd.date_range('2026-01-01',periods=size,freq='15min',tz='UTC'))

    def test_future_prices_do_not_change_past_features(self):
        frame=self.candles()
        original=features(frame)
        frame.iloc[601:,frame.columns.get_indexer(['open','high','low','close'])]*=2
        changed=features(frame)
        cutoff=frame.index[601]
        pd.testing.assert_frame_equal(original.loc[:cutoff],changed.loc[:cutoff])

    def test_unclosed_hour_does_not_change_hourly_features(self):
        frame=self.candles()
        changed=frame.copy()
        changed.iloc[603,changed.columns.get_indexer(['open','high','low','close'])]*=2
        a,b=features(frame),features(changed)
        cutoff=frame.index[603]
        pd.testing.assert_frame_equal(a.loc[:cutoff,['bias','adx','slope']],b.loc[:cutoff,['bias','adx','slope']])

    def test_gaps_and_invalid_prices_fail(self):
        for frame in [self.candles().drop(self.candles().index[300]),self.candles().assign(low=-1)]:
            with self.assertRaises(ValueError):features(frame)

    def test_stop_precedes_target_and_gap_gets_worse_fill(self):
        self.assertEqual(barrier_exit(1,100,.005,.003,dict(open=100,high=101,low=99)),(99.5,'STOP'))
        self.assertEqual(barrier_exit(1,100,.005,.003,dict(open=98,high=101,low=97)),(98,'STOP_GAP'))
        self.assertEqual(barrier_exit(-1,100,.005,.003,dict(open=102,high=103,low=99)),(102,'STOP_GAP'))

    def test_adx_and_slope_gate_without_changing_baseline(self):
        signal=dict(cross=1,bias=1,ema20=100,adx=24,slope=.2,atr=.3)
        self.assertEqual(entry_side(signal,Variant('base'),100),1)
        self.assertEqual(entry_side(signal,Variant('filter',25),100),0)
        signal['adx']=26
        self.assertEqual(entry_side(signal,Variant('filter',25),100),1)
        signal['slope']=-.2
        self.assertEqual(entry_side(signal,Variant('filter',25),100),0)
        self.assertEqual(entry_side(signal,Variant('base'),101),0)
        self.assertEqual(distances(signal,Variant('atr',25,True),100),(.0045,.009))
        signal['atr']=2
        self.assertIsNone(distances(signal,Variant('atr',25,True),100))

    def test_cash_reconciles_fees_funding_and_next_open(self):
        index=pd.date_range('2026-01-01',periods=4,freq='15min',tz='UTC')
        frame=pd.DataFrame(dict(open=100.,high=100.05,low=99.95,close=100.,volume=1),index=index)
        signals=pd.DataFrame(dict(cross=[0,1,0,0],bias=1,ema20=100.,adx=30.,slope=1.,atr=.3),index=index)
        funding=pd.DataFrame([dict(time=index[2],rate=.001,mark_price=100)])
        result,trades,curve=run(frame,signals,funding,Variant('base'),'2026-01-01','2026-01-02')
        self.assertEqual(len(trades),1)
        self.assertEqual(trades[0]['entry_time'],index[1])
        self.assertLess(trades[0]['funding'],0)
        self.assertGreater(trades[0]['fees'],0)
        self.assertAlmostEqual(result['final_equity'],10000+sum(t['net'] for t in trades))
        self.assertAlmostEqual(curve[-1]['equity'],result['final_equity'])

    def test_daily_budget_blocks_repeated_normal_stop_losses(self):
        index=pd.date_range('2026-01-01',periods=8,freq='15min',tz='UTC')
        frame=pd.DataFrame(dict(open=100.,high=100.1,low=99.,close=100.,volume=1),index=index)
        signals=pd.DataFrame(dict(cross=1,bias=1,ema20=100.,adx=30.,slope=1.,atr=.3),index=index)
        funding=pd.DataFrame({'time':pd.Series([],dtype='datetime64[ns, UTC]'),'rate':[],'mark_price':[]})
        result,trades,_=run(frame,signals,funding,Variant('base'),'2026-01-01','2026-01-02')
        self.assertLess(len(trades),len(frame))
        self.assertGreaterEqual(result['final_equity'],9799)
        self.assertLess(result['final_equity'],9901)


if __name__=='__main__':unittest.main()
