import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STRATEGY_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json"
STRATEGY_SNAPSHOT_PATH = ROOT / "canonical" / "manifests" / "canonical_strategy_snapshot.json"
UNIVERSE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_universe_decision.json"
LEVERAGE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json"
REF_66G_PATH = ROOT / "canonical" / "references" / "canonical_66g_reference.json"
BENCHMARK_REF_PATH = ROOT / "canonical" / "references" / "canonical_benchmark_reference.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalTruthConsistency(unittest.TestCase):
    def test_strategy_decision_and_snapshot_are_consistent(self):
        decision = load_json(STRATEGY_DECISION_PATH)
        snapshot = load_json(STRATEGY_SNAPSHOT_PATH)

        decision_summary = decision["decision_summary"]
        current_state = snapshot["current_state"]

        self.assertEqual(
            decision_summary["official_core_production_baseline"],
            current_state["official_core_production_baseline"]["value"],
        )
        self.assertEqual(
            decision_summary["official_universe_winner"],
            current_state["official_universe_winner"]["value"],
        )
        self.assertEqual(
            decision_summary["product_direction"],
            current_state["product_direction"]["value"],
        )
        self.assertEqual(
            decision_summary["live_leverage_truth"],
            current_state["live_leverage_truth"]["value"],
        )

    def test_universe_decision_matches_strategy_snapshot(self):
        universe_decision = load_json(UNIVERSE_DECISION_PATH)
        snapshot = load_json(STRATEGY_SNAPSHOT_PATH)

        self.assertEqual(
            universe_decision["decision_summary"]["official_universe_winner"],
            snapshot["current_state"]["official_universe_winner"]["value"],
        )

        self.assertEqual(
            universe_decision["decision_summary"]["reference_baseline"],
            snapshot["current_state"]["official_core_production_baseline"]["value"],
        )

    def test_leverage_decision_matches_strategy_snapshot(self):
        leverage_decision = load_json(LEVERAGE_DECISION_PATH)
        snapshot = load_json(STRATEGY_SNAPSHOT_PATH)

        self.assertEqual(
            leverage_decision["decision_summary"]["current_live_leverage_mode"],
            snapshot["current_state"]["live_leverage_truth"]["value"],
        )

    def test_66g_reference_is_not_marked_as_current_universe_winner_or_live_leverage_truth(self):
        reference_payload = load_json(REF_66G_PATH)
        reference_summary = reference_payload["reference_summary"]

        self.assertEqual(reference_payload["truth_status"], "reference")
        self.assertFalse(reference_summary["is_current_universe_winner"])
        self.assertFalse(reference_summary["is_current_live_leverage_truth"])

    def test_benchmark_reference_is_not_marked_as_current_live_truth(self):
        benchmark_payload = load_json(BENCHMARK_REF_PATH)
        reference_summary = benchmark_payload["reference_summary"]

        self.assertEqual(benchmark_payload["truth_status"], "reference")
        self.assertFalse(reference_summary["is_current_live_truth"])

    def test_product_direction_mentions_btc_benchmark(self):
        decision = load_json(STRATEGY_DECISION_PATH)
        self.assertIn("BTC benchmark", decision["decision_summary"]["product_direction"])


if __name__ == "__main__":
    unittest.main()