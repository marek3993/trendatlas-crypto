import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DECISION_FILES = [
    ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_universe_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalDecisionScopeListsAreStrings(unittest.TestCase):
    def test_covers_contains_only_non_empty_strings(self):
        failures = []

        for path in DECISION_FILES:
            payload = load_json(path)
            covers = payload["decision_scope"]["covers"]

            if not isinstance(covers, list):
                failures.append(f"{path.relative_to(ROOT)} covers must be a list")
                continue

            invalid = [item for item in covers if not isinstance(item, str) or not item.strip()]
            if invalid:
                failures.append(f"{path.relative_to(ROOT)} covers contains invalid entries")

        self.assertFalse(failures, " | ".join(failures))

    def test_does_not_cover_contains_only_non_empty_strings(self):
        failures = []

        for path in DECISION_FILES:
            payload = load_json(path)
            does_not_cover = payload["decision_scope"]["does_not_cover"]

            if not isinstance(does_not_cover, list):
                failures.append(f"{path.relative_to(ROOT)} does_not_cover must be a list")
                continue

            invalid = [item for item in does_not_cover if not isinstance(item, str) or not item.strip()]
            if invalid:
                failures.append(f"{path.relative_to(ROOT)} does_not_cover contains invalid entries")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()