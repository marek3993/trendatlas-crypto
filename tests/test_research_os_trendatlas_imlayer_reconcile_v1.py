import importlib.util
import json
import shutil
import unittest
from pathlib import Path


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
            {
                "schema_version": "trendatlas.imlayer.decision_episode.v1",
                "memory_id": "trendatlas.crypto.decision_episode.alpha.family",
            },
        )
        write_json(
            export_root / episode_paths[1],
            {
                "schema_version": "trendatlas.imlayer.decision_episode.v1",
                "memory_id": "trendatlas.crypto.decision_episode.beta.family",
            },
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

    def test_reconcile_reports_passed_write_ack_but_blocked_true_read_back_without_read_surface(self) -> None:
        batch_id, export_root, ingestion_manifest_path = self.create_batch_fixture(include_second_result=True)

        report = self.module.reconcile_batch(
            batch_id=batch_id,
            batch_root=str(export_root),
            ingestion_manifest=str(ingestion_manifest_path),
            ingestion_root=None,
            project_root=self.temp_dir,
        )

        self.assertEqual(report["write_ack_parity"]["status"], "passed")
        self.assertEqual(report["true_read_back_parity"]["status"], "blocked")
        self.assertEqual(report["final_status"], "blocked")
        self.assertIn(
            "No repo-local imLayer read contract was found",
            report["true_read_back_parity"]["blocker"],
        )
        minimal_read_surface = report["true_read_back_parity"]["minimal_read_surface_v1"]
        self.assertEqual(minimal_read_surface["status"], "proposal_only")
        self.assertEqual(
            minimal_read_surface["required_iml_change"]["path_template"],
            "/api/v1/reads/decision-episodes/{memory_id}",
        )
        self.assertEqual(
            len(minimal_read_surface["batch_verification_targets"]),
            2,
        )
        self.assertEqual(
            minimal_read_surface["batch_verification_targets"][0]["memory_id"],
            "trendatlas.crypto.decision_episode.alpha.family",
        )
        self.assertIn(
            "sha256(canonical_json(response.record)) matches expected payload_sha256",
            minimal_read_surface["trendatlas_verification_rule"]["required_checks"],
        )

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


if __name__ == "__main__":
    unittest.main()
