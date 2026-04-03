import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

LEVERAGE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json"
REF_66G_PATH = ROOT / "canonical" / "references" / "canonical_66g_reference.json"
BENCHMARK_REF_PATH = ROOT / "canonical" / "references" / "canonical_benchmark_reference.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalBooleanFlags(unittest.TestCase):
    def test_leverage_decision_boolean_flag_type(self):
        payload = load_json(LEVERAGE_DECISION_PATH)
        value = payload["decision_summary"]["is_live_leverage_enabled"]
        self.assertIsInstance(value, bool)

    def test_66g_reference_boolean_flag_types(self):
        payload = load_json(REF_66G_PATH)
        summary = payload["reference_summary"]

        self.assertIsInstance(summary["is_current_universe_winner"], bool)
        self.assertIsInstance(summary["is_current_live_leverage_truth"], bool)

    def test_benchmark_reference_boolean_flag_type(self):
        payload = load_json(BENCHMARK_REF_PATH)
        value = payload["reference_summary"]["is_current_live_truth"]
        self.assertIsInstance(value, bool)


if __name__ == "__main__":
    unittest.main()