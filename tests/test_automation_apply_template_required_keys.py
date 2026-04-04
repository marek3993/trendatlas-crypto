import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "automation" / "templates" / "apply_log.template.json"


class TestAutomationApplyTemplateRequiredKeys(unittest.TestCase):
    def load_json(self):
        with TEMPLATE_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_template_has_required_keys(self):
        payload = self.load_json()
        for key in ["patch_id", "applied_at", "target_files"]:
            self.assertIn(key, payload, f"Missing template key: {key}")

    def test_target_files_is_list(self):
        payload = self.load_json()
        self.assertIsInstance(payload.get("target_files"), list)


if __name__ == "__main__":
    unittest.main()
