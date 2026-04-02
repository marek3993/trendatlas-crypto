import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REFERENCE_FILES = [
    ROOT / "canonical" / "references" / "canonical_66g_reference.json",
    ROOT / "canonical" / "references" / "canonical_benchmark_reference.json",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalReferenceSummaryBlocksPresent(unittest.TestCase):
    def test_reference_files_have_non_empty_reference_summary(self):
        failures = []

        for path in REFERENCE_FILES:
            payload = load_json(path)
            reference_summary = payload.get("reference_summary")

            if not isinstance(reference_summary, dict) or not reference_summary:
                failures.append(f"{path.relative_to(ROOT)} missing non-empty reference_summary")

        self.assertFalse(failures, " | ".join(failures))

    def test_reference_files_have_non_empty_reference_rules(self):
        failures = []

        for path in REFERENCE_FILES:
            payload = load_json(path)
            reference_rules = payload.get("reference_rules")

            if not isinstance(reference_rules, dict) or not reference_rules:
                failures.append(f"{path.relative_to(ROOT)} missing non-empty reference_rules")

        self.assertFalse(failures, " | ".join(failures))

    def test_reference_rules_contain_usage_boundaries(self):
        failures = []

        for path in REFERENCE_FILES:
            payload = load_json(path)
            reference_rules = payload.get("reference_rules", {})

            must_not_be_used_as = reference_rules.get("must_not_be_used_as")
            may_be_used_as = reference_rules.get("may_be_used_as")

            if not isinstance(must_not_be_used_as, list) or not must_not_be_used_as:
                failures.append(f"{path.relative_to(ROOT)} invalid must_not_be_used_as block")

            if not isinstance(may_be_used_as, list) or not may_be_used_as:
                failures.append(f"{path.relative_to(ROOT)} invalid may_be_used_as block")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()