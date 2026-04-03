import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_REGISTRY_PATH = ROOT / "canonical" / "output_registry.json"

REQUIRED_FIELDS = {
    "output_path",
    "layer",
    "decision_relevance",
    "official_truth",
}


class TestOutputRegistryRequiredFields(unittest.TestCase):
    def load_registry(self) -> dict:
        with OUTPUT_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_output_registry_outputs_block_exists(self):
        payload = self.load_registry()
        outputs = payload.get("outputs")

        self.assertIsInstance(outputs, list)
        self.assertTrue(outputs)

    def test_output_entries_have_required_fields(self):
        payload = self.load_registry()
        failures = []

        for idx, entry in enumerate(payload["outputs"]):
            if not isinstance(entry, dict):
                failures.append(f"outputs[{idx}] must be object")
                continue

            missing = sorted(REQUIRED_FIELDS - set(entry.keys()))
            if missing:
                failures.append(f"outputs[{idx}] missing fields: {missing}")

        self.assertFalse(failures, " | ".join(failures))

    def test_required_field_shapes_are_valid(self):
        payload = self.load_registry()
        failures = []

        for idx, entry in enumerate(payload["outputs"]):
            if not isinstance(entry.get("output_path"), str) or not entry["output_path"].strip():
                failures.append(f"outputs[{idx}] invalid output_path")
            if not isinstance(entry.get("layer"), str) or not entry["layer"].strip():
                failures.append(f"outputs[{idx}] invalid layer")
            if not isinstance(entry.get("decision_relevance"), str) or not entry["decision_relevance"].strip():
                failures.append(f"outputs[{idx}] invalid decision_relevance")
            if not isinstance(entry.get("official_truth"), bool):
                failures.append(f"outputs[{idx}] official_truth must be bool")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()