import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DECISION_FILES = [
    ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_universe_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json",
]

REFERENCE_FILES = [
    ROOT / "canonical" / "references" / "canonical_66g_reference.json",
    ROOT / "canonical" / "references" / "canonical_benchmark_reference.json",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalDecisionIdsPresent(unittest.TestCase):
    def test_decision_files_have_non_empty_decision_id(self):
        failures = []

        for path in DECISION_FILES:
            payload = load_json(path)
            decision_id = payload.get("decision_id")

            if not isinstance(decision_id, str) or not decision_id.strip():
                failures.append(f"{path.relative_to(ROOT)} missing valid decision_id")

        self.assertFalse(failures, " | ".join(failures))

    def test_reference_files_have_non_empty_reference_id(self):
        failures = []

        for path in REFERENCE_FILES:
            payload = load_json(path)
            reference_id = payload.get("reference_id")

            if not isinstance(reference_id, str) or not reference_id.strip():
                failures.append(f"{path.relative_to(ROOT)} missing valid reference_id")

        self.assertFalse(failures, " | ".join(failures))

    def test_decision_ids_match_artifact_prefix(self):
        failures = []

        for path in DECISION_FILES:
            payload = load_json(path)
            artifact_name = payload["artifact_name"]
            decision_id = payload["decision_id"]

            expected_prefix = artifact_name + "_"
            if not decision_id.startswith(expected_prefix):
                failures.append(
                    f"{path.relative_to(ROOT)} decision_id must start with {expected_prefix}"
                )

        self.assertFalse(failures, " | ".join(failures))

    def test_reference_ids_match_artifact_prefix(self):
        failures = []

        for path in REFERENCE_FILES:
            payload = load_json(path)
            artifact_name = payload["artifact_name"]
            reference_id = payload["reference_id"]

            expected_prefix = artifact_name + "_"
            if not reference_id.startswith(expected_prefix):
                failures.append(
                    f"{path.relative_to(ROOT)} reference_id must start with {expected_prefix}"
                )

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()