import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STRATEGY_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json"
UNIVERSE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_universe_decision.json"
LEVERAGE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalDecisionSummaryRequiredKeys(unittest.TestCase):
    def test_strategy_decision_summary_required_keys(self):
        payload = load_json(STRATEGY_DECISION_PATH)
        summary = payload["decision_summary"]

        required = {
            "official_core_production_baseline",
            "official_universe_winner",
            "product_direction",
            "live_leverage_truth",
        }
        missing = sorted(required - set(summary.keys()))
        self.assertFalse(missing, f"Missing strategy decision summary keys: {missing}")

    def test_universe_decision_summary_required_keys(self):
        payload = load_json(UNIVERSE_DECISION_PATH)
        summary = payload["decision_summary"]

        required = {
            "official_universe_winner",
            "reference_baseline",
            "reading_rule",
            "product_direction_alignment",
        }
        missing = sorted(required - set(summary.keys()))
        self.assertFalse(missing, f"Missing universe decision summary keys: {missing}")

    def test_leverage_decision_summary_required_keys(self):
        payload = load_json(LEVERAGE_DECISION_PATH)
        summary = payload["decision_summary"]

        required = {
            "current_live_leverage_mode",
            "is_live_leverage_enabled",
            "approved_reference_position",
            "downstream_rule",
        }
        missing = sorted(required - set(summary.keys()))
        self.assertFalse(missing, f"Missing leverage decision summary keys: {missing}")


if __name__ == "__main__":
    unittest.main()