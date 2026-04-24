import importlib.util
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "research_os_trendatlas_imlayer_reconcile_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "research_os_trendatlas_imlayer_reconcile_v1",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class TestResearchOSTrendAtlasIMLayerReconcileV1(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.temp_dir = ROOT / "tests_runtime_trendatlas_imlayer_reconcile"
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def build_episode(self, memory_id: str, family_id: str) -> dict:
        return {
            "schema_version": "trendatlas.imlayer.decision_episode.v1",
            "memory_id": memory_id,
            "project": "trendatlas-crypto",
            "source_system": "trendatlas-research-os",
            "export_generated_at": "2026-04-24T17:52:34Z",
            "retrieval_text": f"Decision episode for {family_id}",
            "keys": {
                "cycle_id": "20260424_cycle",
                "family_id": family_id,
                "proposal_id": f"{family_id}_proposal",
                "request_id": f"{family_id}_request",
                "result_id": f"{family_id}_result",
                "verdict_id": f"{family_id}_verdict",
                "state_id": f"{family_id}_state",
            },
            "planner_proposal": {
                "mutation_target": {
                    "target_id": f"mechanism.{family_id}",
                },
                "expected_impact": {
                    "switch_count": {
                        "direction": "decrease",
                        "target": "switch_count_delta <= 1",
                        "basis": {"latest_switch_count_delta": 2},
                    }
                },
                "stop_condition": "Stop if net return falls below zero",
            },
            "episode_timestamps": {
                "heavy_validation_finished_at": "2026-04-24T17:00:00Z",
            },
            "heavy_validation_verdict": {
                "job_id": f"{family_id}_heavy_job",
                "status": "heavy_validation_completed",
                "expected_impact": {
                    "switch_count": {
                        "direction": "decrease",
                        "target": "switch_count_delta <= 1",
                    }
                },
            },
            "critic_verdict": {
                "job_id": f"{family_id}_critic_job",
                "next_action": "pause_family",
                "verdict": "pause",
                "verdict_reason": "Guardrails breached",
                "guardrail_breaches": ["switch count delta above threshold"],
                "key_metrics": {"net_return": 1.0},
                "net_first_rules": {"pause_if_switch_count_delta_gt": 1.0},
            },
            "governor_decision": {
                "job_id": f"{family_id}_governor_job",
                "lifecycle_state": "paused",
            },
            "compact_packet": {
                "planner": f"planner packet {family_id}",
                "critic": f"critic packet {family_id}",
            },
            "artifact_refs": {
                "cycle_summary": {
                    "path": f"C:/tmp/{family_id}_cycle_summary.json",
                    "sha256": f"{family_id}_cycle_sha",
                }
            },
        }

    def create_batch_fixture(self, *, include_second_result: bool) -> tuple[str, Path, Path]:
        batch_id = "20260424T175234Z"
        export_root = self.temp_dir / "outputs" / "research_os" / "dev_only" / "imlayer_exports" / batch_id
        ingestion_manifest_path = (
            self.temp_dir
            / "outputs"
            / "research_os"
            / "dev_only"
            / "imlayer_ingestion"
            / batch_id
            / batch_id
            / "ingestion_manifest.json"
        )

        episode_paths = [
            "episodes/trendatlas.crypto.decision_episode.alpha.family.json",
            "episodes/trendatlas.crypto.decision_episode.beta.family.json",
        ]
        write_json(
            export_root / "manifest.json",
            {
                "schema_version": "trendatlas.imlayer.export_manifest.v1",
                "export_batch_id": batch_id,
                "episode_paths": episode_paths,
            },
        )
        write_json(
            export_root / episode_paths[0],
            self.build_episode(
                "trendatlas.crypto.decision_episode.alpha.family",
                "alpha.family",
            ),
        )
        write_json(
            export_root / episode_paths[1],
            self.build_episode(
                "trendatlas.crypto.decision_episode.beta.family",
                "beta.family",
            ),
        )

        results = [
            {
                "memory_id": "trendatlas.crypto.decision_episode.alpha.family",
                "episode_path": episode_paths[0],
                "status": "ingested",
                "request": {
                    "memory_id": "trendatlas.crypto.decision_episode.alpha.family",
                    "namespace": "trendatlas",
                    "collection": "decision_episodes",
                },
                "response": {
                    "memory_id": "trendatlas.crypto.decision_episode.alpha.family",
                    "namespace": "trendatlas",
                    "collection": "decision_episodes",
                },
            }
        ]
        if include_second_result:
            results.append(
                {
                    "memory_id": "trendatlas.crypto.decision_episode.beta.family",
                    "episode_path": episode_paths[1],
                    "status": "ingested",
                    "request": {
                        "memory_id": "trendatlas.crypto.decision_episode.beta.family",
                        "namespace": "trendatlas",
                        "collection": "decision_episodes",
                    },
                    "response": {
                        "memory_id": "trendatlas.crypto.decision_episode.beta.family",
                        "namespace": "trendatlas",
                        "collection": "decision_episodes",
                    },
                }
            )

        write_json(
            ingestion_manifest_path,
            {
                "schema_version": "trendatlas.imlayer.ingestion_manifest.v1",
                "batch_id": batch_id,
                "counts": {
                    "total": len(results),
                },
                "writer": {
                    "payload_namespace": "trendatlas",
                    "payload_collection": "decision_episodes",
                },
                "results": results,
            },
        )
        return batch_id, export_root, ingestion_manifest_path

    def build_read_response(self, episode: dict, write_id: str, received_at_utc: str) -> dict:
        stored_payload = self.module.load_ingest_helper_module().build_live_episode_payload(
            episode,
            now_utc=self.module.load_ingest_helper_module().parse_utc_timestamp(
                received_at_utc,
                label="record.received_at_utc",
            ),
        )
        return {
            "success": True,
            "contract": "imlayer.trendatlas.v1",
            "memory_id": episode["memory_id"],
            "record": {
                "write_id": write_id,
                "received_at_utc": received_at_utc,
                "payload": stored_payload,
            },
        }

    def mock_urlopen_factory(self, responses_by_memory_id: dict[str, dict]):
        def _urlopen(request, timeout=None, context=None):
            memory_id = request.full_url.rsplit("/", 1)[-1]
            payload = responses_by_memory_id[memory_id]

            class _Response:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

                def read(self_inner):
                    return json.dumps(payload).encode("utf-8")

            return _Response()

        return _urlopen

    def test_reconcile_reports_passed_true_read_back_when_read_surface_matches_exact_payload(self) -> None:
        batch_id, export_root, ingestion_manifest_path = self.create_batch_fixture(include_second_result=True)
        alpha_episode = json.loads((export_root / "episodes/trendatlas.crypto.decision_episode.alpha.family.json").read_text(encoding="utf-8"))
        beta_episode = json.loads((export_root / "episodes/trendatlas.crypto.decision_episode.beta.family.json").read_text(encoding="utf-8"))
        responses = {
            "trendatlas.crypto.decision_episode.alpha.family": self.build_read_response(
                alpha_episode,
                "wr_alpha",
                "2026-04-24T17:52:34Z",
            ),
            "trendatlas.crypto.decision_episode.beta.family": self.build_read_response(
                beta_episode,
                "wr_beta",
                "2026-04-24T17:52:35Z",
            ),
        }

        with mock.patch.object(
            self.module.urllib.request,
            "urlopen",
            side_effect=self.mock_urlopen_factory(responses),
        ):
            report = self.module.reconcile_batch(
                batch_id=batch_id,
                batch_root=str(export_root),
                ingestion_manifest=str(ingestion_manifest_path),
                ingestion_root=None,
                project_root=self.temp_dir,
            )

        self.assertEqual(report["write_ack_parity"]["status"], "passed")
        self.assertEqual(report["true_read_back_parity"]["status"], "passed")
        self.assertEqual(report["true_read_back_parity"]["verified_count"], 2)
        self.assertEqual(report["true_read_back_parity"]["mismatches"], [])
        self.assertEqual(report["final_status"], "working")

    def test_reconcile_accepts_semantic_payload_parity_when_only_freshness_hours_drift_is_within_tolerance(self) -> None:
        batch_id, export_root, ingestion_manifest_path = self.create_batch_fixture(include_second_result=True)
        alpha_episode = json.loads((export_root / "episodes/trendatlas.crypto.decision_episode.alpha.family.json").read_text(encoding="utf-8"))
        beta_episode = json.loads((export_root / "episodes/trendatlas.crypto.decision_episode.beta.family.json").read_text(encoding="utf-8"))
        alpha_response = self.build_read_response(
            alpha_episode,
            "wr_alpha",
            "2026-04-24T17:52:34Z",
        )
        beta_response = self.build_read_response(
            beta_episode,
            "wr_beta",
            "2026-04-24T17:52:35Z",
        )
        beta_response["record"]["payload"]["decision_packet"]["freshness_hours"] += 0.0002
        responses = {
            "trendatlas.crypto.decision_episode.alpha.family": alpha_response,
            "trendatlas.crypto.decision_episode.beta.family": beta_response,
        }

        with mock.patch.object(
            self.module.urllib.request,
            "urlopen",
            side_effect=self.mock_urlopen_factory(responses),
        ):
            report = self.module.reconcile_batch(
                batch_id=batch_id,
                batch_root=str(export_root),
                ingestion_manifest=str(ingestion_manifest_path),
                ingestion_root=None,
                project_root=self.temp_dir,
            )

        self.assertEqual(report["write_ack_parity"]["status"], "passed")
        self.assertEqual(report["true_read_back_parity"]["status"], "passed")
        self.assertEqual(report["true_read_back_parity"]["semantic_parity"]["status"], "passed")
        self.assertEqual(
            report["true_read_back_parity"]["freshness_hours_drift_check"]["status"],
            "passed",
        )
        self.assertEqual(report["true_read_back_parity"]["mismatches"], [])
        beta_verified = next(
            item
            for item in report["true_read_back_parity"]["verified_records"]
            if item["memory_id"] == "trendatlas.crypto.decision_episode.beta.family"
        )
        self.assertEqual(beta_verified["semantic_parity_status"], "passed")
        self.assertEqual(beta_verified["freshness_hours_status"], "passed")
        self.assertAlmostEqual(beta_verified["freshness_hours_drift_hours"], 0.0002)
        self.assertEqual(report["final_status"], "working")

    def test_reconcile_fails_write_ack_when_memory_id_is_missing_from_acknowledged_results(self) -> None:
        batch_id, export_root, ingestion_manifest_path = self.create_batch_fixture(include_second_result=False)

        report = self.module.reconcile_batch(
            batch_id=batch_id,
            batch_root=str(export_root),
            ingestion_manifest=str(ingestion_manifest_path),
            ingestion_root=None,
            project_root=self.temp_dir,
        )

        self.assertEqual(report["write_ack_parity"]["status"], "failed")
        self.assertEqual(
            report["write_ack_parity"]["missing_on_imlayer"],
            ["trendatlas.crypto.decision_episode.beta.family"],
        )
        self.assertEqual(report["final_status"], "blocked")

    def test_reconcile_fails_closed_when_read_back_payload_schema_version_mismatches(self) -> None:
        batch_id, export_root, ingestion_manifest_path = self.create_batch_fixture(include_second_result=True)
        alpha_episode = json.loads((export_root / "episodes/trendatlas.crypto.decision_episode.alpha.family.json").read_text(encoding="utf-8"))
        beta_episode = json.loads((export_root / "episodes/trendatlas.crypto.decision_episode.beta.family.json").read_text(encoding="utf-8"))
        alpha_response = self.build_read_response(
            alpha_episode,
            "wr_alpha",
            "2026-04-24T17:52:34Z",
        )
        beta_response = self.build_read_response(
            beta_episode,
            "wr_beta",
            "2026-04-24T17:52:35Z",
        )
        beta_response["record"]["payload"]["schema_version"] = "wrong.contract.v1"
        responses = {
            "trendatlas.crypto.decision_episode.alpha.family": alpha_response,
            "trendatlas.crypto.decision_episode.beta.family": beta_response,
        }

        with mock.patch.object(
            self.module.urllib.request,
            "urlopen",
            side_effect=self.mock_urlopen_factory(responses),
        ):
            report = self.module.reconcile_batch(
                batch_id=batch_id,
                batch_root=str(export_root),
                ingestion_manifest=str(ingestion_manifest_path),
                ingestion_root=None,
                project_root=self.temp_dir,
            )

        self.assertEqual(report["write_ack_parity"]["status"], "passed")
        self.assertEqual(report["true_read_back_parity"]["status"], "failed")
        self.assertEqual(report["final_status"], "blocked")
        self.assertIn(
            {
                "memory_id": "trendatlas.crypto.decision_episode.beta.family",
                "episode_path": "episodes/trendatlas.crypto.decision_episode.beta.family.json",
                "field": "record.payload.schema_version",
                "expected": "imlayer.trendatlas.v1",
                "actual": "wrong.contract.v1",
            },
            report["true_read_back_parity"]["mismatches"],
        )

    def test_reconcile_fails_closed_when_freshness_hours_drift_exceeds_tolerance(self) -> None:
        batch_id, export_root, ingestion_manifest_path = self.create_batch_fixture(include_second_result=True)
        alpha_episode = json.loads((export_root / "episodes/trendatlas.crypto.decision_episode.alpha.family.json").read_text(encoding="utf-8"))
        beta_episode = json.loads((export_root / "episodes/trendatlas.crypto.decision_episode.beta.family.json").read_text(encoding="utf-8"))
        alpha_response = self.build_read_response(
            alpha_episode,
            "wr_alpha",
            "2026-04-24T17:52:34Z",
        )
        beta_response = self.build_read_response(
            beta_episode,
            "wr_beta",
            "2026-04-24T17:52:35Z",
        )
        beta_response["record"]["payload"]["decision_packet"]["freshness_hours"] += 0.001
        responses = {
            "trendatlas.crypto.decision_episode.alpha.family": alpha_response,
            "trendatlas.crypto.decision_episode.beta.family": beta_response,
        }

        with mock.patch.object(
            self.module.urllib.request,
            "urlopen",
            side_effect=self.mock_urlopen_factory(responses),
        ):
            report = self.module.reconcile_batch(
                batch_id=batch_id,
                batch_root=str(export_root),
                ingestion_manifest=str(ingestion_manifest_path),
                ingestion_root=None,
                project_root=self.temp_dir,
            )

        self.assertEqual(report["write_ack_parity"]["status"], "passed")
        self.assertEqual(report["true_read_back_parity"]["status"], "failed")
        self.assertEqual(report["true_read_back_parity"]["semantic_parity"]["status"], "passed")
        self.assertEqual(
            report["true_read_back_parity"]["freshness_hours_drift_check"]["status"],
            "failed",
        )
        self.assertEqual(report["final_status"], "blocked")
        freshness_mismatch = next(
            item
            for item in report["true_read_back_parity"]["mismatches"]
            if item["field"] == "record.payload.decision_packet.freshness_hours"
        )
        self.assertEqual(
            freshness_mismatch["memory_id"],
            "trendatlas.crypto.decision_episode.beta.family",
        )
        self.assertEqual(
            freshness_mismatch["episode_path"],
            "episodes/trendatlas.crypto.decision_episode.beta.family.json",
        )
        self.assertAlmostEqual(freshness_mismatch["expected"], 0.876389)
        self.assertAlmostEqual(freshness_mismatch["actual"], 0.877389)
        self.assertAlmostEqual(freshness_mismatch["drift_hours"], 0.001)
        self.assertEqual(
            freshness_mismatch["tolerance_hours"],
            self.module.FRESHNESS_HOURS_TOLERANCE_HOURS,
        )


if __name__ == "__main__":
    unittest.main()
