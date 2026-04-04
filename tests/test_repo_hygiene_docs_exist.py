import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DOCS = [
    ROOT / "repo_artifact_contract.md",
    ROOT / "commit_hygiene_rules.md",
    ROOT / "artifact_status_rules.md",
    ROOT / "track_vs_ignore_rules.md",
]


class TestRepoHygieneDocsExist(unittest.TestCase):
    def test_required_repo_hygiene_docs_exist(self):
        missing = [
            str(path.relative_to(ROOT))
            for path in REQUIRED_DOCS
            if not path.exists() or not path.is_file()
        ]
        self.assertFalse(missing, f"Missing hygiene docs: {missing}")

    def test_required_repo_hygiene_docs_are_non_empty(self):
        empty = [
            str(path.relative_to(ROOT))
            for path in REQUIRED_DOCS
            if path.exists() and path.stat().st_size <= 0
        ]
        self.assertFalse(empty, f"Empty hygiene docs: {empty}")


if __name__ == "__main__":
    unittest.main()