import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    ROOT / "automation" / "tools" / "apply_truth_patch.py",
    ROOT / "automation" / "schemas" / "apply_log.schema.json",
    ROOT / "automation" / "templates" / "apply_log.template.json",
    ROOT / "automation" / "truth_apply" / "backups" / ".gitkeep",
    ROOT / "automation" / "truth_apply" / "diffs" / ".gitkeep",
    ROOT / "automation" / "truth_apply" / "logs" / ".gitkeep",
    ROOT / "automation" / "truth_patches" / "applied" / ".gitkeep",
]

REQUIRED_DIRS = [
    ROOT / "automation" / "truth_apply",
    ROOT / "automation" / "truth_apply" / "backups",
    ROOT / "automation" / "truth_apply" / "diffs",
    ROOT / "automation" / "truth_apply" / "logs",
    ROOT / "automation" / "truth_patches",
    ROOT / "automation" / "truth_patches" / "applied",
]


class TestAutomationApplyPathsExist(unittest.TestCase):
    def test_required_automation_apply_dirs_exist(self):
        missing = [
            str(path.relative_to(ROOT))
            for path in REQUIRED_DIRS
            if not path.exists() or not path.is_dir()
        ]
        self.assertFalse(missing, f"Missing automation/apply dirs: {missing}")

    def test_required_automation_apply_files_exist(self):
        missing = [
            str(path.relative_to(ROOT))
            for path in REQUIRED_FILES
            if not path.exists() or not path.is_file()
        ]
        self.assertFalse(missing, f"Missing automation/apply files: {missing}")


if __name__ == "__main__":
    unittest.main()