import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import research_objectives as research


def metrics(cagr=1.5, drawdown=0.25):
    return {
        "cagr": cagr, "max_drawdown": drawdown, "calmar": cagr / drawdown,
        "sharpe": 1.5, "profitable_fold_fraction": 0.75,
        "worst_fold_return": -0.35, "fold_returns": [0.2, 0.3, 0.4, -0.35],
        "asset_log_growth_share": 0.35, "trade_log_growth_share": 0.15,
        "turnover": 10.0, "cost_drag": 0.05, "parameter_stability": 0.9,
        "delayed_entry_cagr": 0.01, "double_cost_cagr": 1.0,
        "without_best_day_cagr": 1.0, "without_top_three_trades_cagr": 0.8,
        "max_realized_exposure": 1.25,
    }


class ResearchObjectivesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.contract = research.load_contract()
        self.proof = self.root / "synthetic_test_evidence.txt"
        self.proof.write_text("Synthetic gate fixture; never a market result.\n", encoding="utf-8")
        self.candidate = {
            "id": "synthetic", "mode": "aggressive", "exposure_cap": 1.25, "nominee_categories": ["A", "C"],
            "development": metrics(), "oos": metrics(), "sealed": metrics(),
            "binding": {"candidate_id": "synthetic", "input_sha256": "1" * 64,
                        "code_sha256": "2" * 64, "parameters_sha256": "3" * 64,
                        "contract_sha256": research.contract_sha256()},
        }
        self.candidate["binding"]["evaluation_sha256"] = research.evaluation_sha256(self.candidate)
        required = self.contract["required_audits"] + self.contract["extended_audit_checks"]
        required += ["sealed_evaluation", "selection_frozen_before_seal"]
        self.candidate["audits"] = {name: self.report() for name in required}

    def report(self):
        return {"passed": True, "binding": copy.deepcopy(self.candidate["binding"]),
                "artifacts": [{"path": self.proof.name,
                               "sha256": hashlib.sha256(self.proof.read_bytes()).hexdigest()}]}

    def assess(self):
        return research.assess(self.candidate, self.root)

    def rebind_fixture(self):
        self.candidate["binding"]["evaluation_sha256"] = research.evaluation_sha256(self.candidate)
        for report in self.candidate["audits"].values():
            report["binding"] = copy.deepcopy(self.candidate["binding"])

    def test_user_contract_targets_and_separate_modes(self):
        self.assertEqual(self.contract["targets"]["oos_cagr_range"], [1.5, 2.0])
        self.assertFalse(self.contract["targets"]["conservative_reference_is_goal"])
        self.assertEqual(self.contract["modes"]["robust"]["exposure_caps"], [1.25])
        self.assertEqual(self.contract["modes"]["aggressive"]["exposure_caps"], [1.25, 1.5, 2.0, 2.5, 3.0])
        self.assertIsNone(self.contract["modes"]["robust"]["cagr_floor"])
        self.assertEqual(self.contract["targets"]["drawdown_target"], 0.2)
        self.assertEqual(self.contract["targets"]["drawdown_acceptable"], 0.3)
        self.assertFalse(self.contract["automatic_deployment_allowed"])

    def test_exact_high_return_thresholds_pass_with_bound_evidence(self):
        self.assertTrue(self.assess()["high_return_gates_passed"])
        for part in ("oos", "sealed"):
            self.candidate[part]["max_drawdown"] = 0.35
            self.candidate[part]["calmar"] = 1.5 / 0.35
        self.rebind_fixture()
        self.assertTrue(self.assess()["high_return_gates_passed"])
        self.assertFalse(self.assess()["production_promotion_allowed"])

    def test_every_high_return_threshold_fails_independently(self):
        bad = {"cagr": 1.4999, "max_drawdown": 0.3501, "sharpe": 1.4999,
               "calmar": 3.9999, "without_best_day_cagr": 0.9999,
               "without_top_three_trades_cagr": 0.7999, "double_cost_cagr": 0.9999,
               "delayed_entry_cagr": 0.0, "asset_log_growth_share": 0.3501,
               "trade_log_growth_share": 0.1501}
        for part in ("oos", "sealed"):
            for key, value in bad.items():
                with self.subTest(part=part, key=key):
                    candidate = copy.deepcopy(self.candidate)
                    candidate[part][key] = value
                    result = research.assess(candidate, self.root)
                    self.assertFalse(result["high_return_gates_passed"])
                    self.assertIn(key, result["high_return_failures"][part])

    def test_robust_lower_return_is_not_rejected_for_missing_150_percent(self):
        self.candidate["mode"] = "robust"
        for part in ("development", "oos", "sealed"):
            self.candidate[part] = metrics(0.32, 0.2)
        self.rebind_fixture()
        result = self.assess()
        self.assertTrue(result["robust_candidate_passed"])
        self.assertFalse(result["high_return_gates_passed"])
        self.candidate["sealed"]["max_drawdown"] = 0.2501
        self.assertFalse(self.assess()["robust_candidate_passed"])

    def test_180_percent_with_70_percent_drawdown_cannot_beat_feasible_150(self):
        bad = copy.deepcopy(self.candidate)
        bad["id"] = "bad"
        bad["development"] = metrics(1.8, 0.7)
        front = research.pareto_front([bad, self.candidate], mode="aggressive", exposure_cap=1.25)
        self.assertEqual(front, ["synthetic"])

    def test_pareto_retains_real_tradeoff_and_removes_dominated_candidate(self):
        lower_turnover = copy.deepcopy(self.candidate)
        lower_turnover["id"] = "lower_turnover"
        lower_turnover["development"] = metrics(1.4, 0.25)
        lower_turnover["development"]["turnover"] = 5
        dominated = copy.deepcopy(self.candidate)
        dominated["id"] = "dominated"
        dominated["development"]["turnover"] = 11
        front = research.pareto_front([dominated, lower_turnover, self.candidate], mode="aggressive", exposure_cap=1.25)
        self.assertEqual(front, ["lower_turnover", "synthetic"])

    def test_mode_and_exposure_populations_are_separate(self):
        robust = copy.deepcopy(self.candidate)
        robust.update(id="robust", mode="robust")
        high = copy.deepcopy(self.candidate)
        high.update(id="high", exposure_cap=3.0)
        pool = [self.candidate, robust, high]
        self.assertEqual(research.pareto_front(pool, mode="robust", exposure_cap=1.25), ["robust"])
        self.assertEqual(research.pareto_front(pool, mode="aggressive", exposure_cap=3.0), ["high"])
        with self.assertRaises(ValueError):
            research.pareto_front(pool, mode="robust", exposure_cap=3.0)

    def test_sealed_or_oos_results_cannot_change_development_selection(self):
        before = research.pareto_front([self.candidate], mode="aggressive", exposure_cap=1.25)
        self.candidate["sealed"] = metrics(100, 0.9)
        self.candidate["oos"] = metrics(-0.9, 0.9)
        self.assertEqual(before, research.pareto_front([self.candidate], mode="aggressive", exposure_cap=1.25))

    def test_missing_seal_or_selection_freeze_blocks_finalist(self):
        for field in ("sealed_evaluation", "selection_frozen_before_seal"):
            candidate = copy.deepcopy(self.candidate)
            del candidate["audits"][field]
            self.assertFalse(research.assess(candidate, self.root)["feasible_frozen_candidate"])
        del self.candidate["sealed"]
        self.assertFalse(self.assess()["high_return_gates_passed"])

    def test_actual_notional_cap_cannot_be_replaced_by_exchange_leverage(self):
        self.candidate["exchange_leverage"] = 10
        self.assertTrue(self.assess()["feasible_frozen_candidate"])
        self.candidate["oos"]["max_realized_exposure"] = 10
        self.assertIn("account_exposure_cap_exceeded", self.assess()["oos_errors"])
        self.candidate["exposure_cap"] = 10
        self.assertIn("invalid_exposure_cap", self.assess()["oos_errors"])

    def test_nan_missing_infinite_boolean_and_negative_drawdown_fail_closed(self):
        for value in (None, float("nan"), float("inf"), True, -0.25):
            with self.subTest(value=value):
                self.candidate["oos"]["max_drawdown"] = value
                self.assertFalse(self.assess()["feasible_frozen_candidate"])

    def test_fold_thresholds_zero_returns_and_summary_reconciliation(self):
        self.candidate["oos"].update(fold_returns=[0.1, 0.2, 0, -0.1],
                                     profitable_fold_fraction=0.5, worst_fold_return=-0.1)
        self.assertIn("profitable_fold_fraction", self.assess()["high_return_failures"]["oos"])
        self.candidate["oos"]["profitable_fold_fraction"] = 0.75
        self.assertIn("fold_summary_not_reconciled", self.assess()["oos_errors"])
        self.candidate["oos"].update(fold_returns=[0.1, 0.2, 0.1, -0.36], worst_fold_return=-0.36)
        self.assertIn("worst_fold_return", self.assess()["high_return_failures"]["oos"])

    def test_all_scientific_audits_are_required(self):
        for name in self.candidate["audits"]:
            with self.subTest(name=name):
                candidate = copy.deepcopy(self.candidate)
                candidate["audits"][name]["passed"] = False
                result = research.assess(candidate, self.root)
                self.assertFalse(result["feasible_frozen_candidate"])
                self.assertIn(name, result["missing_or_failed_audits"])

    def test_high_cagr_automatically_invokes_extended_runner_before_acceptance(self):
        calls = []
        def runner(candidate, checks):
            calls.append((candidate["id"], checks))
            return {name: self.report() for name in checks}
        for value in (1.5, 2.1):
            self.candidate["development"] = metrics(value, 0.25)
            self.rebind_fixture()
            result = research.assess(self.candidate, self.root, audit_runner=runner)
            self.assertTrue(result["extended_audit_runner_invoked"])
            self.assertTrue(result["high_return_gates_passed"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(set(calls[0][1]), set(self.contract["extended_audit_checks"]))

    def test_runner_failure_cannot_reuse_old_pass_reports(self):
        def fails(*args):
            raise RuntimeError("replay failed")
        result = research.assess(self.candidate, self.root, audit_runner=fails)
        self.assertFalse(result["feasible_frozen_candidate"])
        self.assertEqual(result["audit_error"], "RuntimeError")
        self.assertTrue(set(self.contract["extended_audit_checks"]).issubset(result["missing_or_failed_audits"]))

    def test_stale_bindings_or_changed_evidence_cannot_pass(self):
        self.candidate["binding"]["input_sha256"] = "f" * 64
        self.assertFalse(self.assess()["feasible_frozen_candidate"])
        self.candidate["binding"]["input_sha256"] = "1" * 64
        self.proof.write_text("tampered", encoding="utf-8")
        self.assertFalse(self.assess()["feasible_frozen_candidate"])

    def test_evidence_cannot_escape_the_evaluation_bundle(self):
        self.candidate["audits"]["asset_lineage"]["artifacts"][0]["path"] = "../outside.txt"
        self.assertFalse(self.assess()["feasible_frozen_candidate"])

    def test_obsolete_contract_binding_is_rejected(self):
        self.candidate["binding"]["contract_sha256"] = "0" * 64
        for report in self.candidate["audits"].values():
            report["binding"] = copy.deepcopy(self.candidate["binding"])
        self.assertFalse(self.assess()["binding_valid"])

    def test_changed_metrics_cannot_reuse_existing_audit_evidence(self):
        self.candidate["oos"]["cagr"] = 1.6
        self.candidate["oos"]["calmar"] = 1.6 / 0.25
        self.assertFalse(self.assess()["binding_valid"])

    def test_final_categories_do_not_reselect_after_a_failed_seal(self):
        verdict = research.final_verdict({"A": "synthetic", "B": "synthetic", "C": "synthetic"},
                                         [self.candidate], self.root)
        self.assertEqual(verdict["A"], "synthetic")
        self.assertIsNone(verdict["B"])
        self.assertEqual(verdict["C"], "synthetic")
        self.assertFalse(verdict["D"])
        self.candidate["sealed"]["cagr"] = 1.4
        self.candidate["sealed"]["calmar"] = 1.4 / 0.25
        self.rebind_fixture()
        verdict = research.final_verdict({"A": "synthetic", "C": "synthetic"}, [self.candidate], self.root)
        self.assertIsNone(verdict["A"])
        self.assertEqual(verdict["C"], "synthetic")
        self.assertTrue(verdict["D"])

    def test_no_candidates_means_no_invented_winner_or_boundary(self):
        result = research.final_verdict({}, [], self.root)
        self.assertEqual([result[k] for k in ("A", "B", "C")], [None, None, None])
        self.assertTrue(result["D"])

    def test_report_booleans_without_artifact_bytes_are_not_evidence(self):
        self.candidate["audits"]["asset_lineage"]["artifacts"] = []
        self.assertFalse(self.assess()["feasible_frozen_candidate"])

    def test_changed_nomination_cannot_reuse_audits(self):
        self.candidate["nominee_categories"].append("B")
        self.assertFalse(self.assess()["binding_valid"])


if __name__ == "__main__":
    unittest.main()
