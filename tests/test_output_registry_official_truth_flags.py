import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_REGISTRY_PATH = ROOT / "canonical" / "output_registry.json"

EXPECTED_OFFICIAL_TRUTH_PATHS = {
    "source_of_truth/master_state.md",
    "source_of_truth/project_truth.json",
    "source_of_truth/paths_registry.json",
    "source_of_truth/current_issues.md",
}


class TestOutputRegistryOfficialTruthFlags(unittest.TestCase):
    def load_registry(self) -> dict:
        with OUTPUT_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_output_registry_exists(self):
        self.assertTrue(OUTPUT_REGISTRY_PATH.exists(), str(OUTPUT_REGISTRY_PATH.relative_to(ROOT)))

    def test_expected_official_truth_paths_are_flagged_official(self):
        payload = self.load_registry()
        outputs = payload.get("outputs", [])

        outputs_by_path = {entry.get("output_path"): entry for entry in outputs}
        failures = []

        for expected_path in EXPECTED_OFFICIAL_TRUTH_PATHS:
            entry = outputs_by_path.get(expected_path)
            if not entry:
                failures.append(f"Missing output_registry entry: {expected_path}")
                continue

            if entry.get("official_truth") is not True:
                failures.append(f"{expected_path} must have official_truth=true")

            if entry.get("decision_relevance") != "official_truth":
                failures.append(f"{expected_path} must have decision_relevance=official_truth")

            if entry.get("layer") != "source_of_truth":
                failures.append(f"{expected_path} must have layer=source_of_truth")

        self.assertFalse(failures, " | ".join(failures))

    def test_phase68g_output_is_not_official_truth(self):
        payload = self.load_registry()
        outputs = payload.get("outputs", [])
        entry = next(
            (item for item in outputs if item.get("output_path") == "outputs/phase68g_portfolio_exposure_leverage_validation/"),
            None,
        )

        self.assertIsNotNone(entry, "Missing phase68g output_registry entry")
        self.assertFalse(entry.get("official_truth"))
        self.assertEqual(entry.get("decision_relevance"), "decision_relevant")


if __name__ == "__main__":
    unittest.main()