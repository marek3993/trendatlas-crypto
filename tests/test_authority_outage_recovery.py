"""Regression for a Pi missing multiple daily authority publications."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.production import data_health_common as health


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.day = "2026-09-19"
        self.production = {
            "closed_day": self.day, "strategy_version": "fixture",
            "execution_intent": {
                "signal_id": "signal-current", "target_asset": "CASH",
                "target_exposure": 0.0, "stale_signal": False,
                "allow_live_order_candidate": False,
            },
        }
        self.write("production_current_strategy_snapshot", self.production)
        account = self.root / health.CANONICAL_ACCOUNT_SNAPSHOT_PATH
        account.parent.mkdir(parents=True, exist_ok=True)
        account.write_text('{"as_of_utc":"2026-09-20T06:13:27Z"}')
        self.attempt = {
            "run_id": "current-run", "target_closed_day_utc": self.day,
            "latest_available_closed_utc_day": self.day,
            "latest_authoritative_attempt_status": "in_progress",
        }
        self.write("execution_authority_latest_attempt_status", self.attempt)
        self.intent = {
            "as_of_source": self.day, "strategy_model": "fixture",
            "signal_id": "signal-current", "target_asset": "CASH",
            "target_size_pct": 0.0, "stale_signal": False,
            "allow_live_order_candidate": False,
            "guardrail_flags": {
                "same_run_authority_allowed": True,
                "same_run_authority_run_id": "current-run",
                "same_run_authority_target_closed_day": self.day,
            },
            "source_fingerprints": {
                "production_snapshot_sha256": self.digest("production_current_strategy_snapshot"),
            },
        }
        self.write("execution_latest_execution_intent", self.intent)
        self.gate = {
            "signal_id": "signal-current", "target_asset": "CASH",
            "production_signal_context": {
                "strategy_version": "fixture", "closed_day": self.day,
                "signal_id": "signal-current", "target_asset": "CASH",
                "target_exposure": 0.0, "allow_live_order_candidate": False,
            },
            "checks": {name: True for name in (
                "intent_day_matches_production_snapshot",
                "intent_signal_matches_production_snapshot",
                "intent_target_asset_matches_production_snapshot",
                "intent_target_exposure_matches_production_snapshot",
                "intent_stale_signal_matches_production_snapshot",
                "intent_strategy_model_matches_production_snapshot",
                "intent_allow_live_order_candidate_matches_snapshot",
            )},
            "source_paths": {
                "intent_path": health.SOURCE_INDEX["execution_latest_execution_intent"].path,
                "account_snapshot_path": health.CANONICAL_ACCOUNT_SNAPSHOT_PATH,
            },
            "source_fingerprints": {
                "intent_sha256": self.digest("execution_latest_execution_intent"),
                "production_snapshot_sha256": self.digest("production_current_strategy_snapshot"),
                "account_snapshot_sha256": health.sha256_file(account),
            },
        }
        self.write("execution_latest_real_order_gate_decision", self.gate)

    def write(self, key, data):
        path = self.root / health.SOURCE_INDEX[key].path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def digest(self, key):
        return health.sha256_file(self.root / health.SOURCE_INDEX[key].path)

    def check(self, previous="2026-09-05"):
        return health.same_run_new_closed_day_is_proven(
            root=self.root, path_overrides={}, expected_day=self.day,
            previous_success_day=previous,
        )[0]

    def test_fourteen_day_outage_and_normal_day_advance(self):
        self.assertTrue(self.check())
        self.assertTrue(self.check("2026-09-18"))

    def test_invalid_same_day_and_future_do_not_qualify(self):
        for day in ("invalid", "2026-09-19", "2026-09-20"):
            with self.subTest(day=day):
                self.assertFalse(self.check(day))

    def test_failed_attempt_blocks(self):
        self.attempt["latest_authoritative_attempt_status"] = "failed"
        self.write("execution_authority_latest_attempt_status", self.attempt)
        self.assertFalse(self.check())

    def test_wrong_run_blocks(self):
        self.attempt["run_id"] = "other-run"
        self.write("execution_authority_latest_attempt_status", self.attempt)
        self.assertFalse(self.check())

    def test_wrong_available_day_blocks(self):
        self.attempt["latest_available_closed_utc_day"] = "2026-09-18"
        self.write("execution_authority_latest_attempt_status", self.attempt)
        self.assertFalse(self.check())

    def test_changed_production_fingerprint_blocks(self):
        self.production["extra"] = "changed"
        self.write("production_current_strategy_snapshot", self.production)
        self.assertFalse(self.check())

    def test_changed_account_fingerprint_blocks(self):
        (self.root / health.CANONICAL_ACCOUNT_SNAPSHOT_PATH).write_text("{}")
        self.assertFalse(self.check())

    def test_gate_failed_alignment_blocks(self):
        self.gate["checks"]["intent_day_matches_production_snapshot"] = False
        self.write("execution_latest_real_order_gate_decision", self.gate)
        self.assertFalse(self.check())

    def test_missing_gate_blocks(self):
        (self.root / health.SOURCE_INDEX["execution_latest_real_order_gate_decision"].path).unlink()
        self.assertFalse(self.check())

    def test_absent_same_run_permission_blocks(self):
        self.intent["guardrail_flags"]["same_run_authority_allowed"] = False
        self.write("execution_latest_execution_intent", self.intent)
        self.assertFalse(self.check())


if __name__ == "__main__":
    unittest.main()
