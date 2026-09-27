import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from .protocol import CONTRACT, periods, initial, plateau_neighbors, successor_allowed, four_mutations
from .vendor.common import config,cid
from .vendor.test_research import fixture
from .vendor.ledger import replay
from .statistics import dsr,holm,paired_bootstrap,cscv,survivors
from .store import Store
from .proposal_schema import make_payload
from .designer import strict_json,validate_payload,validate_response
from .evaluator import prefix_audit,synthetic_market,Evaluator
from .gate import allowed,dispatch_allowed,parse_jobs

class Causality(unittest.TestCase):
    def test_missing_bar_delay_counts_executable_bars(self):
        m,w,e=fixture();w[:,0]=1;m['prices'][7:9,0]=np.nan;m['mark'][7:9,0]=np.nan
        normal=replay(m,(w,e),'2020-01-01','2020-01-12',details=True)
        late=replay(m,(w,e),'2020-01-01','2020-01-12',details=True,delay=1)
        self.assertEqual(normal['fills'][0]['date'],'2020-01-02 12:00:00')
        self.assertEqual(late['fills'][0]['date'],'2020-01-02 16:00:00')

    def test_holding_exit_latency_and_no_fake_flat(self):
        m,w,e=fixture(days=110);w[:,0]=1;e[:]=False;e[0]=True
        r=replay(m,(w,e),'2020-01-01','2020-04-19',details=True,max_holding_days=90)
        self.assertEqual(r['metrics']['trades'],1)
        closed=[ep for ep in r['episodes'] if ep['closed']][0]
        self.assertGreaterEqual(closed['holding_days'],90)
        self.assertLess(closed['holding_days'],91)
        self.assertTrue(all(pd.Timestamp(f['date'])>pd.Timestamp(f['available_at']) for f in r['fills']))
        m['prices'][540:,0,:]=np.nan;m['mark'][540:,0,:]=np.nan
        broken=replay(m,(w,e),'2020-01-01','2020-04-19',details=True,max_holding_days=90)
        self.assertEqual(broken['metrics']['trades'],0);self.assertFalse(broken['metrics']['reliable'])

    def test_funding_credit_not_doubled(self):
        m,w,e=fixture(True);w[:,0]=-.5;e[1:]=False
        m['funding']=[(t,0,.0001) for t in m['dates'][::2]]
        a=replay(m,(w,e),'2020-01-01','2020-01-12');b=replay(m,(w,e),'2020-01-01','2020-01-12',cost_mult=2)
        self.assertAlmostEqual(a['metrics']['funding_credit_usd'],b['metrics']['funding_credit_usd'],places=7)

    def test_all_families_future_mutation(self):
        for track,families in [('spot','FGH'),('perp','D')]:
            m=synthetic_market(track,'2021-12-31')
            for family in families:
                for genes in initial(family,1701)[:3]:
                    self.assertTrue(prefix_audit(genes,track,m,'2021-07-01')['pass_audit'])

    def test_asset_identity_split_never_splices_returns(self):
        from .vendor.data import split
        from unittest.mock import patch
        from .vendor import data
        dates=pd.date_range('2020-01-01',periods=4,freq='D')
        source={'ABCUSDT':pd.DataFrame({'close':[10,11,900,901]},index=dates)}
        event=[dict(symbol='ABCUSDT',effective_utc='2020-01-03',new_start='2020-01-03')]
        with patch.object(data.json,'loads',return_value=event):out=split(source,24)
        self.assertEqual(list(out['ABCUSDT@original'].close),[10,11]);self.assertEqual(list(out['ABCUSDT@20200103'].close),[900,901])

    def test_continuous_annual_schedule_does_not_reset_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(tmp);s.set('outer_opened',True);s.set('fingerprint','synthetic')
            e=Evaluator(s,True);c=config(signal='mom90',cadence='monthly')
            p=dict(scope='outer',fold='continuous_test',start='2023-01-01',end='2024-12-31')
            single=e.evaluate(c,p,'spot');scheduled=e.evaluate(c,p,'spot',schedule=[dict(year=2023,genes=c),dict(year=2024,genes=c)])
            np.testing.assert_allclose([d['nav'] for d in single['daily']],[d['nav'] for d in scheduled['daily']],rtol=0,atol=0)
            self.assertEqual(single['episodes'],scheduled['episodes']);self.assertEqual(single['metrics']['fee_usd'],scheduled['metrics']['fee_usd'])
            changed=e.evaluate(c,p,'spot',schedule=[dict(year=2023,genes=c),dict(year=2024,genes=config(signal='sma50'))])
            before=[d['nav'] for d in single['daily'] if d['date']<'2024-01-01']
            after=[d['nav'] for d in changed['daily'] if d['date']<'2024-01-01']
            np.testing.assert_allclose(before,after,rtol=0,atol=0);s.close()

    def test_future_gross_policy_does_not_change_prefix(self):
        m,w,e=fixture(True);w[:,0]=-.8;e[1:]=False
        a=replay(m,(w,e),'2020-01-01','2020-01-12',gross_schedule=np.ones(len(w)))
        cap=np.ones(len(w));cap[-1]=1.25
        b=replay(m,(w,e),'2020-01-01','2020-01-12',gross_schedule=cap)
        np.testing.assert_allclose(a['daily'].nav,b['daily'].nav,rtol=0,atol=0)

