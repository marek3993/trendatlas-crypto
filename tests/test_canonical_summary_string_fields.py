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


class TestCanonicalSummaryStringFields(unittest.TestCase):
    def test_decision_summary_string_fields_are_non_empty(self):
        checks = [
            (STRATEGY_DECISION_PATH, "decision_summary", [
                "official_core_production_baseline",
                "official_universe_winner",
                "product_direction",
                "live_leverage_truth",
            ]),
            (UNIVERSE_DECISION_PATH, "decision_summary", [
                "official_universe_winner",
                "reference_baseline",
                "reading_rule",
                "product_direction_alignment",
            ]),
            (LEVERAGE_DECISION_PATH, "decision_summary", [
                "current_live_leverage_mode",
                "approved_reference_position",
                "downstream_rule",
            ]),
            (REF_66G_PATH, "reference_summary", [
                "reference_name",
                "reference_role",
            ]),
            (BENCHMARK_REF_PATH, "reference_summary", [
                "benchmark_name",
                "reference_role",
                "product_direction_alignment",
            ]),
        ]

        failures = []

        for path, block_name, keys in checks:
            payload = load_json(path)
            block = payload[block_name]

            for key in keys:
                value = block.get(key)
                if not isinstance(value, str) or not value.strip():
                    failures.append(f"{path.relative_to(ROOT)} invalid string field {block_name}.{key}={value}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()