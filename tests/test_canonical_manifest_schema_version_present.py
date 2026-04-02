import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MANIFEST_FILES = [
    ROOT / "canonical" / "manifests" / "canonical_artifacts_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_lineage_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_product_manifest.json",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalManifestSchemaVersionPresent(unittest.TestCase):
    def test_manifest_files_have_schema_version(self):
        failures = []

        for path in MANIFEST_FILES:
            payload = load_json(path)
            schema_version = payload.get("schema_version")

            if not isinstance(schema_version, str) or not schema_version.strip():
                failures.append(f"{path.relative_to(ROOT)} missing valid schema_version")

        self.assertFalse(failures, " | ".join(failures))

    def test_manifest_schema_version_uses_v_prefix(self):
        failures = []

        for path in MANIFEST_FILES:
            payload = load_json(path)
            schema_version = payload.get("schema_version", "")

            if not isinstance(schema_version, str) or not schema_version.startswith("v"):
                failures.append(
                    f"{path.relative_to(ROOT)} schema_version must start with 'v'"
                )

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()