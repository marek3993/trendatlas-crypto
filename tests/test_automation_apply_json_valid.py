import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

JSON_FILES = [
    ROOT / "automation" / "schemas" / "apply_log.schema.json",
    ROOT / "automation" / "templates" / "apply_log.template.json",
]


class TestAutomationApplyJsonValid(unittest.TestCase):
    def test_apply_json_files_exist(self):
        missing = [
            str(path.relative_to(ROOT))
            for path in JSON_FILES
            if not path.exists() or not path.is_file()
        ]
        self.assertFalse(missing, f"Missing automation apply JSON files: {missing}")

    def test_apply_json_files_are_valid_json(self):
        failures = []

        for path in JSON_FILES:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    json.load(handle)
            except Exception as exc:
                failures.append(f"{path.relative_to(ROOT)} invalid JSON: {exc}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()
