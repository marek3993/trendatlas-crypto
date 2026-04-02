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


class TestCanonicalDecisionSummaryBlocksPresent(unittest.TestCase):
    def test_decision_files_have_non_empty_decision_summary(self):
        failures = []

        for path in DECISION_FILES:
            payload = load_json(path)
            decision_summary = payload.get("decision_summary")

            if not isinstance(decision_summary, dict) or not decision_summary:
                failures.append(f"{path.relative_to(ROOT)} missing non-empty decision_summary")

        self.assertFalse(failures, " | ".join(failures))

    def test_decision_files_have_non_empty_decision_scope(self):
        failures = []

        for path in DECISION_FILES:
            payload = load_json(path)
            decision_scope = payload.get("decision_scope")

            if not isinstance(decision_scope, dict) or not decision_scope:
                failures.append(f"{path.relative_to(ROOT)} missing non-empty decision_scope")

        self.assertFalse(failures, " | ".join(failures))

    def test_decision_scope_contains_covers_and_does_not_cover(self):
        failures = []

        for path in DECISION_FILES:
            payload = load_json(path)
            decision_scope = payload.get("decision_scope", {})

            covers = decision_scope.get("covers")
            does_not_cover = decision_scope.get("does_not_cover")

            if not isinstance(covers, list) or not covers:
                failures.append(f"{path.relative_to(ROOT)} invalid covers block")

            if not isinstance(does_not_cover, list) or not does_not_cover:
                failures.append(f"{path.relative_to(ROOT)} invalid does_not_cover block")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()