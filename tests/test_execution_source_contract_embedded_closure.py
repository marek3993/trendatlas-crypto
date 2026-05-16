import copy
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution.current_strategy_root_contract import (
    serialize_current_main_strategy_root_contract,
    validate_authoritative_embedded_dependency_closure,
)


MODEL = "phase68g_etf_flow_impulse_early_risk_cooldown_15"


class TestExecutionSourceContractEmbeddedClosure(unittest.TestCase):
    def build_contract(self) -> dict:
        return {
            "contract_version": 1,
            "source_family": "canonical_current_main_strategy_app_exports",
            "main_strategy_model": MODEL,
            "canonical_metrics_source_path": (
                "outputs/execution/app_exports/"
                "phase68g_etf_flow_impulse_early_risk_cooldown_15_authoritative_net_compare_export.csv"
            ),
            "canonical_paper_source_path": (
                "outputs/execution/app_exports/"
                "phase68g_etf_flow_impulse_early_risk_cooldown_15_paper.csv"
            ),
            "allowed_canonical_root": "outputs/execution/app_exports",
            "forbidden_source_roots": ["outputs/execution/app_snapshot"],
        }

    def build_snapshot(self, contract: dict, day: str) -> dict:
        return {
            "current_main_strategy_root_contract": serialize_current_main_strategy_root_contract(contract),
            "main_strategy_model": MODEL,
            "strategy_last_closed_day": day,
            "freshness_target_closed_day": day,
            "main_strategy_metrics": {
                "model": MODEL,
                "switch_count": 0,
                "cash_days_pct": 0.0,
                "btc_days_pct": 100.0,
            },
            "chart_source_paths": {
                "main_strategy": contract["canonical_paper_source_path"],
                "reference_strategy": "outputs/execution/app_exports/phase67j_no_neo_main_paper.csv",
            },
            "source_metadata": {
                "main_strategy_metrics": {
                    "path": contract["canonical_metrics_source_path"],
                    "operational_metrics": {
                        "path": contract["canonical_paper_source_path"],
                    },
                },
                "freshness": {
                    "path": "outputs/execution/freshness/app_freshness_report.json",
                },
                "freshness_target_closed_day": {
                    "path": "outputs/execution/freshness/app_freshness_report.json",
                },
            },
            "freshness": {
                "status": "ok",
                "errors": [],
                "checks": {
                    "phase66g_paper_last_date": day,
                    "phase66g_live_latest_available_date": day,
                    "phase66g_trend_last_date": day,
                    "phase67j_paper_last_date": day,
                    "phase67j_live_latest_available_date": day,
                },
            },
        }

    def test_embedded_authority_closure_accepts_current_publish_without_reading_local_phase66g_files(self):
        contract = self.build_contract()
        snapshot = self.build_snapshot(contract, "2026-05-14")

        with mock.patch(
            "scripts.execution.current_strategy_root_contract._read_csv_rows_required",
            side_effect=AssertionError("embedded authority validation must not read local CSV files"),
        ):
            result = validate_authoritative_embedded_dependency_closure(
                snapshot,
                contract,
                root=ROOT,
                context="test authority snapshot:",
            )

        self.assertEqual(result["expected_closed_day"], "2026-05-14")
        self.assertEqual(
            result["dependency_days"]["phase66g_paper_last_date"],
            "2026-05-14",
        )
        self.assertEqual(result["validation_mode"], "authority_embedded_snapshot")

    def test_embedded_authority_closure_blocks_stale_phase66g_day_with_actionable_error(self):
        contract = self.build_contract()
        snapshot = self.build_snapshot(contract, "2026-05-14")
        stale_snapshot = copy.deepcopy(snapshot)
        stale_snapshot["freshness"]["checks"]["phase66g_paper_last_date"] = "2026-04-19"

        with self.assertRaisesRegex(
            ValueError,
            "phase66g_paper_last_date.*expected=2026-05-14.*actual=2026-04-19.*Pi fast daily authority wrapper",
        ):
            validate_authoritative_embedded_dependency_closure(
                stale_snapshot,
                contract,
                context="test authority snapshot:",
            )


if __name__ == "__main__":
    unittest.main()
