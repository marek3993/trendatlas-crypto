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


class TestCanonicalReferenceRuleListsAreStrings(unittest.TestCase):
    def test_may_be_used_as_contains_only_non_empty_strings(self):
        failures = []

        for path in REFERENCE_FILES:
            payload = load_json(path)
            may_be_used_as = payload["reference_rules"]["may_be_used_as"]

            if not isinstance(may_be_used_as, list):
                failures.append(f"{path.relative_to(ROOT)} may_be_used_as must be a list")
                continue

            invalid = [item for item in may_be_used_as if not isinstance(item, str) or not item.strip()]
            if invalid:
                failures.append(f"{path.relative_to(ROOT)} may_be_used_as contains invalid entries")

        self.assertFalse(failures, " | ".join(failures))

    def test_must_not_be_used_as_contains_only_non_empty_strings(self):
        failures = []

        for path in REFERENCE_FILES:
            payload = load_json(path)
            must_not_be_used_as = payload["reference_rules"]["must_not_be_used_as"]

            if not isinstance(must_not_be_used_as, list):
                failures.append(f"{path.relative_to(ROOT)} must_not_be_used_as must be a list")
                continue

            invalid = [item for item in must_not_be_used_as if not isinstance(item, str) or not item.strip()]
            if invalid:
                failures.append(f"{path.relative_to(ROOT)} must_not_be_used_as contains invalid entries")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()