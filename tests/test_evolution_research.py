from datetime import date, timedelta
import csv
import io
import json
import hashlib
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research_os.dev_only.evolution import backtest as engine
from research_os.dev_only.evolution import controller as ctl
from research_os.dev_only.evolution.protocol import RULE, comparison, stability_decision


GENES = {"fast": 5, "slow": 60, "momentum": 10, "threshold": 0.0, "vol_target": 0.75, "cap": 1.0}


def fixture_bytes(days=800):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["date", "open", "high", "low", "close", "volume"])
    previous = 100.0
    for n in range(days):
        day = date(2020, 1, 1) + timedelta(days=n)
        opening = previous * (1 + 0.001 * math.sin(n / 7))
        close = opening * (1.001 + 0.012 * math.sin(n / 15))
        writer.writerow([day.isoformat(), opening, max(opening, close) * 1.01, min(opening, close) * 0.99, close, 1000])
        previous = close
    return stream.getvalue().encode()


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.bars = engine.read_bars(fixture_bytes())

    def test_same_day_close_cannot_change_open_weight(self):
        start, end = "2021-01-01", "2021-02-01"
        original = engine.backtest(self.bars, GENES, start, end, 15)
        index = next(i for i, row in enumerate(original["curve"]) if row["weight"] > 0)
        execution_day = original["curve"][index]["day"]
        changed = [engine.Bar(b.day, b.open, b.high * 3, b.low, b.close * 2, b.volume) if b.day == execution_day else b for b in self.bars]
        variant = engine.backtest(changed, GENES, start, end, 15)
        self.assertEqual(original["curve"][index]["weight"], variant["curve"][index]["weight"])
        self.assertNotEqual(original["curve"][index]["equity"], variant["curve"][index]["equity"])

    def test_future_bars_cannot_change_training_results(self):
        kwargs = (GENES, "2021-01-01", "2021-02-01", 15)
        first = engine.backtest(self.bars, *kwargs)
        changed = [b if b.day <= "2021-02-01" else engine.Bar(b.day, 1, 2, 0.5, 1, 1) for b in self.bars]
        self.assertEqual(first, engine.backtest(changed, *kwargs))

    def test_known_buy_hold_cost_and_overnight_return(self):
        # Buy at first open, carry overnight, sell at last close.
        result = engine.backtest(self.bars, GENES, "2021-01-01", "2021-02-01", 15, benchmark=True)
        opening = next(b.open for b in self.bars if b.day == "2021-01-01")
        closing = next(b.close for b in self.bars if b.day == "2021-02-01")
        expected = closing / opening / 1.0015 * 0.9985
        self.assertAlmostEqual(result["curve"][-1]["equity"], expected, places=12)
        self.assertEqual(result["metrics"]["trade_count"], 2)
        self.assertGreater(result["metrics"]["cost_paid"], 0)

    def test_costs_reduce_flat_market_equity(self):
        flat = [engine.Bar(b.day, 100, 100, 100, 100, 10) for b in self.bars]
        result = engine.backtest(flat, GENES, "2021-01-01", "2021-02-01", 15, benchmark=True)
        self.assertAlmostEqual(result["metrics"]["total_return"], 0.9985 / 1.0015 - 1)
        self.assertLess(result["metrics"]["max_drawdown"], 0)

    def test_reject_bad_dates_nan_ranges_and_open_day(self):
        raw = fixture_bytes().decode().splitlines()
        variants = ["\n".join(raw[:10] + raw[11:]), "\n".join(raw[:10] + [raw[9]] + raw[10:]),
                    "\n".join([raw[0], "2020-01-01,nan,120,90,100,1"]),
                    "\n".join([raw[0], "2020-01-01,100,90,95,100,1"])]
        for value in variants:
            with self.subTest(value=value[:90]), self.assertRaises(ValueError):
                engine.read_bars(value.encode())
        with self.assertRaises(ValueError):
            engine.read_bars(fixture_bytes(), today=date(2020, 1, 2))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / "input.csv"
        self.input.write_bytes(fixture_bytes())
        self.kwargs = dict(train_start="2020-08-01", train_end="2020-12-31", validation_end="2021-06-30", holdout_end="2022-01-31", generations=2)

    def init(self, run="test"):
        return ctl.initialize(self.root, run, self.input, **self.kwargs)

    def protocol(self, run="test"):
        return {
            "protocol_version": "cash_stability_v2", "experiment_id": run,
            "input_sha256": hashlib.sha256(self.input.read_bytes()).hexdigest(),
            **self.kwargs, "seed": 20260920, "cost_bps": 15.0,
            "control_windows": [
                {"id": "control_july", "start": "2021-07-01", "end": "2021-07-31"},
                {"id": "control_august", "start": "2021-08-01", "end": "2021-08-31"},
                {"id": "control_september", "start": "2021-09-01", "end": "2021-09-30"},
            ],
            "exploratory": {"id": "seen_exploratory", "start": "2021-10-01", "end": "2022-01-31",
                            "already_seen": True, "evidence_role": "exploratory_only"},
            "decision_rule": RULE, "iml_required": False, "promotion_allowed": False,
        }

    def test_chronological_protocol_persists_comparisons_without_selection_leak(self):
        spec = self.protocol()
        ctl.initialize(self.root, "test", self.input, **self.kwargs, evaluation_protocol=spec)
        spec["exploratory"]["already_seen"] = False
        real = ctl.backtest
        def selection_only(bars, *args, **kwargs):
            self.assertLessEqual(bars[-1].day, "2021-06-30")
            return real(bars, *args, **kwargs)
        with patch.object(ctl, "backtest", side_effect=selection_only):
            ctl.evolve(self.root, "test")
            ctl.evolve(self.root, "test")
        with self.assertRaises(ValueError):
            ctl.evolve(self.root, "test")
        champion = ctl.status(self.root, "test")["metadata"]["champion"]
        result = ctl.finalize(self.root, "test")
        self.assertEqual(result["champion"], champion)
        self.assertEqual(len(result["chronological_controls"]), 3)
        self.assertTrue(result["seen_exploratory"]["already_seen"])
        self.assertEqual(result["seen_exploratory"]["evidence_role"], "exploratory_only")
        self.assertFalse(result["research_decision"]["generation_extension_allowed"])
        db = ctl.connect(self.root, "test")
        try:
            for window in [*result["chronological_controls"], result["continuous_controls"], result["seen_exploratory"]]:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM evaluations WHERE split=?", (window["id"],)).fetchone()[0], 3)
                cash = db.execute("SELECT MIN(equity),MAX(equity) FROM curves WHERE split=? AND candidate='benchmark_cash'", (window["id"],)).fetchone()
                self.assertEqual(cash, (1.0, 1.0))
        finally:
            db.close()

    def test_protocol_rejects_overlap_missing_disclosure_or_changed_budget(self):
        for case in ("overlap", "unseen", "budget", "input"):
            spec = self.protocol()
            if case == "overlap":
                spec["control_windows"][0]["start"] = "2021-06-01"
            elif case == "unseen":
                spec["exploratory"]["already_seen"] = False
            elif case == "budget":
                spec["generations"] += 1
            else:
                spec["input_sha256"] = "wrong"
            with self.subTest(case=case), self.assertRaises(ValueError):
                ctl.initialize(self.root, "test", self.input, **self.kwargs, evaluation_protocol=spec)
            self.assertFalse(ctl.database_path(self.root, "test").exists())

    def test_cash_stability_rejects_risky_return_and_one_failed_window(self):
        cash = {"total_return": 0.0, "fitness": 0.0}
        btc = {"total_return": -0.3, "fitness": -0.5}
        poor = comparison({"total_return": 0.02, "fitness": -0.4}, cash, btc)
        good = comparison({"total_return": 0.1, "fitness": 0.05}, cash, btc)
        self.assertEqual(poor["status"], "REJECT")
        self.assertGreater(poor["return_delta_vs_btc"], 0)
        self.assertEqual(stability_decision([good, poor, good], good, good)["status"], "REJECT")
        self.assertEqual(stability_decision([good] * 3, good, poor)["status"], "REJECT")
        self.assertEqual(stability_decision([good] * 3, good, good)["status"], "PASS")

    def test_new_protocol_run_does_not_modify_prior_sealed_artifacts(self):
        self.init("old")
        ctl.evolve(self.root, "old")
        ctl.evolve(self.root, "old")
        ctl.finalize(self.root, "old")
        ctl.export_report(self.root, "old")
        old_files = list(ctl.database_path(self.root, "old").parent.iterdir())
        hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in old_files}
        ctl.initialize(self.root, "test", self.input, **self.kwargs, evaluation_protocol=self.protocol())
        ctl.evolve(self.root, "test")
        ctl.evolve(self.root, "test")
        ctl.finalize(self.root, "test")
        ctl.export_report(self.root, "test")
        self.assertEqual(hashes, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in old_files})

    def test_late_chronological_failure_rolls_back_all_final_evaluations(self):
        ctl.initialize(self.root, "test", self.input, **self.kwargs, evaluation_protocol=self.protocol())
        ctl.evolve(self.root, "test")
        ctl.evolve(self.root, "test")
        before = ctl.status(self.root, "test")["evaluation_count"]
        real = ctl.backtest
        def fail_last(bars, genes, start, end, costs, **kwargs):
            if start == "2021-10-01":
                raise RuntimeError("interrupted exploratory evaluation")
            return real(bars, genes, start, end, costs, **kwargs)
        with patch.object(ctl, "backtest", side_effect=fail_last), self.assertRaises(RuntimeError):
            ctl.finalize(self.root, "test")
        state = ctl.status(self.root, "test")
        self.assertEqual(state["evaluation_count"], before)
        self.assertEqual(state["metadata"]["state"], "FROZEN")
        self.assertIsNone(state["final_test"])

    def test_population_survival_mutation_lineage_and_persistence(self):
        self.init()
        result = ctl.evolve(self.root, "test")
        self.assertEqual((len(result["scores"]), len(result["survivors"]), len(result["mutations"])), (10, 6, 4))
        self.assertFalse(set(result["mutations"]) & set(result["scores"]))
        db = ctl.connect(self.root, "test")
        with db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM populations WHERE generation=1").fetchone()[0], 10)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0], 30)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM curves").fetchone()[0], 0)
            self.assertGreater(db.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)
            for cid in result["mutations"]:
                child, parent = db.execute("SELECT genes,parent FROM candidates WHERE id=?", (cid,)).fetchone()
                original = json.loads(db.execute("SELECT genes FROM candidates WHERE id=?", (parent,)).fetchone()[0])
                self.assertIn(parent, result["survivors"])
                decoded = json.loads(child)
                changed = [key for key, value in decoded.items() if value != original[key]]
                self.assertEqual(len(changed), 1)
                key = changed[0]
                domain = engine.DOMAINS[key]
                self.assertEqual(abs(domain.index(decoded[key]) - domain.index(original[key])), 1)
        db.close()
        self.assertEqual(ctl.status(self.root, "test")["metadata"]["completed_generations"], 1)

    def test_holdout_inaccessible_until_frozen_and_sealed_afterwards(self):
        self.init()
        with self.assertRaises(ValueError):
            ctl.finalize(self.root, "test")
        real_backtest = ctl.backtest
        def no_holdout(bars, *args, **kwargs):
            self.assertLessEqual(max(b.day for b in bars), "2021-06-30")
            return real_backtest(bars, *args, **kwargs)
        with patch.object(ctl, "backtest", side_effect=no_holdout):
            ctl.evolve(self.root, "test")
            ctl.evolve(self.root, "test")
        before = ctl.status(self.root, "test")
        self.assertIsNone(before["final_test"])
        champion = before["metadata"]["champion"]
        result = ctl.finalize(self.root, "test")
        self.assertEqual(result["champion"], champion)
        self.assertEqual(result["start"], "2021-07-01")
        self.assertEqual(result["cash"]["total_return"], 0.0)
        self.assertEqual(result["cash"]["max_drawdown"], 0.0)
        expected = (
            "PASS"
            if result["candidate"]["total_return"] > 0
            and result["candidate"]["fitness"] > 0
            else "REJECT"
        )
        self.assertEqual(result["research_decision"]["status"], expected)
        self.assertEqual(ctl.status(self.root, "test")["metadata"]["state"], "SEALED")
        for action in (ctl.evolve, ctl.finalize):
            with self.assertRaises(ValueError):
                action(self.root, "test")

    def test_interruption_rolls_back_generation_and_resume_is_deterministic(self):
        self.init()
        self.init("reference")
        real_backtest = ctl.backtest
        calls = 0
        def interrupt(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("simulated interruption")
            return real_backtest(*args, **kwargs)
        with patch.object(ctl, "backtest", side_effect=interrupt), self.assertRaises(RuntimeError):
            ctl.evolve(self.root, "test")
        self.assertEqual(ctl.status(self.root, "test")["evaluation_count"], 0)
        self.assertEqual(ctl.evolve(self.root, "test"), ctl.evolve(self.root, "reference"))

    def test_final_test_interruption_rolls_back_without_consuming_holdout(self):
        self.init()
        ctl.evolve(self.root, "test")
        ctl.evolve(self.root, "test")
        before = ctl.status(self.root, "test")["evaluation_count"]
        real_backtest = ctl.backtest
        def fail_baseline(*args, **kwargs):
            if kwargs.get("benchmark"):
                raise RuntimeError("interrupted final test")
            return real_backtest(*args, **kwargs)
        with patch.object(ctl, "backtest", side_effect=fail_baseline), self.assertRaises(RuntimeError):
            ctl.finalize(self.root, "test")
        self.assertEqual(ctl.status(self.root, "test")["evaluation_count"], before)
        self.assertIsNone(ctl.status(self.root, "test")["final_test"])
        ctl.finalize(self.root, "test")

    def test_frozen_input_and_code_guard_and_duplicate_init(self):
        self.init()
        self.input.write_text("changed input")
        ctl.evolve(self.root, "test")  # Uses the persisted input, not the modified CSV.
        with patch.object(ctl, "code_hash", return_value="changed"), self.assertRaises(ValueError):
            ctl.evolve(self.root, "test")
        self.input.write_bytes(fixture_bytes())
        with self.assertRaises(FileExistsError):
            self.init()

    def test_bad_splits_and_output_traversal(self):
        for run in ("../production", "/tmp/test", "a/b"):
            with self.assertRaises(ValueError):
                self.init(run)
        self.kwargs["validation_end"] = "2020-12-31"
        with self.assertRaises(ValueError):
            self.init()

    def test_ranking_prefers_worst_fold_then_mean(self):
        scores = {
            "spike": (1.0, -0.20),
            "stable": (0.05, 0.05),
            "tie_low_mean": (0.05, 0.06),
        }
        self.assertEqual(
            ctl.rank_candidates(scores),
            ["tie_low_mean", "stable", "spike"],
        )

    def test_time_budget_rolls_back(self):
        self.init()
        with patch.object(ctl, "check_deadline", side_effect=TimeoutError), self.assertRaises(TimeoutError):
            ctl.evolve(self.root, "test")
        self.assertEqual(ctl.status(self.root, "test")["evaluation_count"], 0)

    def test_research_writes_preserve_production_sentinels_and_export(self):
        protected = [self.root / name for name in ("outputs/production/snapshot.json", "outputs/execution/authority/success.json", "source_of_truth/project_truth.json", "data/ohlcv/BTC.csv")]
        for path in protected:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("production sentinel")
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
        self.init()
        ctl.evolve(self.root, "test")
        report = ctl.export_report(self.root, "test")
        payload = json.loads(Path(report["report"]).read_text())
        self.assertIsNone(payload["final_test"])
        self.assertTrue(all(row["split"] != "final_test" for row in payload["evaluations"]))
        ctl.evolve(self.root, "test")
        ctl.finalize(self.root, "test")
        report = ctl.export_report(self.root, "test")
        self.assertEqual(report["state"], "SEALED")
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected})

    def test_changed_holdout_does_not_change_any_selection(self):
        self.init()
        rows = list(csv.reader(io.StringIO(fixture_bytes().decode())))
        for row in rows[1:]:
            if row[0] > "2021-06-30":
                row[1:5] = [str(float(value) * 10) for value in row[1:5]]
        stream = io.StringIO()
        csv.writer(stream).writerows(rows)
        self.input.write_text(stream.getvalue())
        self.init("different_final_test")
        for _ in range(2):
            self.assertEqual(ctl.evolve(self.root, "test"), ctl.evolve(self.root, "different_final_test"))

    def test_symlink_escape_is_rejected(self):
        destination = self.root / "production"
        destination.mkdir()
        link = self.root / "outputs"
        try:
            link.symlink_to(destination, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            # Junctions need no Windows symlink privilege and are also escapes.
            import _winapi
            _winapi.CreateJunction(str(destination), str(link))
        with self.assertRaises(ValueError):
            self.init()


if __name__ == "__main__":
    unittest.main()
