"""Regression tests for the preregistered isolated mean-reversion family."""
import ast
from contextlib import closing
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from research_os.dev_only.mean_reversion import backtest as bt
from research_os.dev_only.mean_reversion import controller as ctl


GENES = {"mean_window": 20, "entry_z": 1.5, "regime_window": 200,
         "range_band": .15, "downtrend_floor": .20, "max_hold": 3,
         "cooldown": 3, "exposure_cap": .75}


def make_bars(closes, opens=None):
    start = date(2017, 1, 1)
    opens = opens or closes
    return [bt.Bar((start + timedelta(days=i)).isoformat(), o, max(o, c) + 1,
                   min(o, c) - 1, c, 1000) for i, (o, c) in enumerate(zip(opens, closes))]


def forced_signal(history, genes):
    return {"mean": 1000, "enter": True}


def fake_backtest(bars, genes, start, end, benchmark=None):
    # Positive, eligible fixture lets all five transactional generations execute.
    value = .1 if benchmark != "cash" else 0.0
    return {"metrics": {"fitness": value, "total_return": value,
                         "annualized_turnover": 1, "turnover_disqualified": False},
            "curve": [{"day": start, "equity": 1}, {"day": end, "equity": 1 + value}],
            "trades": []}


class SimulatorTests(unittest.TestCase):
    def run_fixture(self, bars, genes=None, benchmark=None):
        return bt.backtest(bars, genes or GENES, bars[200].day, bars[-1].day, benchmark=benchmark)

    def test_actual_next_open_entry_exit_and_prices(self):
        bars = make_bars([100] * 199 + [90, 100, 100, 100], [100] * 199 + [90, 91, 105, 100])
        result = self.run_fixture(bars)
        buy, sell = result["trades"]
        self.assertEqual((buy["signal_day"], buy["day"], buy["price"]),
                         (bars[199].day, bars[200].day, 91))
        self.assertEqual((sell["signal_day"], sell["day"], sell["price"], sell["reason"]),
                         (bars[200].day, bars[201].day, 105, "mean_reversion"))
        self.assertTrue(all(t["signal_day"] < t["day"] and t["fill"] == "open" for t in result["trades"]))

    def test_future_close_high_low_and_volume_cannot_change_entry(self):
        bars = make_bars([100] * 199 + [90, 95, 95, 95])
        changed = list(bars)
        changed[200] = replace(changed[200], close=300, high=900, low=1, volume=999999)
        self.assertEqual(self.run_fixture(bars)["trades"][0], self.run_fixture(changed)["trades"][0])
        before = bt.backtest(bars, GENES, bars[200].day, bars[201].day)
        changed[202] = replace(changed[202], open=1, close=1000000)
        self.assertEqual(before, bt.backtest(changed[:200] + bars[200:202] + changed[202:],
                                            GENES, bars[200].day, bars[201].day))

    def test_downtrend_veto_even_when_oversold_and_in_range(self):
        evidence = bt.signal([100] * 199 + [70], {**GENES, "downtrend_floor": .10})
        self.assertTrue(evidence["oversold"])
        self.assertTrue(evidence["range_allowed"])
        self.assertFalse(evidence["regime_allowed"])
        self.assertFalse(evidence["enter"])

    def test_range_filter_independent_of_downtrend(self):
        evidence = bt.signal([100] * 170 + [80] * 29 + [79], {**GENES, "range_band": .05})
        self.assertTrue(evidence["oversold"])
        self.assertTrue(evidence["regime_allowed"])
        self.assertFalse(evidence["range_allowed"])
        self.assertFalse(evidence["enter"])

    def test_zero_variance_does_not_enter_and_200_day_warmup_required(self):
        self.assertFalse(bt.signal([100] * 200, GENES)["enter"])
        with self.assertRaises(ValueError):
            bt.signal([100] * 199, GENES)

    @patch.object(bt, "signal", forced_signal)
    def test_max_hold_counts_entry_close_and_exits_next_open(self):
        bars = make_bars([100] * 210)
        result = self.run_fixture(bars)
        buy, sell = result["trades"][:2]
        self.assertEqual(buy["day"], bars[200].day)
        self.assertEqual((sell["day"], sell["held_closes"], sell["reason"]),
                         (bars[203].day, 3, "max_hold"))

    @patch.object(bt, "signal", forced_signal)
    def test_cooldown_blocks_exact_closed_days_and_same_open_reentry(self):
        bars = make_bars([100] * 225)
        trades = self.run_fixture(bars)["trades"]
        entries = [t["day"] for t in trades if t["side"] == "buy"]
        self.assertEqual(entries, [bars[i].day for i in (200, 207, 214, 221)])
        self.assertEqual(len({t["day"] for t in trades}), len(trades))

    @patch.object(bt, "signal", forced_signal)
    def test_no_averaging_borrowing_and_opening_cap_risk_trim(self):
        bars = make_bars([100] * 200 + [150, 300, 60, 60, 60],
                         [100] * 200 + [100, 200, 50, 60, 60])
        result = self.run_fixture(bars)
        self.assertEqual(sum(t["side"] == "buy" for t in result["trades"]), 1)
        self.assertTrue(any(t["reason"] == "exposure_cap" for t in result["trades"]))
        self.assertTrue(all(r["weight"] <= .75 + 1e-12 and r["cash"] >= 0 for r in result["curve"]))
        self.assertGreater(result["metrics"]["max_close_exposure"], .75)
        sell = next(t for t in result["trades"] if t["reason"] == "max_hold")
        self.assertEqual(sell["held_closes"], 3)
        self.assertTrue(all(t["cost"] == t["notional"] * .0015 for t in result["trades"]))

    @patch.object(bt, "signal", forced_signal)
    def test_costs_both_sides_exact_cash_accounting(self):
        result = self.run_fixture(make_bars([100] * 204))
        notional = .75 / (1 + .75 * .0015)
        self.assertAlmostEqual(result["metrics"]["cost_paid"], 2 * notional * .0015)
        self.assertAlmostEqual(result["metrics"]["total_return"], -2 * notional * .0015)
        self.assertAlmostEqual(result["curve"][0]["weight"], .75)

    def test_boundary_liquidates_at_open_not_last_close_and_btc_costs(self):
        bars = make_bars([100] * 202 + [1000], [100] * 203)
        result = self.run_fixture(bars, benchmark="btc")
        self.assertEqual(result["trades"][-1]["reason"], "fold_boundary")
        self.assertEqual(result["trades"][-1]["price"], 100)
        self.assertEqual(result["curve"][-1]["weight"], 0)
        self.assertAlmostEqual(result["metrics"]["total_return"], (1 - .0015) / (1 + .0015) - 1)
        cash = self.run_fixture(bars, benchmark="cash")
        self.assertEqual(cash["metrics"]["total_return"], 0)
        self.assertEqual(cash["metrics"]["fitness"], 0)
        self.assertEqual(cash["trades"], [])

    @patch.object(bt, "signal", forced_signal)
    def test_annualized_turnover_counts_all_legs_and_disqualifies(self):
        result = self.run_fixture(make_bars([100] * 230))
        expected = sum(t["notional"] / t["equity_before"] for t in result["trades"]) * 365.25 / 30
        self.assertAlmostEqual(result["metrics"]["annualized_turnover"], expected)
        self.assertTrue(result["metrics"]["turnover_disqualified"])
        self.assertFalse(bt.turnover_disqualified(24))
        self.assertTrue(bt.turnover_disqualified(24.0000001))

    def test_fold_restarts_cash_and_does_not_read_later_fold(self):
        bars = make_bars([100] * 199 + [90] + [95] * 30)
        first = bt.backtest(bars, GENES, bars[200].day, bars[210].day)
        changed = bars[:211] + [replace(b, close=10000) for b in bars[211:]]
        self.assertEqual(first, bt.backtest(changed, GENES, bars[200].day, bars[210].day))
        second = bt.backtest(bars, GENES, bars[211].day, bars[-1].day, benchmark="cash")
        self.assertTrue(all(r["equity"] == 1 for r in second["curve"]))


