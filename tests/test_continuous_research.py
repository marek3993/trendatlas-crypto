import copy
import itertools
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from research.continuous_research.common import canonical,digest,atomic,period
from research.continuous_research.contract import load,validate
from research.continuous_research import ledger,planner,runtime,broker,schema

TARIFF={'rates_nano_per_token':{'hit':6,'input':300,'output':1200},'source':'synthetic_test_fixture','html_sha256':'fixture'}


def gene(offset=0):
    space=schema.spaces()[0];keys=list(space)
    vals=list(itertools.islice(itertools.product(*(space[k] for k in keys)),offset,offset+1))[0]
    return {'family':'K',**dict(zip(keys,vals))}


def proposal(offset=1):
    return {'parent':digest(gene()),'genes':gene(offset),'rule':{'family':'momentum','threshold':.05,'horizon':7,'action':'long'},
            'mechanism':'Test a new correlation-aware K allocation configuration.','falsification':'Negative validation growth or excessive drawdown refutes this configuration.'}


def boot():
    c=load();p=proposal(0);parent={'id':digest(gene()),'genes':gene(),'rule':p['rule'],'cutoff':c['feedback_cutoff'],
        'training':{'valid':True,'metrics':{'log_growth':.1,'cagr':.1,'mdd':.2},'interval':[c['training'][0],c['feedback_cutoff']]},
        'validation':None,'frequency_episodes':30,'source':'fixture'}
    return {'contract':digest(c),'seen_genes':[digest(gene())],'configuration_hypotheses':[p],
        'known_rules':[p['rule']],'prior_training':[parent],'cached_discoveries':[],
        'K_cardinality':54880,'historical_K_count':1,'inherited':{'alpha_index':1444,'historical_gene_count':1}}


def evaluator(m,f,g,interval,stress):
    from datetime import date,timedelta
    lo,hi=map(date.fromisoformat,interval);n=(hi-lo).days+1;v=.0001 if isinstance(g,dict) else 0.
    rows=[{'date':(lo+timedelta(days=i)).isoformat(),'log_return':v,'equity':100.} for i in range(n)]
    return {'metrics':{'log_growth':v*n,'cagr':.03,'mdd':.2},'equity':rows,'audit':{'pnl_reconciled':True}}


def discovery(*args):return {'valid':True,'bounded_episodes':31,'eligible_calendar_days':717,'raw_asset_day_triggers':80}


def setup(root):
    db=ledger.connect(root);planner.initialize(db,boot(),{'fixture':'stable'})
    mailbox=Path(root)/'mailbox';mailbox.mkdir();atomic(mailbox/'status.json',{'state':'WAIT_DAILY_API_BUDGET'})
    return db,mailbox


def reply(offset=1):
    return {'id':'provider-real-format-fixture','model':'deepseek-flash','usage':{'prompt_tokens':1000,'completion_tokens':500},
        'choices':[{'finish_reason':'stop','message':{'content':canonical({'evaluation':'Training evidence motivates this prospective configuration test.','proposals':[proposal(offset)]})}}]}


