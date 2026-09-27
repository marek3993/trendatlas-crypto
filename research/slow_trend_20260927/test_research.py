import unittest
import numpy as np
import pandas as pd
from common import config,validate,neighbors
from ledger import replay
from signals import targets,trend,risk_weights,panel

def fixture(perp=False,days=12):
    dates=pd.date_range('2020-01-01',periods=days*6,freq='4h');ds=pd.date_range('2020-01-01',periods=days,freq='D');names=['BTCUSDT','ETHUSDT'];p=np.ones((len(dates),2,5))*100;p[:,:,4]=1000
    c=pd.DataFrame(100.,index=ds,columns=names);base=pd.DataFrame(True,index=ds,columns=names)
    m=dict(track='perp' if perp else 'spot',assets=names,dates=dates,days=ds,prices=p,mark=p[:,:,:4].copy(),quote=np.ones((len(dates),2))*1e9,mark_missing=np.zeros((len(dates),2),bool),funding=[],close=c,high=c,low=c,base=base,eligible=base,rank=pd.DataFrame([[1,2]]*days,index=ds,columns=names),vol=c*.005,daily_returns=c*0)
    w=np.zeros((days,2));ev=np.ones(days,bool)
    return m,w,ev

class LedgerTests(unittest.TestCase):
    def run_case(self,m,w,e,**kw):return replay(m,(w,e),'2020-01-01','2020-01-12',details=True,**kw)
    def test_own_asset_identity(self):
        m,w,e=fixture();w[:,0]=.5;m['prices'][15:,1,:4]=1000;m['mark'][15:,1,:]=1000
        r=self.run_case(m,w,e);self.assertLess(r['metrics']['final_nav'],100);self.assertGreater(r['metrics']['final_nav'],99)
        self.assertTrue(all(f['asset']=='BTCUSDT' for f in r['fills']))
    def test_latency(self):
        m,w,e=fixture();w[:,0]=1;r=self.run_case(m,w,e)
        self.assertEqual(r['fills'][0]['date'],'2020-01-02 04:00:00')
        self.assertTrue(all(pd.Timestamp(f['date'])>pd.Timestamp(f['available_at']) for f in r['fills']))
        z=self.run_case(m,w,e,delay=1);self.assertEqual(z['fills'][0]['date'],'2020-01-02 08:00:00')
    def test_partial_and_ttl(self):
        m,w,e=fixture();w[:,0]=1;e[1:]=False;m['quote'][:,0]=1000
        r=self.run_case(m,w,e);self.assertGreater(r['metrics']['partial_fills'],0);self.assertGreater(r['metrics']['ttl_cancellations'],0)
        self.assertTrue(any(o['reason']=='TTL_residual_kept' and abs(o['unfilled_quantity'])>.1 for o in r['orders']))
    def test_dust_is_marked_not_filled(self):
        m,w,e=fixture();w[:3,0]=1;m['prices'][24:,0,:4]=5;m['mark'][24:,0,:]=5
        r=self.run_case(m,w,e);self.assertTrue(r['metrics']['reliable']);self.assertGreater(r['metrics']['residual_usd'],0)
        self.assertTrue(all(f['quantity']>0 for f in r['fills']));self.assertTrue(r['episodes'][0]['closed'] is False)
    def test_funding_signed(self):
        m,w,e=fixture(True);w[:,0]=-.5;m['funding']=[(t+pd.Timedelta(milliseconds=2),0,.001) for t in m['dates'][::2]]
        r=self.run_case(m,w,e);self.assertGreater(r['metrics']['funding_credit_usd'],0);self.assertEqual(r['metrics']['funding_debit_usd'],0)
        w[:,0]=.5;a=self.run_case(m,w,e);b=self.run_case(m,w,e,cost_mult=2)
        self.assertGreater(b['metrics']['funding_debit_usd'],a['metrics']['funding_debit_usd']*1.9)
        self.assertLess(a['metrics']['log_reconciliation_error'],1e-9)
    def test_adverse_margin(self):
        m,w,e=fixture(True);w[:,0]=-.9;m['mark'][20,0,1]=180
        r=self.run_case(m,w,e,mm=.2);self.assertIn('margin_proximity',r['metrics']['flags'])
        risk=[f for f in r['fills'] if f['signal_kind']=='published_4h_margin_risk']
        self.assertTrue(risk);self.assertTrue(all(pd.Timestamp(f['date'])>pd.Timestamp(f['available_at']) for f in risk))
    def test_gross_risk_uses_published_bar(self):
        m,w,e=fixture(True);w[:,0]=-.9;e[1:]=False;m['prices'][12:,0,:4]=120;m['mark'][12:,0,:]=120
        r=self.run_case(m,w,e);risk=[f for f in r['fills'] if f['signal_kind']=='published_4h_gross_risk']
        self.assertTrue(risk);self.assertGreaterEqual(pd.Timestamp(risk[0]['date']),m['dates'][14])
        self.assertTrue(all(pd.Timestamp(f['date'])>pd.Timestamp(f['available_at']) for f in risk))
        delayed=self.run_case(m,w,e,delay=1);slow=[f for f in delayed['fills'] if f['signal_kind']=='published_4h_gross_risk']
        self.assertTrue(slow);self.assertGreaterEqual(pd.Timestamp(slow[0]['date']),pd.Timestamp(risk[0]['date'])+pd.Timedelta(hours=4))
    def test_future_target_does_not_change_gross_cap(self):
        m,w,e=fixture(True);w[:,0]=-.8;e[1:]=False;r=self.run_case(m,w,e)
        w[-1,0]=1.25;z=self.run_case(m,w,e)
        np.testing.assert_allclose(r['daily'].nav,z['daily'].nav)
    def test_missing_does_not_fill(self):
        m,w,e=fixture();w[:,0]=1;m['prices'][7:9,0]=np.nan;m['mark'][7:9,0]=np.nan
        r=self.run_case(m,w,e);self.assertFalse(any(f['date'] in ['2020-01-02 04:00:00','2020-01-02 08:00:00'] for f in r['fills']))
    def test_spot_cannot_short(self):
        m,w,e=fixture();w[:,0]=-.5
        with self.assertRaises(AssertionError):self.run_case(m,w,e)
    def test_whole_episode_cash_reconciles(self):
        m,w,e=fixture();w[:5,0]=.5;m['prices'][20:,0,:4]=110;m['mark'][20:,0,:]=110
        r=self.run_case(m,w,e);self.assertEqual(r['metrics']['trades'],1);self.assertEqual(r['metrics']['open_episodes'],0);self.assertLess(r['metrics']['log_reconciliation_error'],1e-9)
        self.assertAlmostEqual(r['metrics']['no_top3_cagr'],0,places=8)
    def test_precision_residual_not_global_failure(self):
        m,w,e=fixture();w[:,0]=.3333;r=self.run_case(m,w,e,coarse=True);self.assertTrue(r['metrics']['reliable'])