class EvolutionTests(unittest.TestCase):
    def test_adjacent_mutations_one_gene_one_step_globally_unseen(self):
        population = ctl.initial_population(random.Random(20260920))
        self.assertEqual(len(population), 10)
        children = ctl.adjacent_children(list(population)[:6], population, set(population), random.Random(1))
        self.assertEqual(len({c[0] for c in children}), 4)
        for cid, child, parent in children:
            differences = [k for k in child if child[k] != population[parent][k]]
            self.assertEqual(len(differences), 1)
            key = differences[0]
            self.assertEqual(abs(bt.DOMAINS[key].index(child[key]) - bt.DOMAINS[key].index(population[parent][key])), 1)
            self.assertNotIn(cid, population)
            self.assertEqual(cid, bt.candidate_id(child))

    def test_rank_worst_then_median_then_mean_then_hash_and_dq_exclusion(self):
        scores = {"a": [0, 5, 5, 90], "b": [0, 6, 6, 7], "c": [0, 6, 6, 8],
                  "d": [1, 1, 1, 1], "e": [99] * 4, "f": [0, 6, 6, 8]}
        self.assertEqual(ctl.rank_candidates(scores, {"e"}), ["d", "c", "f", "b", "a"])

    def test_qualification_rejects_any_nonpositive_fold_or_continuous(self):
        positive = {"total_return": .01, "fitness": .001, "turnover_disqualified": False}
        self.assertEqual(ctl.qualification({"fold": positive, "continuous": positive})[0], ctl.QUALIFIED)
        for key, value in (("total_return", 0), ("fitness", -.1), ("turnover_disqualified", True)):
            self.assertEqual(ctl.qualification({"fold": positive,
                "continuous": {**positive, key: value}})[0], ctl.REJECT)

    def test_preregistered_folds_domains_and_chronology(self):
        study = ctl.load_study()
        bars = make_bars([100] * 3600)
        ctl.validate_study(study, bars)
        for alteration in ("overlap", "gap", "budget", "domain"):
            changed = json.loads(json.dumps(study))
            if alteration == "overlap":
                changed["folds"][1]["start"] = changed["folds"][0]["end"]
            elif alteration == "gap":
                changed["folds"][1]["start"] = "2020-01-02"
            elif alteration == "budget":
                changed["generations"] = 6
            else:
                changed["domains"]["mean_window"].append(40)
            with self.assertRaises(ValueError):
                ctl.validate_study(changed, bars)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.study = ctl.load_study()
        bars = make_bars([100] * 440)
        self.study["folds"] = [{"id": f"fold_{i}", "start": bars[200 + i * 30].day,
                                "end": bars[229 + i * 30].day} for i in range(8)]
        self.input = self.root / "history.csv"
        text = "date,open,high,low,close,volume\n" + "".join(
            f"{b.day},{b.open},{b.high},{b.low},{b.close},{b.volume}\n" for b in bars)
        self.input.write_text(text, encoding="utf-8")
        self.study["input_sha256"] = hashlib.sha256(self.input.read_bytes()).hexdigest()
        self.run_id = self.study["experiment_id"]
        self.loader = patch.object(ctl, "load_study", return_value=self.study)
        self.loader.start()
        self.addCleanup(self.loader.stop)
        self.addCleanup(self.temp.cleanup)

    def initialize(self, root=None):
        return ctl.initialize(root or self.root, self.run_id, self.input)

    @patch.object(ctl, "backtest", fake_backtest)
    def test_deterministic_resume_atomic_rollback_and_five_generation_seal(self):
        self.initialize()
        other = self.root / "other"
        self.initialize(other)
        calls = 0
        def fail_mid_generation(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise RuntimeError("simulated interruption")
            return fake_backtest(*args, **kwargs)
        with patch.object(ctl, "backtest", side_effect=fail_mid_generation):
            with self.assertRaises(RuntimeError):
                ctl.step(self.root, self.run_id)
        with closing(ctl.connect(self.root, self.run_id)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0], 0)
            self.assertEqual(ctl.metadata(db)["completed_generations"], 0)
        for _ in range(5):
            ctl.step(self.root, self.run_id)
            ctl.step(other, self.run_id)
        self.assertEqual(ctl.report(self.root, self.run_id), ctl.report(other, self.run_id))
        result = ctl.report(self.root, self.run_id)
        self.assertEqual(result["evaluated_candidates"], 26)
        self.assertEqual(result["candidate_count"], 30)
        self.assertEqual(result["meta"]["outcome"], ctl.QUALIFIED)
        for g in result["generations"]:
            self.assertEqual((len(g["population"]), len(g["survivors"]), len(g["mutations"])), (10, 6, 4))
        dbpath = ctl.database_path(self.root, self.run_id)
        before = dbpath.read_bytes()
        with self.assertRaises(ValueError):
            ctl.step(self.root, self.run_id)
        self.assertEqual(before, dbpath.read_bytes())
        report_path = ctl.export_report(self.root, self.run_id)
        report_before = report_path.read_bytes()
        with self.assertRaises(FileExistsError):
            ctl.export_report(self.root, self.run_id)
        self.assertEqual(report_before, report_path.read_bytes())

    def test_turnover_disqualified_cannot_survive_or_be_parent(self):
        self.initialize()
        def disqualify(*args, **kwargs):
            result = fake_backtest(*args, **kwargs)
            result["metrics"]["turnover_disqualified"] = True
            result["metrics"]["annualized_turnover"] = 25
            return result
        with patch.object(ctl, "backtest", side_effect=disqualify):
            result = ctl.step(self.root, self.run_id)
        self.assertEqual(result["meta"]["outcome"], ctl.REJECT)
        self.assertEqual(result["meta"]["completed_generations"], 1)
        self.assertEqual(result["generation"]["survivors"], [])
        self.assertEqual(result["generation"]["mutations"], [])
        with self.assertRaises(ValueError):
            ctl.step(self.root, self.run_id)

    def test_hash_guard_and_exclusive_init(self):
        self.initialize()
        with self.assertRaises(FileExistsError):
            self.initialize()
        with patch.object(ctl, "code_hash", return_value="changed"):
            with self.assertRaises(ValueError):
                ctl.step(self.root, self.run_id)
        self.input.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.initialize(self.root / "new")

    def test_production_paths_old_sealed_files_and_input_unchanged(self):
        sentinels = [self.root / p for p in (
            "outputs/production/sentinel", "outputs/execution/authority/snapshot.json",
            "outputs/research_os/dev_only/evolution/old/research.sqlite3", "data/snapshot.csv")]
        for path in sentinels:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original sealed or production bytes")
        originals = {p: p.read_bytes() for p in sentinels + [self.input]}
        self.initialize()
        with patch.object(ctl, "backtest", fake_backtest):
            for _ in range(5):
                ctl.step(self.root, self.run_id)
        ctl.export_report(self.root, self.run_id)
        self.assertEqual(originals, {p: p.read_bytes() for p in originals})
        for bad in ("../production", "../../data", "/opt/market_regime_v1", "C:\\production", "a/b"):
            with self.assertRaises(ValueError):
                ctl.database_path(self.root, bad)

    def test_output_junction_or_symlink_and_hard_link_rejected(self):
        destination = self.root / "authority"
        destination.mkdir()
        output = self.root / ctl.OUTPUT
        output.parent.mkdir(parents=True)
        try:
            output.symlink_to(destination, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            import _winapi
            _winapi.CreateJunction(str(destination), str(output))
        with self.assertRaises(ValueError):
            ctl.database_path(self.root, self.run_id)
        clean = self.root / "clean"
        path = ctl.database_path(clean, self.run_id)
        path.parent.mkdir(parents=True)
        target = clean / "authority.db"
        target.write_bytes(b"protected")
        os.link(target, path)
        with self.assertRaises(ValueError):
            ctl.database_path(clean, self.run_id)
        self.assertEqual(target.read_bytes(), b"protected")

    def test_no_production_exchange_subprocess_or_network_imports(self):
        files = list(Path(ctl.__file__).parent.glob("*.py")) + [Path(bt.__file__).parents[1] / "evolution/backtest.py"]
        for file in files:
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    self.assertFalse(any(word in name for word in (
                        "execution", "exchange", "ccxt", "subprocess", "requests", "socket", "urllib", "paramiko")), name)


if __name__ == "__main__":
    unittest.main()
