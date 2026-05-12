import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SOURCE_OF_TRUTH_FILES = [
    ROOT / "source_of_truth" / "README.md",
    ROOT / "source_of_truth" / "master_state.md",
    ROOT / "source_of_truth" / "chat_roles.md",
    ROOT / "source_of_truth" / "project_truth.json",
    ROOT / "source_of_truth" / "export_contract.json",
    ROOT / "source_of_truth" / "paths_registry.json",
    ROOT / "source_of_truth" / "current_issues.md",
    ROOT / "source_of_truth" / "pi_codex_runtime_workflow.md",
]


class TestSourceOfTruthPresence(unittest.TestCase):
    def test_required_source_of_truth_files_exist(self):
        missing = [
            str(path.relative_to(ROOT))
            for path in REQUIRED_SOURCE_OF_TRUTH_FILES
            if not path.exists()
        ]
        self.assertFalse(missing, f"Missing source_of_truth files: {missing}")

    def test_required_source_of_truth_files_are_non_empty(self):
        empty_files = []

        for path in REQUIRED_SOURCE_OF_TRUTH_FILES:
            if not path.exists():
                continue
            if path.stat().st_size <= 0:
                empty_files.append(str(path.relative_to(ROOT)))

        self.assertFalse(empty_files, f"Empty source_of_truth files: {empty_files}")


if __name__ == "__main__":
    unittest.main()
