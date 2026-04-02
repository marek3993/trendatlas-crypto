import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PRODUCT_MANIFEST_PATH = ROOT / "canonical" / "manifests" / "canonical_product_manifest.json"
PRODUCT_EXPORT_CONTRACT_PATH = ROOT / "canonical" / "exports" / "canonical_product_export_contract.json"
STRATEGY_SNAPSHOT_PATH = ROOT / "canonical" / "manifests" / "canonical_strategy_snapshot.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalProductExportContract(unittest.TestCase):
    def test_product_manifest_has_official_truth_status(self):
        payload = load_json(PRODUCT_MANIFEST_PATH)
        self.assertEqual(payload["truth_status"], "official")

    def test_product_export_contract_has_official_truth_status(self):
        payload = load_json(PRODUCT_EXPORT_CONTRACT_PATH)
        self.assertEqual(payload["truth_status"], "official")

    def test_product_manifest_matches_strategy_snapshot(self):
        manifest = load_json(PRODUCT_MANIFEST_PATH)
        snapshot = load_json(STRATEGY_SNAPSHOT_PATH)

        contract = manifest["product_truth_contract"]
        current_state = snapshot["current_state"]

        self.assertEqual(
            contract["official_strategy_driver"],
            current_state["official_universe_winner"]["value"],
        )
        self.assertEqual(
            contract["reference_baseline"],
            current_state["official_core_production_baseline"]["value"],
        )
        self.assertEqual(
            contract["live_leverage_mode"],
            current_state["live_leverage_truth"]["value"],
        )

    def test_product_export_contract_forbids_historical_compare_as_product_truth(self):
        payload = load_json(PRODUCT_EXPORT_CONTRACT_PATH)
        forbidden_sources = payload["export_contract"]["forbidden_sources"]

        self.assertTrue(
            any("historical compare" in item.lower() for item in forbidden_sources)
        )
        self.assertTrue(
            any("historical summary" in item.lower() for item in forbidden_sources)
        )
        self.assertTrue(
            any("raw research outputs" in item.lower() for item in forbidden_sources)
        )

    def test_product_export_contract_requires_truth_fields(self):
        payload = load_json(PRODUCT_EXPORT_CONTRACT_PATH)
        required_fields = payload["export_contract"]["required_truth_fields"]

        self.assertIn("official_strategy_driver", required_fields)
        self.assertIn("reference_baseline", required_fields)
        self.assertIn("benchmark_reference", required_fields)
        self.assertIn("live_leverage_mode", required_fields)

    def test_product_export_contract_reading_rule_mentions_canonical_first(self):
        payload = load_json(PRODUCT_EXPORT_CONTRACT_PATH)
        reading_rule = payload["export_contract"]["reading_rule"].lower()

        self.assertIn("canonical", reading_rule)
        self.assertIn("historical", reading_rule)


if __name__ == "__main__":
    unittest.main()