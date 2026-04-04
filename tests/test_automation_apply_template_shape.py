import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "automation" / "schemas" / "apply_log.schema.json"
TEMPLATE_PATH = ROOT / "automation" / "templates" / "apply_log.template.json"


class TestAutomationApplyTemplateShape(unittest.TestCase):
    def load_json(self, path: Path):
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_schema_and_template_exist(self):
        self.assertTrue(SCHEMA_PATH.exists(), f"Missing file: {SCHEMA_PATH.relative_to(ROOT)}")
        self.assertTrue(TEMPLATE_PATH.exists(), f"Missing file: {TEMPLATE_PATH.relative_to(ROOT)}")

    def test_schema_root_is_object(self):
        payload = self.load_json(SCHEMA_PATH)
        self.assertIsInstance(payload, dict)

    def test_template_root_is_object(self):
        payload = self.load_json(TEMPLATE_PATH)
        self.assertIsInstance(payload, dict)

    def test_schema_has_basic_contract_keys(self):
        payload = self.load_json(SCHEMA_PATH)
        self.assertIn("type", payload)
        self.assertIn("properties", payload)

    def test_template_has_basic_apply_fields(self):
        payload = self.load_json(TEMPLATE_PATH)
        required_any = [
            "patch_id",
            "applied_at",
            "target_files",
        ]
        missing = [key for key in required_any if key not in payload]
        self.assertFalse(missing, f"Template missing expected keys: {missing}")


if __name__ == "__main__":
    unittest.main()
