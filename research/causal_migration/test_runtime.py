"""Orchestration regressions on synthetic books; no real experiment mutation."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

p=argparse.ArgumentParser();p.add_argument('--engine',required=True)
args,rest=p.parse_known_args();sys.path.insert(0,str(Path(args.engine).resolve()))
spec=importlib.util.spec_from_file_location('migration_runtime',Path(__file__).with_name('runtime.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
from research.causal_evolution.protocol import freeze, CONTRACT
from research.causal_evolution.store import Store
from research.causal_evolution.evaluator import Evaluator
from research.causal_evolution.vendor.common import config
from research.causal_evolution.resources import PauseResearch


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.manifest=freeze(self.root,True);self.s=Store(self.root)
        for k,v in [('experiment_id',self.manifest['experiment_id']),('fingerprint',self.manifest['fingerprint']),('status','CHECKPOINTED')]:self.s.set(k,v)
        self.book(Evaluator(self.s,synthetic=True),'sma200')

    def tearDown(self):self.s.close();self.tmp.cleanup()

    def book(self,e,signal_name):
        return e.evaluate(config(signal=signal_name),dict(scope='inner_train',fold=0,start='2020-01-01',end='2020-02-01'),'spot')

    def authorize(self,g):
        r.atomic(self.root/'stop_request.json',dict(token=g.record['token'],pid=g.record['pid']))
        g.signal()

    def seed_ai_ledger(self):
        with self.s.mail:
            self.s.mail.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?)',
                ('fixture-call','test',1,'{}','COMPLETE','{}','{}',
                 json.dumps(dict(api_call=1,total_tokens=123,usd=.001,reserved_usd=.01)),'fixture'))
        return r.rows_hash(self.s.mail,'proposals')

    def test_admin_stop_during_helper_is_checkpoint_not_failure(self):
        def loop(s,e,g):
            self.authorize(g)
            raise subprocess.CalledProcessError(-signal.SIGTERM,['/usr/bin/systemctl','list-jobs','--no-legend','--no-pager'])
        self.assertEqual(r.activate(self.s,synthetic=True,loop=loop,no_outer=True),0)
        self.assertEqual(self.s.meta('status'),'CHECKPOINTED');self.assertIsNone(self.s.meta('failure'))

    def test_admin_stop_during_evaluation_retains_interrupted_attempt(self):
        old=r.rows_hash(self.s.db,'evaluations')
        def loop(s,e,g):
            s.reserve('uncommitted','inner_train');self.authorize(g);g(force=True)
        r.activate(self.s,synthetic=True,loop=loop,no_outer=True)
        self.assertEqual(self.s.meta('status'),'CHECKPOINTED')
        self.assertEqual(r.rows_hash(self.s.db,'evaluations'),old)
        self.assertEqual(self.s.db.execute("SELECT status FROM attempts WHERE cache_key='uncommitted'").fetchone()[0],'INTERRUPTED')
        self.assertEqual(r.legacy.reconcile(self.s),[])

    def test_unexpected_sigterm_unsaved_work_is_failed(self):
        def loop(s,e,g):s.reserve('uncommitted','inner_train');g.signal();g(force=True)
        with self.assertRaises(r.UnexpectedStop):r.activate(self.s,synthetic=True,loop=loop)
        self.assertEqual(self.s.meta('status'),'FAILED')
        self.assertEqual(self.s.db.execute("SELECT status FROM attempts WHERE cache_key='uncommitted'").fetchone()[0],'RUNNING')

    def test_stale_stop_token_does_not_authorize_signal(self):
        r.atomic(self.root/'stop_request.json',dict(token='old',pid=os.getpid()))
        def loop(s,e,g):g.signal();g(force=True)
        with self.assertRaises(r.UnexpectedStop):r.activate(self.s,synthetic=True,loop=loop)

    def test_other_helper_failure_is_failed_even_during_stop(self):
        def loop(s,e,g):self.authorize(g);raise subprocess.CalledProcessError(1,['/usr/bin/systemctl','list-jobs'])
        with self.assertRaises(subprocess.CalledProcessError):r.activate(self.s,synthetic=True,loop=loop)
        self.assertEqual(self.s.meta('status'),'FAILED')

    def test_timeout_poststop_resumes_only_valid_durable_checkpoint(self):
        record=dict(initial_evaluations=1,closed_outer=True,active_seconds_before=0,monotonic=r.time.monotonic(),token='timeout')
        r.atomic(self.root/'activation.json',record);self.s.set('status','RUNNING')
        self.s.reserve('hard-killed','inner_train')
        r.finalize(self.s,'timeout')
        self.assertEqual(self.s.meta('status'),'CHECKPOINTED')
        self.assertEqual(self.s.counts()['evaluations'],1)
        self.assertEqual(self.s.db.execute("SELECT status FROM attempts WHERE cache_key='hard-killed'").fetchone()[0],'INTERRUPTED')
        before=r.rows_hash(self.s.db,'orchestration_events');r.finalize(self.s,'timeout')
        self.assertEqual(before,r.rows_hash(self.s.db,'orchestration_events'))

    def test_timeout_with_invalid_checkpoint_is_failed(self):
        r.atomic(self.root/'activation.json',dict(initial_evaluations=1,closed_outer=True,active_seconds_before=0,monotonic=r.time.monotonic(),token='bad'))
        self.s.set('status','RUNNING');self.s.set('checkpoint',dict(attempt=999,evaluation='missing'))
        with self.assertRaisesRegex(RuntimeError,'checkpoint mismatch'):r.finalize(self.s,'timeout')
        self.assertEqual(self.s.meta('status'),'FAILED')

    def test_repeat_start_stop_preserves_cache_lineage_ledger_budget_oos(self):
        budget=json.dumps(CONTRACT['budget'],sort_keys=True)
        ledger=self.seed_ai_ledger()
        self.s.set('active_seconds',42.)
        manifest=(self.root/'frozen_manifest.json').read_bytes()
        saved=[tuple(x) for x in self.s.db.execute('SELECT * FROM evaluations')]
        for signal_name in ['mom90','breakout120','mom90']:
            def loop(s,e,g):
                s.add_trial(signal_name,'test',0,config(signal=signal_name))
                self.book(e,signal_name);self.authorize(g);g(force=True)
            r.activate(self.s,synthetic=True,loop=loop,no_outer=True)
            self.assertEqual(self.s.meta('status'),'CHECKPOINTED')
            self.assertFalse(self.s.meta('outer_opened',False))
            self.assertTrue(all(x in [tuple(v) for v in self.s.db.execute('SELECT * FROM evaluations')] for x in saved))
        self.assertEqual(self.s.counts()['evaluations'],3);self.assertEqual(self.s.counts()['attempts'],3)
        self.assertEqual(self.s.counts()['trials'],2);self.assertEqual(self.s.counts()['proposals'],1)
        self.assertEqual(r.rows_hash(self.s.mail,'proposals'),ledger)
        self.assertGreaterEqual(self.s.meta('active_seconds'),42.)
        self.assertEqual(json.dumps(CONTRACT['budget'],sort_keys=True),budget)
        self.assertEqual((self.root/'frozen_manifest.json').read_bytes(),manifest)

    def test_recovery_exact_5085_fixture_preserves_all_rows_and_history(self):
        # Accounting fixture only: 5085 unique synthetic records, not market evidence.
        self.seed_ai_ledger()
        parent=self.s.add_trial('seed','test',0,config(signal='sma200'))
        child=self.s.add_trial('child','test',1,config(signal='mom90'),parent=parent,source='deterministic')
        self.s.population('test',1,[parent,child])
        base=list(self.s.db.execute('SELECT * FROM evaluations').fetchone())
        for n in range(1,5085):
            row=list(base);row[0]='fixture-'+str(n)
            with self.s.db:
                self.s.db.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?,?,?)',row)
                self.s.db.execute('INSERT INTO attempts(cache_key,started,finished,status,scope) VALUES(?,?,?,?,?)',(row[0],'fixture','fixture','COMPLETE','inner_train'))
        cp=self.s.db.execute('SELECT id,cache_key FROM attempts ORDER BY id DESC LIMIT 1').fetchone()
        self.s.set('checkpoint',dict(attempt=cp[0],evaluation=cp[1],utc='fixture'))
        rule=dict(r.POLICY['recovery'],attempts=5085,candidates=2,trials=2)
        policy=dict(r.POLICY,recovery=rule,manifest_sha256=r.legacy.sha(self.root/'frozen_manifest.json'))
        failure=dict(type=rule['failure_type'],reason=rule['failure_reason'],utc=rule['failure_utc'])
        self.s.set('failure',failure);r.event(self.s,'FAILED','original',failure=failure)
        before={t:r.rows_hash(self.s.db,t) for t in r.TABLES}
        before_mail=r.rows_hash(self.s.mail,'proposals')
        backup=self.root/'backup';backup.mkdir();audit=dict(source=str(self.root),databases={})
        for name,db in [('candidates.sqlite',self.s.db),('mailbox/proposals.sqlite',self.s.mail)]:
            path=backup/name;path.parent.mkdir(parents=True,exist_ok=True)
            dest=sqlite3.connect(path);db.backup(dest);dest.close();audit['databases'][name]={'sha256':r.legacy.sha(path)}
        (backup/'frozen_manifest.json').write_bytes((self.root/'frozen_manifest.json').read_bytes())
        (backup/'backup_audit.json').write_text(json.dumps(audit))
        r.recover(self.s,backup,policy);r.recover(self.s,backup,policy)
        self.assertEqual(before,{t:r.rows_hash(self.s.db,t) for t in r.TABLES})
        self.assertEqual(before_mail,r.rows_hash(self.s.mail,'proposals'))
        self.assertEqual(self.s.counts()['evaluations'],5085)
        self.assertEqual(self.s.meta('migration_recovery')['original_failure'],failure)
        self.assertIsNone(self.s.meta('failure'));self.assertFalse(self.s.meta('outer_opened',False))
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM orchestration_events').fetchone()[0],3)


if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+rest)
