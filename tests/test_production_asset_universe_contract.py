import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.production.strategy_adapters.current_emittable_universe import derive_current_emittable_universe


class ProductionAssetUniverseContractTests(unittest.TestCase):
    def test_source_contract_derives_assets_from_current_selector_not_historical_aliases(self):
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "source_of_truth/production_asset_universe_contract.json").read_text())
        self.assertEqual(contract["authority"], "active_production_strategy_adapter")
        self.assertEqual(contract["artifact_field"], "current_strategy_snapshot.source_inputs.current_emittable_universe")
        self.assertIn("successfully_loaded_current_production_selector_candidates", contract["selector_semantics"])
        self.assertIn("deployment_fails_closed", contract["missing_or_invalid_source"])
        self.assertNotIn("assets", contract)
        self.assertTrue((root / contract["adapter_source"]).is_file())
        self.assertIn("verify_both_against_declared_source_files", contract["fingerprint_rule"])
        self.assertFalse(contract["strategy_math_changed"])

    def derive(self, candidate_rows):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "source_of_truth").mkdir()
            (root / "source_of_truth/production_asset_universe_contract.json").write_text(json.dumps({"selector_source": "selector.csv", "adapter_source": "adapter.py"}))
            (root / "selector.csv").write_text("asset,end_date,history_days\n" + candidate_rows)
            (root / "adapter.py").write_text("# Fixture active adapter source\n")
            return derive_current_emittable_universe(root=root, closed_day="2026-09-24", strategy_version="fixture", adapter_path=root / "adapter.py", overlay_assets=("BTC",))

    def test_new_selector_asset_is_exported_without_executor_edit(self):
        result = self.derive("AVAX,2026-09-24,900\nNEWCOIN,2026-09-24,180\n")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["assets"], ["AVAX", "BTC", "CASH", "NEWCOIN"])
        self.assertEqual(len(result["selector_sha256"]), 64)
        self.assertEqual(len(result["adapter_sha256"]), 64)
        self.assertEqual(result["overlay_assets"], ["BTC"])

    def test_no_hardcoded_historical_symbol_exclusion(self):
        self.assertIn("BASE", self.derive("BASE,2026-09-24,180\n")["assets"])

    def test_empty_stale_or_invalid_candidates_fail_closed(self):
        for rows in ("", "AVAX,2026-09-23,180\n", "INVALID SYMBOL,2026-09-24,180\n", "AVAX,broken,180\n", "AVAX,2026-09-24,180\nAVAX,2026-09-24,180\n"):
            self.assertEqual(self.derive(rows)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
