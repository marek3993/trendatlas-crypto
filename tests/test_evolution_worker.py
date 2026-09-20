"""Worker infrastructure tests use synthetic prices only, never market search."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from research_os.dev_only.evolution_worker import runtime as w, gate
from research_os.dev_only.evolution_worker.fixture import fixture_job
from scripts.research.build_evolution_worker_release import FILES, ROOT


def fake_positive(*args, **kwargs):
    return {"metrics": {"fitness": .1, "total_return": .1, "turnover_disqualified": False},
            "curve": [], "trades": []}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / "release"
        self.state = self.root / "state"
        self.inputs = self.root / "inputs"
        for name in FILES:
            dest = self.release / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / name).read_bytes())
        identity = {"source_commit": "a" * 40, "files": {n: w.sha(self.release / n) for n in FILES}}
        self.manifest = {**identity, "release_sha256": w.digest(w.canonical(identity).encode())}
        (self.release / "manifest.json").write_text(w.canonical(self.manifest))
        self.job, self.raw = fixture_job(self.manifest)
        w.atomic_bytes(self.inputs / "synthetic.csv", self.raw)
        w.atomic_json(self.state / "queue" / self.job["job_id"] / "study.json", self.job)
        self.env = patch.dict(os.environ, {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_worker(self, state=None):
        return w.run_once(self.release, state or self.state, self.inputs, allow_fixture=True)

    def job_root(self):
        return self.state / "jobs" / self.job["job_id"]

    def test_full_frozen_budget_real_synthetic_backtests_and_sealed_immutability(self):
        result = self.run_worker()
        self.assertEqual(result["outcome"], "HISTORICAL_REJECT")
        report = json.loads((self.job_root() / "report.json").read_bytes())
        self.assertEqual(report["meta"]["completed_generations"], 5)
        self.assertEqual(report["evaluated_candidates"], 26)
        self.assertTrue(all([len(g[k]) for k in ("population", "survivors", "mutations")] == [10, 6, 4]
                            for g in report["generations"]))
        before = {str(p): w.sha(p) for p in self.job_root().rglob("*") if p.is_file()}
        self.assertEqual(self.run_worker(), {"status": "IDLE"})
        self.assertEqual(before, {str(p): w.sha(p) for p in self.job_root().rglob("*") if p.is_file()})
        self.assertFalse((self.job_root() / "paper-monitor-proposal.json").exists())
        self.assertFalse(w.pending(self.state))

    def test_interruption_resumes_same_generation_and_accepted_job_without_queue(self):
        original = w.engine.step
        count = 0
        def interrupt(root, job_id):
            nonlocal count
            count += 1
            if count == 3:
                raise RuntimeError("simulated reboot")
            return original(root, job_id)
        with patch.object(w.engine, "step", side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.run_worker()
        self.assertEqual(w.read_engine_meta(self.job_root(), self.job["job_id"])["completed_generations"], 2)
        (self.state / "queue" / self.job["job_id"] / "study.json").unlink()
        self.assertTrue(w.pending(self.state))
        self.assertEqual(self.run_worker()["status"], "SEALED")
        resumed = json.loads((self.job_root() / "report.json").read_bytes())
        other = self.root / "uninterrupted"
        w.atomic_json(other / "queue" / self.job["job_id"] / "study.json", self.job)
        self.run_worker(other)
        expected = json.loads((other / "jobs" / self.job["job_id"] / "report.json").read_bytes())
        self.assertEqual(resumed["generations"], expected["generations"])
        self.assertEqual(resumed["comparisons"], expected["comparisons"])

    def test_atomic_initialization_recovery(self):
        original = os.replace
        def interrupted(source, target):
            if Path(source).is_dir():
                raise RuntimeError("power failure before atomic directory publication")
            original(source, target)
        with patch.object(w.os, "replace", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.run_worker()
        self.assertFalse(self.job_root().exists())
        self.assertEqual(self.run_worker()["status"], "SEALED")

    def test_killed_sqlite_transaction_recovers_without_consuming_generation(self):
        with w.study_adapter(self.job["study"]):
            root = w.prepare_job(self.state, self.job, self.inputs)
        path = w.engine.database_path(root, self.job["job_id"])
        code = "import os,sqlite3,sys; d=sqlite3.connect(sys.argv[1]); d.execute('BEGIN IMMEDIATE'); d.execute(\"UPDATE meta SET payload='corrupt_uncommitted'\"); os._exit(137)"
        result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True)
        self.assertEqual(result.returncode, 137)
        self.assertEqual(w.read_engine_meta(root, self.job["job_id"])["completed_generations"], 0)
        self.assertEqual(self.run_worker()["status"], "SEALED")

    def test_changed_queued_spec_blocks_instead_of_tuning(self):
        with patch.object(w.engine, "step", side_effect=RuntimeError("interrupt")):
            with self.assertRaises(RuntimeError):
                self.run_worker()
        path = self.state / "queue" / self.job["job_id"] / "study.json"
        job = json.loads(path.read_bytes())
        job["study"]["seed"] += 1
        path.write_text(w.canonical(job))
        with self.assertRaises(w.Blocked):
            self.run_worker()
        self.assertFalse(w.pending(self.state))
        self.assertEqual(w.read_engine_meta(self.job_root(), self.job["job_id"])["completed_generations"], 0)

    def test_changed_release_and_input_hash_fail_closed(self):
        source = self.inputs / "synthetic.csv"
        source.write_bytes(self.raw + b"bad")
        with self.assertRaises(w.Blocked):
            self.run_worker()
        self.assertFalse(self.job_root().exists())
        (self.release / FILES[0]).write_bytes(b"tampered")
        with self.assertRaises(w.Blocked):
            w.verify_release(self.release)

    def test_frozen_input_used_on_resume_not_live_production_data(self):
        with patch.object(w.engine, "step", side_effect=RuntimeError("interrupt")):
            with self.assertRaises(RuntimeError):
                self.run_worker()
        (self.inputs / "synthetic.csv").write_bytes(b"production has refreshed")
        self.assertEqual(self.run_worker()["status"], "SEALED")
        self.assertEqual(w.sha(self.job_root() / "input.csv"), self.job["input_sha256"])

    def test_duplicate_study_under_new_id_is_blocked(self):
        self.run_worker()
        duplicate = json.loads(w.canonical(self.job))
        duplicate["job_id"] = duplicate["study"]["experiment_id"] = "renamed_same_study"
        w.atomic_json(self.state / "queue" / duplicate["job_id"] / "study.json", duplicate)
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_worker()
        self.assertFalse((self.state / "jobs" / duplicate["job_id"]).exists())
        self.assertFalse(w.pending(self.state))

    def test_old_rejected_study_cannot_be_requeued_even_if_renamed(self):
        job = json.loads(w.canonical(self.job))
        job["mode"] = "research"
        job["study"] = json.loads(w.engine.STUDY_PATH.read_bytes())
        job["job_id"] = job["study"]["experiment_id"] = "renamed_rejected_history"
        job["input_name"] = "BTCUSDT_1d.csv"
        job["input_sha256"] = job["study"]["input_sha256"]
        with self.assertRaises(w.Blocked):
            w.validate_job(job, self.manifest)

    def test_qualified_only_writes_frozen_monitor_proposal(self):
        with patch.object(w.engine, "backtest", fake_positive):
            self.assertEqual(self.run_worker()["outcome"], "HISTORICAL_QUALIFIED_AWAITING_FORWARD")
        proposal = json.loads((self.job_root() / "paper-monitor-proposal.json").read_bytes())
        self.assertEqual(proposal["status"], "REVIEW_REQUIRED_NOT_INSTALLED")
        self.assertFalse(proposal["orders_allowed"])
        self.assertEqual(len(proposal["candidate"]["sha256"]), 64)

    def test_no_queue_is_idle_and_fixture_not_admitted_as_research(self):
        empty = self.root / "empty"
        self.assertEqual(self.run_worker(empty), {"status": "IDLE"})
        with self.assertRaises(w.Blocked):
            w.run_once(self.release, self.state, self.inputs)

    def test_no_credential_environment_allowed(self):
        with patch.dict(os.environ, {"SUPABASE_SERVICE_ROLE_KEY": "fixture-not-a-secret"}):
            with self.assertRaises(w.Blocked):
                self.run_worker()

    def test_low_disk_pauses_without_claim_or_rewrite(self):
        with patch.object(w.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(10**10, 10**10, 1)):
            with self.assertRaises(w.Paused):
                self.run_worker()
        self.assertFalse(self.job_root().exists())
        self.assertTrue(w.pending(self.state))

    def test_single_worker_lock_and_atomic_artifact(self):
        with w.worker_lock(self.state):
            with self.assertRaises(OSError):
                with w.worker_lock(self.state):
                    pass
        path = self.state / "atomic.json"
        w.atomic_json(path, {"a": 1})
        with self.assertRaises(w.Blocked):
            w.atomic_json(path, {"a": 2})
        self.assertEqual(json.loads(path.read_bytes()), {"a": 1})

    def test_production_paths_and_output_links_refused(self):
        for path in ("/opt/market_regime_v1", "/opt/home_automation", "/etc/default", "C:/market_regime_v1/outputs"):
            with self.assertRaises(w.Blocked):
                w.state_path(path)
        link = self.state / "escape"
        try:
            link.symlink_to(self.inputs, target_is_directory=True)
        except OSError:
            import _winapi
            _winapi.CreateJunction(str(self.inputs), str(link))
        with self.assertRaises(w.Blocked):
            w.safe_path(link / "synthetic.csv")

    def test_gate_prioritizes_production_and_pending_jobs(self):
        service = {"LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead",
                   "Result": "success", "ExecMainExitTimestampMonotonic": "1"}
        timer = {"UnitFileState": "enabled", "ActiveState": "active"}
        self.assertTrue(gate.allowed(service, timer, []))
        for state in ("active", "activating", "deactivating", "failed"):
            self.assertFalse(gate.allowed({**service, "ActiveState": state}, timer, []))
        self.assertFalse(gate.allowed(service, timer, [{"unit": "mrv1-production.service"}]))
        self.assertFalse(gate.allowed({**service, "ExecMainExitTimestampMonotonic": "0"}, timer, []))
        self.assertFalse(gate.allowed(service, {**timer, "UnitFileState": "disabled"}, []))
        worker = {"LoadState": "loaded", "ActiveState": "inactive"}
        self.assertTrue(gate.dispatch_allowed(worker, []))
        for active in ("active", "activating", "deactivating"):
            self.assertFalse(gate.dispatch_allowed({**worker, "ActiveState": active}, []))
        self.assertFalse(gate.dispatch_allowed(worker, [{"unit": "trendatlas-evolution-worker.service"}]))
        self.assertEqual(gate.parse_jobs(""), [])
        self.assertEqual(gate.parse_jobs("123 mrv1-production.service start waiting\n"),
                         [{"unit": "mrv1-production.service"}])
        with self.assertRaises(ValueError):
            gate.parse_jobs("unrecognized output")

    def test_units_have_asymmetric_arbitration_and_security_boundaries(self):
        base = ROOT / "research_os/dev_only/evolution_worker/systemd"
        worker = (base / "trendatlas-evolution-worker.service.in").read_text()
        dispatch = (base / "trendatlas-evolution-dispatch.service.in").read_text()
        timer = (base / "trendatlas-evolution-dispatch.timer").read_text()
        for required in ("RefuseManualStart=yes", "Conflicts=mrv1-production.service",
                         "After=mrv1-production.service", "User=trendatlas-research", "PrivateNetwork=yes",
                         "ProtectSystem=strict", "CPUQuota=20%", "MemoryMax=384M", "Nice=19",
                         "IOSchedulingClass=idle", "KillMode=control-group", "Restart=no", "env -i"):
            self.assertIn(required, worker)
        self.assertNotIn("[Install]", worker)
        self.assertIn("OnSuccessJobMode=ignore-requirements", dispatch)
        self.assertIn("Unit=trendatlas-evolution-dispatch.service", timer)
        self.assertNotIn("Unit=trendatlas-evolution-worker.service", timer)
        self.assertNotIn("LoadCredential", worker + dispatch)
        self.assertNotIn("EnvironmentFile", worker + dispatch)


if __name__ == "__main__":
    unittest.main()
