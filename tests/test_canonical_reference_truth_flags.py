import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REF_66G_PATH = ROOT / "canonical" / "references" / "canonical_66g_reference.json"
BENCHMARK_REF_PATH = ROOT / "canonical" / "references" / "canonical_benchmark_reference.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalReferenceTruthFlags(unittest.TestCase):
    def test_66g_reference_has_expected_truth_flags(self):
        payload = load_json(REF_66G_PATH)
        summary = payload["reference_summary"]
        rules = payload["reference_rules"]

        self.assertEqual(payload["truth_status"], "reference")
        self.assertFalse(summary["is_current_universe_winner"])
        self.assertFalse(summary["is_current_live_leverage_truth"])
        self.assertIn("official current universe winner", " | ".join(rules["must_not_be_used_as"]).lower())
        self.assertIn("official live leverage truth", " | ".join(rules["must_not_be_used_as"]).lower())

    def test_benchmark_reference_has_expected_truth_flags(self):
        payload = load_json(BENCHMARK_REF_PATH)
        summary = payload["reference_summary"]
        rules = payload["reference_rules"]

        self.assertEqual(payload["truth_status"], "reference")
        self.assertFalse(summary["is_current_live_truth"])
        self.assertIn("current strategy winner", " | ".join(rules["must_not_be_used_as"]).lower())
        self.assertIn("official live state", " | ".join(rules["must_not_be_used_as"]).lower())

    def test_reference_files_have_reference_summary_blocks(self):
        for path in [REF_66G_PATH, BENCHMARK_REF_PATH]:
            payload = load_json(path)
            self.assertIn("reference_summary", payload, str(path.relative_to(ROOT)))
            self.assertIsInstance(payload["reference_summary"], dict, str(path.relative_to(ROOT)))
            self.assertTrue(payload["reference_summary"], str(path.relative_to(ROOT)))

    def test_reference_files_have_reference_rules_blocks(self):
        for path in [REF_66G_PATH, BENCHMARK_REF_PATH]:
            payload = load_json(path)
            self.assertIn("reference_rules", payload, str(path.relative_to(ROOT)))
            self.assertIsInstance(payload["reference_rules"], dict, str(path.relative_to(ROOT)))
            self.assertTrue(payload["reference_rules"], str(path.relative_to(ROOT)))


if __name__ == "__main__":
    unittest.main()