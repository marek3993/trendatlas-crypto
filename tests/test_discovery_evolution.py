import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from research.phase2_v2.market import synthetic_market, digest, validate_genes, SPACE
from research.anomaly_lab.rules import catalogue, prepare
from research.discovery_evolution.contract import load, validate
from research.discovery_evolution.pool import build_pool, novel_k
from research.discovery_evolution.statistics import design, infer, tail
from research.discovery_evolution.discovery import episodes
from research.discovery_evolution import runtime
from research.discovery_evolution.deploy import units


def boot_fixture(count=4):
    receipts=[]
    for i,r in enumerate(catalogue()[:count]):
        receipts.append({'receipt_id':str(i),'hypothesis_id':digest(r),'rule':r,
                         'genes':{'family':'M','slow_days':120,'breakout_days':40,'momentum_days':30,'vol_target':.1},'training_cutoff':'2021-12-17'})
    c=load(); pool=build_pool(receipts,set())
    return {'contract':digest(c),'pool':pool,'pool_digest':digest(pool),'seen_gene_ids':[], 'legacy_receipts':receipts,
            'inherited':{'api_calls':14,'api_tokens':42953,'backtest_trials':1428},'histories':[]}


def fake_evaluator(m,f,genes,interval,stress):
    lo,hi=m.dates.get_indexer(interval); log=.0001 if isinstance(genes,dict) else 0.
    rows=[{'date':d.strftime('%Y-%m-%d'),'log_return':log,'equity':100*math.exp(log*(i+1))} for i,d in enumerate(m.dates[lo:hi+1])]
    return {'metrics':{'cagr':.02,'mdd':.4,'log_growth':log*len(rows)},'equity':rows,'audit':{'pnl_reconciled':True}}


class SuccessorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m=synthetic_market(); cls.f=prepare(cls.m)

    def test_actual_old_calendar_alignment_and_new_design_power_disclosed(self):
        from datetime import date
        base=date(2018,5,5)
        ordinary=(date(2023,12,31)-base).days//30-(date(2023,7,1)-base).days//30+1
        boundary=(date(2024,12,31)-base).days//30-(date(2024,7,1)-base).days//30+1
        self.assertEqual(ordinary,7);self.assertEqual(boundary,8)
        # Two partial boundary cells can produce eight labels in this one window.
        # Even then the exact sign floor overwhelms the lifetime alpha allowance.
        self.assertGreater(2.**(-boundary),.05/(67*68))
        d=design(); self.assertEqual(d['available_full_blocks'],39); self.assertEqual(d['critical_positive_blocks_at_full_coverage'],36)
        self.assertLess(d['minimum_p_at_required_blocks'],d['worst_planned_alpha'])
        self.assertLess(d['power_at_block_positive_probability']['0.8'],.04)
        self.assertGreater(d['power_at_block_positive_probability']['0.95'],.85)

    def test_contract_rejects_resets_seal_and_weakened_windows(self):
        for key,value in [('new_api_calls_allowed',1),('legacy_alpha_debt',0),('test',['2026-01-01','2026-09-25']),('test',['2026-09-27','2027-09-26'])]:
            c=copy.deepcopy(load()); c[key]=value
            with self.assertRaises(ValueError):validate(c)

    def test_exact_sign_resolution_lifetime_debt_no_candidate_claim(self):
        c=load(); start,end=self.m.dates.get_indexer(c['test']); dates=self.m.dates[start:end+1]
        base=[{'date':str(d),'log_return':0.} for d in dates]; positive=[{**r,'log_return':.01} for r in base]
        out=infer(positive,base,1444); self.assertEqual(out['nonzero_blocks'],39); self.assertLess(out['p'],out['alpha'])
        self.assertFalse(out['confirmed_trading_candidate']); self.assertIsNone(infer(base,base,1444)['p'])
        self.assertLessEqual(tail(36,39),out['alpha']); self.assertGreater(tail(35,39),out['alpha'])

    def test_no_edge_common_block_signs_and_dependence(self):
        # Shared block signs across assets; arbitrary serial repeats within blocks.
        rng=np.random.default_rng(42); rejected=0
        for run in range(256):
            signs=rng.choice([-1.,1.],39); blocks=np.repeat(signs,44)[:1729]
            blocks=np.pad(blocks,(0,1729-len(blocks)),constant_values=0)
            a=[{'date':str(i),'log_return':float(v*.001)} for i,v in enumerate(blocks)]
            b=[{'date':str(i),'log_return':0.} for i in range(1729)]
            rejected+=infer(a,b,1429+run%16)['rejected_under_declared_null']
        self.assertEqual(rejected,0)
        self.assertLess(sum(.05/(t*(t+1)) for t in range(1429,1445)),.05/1429)

    def test_bounded_episodes_prevent_transitive_coin_bridge(self):
        mask=np.zeros((120,20),bool); eligible=np.ones_like(mask); ranks=np.tile(np.arange(20),(120,1))
        for i in range(1,100,3): mask[i,i%20]=True
        result,n=episodes(mask,eligible,ranks,list(map(str,range(20))),7,1,119)
        self.assertGreater(len(result),8); self.assertTrue(all(r['duration_days']<=7 for r in result)); self.assertGreater(n,len(result))
        mask[:]=True; mask[0]=False
        self.assertEqual(len(episodes(mask,eligible,ranks,list(map(str,range(20))),7,1,119)[0]),1)

    def test_prior_only_pool_gene_dedup_and_new_behavior_identity(self):
        b=boot_fixture(); self.assertEqual(len(b['pool']),4)
        self.assertTrue(all(p['hypothesis_id']!=p['root_hypothesis'] for p in b['pool']))
        seen={b['pool'][0]['gene_id']}; p=build_pool(b['legacy_receipts'],seen)
        self.assertNotIn(next(iter(seen)),{e['gene_id'] for e in p})
        late=copy.deepcopy(b['legacy_receipts']);
        for r in late:r['training_cutoff']='2023-01-01'
        self.assertEqual(build_pool(late,set()),[])
        root=b['legacy_receipts'][0]
        with patch('research.discovery_evolution.pool.SPACE',{'K':{k:[v[0]] for k,v in SPACE['K'].items()}}):
            g=novel_k(root['genes'],root['rule'],set()); self.assertIsNone(novel_k(root['genes'],root['rule'],{digest(g)}))

    def test_real_unmodified_engine_backtests_valid_K_candidate(self):
        b=boot_fixture(1); genes=b['pool'][0]['genes']; validate_genes(genes)
        value=runtime.checked_evaluate(self.m,self.f,genes,['2020-01-01','2020-06-30'],'nominal')
        self.assertTrue(value['audit']['pnl_reconciled']); self.assertEqual(value['metrics']['elapsed_calendar_days'],182)

    def test_crash_recovery_reuses_reservations_no_duplicate_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            b=boot_fixture(); db=runtime.connect(directory);runtime.initialize(db,b,{'test':1})
            def interrupted(*args): raise KeyboardInterrupt('simulated process death')
            with self.assertRaises(KeyboardInterrupt): runtime.work(db,directory,self.m,self.f,b,interrupted)
            reserved=db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]; self.assertEqual(reserved,1)
            db.close(); db=runtime.connect(directory);runtime.initialize(db,b,{'test':1})
            a=runtime.work(db,directory,self.m,self.f,b,fake_evaluator)
            self.assertEqual(a['statistical_attempts_reserved'],1); self.assertEqual(a['backtest_attempts_reserved'],5)
            self.assertEqual(a['backtest_calculations_completed'],5)
            db.close(); self.assertEqual(runtime.audit(directory)['hash_chain'],'PASS')

    def test_complete_real_flow_feedback_successor_and_truthful_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            b=boot_fixture();db=runtime.connect(directory);runtime.initialize(db,b,{'test':1})
            for _ in range(4): state=runtime.work(db,directory,self.m,self.f,b,fake_evaluator)
            self.assertEqual(state['state'],'IDLE_NO_NEW_WORK'); self.assertEqual(state['candidates_actually_evaluated'],4)
            self.assertEqual(state['unique_new_hypotheses'],4); self.assertEqual(state['backtest_calculations_completed'],17)
            self.assertEqual(state['statistical_attempts_reserved'],4); self.assertEqual(state['conservative_lifetime_alpha_index'],1432)
            cycle=json.loads(db.execute('SELECT body FROM cycles WHERE id=2').fetchone()[0]);self.assertEqual(len(cycle['prior_feedback_hashes']),2)
            before=state['counts']; after=runtime.work(db,directory,self.m,self.f,b,fake_evaluator);self.assertEqual(before,after['counts'])
            with self.assertRaises(Exception): db.execute('DELETE FROM feedback')
            self.assertEqual(len(list((Path(directory)/'inbox').glob('*.json'))),4)
            self.assertEqual(len(list((Path(directory)/'feedback').glob('*.json'))),4)
            db.close()

    def test_one_candidate_failure_does_not_stop_others(self):
        with tempfile.TemporaryDirectory() as directory:
            b=boot_fixture(2);db=runtime.connect(directory);runtime.initialize(db,b,{'test':1})
            bad=b['pool'][0]['genes']
            def evaluator(m,f,g,interval,stress):
                if g==bad: raise ValueError('missing_held_asset_price:LUNAUSDT@original')
                return fake_evaluator(m,f,g,interval,stress)
            runtime.work(db,directory,self.m,self.f,b,evaluator);state=runtime.work(db,directory,self.m,self.f,b,evaluator)
            self.assertEqual(state['failed_candidates'],1); self.assertEqual(state['candidates_actually_evaluated'],2)
            self.assertEqual(state['closed_cycles'],1);db.close()

    def test_code_or_bootstrap_changes_reject_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            db=runtime.connect(directory);runtime.initialize(db,boot_fixture(),{'test':1})
            with self.assertRaises(ValueError):runtime.initialize(db,boot_fixture(),{'test':2})
            db.close()

    def test_systemd_has_no_network_credential_or_predecessor_write_authority(self):
        unit=units(Path('/opt/research-test'))['trendatlas-discovery-evolution.service']
        self.assertIn('PrivateNetwork=true',unit);self.assertNotIn('LoadCredential=',unit)
        self.assertIn('-/var/lib/trendatlas-anomaly-lab',unit);self.assertIn('-/var/lib/trendatlas-phase2',unit)
        self.assertIn('Restart=on-failure',unit);self.assertIn('ReadWritePaths=/var/lib/trendatlas-discovery-evolution',unit)

    def test_native_readonly_market_restriction_keeps_original_arrays(self):
        from dataclasses import replace
        original=self.m.eligible.copy();original.setflags(write=False)
        m=replace(self.m,eligible=original);f={**self.f,'eligible':self.f['eligible'].copy()};f['eligible'][100,0]=False
        child=runtime.restricted_market(m,f)
        self.assertIs(m.eligible,original);self.assertFalse(child.eligible[100,0])
        self.assertFalse(np.shares_memory(m.eligible,child.eligible))

    def test_pre_result_repair_retains_binding_and_rejects_changes_after_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            db=runtime.connect(directory);b=boot_fixture()
            before={'code':{'runtime.py':'old','statistics.py':'same'},'contract':'same'}
            after={'code':{'runtime.py':'fixed','statistics.py':'same'},'contract':'same'}
            runtime.initialize(db,b,before);runtime.initialize(db,b,after);runtime.initialize(db,b,after)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'binding%'").fetchone()[0],2)
            runtime.freeze_next(db,b)
            with self.assertRaises(ValueError):runtime.initialize(db,b,before)
            db.close();self.assertEqual(runtime.audit(directory)['hash_chain'],'PASS')


if __name__=='__main__':unittest.main()
