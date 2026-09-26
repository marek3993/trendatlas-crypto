import unittest
import numpy as np
import pandas as pd
from common import *
from replay import simulate
from signals import Controller

def fixture():
    dates=pd.date_range('2019-01-01',periods=800)
    frames={}
    for a,k in [('BTC',.001),('ETH',.0015)]:
        c=100*np.exp(np.arange(len(dates))*k)
        frames[a]=pd.DataFrame(dict(open=c,high=c*1.01,low=c*.99,close=c*1.002),index=dates)
    m=enhanced_market(e.market_from_frames(frames))
    m.features={k:v.copy() for k,v in m.features.items()}
    return m

class Tests(unittest.TestCase):
    def test_default_engine_equivalence(self):
        m=fixture();p=legacy_spec()['variants'][17]
        kw=dict(start='2020-01-01',end='2020-12-31',ledger=True)
        a=e.simulate(m,p,1.25,**kw);b=simulate(m,p,1.25,**kw)
        np.testing.assert_array_equal(a['rows'],b['rows']);self.assertEqual(a['events'],b['events'])
    def test_hold_has_no_daily_resize(self):
        r=simulate(fixture(),no_risk(),3,start='2020-01-01',end='2020-12-31',controller=Controller(dict(family='hold')),ledger=True)
        self.assertEqual(sum(v[6]=='entry' for v in r['events']),1)
        self.assertFalse(any(v[6]=='resize' for v in r['events']))
        self.assertTrue(all(pd.Timestamp(v[0])-pd.Timestamp(v[1])>=pd.Timedelta(days=2) for v in r['signals']))
    def test_future_mutation_does_not_change_prefix(self):
        m=fixture();p=dict(family='dual_momentum',lookback=90,schedule='monthly',vol_target=.5)
        kw=dict(start='2020-01-01',end='2020-08-31')
        a=simulate(m,no_risk(),1.25,controller=Controller(p),**kw)
        idx=m.dates>kw['end'];m.prices[idx]*=9
        raw={asset:pd.DataFrame(m.prices[:,j],index=m.dates,columns=['open','high','low','close']) for j,asset in enumerate(m.assets)}
        changed=enhanced_market(e.market_from_frames(raw))
        b=simulate(changed,no_risk(),1.25,controller=Controller(p),**kw)
        np.testing.assert_array_equal(a['rows'],b['rows'])
    def test_cash_zero(self):
        r=simulate(fixture(),no_risk(),1.25,start='2020-01-01',end='2020-12-31',controller=Controller(dict(family='cash')))
        self.assertEqual(e.summarize(r)['total_return'],0)
    def test_no_downward_signal_averaging(self):
        m=fixture();p=dict(family='dual_momentum',lookback=90,schedule='monthly',vol_target=.5)
        r=simulate(m,no_risk(),1.25,start='2020-01-01',end='2020-12-31',controller=Controller(p),ledger=True)
        self.assertLessEqual(e.summarize(r)['max_realized_exposure'],1.25+1e-10)
        self.assertLess(e.summarize(r)['log_reconciliation_error'],1e-10)
    def test_sma_is_not_ema(self):
        m=fixture();self.assertNotEqual(float(m.features['sma200'][400,0]),float(m.features['ema200'][400,0]))
    def test_monthly_rotation_waits_for_calendar(self):
        m=fixture();ctrl=Controller(dict(family='cross_sectional',lookback=90,schedule='monthly',vol_target=.5));s=e.State()
        i=m.dates.get_loc('2020-02-05');a,_=ctrl(m,no_risk(),i-2,s,i)
        self.assertEqual(m.assets[a],'ETH')
        m.features['mom90'][i-1,m.assets.index('BTC')]=99
        b,_=ctrl(m,no_risk(),i-1,s,i+1);self.assertEqual(a,b)
    def test_slow_holding_overridden_by_absolute_exit(self):
        m=fixture();btc=m.assets.index('BTC');s=e.State(asset=btc,qty=.001,mark=100,equity=1,entry_i=399)
        ctrl=Controller(dict(family='slow_hysteresis',lookback=90,schedule='monthly',vol_target=.5,min_hold=60,hysteresis=.1))
        a,_=ctrl(m,no_risk(),400,s,402);self.assertEqual(a,btc)
        m.features['mom90'][401,btc]=-.1
        a,_=ctrl(m,no_risk(),401,s,403);self.assertEqual(a,-1)
    def test_all_families_executed_without_overlay(self):
        from search import variants,FAMILIES
        m=fixture();seen=set()
        for p in variants():
            if p['family'] in seen:continue
            seen.add(p['family']);r=simulate(m,no_risk(),1.25,start='2020-01-01',end='2020-12-31',controller=Controller(p),ledger=True)
            self.assertTrue(np.isfinite(r['rows']).all())
            self.assertFalse(any(v[6] in ('stop','partial_tp') for v in r['events']))
        self.assertEqual(seen,set(FAMILIES))
    def test_pareto_rejects_high_growth_high_drawdown(self):
        from search import choose
        m=fixture();r=simulate(m,no_risk(),1.25,start='2020-01-01',end='2020-12-31',controller=Controller(dict(family='hold')))
        x=metrics(r);x.update(cagr=.15,max_drawdown=.2,calmar=.75,delayed_entry_cagr=.1,double_cost_cagr=.1,parameter_stability=1.,max_realized_exposure=1.)
        bad=dict(x,cagr=1.8,max_drawdown=.7,calmar=1.8/.7)
        records={'valid':{'2020':x},'bad':{'2020':bad}};vm={k:dict(family='dual_momentum') for k in records}
        self.assertEqual(choose(records,dict(mode='robust',cap=1.25),'2020','all_growth',vm),'valid')

if __name__=='__main__':unittest.main()
