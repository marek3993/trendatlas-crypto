import copy, json, unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import engine as e
import rules

def market(n=12):
    dates=pd.date_range('2021-01-01',periods=n)
    p=np.ones((n,2,5))*100;p[:,:,4]=1000
    return dict(dates=dates,assets=['BTC','ALT'],prices=p,eligible=np.ones((n,2),bool))

class Accounting(unittest.TestCase):
    def test_contract_scope(self):
        s=e.spec();self.assertFalse(s['orders_allowed']);self.assertFalse(s['production_changes_allowed'])
        self.assertEqual(s['optimization'].split(';')[0],'none');self.assertEqual(len(s['folds']),6)
        self.assertEqual(e.digest(e.HERE/'inputs.zip'),s['input_bundle_sha256'])
    def test_cash_and_folds(self):
        r=e.simulate(market(),e.target(market()))
        self.assertTrue(r['daily'].net_return.eq(0).all());self.assertEqual(e.summarize(r)['profitable_folds'],0)
    def test_no_other_asset_return(self):
        m=market();m['prices'][:,1,:4]=np.arange(1,13)[:,None]*100
        r=e.simulate(m,e.target(m,'BTC'),mult=0)
        self.assertTrue(r['daily'].net_return.eq(0).all())
    def test_d_plus_two_and_first_trade_cost(self):
        m=market();t=e.target(m);t.iloc[2]=['BTC',1.]
        r=e.simulate(m,t,details=True);self.assertEqual(r['fills'][0]['date'],'2021-01-05')
        self.assertLess(r['daily'].net_return.loc['2021-01-05'],0)
        self.assertTrue(r['daily'].net_return.iloc[:4].eq(0).all())
    def test_same_day_and_unknown_rejected(self):
        m=market()
        with self.assertRaises(ValueError):e.simulate(m,e.target(m,'BTC'),lag=1)
        with self.assertRaises(ValueError):e.simulate(m,e.target(m,'BASE'))
    def test_missing_exit_quote_rejected(self):
        m=market();t=e.target(m,'BTC');t.iloc[2:]=['CASH',0.];m['prices'][4,0,:4]=np.nan
        with self.assertRaises(ValueError):e.simulate(m,t)
    def test_no_prelisting_fill(self):
        m=market();m['eligible'][:8,1]=False
        with self.assertRaises(ValueError):e.simulate(m,e.target(m,'ALT'))
        t=e.admit(m,e.target(m,'ALT'));self.assertTrue(t.asset.iloc[:8].eq('CASH').all())
    def test_adverse_prices_and_two_rotation_legs(self):
        m=market();t=e.target(m,'BTC');t.iloc[4:]=['ALT',1.]
        r=e.simulate(m,t,details=True);f=pd.DataFrame(r['fills'])
        self.assertTrue((f.loc[f.side.eq('buy'),'fill_price']>100).all())
        self.assertTrue((f.loc[f.side.eq('sell'),'fill_price']<100).all())
        self.assertGreater(r['daily'].turnover.iloc[6],1.9)
    def test_episode_reconciliation_and_resize(self):
        m=market();m['prices'][:,0,:4]=np.linspace(100,150,12)[:,None];t=e.target(m,'BTC');t.iloc[5,1]=.5
        r=e.simulate(m,t);self.assertEqual(len(r['episodes']),1)
        self.assertAlmostEqual(sum(x['log_growth'] for x in r['episodes']),np.log(r['daily'].equity.iloc[-1]))
    def test_double_cost_worse_on_flat_market(self):
        m=market();t=e.target(m,'BTC')
        a=e.simulate(m,t);b=e.simulate(m,t,mult=2)
        self.assertLess(b['daily'].equity.iloc[-1],a['daily'].equity.iloc[-1])
    def test_initial_equity_intrabar_drawdown(self):
        m=market();m['prices'][2,0,1]=150;m['prices'][2,0,2]=50
        r=e.simulate(m,e.target(m,'BTC'),mult=0)
        self.assertAlmostEqual(e.summarize(r)['mdd'],2/3)
    def test_maintenance_liquidation(self):
        m=market();m['prices'][3,0,2]=20
        r=e.simulate(m,e.target(m,'BTC',1.5));self.assertGreater(r['liquidations'],0)
    def test_future_perturbation_cannot_change_past_ledger(self):
        m=market();t=e.target(m,'BTC');a=e.simulate(m,t,terminal_exit=False)['daily']
        changed=copy.deepcopy(m);changed['prices'][8:,:,:4]*=3;b=e.simulate(changed,t,terminal_exit=False)['daily']
        pd.testing.assert_frame_equal(a.iloc[:8],b.iloc[:8])
    def test_corrected_dd_sign_first_return(self):
        total,dd=rules.slice_metrics(pd.Series([-.2,.1]));self.assertAlmostEqual(total,-12);self.assertAlmostEqual(dd,-20)
    def test_future_unlisted_asset_cannot_affect_cross_section(self):
        idx=pd.date_range('2020-01-01',periods=120)
        known=pd.DataFrame({'BTCUSDT':np.arange(100,220),'ALTUSDT':np.arange(100,340,2)},index=idx)
        changed=known.copy();changed['FUTUREUSDT']=np.nan;changed.iloc[100:,2]=np.arange(20)+10
        a=rules.pit_cross_sections(known);b=rules.pit_cross_sections(changed)
        for key in a:pd.testing.assert_frame_equal(a[key].iloc[:100],b[key].loc[:,known.columns].iloc[:100])
        np.testing.assert_array_equal(rules.eligible_rank_scores(np.array([1.,2.]),np.array([True,True])),rules.eligible_rank_scores(np.array([1.,2.,np.nan]),np.array([True,True,False]))[:2])
    def test_exact_open_to_open_holding_duration(self):
        m=market();t=e.target(m);t.iloc[0]=['BTC',1.]
        r=e.simulate(m,t);self.assertEqual(r['episodes'][0]['holding_days'],1.)
    def test_cash_permission_cannot_create_exposure(self):
        m=e.load();x=e.target(m);x['policy']='BASE';x['trend_score']=1.
        out=rules.wrap(m,x);self.assertTrue(out.weight.eq(0).all())
    def test_tail_trigger_relabel_not_future_return(self):
        x=pd.DataFrame({'parent_realistic_ret':[-.06,0.,0.,0.]})
        y=rules.tail.apply_g1_adverse_cooldown(x)
        self.assertEqual(y.guardrail_forced_1p00.tolist(),[False,True,True,False])
    def test_persistence_source_threshold(self):
        x=pd.DataFrame({'candidate_asset':['BTC']*12,'baseline_non_cash':False,'stress_block_day':False,'hard_invalidation':False,'trend_score':0.,'trend_permission_active':False})
        x['btc_candidate_persistence_rows']=rules.persist.compute_btc_candidate_persistence_rows(x)
        states=rules.persist.build_override_states(x,variant_id='btc_candidate_persistence_10d_075')
        self.assertEqual(states[:9],['CASH']*9);self.assertEqual(states[9],'EARLY_RISK')
    def test_selector_replacement_preserves_original_pool(self):
        m=market(320)
        for a,rate in enumerate([.001,.003]):m['prices'][:,a,:4]=(100*np.exp(np.arange(320)*rate))[:,None]
        unrestricted=rules.phase2(m,'vol_adjusted',size=False,schedule='daily')
        restricted=rules.phase2(m,'vol_adjusted',size=False,schedule='daily',pool=['BTC'])
        self.assertEqual(unrestricted.asset.iloc[-1],'ALT')
        self.assertEqual(restricted.asset.iloc[-1],'BTC')
        self.assertFalse(restricted.asset.eq('ALT').any())
    def test_slow_selector_preserves_market_risk_exit(self):
        dates=pd.date_range('2021-01-31',periods=3)
        selected=pd.Series(['BTC','CASH','BTC'],index=dates)
        tables={'BTCUSDT':pd.DataFrame({'dummy':1.},index=dates)}
        with patch.object(rules.p60,'candidate_ok',return_value=True):
            out=rules.slow_core(selected,tables)
        self.assertEqual(out.tolist(),['BTC','CASH','CASH'])

if __name__=='__main__':unittest.main(verbosity=2)