class Separation(unittest.TestCase):
    def test_purge_and_global_outer_barrier_dates(self):
        for origin in (2024,2025):
            ps=periods(origin);outer=[p for p in ps if p['scope']=='outer'][0]
            for k in (0,1):
                train,val=[p for p in ps if p['fold']==k]
                self.assertEqual((dt.date.fromisoformat(val['start'])-dt.date.fromisoformat(train['end'])).days,460)
                self.assertLess(val['end'],'2024-01-01')
            self.assertEqual((dt.date.fromisoformat(outer['start'])-dt.date.fromisoformat(ps[3]['end'])).days,460)

    def payload(self):
        rows=[]
        for c in initial('F',1701)[:6]:
            rows.append(dict(id=cid(c),genes=c,folds=[dict(p,metrics=dict(cagr=.1,mdd=.2)) for p in periods(2024) if p['scope']!='outer']))
        return make_payload('2024:F_spot:1701:deepseek',1,rows,{r['id'] for r in rows})

    def test_no_outer_label_or_fake_development_dates(self):
        p=self.payload();validate_payload(p)
        p['parents'][0]['folds'][0]['scope']='outer'
        with self.assertRaises(ValueError):validate_payload(p)
        p=self.payload();p['parents'][0]['folds'][0]['end']='2025-01-01'
        with self.assertRaises(ValueError):validate_payload(p)

    def test_schema_duplicate_nonfinite_code_and_island(self):
        for x in ('{"candidates":[],"candidates":[]}','{"candidates":NaN}','{"code":"print(1)"}'):
            with self.assertRaises(ValueError):strict_json(x)
        p=self.payload();mut=four_mutations([r['genes'] for r in p['parents']],55,set(p['seen']))
        good,bad=validate_response(json.dumps(dict(candidates=mut)),p);self.assertEqual(len(good),4);self.assertFalse(bad)
        mut[0]['genes']['fee_bps']=0
        good,bad=validate_response(json.dumps(dict(candidates=mut)),p);self.assertEqual(len(good),3);self.assertTrue(bad)

    def test_new_hash_not_enough_and_refit_quarantine(self):
        prev=dict(status='SEALED',closed_through='2025-12-31',fingerprint='a',experiment_id='a',next_refit='2027-01-01')
        inc=dict(closed_through='2026-09-26',fingerprint='b',experiment_id='b',parent_fingerprint='a',coverage_complete=True)
        self.assertFalse(successor_allowed(prev,inc,dt.date(2026,9,27))[0])
        inc['closed_through']='2026-12-31';self.assertTrue(successor_allowed(prev,inc,dt.date(2027,1,1))[0])
        inc['experiment_id']='a';self.assertFalse(successor_allowed(prev,inc,dt.date(2027,1,1))[0])

    def test_sqlite_resume_outer_is_irreversible(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(tmp);s.set('outer_opened',True);s.close();s=Store(tmp)
            with self.assertRaises(RuntimeError):s.add_trial('x','x',1,config())
            with self.assertRaises(RuntimeError):s.reserve('x','inner_train')
            s.close()

    def test_outer_evaluator_refuses_before_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(tmp);e=Evaluator(s,True)
            with self.assertRaises(RuntimeError):e.evaluate(config(),periods(2024)[-1],'spot')
            s.close()

    def test_crash_reservation_does_not_vanish(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(tmp);s.reserve('unfinished','inner_train');s.close();s=Store(tmp)
            self.assertEqual(s.counts()['attempts'],1);self.assertEqual(s.counts()['evaluations'],0);s.close()

    def test_islands_10_6_4_and_independent_seeds(self):
        for f in 'FGHD':
            p=initial(f,1701);self.assertEqual(len(p),10)
            self.assertNotEqual(p,initial(f,2903));self.assertTrue(all(x['family']==f for x in p))
            mut=four_mutations(p[:6],555,{cid(c) for c in p});self.assertEqual(len(mut),4)
            self.assertTrue(all(x['genes']['family']==f for x in mut))
            self.assertTrue(all(len(plateau_neighbors(x))==2 for x in p))

class Statistics(unittest.TestCase):
    def test_more_trials_deflates_sharpe(self):
        x=np.random.default_rng(11).normal(.002,.02,800)
        self.assertGreater(dsr(x,2,[1,2,3])['probability'],dsr(x,1000,[1,2,3])['probability'])

    def test_insufficient_power_is_not_pass(self):
        r=paired_bootstrap(np.ones(100)*.001,np.zeros(100),1,replicates=20)
        self.assertEqual(r['status'],'INCONCLUSIVE')
        self.assertEqual(cscv(np.ones((500,10)))['status'],'INCONCLUSIVE')

    def test_holm_monotone_and_familywise(self):
        adjusted=holm([.01,.04,.03]);np.testing.assert_allclose(adjusted,[.03,.06,.06])

    def test_pareto_tradeoff_kept_without_weighted_sum(self):
        rows=[dict(id='a',vector=[2,-.4],complexity=1),dict(id='b',vector=[1,-.1],complexity=1),dict(id='c',vector=[0,-.5],complexity=1)]
        self.assertEqual({r['id'] for r in survivors(rows,2)},{'a','b'})

    def test_cscv_bounded_reproducible(self):
        x=np.random.default_rng(123).normal(0,.01,(480,12));a=cscv(x);b=cscv(x)
        self.assertEqual(a,b);self.assertEqual(a['splits'],70);self.assertTrue(0<=a['pbo']<=1)

class ProductionPriority(unittest.TestCase):
    def test_gate_never_starts_over_production(self):
        p=dict(LoadState='loaded',ActiveState='inactive',SubState='dead',Result='success',ExecMainExitTimestampMonotonic='100')
        t=dict(UnitFileState='enabled',ActiveState='active');self.assertTrue(allowed(p,t,[]))
        for phase in ('active','activating','deactivating','failed'):
            self.assertFalse(allowed(dict(p,ActiveState=phase),t,[]))
        self.assertFalse(allowed(p,t,[dict(unit='mrv1-production.service')]))
        self.assertFalse(dispatch_allowed(dict(LoadState='loaded',ActiveState='active'),[]))
        self.assertFalse(dispatch_allowed(dict(LoadState='loaded',ActiveState='inactive'),[dict(unit='trendatlas-evolution-worker.service')]))

    def test_unrecognized_job_listing_fails_closed(self):
        with self.assertRaises(ValueError):parse_jobs('unexpected fields')

    def test_rendered_units_preserve_production_and_isolate_mailbox(self):
        from .deployment import units
        files=units('/opt/trendatlas-research/releases/'+'a'*40)
        self.assertFalse(any(k.startswith('mrv1-') for k in files))
        worker=files['trendatlas-evolution-worker.service'];broker=files['trendatlas-causal-broker.service']
        self.assertIn('PrivateNetwork=yes',worker);self.assertIn('RefuseManualStart=yes',worker)
        self.assertIn('OnSuccessJobMode=ignore-requirements',files['trendatlas-evolution-dispatch.service'])
        self.assertIn('InaccessiblePaths=/var/lib/trendatlas-research',broker)
        self.assertIn('/current/mailbox:/var/lib/trendatlas-causal-broker/mailbox',broker)
        self.assertIn('CPUQuota=20%',files['trendatlas-causal-research.slice'])

    def test_broker_database_contains_no_market_or_outer_tables(self):
        from .mailbox import Mailbox
        with tempfile.TemporaryDirectory() as tmp:
            m=Mailbox(tmp)
            self.assertEqual([r[0] for r in m.db.execute("SELECT name FROM sqlite_master WHERE type='table'")],['proposals'])
            m.close()

    def test_sealed_mailbox_cannot_call_api(self):
        from .mailbox import Mailbox
        from .designer import broker_once
        with tempfile.TemporaryDirectory() as tmp:
            m=Mailbox(tmp);(Path(tmp)/'SEALED.json').write_text('{}')
            self.assertFalse(broker_once(m));m.close()

class CollectorTests(unittest.TestCase):
    def test_public_archive_url_boundary(self):
        from .acquisition import Collector
        with tempfile.TemporaryDirectory() as tmp:
            c=Collector(tmp)
            for url in ('https://api.hyperliquid.xyz/exchange','http://data.binance.vision/x','https://s3-ap-northeast-1.amazonaws.com/other-bucket'):
                with self.assertRaises(ValueError):c.fetch(url)
            c.db.close()

    def test_raw_microsecond_timestamp_and_ohlc_validation(self):
        from .acquisition import raw_frame
        import io,zipfile
        def zipped(price):
            b=io.BytesIO()
            with zipfile.ZipFile(b,'w') as z:z.writestr('data.csv',f'1735689600000000,100,{price},99,101,10,1735775999999999,1000,5,2,200,0\n')
            return b.getvalue()
        f=raw_frame(zipped(102));self.assertEqual(f.index[0],pd.Timestamp('2025-01-01'))
        with self.assertRaises(ValueError):raw_frame(zipped(100))

if __name__=='__main__':unittest.main()
