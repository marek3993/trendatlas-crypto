import unittest
from pathlib import Path

from scripts.execution.current_strategy_root_contract import (
    CurrentMainStrategyContractError,
    load_current_main_strategy_root_contract,
    resolve_homepage_current_strategy_sources,
    serialize_current_main_strategy_root_contract,
)


ROOT = Path(__file__).resolve().parents[1]


class TestExecutionCurrentStrategyRootContract(unittest.TestCase):
    def test_source_of_truth_root_contract_resolves_current_main_strategy(self):
        contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)

        self.assertEqual(contract["main_strategy_model"], "phase68g_66g_1p25x_candidate")
        self.assertEqual(
            contract["source_family"],
            "canonical_current_main_strategy_app_exports",
        )
        self.assertEqual(
            contract["canonical_metrics_source_path"],
            "outputs/execution/app_exports/phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv",
        )
        self.assertEqual(
            contract["canonical_paper_source_path"],
            "outputs/execution/app_exports/phase68g_66g_1p25x_candidate_paper.csv",
        )

    def test_homepage_source_resolution_uses_same_canonical_metric_path(self):
        contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)
        product_snapshot = {
            "current_main_strategy_root_contract": serialize_current_main_strategy_root_contract(contract),
            "main_strategy_model": contract["main_strategy_model"],
            "main_strategy_metrics": {
                "model": contract["main_strategy_model"],
            },
            "chart_source_paths": {
                "main_strategy": contract["canonical_paper_source_path"],
            },
            "source_metadata": {
                "main_strategy_metrics": {
                    "path": contract["canonical_metrics_source_path"],
                },
                "strategy_last_closed_day": {
                    "path": contract["canonical_paper_source_path"],
                },
                "live_public_state": {
                    "path": contract["canonical_paper_source_path"],
                },
                "chart_source_paths": {
                    "main_strategy": {
                        "path": contract["canonical_paper_source_path"],
                    }
                },
            },
        }

        resolved_sources = resolve_homepage_current_strategy_sources(product_snapshot, contract)

        self.assertEqual(
            resolved_sources["metrics_source_path"],
            contract["canonical_metrics_source_path"],
        )
        self.assertEqual(
            resolved_sources["paper_source_path"],
            contract["canonical_paper_source_path"],
        )

    def test_homepage_source_resolution_fails_closed_on_metric_path_divergence(self):
        contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)
        product_snapshot = {
            "current_main_strategy_root_contract": serialize_current_main_strategy_root_contract(contract),
            "main_strategy_model": contract["main_strategy_model"],
            "main_strategy_metrics": {
                "model": contract["main_strategy_model"],
            },
            "chart_source_paths": {
                "main_strategy": contract["canonical_paper_source_path"],
            },
            "source_metadata": {
                "main_strategy_metrics": {
                    "path": "outputs/phase68h_dynamic_leverage_ladder_candidate/phase68h_dynamic_leverage_ladder_summary.csv",
                },
                "strategy_last_closed_day": {
                    "path": contract["canonical_paper_source_path"],
                },
                "live_public_state": {
                    "path": contract["canonical_paper_source_path"],
                },
                "chart_source_paths": {
                    "main_strategy": {
                        "path": contract["canonical_paper_source_path"],
                    }
                },
            },
        }

        with self.assertRaises(CurrentMainStrategyContractError):
            resolve_homepage_current_strategy_sources(product_snapshot, contract)


if __name__ == "__main__":
    unittest.main()
