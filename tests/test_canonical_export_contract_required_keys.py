import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT_CONTRACT_PATH = ROOT / "canonical" / "exports" / "canonical_product_export_contract.json"

REQUIRED_EXPORT_CONTRACT_KEYS = {
    "purpose",
    "allowed_sources",
    "forbidden_sources",
    "required_truth_fields",
    "reading_rule",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalExportContractRequiredKeys(unittest.TestCase):
    def test_export_contract_block_exists(self):
        payload = load_json(EXPORT_CONTRACT_PATH)
        export_contract = payload.get("export_contract")

        self.assertIsInstance(export_contract, dict)
        self.assertTrue(export_contract)

    def test_export_contract_required_keys_exist(self):
        payload = load_json(EXPORT_CONTRACT_PATH)
        export_contract = payload["export_contract"]

        missing = sorted(REQUIRED_EXPORT_CONTRACT_KEYS - set(export_contract.keys()))
        self.assertFalse(missing, f"Missing export_contract keys: {missing}")

    def test_export_contract_required_keys_are_not_empty(self):
        payload = load_json(EXPORT_CONTRACT_PATH)
        export_contract = payload["export_contract"]
        failures = []

        for key in REQUIRED_EXPORT_CONTRACT_KEYS:
            value = export_contract.get(key)
            if value is None:
                failures.append(f"null key: {key}")
                continue
            if isinstance(value, (list, dict, str)) and len(value) == 0:
                failures.append(f"empty key: {key}")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()