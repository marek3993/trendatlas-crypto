import copy
import io
import math
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from research.phase2_v2.contract import load, validate, validate_folds, allowed
from research.phase2_v2.engine import curve_metrics, evaluate, suite, eligibility
from research.phase2_v2.inputs import guarded_rows
from research.phase2_v2.market import synthetic_market
from research.phase2_v2 import runtime, broker
from research.phase2_v2.dispatch_condition import executable

class V2RegressionTests(unittest.TestCase):
    def setUp(self):
        self.c=load(); self.m=synthetic_market();self.f=self.c['diagnostic_only_folds']

    def test_new_authorized_partition_and_seal(self):
        validate(self.c,activate=True)
        self.assertTrue(allowed('2025-12-31',self.c));self.assertTrue(allowed('2026-09-25',self.c))
        self.assertFalse(allowed('2026-09-26',self.c));self.assertFalse(allowed('2026-09-27',self.c))
        self.assertFalse(allowed('2027-01-01',self.c))
        with self.assertRaises(ValueError):validate_folds([['2026-09-25','2026-09-27']],self.c)

    def test_calendar_geometric_growth_not_short_fold_average(self):
        r=curve_metrics(['2020-01-01','2020-01-02'],[120.,100.])
        self.assertEqual(r['cagr'],0.)
        self.assertAlmostEqual(r['mdd'],1-100/120)
        # Large up/down short windows can have huge arithmetic CAGR but zero true CAGR.
        self.assertGreater(((1.2**(365.25)-1)+(1/1.2)**365.25-1)/2,1e20)

    def test_fold_boundary_keeps_same_book_and_whole_episode(self):
        split=evaluate(self.m,'BTC_BUY_HOLD',self.f)
        whole=evaluate(self.m,'BTC_BUY_HOLD',[[self.f[0][0],self.f[-1][1]]])
        self.assertEqual(split['equity'],[{**r,'fold':next(k for k,(a,b) in enumerate(self.f) if a<=r['date']<=b)} for r in whole['equity']])
        self.assertEqual(split['metrics']['cagr'],whole['metrics']['cagr'])
        self.assertEqual(len(split['episodes']),1);self.assertEqual(split['episodes'][0]['status'],'OPEN')
        self.assertIsNone(split['metrics']['no_top3_trades_cagr'])

    def test_gap_rejected_null_not_zero_and_attribution(self):
        with self.assertRaises(ValueError):validate_folds([['2020-01-01','2020-01-10'],['2020-01-12','2020-01-20']],self.c)
        r=suite(self.m,'CASH',self.f)
        self.assertIsNone(r['metrics']['asset_concentration']);self.assertFalse(eligibility(r['metrics'])[0])
        r=suite(self.m,'BTC_SMA200',self.f)
        self.assertAlmostEqual(sum(x['log_contribution'] for x in r['assets']),r['metrics']['log_growth'])
        self.assertAlmostEqual(sum(x['log_contribution'] for x in r['episodes']),r['metrics']['log_growth'])
        self.assertTrue(all('asset' in ep and 'id' in ep for ep in r['episodes']))

    def test_exact_delayed_entry_and_future_prefix_invariance(self):
        f=[['2020-01-01','2020-01-10']]
        r=evaluate(self.m,'BTC_BUY_HOLD',f,delay_entries=True)
        self.assertEqual(r['equity'][0]['equity'],100.)
        self.assertGreater(r['equity'][1]['gross_exposure'],0.)
        before=evaluate(self.m,'BTC_SMA200',f)
        self.m.close[self.m.dates>'2020-01-10']*=100
        self.assertEqual(before,evaluate(self.m,'BTC_SMA200',f))

    def test_checkpoint_resume_same_equity_and_episode_identity(self):
        a=evaluate(self.m,'BTC_BUY_HOLD',self.f[:2])
        b=evaluate(self.m,'BTC_BUY_HOLD',self.f[2:],initial_state=a['checkpoint'])
        whole=evaluate(self.m,'BTC_BUY_HOLD',self.f)
        self.assertAlmostEqual(b['equity'][-1]['equity'],whole['equity'][-1]['equity'])
        self.assertEqual(b['episodes'][0]['id'],whole['episodes'][0]['id'])

    def test_guard_does_not_parse_locked_columns(self):
        stream=io.BytesIO(b'date,open\n2026-09-25,100\n2026-09-26,FORBIDDEN_VALUE\n2026-09-27,FORBIDDEN_VALUE\n')
        rows=list(guarded_rows(stream,self.c))
        self.assertEqual(rows,[{'date':'2026-09-25','open':'100'}])
        self.assertEqual(stream.read(),b'FORBIDDEN_VALUE\n2026-09-27,FORBIDDEN_VALUE\n')
        bad=io.BytesIO(b'date,open\n1970-01-20,unknown\n1970-01-20,unknown\n2020-01-01,100\n')
        self.assertEqual(list(guarded_rows(bad,self.c)),[{'date':'2020-01-01','open':'100'}])

    def test_fee_parity_for_same_target_reference(self):
        targets={d.strftime('%Y-%m-%d'):('BTC',1.) for d in self.m.dates}
        a=suite(self.m,'BTC_BUY_HOLD',self.f)
        b=suite(self.m,'PRODUCTION',self.f,production_targets=targets)
        self.assertEqual(a['metrics'],b['metrics'])
        self.assertLess(a['stresses']['double_cost']['net_return'],a['metrics']['net_return'])

    def test_origin_training_never_contains_test_or_future(self):
        for k,(a,b) in enumerate(self.c['walk_forward']['validation_folds']):
            folds=runtime.training_folds(k)
            self.assertLess(folds[-1][1],a)
            validate_folds(folds,self.c)

    def test_dispatch_skips_empty_mailbox_and_completed_walk_forward(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'requests').mkdir();(root/'responses').mkdir()
            self.assertFalse(executable(mailbox=root))
            (root/'requests/one.json').write_text('{}');self.assertTrue(executable(mailbox=root))
            (root/'responses/one.json').write_text('{}');self.assertFalse(executable(mailbox=root))
            db=runtime.connect(root);db.execute("insert into test_books values(0,'{}','test')");db.commit();db.close()
            self.assertTrue(executable(root=root,fold_count=2));self.assertFalse(executable(root=root,fold_count=1))

    def test_missing_held_price_rejects_whole_trial_not_imputed_zero(self):
        f=[['2020-01-01','2020-01-10']]
        j=self.m.assets.index('BTCUSDT');i=self.m.dates.get_indexer(['2020-01-05'])[0]
        self.m.opening[i,j]=np.nan
        with self.assertRaisesRegex(ValueError,'missing_held_asset_price:2020-01-05:BTCUSDT'):
            evaluate(self.m,'BTC_BUY_HOLD',f)

    def test_atr_stop_checkpoint_is_native_json_and_roundtrips(self):
        genes={'family':'N','breakout_days':30,'atr_days':14,'initial_stop_atr':1.5,'trailing_stop_atr':3.0,'risk_per_entry':.005}
        # Force a causal breakout and an intraday stop to exercise cooldown keys.
        i=self.m.dates.get_indexer(['2020-01-01'])[0]
        self.m.features['breakout30']=self.m.features['breakout30'].copy()
        self.m.features['breakout30'][i-1:i+20]=0.
        self.m.low[i:i+20]=.01
        r=evaluate(self.m,genes,[['2020-01-01','2020-01-10']])
        self.assertTrue(r['checkpoint']['strategy_state']['cooldown'])
        body=json.loads(json.dumps(r,allow_nan=False))
        resumed=evaluate(self.m,genes,[['2020-01-11','2020-01-20']],initial_state=body['checkpoint'])
        self.assertTrue(resumed['audit']['pnl_reconciled'])

    def test_remove_top3_whole_closed_episodes_across_fold_boundaries(self):
        targets={d.strftime('%Y-%m-%d'):('BTC',float((k//30)%2==0)) for k,d in enumerate(self.m.dates)}
        r=evaluate(self.m,'PRODUCTION',self.f,production_targets=targets)
        closed=sorted([ep for ep in r['episodes'] if ep['status']=='CLOSED' and ep['log_contribution']>0],
            key=lambda ep:ep['log_contribution'],reverse=True)
        self.assertGreaterEqual(len(closed),3)
        years=r['metrics']['elapsed_calendar_days']/365.25
        expected=math.expm1((r['metrics']['log_growth']-sum(ep['log_contribution'] for ep in closed[:3]))/years)
        self.assertAlmostEqual(r['metrics']['no_top3_trades_cagr'],expected)
        self.assertEqual(r['metrics']['top3_removed'],[ep['id'] for ep in closed[:3]])

    def test_nested_checkpoint_freeze_survivor_inheritance_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=runtime.connect(root)
            runtime.initialize(db,{'engine':'test','inputs':'test','contract':'test'})
            runtime.seed(db,0);runtime.seed(db,0)
            self.assertEqual(db.execute('select count(*) from candidates').fetchone()[0],6)
            runtime.init_worker(self.m)
            bound={'engine':'test'}
            tasks=runtime.pending(db,0,0,bound)
            for task in tasks:runtime.store_job(db,bound,runtime.job(task))
            self.assertEqual(runtime.pending(db,0,0,bound),[])
            state=runtime.advance(db,root,0,0)
            self.assertEqual(state,'WAITING')
            request=next((root/'mailbox/requests').glob('*.json'))
            payload=json.loads(request.read_text())['payload']
            self.assertEqual(payload['aggregate']['training_cutoff'],'2019-12-31')
            self.assertNotIn('ledger',payload);self.assertNotIn('seen_hashes',payload)
            def transport(p,key):
                candidates=[{**o,'hypothesis':'test mutation'} for o in p['unseen_options'][:4]]
                return json.dumps({'candidates':candidates}),{'total_tokens':100,'billing_known':True,'usd_upper_estimate':.0001},'test'
            with patch.object(broker,'api_key',return_value='TEST_NON_SECRET'):
                broker.broker_once(root/'mailbox',transport)
            self.assertEqual(runtime.advance(db,root,0,0),'ADVANCED')
            self.assertEqual(runtime.advance(db,root,0,0),'ADVANCED')
            old_ids={r[0] for r in db.execute('select id from members where origin=0 and generation=0')}
            inherited={r[0] for r in db.execute("select id from members where origin=0 and generation=1 and role='survivor'")}
            self.assertEqual(len(inherited),2);self.assertTrue(inherited<=old_ids)
            self.assertEqual(db.execute('select count(*) from evaluations').fetchone()[0],18)
            db.close();db=runtime.connect(root);runtime.initialize(db,{'engine':'test','inputs':'test','contract':'test'})
            with self.assertRaises(RuntimeError):runtime.initialize(db,{'engine':'changed','inputs':'test','contract':'test'})
            with self.assertRaises(Exception):db.execute("update evaluations set result='{}'")
            db.close()

    def broker_payload(self,cycle):
        genes={'family':'J','trend_days':120,'vol_days':20,'vol_target':.10,'exit_confirm_days':1}
        return {'cycle_id':cycle,'generation':1,'family':'J','parents':[{'id':'parent','genes':genes,'weak_folds':[],
            'eligible':False,'metrics':{},'reasons':[]}],'schema':runtime.SPACE['J'],
            'unseen_options':[],'scope':'development_inner_validation_only','aggregate':{'training_cutoff':'2019-12-31'}}

    def test_content_cache_cross_cycle_has_no_second_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);calls=[]
            def transport(p,key):calls.append(p);return '{"candidates":[]}',{'total_tokens':10,'billing_known':True,'usd_upper_estimate':.00001},'test'
            with patch.object(broker,'api_key',return_value='TEST_NON_SECRET'):
                for cycle in ('a','b'):
                    payload=self.broker_payload(cycle);h=runtime.digest(payload)
                    runtime.atomic(root/'requests'/(h+'.json'),{'hash':h,'payload':payload})
                    self.assertTrue(broker.broker_once(root,transport))
            self.assertEqual(len(calls),1)
            responses=[json.loads(p.read_text()) for p in (root/'responses').glob('*.json')]
            self.assertEqual(sum(p['usage']['api_call'] for p in responses),1)
            self.assertTrue(any(p.get('cache_source') for p in responses))

    def test_ambiguous_billed_transport_is_not_retried_or_reported_free(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);calls=[]
            def transport(p,key):calls.append(p);raise TimeoutError('ambiguous')
            payload=self.broker_payload('a');h=runtime.digest(payload)
            runtime.atomic(root/'requests'/(h+'.json'),{'hash':h,'payload':payload})
            with patch.object(broker,'api_key',return_value='TEST_NON_SECRET'):
                self.assertTrue(broker.broker_once(root,transport));self.assertFalse(broker.broker_once(root,transport))
            response=json.loads((root/'responses'/(h+'.json')).read_text())
            self.assertEqual(len(calls),1);self.assertIsNone(response['usage']['total_tokens'])
            self.assertFalse(response['usage']['billing_known']);self.assertTrue(response['usage']['uncertain'])

if __name__=='__main__':unittest.main()
