import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REF_66G_PATH = ROOT / "canonical" / "references" / "canonical_66g_reference.json"
BENCHMARK_REF_PATH = ROOT / "canonical" / "references" / "canonical_benchmark_reference.json"
UNIVERSE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_universe_decision.json"
LEVERAGE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalReferenceSeparation(unittest.TestCase):
    def test_66g_reference_has_reference_truth_status(self):
        payload = load_json(REF_66G_PATH)
        self.assertEqual(payload["truth_status"], "reference")

    def test_66g_reference_is_not_current_universe_winner(self):
        payload = load_json(REF_66G_PATH)
        self.assertFalse(payload["reference_summary"]["is_current_universe_winner"])

    def test_66g_reference_is_not_current_live_leverage_truth(self):
        payload = load_json(REF_66G_PATH)
        self.assertFalse(payload["reference_summary"]["is_current_live_leverage_truth"])

    def test_benchmark_reference_has_reference_truth_status(self):
        payload = load_json(BENCHMARK_REF_PATH)
        self.assertEqual(payload["truth_status"], "reference")

    def test_benchmark_reference_is_not_current_live_truth(self):
        payload = load_json(BENCHMARK_REF_PATH)
        self.assertFalse(payload["reference_summary"]["is_current_live_truth"])

    def test_universe_decision_keeps_66g_as_reference_only(self):
        payload = load_json(UNIVERSE_DECISION_PATH)
        reading_rule = payload["decision_summary"]["reading_rule"]
        self.assertIn("66G", reading_rule)
        self.assertIn("reference", reading_rule.lower())

    def test_leverage_decision_keeps_research_experiments_out_of_live_truth(self):
        payload = load_json(LEVERAGE_DECISION_PATH)
        approved_reference_position = payload["decision_summary"]["approved_reference_position"]
        self.assertIn("not current live truth", approved_reference_position.lower())


if __name__ == "__main__":
    unittest.main()