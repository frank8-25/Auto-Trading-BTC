import unittest
from research.strategy_review import Variant,entry_side,signal_exit,distances
from research.frequency_review import acceptance,VARIANTS


class FrequencyReviewTests(unittest.TestCase):
    def test_confirmed_exit_needs_two_closed_bars(self):
        variant=Variant('confirm',exit_confirmation=2)
        signal=dict(ema_side=-1,ema_side_previous=1)
        self.assertIsNone(signal_exit(signal,1,variant))
        signal['ema_side_previous']=-1
        self.assertEqual(signal_exit(signal,1,variant),'EMA_CONFIRMED_EXIT')
        self.assertIsNone(signal_exit(signal,-1,variant))

    def test_target_change_preserves_stop(self):
        self.assertEqual(distances({},Variant('target',target_fraction=.0045),100),(.005,.0045))

    def test_range_entry_rejects_trending_or_unknown_regime(self):
        variant=Variant('range',entry_mode='range')
        for adx in (25,30,float('nan')):
            self.assertEqual(entry_side(dict(adx=adx,range_signal=1),variant,100),0)
        self.assertEqual(entry_side(dict(adx=20,range_signal=-1),variant,100),-1)
        self.assertEqual(signal_exit(dict(rsi=50),-1,variant),'RSI_MID_EXIT')
        self.assertIsNone(signal_exit(dict(rsi=49),1,variant))

    def test_low_activity_is_not_accepted_as_an_improvement(self):
        rows=[]
        for label in ('validation','historical_check'):
            for cost in (1,2):
                for variant in VARIANTS:
                    rows.append(dict(window=label,cost_factor=cost,variant=variant.name,return_pct=5,
                                     profit_factor=2,trades=50,frequency_ratio=.4,max_close_drawdown_pct=1))
        self.assertTrue(all(not x['accepted'] for x in acceptance(rows).values()))
        for row in rows:row['frequency_ratio']=1
        self.assertTrue(all(x['accepted'] for x in acceptance(rows).values()))


if __name__=='__main__':unittest.main()
