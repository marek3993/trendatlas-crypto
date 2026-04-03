import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ID_FILES = [
    ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_universe_decision.json",
    ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json",
    ROOT / "canonical" / "references" / "canonical_66g_reference.json",
    ROOT / "canonical" / "references" / "canonical_benchmark_reference.json",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalIdsUniqueness(unittest.TestCase):
    def test_decision_ids_are_unique(self):
        ids = []
        for path in ID_FILES[:3]:
            payload = load_json(path)
            ids.append(payload["decision_id"])

        self.assertEqual(len(ids), len(set(ids)), f"Duplicate decision_id values: {ids}")

    def test_reference_ids_are_unique(self):
        ids = []
        for path in ID_FILES[3:]:
            payload = load_json(path)
            ids.append(payload["reference_id"])

        self.assertEqual(len(ids), len(set(ids)), f"Duplicate reference_id values: {ids}")

    def test_no_overlap_between_decision_ids_and_reference_ids(self):
        decision_ids = []
        reference_ids = []

        for path in ID_FILES[:3]:
            decision_ids.append(load_json(path)["decision_id"])

        for path in ID_FILES[3:]:
            reference_ids.append(load_json(path)["reference_id"])

        overlap = sorted(set(decision_ids) & set(reference_ids))
        self.assertFalse(overlap, f"Overlapping canonical ids: {overlap}")


if __name__ == "__main__":
    unittest.main()