import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "automation" / "schemas" / "apply_log.schema.json"


class TestAutomationApplySchemaRequiredKeys(unittest.TestCase):
    def load_json(self):
        with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_schema_has_required_top_level_keys(self):
        payload = self.load_json()
        for key in ["type", "properties"]:
            self.assertIn(key, payload, f"Missing schema key: {key}")

    def test_schema_properties_contains_expected_fields(self):
        payload = self.load_json()
        props = payload.get("properties", {})
        expected_any = [
            "patch_id",
            "applied_at",
            "target_files",
        ]
        missing = [key for key in expected_any if key not in props]
        self.assertFalse(missing, f"Schema missing expected properties: {missing}")


if __name__ == "__main__":
    unittest.main()
