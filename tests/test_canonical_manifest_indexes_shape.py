import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS_MANIFEST_PATH = ROOT / "canonical" / "manifests" / "canonical_artifacts_manifest.json"
LINEAGE_MANIFEST_PATH = ROOT / "canonical" / "manifests" / "canonical_lineage_manifest.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalManifestIndexesShape(unittest.TestCase):
    def test_artifact_index_exists_and_is_non_empty_list(self):
        payload = load_json(ARTIFACTS_MANIFEST_PATH)
        artifact_index = payload.get("artifact_index")

        self.assertIsInstance(artifact_index, list)
        self.assertTrue(artifact_index)

    def test_artifact_index_entries_have_required_keys(self):
        payload = load_json(ARTIFACTS_MANIFEST_PATH)
        artifact_index = payload["artifact_index"]
        required_keys = {"artifact_name", "artifact_type", "truth_domain", "truth_status", "path", "consumer_scope"}

        failures = []

        for idx, entry in enumerate(artifact_index):
            if not isinstance(entry, dict):
                failures.append(f"artifact_index[{idx}] must be an object")
                continue

            missing = sorted(required_keys - set(entry.keys()))
            if missing:
                failures.append(f"artifact_index[{idx}] missing keys: {missing}")

        self.assertFalse(failures, " | ".join(failures))

    def test_lineage_index_exists_and_is_non_empty_list(self):
        payload = load_json(LINEAGE_MANIFEST_PATH)
        lineage_index = payload.get("lineage_index")

        self.assertIsInstance(lineage_index, list)
        self.assertTrue(lineage_index)

    def test_lineage_index_entries_have_required_keys(self):
        payload = load_json(LINEAGE_MANIFEST_PATH)
        lineage_index = payload["lineage_index"]
        required_keys = {"artifact_name", "path", "producer_script", "source_run_id", "upstream_artifacts"}

        failures = []

        for idx, entry in enumerate(lineage_index):
            if not isinstance(entry, dict):
                failures.append(f"lineage_index[{idx}] must be an object")
                continue

            missing = sorted(required_keys - set(entry.keys()))
            if missing:
                failures.append(f"lineage_index[{idx}] missing keys: {missing}")

        self.assertFalse(failures, " | ".join(failures))

    def test_manifest_index_paths_exist(self):
        failures = []

        for manifest_path, index_key in [
            (ARTIFACTS_MANIFEST_PATH, "artifact_index"),
            (LINEAGE_MANIFEST_PATH, "lineage_index"),
        ]:
            payload = load_json(manifest_path)
            for idx, entry in enumerate(payload[index_key]):
                rel_path = entry.get("path")
                if not isinstance(rel_path, str) or not rel_path.strip():
                    failures.append(f"{manifest_path.relative_to(ROOT)} {index_key}[{idx}] has invalid path")
                    continue

                repo_path = ROOT / rel_path
                if not repo_path.exists():
                    failures.append(
                        f"{manifest_path.relative_to(ROOT)} {index_key}[{idx}] references missing path: {rel_path}"
                    )

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()