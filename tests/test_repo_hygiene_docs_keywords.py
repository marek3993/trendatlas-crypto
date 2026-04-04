import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DOC_RULES = {
    ROOT / "repo_artifact_contract.md": [
        "source_of_truth",
        "canonical",
        "Artifact taxonomy",
        "Directory contract",
        "Metric lineage contract",
    ],
    ROOT / "commit_hygiene_rules.md": [
        "Jeden commit = jedna téma",
        "generated outputs",
        "truth commit",
        "hygiene commit",
    ],
    ROOT / "artifact_status_rules.md": [
        "official",
        "reference",
        "generated",
        "support_only",
        "retired",
    ],
    ROOT / "track_vs_ignore_rules.md": [
        "Track",
        "Defaultne netrackovať",
        "outputs/",
        "research_os/runs/",
        "automation/screenshots/",
    ],
}


class TestRepoHygieneDocsKeywords(unittest.TestCase):
    def test_docs_contain_required_keywords(self):
        failures = []

        for path, keywords in DOC_RULES.items():
            if not path.exists():
                failures.append(f"Missing file: {path.relative_to(ROOT)}")
                continue

            text = path.read_text(encoding="utf-8")

            for keyword in keywords:
                if keyword not in text:
                    failures.append(f"{path.relative_to(ROOT)} missing keyword: {keyword}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()
