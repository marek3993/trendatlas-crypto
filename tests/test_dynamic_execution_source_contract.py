import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DynamicExecutionSourceContractTests(unittest.TestCase):
    def test_execution_and_export_reference_the_same_contract(self):
        contract = json.loads((ROOT / "source_of_truth/production_execution_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["canonical_entrypoint"], "scripts/execution/run_trendatlas_production.py")
        self.assertEqual(contract["operator_control"]["emergency_switch"], "execution/config/execution_mode.json::kill_switch")
        self.assertTrue(contract["exit_contract"]["reduce_only"])
        self.assertLess(contract["state_machine"].index("VERIFY_EXIT"), contract["state_machine"].index("ENTRY"))
        self.assertEqual(contract["entry_contract"]["failure_after_verified_exit"], "EXITED_ENTRY_FAILED_STAYING_CASH")
        self.assertEqual(contract["multi_account"]["retryable_statuses_remain_eligible"], ["blocked", "error"])
        for filename in ("project_truth.json", "export_contract.json"):
            reference = json.loads((ROOT / "source_of_truth" / filename).read_text(encoding="utf-8"))
            self.assertEqual(reference["production_execution_source_contract"], "source_of_truth/production_execution_contract.json")


if __name__ == "__main__":
    unittest.main()
