"""Campaign lifecycle with synthetic prices; real history runs only on the Pi."""
import ast
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from research_os.dev_only.evolution_worker import campaign as c, runtime as w, walk_forward as e
from scripts.research.build_evolution_worker_release import FILES, ROOT

REAL_DISK_GUARD = c.disk_guard


def positive(*args, **kwargs):
    return {'metrics': {'fitness': .05, 'total_return': .05, 'turnover_disqualified': False}, 'curve': [], 'trades': []}


def sealed_fixture(root, job, guard, progress):
    # Queue-budget test isolates orchestration; other tests run all real generations.
    db = e.connect(root)
    try:
        with db:
            info = e.meta(db)
            info.update(state='SEALED', outcome=e.pure.REJECT)
            e.save(db, info)
        return info
    finally:
        db.close()


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / 'state'
        self.state.mkdir()
        self.release = self.base / 'release'
        for name in FILES:
            dest = self.release / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / name).read_bytes())
        identity = {'source_commit': 'a' * 40, 'files': {n: w.sha(self.release / n) for n in FILES}}
        self.manifest = {**identity, 'release_sha256': w.digest(w.canonical(identity).encode())}
        (self.release / 'manifest.json').write_text(w.canonical(self.manifest))
        days = [(date(2018, 1, 1) + timedelta(days=i)).isoformat() for i in range(3105)]
        self.raw = ('date,open,high,low,close,volume\n' + ''.join(f'{d},100,101,99,100,1\n' for d in days)).encode()
        definition = json.loads(c.DEFINITION.read_bytes())
        for study in definition['studies']:
            study['input_sha256'] = w.digest(self.raw)
        self.definition = self.base / 'synthetic-campaign.json'
        self.definition.write_text(w.canonical(definition))
        self.auth = {'definition': definition, 'release_sha256': self.manifest['release_sha256'],
                     'preregistration_commit': c.PREREGISTRATION, 'activated_at': time.time()}
        w.atomic_json(self.state / 'campaign.json', self.auth)
        w.atomic_bytes(self.state / 'campaign-input' / 'BTCUSDT_1d.csv', self.raw)
        for patcher in [patch.object(c, 'DEFINITION', self.definition), patch.object(c, 'temperature', return_value=50), patch.object(c, 'disk_guard'),
                        patch.dict(os.environ, {'PATH': os.environ.get('PATH', ''), 'LANG': 'C.UTF-8'}, clear=True)]:
            patcher.start(); self.addCleanup(patcher.stop)
        self.job = c.job_for(self.auth, definition['studies'][0])

    def run_campaign(self):
        return c.run(self.release, self.state, check_production=False)

    def first_only(self, fake=positive):
        original = c.resource_guard
        def stop_after_one(state, auth, root=None):
            if any(v['state'] == 'SEALED' for v in c.known_jobs(state).values()):
                raise w.Paused('test boundary')
            original(state, auth, root)
        with patch.object(c, 'resource_guard', side_effect=stop_after_one), patch.object(e, 'backtest', side_effect=fake):
            return self.run_campaign()

    def test_empty_queue_authorized_campaign_creates_and_evaluates_real_job(self):
        self.first_only(fake=e.backtest)
        rows = c.known_jobs(self.state)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[self.job['job_id']]['outcome'], e.pure.REJECT)
        report = e.report(self.state / 'jobs' / self.job['job_id'])
        self.assertEqual(report['meta']['completed_generations'], 5)
        self.assertEqual(report['evaluated_candidates'], 26)
        self.assertIn('walk_forward_assessment', report['comparisons']['cash'])
        self.assertTrue((self.state / 'campaign_queue' / self.job['job_id'] / 'study.json').exists())

    def test_budget_exhausted_has_exactly_ten_jobs_and_no_unbounded_requeue(self):
        with patch.object(e, 'step', side_effect=sealed_fixture):
            result = self.run_campaign()
        self.assertEqual(result['pause_reason'], 'campaign_budget_exhausted')
        self.assertEqual(len(c.known_jobs(self.state)), 10)
        self.assertFalse(c.pending(self.state, self.manifest))
        before = {str(p): w.sha(p) for p in (self.state / 'jobs').rglob('*') if p.is_file()}
        self.run_campaign()
        self.assertEqual(before, {str(p): w.sha(p) for p in (self.state / 'jobs').rglob('*') if p.is_file()})
        with self.assertRaises(w.Blocked):
            c.enqueue(self.state, self.job, self.manifest)

    def test_partial_period_commit_resumes_and_assessment_never_enters_selection(self):
        root = c.prepare(self.state, self.job)
        calls = []
        def observe(bars, genes, start, end, **kwargs):
            calls.append((start, end, max(b.day for b in bars)))
            self.assertLessEqual(max(b.day for b in bars), self.job['study']['selection_folds'][-1]['end'])
            return positive()
        count = 0
        def crash():
            nonlocal count
            count += 1
            if count == 3:
                raise RuntimeError('reboot')
        with patch.object(e, 'backtest', side_effect=observe):
            with self.assertRaises(RuntimeError):
                e.step(root, self.job, lambda: None, crash)
        before = e.report(root)
        self.assertEqual(before['period_evaluations'], 3)
        self.assertEqual(before['meta']['completed_generations'], 0)
        with patch.object(e, 'backtest', side_effect=observe):
            e.step(root, self.job, lambda: None, lambda: None)
        report = e.report(root)
        self.assertEqual(len(calls), 60)  # 10 candidates + 2 benchmarks, five periods.
        self.assertEqual(report['meta']['completed_generations'], 1)
        self.assertTrue(all(a <= b == visible for a, b, visible in calls))
        self.assertEqual(len(report['generations'][0]['survivors']), 6)
        self.assertEqual(len(report['generations'][0]['mutations']), 4)
        other = self.base / 'uninterrupted'
        other.mkdir()
        w.atomic_bytes(other / 'input.csv', self.raw)
        e.initialize(other, self.job)
        with patch.object(e, 'backtest', side_effect=positive):
            e.step(other, self.job, lambda: None, lambda: None)
        self.assertEqual(report['generations'], e.report(other)['generations'])
        self.assertEqual(report['comparisons'], e.report(other)['comparisons'])

    def test_disk_guard_and_status_read_are_safe(self):
        with patch.object(w.shutil, 'disk_usage', return_value=w.shutil._ntuple_diskusage(10**10, 10**10, 0)):
            with self.assertRaises(w.Paused): REAL_DISK_GUARD(self.state)
        root = c.prepare(self.state, self.job)
        c.publish(self.state, self.auth, self.job, 'RUNNING')
        before = {str(p): w.sha(p) for p in root.rglob('*') if p.is_file()}
        value = c.read_status(self.state)
        self.assertEqual(value['current_generation'], 1)
        self.assertEqual(before, {str(p): w.sha(p) for p in root.rglob('*') if p.is_file()})

    def test_thermal_hysteresis_persists_and_resumes_only_below_68(self):
        for temp, pause in [(76, True), (70, True), (68, True), (67.9, False), (75, False)]:
            with patch.object(c, 'temperature', return_value=temp):
                if pause:
                    with self.assertRaises(w.Paused): c.resource_guard(self.state, self.auth)
                else:
                    c.resource_guard(self.state, self.auth)
        with patch.object(c, 'temperature', side_effect=OSError('no sensor')):
            with self.assertRaises(w.Paused): c.resource_guard(self.state, self.auth)

    def test_thermal_pause_and_resume_worker_without_ai_key(self):
        with patch.object(c, 'temperature', return_value=76):
            result = self.run_campaign()
        self.assertEqual(result['status'], 'PAUSED')
        self.assertEqual(c.known_jobs(self.state), {})
        self.assertNotIn('OPENAI_API_KEY', os.environ)
        self.first_only()
        self.assertEqual(c.known_jobs(self.state)[self.job['job_id']]['state'], 'SEALED')

    def test_production_gate_blocks_before_enqueue(self):
        with patch('research_os.dev_only.evolution_worker.gate.main', return_value=1):
            result = c.run(self.release, self.state)
        self.assertEqual(result['status'], 'PAUSED')
        self.assertEqual(result['pause_reason'], 'production_priority')
        self.assertEqual(c.known_jobs(self.state), {})
        self.assertFalse((self.state / 'campaign_queue').exists())

    def test_changed_spec_duplicate_or_old_id_cannot_be_enqueued(self):
        with w.worker_lock(self.state): c.enqueue(self.state, self.job, self.manifest)
        with self.assertRaises(w.Blocked): c.enqueue(self.state, self.job, self.manifest)
        job = json.loads(w.canonical(self.job)); job['study']['seed'] += 1
        with self.assertRaises(w.Blocked): c.validate_job(job, self.manifest, self.state)
        job['job_id'] = 'btc_cash_stability_v2_20260920'
        with self.assertRaises(w.Blocked): c.validate_job(job, self.manifest, self.state)

    def test_blocked_job_halts_campaign_and_budget_is_not_reset(self):
        root = c.prepare(self.state, self.job)
        budget = json.loads((root / 'budget.json').read_bytes())
        self.assertEqual(c.prepare(self.state, self.job), root)
        self.assertEqual(json.loads((root / 'budget.json').read_bytes()), budget)
        with patch.object(c.time, 'time', return_value=budget['deadline'] + 1):
            result = self.run_campaign()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(c.pending(self.state, self.manifest))
        self.assertEqual(len(c.known_jobs(self.state)), 1)

    def test_no_network_execution_or_promotion_imports_and_resource_units(self):
        for name in ('campaign.py', 'walk_forward.py'):
            tree = ast.parse((ROOT / 'research_os/dev_only/evolution_worker' / name).read_text())
            imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(any(x in v for x in ('execution', 'exchange', 'openai', 'socket', 'requests', 'subprocess')) for v in imports))
        worker = (ROOT / 'research_os/dev_only/evolution_worker/systemd/trendatlas-evolution-worker.service.in').read_text()
        for key in ('MemorySwapMax=0', 'CPUQuota=20%', 'MemoryMax=384M', 'Nice=19', 'RefuseManualStart=yes', 'Conflicts=mrv1-production.service', 'After=mrv1-production.service', 'KillMode=control-group'):
            self.assertIn(key, worker)


if __name__ == '__main__':
    unittest.main()
