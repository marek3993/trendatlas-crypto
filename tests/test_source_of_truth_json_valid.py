import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

JSON_FILES = [
    ROOT / "source_of_truth" / "project_truth.json",
    ROOT / "source_of_truth" / "paths_registry.json",
]


class TestSourceOfTruthJsonValid(unittest.TestCase):
    def test_source_of_truth_json_files_exist(self):
        missing = [str(path.relative_to(ROOT)) for path in JSON_FILES if not path.exists()]
        self.assertFalse(missing, f"Missing source_of_truth JSON files: {missing}")

    def test_source_of_truth_json_files_are_valid_json(self):
        failures = []

        for path in JSON_FILES:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    json.load(handle)
            except Exception as exc:
                failures.append(f"{path.relative_to(ROOT)} invalid JSON: {exc}")

        self.assertFalse(failures, " | ".join(failures))

    def test_source_of_truth_json_roots_are_objects(self):
        failures = []

        for path in JSON_FILES:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)

            if not isinstance(payload, dict):
                failures.append(f"{path.relative_to(ROOT)} root must be JSON object")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()