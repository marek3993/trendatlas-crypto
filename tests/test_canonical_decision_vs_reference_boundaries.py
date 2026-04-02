import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STRATEGY_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_strategy_decision.json"
UNIVERSE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_universe_decision.json"
LEVERAGE_DECISION_PATH = ROOT / "canonical" / "decisions" / "canonical_leverage_decision.json"
REF_66G_PATH = ROOT / "canonical" / "references" / "canonical_66g_reference.json"
BENCHMARK_REF_PATH = ROOT / "canonical" / "references" / "canonical_benchmark_reference.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalDecisionVsReferenceBoundaries(unittest.TestCase):
    def test_decisions_are_official_and_references_are_reference(self):
        decision_paths = [
            STRATEGY_DECISION_PATH,
            UNIVERSE_DECISION_PATH,
            LEVERAGE_DECISION_PATH,
        ]
        reference_paths = [
            REF_66G_PATH,
            BENCHMARK_REF_PATH,
        ]

        for path in decision_paths:
            payload = load_json(path)
            self.assertEqual(payload["truth_status"], "official", str(path.relative_to(ROOT)))

        for path in reference_paths:
            payload = load_json(path)
            self.assertEqual(payload["truth_status"], "reference", str(path.relative_to(ROOT)))

    def test_66g_reference_does_not_replace_universe_decision(self):
        universe_decision = load_json(UNIVERSE_DECISION_PATH)
        reference_66g = load_json(REF_66G_PATH)

        self.assertEqual(
            universe_decision["decision_summary"]["official_universe_winner"],
            "phase67j_no_neo_main",
        )
        self.assertEqual(
            reference_66g["reference_summary"]["reference_name"],
            "phase66g_production_soft_filters",
        )
        self.assertNotEqual(
            universe_decision["decision_summary"]["official_universe_winner"],
            reference_66g["reference_summary"]["reference_name"],
        )

    def test_leverage_decision_keeps_live_truth_separate_from_reference_role(self):
        leverage_decision = load_json(LEVERAGE_DECISION_PATH)
        benchmark_reference = load_json(BENCHMARK_REF_PATH)

        self.assertEqual(
            leverage_decision["decision_summary"]["current_live_leverage_mode"],
            "1.0x without leverage",
        )
        self.assertFalse(
            benchmark_reference["reference_summary"]["is_current_live_truth"]
        )

    def test_reference_rules_contain_must_not_be_used_as(self):
        for path in [REF_66G_PATH, BENCHMARK_REF_PATH]:
            payload = load_json(path)
            reference_rules = payload.get("reference_rules", {})
            self.assertIn("must_not_be_used_as", reference_rules, str(path.relative_to(ROOT)))
            self.assertIsInstance(reference_rules["must_not_be_used_as"], list, str(path.relative_to(ROOT)))
            self.assertTrue(reference_rules["must_not_be_used_as"], str(path.relative_to(ROOT)))

    def test_decision_scope_does_not_cover_product_wording(self):
        for path in [STRATEGY_DECISION_PATH, UNIVERSE_DECISION_PATH, LEVERAGE_DECISION_PATH]:
            payload = load_json(path)
            does_not_cover = payload["decision_scope"]["does_not_cover"]
            self.assertIn("product wording", " | ".join(does_not_cover).lower(), str(path.relative_to(ROOT)))


if __name__ == "__main__":
    unittest.main()