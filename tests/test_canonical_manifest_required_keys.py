import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MANIFEST_FILES = [
    ROOT / "canonical" / "manifests" / "canonical_artifacts_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_lineage_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_product_manifest.json",
]

REQUIRED_KEYS_BY_FILE = {
    "canonical_artifacts_manifest.json": {"schema_version", "canonical_domains", "canonical_artifact_types", "artifact_index"},
    "canonical_lineage_manifest.json": {"schema_version", "lineage_rules", "lineage_index"},
    "canonical_product_manifest.json": {"schema_version", "product_truth_contract", "artifact_dependencies"},
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalManifestRequiredKeys(unittest.TestCase):
    def test_manifest_specific_required_keys_exist(self):
        failures = []

        for path in MANIFEST_FILES:
            payload = load_json(path)
            required = REQUIRED_KEYS_BY_FILE[path.name]
            missing = sorted(required - set(payload.keys()))
            if missing:
                failures.append(f"{path.relative_to(ROOT)} missing keys: {missing}")

        self.assertFalse(failures, " | ".join(failures))

    def test_manifest_specific_required_keys_are_not_empty(self):
        failures = []

        for path in MANIFEST_FILES:
            payload = load_json(path)
            required = REQUIRED_KEYS_BY_FILE[path.name]

            for key in required:
                value = payload.get(key)
                if value is None:
                    failures.append(f"{path.relative_to(ROOT)} null key: {key}")
                    continue
                if isinstance(value, (list, dict, str)) and len(value) == 0:
                    failures.append(f"{path.relative_to(ROOT)} empty key: {key}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()