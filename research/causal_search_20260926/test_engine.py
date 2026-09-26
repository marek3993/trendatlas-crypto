import copy
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
import engine as e
from prepare import variants


def fixture():
    dates=pd.date_range('2019-01-01',periods=400)
    frames={}
    for a,slope in [('BTC',.1),('ETH',.05)]:
        p=100+np.arange(len(dates))*slope
        frames[a]=pd.DataFrame(dict(open=p,high=p*1.01,low=p*.99,close=p*1.002),index=dates)
    return frames


def params(name='combo25'):
    return copy.deepcopy(next(p for p in variants() if p['name']==name and p['trend']=='own100' and p['momentum']==21))


class EngineTests(unittest.TestCase):
    def test_raw_symbol_returns_and_accounting(self):
        s=e.State(equity=100,qty=1,asset=0,mark=100,episode=1)
        ev=[];e.mark(s,110,ev);e.trade(s,-1,110,.001,ev,'exit')
        self.assertAlmostEqual(s.equity,109.89)
        self.assertAlmostEqual(sum(x[2] for x in ev),np.log(109.89/100))

    def test_stop_gap_uses_adverse_open(self):
        m=e.market_from_frames(fixture());p=params('cat3')
        idx=285;m.prices[idx,0,:]=[50,52,45,51]
        run=e.simulate(m,p,1.25,start=str(m.dates[280].date()),end=str(m.dates[290].date()),ledger=True)
        stops=[x for x in run['events'] if x[6] in ('stop','exposure_guard')]
        self.assertTrue(any(x[7]==50 for x in stops))

    def test_partial_tp_keeps_episode_and_remainder(self):
        for fraction in [.25,.5]:
            s=e.State(equity=100,qty=1,asset=0,mark=100,entry=100,entry_atr=10,episode=9)
            p=params();p.update(tp=fraction,tp_atr=2,catastrophic=0,trail=0)
            r,ev,_,_=e.path_replay(s,[125,121,122],p,3,0,300)
            self.assertAlmostEqual(r.qty,1-fraction);self.assertTrue(r.tp_done)
            self.assertTrue(all(x[1]==9 for x in ev))

    def test_trailing_level_not_raised_with_same_bar_high(self):
        s=e.State(equity=100,qty=1,asset=0,mark=100,entry=100,entry_atr=10,trail=90,episode=1)
        p=params('trail3')
        r,_,_,_=e.path_replay(s,[150,95,140],p,3,0,300)
        self.assertEqual(r.trail,90);self.assertGreater(r.qty,0)

    def test_stop_and_tp_path_order_matters_conservatively(self):
        s=e.State(equity=100,qty=1,asset=0,mark=100,entry=100,entry_atr=5,trail=90,episode=1)
        p=params();p.update(tp=.5,tp_atr=2,catastrophic=0)
        high=e.path_replay(s,[120,80,100],p,3,0,300)[0].equity
        low=e.path_replay(s,[80,120,100],p,3,0,300)[0].equity
        self.assertEqual(low,90);self.assertGreater(high,low)

    def test_exposure_guard_exits_at_cap_before_insolvency(self):
        s=e.State(equity=100,qty=2.7,asset=0,mark=100,entry=100,entry_atr=20,episode=1)
        r,ev,mx,reasons=e.path_replay(s,[80,90,85],params('rotation'),3,0,300)
        self.assertIn('exposure_guard',reasons);self.assertAlmostEqual(mx,3);self.assertEqual(r.qty,0);self.assertGreater(r.equity,0)

    def test_prefix_replay_identical_before_future_cut(self):
        frames=fixture();m=e.market_from_frames(frames);p=params()
        end=str(m.dates[349].date());start=str(m.dates[270].date())
        whole=e.simulate(m,p,1.25,start=start,end=end)
        cut=e.market_from_frames({a:f.iloc[:350] for a,f in frames.items()})
        short=e.simulate(cut,p,1.25,start=start,end=end)
        np.testing.assert_array_equal(whole['rows'],short['rows'])
        self.assertEqual(whole['signals'],short['signals'])

    def test_future_price_mutation_cannot_change_past(self):
        frames=fixture();m=e.market_from_frames(frames);p=params()
        start=str(m.dates[270].date());end=str(m.dates[349].date())
        original=e.simulate(m,p,1.25,start=start,end=end)
        for f in frames.values():f.iloc[350:]*=10
        changed=e.simulate(e.market_from_frames(frames),p,1.25,start=start,end=end)
        np.testing.assert_array_equal(original['rows'],changed['rows'])

    def test_same_day_close_not_in_same_day_signal(self):
        frames=fixture();m=e.market_from_frames(frames);i=280
        original=e.choose_target(m,params(),i-2,-1)
        frames['BTC'].iloc[i:,frames['BTC'].columns.get_loc('close')]*=.1
        changed=e.choose_target(e.market_from_frames(frames),params(),i-2,-1)
        self.assertEqual(original,changed)

    def test_listing_admission_uses_past_bars(self):
        m=e.market_from_frames(fixture());p=params()
        self.assertEqual(e.choose_target(m,p,250,-1)[0],-1)
        self.assertGreaterEqual(e.choose_target(m,p,260,-1)[0],0)

    def test_log_contributions_reconcile(self):
        m=e.market_from_frames(fixture())
        run=e.simulate(m,params(),1.25,start=str(m.dates[270].date()),end=str(m.dates[-1].date()))
        stats=e.summarize(run)
        self.assertLess(stats['log_reconciliation_error'],1e-12)
        self.assertLess(stats['trade_log_reconciliation_error'],1e-12)

    def test_stress_replays_costs_not_rescaling_cagr(self):
        m=e.market_from_frames(fixture());kw=dict(start=str(m.dates[270].date()),end=str(m.dates[-1].date()))
        normal=e.summarize(e.simulate(m,params('rotation'),1.25,**kw))
        stress=e.summarize(e.simulate(m,params('rotation'),1.25,cost_multiplier=2,**kw))
        self.assertLess(stress['cagr'],normal['cagr']);self.assertGreater(stress['cost_drag'],normal['cost_drag'])

    def test_delay_moves_source_timestamp_one_bar_earlier(self):
        m=e.market_from_frames(fixture());kw=dict(start=str(m.dates[270].date()),end=str(m.dates[290].date()))
        a=e.simulate(m,params(),1.25,**kw);b=e.simulate(m,params(),1.25,delay=1,**kw)
        self.assertEqual(pd.Timestamp(a['signals'][0][1])-pd.Timestamp(b['signals'][0][1]),pd.Timedelta(days=1))

    def test_cash_days_retained_in_annualization(self):
        m=e.market_from_frames(fixture());run=e.simulate(m,params(),1.25,start=str(m.dates[0].date()),end=str(m.dates[240].date()))
        stats=e.summarize(run);self.assertEqual(stats['days'],241);self.assertEqual(stats['cagr'],0)

    def test_volatility_and_market_reduce_risk(self):
        m=e.market_from_frames(fixture());p=params();p['vol_target']=.6;j=280
        a,_=e.choose_target(m,p,j,-1)
        m.features['vol20'][j,a]=.6;m.features['vol60'][j,a]=.2
        self.assertLessEqual(e.choose_target(m,p,j,-1)[1],.5)
        m.features['close']=m.features['close'].copy()
        m.features['close'][j,m.assets.index('BTC')]=1
        self.assertLessEqual(e.choose_target(m,p,j,-1)[1],.5)

    def test_no_automatic_dip_averaging(self):
        m=e.market_from_frames(fixture());p=params('rotation')
        m.features['vol20'][:]=.5;m.features['vol60'][:]=.5
        m.prices[281:290,0,:]*=.99
        r=e.simulate(m,p,1.25,start=str(m.dates[280].date()),end=str(m.dates[291].date()),ledger=True)
        self.assertGreater(r['counters']['no_average_down'],0)

    def test_rotation_overrides_old_position_cooldown(self):
        m=e.market_from_frames(fixture());p=params('combo25')
        m.prices[285,0,:]=[50,52,45,51]
        m.features['mom21']=m.features['mom21'].copy()
        m.features['mom21'][284:,1]=1.0
        r=e.simulate(m,p,1.25,start=str(m.dates[280].date()),end=str(m.dates[290].date()),ledger=True)
        entries=[x for x in r['events'] if x[6]=='entry' and x[1]=='ETH']
        self.assertTrue(entries)
        self.assertLessEqual(pd.Timestamp(entries[0][0]),m.dates[286])

    def test_stop_reentry_requires_rebound_and_cooldown(self):
        m=e.market_from_frames(fixture());p=params('cat4')
        m.prices[285,0,:]=[50,52,45,51]
        m.features['rebound']=m.features['rebound'].copy()
        m.features['rebound'][283:291,0]=False
        r=e.simulate(m,p,1.25,start=str(m.dates[280].date()),end=str(m.dates[292].date()),ledger=True)
        forbidden=[x for x in r['events'] if x[6]=='entry' and x[1]=='BTC' and m.dates[285]<=pd.Timestamp(x[0])<=m.dates[291]]
        self.assertFalse(forbidden)

    def test_stitch_episode_ids_are_unique_across_folds(self):
        m=e.market_from_frames(fixture());p=params()
        a=e.simulate(m,p,1.25,start=str(m.dates[270].date()),end=str(m.dates[300].date()))
        b=e.simulate(m,p,1.25,start=str(m.dates[301].date()),end=str(m.dates[340].date()))
        joined=e.stitch([a,b]);stats=e.summarize(joined)
        self.assertLess(stats['trade_log_reconciliation_error'],1e-12)
        self.assertEqual(stats['closed_episodes'],e.summarize(a)['closed_episodes']+e.summarize(b)['closed_episodes'])


if __name__=='__main__':unittest.main(verbosity=2)
