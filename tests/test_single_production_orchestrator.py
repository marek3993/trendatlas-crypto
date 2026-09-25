from __future__ import annotations

import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from scripts.execution.production_execution import sha256_file, build_execution_plan, ExecutionJournal
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
    def __init__(self, root: Path, *, no_submit: bool, adapter: FakeAdapter, signer_validator=None, execution_backend="legacy"):
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
            execution_backend=execution_backend,
            now=lambda: "2026-09-01T12:00:00Z",
        )
        self.target_day = "2026-08-31"
        self.manifest["target_closed_day"] = self.target_day
        self.adapter = adapter
        self.authority_calls = []
        self.dashboard_seen = None
        self.env.update({
            "NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ADMIN_KEY": "server-only-test-key",
            "TRENDATLAS_AGENT_KEK_B64": "test-kek",
            "MRV1_MULTI_ACCOUNT_NODE_BINARY": "/test/node",
            "MRV1_MULTI_ACCOUNT_WEB_ROOT": "/test/web",
        })

    def run_multi_account_backend(self, signal_id, *, no_submit):
        return ({
            "runId": self.run_id,
            "signalId": signal_id,
            "successful": True,
            "realOrderSent": False if no_submit else True,
            "ownerResult": {"accountId": "account-a", "status": "PREFLIGHT_READY" if no_submit else "FILLED_AND_ALIGNED"},
            "results": [{"accountId": "account-a", "status": "PREFLIGHT_READY" if no_submit else "FILLED_AND_ALIGNED"}],
        }, 0)

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
            write_json(root / "outputs/execution/read_only/hyperliquid_account_snapshot.json", account(label == "read_account_after" and self.execution_backend == "multi_account"))
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
        self.assertEqual(result["heavy_refresh_steps"], "skipped")
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

    def test_multi_account_backend_replaces_legacy_submission_inside_same_orchestrator(self):
        adapter = FakeAdapter()
        legacy_signer = unittest.mock.Mock(side_effect=AssertionError("legacy signer must not be used"))
        orchestrator = FixtureOrchestrator(
            self.root,
            no_submit=False,
            adapter=adapter,
            signer_validator=legacy_signer,
            execution_backend="multi_account",
        )
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()):
            result = orchestrator.run()
        self.assertEqual(result["final_status"], "SUCCESS")
        self.assertEqual(result["execution_backend"], "multi_account")
        self.assertEqual(result["multi_account_execution"]["results"][0]["status"], "FILLED_AND_ALIGNED")
        self.assertEqual(result["live_order_chain"], "INVOKED")
        self.assertTrue(result["real_order_sent"])
        self.assertEqual(adapter.submits, [])
        legacy_signer.assert_not_called()
        self.assertEqual(orchestrator.authority_calls, ["authority_publish_existing_dry_run", "authority_publish_existing"])

    def test_multi_account_no_submit_runs_all_account_preflight_without_legacy_adapter(self):
        adapter = FakeAdapter()
        orchestrator = FixtureOrchestrator(
            self.root,
            no_submit=True,
            adapter=adapter,
            execution_backend="multi_account",
        )
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()), patch(
            "scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure",
            return_value={"published": True},
        ):
            result = orchestrator.run()
        self.assertEqual(result["final_status"], "PREFLIGHT_READY")
        self.assertEqual(result["multi_account_execution"]["results"][0]["status"], "PREFLIGHT_READY")
        self.assertEqual(result["live_order_chain"], "NOT_INVOKED")
        self.assertFalse(result["real_order_sent"])
        self.assertEqual(adapter.submits, [])

    def test_multi_account_child_is_run_from_canonical_web_root_with_inherited_server_secrets(self):
        web_root = self.root / "web"
        runner_path = web_root / "scripts/run-multi-account-production-cycle.ts"
        runner_path.parent.mkdir(parents=True)
        runner_path.write_text("// fixture", encoding="utf-8")
        node_binary = self.root / ".runtime/node"
        node_binary.parent.mkdir(parents=True)
        node_binary.write_text("#!/bin/sh\n", encoding="utf-8")
        node_binary.chmod(0o700)
        command_runner = unittest.mock.Mock(return_value=SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"runId": "run-fixture", "signalId": "sig-1", "successful": True, "realOrderSent": False, "results": []}) + "\n",
            stderr="",
        ))
        orchestrator = TrendAtlasProductionOrchestrator(
            root=self.root,
            no_submit=False,
            command_runner=command_runner,
            execution_backend="multi_account",
            signer_validator=lambda: {"status": "PASS"},
        )
        orchestrator.run_id = "run-fixture"
        orchestrator.env.update({
            "MRV1_CURRENT_AUTHORITY_RUN_ID": "run-fixture",
            "MRV1_MULTI_ACCOUNT_WEB_ROOT": str(web_root),
            "MRV1_MULTI_ACCOUNT_NODE_BINARY": str(node_binary),
            "NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ADMIN_KEY": "server-only-test-key",
            "TRENDATLAS_AGENT_KEK_B64": "test-kek",
        })

        report, returncode = orchestrator.run_multi_account_backend("sig-1", no_submit=False)

        self.assertEqual(returncode, 0)
        self.assertTrue(report["successful"])
        command = command_runner.call_args.args[0]
        child_env = command_runner.call_args.kwargs["env"]
        self.assertNotIn("--env-file", " ".join(command))
        self.assertEqual(command[-1], str(runner_path))
        self.assertEqual(child_env["TRENDATLAS_LIVE_SIGNAL_CONFIRMATION"], "sig-1")
        self.assertEqual(child_env["TRENDATLAS_MULTI_ACCOUNT_EXECUTION_CONTEXT"], "canonical_orchestrator")

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
        self.assertEqual(orchestrator.dashboard_seen["final_status"], "SUCCESS")
        self.assertIsNotNone(orchestrator.dashboard_seen["finished_at"])
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
        self.assertIn("Restart=on-failure", service)
        self.assertIn("RestartSec=15min", service)
        self.assertIn("MRV1_EXECUTION_BACKEND=multi_account", service)
        self.assertIn("EnvironmentFile=-/etc/default/trendatlas-multi-account", service)
        self.assertNotIn("LoadCredentialEncrypted=hyperliquid-agent-private-key", service)
        self.assertNotIn("validate_hyperliquid_production_signer.py --quiet", service)
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


    def test_multi_exit_callback_checks_only_last_completed_close_and_fresh_residual(self):
        from datetime import datetime, timezone
        mids, precision = {"BTC": 100000.0, "ETH": 4000.0, "AVAX": 25.0}, {"BTC": 5, "ETH": 4, "AVAX": 2}
        snapshot = account(True)
        snapshot["summary"]["spot_stable_total_usd"] = 1000
        snapshot["summary"]["spot_stable_available_usd"] = 1000
        snapshot["raw"]["clearinghouseState"]["assetPositions"].append({"position": {"coin": "ETH", "szi": ".05", "positionValue": "200"}})
        prod, canonical_intent = production("AVAX", 1.25), intent("AVAX", 1.25)
        canonical_gate = {"signal_id": "sig-1", "target_asset": "AVAX", "production_signal_context": {"closed_day": "2026-08-31"}}
        plan = build_execution_plan(production=prod, intent=canonical_intent, gate=canonical_gate, account_snapshot=snapshot, policy=policy(), mids=mids, size_decimals=precision, now=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
        runner = TrendAtlasProductionOrchestrator(root=self.root, market_loader=lambda: (mids, precision))
        runner.run_script = unittest.mock.Mock()
        runner.load_runtime = lambda: (prod, canonical_intent, canonical_gate, snapshot, {"kill_switch": False}, policy())
        result_rows = [{"step": plan["steps"][0], "response": {"acknowledged": True}}]
        # An exchange acknowledgement alone cannot authorize ENTRY.
        still_open = runner.post_trade_verifier(plan, result_rows)
        self.assertFalse(still_open["safe_for_next_step"])
        snapshot["raw"]["clearinghouseState"]["assetPositions"] = [row for row in snapshot["raw"]["clearinghouseState"]["assetPositions"] if row["position"]["coin"] != "BTC"]
        after_first = runner.post_trade_verifier(plan, result_rows)
        self.assertTrue(after_first["safe_for_next_step"])
        self.assertEqual([p["asset"] for p in after_first["residual_plan"]["unwanted_positions"]], ["ETH"])
        self.assertEqual(after_first["residual_plan"]["steps"][0]["asset"], "ETH")
        snapshot["raw"]["clearinghouseState"]["assetPositions"] = []
        snapshot["summary"]["spot_stable_total_usd"] = 900
        result_rows.append({"step": plan["steps"][1], "response": {"acknowledged": True}})
        after_second = runner.post_trade_verifier(plan, result_rows)
        self.assertTrue(after_second["safe_for_next_step"])
        self.assertEqual(after_second["residual_plan"]["target_notional_usd"], 1125)
        self.assertEqual(after_second["residual_plan"]["unwanted_positions"], [])
        self.assertEqual(runner.run_script.call_count, 3)

    def test_multi_account_owner_plan_error_does_not_prevent_child_accounts(self):
        class OwnerSnapshotError(FixtureOrchestrator):
            child_ran = False
            def run_script(self, script, *arguments, label):
                super().run_script(script, *arguments, label=label)
                if label == "read_account_before":
                    broken = account()
                    broken["summary"]["spot_stable_total_usd"] = None
                    write_json(self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json", broken)
            def run_multi_account_backend(self, signal_id, *, no_submit):
                self.child_ran = True
                return super().run_multi_account_backend(signal_id, no_submit=no_submit)
        runner = OwnerSnapshotError(self.root, no_submit=False, adapter=FakeAdapter(), execution_backend="multi_account")
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()):
            result = runner.run()
        self.assertTrue(runner.child_ran)
        self.assertEqual(result["final_status"], "SUCCESS")
        self.assertIsNone(result["account_equity_before"])
        self.assertEqual(result["account_equity_after"], 20)

    def test_publication_failure_preserves_execution_and_retry_never_resubmits(self):
        class PublishFailure(FixtureOrchestrator):
            def run_script(self, script, *arguments, label):
                if label == "authority_publish_existing":
                    raise TimeoutError("temporary publication failure")
                super().run_script(script, *arguments, label=label)
        adapter = FakeAdapter()
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()), patch("scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure", return_value={"published": True}):
            failed = PublishFailure(self.root, no_submit=False, adapter=adapter).run()
            self.assertEqual(failed["final_status"], "EXECUTION_COMPLETE_PUBLISH_FAILED")
            self.assertEqual(failed["execution_outcome"], "FILLED_AND_ALIGNED")
            self.assertEqual(len(adapter.submits), 1)
            success = FixtureOrchestrator(self.root, no_submit=False, adapter=adapter).run()
        self.assertEqual(success["final_status"], "SUCCESS")
        self.assertEqual(len(adapter.submits), 1)
        self.assertEqual(success["execution_outcome"], "FILLED_AND_ALIGNED")
        self.assertFalse(success["real_order_sent"])

    def test_dashboard_failure_preserves_execution_and_retry_never_resubmits(self):
        class DashboardFailure(FixtureOrchestrator):
            def run_script(self, script, *arguments, label):
                if label == "materialize_dashboard_runtime":
                    raise TimeoutError("dashboard storage unavailable")
                super().run_script(script, *arguments, label=label)
        adapter = FakeAdapter()
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()), patch("scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure", return_value={"published": True}):
            failed = DashboardFailure(self.root, no_submit=False, adapter=adapter).run()
            self.assertEqual(failed["final_status"], "EXECUTION_COMPLETE_PUBLISH_FAILED")
            self.assertEqual(failed["execution_outcome"], "FILLED_AND_ALIGNED")
            self.assertEqual(len(adapter.submits), 1)
            success = FixtureOrchestrator(self.root, no_submit=False, adapter=adapter).run()
        self.assertEqual(success["final_status"], "SUCCESS")
        self.assertEqual(len(adapter.submits), 1)

    def test_presentation_steps_run_after_execution_and_fail_as_warnings(self):
        class PresentationFailure(FixtureOrchestrator):
            presentation_labels = []
            def run_script(self, script, *arguments, label):
                if label in {"verify_app_freshness", "hyperliquid_real_performance_ledger"}:
                    self.presentation_labels.append((label, self.manifest.get("execution_outcome")))
                    raise RuntimeError("presentation source unavailable")
                super().run_script(script, *arguments, label=label)
        runner = PresentationFailure(self.root, no_submit=False, adapter=FakeAdapter(), execution_backend="multi_account")
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()):
            result = runner.run()
        self.assertEqual(result["final_status"], "SUCCESS")
        self.assertEqual(set(result["presentation_warnings"]), {"verify_app_freshness", "hyperliquid_real_performance_ledger"})
        self.assertEqual(len(runner.presentation_labels), 2)
        self.assertTrue(all(outcome == "FILLED_AND_ALIGNED" for _, outcome in runner.presentation_labels))

    def test_owner_readback_failure_preserves_terminal_batch_results_and_marks_wallet_unknown(self):
        class ReadbackFailure(FixtureOrchestrator):
            def run_script(self, script, *arguments, label):
                if label == "read_account_after":
                    raise TimeoutError("owner presentation read unavailable")
                super().run_script(script, *arguments, label=label)
        runner = ReadbackFailure(self.root, no_submit=False, adapter=FakeAdapter(), execution_backend="multi_account")
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()), patch("scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure", return_value={"published": True}):
            result = runner.run()
        self.assertEqual(result["final_status"], "EXECUTION_COMPLETE_PUBLISH_FAILED")
        self.assertEqual(result["execution_outcome"], "FILLED_AND_ALIGNED")
        self.assertEqual(result["multi_account_execution"]["results"][0]["status"], "FILLED_AND_ALIGNED")
        self.assertFalse(result["owner_account_snapshot_available"])
        self.assertIsNone(result["real_position_after"])
        self.assertIsNone(result["real_exposure_after"])
        self.assertEqual(runner.authority_calls, [])

    def test_staying_cash_is_terminal_only_after_flat_exchange_readback(self):
        class StayingCash(FixtureOrchestrator):
            leave_position = False
            def run_multi_account_backend(self, signal_id, *, no_submit):
                report, _ = super().run_multi_account_backend(signal_id, no_submit=no_submit)
                report.update({"successful": False, "failureKind": "deterministic", "ownerResult": {"status": "EXITED_ENTRY_FAILED_STAYING_CASH"}})
                return report, 2
            def run_script(self, script, *arguments, label):
                super().run_script(script, *arguments, label=label)
                if label == "read_account_after":
                    write_json(self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json", account(self.leave_position))
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()), patch("scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure", return_value={"published": True}):
            runner = StayingCash(self.root, no_submit=False, adapter=FakeAdapter(), execution_backend="multi_account")
            result = runner.run()
            self.assertEqual(result["final_status"], "EXITED_ENTRY_FAILED_STAYING_CASH")
            self.assertEqual(result["real_position_after"], [])
            self.assertEqual(result["real_exposure_after"], 0)
            self.assertEqual(result["authority_status"], "EXECUTION_TARGET_NOT_ALIGNED")
            self.assertEqual(runner.authority_calls, [])
            bad = StayingCash(self.root, no_submit=False, adapter=FakeAdapter(), execution_backend="multi_account")
            bad.leave_position = True
            invalid = bad.run()
        self.assertEqual(invalid["final_status"], "BLOCKED")
        self.assertEqual(invalid["execution_outcome"], "POST_TRADE_VERIFICATION_FAILED")
        self.assertEqual(invalid["failure_stage"], "POST_TRADE_VERIFY")

    def test_deterministic_exit_status_stops_retry_without_disabling_next_daily_run(self):
        import contextlib
        import io
        from scripts.execution import run_trendatlas_production as module
        service = (Path(__file__).resolve().parents[1] / "deploy/systemd/mrv1-production.service").read_text(encoding="utf-8")
        self.assertIn("RestartPreventExitStatus=2", service)
        with patch.object(module, "ROOT", self.root), patch.object(module, "TrendAtlasProductionOrchestrator") as runner_type, contextlib.redirect_stdout(io.StringIO()):
            runner_type.return_value.run.return_value = {"final_status": "BLOCKED", "failure_kind": "deterministic"}
            self.assertEqual(module.main([]), 2)
            runner_type.return_value.run.return_value = {"final_status": "FAILED", "failure_kind": "retryable"}
            self.assertEqual(module.main([]), 1)
        write_json(self.root / "outputs/execution/production_runs/latest_production_run.json", {"target_closed_day": "2026-08-30", "failure_kind": "deterministic", "retry_attempt": 3})
        next_run = FixtureOrchestrator(self.root, no_submit=False, adapter=FakeAdapter())
        self.assertEqual(next_run.manifest["retry_attempt"], 0)
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()):
            result = next_run.run()
        self.assertEqual(result["final_status"], "SUCCESS")

    def test_live_batch_never_infers_owner_alignment_from_another_account_order(self):
        class MissingOwner(FixtureOrchestrator):
            def run_multi_account_backend(self, signal_id, *, no_submit):
                report, code = super().run_multi_account_backend(signal_id, no_submit=no_submit)
                del report["ownerResult"]
                return report, code
        runner = MissingOwner(self.root, no_submit=False, adapter=FakeAdapter(), execution_backend="multi_account")
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()), patch("scripts.execution.run_trendatlas_production.authority_publish_helpers.publish_authority_refresh_failure", return_value={"published": True}):
            result = runner.run()
        self.assertEqual(result["final_status"], "BLOCKED")
        self.assertIn("owner_result_missing", result["failure_reason"])
        self.assertEqual(runner.authority_calls, [])


    def test_owner_snapshot_read_failure_does_not_block_independent_accounts(self):
        class ReadFailure(FixtureOrchestrator):
            child_ran = False
            def run_script(self, script, *arguments, label):
                if label == "read_account_before":
                    raise TimeoutError("owner account temporarily unavailable")
                super().run_script(script, *arguments, label=label)
            def run_multi_account_backend(self, signal_id, *, no_submit):
                self.child_ran = True
                return super().run_multi_account_backend(signal_id, no_submit=no_submit)
        runner = ReadFailure(self.root, no_submit=False, adapter=FakeAdapter(), execution_backend="multi_account")
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()):
            result = runner.run()
        self.assertTrue(runner.child_ran)
        self.assertEqual(result["final_status"], "SUCCESS")
        self.assertIn("temporarily unavailable", result["owner_account_snapshot_warning"])


    def test_missing_owner_snapshot_is_optional_and_not_fabricated_before_batch(self):
        class MissingOwnerObservation(FixtureOrchestrator):
            child_ran_without_snapshot = False
            def run_script(self, script, *arguments, label):
                path = self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json"
                if label == "read_account_before":
                    path.unlink(missing_ok=True)
                    raise TimeoutError("owner read unavailable")
                if label == "build_real_order_gate":
                    prod = self.root / "outputs/production/current_strategy_snapshot.json"
                    canonical_intent = self.root / "outputs/execution/intents/latest_execution_intent.json"
                    write_json(self.root / "outputs/execution/live_gate/latest_real_order_gate_decision.json", {
                        "signal_id": "sig-1", "target_asset": "BTC", "status": "ready_if_enabled", "would_place_real_order": True,
                        "real_orders_enabled": True, "strategy_validated": True,
                        "account_validation_scope": "per_account_exchange", "account_snapshot_available": False,
                        "production_signal_context": {"closed_day": "2026-08-31"},
                        "source_fingerprints": {"production_snapshot_sha256": sha256_file(prod), "intent_sha256": sha256_file(canonical_intent), "account_snapshot_sha256": None},
                    })
                    return
                super().run_script(script, *arguments, label=label)
            def run_multi_account_backend(self, signal_id, *, no_submit):
                self.child_ran_without_snapshot = not (self.root / "outputs/execution/read_only/hyperliquid_account_snapshot.json").exists()
                return super().run_multi_account_backend(signal_id, no_submit=no_submit)
        runner = MissingOwnerObservation(self.root, no_submit=False, adapter=FakeAdapter(), execution_backend="multi_account")
        with patch("scripts.execution.run_trendatlas_production.build_report_bundle", return_value=health_bundle()):
            result = runner.run()
        self.assertTrue(runner.child_ran_without_snapshot)
        self.assertEqual(result["final_status"], "SUCCESS")
        self.assertIsNone(result["account_equity_before"])
        self.assertEqual(result["account_equity_after"], 20)


if __name__ == "__main__":
    unittest.main()
