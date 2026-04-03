import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NON_EMPTY_FILES = [
    ROOT / "automation" / "tools" / "apply_truth_patch.py",
    ROOT / "automation" / "schemas" / "apply_log.schema.json",
    ROOT / "automation" / "templates" / "apply_log.template.json",
]


class TestAutomationApplyFilesNonEmpty(unittest.TestCase):
    def test_automation_apply_core_files_are_non_empty(self):
        failures = []

        for path in NON_EMPTY_FILES:
            if not path.exists():
                failures.append(f"Missing file: {path.relative_to(ROOT)}")
                continue

            if path.stat().st_size <= 0:
                failures.append(f"Empty file: {path.relative_to(ROOT)}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()