class SignalTests(unittest.TestCase):
    def test_schema_cannot_mutate_evaluator(self):
        with self.assertRaises(ValueError):validate(dict(config(),fee_bps=0))
        with self.assertRaises(ValueError):validate(dict(config(),confirm=True))
        with self.assertRaises(ValueError):config(family='H',weighting='equal')
    def test_missing_cash_slots(self):
        m,w,e=fixture(days=400);m['close'].iloc[:]=np.arange(400)[:,None]+100
        t,_=targets(m,config(family='H',top_k=5,weighting='inverse_vol'))
        self.assertAlmostEqual(float(t[-1].sum()),.4)
    def test_prefix_causality(self):
        m,w,e=fixture(days=400);m['close']=m['close'].copy();m['close'].iloc[:,0]=100+np.arange(400)*.1
        a=trend(m,'sma50',7,.01);m['close'].iloc[300:,0]*=100;b=trend(m,'sma50',7,.01)
        np.testing.assert_array_equal(a[:300],b[:300])
    def test_breakout_prior_high(self):
        m,w,e=fixture(days=100);m['close'].iloc[30:,0]=110;m['high']=m['close'].copy();m['low']=m['close'].copy()
        s=trend(m,'breakout20');self.assertEqual(s[30,0],1)
    def test_negative_trend_cash(self):
        m,w,e=fixture(days=400);m['close'].iloc[:]=1000-np.arange(400)[:,None]
        t,_=targets(m,config(family='H',top_k=2,weighting='inverse_vol'));self.assertEqual(float(t.sum()),0)
    def test_pinned_panel_no_B_C(self):
        self.assertEqual(len(panel()),184);self.assertEqual(set(c['family'] for c in panel()),{'F','G','H','D'})
        self.assertTrue(all(n['family']=='F' for n in neighbors(config())))

if __name__=='__main__':unittest.main()
