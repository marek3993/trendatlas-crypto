import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_REGISTRY_PATH = ROOT / "canonical" / "script_registry.json"

REQUIRED_FIELDS = {
    "script_path",
    "layer",
    "status",
    "purpose",
    "output_type",
    "decision_relevance",
    "writes_source_of_truth",
    "notes",
}


class TestScriptRegistryRequiredFields(unittest.TestCase):
    def load_registry(self) -> dict:
        with SCRIPT_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_script_registry_scripts_block_exists(self):
        payload = self.load_registry()
        scripts = payload.get("scripts")

        self.assertIsInstance(scripts, list)
        self.assertTrue(scripts)

    def test_script_entries_have_required_fields(self):
        payload = self.load_registry()
        failures = []

        for idx, entry in enumerate(payload["scripts"]):
            if not isinstance(entry, dict):
                failures.append(f"scripts[{idx}] must be object")
                continue

            missing = sorted(REQUIRED_FIELDS - set(entry.keys()))
            if missing:
                failures.append(f"scripts[{idx}] missing fields: {missing}")

        self.assertFalse(failures, " | ".join(failures))

    def test_required_field_shapes_are_valid(self):
        payload = self.load_registry()
        failures = []

        for idx, entry in enumerate(payload["scripts"]):
            if not isinstance(entry.get("script_path"), str) or not entry["script_path"].strip():
                failures.append(f"scripts[{idx}] invalid script_path")
            if not isinstance(entry.get("layer"), str) or not entry["layer"].strip():
                failures.append(f"scripts[{idx}] invalid layer")
            if not isinstance(entry.get("status"), str) or not entry["status"].strip():
                failures.append(f"scripts[{idx}] invalid status")
            if not isinstance(entry.get("purpose"), str) or not entry["purpose"].strip():
                failures.append(f"scripts[{idx}] invalid purpose")
            if not isinstance(entry.get("output_type"), str) or not entry["output_type"].strip():
                failures.append(f"scripts[{idx}] invalid output_type")
            if not isinstance(entry.get("decision_relevance"), str) or not entry["decision_relevance"].strip():
                failures.append(f"scripts[{idx}] invalid decision_relevance")
            if not isinstance(entry.get("writes_source_of_truth"), bool):
                failures.append(f"scripts[{idx}] writes_source_of_truth must be bool")
            if not isinstance(entry.get("notes"), str) or not entry["notes"].strip():
                failures.append(f"scripts[{idx}] invalid notes")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()