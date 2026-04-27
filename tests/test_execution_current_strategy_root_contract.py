import unittest
from pathlib import Path
from unittest import mock

from scripts.execution import current_strategy_root_contract as current_strategy_contract
from scripts.execution.current_strategy_root_contract import (
    CurrentMainStrategyContractError,
    load_current_main_strategy_root_contract,
    resolve_homepage_current_strategy_sources,
    resolve_validated_homepage_top_performance_source_contract,
    serialize_current_main_strategy_root_contract,
    validate_homepage_main_chart_source_path,
    validate_product_snapshot_current_strategy_contract,
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

    def test_homepage_main_chart_source_path_must_match_current_main_strategy_paper_path(self):
        contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)

        resolved_path = validate_homepage_main_chart_source_path(
            contract["canonical_paper_source_path"],
            contract,
            context="test:",
        )

        self.assertEqual(resolved_path, contract["canonical_paper_source_path"])

    def test_homepage_main_chart_source_path_rejects_non_canonical_paper_artifact(self):
        contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)

        with self.assertRaisesRegex(
            CurrentMainStrategyContractError,
            "must not switch to a stale/native/non-canonical paper artifact",
        ):
            validate_homepage_main_chart_source_path(
                "outputs/phase68g_portfolio_exposure_leverage_validation/papers/phase68g_66g_1p25x_candidate_paper.csv",
                contract,
                context="test:",
            )

    def test_homepage_top_card_source_contract_must_match_current_main_strategy_metrics_path(self):
        contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)

        source_contract = resolve_validated_homepage_top_performance_source_contract(
            contract["main_strategy_model"],
            contract,
            root=ROOT,
            require_file=False,
        )

        self.assertEqual(
            source_contract["metrics_source_path"],
            contract["canonical_metrics_source_path"],
        )
        self.assertEqual(
            source_contract["semantic_role"],
            "current_live_main_strategy_top_cards",
        )

    def test_homepage_top_card_source_contract_rejects_separate_compare_ranking_artifact(self):
        contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)
        original_contract = dict(
            current_strategy_contract.HOMEPAGE_TOP_PERFORMANCE_SOURCE_CONTRACTS[
                contract["main_strategy_model"]
            ]
        )
        compare_artifact_contract = dict(original_contract)
        compare_artifact_contract["metrics_source_path"] = (
            "outputs/execution/app_exports/"
            "phase68i_dynamic_ladder_candidate_authoritative_net_compare_export.csv"
        )

        with mock.patch.dict(
            current_strategy_contract.HOMEPAGE_TOP_PERFORMANCE_SOURCE_CONTRACTS,
            {contract["main_strategy_model"]: compare_artifact_contract},
            clear=False,
        ):
            with self.assertRaisesRegex(
                CurrentMainStrategyContractError,
                "must not use a separate compare/ranking artifact",
            ):
                resolve_validated_homepage_top_performance_source_contract(
                    contract["main_strategy_model"],
                    contract,
                    root=ROOT,
                    require_file=False,
                )

    def test_product_snapshot_validation_rejects_top_card_source_path_divergence(self):
        contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)
        product_snapshot = {
            "current_main_strategy_root_contract": serialize_current_main_strategy_root_contract(contract),
            "main_strategy_model": contract["main_strategy_model"],
            "main_strategy_metrics": {
                "model": contract["main_strategy_model"],
            },
            "main_strategy_top_performance_metrics": {
                "model": contract["main_strategy_model"],
                "cagr_pct": 118.66,
            },
            "chart_source_paths": {
                "main_strategy": contract["canonical_paper_source_path"],
            },
            "source_metadata": {
                "main_strategy_metrics": {
                    "path": contract["canonical_metrics_source_path"],
                },
                "main_strategy_top_performance_metrics": {
                    "path": (
                        "outputs/execution/app_exports/"
                        "phase68i_dynamic_ladder_candidate_authoritative_net_compare_export.csv"
                    ),
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

        with self.assertRaisesRegex(
            CurrentMainStrategyContractError,
            "must not use a separate compare/ranking artifact",
        ):
            validate_product_snapshot_current_strategy_contract(
                product_snapshot,
                contract,
                context="test:",
            )

    def test_product_snapshot_validation_rejects_chart_source_metadata_divergence(self):
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
                        "path": "outputs/phase68g_portfolio_exposure_leverage_validation/papers/phase68g_66g_1p25x_candidate_paper.csv",
                    }
                },
            },
        }

        with self.assertRaisesRegex(
            CurrentMainStrategyContractError,
            "must not switch to a stale/native/non-canonical paper artifact",
        ):
            validate_product_snapshot_current_strategy_contract(
                product_snapshot,
                contract,
                context="test:",
            )


if __name__ == "__main__":
    unittest.main()
