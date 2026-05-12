import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

JSON_FILES = [
    ROOT / "source_of_truth" / "project_truth.json",
    ROOT / "source_of_truth" / "export_contract.json",
    ROOT / "source_of_truth" / "paths_registry.json",
]

REQUIRED_NORMALIZED_CONTRACTS = {
    "real_account_state",
    "model_signal_state",
    "model_performance_state",
    "authority_state",
    "data_health_state",
}

REQUIRED_DASHBOARD_PUBLIC_ARTIFACTS = {
    "dashboard_public_status",
    "dashboard_public_chart_timeseries",
    "dashboard_public_status_quality",
    "dashboard_public_status_manifest",
}

REQUIRED_CODEX_OUTPUT_SECTIONS = {
    "FILES READ",
    "SOURCE OF TRUTH",
    "exact root cause",
    "exact contract impact",
    "exact files changed",
    "regression test added/updated",
    "forbidden old path checked",
    "validation commands/results",
    "exact git add list",
    "commit message",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} root must be JSON object")

    return payload


class TestSourceOfTruthJsonValid(unittest.TestCase):
    def test_source_of_truth_json_files_exist(self):
        missing = [str(path.relative_to(ROOT)) for path in JSON_FILES if not path.exists()]
        self.assertFalse(missing, f"Missing source_of_truth JSON files: {missing}")

    def test_source_of_truth_json_files_are_valid_json(self):
        failures = []

        for path in JSON_FILES:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    json.load(handle)
            except Exception as exc:
                failures.append(f"{path.relative_to(ROOT)} invalid JSON: {exc}")

        self.assertFalse(failures, " | ".join(failures))

    def test_source_of_truth_json_roots_are_objects(self):
        failures = []

        for path in JSON_FILES:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)

            if not isinstance(payload, dict):
                failures.append(f"{path.relative_to(ROOT)} root must be JSON object")

        self.assertFalse(failures, " | ".join(failures))

    def test_project_truth_contains_contract_first_repo_policy(self):
        payload = load_json(ROOT / "source_of_truth" / "project_truth.json")

        workflow_rules = payload.get("workflow_rules")
        self.assertIsInstance(workflow_rules, dict)

        policy = workflow_rules.get("contract_first_repo_policy")
        self.assertIsInstance(policy, dict)
        self.assertTrue(policy.get("bug_classification_required_before_patching"))

        bug_classes = policy.get("bug_classes")
        self.assertIsInstance(bug_classes, dict)
        self.assertTrue({"A", "B", "C", "D"}.issubset(set(bug_classes)))

        patch_order = policy.get("patch_order")
        self.assertIsInstance(patch_order, dict)
        self.assertTrue(patch_order.get("do_not_start_with_ui_patch_for_bug_classes_b_c_d"))
        self.assertTrue(patch_order.get("patch_source_contract_first_for_bug_classes_b_c_d"))
        self.assertTrue(patch_order.get("validate_source_contract_before_consumer_patch"))
        self.assertTrue(patch_order.get("patch_consumers_only_after_source_contract_validation"))

        required_contracts = set(policy.get("required_normalized_public_runtime_contracts", []))
        self.assertTrue(REQUIRED_NORMALIZED_CONTRACTS.issubset(required_contracts))

        regression_rule = policy.get("regression_rule")
        self.assertIsInstance(regression_rule, dict)
        self.assertTrue(regression_rule.get("every_recurring_bug_requires_regression_test"))
        self.assertTrue(regression_rule.get("wording_only_fix_allowed_only_for_bug_class_a"))

        output_sections = set(policy.get("codex_non_trivial_output_sections", []))
        self.assertTrue(REQUIRED_CODEX_OUTPUT_SECTIONS.issubset(output_sections))

        normalized_contracts = payload.get("normalized_public_runtime_contracts")
        self.assertIsInstance(normalized_contracts, dict)
        self.assertTrue(REQUIRED_NORMALIZED_CONTRACTS.issubset(set(normalized_contracts)))

        forbidden_shortcuts = payload.get("forbidden_semantic_shortcuts")
        self.assertIsInstance(forbidden_shortcuts, dict)
        self.assertEqual(
            forbidden_shortcuts.get("real_wallet_exposure_must_not_be_inferred_from_fields"),
            ["actual_held_asset", "current_asset", "effective_market_exposure"],
        )
        self.assertEqual(
            forbidden_shortcuts.get("real_account_pnl_must_not_be_inferred_from_fields"),
            ["model_equity", "paper_equity"],
        )
        self.assertTrue(
            forbidden_shortcuts.get("model_exposure_must_not_be_shown_as_real_account_exposure")
        )
        self.assertTrue(
            forbidden_shortcuts.get("dashboards_must_not_infer_account_state_from_model_fields")
        )

    def test_export_contract_contains_normalized_public_runtime_contracts(self):
        payload = load_json(ROOT / "source_of_truth" / "export_contract.json")

        normalized_contracts = payload.get("normalized_public_runtime_contracts")
        self.assertIsInstance(normalized_contracts, dict)
        self.assertTrue(REQUIRED_NORMALIZED_CONTRACTS.issubset(set(normalized_contracts)))

        real_account_state = normalized_contracts["real_account_state"]
        self.assertEqual(
            real_account_state.get("authoritative_source_path"),
            "outputs/execution/authority/latest_attempt_status.json",
        )
        self.assertEqual(real_account_state.get("json_path"), "app_runtime_snapshot.real_account_state")
        self.assertIn("would_place_real_order", real_account_state.get("minimum_fields", []))

        model_signal_state = normalized_contracts["model_signal_state"]
        self.assertEqual(model_signal_state.get("json_path"), "app_runtime_snapshot.model_signal_state")
        self.assertIn("not_real_wallet_exposure", model_signal_state.get("minimum_fields", []))

        model_performance_state = normalized_contracts["model_performance_state"]
        self.assertEqual(
            model_performance_state.get("json_path"),
            "app_runtime_snapshot.model_performance_state",
        )
        self.assertIn("equity_curve_semantics", model_performance_state.get("minimum_fields", []))

        authority_state = normalized_contracts["authority_state"]
        self.assertIn(
            "outputs/execution/authority/latest_successful_snapshot.json",
            authority_state.get("authoritative_source_paths", []),
        )
        self.assertIn("authority_role", authority_state.get("minimum_fields", []))

        data_health_state = normalized_contracts["data_health_state"]
        self.assertIn(
            "outputs/production/data_health_report.json",
            data_health_state.get("authoritative_source_paths", []),
        )
        self.assertIn("block_execution", data_health_state.get("minimum_fields", []))

        consumer_guardrails = payload.get("consumer_guardrails")
        self.assertIsInstance(consumer_guardrails, dict)
        self.assertTrue(consumer_guardrails.get("dashboards_must_read_normalized_public_runtime_contracts"))
        self.assertEqual(
            consumer_guardrails.get("real_wallet_exposure_must_not_be_inferred_from_fields"),
            ["actual_held_asset", "current_asset", "effective_market_exposure"],
        )
        self.assertEqual(
            consumer_guardrails.get("real_account_pnl_must_not_be_inferred_from_fields"),
            ["model_equity", "paper_equity"],
        )
        self.assertTrue(
            consumer_guardrails.get("model_exposure_must_not_be_shown_as_real_account_exposure")
        )
        self.assertTrue(
            consumer_guardrails.get("dashboards_must_not_infer_account_state_from_model_fields")
        )
        self.assertTrue(
            consumer_guardrails.get("dashboard_public_status_model_performance_btc_24h_pct_is_published_snapshot")
        )
        self.assertTrue(
            consumer_guardrails.get("live_dashboard_btc_24h_must_not_freeze_from_published_snapshot")
        )
        self.assertTrue(
            consumer_guardrails.get("live_dashboard_btc_24h_must_read_live_market_state_or_ticker")
        )
        self.assertTrue(consumer_guardrails.get("forbidden_hybrid_chart_semantics"))

        dashboard_public_contract = payload.get("dashboard_public_cis_contract")
        self.assertIsInstance(dashboard_public_contract, dict)
        self.assertEqual(
            dashboard_public_contract.get("status_path"),
            "outputs/execution/app_snapshot/dashboard_public_status.json",
        )
        self.assertEqual(
            dashboard_public_contract.get("chart_timeseries_path"),
            "outputs/execution/app_snapshot/dashboard_public_chart_timeseries.csv",
        )
        self.assertEqual(
            dashboard_public_contract.get("quality_path"),
            "outputs/execution/app_snapshot/dashboard_public_status.quality.json",
        )
        self.assertEqual(
            dashboard_public_contract.get("manifest_path"),
            "outputs/execution/app_snapshot/dashboard_public_status.manifest.json",
        )
        status_fields = set(dashboard_public_contract.get("status_contract_fields", []))
        self.assertTrue(
            {"real_account", "execution", "model_signal", "model_performance", "data_health", "live_market_state"}.issubset(status_fields)
        )
        live_market_semantics = dashboard_public_contract.get("live_market_semantics")
        self.assertIsInstance(live_market_semantics, dict)
        self.assertEqual(live_market_semantics.get("btc_24h_pct_expected_source"), "live_ticker")
        self.assertIn(
            "real_account.exposure_x * live_market_state.btc_24h_pct",
            live_market_semantics.get("live_dashboard_account_24h_formula", ""),
        )
        self.assertIn(
            "live_market_state.account_24h_pct - live_market_state.btc_24h_pct",
            live_market_semantics.get("live_dashboard_account_vs_btc_formula", ""),
        )

    def test_paths_registry_contains_dashboard_public_artifacts(self):
        payload = load_json(ROOT / "source_of_truth" / "paths_registry.json")
        canonical_roots = payload.get("canonical_roots")
        self.assertIsInstance(canonical_roots, dict)
        self.assertIn("execution_app_snapshot", canonical_roots)

        artifacts = payload.get("artifacts")
        self.assertIsInstance(artifacts, dict)
        self.assertTrue(REQUIRED_DASHBOARD_PUBLIC_ARTIFACTS.issubset(set(artifacts)))

        dashboard_public_status = artifacts["dashboard_public_status"]
        self.assertTrue(
            str(dashboard_public_status.get("canonical", "")).endswith(
                "outputs\\execution\\app_snapshot\\dashboard_public_status.json"
            )
        )
        self.assertEqual(dashboard_public_status.get("truth_domain"), "dashboard_read_model")
        field_contract = dashboard_public_status.get("field_contract")
        self.assertIsInstance(field_contract, dict)
        self.assertEqual(
            field_contract.get("forbidden_real_wallet_inference_fields"),
            ["actual_held_asset", "current_asset", "effective_market_exposure"],
        )
        self.assertTrue(field_contract.get("published_snapshot_btc_24h_is_not_live_for_tablet"))

        chart_artifact = artifacts["dashboard_public_chart_timeseries"]
        self.assertTrue(
            str(chart_artifact.get("canonical", "")).endswith(
                "outputs\\execution\\app_snapshot\\dashboard_public_chart_timeseries.csv"
            )
        )
        chart_field_contract = chart_artifact.get("field_contract")
        self.assertIsInstance(chart_field_contract, dict)
        self.assertTrue(chart_field_contract.get("separate_model_and_real_account_columns_required"))
        self.assertTrue(chart_field_contract.get("forbidden_hybrid_chart_semantics"))


if __name__ == "__main__":
    unittest.main()
