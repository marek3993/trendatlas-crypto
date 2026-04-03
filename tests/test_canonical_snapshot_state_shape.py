import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "canonical" / "manifests" / "canonical_strategy_snapshot.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestCanonicalSnapshotStateShape(unittest.TestCase):
    def test_current_state_block_exists(self):
        payload = load_json(SNAPSHOT_PATH)
        current_state = payload.get("current_state")

        self.assertIsInstance(current_state, dict)
        self.assertTrue(current_state)

    def test_current_state_expected_keys_exist(self):
        payload = load_json(SNAPSHOT_PATH)
        current_state = payload["current_state"]

        required = {
            "official_core_production_baseline",
            "official_universe_winner",
            "product_direction",
            "live_leverage_truth",
        }
        missing = sorted(required - set(current_state.keys()))
        self.assertFalse(missing, f"Missing current_state keys: {missing}")

    def test_current_state_entries_have_value_and_truth_status(self):
        payload = load_json(SNAPSHOT_PATH)
        current_state = payload["current_state"]
        failures = []

        for key, entry in current_state.items():
            if not isinstance(entry, dict):
                failures.append(f"{key} must be object")
                continue
            if not isinstance(entry.get("value"), str) or not entry["value"].strip():
                failures.append(f"{key} invalid value")
            if not isinstance(entry.get("truth_status"), str) or not entry["truth_status"].strip():
                failures.append(f"{key} invalid truth_status")

        self.assertFalse(failures, " | ".join(failures))


if __name__ == "__main__":
    unittest.main()