import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_REGISTRY_PATH = ROOT / "canonical" / "output_registry.json"

ALLOWED_LAYERS = {
    "source_of_truth",
    "canonical",
    "raw_output",
    "report",
    "automation",
    "forensic_validation",
}

ALLOWED_DECISION_RELEVANCE = {
    "official_truth",
    "decision_relevant",
    "reference_only",
    "informational",
}


class TestOutputRegistryAllowedValues(unittest.TestCase):
    def load_registry(self) -> dict:
        with OUTPUT_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_layer_values_are_allowed(self):
        payload = self.load_registry()
        failures = []

        for idx, entry in enumerate(payload["outputs"]):
            layer = entry.get("layer")
            if layer not in ALLOWED_LAYERS:
                failures.append(f"outputs[{idx}] invalid layer={layer}")

        self.assertFalse(failures, " | ".join(failures))

    def test_decision_relevance_values_are_allowed(self):
        payload = self.load_registry()
        failures = []

        for idx, entry in enumerate(payload["outputs"]):
            value = entry.get("decision_relevance")
            if value not in ALLOWED_DECISION_RELEVANCE:
                failures.append(f"outputs[{idx}] invalid decision_relevance={value}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()