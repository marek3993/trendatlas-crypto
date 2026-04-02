import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CANONICAL_JSON_FILES = [
    ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_universe_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json",
    ROOT / "canonical" / "manifests" / "canonical_artifacts_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_lineage_manifest.json",
    ROOT / "canonical" / "manifests" / "canonical_strategy_snapshot.json",
    ROOT / "canonical" / "manifests" / "canonical_product_manifest.json",
    ROOT / "canonical" / "exports" / "canonical_product_export_contract.json",
    ROOT / "canonical" / "references" / "canonical_66g_reference.json",
    ROOT / "canonical" / "references" / "canonical_benchmark_reference.json",
]

ALLOWED_ARTIFACT_TYPES = {
    "decision",
    "snapshot",
    "manifest",
    "export",
    "reference",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalArtifactTypeAllowedValues(unittest.TestCase):
    def test_artifact_type_is_in_allowed_set(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            artifact_type = payload.get("artifact_type")

            if artifact_type not in ALLOWED_ARTIFACT_TYPES:
                failures.append(
                    f"{path.relative_to(ROOT)} invalid artifact_type={artifact_type}"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_artifact_type_is_non_empty_string(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            artifact_type = payload.get("artifact_type")

            if not isinstance(artifact_type, str) or not artifact_type.strip():
                failures.append(
                    f"{path.relative_to(ROOT)} artifact_type must be non-empty string"
                )

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()