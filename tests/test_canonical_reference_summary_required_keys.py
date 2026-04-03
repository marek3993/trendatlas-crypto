import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REF_66G_PATH = ROOT / "canonical" / "references" / "canonical_66g_reference.json"
BENCHMARK_REF_PATH = ROOT / "canonical" / "references" / "canonical_benchmark_reference.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalReferenceSummaryRequiredKeys(unittest.TestCase):
    def test_66g_reference_summary_required_keys(self):
        payload = load_json(REF_66G_PATH)
        summary = payload["reference_summary"]

        required = {
            "reference_name",
            "reference_role",
            "is_current_universe_winner",
            "is_current_live_leverage_truth",
            "allowed_usage",
        }
        missing = sorted(required - set(summary.keys()))
        self.assertFalse(missing, f"Missing 66g reference summary keys: {missing}")

    def test_benchmark_reference_summary_required_keys(self):
        payload = load_json(BENCHMARK_REF_PATH)
        summary = payload["reference_summary"]

        required = {
            "benchmark_name",
            "reference_role",
            "is_current_live_truth",
            "product_direction_alignment",
        }
        missing = sorted(required - set(summary.keys()))
        self.assertFalse(missing, f"Missing benchmark reference summary keys: {missing}")


if __name__ == "__main__":
    unittest.main()