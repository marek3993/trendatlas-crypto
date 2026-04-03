import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_REGISTRY_PATH = ROOT / "canonical" / "output_registry.json"

EXPECTED_SOURCE_OF_TRUTH_OUTPUTS = {
    "source_of_truth/master_state.md",
    "source_of_truth/project_truth.json",
    "source_of_truth/paths_registry.json",
    "source_of_truth/current_issues.md",
}


class TestOutputRegistrySourceOfTruthConsistency(unittest.TestCase):
    def load_registry(self) -> dict:
        with OUTPUT_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_expected_source_of_truth_outputs_exist(self):
        payload = self.load_registry()
        outputs = payload.get("outputs", [])
        seen = {entry.get("output_path") for entry in outputs if isinstance(entry, dict)}

        missing = sorted(EXPECTED_SOURCE_OF_TRUTH_OUTPUTS - seen)
        self.assertFalse(missing, f"Missing source_of_truth outputs in registry: {missing}")

    def test_source_of_truth_outputs_are_flagged_consistently(self):
        payload = self.load_registry()
        outputs = payload.get("outputs", [])
        by_path = {entry.get("output_path"): entry for entry in outputs if isinstance(entry, dict)}
        failures = []

        for path in EXPECTED_SOURCE_OF_TRUTH_OUTPUTS:
            entry = by_path[path]
            if entry.get("layer") != "source_of_truth":
                failures.append(f"{path} must have layer=source_of_truth")
            if entry.get("official_truth") is not True:
                failures.append(f"{path} must have official_truth=true")
            if entry.get("decision_relevance") != "official_truth":
                failures.append(f"{path} must have decision_relevance=official_truth")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()