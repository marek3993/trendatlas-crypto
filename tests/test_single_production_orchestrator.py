from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.execution.production_execution import sha256_file
from scripts.execution.run_trendatlas_production import (
    AlreadyRunning,
    SingleRunLock,
    TrendAtlasProductionOrchestrator,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def production(asset="BTC", exposure=0.5):
    return {
        "artifact_type": "current_strategy_snapshot",
        "closed_day": "2026-08-31",
        "strategy_version": "model_v1",
        "validation": {"status": "passed"},
        "execution_intent": {
            "signal_id": "sig-1",
            "target_asset": asset,
            "target_exposure": exposure,
            "stale_signal": False,
            "allow_live_order_candidate": asset != "CASH",
        },
    }


def intent(asset="BTC", exposure=0.5):
    return {
        "as_of_source": "2026-08-31",
        "strategy_model": "model_v1",
        "signal_id": "sig-1",
        "target_asset": asset,
        "target_size_pct": exposure,
        "stale_signal": False,
        "allow_live_order_candidate": asset != "CASH",
    }


def account(position=False):
    positions = []
    if position:
        positions = [{"position": {"coin": "BTC", "szi": "0.0001", "positionValue": "10"}}]
    return {
        "as_of_utc": "2026-09-01T12:00:00Z",
        "account_address": "0xabc",
        "summary": {
            "account_abstraction": "unifiedAccount",
            "spot_stable_total_usd": 20.0,
            "spot_stable_available_usd": 20.0,
            "perp_account_value": 0.0,
            "perp_withdrawable": 0.0,
        },
        "raw": {"clearinghouseState": {"assetPositions": positions}, "openOrders": []},
    }


def policy():
    return {
        "allow_live_orders": True,
        "manual_approval_required": False,
        "require_kill_switch_off": True,
        "sizing_mode": "equity_target_exposure",
        "max_strategy_target_exposure": 2.0,
        "max_delta_fraction_of_equity": 2.0,
        "execution_leverage": 2,
        "max_execution_leverage": 3,
        "margin_buffer_fraction": 0.05,
        "reconciliation_tolerance_fraction_of_equity": 0.01,
        "post_trade_tolerance_fraction_of_equity": 0.02,
        "minimum_order_notional_usd": 10.0,
        "max_slippage_bps": 100,
        "account_snapshot_max_age_seconds": 99999999,
        "allowed_assets": ["BTC", "CASH"],
    }


class FakeAdapter:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.submits = []

    def query_order_by_cloid(self, _cloid):
        return {"found": False, "status": "missing"}

    def submit_ioc_order(self, step):
        self.submits.append(dict(step))
        if self.accepted:
            return {"acknowledged": True, "submit_state": "filled", "oid": 777}
        return {"acknowledged": False, "submit_state": "error", "error": "rejected"}


class FixtureOrchestrator(TrendAtlasProductionOrchestrator):
    def __init__(self, root: Path, *, no_submit: bool, adapter: FakeAdapter, signer_validator=None):
        default_signer_validator = lambda: {
            "status": "PASS",
            "credential_present": True,
            "credential_value_exposed": False,
            "account_address": "0xAE8D1A44F5C32EcB235519A06bb6691a4B33E856",
            "signer_address": "0x1111111111111111111111111111111111111111",
            "agent_name": "TrendAtlasProd",
            "signer_authorized": True,
        }
        super().__init__(
            root=root,
            no_submit=no_submit,
            market_loader=lambda: ({"BTC": 100_000.0}, {"BTC": 5}),
            adapter_factory=lambda: adapter,
            signer_validator=signer_validator or default_signer_validator,
            now=lambda: "2026-09-01T12:00:00Z",
        )
        self.target_day = "2026-08-31"
        self.manifest["target_closed_day"] = self.target_day
        self.adapter = adapter
        self.authority_calls = []
        self.dashboard_seen = None

    def publish_attempt_started(self):
        self.authority_state = {"mock": True}

    def run_script(self, script: Path, *arguments: str, label: str):
        root = self.root
        if label == "build_production_core":
            write_json(root / "outputs/production/current_strategy_snapshot.json", production())
        elif label == "build_canonical_intent":
            write_json(root / "outputs/execution/intents/latest_execution_intent.json", intent())
        elif label in {"build_real_order_gate", "rebuild_gate_after_account_readback"}:
            prod_path = root / "outputs/production/current_strategy_snapshot.json"
            intent_path = root / "outputs/execution/intents/latest_execution_intent.json"
            account_path = root / "outputs/execution/read_only/hyperliquid_account_snapshot.json"
            write_json(root / "outputs/execution/live_gate/latest_real_order_gate_decision.json", {
                "signal_id": "sig-1",
                "target_asset": "BTC",
                "status": "ready_if_enabled",
                "would_place_real_order": True,
                "real_orders_enabled": True,
                "production_signal_context": {"closed_day": "2026-08-31"},
                "source_fingerprints": {
                    "production_snapshot_sha256": sha256_file(prod_path),
                    "intent_sha256": sha256_file(intent_path),
                    "account_snapshot_sha256": sha256_file(account_path),
                },
            })
        elif label in {"read_account_before", "read_account_after"}:
            write_json(root / "outputs/execution/read_only/hyperliquid_account_snapshot.json", account(False))
        elif label == "materialize_dashboard_runtime":
            self.dashboard_seen = json.loads(self.latest_run_path.read_text(encoding="utf-8"))
            write_json(root / "outputs/execution/app_snapshot/dashboard_public_status.json", {
                "production_execution": {
                    "model_target": self.dashboard_seen["model_target_asset"],
                    "real_account": self.dashboard_seen["real_position_after"],
                }
            })
        elif label.startswith("authority_publish_existing"):
            self.authority_calls.append(label)

    def post_trade_verifier(self, plan, action_results):
        write_json(self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json", account(True))
        return {
            "status": "FILLED_AND_ALIGNED",
            "safe_for_next_step": True,
            "positions": [{"asset": "BTC", "notional_usd": 10.0}],
            "open_orders": [],
            "residual_delta_usd": 0.0,
        }


def health_bundle():
    return {
        "report": {
            "overall_status": "ok",
            "summary": {"block_execution": False, "execution_status": "ok"},
            "sources": [],
        },
        "quality": {"status": "passed"},
        "manifest": {},
    }


class SingleProductionOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write_json(self.root / "execution/config/execution_mode.json", {
            "mode": "live", "trading_enabled": True, "kill_switch": False,
        })
        write_json(self.root / "execution/config/live_order_policy.json", policy())
        write_json(self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json", account(False))

    def tearDown(self):
        self.temp.cleanup()

    def test_no_submit_never_constructs_or_calls_live_adapter(self):
        adapter = FakeAdapter()
        orchestrator = FixtureOrchestrator(self.root, no_submit=True, adapter=adapter)
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()), patch(
            "scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure",
            return_value={"published": True},
        ):
            result = orchestrator.run()
        self.assertEqual(result["final_status"], "PREFLIGHT_READY")
        self.assertEqual(adapter.submits, [])
        self.assertEqual(result["live_order_chain"], "NOT_INVOKED")
        self.assertFalse(result["real_order_sent"])
        self.assertEqual(result["signer_validation"]["status"], "PASS")

    def test_live_cycle_submits_once_then_publishes_authority(self):
        adapter = FakeAdapter()
        orchestrator = FixtureOrchestrator(self.root, no_submit=False, adapter=adapter)
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()):
            result = orchestrator.run()
        self.assertEqual(result["final_status"], "SUCCESS")
        self.assertEqual(len(adapter.submits), 1)
        self.assertEqual(result["order_id"], [777])
        self.assertEqual(result["post_trade_verification_status"], "FILLED_AND_ALIGNED")
        self.assertEqual(
            orchestrator.authority_calls,
            ["authority_publish_existing_dry_run", "authority_publish_existing"],
        )

    def test_authority_is_blocked_when_required_execution_rejected(self):
        adapter = FakeAdapter(accepted=False)
        orchestrator = FixtureOrchestrator(self.root, no_submit=False, adapter=adapter)
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()), patch(
            "scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure",
            return_value={"published": True},
        ):
            result = orchestrator.run()
        self.assertEqual(result["final_status"], "BLOCKED")
        self.assertEqual(result["failure_stage"], "EXECUTE")
        self.assertEqual(orchestrator.authority_calls, [])
        self.assertTrue(result["real_order_sent"])

    def test_dashboard_consumes_final_verified_real_state(self):
        orchestrator = FixtureOrchestrator(self.root, no_submit=False, adapter=FakeAdapter())
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()):
            result = orchestrator.run()
        self.assertEqual(result["final_status"], "SUCCESS")
        self.assertEqual(orchestrator.dashboard_seen["post_trade_verification_status"], "FILLED_AND_ALIGNED")
        self.assertEqual(orchestrator.dashboard_seen["real_position_after"][0]["asset"], "BTC")

    def test_concurrent_lock_is_blocked_before_work(self):
        lock_path = self.root / "lock"
        with SingleRunLock(lock_path):
            with self.assertRaises(AlreadyRunning):
                with SingleRunLock(lock_path):
                    self.fail("second lock must not be acquired")

    def test_canonical_systemd_unit_has_one_production_entrypoint(self):
        repo_root = Path(__file__).resolve().parents[1]
        service = (repo_root / "deploy/systemd/mrv1-production.service").read_text(encoding="utf-8")
        timer = (repo_root / "deploy/systemd/mrv1-production.timer").read_text(encoding="utf-8")
        self.assertIn("scripts/execution/run_trendatlas_production.py", service)
        self.assertNotIn("run_full_auto", service)
        self.assertNotIn("submit_controlled_real_order.py", service)
        self.assertEqual(service.count("ExecStart="), 1)
        self.assertIn("Unit=mrv1-production.service", timer)

    def test_signer_failure_is_redacted_from_run_manifest(self):
        private_key = "0x" + ("cd" * 32)

        def fail_signer_validation():
            raise RuntimeError(f"invalid credential {private_key}")

        orchestrator = FixtureOrchestrator(
            self.root,
            no_submit=True,
            adapter=FakeAdapter(),
            signer_validator=fail_signer_validation,
        )
        with patch(
            "scripts.execution.run_trendatlas_production.build_report_bundle",
            return_value=health_bundle(),
        ), patch(
            "scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure",
            return_value={"published": True},
        ):
            result = orchestrator.run()
        rendered = json.dumps(result)
        self.assertEqual(result["failure_stage"], "VALIDATE_SIGNER")
        self.assertNotIn(private_key, rendered)
        self.assertNotIn(private_key[2:], rendered)
        self.assertIn("[REDACTED_PRIVATE_KEY]", rendered)


if __name__ == "__main__":
    unittest.main()
