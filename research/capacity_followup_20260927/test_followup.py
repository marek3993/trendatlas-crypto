import copy,importlib.util,json,unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import common,market,signals,ledger,designer,evaluate,identity,perpetual_gate,run

def toy(n=90):
    d=pd.date_range('2021-01-01',periods=n,freq='4h');p=np.ones((n,2,5))*100;p[:,:,4]=1e9
    return dict(dates=d,assets=['BTCUSDT','ALTUSDT'],prices=p,quote=np.ones((n,2))*1e9,eligible=np.ones((n,2),bool))
def target(m,weights=(1.,0.)):
    return dict(weights=np.tile(weights,(len(m['dates']),1)),event=np.zeros(len(m['dates']),bool))
def sim(m,t,**kw):return ledger.simulate(m,t,start=m['dates'][0],end=m['dates'][-1],**kw)

class Followup(unittest.TestCase):
    def test_numpy_bool_json_serialization(self):
        x={'passed':np.bool_(True),'value':np.float64(.4)};self.assertEqual(json.loads(common.canonical(run.clean(x))),{'passed':True,'value':.4})
    def test_variable_timestamp_funding_coverage(self):
        d=pd.to_datetime(['2021-01-01 00:00:00','2021-01-01 08:00:00','2021-01-01 10:00:00','2021-01-01 12:00:00']);f=pd.DataFrame({'calc_time':[int(t.timestamp()*1000)+2 for t in d],'funding_interval_hours':[8,8,2,2]})
        gaps,changes=perpetual_gate.funding_coverage(f,d[0],d[-1]);self.assertEqual(gaps,[]);self.assertEqual(len(changes),1)
    def test_ticker_reuse_is_new_identity(self):
        dates=pd.date_range('2022-01-01','2023-12-31');f=pd.DataFrame({'close':10.,'quote_volume':1e8},index=dates)
        split=identity.split({'LUNAUSDT':f},24);self.assertNotIn('LUNAUSDT',split)
        self.assertLess(split['LUNAUSDT@original'].index.max(),pd.Timestamp('2022-05-13'))
        self.assertGreater(split['LUNAUSDT@20220531'].index.min(),pd.Timestamp('2022-05-31'))
        close=pd.DataFrame({k:v.close for k,v in split.items()}).reindex(dates);quote=close*1e7;ok=market.eligibility(close,quote,close.notna())
        self.assertFalse(ok.loc['2022-12-31','LUNAUSDT@20220531']);self.assertTrue(ok.loc['2023-06-05','LUNAUSDT@20220531'])
    def test_epoch_split_prefix_invariant(self):
        dates=pd.date_range('2021-01-01','2024-01-01',freq='4h');f=pd.DataFrame({'close':np.arange(len(dates))+1.},index=dates)
        full=identity.split({'BNXUSDT':f},4);prefix=identity.split({'BNXUSDT':f.loc[:'2022-12-31']},4)
        pd.testing.assert_frame_equal(full['BNXUSDT@original'].loc[:'2022-12-31'],prefix['BNXUSDT@original'])
    def test_cash_cost_reconciliation(self):
        m=toy();r=sim(m,target(m),details=True);summary=ledger.summarize(r)
        self.assertAlmostEqual(summary['fee_usd'],sum(f['fee'] for f in r['fills']));self.assertAlmostEqual(summary['slippage_usd'],sum(f['slippage'] for f in r['fills']))
    def test_frozen_protocol(self):
        f=json.loads((common.HERE/'protocol_freeze.json').read_text());self.assertEqual(common.digest(common.HERE/'contract.json'),f['contract_sha256']);self.assertEqual(common.SPEC['primary_usd'],100);self.assertFalse(common.SPEC['orders_allowed'])
    def test_partial_buy_and_ttl(self):
        m=toy();m['quote'][:]=100000;r=sim(m,target(m),capital=1000,mult=0,details=True,liquidate=False)
        self.assertEqual(len(r['fills']),6);self.assertAlmostEqual(sum(f['notional'] for f in r['fills']),600)
        o=r['orders'][0];self.assertEqual(o['status'],'CANCELLED_TTL');self.assertAlmostEqual(o['average_price'],100);self.assertAlmostEqual(o['unfilled_quantity'],4)
    def test_partial_exit_is_real(self):
        m=toy();m['quote'][:]=100000;t=target(m);t['weights'][12:]=0
        r=sim(m,t,capital=1000,mult=0,details=True,liquidate=False)
        self.assertEqual(len([f for f in r['fills'] if f['side']=='sell']),6);self.assertEqual(r['residual_positions'],{});self.assertAlmostEqual(r['ending_cash'],1000)
    def test_exit_ttl_does_not_force_fill(self):
        m=toy();t=target(m);t['weights'][10:]=0;m['quote'][8:,0]=100
        with self.assertRaises(ledger.UnsafeExecution) as cm:sim(m,t,capital=1000,details=True)
        self.assertIn('TTL',str(cm.exception));r=cm.exception.partial;self.assertTrue(r['residual_positions']);self.assertFalse(any(f['side']=='sell' for f in r['fills']))
    def test_entry_unavailable_cancels_without_rejecting_cash(self):
        m=toy();m['prices'][2:,0,0]=np.nan;r=sim(m,target(m),liquidate=False,details=True)
        self.assertEqual(r['ending_cash'],100);self.assertEqual(r['fills'],[]);self.assertEqual(r['orders'][0]['status'],'CANCELLED_TTL')
    def test_missing_held_quote_fails(self):
        m=toy();m['prices'][8,0,:4]=np.nan
        with self.assertRaisesRegex(ledger.UnsafeExecution,'Missing actual held'):sim(m,target(m))
    def test_participation_each_fill(self):
        m=toy();m['quote'][:]=250000;r=sim(m,target(m),capital=1000,details=True)
        for f in r['fills']:self.assertLessEqual(f['notional'],f['capacity_quote']*.001+1e-8)
    def test_latency_and_initial_delay(self):
        m=toy();t=target(m)
        a=ledger.simulate(m,t,start='2021-01-02',end=m['dates'][-1],details=True)
        b=ledger.simulate(m,t,start='2021-01-02',end=m['dates'][-1],lag=3,details=True)
        self.assertEqual(a['fills'][0]['date'],'2021-01-02 00:00:00');self.assertEqual(b['fills'][0]['date'],'2021-01-02 04:00:00')
        self.assertEqual(a['fills'][0]['signal_at'],b['fills'][0]['signal_at'])
        for f in a['fills']:self.assertGreater(pd.Timestamp(f['date']),pd.Timestamp(f['available_at']))
    def test_daily_close_D_plus_one(self):
        m=toy();t=target(m,(0,0));t['weights'][5:,0]=1;r=sim(m,t,details=True)
        self.assertEqual(r['fills'][0]['date'],'2021-01-02 04:00:00');self.assertEqual(r['fills'][0]['available_at'],'2021-01-02 00:01:00')
    def test_cash_and_asset_identity(self):
        m=toy();m['prices'][:,1,:4]=np.linspace(100,1000,len(m['dates']))[:,None]
        r=sim(m,target(m),mult=0);self.assertAlmostEqual(r['ending_nav'],100)
    def test_two_assets_and_episode_reconciliation(self):
        m=toy();m['prices'][:,0,:4]=np.linspace(100,150,len(m['dates']))[:,None];m['prices'][:,1,:4]=np.linspace(100,60,len(m['dates']))[:,None]
        r=sim(m,target(m,(.5,.5)),details=True);self.assertGreaterEqual(r['daily'].cash_usd.min(),-1e-8)
        self.assertAlmostEqual(sum(ep['log_growth'] for ep in r['episodes']),np.log(r['ending_nav']/100),places=10)
        self.assertEqual(len(r['episodes']),2);self.assertGreater(next(e for e in r['episodes'] if e['asset']=='BTCUSDT')['dollar_pnl'],0)
    def test_no_leverage_short_nan(self):
        m=toy()
        for values in [(1.25,0),(-1,0),(np.nan,0)]:
            with self.assertRaises(ValueError):sim(m,target(m,values))
    def test_exit_dust_remains_visible(self):
        m=toy();m['prices'][15:,0,:4]=1;t=target(m);t['weights'][15:]=0
        with self.assertRaises(ledger.UnsafeExecution) as cm:sim(m,t,details=True)
        self.assertTrue(cm.exception.partial['residual_positions']);self.assertFalse(any(f['side']=='sell' for f in cm.exception.partial['fills']))
    def test_new_target_cancels_stale_buy(self):
        m=toy();m['quote'][:]=100000;t=target(m);t['weights'][4:]=[0,1]
        r=sim(m,t,capital=1000,mult=0,details=True,liquidate=False)
        self.assertEqual(r['orders'][0]['status'],'CANCELLED_REPLACED_TARGET')
        self.assertFalse(any(f['asset']=='BTCUSDT' and f['side']=='buy' and f['date']>='2021-01-02 00:00:00' for f in r['fills']))
    def test_parent_ledger_parity_no_cap_binding(self):
        sp=importlib.util.spec_from_file_location('parent_parity',common.PARENT/'ledger.py');old=importlib.util.module_from_spec(sp);sp.loader.exec_module(old)
        m=toy();m['prices'][:,0,:4]=np.linspace(100,120,len(m['dates']))[:,None];t=target(m);x=pd.DataFrame(dict(asset='BTCUSDT',weight=1.),index=m['dates'])
        a=old.simulate(m,x,terminal_exit=False,fold_reset=False,capacity=False)
        b=sim(m,t,liquidate=False)
        np.testing.assert_allclose(a['daily'].equity,b['daily'].equity,atol=1e-12,rtol=0)
        for k in ['cagr','mdd','sharpe','turnover','costs']:self.assertAlmostEqual(old.summarize(a)[k],ledger.summarize(b)[k],places=9)
    def test_future_ledger_invariance(self):
        m=toy();t=target(m);a=sim(m,t,liquidate=False);m['prices'][50:,:,:4]*=2;b=sim(m,t,liquidate=False)
        pd.testing.assert_frame_equal(a['daily'].iloc[:50],b['daily'].iloc[:50])
    def test_two_costs_worse(self):
        m=toy();t=target(m);self.assertLess(ledger.summarize(sim(m,t,mult=2))['cagr'],ledger.summarize(sim(m,t))['cagr'])
    def test_missing_symbols_do_not_rank_as_zero(self):
        ix=pd.date_range('2019-01-01',periods=500);c=pd.DataFrame({'BTCUSDT':100.,'ALTUSDT':50.},index=ix);q=c*1e7;o=c.notna();one=market.eligibility(c,q,o)
        c['NEW']=np.nan;q['NEW']=np.nan;o['NEW']=False;two=market.eligibility(c,q,o);pd.testing.assert_frame_equal(one,two[one.columns]);self.assertFalse(two.NEW.any())
    def test_new_listing_can_enter_after_history(self):
        ix=pd.date_range('2019-01-01',periods=800);c=pd.DataFrame({'BTCUSDT':100.,'NEWUSDT':50.},index=ix);c.loc[ix[:400],'NEWUSDT']=np.nan;q=c*1e7;a=market.eligibility(c,q,c.notna())
        self.assertFalse(a.NEWUSDT.iloc[:764].any());self.assertTrue(a.NEWUSDT.iloc[764])
    def test_known_unavailability_before_rank(self):
        ix=pd.date_range('2019-01-01',periods=400);c=pd.DataFrame({str(j):100. for j in range(11)},index=ix);q=pd.DataFrame({str(j):(100-j)*1e7 for j in range(11)},index=ix);allowed=c.notna();allowed['0']=False
        a=market.eligibility(c,q,c.notna(),allowed);self.assertFalse(a['0'].any());self.assertTrue(a['10'].iloc[-1])
    def test_strict_candidate_schema(self):
        c=designer.initial()[0]
        for bad in [dict(c,evaluator='evil'),dict(c,top_k=True),dict(c,lookback=31)]:
            with self.assertRaises(ValueError):common.validate(bad)
        with self.assertRaises(ValueError):designer.strict_json('{"candidates":[],"candidates":[]}')
    def test_no_OOS_at_designer_boundary(self):
        with self.assertRaises(ValueError):designer.Designer().propose('deepseek',[{'scope':'outer_oos'}],[],set(),1)
    def test_arms_equal_without_key(self):
        parents=designer.initial()[:6];seen={common.cid(c) for c in designer.initial()}
        with patch.object(designer,'api_key',return_value=(None,'unavailable')):
            a=designer.Designer().propose('deterministic',[],parents,seen,1);b=designer.Designer().propose('deepseek',[],parents,seen,1)
        self.assertEqual(a,b);self.assertEqual(len(a),4)
    def test_grid_and_neighbors_canonical(self):
        self.assertEqual(len(designer.panel()),24);self.assertEqual(len(designer.initial()),10);self.assertEqual(len({common.cid(c) for c in designer.grid()}),len(designer.grid()))
        c=dict(designer.initial()[0],blend=True,lookback=90);self.assertFalse(any(n==c for n in designer.neighbors(c)))
    def test_drawdown_direction(self):
        a={k:1. for k,d in evaluate.OBJECTIVES};a.update(status='VALID',candidate_id='a',mdd=.1);b=dict(a,candidate_id='b',mdd=.3)
        self.assertTrue(evaluate.dominates(a,b));self.assertFalse(evaluate.dominates(b,a))
    def test_benchmark_no_CAGR_only_win(self):
        b=dict(status='VALID',cagr=.3,mdd=.3,sharpe=1.,calmar=1.,positive_profit_asset_share=1.)
        a=dict(b,cagr=.6,mdd=.8,sharpe=.2);self.assertFalse(evaluate.benchmark_gate(a,b)['passed'])
        a=dict(b,positive_profit_asset_share=.5);self.assertTrue(evaluate.benchmark_gate(a,b)['passed'])

if __name__=='__main__':unittest.main(verbosity=2)
