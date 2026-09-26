"""Additional independent edge cases; not parameters for the market search."""
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
import engine as e
from test_engine import fixture,params


class AccountingEdgeTests(unittest.TestCase):
    def test_summary_scalars_are_json_native_for_strict_objectives(self):
        m=e.market_from_frames(fixture())
        run=e.simulate(m,params(),1.25,start='2019-10-01',end='2020-01-31')
        for key,value in e.summarize(run).items():
            if not isinstance(value,list):self.assertIn(type(value),(int,float,bool),key)

    def test_rotation_after_partial_tp_closes_only_remaining_qty(self):
        s=e.State(equity=100,qty=1,asset=0,mark=100,entry=100,entry_atr=10,episode=1)
        p=params();p.update(tp=.25,tp_atr=2,catastrophic=0,trail=0)
        s,events,_,_=e.path_replay(s,[125,122,123],p,3,0,280)
        self.assertAlmostEqual(s.qty,.75)
        e.close(s,123,0,events,'rotation',281,0)
        self.assertEqual(events[-1][7],-.75);self.assertEqual(s.qty,0)

    def test_trailing_cannot_widen_when_atr_rises(self):
        m=e.market_from_frames(fixture());p=params('trail3')
        m.features['atr'][:]=10;m.features['atr'][286:]=40
        m.prices[281,0,1]=150;m.prices[289,0,2]=110
        run=e.simulate(m,p,1.25,start=str(m.dates[280].date()),end=str(m.dates[292].date()),ledger=True)
        stops=[x for x in run['events'] if x[6]=='stop']
        self.assertTrue(any(abs(x[7]-120)<1e-10 for x in stops))

    def test_intraday_drawdown_exceeds_close_only_drawdown(self):
        rows=np.array([[0,.8,1.1,1-.8/1.1,0,0,1,0,1]])
        run=dict(dates=pd.DatetimeIndex(['2025-01-01']),rows=rows,asset_logs=np.zeros((1,1)),trade_logs=np.zeros((0,4)))
        self.assertAlmostEqual(e.summarize(run)['max_drawdown'],1-.8/1.1)

    def test_cagr_uses_all_calendar_days(self):
        returns=np.array([.1,-.1,0,0]);rows=np.zeros((4,9));rows[:,0]=returns;rows[:,1]=np.minimum(1,1+returns);rows[:,2]=np.maximum(1,1+returns)
        logs=np.log1p(returns)
        run=dict(dates=pd.date_range('2025-01-01',periods=4),rows=rows,asset_logs=logs[:,None],
                 trade_logs=np.column_stack([np.arange(4),np.zeros(4),np.ones(4),logs]))
        metric=e.summarize(run)
        self.assertAlmostEqual(metric['cagr'],.99**(365.25/4)-1)
        self.assertAlmostEqual(metric['max_drawdown'],.1)

    def test_bankruptcy_is_not_healthy_clipped_return(self):
        s=e.State(equity=100,qty=3,asset=0,mark=100);events=[]
        e.mark(s,50,events)
        self.assertTrue(s.bankrupt);self.assertEqual(s.equity,0)


if __name__=='__main__':unittest.main()
