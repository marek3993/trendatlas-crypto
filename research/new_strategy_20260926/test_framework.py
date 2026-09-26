import copy,importlib.util,json,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import common,ledger,signals,market,designer,evaluate

def toy(n=72,freq='4h'):
    dates=pd.date_range('2021-01-01',periods=n,freq=freq);p=np.ones((n,2,5))*100;p[:,:,4]=1e8
    return dict(dates=dates,assets=['BTCUSDT','ALTUSDT'],prices=p,eligible=np.ones((n,2),bool),quote=np.ones((n,2))*1e9)
def t(m,a='BTCUSDT'):
    return pd.DataFrame(dict(asset=a,weight=0. if a=='CASH' else 1.),index=m['dates'])

class Framework(unittest.TestCase):
    def test_contract(self):
        s=common.SPEC;self.assertEqual(s['evolution']['population'],10);self.assertEqual(s['evolution']['survivors'],6);self.assertEqual(s['evolution']['new_mutations'],4)
        self.assertFalse(s['orders_allowed']);self.assertFalse(s['production_changes_allowed']);self.assertFalse(s['forward']['sealed_available'])
    def test_parent_daily_ledger_parity(self):
        path=common.ROOT/'research/archeology_20260926/engine.py';sp=importlib.util.spec_from_file_location('archaeology_parent',path);parent=importlib.util.module_from_spec(sp);sp.loader.exec_module(parent)
        m=toy(24,'D');m['prices'][:,0,:4]=np.linspace(100,130,24)[:,None];a=t(m);a.iloc[12:15]=['CASH',0.]
        with patch.object(parent,'spec',ledger.spec):old=parent.simulate(m,a)
        new=ledger.simulate(m,a,rebalance=True,capacity=False)
        np.testing.assert_allclose(old['daily'].net_return,new['daily'].net_return,atol=1e-14,rtol=0)
        for k in ['cagr','mdd','sharpe','calmar','costs','turnover']:self.assertAlmostEqual(parent.summarize(old)[k],ledger.summarize(new)[k],places=12)
    def test_asset_identity(self):
        m=toy();m['prices'][:,1,:4]=np.linspace(100,1000,len(m['dates']))[:,None]
        r=ledger.simulate(m,t(m),mult=0);self.assertTrue(r['daily'].net_return.eq(0).all())
        with self.assertRaises(ValueError):ledger.simulate(m,t(m,'BASE'))
    def test_latency_D_plus_one(self):
        m=toy();x=t(m,'CASH');x.loc['2021-01-01 20:00:00']=['BTCUSDT',1.]
        r=ledger.simulate(m,x,details=True);fill=r['fills'][0]
        self.assertEqual(fill['date'],'2021-01-02 04:00:00');self.assertEqual(fill['available_at'],'2021-01-02 00:01:00')
        with self.assertRaises(ValueError):ledger.simulate(m,x,lag=1)
    def test_adverse_fills_and_complete_episodes(self):
        m=toy();x=t(m);x.iloc[20:]=['ALTUSDT',1.];r=ledger.simulate(m,x,details=True)
        self.assertEqual(len(r['episodes']),2)
        for f in r['fills']:self.assertGreater(f['fill_price'],100) if f['side']=='buy' else self.assertLess(f['fill_price'],100)
        self.assertAlmostEqual(sum(e['log_growth'] for e in r['episodes']),np.log(r['daily'].equity.iloc[-1]))
    def test_delay_includes_carried_target_at_fold_start(self):
        m=toy();x=t(m)
        normal=ledger.simulate(m,x,start='2021-01-02',details=True)
        delayed=ledger.simulate(m,x,start='2021-01-02',lag=3,details=True)
        self.assertEqual(normal['fills'][0]['date'],'2021-01-02 00:00:00')
        self.assertEqual(delayed['fills'][0]['date'],'2021-01-02 04:00:00')
        self.assertEqual(normal['fills'][0]['signal_date'],delayed['fills'][0]['signal_date'])
    def test_spot_no_funding_or_short_or_leverage(self):
        m=toy();r=ledger.simulate(m,t(m));self.assertEqual(r['daily'].funding.sum(),0.)
        for w in [-1.,1.25]:
            x=t(m);x.weight=w
            with self.assertRaises(ValueError):ledger.simulate(m,x)
    def test_capacity_is_not_ignored(self):
        m=toy();m['quote'][:]=1.
        with self.assertRaisesRegex(ValueError,'Participation'):ledger.simulate(m,t(m))
    def test_missing_exit_quote_fails(self):
        m=toy();x=t(m);x.iloc[8:]=['CASH',0.];m['prices'][10,0,:4]=np.nan
        with self.assertRaisesRegex(ValueError,'Missing actual'):ledger.simulate(m,x)
    def test_pit_and_zero_fill_prohibited(self):
        ix=pd.date_range('2019-01-01',periods=450);c=pd.DataFrame({'BTCUSDT':100.,'ALTUSDT':50.},index=ix);q=c*1e7;obs=c.notna()
        a=market.eligibility(c,q,obs);c['FUTURE']=np.nan;q['FUTURE']=np.nan;obs['FUTURE']=False
        b=market.eligibility(c,q,obs);pd.testing.assert_frame_equal(a,b[a.columns]);self.assertFalse(b.FUTURE.any());self.assertFalse(a.iloc[:364].any().any())
    def test_slow_confirmation(self):
        x=signals.latch([True]*5+[False]*2+[True]+[False]*5,5)
        self.assertFalse(x[3]);self.assertTrue(x[4]);self.assertTrue(x[6]);self.assertFalse(x[-1])
    def test_cohort_cannot_authorize_preformation_trade(self):
        m=market.load('2021-01-02 20:00:00');cut=pd.Timestamp('2020-12-31 20:00:00')
        self.assertFalse(m['eligible'][m['dates']<cut].any())
        self.assertTrue(m['eligible'][m['dates']==cut,m['assets'].index('BTCUSDT')].all())
        r=ledger.simulate(m,signals.baseline(m,'BTC_hold'),start='2021-01-01',details=True)
        self.assertEqual(r['fills'][0]['date'],'2021-01-01 04:00:00')
    def test_unavailable_asset_removed_before_liquidity_rank(self):
        ix=pd.date_range('2019-01-01',periods=400)
        c=pd.DataFrame({str(i):100. for i in range(11)},index=ix)
        q=pd.DataFrame({str(i):float(100-i)*1e7 for i in range(11)},index=ix)
        allowed=c.notna();allowed['0']=False
        ok=market.eligibility(c,q,c.notna(),allowed)
        self.assertFalse(ok['0'].any());self.assertTrue(ok['10'].iloc[-1])
    def test_json_rejects_untrusted_edits(self):
        c=designer.initial('A',1)[0]
        self.assertEqual(len(designer.strict_response(json.dumps({'candidates':[c]*4}),'A')),4)
        for payload in [{'candidates':[dict(c,engine='evil')]*4},{'candidates':[dict(c,slow=True)]*4},{'candidates':[dict(c,family='B')]*4}]:
            with self.assertRaises(ValueError):designer.strict_response(json.dumps(payload),'A')
        with self.assertRaises(ValueError):designer.strict_response('{"candidates":[],"candidates":[]}','A')
    def test_designer_cannot_see_oos(self):
        d=designer.Designer()
        with self.assertRaises(ValueError):d.propose('A',[{'scope':'oos'}],[],set(),1)
    def test_deterministic_mutations(self):
        p=designer.initial('A',1);seen={common.candidate_id(x) for x in p}
        with patch.dict('os.environ',{},clear=True):
            a=designer.Designer().propose('A',[],p[:6],seen,5);b=designer.Designer().propose('A',[],p[:6],seen,5)
        self.assertEqual(a,b);self.assertEqual(len(a),4);self.assertFalse(seen&{common.candidate_id(x) for x in a})
    def test_pareto_drawdown_direction(self):
        a=dict(status='VALID',**{k:1. for k,d in evaluate.OBJECTIVES});a.update(candidate_id='a',mdd=.1)
        b=dict(a,candidate_id='b',mdd=.3);self.assertTrue(evaluate.dominates(a,b));self.assertFalse(evaluate.dominates(b,a))
    def test_year_exit_once_at_close(self):
        m=toy();m['dates']=pd.date_range('2021-12-30',periods=72,freq='4h');r=ledger.simulate(m,t(m),details=True)
        ex=[f for f in r['fills'] if f['kind']=='fold_exit'];self.assertEqual(len(ex),2);self.assertEqual(ex[0]['date'],'2022-01-01 00:00:00')
    def test_future_prices_do_not_change_past_ledger(self):
        m=toy();x=t(m);a=ledger.simulate(m,x,terminal_exit=False);m2=copy.deepcopy(m);m2['prices'][40:,:,:4]*=2
        b=ledger.simulate(m2,x,terminal_exit=False);pd.testing.assert_frame_equal(a['daily'].iloc[:40],b['daily'].iloc[:40])
    def test_double_cost_and_daily_sharpe(self):
        m=toy();x=t(m);a=ledger.summarize(ledger.simulate(m,x));b=ledger.summarize(ledger.simulate(m,x,mult=2.));self.assertLess(b['cagr'],a['cagr'])
    def test_symbol_url_unicode(self):
        from urllib.parse import quote
        self.assertTrue(quote('https://example.com/币USDT',safe=':/').isascii())

if __name__=='__main__':unittest.main(verbosity=2)
