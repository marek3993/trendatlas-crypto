"""Synthetic-only continuous research lifecycle; no historical Pi search."""
import ast
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from research_os.dev_only.evolution_worker import continuous as c, continuous_engine as e
from research_os.dev_only.evolution_worker import continuous_family as f, runtime as w
from research_os.dev_only.evolution_worker.continuous_fixture import run_fixture
from research_os.dev_only.evolution_worker.resource_guard import continuous_memory_guard as guard
from research_os.dev_only.evolution.backtest import read_bars
from scripts.research.build_evolution_worker_release import FILES, ROOT


class ContinuousTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.release = self.base / "release"
        for name in FILES:
            dest = self.release / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / name).read_bytes())
        identity = {"source_commit": "a" * 40, "files": {n: w.sha(self.release / n) for n in FILES}}
        self.manifest = {**identity, "release_sha256": w.digest(w.canonical(identity).encode())}
        (self.release / "manifest.json").write_text(w.canonical(self.manifest))
        self.state = self.base / "state"
        self.state.mkdir()
        self.root = self.state / "continuous"
        self.source = self.base / "synthetic.csv"
        start = date(2020, 1, 1)
        self.lines = ["date,open,high,low,close,volume"]
        self.lines += [f"{start + timedelta(days=i)},100,101,99,100,1" for i in range(1200)]
        self.source.write_text("\n".join(self.lines) + "\n")
        self.policy = json.loads(c.POLICY.read_bytes())
        self.policy["templates"] = [self.policy["templates"][0], self.policy["templates"][2]]
        self.policy.update(generations=1, population=2, survivors=1, mutations=0,
                           fold_days=10, min_new_closed_days=30)
        self.policy_sha = w.digest(w.canonical(self.policy).encode())
        w.atomic_json(self.root / "authorization.json", {"schema_version": 1,
            "release_sha256": self.manifest["release_sha256"],
            "source_commit": self.manifest["source_commit"],
            "policy_sha256": self.policy_sha, "activated_at": 1})
        for patcher in [patch.object(c, "policy_from_release", return_value=(self.policy, self.policy_sha)),
                        patch.object(c.campaign, "temperature", return_value=50),
                        patch.object(c.campaign, "disk_guard"),
                        patch.dict(os.environ, {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}, clear=True)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_worker(self, **kwargs):
        return c.run(self.release, self.state, source=self.source, check_production=False, **kwargs)

    def cycle_rows(self):
        db = sqlite3.connect(self.root / "ledger.sqlite3")
        try:
            return list(db.execute("SELECT id,fingerprint,template_id,family_id,state,outcome,selection_reason FROM cycles ORDER BY created_at"))
        finally:
            db.close()

    def first_active_seconds(self):
        db = sqlite3.connect(self.root / "ledger.sqlite3")
        try:
            return db.execute("SELECT active_seconds FROM cycles ORDER BY created_at LIMIT 1").fetchone()[0]
        finally:
            db.close()

    def test_two_real_tiny_cycles_transition_without_enqueue_and_seal_once(self):
        self.assertEqual(c.read_status(self.state)["state"], "WAITING_FOR_DISPATCH")
        result = self.run_worker()
        self.assertEqual(result["state"], "WAITING_FOR_NEW_DATA")
        rows = self.cycle_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r[3] for r in rows], ["trend_momentum", "mean_reversion_entry"])
        self.assertEqual(len({r[1] for r in rows}), 2)
        self.assertTrue(all(r[4] == "SEALED" and r[5] == e.REJECT for r in rows))
        self.assertIn("Prior bounded mean-reversion campaign rejected 10/10", rows[0][6])
        self.assertIn("switch trend_momentum to mean_reversion_entry", rows[1][6])
        self.assertEqual(result["family_id"], "mean_reversion_entry")
        self.assertTrue(result["campaign_id"].startswith("input_"))
        self.assertEqual(result["template_id"], "mean_reversion_entry_v1")
        self.assertEqual(result["generation"], 1)
        self.assertEqual(result["evaluated_candidates"], 2)
        self.assertEqual(result["last_reject_reason"], "no_entries")
        self.assertFalse(result["orders_sent"])
        self.assertFalse(result["production_promotion"])
        self.assertFalse(c.ready(self.state, self.manifest, self.release, self.source))
        sealed = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (self.root / "cycles").rglob("*") if p.is_file()}
        self.assertEqual(self.run_worker()["state"], "WAITING_FOR_NEW_DATA")
        self.assertEqual(sealed, {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (self.root / "cycles").rglob("*") if p.is_file()})

    def test_release_fixture_command_runs_restart_and_two_synthetic_cycles(self):
        result = run_fixture(self.release, self.state)
        self.assertTrue(result["passed"])
        self.assertEqual(result["cycles_sealed"], 2)
        self.assertEqual(result["first_periods_before_restart"], 1)
        self.assertEqual(result["first_periods_after_resume"], 23)
        self.assertNotEqual(result["first_fingerprint"], result["second_fingerprint"])

    def test_frozen_five_generation_population_and_adjacent_mutations(self):
        self.policy["templates"] = self.policy["templates"][:1]
        self.policy.update(generations=5, population=10, survivors=6, mutations=4)
        result = self.run_worker()
        self.assertEqual(result["state"], "WAITING_FOR_NEW_DATA")
        rows = self.cycle_rows()
        self.assertEqual(len(rows), 1)
        report = e.report(self.root / "cycles" / rows[0][0])
        self.assertEqual(report["meta"]["completed_generations"], 5)
        self.assertEqual(len(report["generations"]), 5)
        self.assertEqual(report["evaluated_candidates"], 26)
        domains = self.policy["templates"][0]["domains"]
        known = {}
        for generation in report["generations"]:
            self.assertEqual(len(generation["population"]), 10)
            self.assertEqual(len(generation["survivors"]), 6)
            self.assertTrue(all(len(scores) == 4 for scores in generation["scores"].values()))
            if generation["generation"] < 5:
                self.assertEqual(len(generation["mutations"]), 4)
            else:
                self.assertEqual(generation["mutations"], [])
            for mutation in generation["mutations"]:
                parent_genes = known.get(mutation["parent"])
                if parent_genes is None:
                    db = sqlite3.connect(self.root / "cycles" / rows[0][0] / "research.sqlite3")
                    try:
                        parent_genes = json.loads(db.execute("SELECT genes FROM candidates WHERE id=?",
                                                             (mutation["parent"],)).fetchone()[0])
                    finally:
                        db.close()
                changed = [key for key in domains if parent_genes[key] != mutation["genes"][key]]
                self.assertEqual(len(changed), 1)
                key = changed[0]
                self.assertEqual(abs(domains[key].index(parent_genes[key]) -
                                     domains[key].index(mutation["genes"][key])), 1)
                known[mutation["id"]] = mutation["genes"]
        leader = report["meta"]["frozen_candidate"]["sha256"]
        self.assertEqual(leader, report["generations"][-1]["ranking"][0])
        self.assertIn("assessment", report["comparisons"][leader])

    def test_fresh_interpreter_resumes_committed_sqlite_and_starts_next_cycle(self):
        script = ("import json,sys; from research_os.dev_only.evolution_worker.continuous_fixture "
                  "import run_fixture; print(json.dumps(run_fixture(sys.argv[1],sys.argv[2],"
                  "phase=sys.argv[3],fixture_id='fresh_process')))")
        start = subprocess.run([sys.executable, "-c", script, str(self.release), str(self.state), "start"],
                               cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(start.returncode, 0, start.stderr)
        partial = json.loads(start.stdout)
        self.assertEqual(partial["periods_committed"], 1)
        finish = subprocess.run([sys.executable, "-c", script, str(self.release), str(self.state), "resume"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(finish.returncode, 0, finish.stderr)
        outcome = json.loads(finish.stdout)
        self.assertEqual(outcome["cycles_sealed"], 2)
        self.assertNotEqual(outcome["first_fingerprint"], outcome["second_fingerprint"])

    def test_interrupted_evaluation_resumes_same_cycle_without_new_fingerprint(self):
        original = e.step
        calls = 0
        def interrupted(folder, spec, check, progress):
            def crash_after_committed_evaluation():
                nonlocal calls
                progress()
                calls += 1
                if calls == 1:
                    raise SystemExit("simulated power loss")
            return original(folder, spec, check, crash_after_committed_evaluation)
        with patch.object(e, "step", side_effect=interrupted):
            with self.assertRaisesRegex(SystemExit, "simulated power loss"):
                self.run_worker()
        rows = self.cycle_rows()
        self.assertEqual(len(rows), 1)
        root = self.root / "cycles" / rows[0][0]
        self.assertEqual(e.report(root)["period_evaluations"], 1)
        first_spec = json.loads((root / "accepted.json").read_bytes())
        self.assertEqual(self.run_worker()["state"], "WAITING_FOR_NEW_DATA")
        self.assertEqual(len(self.cycle_rows()), 2)
        self.assertEqual(json.loads((root / "accepted.json").read_bytes()), first_spec)
        self.assertEqual(e.report(root)["period_evaluations"], 23)

    def test_production_pause_preserves_active_budget_across_resume(self):
        original = e.step
        paused = False
        def preempt_after_commit(folder, spec, guard, progress):
            def pause_progress():
                nonlocal paused
                progress()
                if not paused:
                    paused = True
                    raise w.Paused("production_preemption")
            return original(folder, spec, guard, pause_progress)
        with patch.object(e, "step", side_effect=preempt_after_commit):
            first = self.run_worker()
        self.assertEqual(first["state"], "PREEMPTED")
        charged = self.first_active_seconds()
        self.assertGreater(charged, 0)
        resumed = self.run_worker()
        self.assertEqual(resumed["state"], "WAITING_FOR_NEW_DATA")
        self.assertGreaterEqual(self.first_active_seconds(), charged)
        first_root = self.root / "cycles" / self.cycle_rows()[0][0]
        audit = json.loads((first_root / "audit.json").read_bytes())
        self.assertGreaterEqual(audit["active_seconds"], charged)
        self.assertEqual(audit["active_budget_seconds"], 7200)

    def test_killed_inflight_evaluation_keeps_conservative_reservation(self):
        with patch.object(f, "backtest", side_effect=SystemExit("simulated hard kill")):
            with self.assertRaisesRegex(SystemExit, "simulated hard kill"):
                self.run_worker()
        reserved = self.first_active_seconds()
        self.assertGreaterEqual(reserved, c.EVALUATION_RESERVATION_SECONDS)
        result = self.run_worker()
        self.assertEqual(result["state"], "WAITING_FOR_NEW_DATA")
        first_root = self.root / "cycles" / self.cycle_rows()[0][0]
        audit = json.loads((first_root / "audit.json").read_bytes())
        self.assertGreaterEqual(audit["active_seconds"], reserved)

    def test_active_budget_guard_rejects_exhaustion(self):
        spec = {"cycle_id": "unused", "cycle_elapsed_seconds": 7200,
                "cycle_disk_bytes": 67108864}
        with patch("research_os.dev_only.evolution_worker.gate.main", return_value=0), \
                patch.object(c.time, "monotonic", return_value=102):
            with self.assertRaises(w.Blocked):
                c.guard(self.state, self.root, spec, 7199, 100)

    def test_crash_between_report_and_seal_reuses_frozen_charge(self):
        original = w.atomic_json
        interrupted = False
        def crash_at_seal(path, value):
            nonlocal interrupted
            if Path(path).name == "SEALED.json" and not interrupted:
                interrupted = True
                raise SystemExit("crash_before_seal")
            return original(path, value)
        with patch.object(w, "atomic_json", side_effect=crash_at_seal):
            with self.assertRaisesRegex(SystemExit, "crash_before_seal"):
                self.run_worker()
        root = self.root / "cycles" / self.cycle_rows()[0][0]
        self.assertTrue((root / "final-charge.json").exists())
        self.assertTrue((root / "report.json").exists())
        frozen = json.loads((root / "final-charge.json").read_bytes())["active_seconds"]
        self.assertEqual(self.run_worker()["state"], "WAITING_FOR_NEW_DATA")
        self.assertEqual(json.loads((root / "audit.json").read_bytes())["active_seconds"], frozen)
        self.assertEqual(self.first_active_seconds(), frozen)

    def test_crash_after_seal_before_ledger_does_not_recharge_cycle(self):
        original = c.seal
        interrupted = False
        def crash_after_seal(folder, cycle, **kwargs):
            nonlocal interrupted
            outcome = original(folder, cycle, **kwargs)
            if not interrupted and (folder / "SEALED.json").exists():
                interrupted = True
                raise SystemExit("crash_after_seal")
            return outcome
        with patch.object(c, "seal", side_effect=crash_after_seal):
            with self.assertRaisesRegex(SystemExit, "crash_after_seal"):
                self.run_worker()
        root = self.root / "cycles" / self.cycle_rows()[0][0]
        frozen = json.loads((root / "audit.json").read_bytes())["active_seconds"]
        self.assertEqual(self.run_worker()["state"], "WAITING_FOR_NEW_DATA")
        self.assertEqual(self.first_active_seconds(), frozen)

    def test_production_preemption_occurs_before_snapshot_or_cycle_creation(self):
        with patch("research_os.dev_only.evolution_worker.gate.main", return_value=1):
            result = c.run(self.release, self.state, source=self.source)
        self.assertEqual(result["state"], "PREEMPTED")
        self.assertEqual(self.cycle_rows(), [])
        self.assertFalse((self.root / "inputs").exists())

    def test_rewrite_or_truncation_never_reopens_exhausted_input(self):
        self.run_worker()
        before = self.cycle_rows()
        old = self.source.read_text().splitlines()
        new_start = date.fromisoformat(old[-1].split(",")[0]) + timedelta(days=1)
        extension = [f"{new_start + timedelta(days=i)},100,101,99,100,1" for i in range(30)]
        self.source.write_text("\n".join(old + extension) + "\n")
        self.assertTrue(c.ready(self.state, self.manifest, self.release, self.source))
        changed = old.copy()
        changed[100] = changed[100].replace(",99,100,", ",99,101,")
        self.source.write_text("\n".join(changed + extension) + "\n")
        result = self.run_worker()
        self.assertEqual(result["state"], "ERROR")
        self.assertIn("rewrote or truncated", result["reason"])
        self.assertFalse(c.ready(self.state, self.manifest, self.release, self.source))
        self.assertTrue((self.root / "error.json").exists())
        self.assertEqual(before, self.cycle_rows())

    def test_malformed_later_source_latches_error_and_dispatcher_stays_idle(self):
        self.run_worker()
        rows = self.cycle_rows()
        self.source.write_bytes(self.source.read_bytes() + b"bad,OHLCV,row\n")
        self.assertTrue(c.ready(self.state, self.manifest, self.release, self.source))
        outcome = self.run_worker()
        self.assertEqual(outcome["state"], "ERROR")
        self.assertFalse(c.ready(self.state, self.manifest, self.release, self.source))
        self.assertEqual(rows, self.cycle_rows())
        self.assertEqual(self.run_worker()["state"], "ERROR")

    def test_error_latch_reconciles_crash_before_status_write(self):
        w.atomic_json(self.root / "status.json", {"mode": "continuous_evolution_v1",
                                              "state": "RUNNING", "cycle_id": "previous"})
        w.atomic_json(self.root / "error.json", {"reason": "source_integrity_failed",
                                             "cycle_id": None, "at": 1})
        visible = c.read_status(self.state)
        self.assertEqual(visible["state"], "ERROR")
        self.assertEqual(visible["reason"], "source_integrity_failed")
        self.assertFalse(c.ready(self.state, self.manifest, self.release, self.source))

    def test_current_utc_bar_is_refused_as_unclosed(self):
        last = date.fromisoformat(self.lines[-1].split(",")[0])
        with patch.object(c, "utc_today", return_value=last):
            with self.assertRaises(ValueError):
                c.source_info(self.source)
        with patch.object(c, "utc_today", return_value=last + timedelta(days=1)):
            self.assertEqual(c.source_info(self.source)[2][-1].day, last.isoformat())

    def test_prior_sealed_tamper_blocks_following_cycle(self):
        self.run_worker()
        rows = self.cycle_rows()
        report = self.root / "cycles" / rows[0][0] / "report.json"
        report.chmod(0o600)
        report.write_bytes(report.read_bytes() + b" ")
        result = self.run_worker()
        self.assertEqual(result["state"], "ERROR")
        self.assertIn("SEALED", result["reason"])
        self.assertFalse(c.ready(self.state, self.manifest, self.release, self.source))

    def test_family_math_uses_previous_close_next_open_costs_and_cap(self):
        template = json.loads(c.POLICY.read_bytes())["templates"][0]
        bars = read_bars(self.source.read_bytes())
        genes = {k: values[0] for k, values in template["domains"].items()}
        start, end = bars[250].day, bars[280].day
        result = f.backtest(bars, template["family_id"], genes, template["domains"], start, end)
        self.assertTrue(all(trade["fill"] == "open" and trade["signal_day"] < trade["day"]
                            for trade in result["trades"]))
        self.assertLessEqual(result["metrics"]["max_opening_exposure"], 0.75)
        with patch.object(f, "decision", return_value={"enter": True, "exit": False, "reason": "test"}):
            entered = f.backtest(bars, template["family_id"], genes, template["domains"], start, end)
        self.assertTrue(entered["trades"])
        self.assertEqual(entered["trades"][0]["day"], start)
        self.assertEqual(entered["trades"][0]["signal_day"], bars[249].day)
        self.assertGreater(entered["metrics"]["cost_paid"], 0)
        self.assertTrue(all(trade["fill"] == "open" for trade in entered["trades"]))
        visible = [bar for bar in bars if bar.day <= end]
        self.assertEqual(f.backtest(bars, template["family_id"], genes, template["domains"], start, end),
                         f.backtest(visible, template["family_id"], genes, template["domains"], start, end))

    def test_research_guard_is_new_release_local_and_recovers_only_unsealed(self):
        text = (ROOT / "research_os/dev_only/evolution_worker/resource_guard/continuous_memory_guard.py").read_text()
        self.assertIn("RELEASE = Path(__file__).absolute().parents[1]", text)
        self.assertNotIn("d534035a216a134cce610f80eec32afb8f0461bd", text)
        state = self.base / "recover"
        active = state / "continuous/cycles/active"
        sealed = state / "continuous/cycles/sealed"
        for path in (active, sealed):
            path.mkdir(parents=True)
            db = sqlite3.connect(path / "research.sqlite3")
            db.execute("CREATE TABLE entries(value TEXT)")
            db.execute("INSERT INTO entries VALUES('committed')")
            db.commit(); db.close()
        (sealed / "SEALED.json").write_text("{}")
        (sealed / "research.sqlite3-journal").write_bytes(b"x" * 1024)
        before = w.sha(sealed / "research.sqlite3")
        self.assertEqual(guard.recover_interrupted_sqlite(state), [])
        self.assertEqual(before, w.sha(sealed / "research.sqlite3"))

    def test_no_execution_network_import_and_unit_resource_boundary(self):
        for name in ("continuous.py", "continuous_engine.py", "continuous_family.py"):
            tree = ast.parse((ROOT / "research_os/dev_only/evolution_worker" / name).read_text())
            imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(any(x in v for x in ("execution", "exchange", "openai", "requests", "socket"))
                                 for v in imports))
        worker = (ROOT / "research_os/dev_only/evolution_worker/systemd/trendatlas-evolution-worker.service.in").read_text()
        dispatch = (ROOT / "research_os/dev_only/evolution_worker/systemd/trendatlas-evolution-dispatch.service.in").read_text()
        for token in ("CPUQuota=20%", "MemoryMax=384M", "MemorySwapMax=0", "Nice=19",
                      "RefuseManualStart=yes", "Conflicts=mrv1-production.service",
                      "ReadOnlyPaths=-/var/lib/trendatlas-research/continuous/authorization.json"):
            self.assertIn(token, worker)
        self.assertIn("BindReadOnlyPaths=/opt/market_regime_v1/data/ohlcv/BTCUSDT_1d.csv", dispatch)


if __name__ == "__main__":
    unittest.main()
