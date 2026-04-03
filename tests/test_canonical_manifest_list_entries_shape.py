import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ARTIFACTS_MANIFEST_PATH = ROOT / "canonical" / "manifests" / "canonical_artifacts_manifest.json"
LINEAGE_MANIFEST_PATH = ROOT / "canonical" / "manifests" / "canonical_lineage_manifest.json"
PRODUCT_MANIFEST_PATH = ROOT / "canonical" / "manifests" / "canonical_product_manifest.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalManifestListEntriesShape(unittest.TestCase):
    def test_artifact_index_entry_shapes(self):
        payload = load_json(ARTIFACTS_MANIFEST_PATH)
        failures = []

        for idx, entry in enumerate(payload["artifact_index"]):
            if not isinstance(entry.get("artifact_name"), str) or not entry["artifact_name"].strip():
                failures.append(f"artifact_index[{idx}] invalid artifact_name")
            if not isinstance(entry.get("artifact_type"), str) or not entry["artifact_type"].strip():
                failures.append(f"artifact_index[{idx}] invalid artifact_type")
            if not isinstance(entry.get("truth_domain"), str) or not entry["truth_domain"].strip():
                failures.append(f"artifact_index[{idx}] invalid truth_domain")
            if not isinstance(entry.get("truth_status"), str) or not entry["truth_status"].strip():
                failures.append(f"artifact_index[{idx}] invalid truth_status")
            if not isinstance(entry.get("path"), str) or not entry["path"].strip():
                failures.append(f"artifact_index[{idx}] invalid path")
            if not isinstance(entry.get("consumer_scope"), list) or not entry["consumer_scope"]:
                failures.append(f"artifact_index[{idx}] invalid consumer_scope")

        self.assertFalse(failures, " | ".join(failures))

    def test_lineage_index_entry_shapes(self):
        payload = load_json(LINEAGE_MANIFEST_PATH)
        failures = []

        for idx, entry in enumerate(payload["lineage_index"]):
            if not isinstance(entry.get("artifact_name"), str) or not entry["artifact_name"].strip():
                failures.append(f"lineage_index[{idx}] invalid artifact_name")
            if not isinstance(entry.get("path"), str) or not entry["path"].strip():
                failures.append(f"lineage_index[{idx}] invalid path")
            if not isinstance(entry.get("producer_script"), str) or not entry["producer_script"].strip():
                failures.append(f"lineage_index[{idx}] invalid producer_script")
            if not isinstance(entry.get("upstream_artifacts"), list):
                failures.append(f"lineage_index[{idx}] invalid upstream_artifacts")

        self.assertFalse(failures, " | ".join(failures))

    def test_product_manifest_artifact_dependencies_shape(self):
        payload = load_json(PRODUCT_MANIFEST_PATH)
        failures = []

        for idx, entry in enumerate(payload["artifact_dependencies"]):
            if not isinstance(entry.get("artifact_name"), str) or not entry["artifact_name"].strip():
                failures.append(f"artifact_dependencies[{idx}] invalid artifact_name")
            if not isinstance(entry.get("role"), str) or not entry["role"].strip():
                failures.append(f"artifact_dependencies[{idx}] invalid role")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()