import csv
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from services.pc import worker_service
from services.shared.schemas import HEAVY_VALIDATION_STATUS_COMPLETED, SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


class HeavyValidationPathPortabilityTest(unittest.TestCase):
    def _write_csv(self, path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _write_validated_mutation_proposal(self, path: Path, *, family_id: str, proposal_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "job_id": "proposal_job_01",
            "family_id": family_id,
            "dev_only": True,
            "non_authoritative": True,
            "official_truth": False,
            "validation": {
                "status": "validated_queue_ready_request_only",
            },
            "proposal": {
                "schema_version": SCHEMA_VERSION,
                "proposal_id": proposal_id,
                "family_id": family_id,
                "mechanism_hypothesis": "portable artifact loading",
                "mutation_target": {
                    "target_id": "pilot_gate",
                },
                "expected_impact": {
                    "churn": "lower",
                    "switch_count": "lower",
                    "dd": "lower",
                    "net_benefit": "higher",
                },
                "stop_condition": "fail_closed",
                "lineage_refs": {},
                "dev_only": True,
                "non_authoritative": True,
                "official_truth": False,
                "execution_allowed": False,
            },
            "queue_ready_heavy_job_request": {
                "status": "prepared_not_submitted",
                "proposal_id": proposal_id,
                "strategy_code_executed": False,
                "execution_allowed": False,
            },
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def test_load_heavy_validation_result_pack_rebases_pi_outputs_paths_to_research_os_root(self) -> None:
        family_id = "family_portability"
        proposal_id = "proposal_portability"
        fixture_root = ROOT / "outputs" / "_tmp_heavy_validation_path_portability"
        if fixture_root.exists():
            shutil.rmtree(fixture_root)
        try:
            project_root = (fixture_root / "market_regime_v1").resolve()
            outputs_root = project_root / "outputs"
            summary_path = outputs_root / "heavy_validation_outputs" / "job_01_summary.json"
            compare_path = outputs_root / "heavy_validation_outputs" / "job_01_compare.csv"
            cost_metrics_path = outputs_root / "heavy_validation_outputs" / "job_01_cost_metrics.csv"
            source_mutation_proposal_path = outputs_root / "worker_outputs" / "proposal.json"

            self._write_csv(
                compare_path,
                rows=[
                    {
                        "family_id": family_id,
                        "metric": "net_benefit",
                        "basis_json": "{}",
                        "strategy_code_executed": "false",
                    }
                ],
                fieldnames=["family_id", "metric", "basis_json", "strategy_code_executed"],
            )
            self._write_csv(
                cost_metrics_path,
                rows=[
                    {
                        "family_id": family_id,
                        "metric": "strategy_code_executed",
                        "value": "false",
                    }
                ],
                fieldnames=["family_id", "metric", "value"],
            )
            self._write_validated_mutation_proposal(
                source_mutation_proposal_path,
                family_id=family_id,
                proposal_id=proposal_id,
            )

            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "job_id": "job_01",
                        "request_id": "request_01",
                        "proposal_id": proposal_id,
                        "family_id": family_id,
                        "status": HEAVY_VALIDATION_STATUS_COMPLETED,
                        "adapter_id": "safe_adapter",
                        "dev_only": True,
                        "non_authoritative": True,
                        "official_truth": False,
                        "strategy_advancement": False,
                        "strategy_code_executed": False,
                        "live_trading": False,
                        "source_of_truth_mutation": False,
                        "official_promotion_logic": False,
                        "source_mutation_proposal_artifact": "/opt/market_regime_v1/outputs/worker_outputs/proposal.json",
                        "artifact_paths": {
                            "compare": "/opt/market_regime_v1/outputs/heavy_validation_outputs/job_01_compare.csv",
                            "cost_metrics": "/opt/market_regime_v1/outputs/heavy_validation_outputs/job_01_cost_metrics.csv",
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {"RESEARCH_OS_ROOT": str(project_root)}, clear=False):
                summary, compare_rows, cost_rows, source_artifact, source_paths = worker_service.load_heavy_validation_result_pack(
                    summary_path
                )

            self.assertEqual(summary["family_id"], family_id)
            self.assertEqual(compare_rows[0]["family_id"], family_id)
            self.assertEqual(cost_rows[0]["family_id"], family_id)
            self.assertEqual(source_artifact["job_id"], "proposal_job_01")
            self.assertEqual(source_paths["summary"], str(summary_path.resolve()))
            self.assertEqual(source_paths["compare"], str(compare_path.resolve()))
            self.assertEqual(source_paths["cost_metrics"], str(cost_metrics_path.resolve()))
        finally:
            shutil.rmtree(fixture_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