class ContinuousResearchRegressionTests(unittest.TestCase):
    def test_contract_does_not_truncate_scheduler_or_reset_scientific_debt(self):
        for mutate in (lambda c:c['scheduler'].update(lifetime_batch_limit=8),lambda c:c['api'].update(attempts_per_day=25),
                       lambda c:c.update(legacy_alpha_index=0),lambda c:c.update(diagnostic=['2026-09-27','2027-09-26'])):
            c=copy.deepcopy(load());mutate(c)
            with self.assertRaises(ValueError):validate(c)

    def test_compact_feedback_excludes_diagnostic_canary_and_bounds_input(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);rid,_=planner.ensure_request(db,mail);p=json.loads(db.execute('SELECT body FROM requests').fetchone()[0])['payload']
            p['parents'][0]['diagnostic_only']={'winner':'SECRET_TEST_CANARY'}
            p['parents'][0]['training']['metrics']['future_test']='SECRET_TEST_CANARY'
            body=schema.wire_body(p);self.assertNotIn('SECRET_TEST_CANARY',canonical(body));self.assertLessEqual(len(canonical(body).encode())+256,6500)
            p['parents'][0]['training']['interval'][1]='2024-01-01'
            with self.assertRaises(ValueError):schema.wire_body(p)
            db.close()

    def test_global_gene_and_wording_independent_hypothesis_dedup(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);p=proposal();a=planner.register(db,p,'AI_AUTHORED','r',0)
            rewritten={**p,'mechanism':'Different prose does not make a new market hypothesis.'}
            self.assertEqual(schema.identity(p),schema.identity(rewritten))
            self.assertIsNone(planner.register(db,rewritten,'AI_AUTHORED','r2',0))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0],1)
            self.assertEqual(planner.register(db,p,'AI_AUTHORED','r',0),a)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM proposal_receipts').fetchone()[0],2);db.close()

    def test_shared_parallel_attempt_cap_reserves_before_every_transport(self):
        with tempfile.TemporaryDirectory() as root:
            db=broker.connect(root);db.close()
            def attempt(i):
                db=sqlite3.connect(Path(root)/'api.sqlite',timeout=30)
                try:return broker.reserve(db,str(i),0,TARIFF,5000,'2026-10-09T12:00:00+00:00')
                finally:db.close()
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(40)))
            self.assertEqual(sum(x[0] is not None for x in results),24)
            db=broker.connect(root);b=broker.budget(db,'2026-10-09T12:00:00+00:00')
            self.assertEqual(b['attempts_remaining_today'],0);self.assertAlmostEqual(b['reserved_usd_today'],.09)
            self.assertEqual(broker.budget(db,'2026-10-10T12:00:00+00:00')['lifetime_new_attempts'],24)
            self.assertEqual(broker.budget(db,'2026-10-10T12:00:00+00:00')['attempts_remaining_today'],24);db.close()

    def test_monthly_cap_and_paris_rollover_do_not_clear_reservations(self):
        with tempfile.TemporaryDirectory() as root:
            db=broker.connect(root);price={'rates_nano_per_token':{'input':1,'output':166000,'hit':1}}
            for day in range(1,21):self.assertIsNotNone(broker.reserve(db,str(day),0,price,5000,f'2026-10-{day:02d}T12:00:00+00:00')[0])
            self.assertEqual(broker.reserve(db,'over',0,price,5000,'2026-10-21T12:00:00+00:00')[1],'WAIT_MONTHLY_API_BUDGET')
            self.assertIsNotNone(broker.reserve(db,'newmonth',0,price,5000,'2026-11-01T12:00:00+00:00')[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],21);db.close()
        self.assertEqual(period('2026-09-30T22:00:00+00:00'),('2026-10-01','2026-10'))

    def test_retry_429_is_second_shared_reservation_and_not_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);planner.ensure_request(db,mail);calls=[]
            def send(body):
                calls.append(body)
                if len(calls)==1:raise urllib.error.HTTPError('https://api.deepseek.com',429,'rate limit',{},None)
                return reply()
            self.assertEqual(broker.once(mail,send,lambda:TARIFF,'2026-10-09T12:00:00+00:00'),'WAIT_RETRY_BACKOFF')
            self.assertEqual(broker.once(mail,send,lambda:TARIFF,'2026-10-09T12:00:06+00:00'),'COMPLETE')
            broker.once(mail,send,lambda:TARIFF,'2026-10-09T12:00:12+00:00');self.assertEqual(len(calls),2)
            adb=broker.connect(mail);self.assertEqual(broker.budget(adb,'2026-10-09T12:00:00+00:00')['attempts_today'],2);adb.close();db.close()

    def test_uncertain_transport_crash_keeps_budget_without_retry(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);planner.ensure_request(db,mail)
            def crash(body):raise KeyboardInterrupt('power loss after durable reservation')
            with self.assertRaises(KeyboardInterrupt):broker.once(mail,crash,lambda:TARIFF)
            sent=[];self.assertEqual(broker.once(mail,lambda body:sent.append(body),lambda:TARIFF),'UNCERTAIN');self.assertEqual(sent,[])
            adb=broker.connect(mail);self.assertEqual(broker.budget(adb)['lifetime_new_attempts'],1);self.assertGreater(broker.budget(adb)['reserved_usd_month'],0);adb.close();db.close()

    def test_real_AI_receipt_to_backtest_and_train_feedback_request(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);rid,_=planner.ensure_request(db,mail)
            broker.once(mail,lambda body:reply(),lambda:TARIFF);planner.ingest(db,mail)
            p=json.loads(db.execute("SELECT body FROM proposals WHERE origin='AI_AUTHORED'").fetchone()[0])
            self.assertEqual(p['genes'],proposal()['genes']);self.assertEqual(p['request'],rid)
            for _ in range(4):runtime.tick(db,root,mail,lambda:(None,None),evaluator,discovery_fn=discovery)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM closed').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],2)
            queued=json.loads(db.execute('SELECT body FROM requests WHERE trigger_batch=1').fetchone()[0])
            self.assertTrue(all(p['validation']['interval'][1]=='2021-12-17' for p in queued['payload']['parents']))
            self.assertNotIn('diagnostic_only',canonical(queued['payload']));self.assertEqual(db.execute('SELECT COUNT(*) FROM backtests').fetchone()[0],21);db.close()

    def test_mid_ingest_crash_does_not_duplicate_admissions(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);planner.ensure_request(db,mail);broker.once(mail,lambda body:reply(),lambda:TARIFF)
            original=planner.register
            def crash(*args,**kwargs):original(*args,**kwargs);raise KeyboardInterrupt('after proposal commit')
            with patch.object(planner,'register',crash):
                with self.assertRaises(KeyboardInterrupt):planner.ingest(db,mail)
            planner.ingest(db,mail);self.assertEqual(db.execute('SELECT COUNT(*) FROM proposal_receipts').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0],1);db.close()

    def test_backtest_crash_resumes_same_candidate_and_alpha_reservation(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root)
            def crash(*args):raise KeyboardInterrupt('engine interrupted')
            with self.assertRaises(KeyboardInterrupt):runtime.tick(db,root,mail,lambda:(None,None),crash,discovery_fn=discovery)
            key=db.execute('SELECT id,key FROM attempts').fetchone();db.close();db=ledger.connect(root)
            planner.initialize(db,boot(),{'fixture':'stable'})
            runtime.tick(db,root,mail,lambda:(None,None),evaluator,discovery_fn=discovery)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT id FROM attempts WHERE key=?',(key[1],)).fetchone()[0],key[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],6);ledger.verify(db);db.close()

    def test_more_than_old_eight_batches_continue_under_API_limit(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root)
            for _ in range(36):runtime.tick(db,root,mail,lambda:(None,None),evaluator,discovery_fn=discovery)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM closed').fetchone()[0],9)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0],36)
            self.assertEqual(db.execute('SELECT COUNT(DISTINCT candidate) FROM feedback').fetchone()[0],36)
            b=json.loads(db.execute('SELECT body FROM batches WHERE id=9').fetchone()[0]);self.assertEqual(len(b['prior_training_feedback_hashes']),4)
            self.assertEqual(b['last_alpha_index'],1480);db.close()

    def test_daily_compute_wait_renews_without_resetting_lifetime_attempts(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);c=load()
            with db:
                db.executemany('INSERT INTO scientific_attempts(candidate,day,utc) VALUES(?,?,?)',((str(i),'2026-10-09','fixture') for i in range(128)))
            p=proposal();p.update(id=schema.identity(p),gene_id=digest(p['genes']),origin='LOCAL_NEIGHBOR',request=None)
            self.assertFalse(runtime.evaluate_candidate(db,root,None,None,1,p,discovery(),evaluator,'2026-10-09T12:00:00+00:00'))
            self.assertTrue(runtime.evaluate_candidate(db,root,None,None,1,p,discovery(),evaluator,'2026-10-10T12:00:00+00:00'))
            self.assertEqual(db.execute('SELECT alpha_index FROM statistics').fetchone()[0],1444+129)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM scientific_attempts').fetchone()[0],129);db.close()

    def test_missing_LUNA_candidate_does_not_stop_independent_candidates(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);planner.freeze_next(db,mail)
            first=json.loads(db.execute('SELECT body FROM batches').fetchone()[0])['entries'][0]['genes']
            def fail_one(m,f,g,interval,stress):
                if g==first:raise ValueError('missing_held_asset_price:LUNAUSDT@original')
                return evaluator(m,f,g,interval,stress)
            for _ in range(4):runtime.tick(db,root,mail,lambda:(None,None),fail_one,discovery_fn=discovery)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM feedback WHERE json_extract(body,'$.valid')=0").fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM closed').fetchone()[0],1);db.close()

    def test_fully_exhausted_space_is_idle_without_new_attempts(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);space=schema.spaces()[0];keys=list(space)
            with db:
                db.executemany('INSERT OR IGNORE INTO genes VALUES(?,?)',((digest({'family':'K',**dict(zip(keys,v))}),'LOCAL_ENUMERATION') for v in itertools.product(*(space[k] for k in keys))))
            self.assertEqual(runtime.tick(db,root,mail,lambda:(_ for _ in ()).throw(AssertionError('must not load market')),evaluator,discovery_fn=discovery),'IDLE_NO_AUTHORIZED_NOVEL_WORK')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],0);db.close()

    def test_price_parser_and_usage_violation(self):
        cells=['MODEL','deepseek-flash(1)','deepseek-v4-pro']
        for label,off,peak in [('1M INPUT TOKENS(CACHE HIT)','.003','.006'),('1M INPUT TOKENS(CACHE MISS)','.15','.3'),('1M OUTPUT TOKENS','.6','1.2')]:
            cells.extend([label,'OFF-PEAK','$0'+off if off.startswith('.') else '$'+off,'$9','PEAK','$0'+peak if peak.startswith('.') else '$'+peak,'$9'])
        html='<table><tr>'+''.join('<td>'+v+'</td>' for v in cells)+'</tr></table>'
        self.assertEqual(broker.parse_tariff(html)['rates_nano_per_token'],TARIFF['rates_nano_per_token'])
        with self.assertRaises(ValueError):broker.parse_tariff('<html>unavailable</html>')
        r=reply();r['usage']['prompt_tokens']=6501;self.assertTrue(broker.receipt(r)['budget_violation'])

    def test_unchanged_native_engine_with_readonly_market(self):
        from research.phase2_v2.market import synthetic_market
        from research.anomaly_lab.rules import prepare
        from research.discovery_evolution.runtime import restricted_market
        m=synthetic_market();m.eligible.setflags(write=False);f=prepare(m);child=restricted_market(m,f)
        value=runtime.default_evaluator(child,f,gene(10),['2020-01-01','2020-06-30'],'nominal')
        self.assertTrue(value['audit']['pnl_reconciled']);self.assertEqual(value['metrics']['elapsed_calendar_days'],182)

    def test_deployment_isolates_credential_and_predecessor_state(self):
        from research.continuous_research.deploy import units,WORKER,BROKER
        u=units('/opt/research-fixture');w=u[WORKER+'.service'];b=u[BROKER+'.service']
        self.assertIn('PrivateNetwork=true',w);self.assertNotIn('LoadCredential=',w)
        self.assertIn('LoadCredential=deepseek-key:/etc/credstore/trendatlas-research-deepseek',b)
        self.assertIn('/var/lib/trendatlas-continuous-research /var/lib/trendatlas-research-v2-inputs',b)
        self.assertIn('-/var/lib/trendatlas-discovery-evolution',w);self.assertIn('AccuracySec=1s',u[WORKER+'.timer'])

    def test_invalid_price_quote_waits_without_stopping_local_work(self):
        with tempfile.TemporaryDirectory() as root:
            db,mail=setup(root);planner.ensure_request(db,mail)
            def invalid():raise ValueError('provider pricing page unavailable')
            self.assertEqual(broker.once(mail,lambda body:reply(),invalid),'WAIT_VERIFIED_TARIFF')
            self.assertEqual(runtime.tick(db,root,mail,lambda:(None,None),evaluator,discovery_fn=discovery),'PROGRESSED')
            adb=broker.connect(mail);self.assertEqual(broker.budget(adb)['lifetime_new_attempts'],0);adb.close();db.close()


if __name__=='__main__':unittest.main()
