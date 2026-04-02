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

ALLOWED_TRUTH_STATUSES = {
    "exploratory",
    "candidate",
    "reference",
    "official",
    "deprecated",
    "superseded",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalTruthStatusAllowedValues(unittest.TestCase):
    def test_truth_status_is_in_allowed_set(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            truth_status = payload.get("truth_status")

            if truth_status not in ALLOWED_TRUTH_STATUSES:
                failures.append(
                    f"{path.relative_to(ROOT)} invalid truth_status={truth_status}"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_truth_status_is_non_empty_string(self):
        failures = []

        for path in CANONICAL_JSON_FILES:
            payload = load_json(path)
            truth_status = payload.get("truth_status")

            if not isinstance(truth_status, str) or not truth_status.strip():
                failures.append(
                    f"{path.relative_to(ROOT)} truth_status must be non-empty string"
                )

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()