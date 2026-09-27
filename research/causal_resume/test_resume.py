"""Run with the frozen release on sys.path, not the mutable research checkout."""
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

parser = argparse.ArgumentParser()
parser.add_argument('--engine', required=True)
options, rest = parser.parse_known_args()
ENGINE = Path(options.engine).resolve()
sys.path.insert(0, str(ENGINE))
spec = importlib.util.spec_from_file_location('resume_runtime', Path(__file__).with_name('runtime.py'))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
from research.causal_evolution.protocol import freeze, CONTRACT, digest
from research.causal_evolution.store import Store
from research.causal_evolution.resources import Guard, PauseResearch
from research.causal_evolution.evaluator import Evaluator
from research.causal_evolution.controller import AwaitBroker
from research.causal_evolution.vendor.common import config
from research.causal_evolution.gate import allowed, dispatch_allowed


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest = freeze(self.root, True)
        self.s = Store(self.root)
        self.s.set('experiment_id', self.manifest['experiment_id'])
        self.s.set('fingerprint', self.manifest['fingerprint'])
        self.s.set('status', 'RUNNING')
        self.policy = dict(runtime.POLICY, experiment_id=self.manifest['experiment_id'],
            fingerprint=self.manifest['fingerprint'], manifest_sha256=runtime.sha(self.root/'frozen_manifest.json'))

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def book(self, e, index=0):
        return e.evaluate(config(signal=['sma200', 'mom90', 'breakout120'][index]),
            dict(scope='inner_train', fold=0, start='2020-01-01', end='2020-02-01'), 'spot')

    def test_cooperative_deadline_before_hard_timeout(self):
        p = runtime.POLICY
        self.assertGreaterEqual(p['hard_timeout_seconds']-p['cooperative_seconds'], 120)
        g = Guard(self.s, seconds=p['cooperative_seconds'])
        with patch('research.causal_evolution.resources.time.monotonic', return_value=g.start+1679):
            g(force=True)
        with patch('research.causal_evolution.resources.time.monotonic', return_value=g.start+1680):
            with self.assertRaisesRegex(PauseResearch, 'bounded_activation_checkpoint'):
                g(force=True)

    def test_original_broker_except_failure_is_checkpointed(self):
        def elapsed_sleep(_):
            # Exact former failure path: cooperative exception in AwaitBroker handler.
            raise PauseResearch('bounded_activation_checkpoint')
        with patch('research.causal_evolution.controller.run_search', side_effect=AwaitBroker), \
             patch.object(runtime.time, 'sleep', side_effect=elapsed_sleep):
            self.assertEqual(runtime.activate(self.s, 1680, synthetic=True), 0)
        self.assertEqual(self.s.meta('status'), 'CHECKPOINTED')
        self.assertIsNone(self.s.meta('failure'))

    def test_three_activations_real_evaluator_cache_lineage_budget_and_oos(self):
        budget = json.dumps(CONTRACT['budget'], sort_keys=True)
        manifest = (self.root/'frozen_manifest.json').read_bytes()
        saved = []
        for activation in range(3):
            def search(s, e, *_):
                for i in range(activation+1):
                    s.add_trial('test:'+str(i), 'test', 0, config(signal=['sma200','mom90','breakout120'][i]))
                    self.book(e, i)
                raise PauseResearch('bounded_activation_checkpoint')
            with patch('research.causal_evolution.controller.run_search', side_effect=search):
                self.assertEqual(runtime.activate(self.s, 1680, synthetic=True), 0)
            self.assertEqual(self.s.counts()['evaluations'], activation+1)
            self.assertEqual(self.s.counts()['attempts'], activation+1)
            self.assertEqual(self.s.meta('status'), 'CHECKPOINTED')
            self.assertFalse(self.s.meta('outer_opened', False))
            now = list(map(tuple, self.s.db.execute('SELECT * FROM evaluations ORDER BY cache_key')))
            self.assertTrue(all(row in now for row in saved))
            saved = now
        self.assertEqual(self.s.counts()['trials'], 3)
        self.assertEqual(self.s.counts()['proposals'], 0)
        self.assertEqual(json.dumps(CONTRACT['budget'], sort_keys=True), budget)
        self.assertEqual((self.root/'frozen_manifest.json').read_bytes(), manifest)

    def test_sigterm_just_before_checkpoint(self):
        previous = signal.getsignal(signal.SIGTERM)
        def loop(s, e, guard, *_):
            signal.signal(signal.SIGTERM, guard.request_stop)
            signal.raise_signal(signal.SIGTERM)
            guard(force=True)
        try:
            with patch.object(runtime, 'search_loop', side_effect=loop):
                self.assertEqual(runtime.activate(self.s, 1680, synthetic=True), 0)
        finally:
            signal.signal(signal.SIGTERM, previous)
        self.assertEqual(self.s.meta('status'), 'PAUSED_WAITING_RESUME')
        self.assertFalse(self.s.meta('outer_opened', False))

    def test_actual_process_crash_after_reservation(self):
        script = "import sys,os;sys.path.insert(0,sys.argv[1]);from research.causal_evolution.store import Store;s=Store(sys.argv[2]);s.reserve('crashed','inner_train');os._exit(71)"
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(ENGINE), str(self.root)])
        self.assertEqual(result.returncode, 71)
        self.assertEqual(len(runtime.reconcile(self.s)), 1)
        self.assertEqual(runtime.reconcile(self.s), [])
        self.assertEqual(self.s.counts()['attempts'], 1)
        self.assertEqual(self.s.db.execute('SELECT status FROM attempts').fetchone()[0], 'INTERRUPTED')
        self.book(Evaluator(self.s, synthetic=True))
        self.assertEqual(self.s.counts()['attempts'], 2)
        self.assertEqual(self.s.counts()['evaluations'], 1)

    def test_pause_inside_reserved_evaluation_is_transactionally_reconciled(self):
        def loop(s, *_):
            s.reserve('interrupted', 'inner_validation')
            raise PauseResearch('bounded_activation_checkpoint')
        with patch.object(runtime, 'search_loop', side_effect=loop):
            runtime.activate(self.s, 1680, synthetic=True)
        self.assertEqual(self.s.db.execute('SELECT status FROM attempts').fetchone()[0], 'INTERRUPTED')
        self.assertEqual(runtime.reconcile(self.s), [])

    def test_multiple_reservations_fail_without_partial_repair(self):
        self.s.reserve('a', 'inner_train'); self.s.reserve('b', 'inner_train')
        with self.assertRaisesRegex(RuntimeError, 'More than one'):
            runtime.activate(self.s, 1680, synthetic=True)
        self.assertEqual(self.s.meta('status'), 'FAILED')
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM attempts WHERE status='RUNNING'").fetchone()[0], 2)

    def test_real_error_remains_failed_and_cannot_auto_resume(self):
        with patch.object(runtime, 'search_loop', side_effect=ValueError('real evaluation failure')):
            with self.assertRaises(ValueError):
                runtime.activate(self.s, 1680, synthetic=True)
        self.assertEqual(self.s.meta('status'), 'FAILED')
        with self.assertRaisesRegex(RuntimeError, 'not admitted'):
            runtime.activate(self.s, 1680, synthetic=True)

    def test_sealed_repeat_does_not_evaluate(self):
        self.s.set('status', 'SEALED')
        with patch.object(runtime, 'search_loop') as loop:
            self.assertEqual(runtime.activate(self.s, 1680, synthetic=True), 0)
            loop.assert_not_called()

    def test_outer_stays_closed_before_nomination_freeze(self):
        e = Evaluator(self.s, synthetic=True)
        with self.assertRaisesRegex(RuntimeError, 'Outer is sealed'):
            e.evaluate(config(), dict(scope='outer',fold=2024,start='2024-01-01',end='2024-12-31'), 'spot')
        self.assertFalse(self.s.meta('outer_opened', False))

    def test_frozen_identity_verified_before_resume(self):
        runtime.verify(self.root, ENGINE, self.policy)
        for field in ('experiment_id', 'fingerprint'):
            old = self.s.meta(field)
            self.s.set(field, 'wrong')
            with self.assertRaisesRegex(RuntimeError, 'SQLite experiment binding'):
                runtime.verify(self.root, ENGINE, self.policy)
            self.s.set(field, old)
        with self.assertRaisesRegex(RuntimeError, 'engine or raw'):
            runtime.verify(self.root, self.root/'wrong-engine', self.policy)
        with self.assertRaisesRegex(RuntimeError, 'manifest binding'):
            runtime.verify(self.root, ENGINE, dict(self.policy, manifest_sha256='wrong'))

    def test_recovery_requires_verified_backup_and_is_idempotent(self):
        self.book(Evaluator(self.s, synthetic=True))
        self.s.set('status', 'FAILED')
        self.s.set('failure', dict(type='PauseResearch', reason='bounded_activation_checkpoint'))
        backup = self.root/'backup'; backup.mkdir()
        audit = dict(source=str(self.root), databases={})
        for name, source in (('candidates.sqlite', self.s.db), ('mailbox/proposals.sqlite', self.s.mail)):
            target = backup/name; target.parent.mkdir(parents=True, exist_ok=True)
            dest = sqlite3.connect(target); source.backup(dest); dest.close()
            audit['databases'][name] = dict(sha256=runtime.sha(target))
        (backup/'frozen_manifest.json').write_bytes((self.root/'frozen_manifest.json').read_bytes())
        (backup/'backup_audit.json').write_text(json.dumps(audit))
        policy = dict(self.policy, recovery=dict(self.policy['recovery'], completed_evaluations=1))
        before = list(map(tuple, self.s.db.execute('SELECT * FROM evaluations')))
        runtime.recover(self.s, backup, policy)
        runtime.recover(self.s, backup, policy)
        self.assertEqual(self.s.meta('status'), 'CHECKPOINTED')
        self.assertEqual(list(map(tuple, self.s.db.execute('SELECT * FROM evaluations'))), before)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM orchestration_events').fetchone()[0], 1)

    def test_production_preemption_and_dispatch_job_race(self):
        service = dict(LoadState='loaded', ActiveState='inactive', SubState='dead', Result='success', ExecMainExitTimestampMonotonic='1')
        timer = dict(UnitFileState='enabled', ActiveState='active')
        self.assertTrue(allowed(service, timer, []))
        self.assertFalse(allowed(dict(service, ActiveState='active'), timer, []))
        self.assertFalse(allowed(service, timer, [{'unit':'mrv1-production.service'}]))
        worker = dict(LoadState='loaded', ActiveState='inactive')
        self.assertTrue(dispatch_allowed(worker, []))
        self.assertFalse(dispatch_allowed(worker, [{'unit':'trendatlas-evolution-worker.service'}]))
        self.assertFalse(dispatch_allowed(dict(worker, ActiveState='active'), []))

    def test_dropins_retain_hard_timeout_and_original_security(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import deploy
        files = deploy.dropins('/opt/trendatlas-research/orchestration/test')
        self.assertEqual(set(files), {'trendatlas-evolution-worker.service','trendatlas-evolution-dispatch.service'})
        worker = files['trendatlas-evolution-worker.service']
        self.assertIn('RuntimeMaxSec=1800s', worker)
        self.assertIn('run --seconds 1680', worker)
        self.assertIn('gate.py', worker)
        for text in files.values():
            for forbidden in ('Conflicts=', 'After=', 'RefuseManualStart=', 'PrivateNetwork=', 'InaccessiblePaths=', 'SuccessExitStatus='):
                self.assertNotIn(forbidden, text)  # Inherited unchanged, no weakening.
        with self.assertRaises(ValueError):
            deploy.dropins('/tmp/test', 1801)

    def test_sqlite_admission_ignores_stale_failed_status_json(self):
        self.s.set('status', 'CHECKPOINTED')
        (self.root/'status.json').write_text('{"status":"FAILED"}')
        meta = runtime.verify(self.root, ENGINE, self.policy)
        self.assertEqual(meta['status'], 'CHECKPOINTED')
        self.assertEqual(runtime.ready(dict(meta, status='FAILED')), 255)

    def test_admission_error_cannot_trigger_systemd_onsuccess(self):
        with patch.object(runtime, 'verify', side_effect=sqlite3.OperationalError('unreadable WAL')):
            self.assertEqual(runtime.entrypoint(['ready']), 255)

    def test_worker_lock_blocks_duplicate_process(self):
        from research.causal_evolution.locking import WorkerLock
        script = "import sys;sys.path.insert(0,sys.argv[1]);from research.causal_evolution.locking import WorkerLock;WorkerLock(sys.argv[2]).__enter__()"
        with WorkerLock(self.root/'worker.lock'):
            result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(ENGINE), str(self.root/'worker.lock')], capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]]+rest)
