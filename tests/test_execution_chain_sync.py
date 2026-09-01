import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.execution import build_execution_intent_from_strategy_exports as intent_builder
from scripts.execution import prepare_real_order_gate as gate_builder
from scripts.execution import run_pi_fast_daily_authority_refresh as fast_refresh
from scripts.production import data_health_common


MODEL = "phase68g_etf_flow_impulse_early_risk_cooldown_15"
DAY = "2026-08-31"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestExecutionChainSync(unittest.TestCase):
    def make_root(
        self,
        *,
        target_asset: str = "BTC",
        target_exposure: float = 0.5,
        block_execution: bool = False,
    ) -> tuple[Path, dict[str, Path]]:
        temp_dir = tempfile.mkdtemp(prefix="mrv1_execution_chain_sync_")
        self.addCleanup(shutil.rmtree, temp_dir, True)
        root = Path(temp_dir)
        signal_id = (
            f"current_strategy::{MODEL}::{DAY}::target_{target_asset}"
            f"::candidate_{'BTC' if target_asset == 'CASH' else target_asset}"
        )
        is_cash = target_asset == "CASH"
        production_path = root / "outputs/production/current_strategy_snapshot.json"
        production = {
            "artifact_type": "current_strategy_snapshot",
            "strategy_id": "current_strategy",
            "strategy_version": MODEL,
            "closed_day": DAY,
            "strategy_status": "ready",
            "candidate_asset": "BTC",
            "current_asset": target_asset,
            "current_regime": target_asset,
            "effective_market_exposure": target_exposure,
            "model_candidate_exposure": 0.5,
            "trend_permission_active": not is_cash,
            "validation": {"status": "passed"},
            "execution_intent": {
                "signal_id": signal_id,
                "target_asset": target_asset,
                "target_exposure": target_exposure,
                "stale_signal": False,
                "allow_live_order_candidate": not is_cash,
            },
        }
        write_json(production_path, production)

        intent_path = root / "outputs/execution/intents/latest_execution_intent.json"
        intent = {
            "intent_type": "normalized_execution_intent",
            "generated_at_utc": "2026-09-01T00:15:00Z",
            "as_of_source": DAY,
            "strategy_model": MODEL,
            "signal_id": signal_id,
            "target_asset": target_asset,
            "target_size_pct": target_exposure,
            "stale_signal": False,
            "allow_live_order_candidate": not is_cash,
            "guardrail_flags": {
                "contract_validated": True,
                "production_snapshot_validated": True,
                "leverage_live_truth_allowed": False,
            },
            "source_fingerprints": {
                "production_snapshot_sha256": sha256_file(production_path),
            },
        }
        write_json(intent_path, intent)

        account_path = (
            root
            / "outputs/execution/read_only/hyperliquid_account_snapshot.json"
        )
        account = {
            "snapshot_type": "hyperliquid_read_only_account_snapshot",
            "as_of_utc": "2026-09-01T00:14:00Z",
            "account_address": "0x0000000000000000000000000000000000000001",
            "raw": {"openOrders": [], "clearinghouseState": {"assetPositions": []}},
            "summary": {"positions_count": 0, "open_orders_count": 0},
        }
        write_json(account_path, account)

        gate_path = (
            root
            / "outputs/execution/live_gate/latest_real_order_gate_decision.json"
        )
        gate = {
            "decision_type": "real_order_gate_decision",
            "generated_at_utc": "2026-09-01T00:16:00Z",
            "signal_id": signal_id,
            "target_asset": target_asset,
            "status": "ready_if_enabled" if not is_cash else "blocked",
            "would_place_real_order": not is_cash,
            "checks": {
                "production_snapshot_validation_passed": True,
                "production_snapshot_stale_signal": False,
                "intent_day_matches_production_snapshot": True,
                "intent_signal_matches_production_snapshot": True,
                "intent_target_asset_matches_production_snapshot": True,
                "intent_target_exposure_matches_production_snapshot": True,
                "intent_stale_signal_matches_production_snapshot": True,
                "intent_strategy_model_matches_production_snapshot": True,
                "intent_allow_live_order_candidate_matches_snapshot": True,
            },
            "production_signal_context": {
                "strategy_version": MODEL,
                "closed_day": DAY,
                "signal_id": signal_id,
                "target_asset": target_asset,
                "target_exposure": target_exposure,
                "allow_live_order_candidate": not is_cash,
            },
            "source_paths": {
                "intent_path": str(intent_path.resolve()),
                "account_snapshot_path": str(account_path.resolve()),
                "production_snapshot_path": str(production_path.resolve()),
            },
            "source_fingerprints": {
                "intent_sha256": sha256_file(intent_path),
                "production_snapshot_sha256": sha256_file(production_path),
                "account_snapshot_sha256": sha256_file(account_path),
            },
        }
        write_json(gate_path, gate)

        data_health_path = root / "outputs/production/data_health_report.json"
        write_json(
            data_health_path,
            {
                "artifact_type": "data_health_report",
                "summary": {
                    "block_app": block_execution,
                    "block_execution": block_execution,
                },
            },
        )
        return root, {
            "production": production_path,
            "intent": intent_path,
            "account": account_path,
            "gate": gate_path,
            "data_health": data_health_path,
        }

    def test_fast_cycle_contract_rejects_older_intent_and_accepts_exact_chain(self):
        root, paths = self.make_root()

        summary = fast_refresh.validate_canonical_execution_chain_sync(
            root=root,
            require_execution_health=True,
        )

        self.assertEqual(summary["production_closed_day"], DAY)
        self.assertEqual(summary["intent_closed_day"], DAY)
        self.assertEqual(summary["intent_target_asset"], "BTC")
        self.assertEqual(summary["intent_target_size_pct"], 0.5)
        self.assertEqual(summary["intent_signal_id"], summary["gate_signal_id"])

        stale_intent = json.loads(paths["intent"].read_text(encoding="utf-8"))
        stale_intent["as_of_source"] = "2026-05-08"
        write_json(paths["intent"], stale_intent)
        with self.assertRaisesRegex(RuntimeError, "diverges from Production Core"):
            fast_refresh.validate_canonical_execution_chain_sync(
                root=root,
                require_execution_health=False,
            )

    def test_data_health_blocks_stale_or_misaligned_canonical_execution(self):
        root, paths = self.make_root()
        context = {
            "latest_closed_utc_day": DAY,
            "btc_last_day": DAY,
            "active_strategy_closed_day": DAY,
            "main_strategy_model": MODEL,
        }
        intent_source = data_health_common.evaluate_source(
            spec=data_health_common.SOURCE_INDEX["execution_latest_execution_intent"],
            root=root,
            reference_now=None,
            context=context,
            path_overrides={},
            env_overrides={},
        )
        gate_source = data_health_common.evaluate_source(
            spec=data_health_common.SOURCE_INDEX[
                "execution_latest_real_order_gate_decision"
            ],
            root=root,
            reference_now=None,
            context=context,
            path_overrides={},
            env_overrides={},
        )
        self.assertEqual(intent_source["status"], "ok")
        self.assertEqual(gate_source["status"], "ok")

        stale_intent = json.loads(paths["intent"].read_text(encoding="utf-8"))
        stale_intent["as_of_source"] = "2026-05-08"
        write_json(paths["intent"], stale_intent)
        stale_source = data_health_common.evaluate_source(
            spec=data_health_common.SOURCE_INDEX["execution_latest_execution_intent"],
            root=root,
            reference_now=None,
            context=context,
            path_overrides={},
            env_overrides={},
        )
        stale_summary = data_health_common.summarize_sources([stale_source])
        self.assertNotEqual(stale_source["status"], "ok")
        self.assertTrue(stale_summary["block_execution"])

        root, paths = self.make_root()
        gate = json.loads(paths["gate"].read_text(encoding="utf-8"))
        gate["target_asset"] = "CASH"
        write_json(paths["gate"], gate)
        mismatched_gate = data_health_common.evaluate_source(
            spec=data_health_common.SOURCE_INDEX[
                "execution_latest_real_order_gate_decision"
            ],
            root=root,
            reference_now=None,
            context=context,
            path_overrides={},
            env_overrides={},
        )
        self.assertEqual(mismatched_gate["status"], "failed")
        self.assertTrue(
            data_health_common.summarize_sources([mismatched_gate])["block_execution"]
        )

    def test_temporary_execution_overrides_cannot_mask_stale_canonical_files(self):
        root, _paths = self.make_root()
        with self.assertRaisesRegex(ValueError, "must use canonical paths"):
            data_health_common.build_report_bundle(
                root=root,
                output_dir=root / "outputs/production",
                path_overrides={
                    "execution_latest_execution_intent": str(
                        root / "outputs/execution/tmp/synthetic_intent.json"
                    ),
                    "execution_latest_real_order_gate_decision": str(
                        root / "outputs/execution/tmp/synthetic_gate.json"
                    ),
                },
                write_outputs=False,
            )

    def test_in_progress_authority_is_healthy_only_when_bound_to_same_canonical_intent(self):
        root, paths = self.make_root()
        intent = json.loads(paths["intent"].read_text(encoding="utf-8"))
        intent["guardrail_flags"].update(
            {
                "same_run_authority_allowed": True,
                "same_run_authority_run_id": "run-current",
                "same_run_authority_target_closed_day": DAY,
            }
        )
        write_json(paths["intent"], intent)
        attempt_path = root / "outputs/execution/authority/latest_attempt_status.json"
        write_json(
            attempt_path,
            {
                "artifact_type": "execution_authority_latest_attempt_status",
                "target_closed_day_utc": DAY,
                "latest_authoritative_attempt_status": "in_progress",
                "currentness_status": "current",
                "generated_at_utc": "2026-09-01T00:15:00Z",
                "run_id": "run-current",
            },
        )
        context = {
            "latest_closed_utc_day": DAY,
            "btc_last_day": DAY,
            "active_strategy_closed_day": DAY,
            "main_strategy_model": MODEL,
        }
        current = data_health_common.evaluate_source(
            spec=data_health_common.SOURCE_INDEX["execution_authority_latest_attempt_status"],
            root=root,
            reference_now=None,
            context=context,
            path_overrides={},
            env_overrides={},
        )
        self.assertEqual(current["status"], "ok")

        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt["run_id"] = "different-run"
        write_json(attempt_path, attempt)
        mismatch = data_health_common.evaluate_source(
            spec=data_health_common.SOURCE_INDEX["execution_authority_latest_attempt_status"],
            root=root,
            reference_now=None,
            context=context,
            path_overrides={},
            env_overrides={},
        )
        self.assertEqual(mismatch["status"], "failed")
        self.assertTrue(
            data_health_common.summarize_sources([mismatch])["block_execution"]
        )

    def run_gate_case(
        self,
        *,
        target_asset: str,
        target_exposure: float,
        duplicate_order_risk: bool = False,
        stale_signal: bool = False,
        authority_day: str = DAY,
        allow_live_orders: bool = True,
        kill_switch: bool = False,
        production_validation: str = "passed",
    ) -> tuple[dict | None, Path]:
        root, paths = self.make_root(
            target_asset=target_asset,
            target_exposure=target_exposure,
        )
        production = json.loads(paths["production"].read_text(encoding="utf-8"))
        production["validation"]["status"] = production_validation
        write_json(paths["production"], production)
        intent = json.loads(paths["intent"].read_text(encoding="utf-8"))
        intent["duplicate_order_risk"] = duplicate_order_risk
        intent["stale_signal"] = stale_signal
        write_json(paths["intent"], intent)

        mode_path = root / "execution/config/execution_mode.json"
        policy_path = root / "execution/config/live_order_policy.json"
        authority_path = (
            root / "outputs/execution/authority/latest_successful_snapshot.json"
        )
        decision_path = root / "gate/decision.json"
        quality_path = root / "gate/quality.json"
        manifest_path = root / "gate/manifest.json"
        write_json(
            mode_path,
            {
                "mode": "live",
                "trading_enabled": True,
                "dry_run_enabled": False,
                "kill_switch": kill_switch,
            },
        )
        write_json(
            policy_path,
            {
                "allow_live_orders": allow_live_orders,
                "manual_approval_required": False,
                "require_kill_switch_off": True,
                "sizing_mode": "equity_target_exposure",
                "max_strategy_target_exposure": 2.0,
                "allowed_assets": ["BTC", "CASH"],
                "allowed_approval_gate_statuses": ["approved_and_applied"],
            },
        )
        write_json(
            authority_path,
            {
                "target_closed_day_utc": authority_day,
                "app_product_snapshot": {
                    "main_strategy_model": MODEL,
                    "strategy_last_closed_day": authority_day,
                    "live_public_state": {
                        "approval_gate_status": "approved_and_applied"
                    },
                },
            },
        )
        args = argparse.Namespace(
            mode_config_path=mode_path,
            live_order_policy_path=policy_path,
            intent_path=paths["intent"],
            snapshot_path=paths["account"],
            production_snapshot_path=paths["production"],
            authority_latest_successful_snapshot_path=authority_path,
            decision_path=decision_path,
            quality_path=quality_path,
            manifest_path=manifest_path,
        )
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(gate_builder, "parse_args", return_value=args))
            stack.enter_context(
                mock.patch.object(
                    gate_builder,
                    "build_report_bundle",
                    return_value={"report": {"sources": []}},
                )
            )
            stack.enter_context(mock.patch.object(gate_builder, "LOGS_DIR", root / "logs"))
            stack.enter_context(mock.patch.object(gate_builder, "LOG_PATH", root / "logs/gate.log"))
            try:
                gate_builder.main()
            except SystemExit:
                return None, decision_path
        return json.loads(decision_path.read_text(encoding="utf-8")), decision_path

    def test_cash_and_btc_gate_postures_are_safe_without_submission(self):
        mocked_submitter = mock.Mock(name="controlled_real_order_submitter")
        cash_gate, _ = self.run_gate_case(
            target_asset="CASH",
            target_exposure=0.0,
        )
        self.assertIsNotNone(cash_gate)
        self.assertEqual(cash_gate["status"], "no_action")
        self.assertFalse(cash_gate["would_place_real_order"])
        self.assertIn("no_market_entry_authorized", cash_gate["block_reasons"])

        btc_gate, _ = self.run_gate_case(
            target_asset="BTC",
            target_exposure=0.5,
        )
        self.assertIsNotNone(btc_gate)
        self.assertEqual(btc_gate["status"], "ready_if_enabled")
        self.assertTrue(btc_gate["would_place_real_order"])
        self.assertTrue(btc_gate["real_orders_enabled"])
        mocked_submitter.assert_not_called()

    def test_gate_and_intent_fail_closed_guardrails_remain_intact(self):
        duplicate_gate, _ = self.run_gate_case(
            target_asset="BTC",
            target_exposure=0.5,
            duplicate_order_risk=True,
        )
        self.assertIn("duplicate_order_risk", duplicate_gate["block_reasons"])

        stale_gate, _ = self.run_gate_case(
            target_asset="BTC",
            target_exposure=0.5,
            stale_signal=True,
        )
        self.assertIn("stale_signal", stale_gate["block_reasons"])

        authority_mismatch_gate, _ = self.run_gate_case(
            target_asset="BTC",
            target_exposure=0.5,
            authority_day="2026-08-30",
        )
        self.assertIn(
            "approval_source_day_mismatch",
            authority_mismatch_gate["block_reasons"],
        )

        blocked_policy_gate, _ = self.run_gate_case(
            target_asset="BTC",
            target_exposure=0.5,
            allow_live_orders=False,
            kill_switch=True,
        )
        self.assertIn("allow_live_orders=false", blocked_policy_gate["block_reasons"])
        self.assertIn("kill_switch_enabled", blocked_policy_gate["block_reasons"])

        invalid_gate, invalid_decision_path = self.run_gate_case(
            target_asset="BTC",
            target_exposure=0.5,
            production_validation="failed",
        )
        self.assertIsNone(invalid_gate)
        self.assertFalse(invalid_decision_path.exists())

        production = {
            "artifact_type": "current_strategy_snapshot",
            "strategy_version": MODEL,
            "closed_day": DAY,
            "strategy_status": "ready",
            "candidate_asset": "BTC",
            "current_asset": "BTC",
            "effective_market_exposure": 0.5,
            "model_candidate_exposure": 0.5,
            "trend_permission_active": True,
            "validation": {"status": "passed"},
            "execution_intent": {
                "signal_id": "signal",
                "target_asset": "BTC",
                "target_exposure": 0.5,
                "stale_signal": False,
                "allow_live_order_candidate": True,
            },
        }
        with mock.patch.object(
            intent_builder,
            "fail",
            side_effect=RuntimeError("blocked"),
        ):
            with self.assertRaisesRegex(RuntimeError, "blocked"):
                intent_builder.validate_authority_alignment(
                    latest_attempt_status={
                        "latest_authoritative_attempt_status": "success",
                        "currentness_status": "current",
                        "target_closed_day_utc": "2026-08-30",
                        "latest_available_closed_utc_day": "2026-08-30",
                    },
                    latest_successful_snapshot={
                        "latest_authoritative_attempt_status": "success",
                        "currentness_status": "current",
                        "target_closed_day_utc": "2026-08-30",
                        "latest_available_closed_utc_day": "2026-08-30",
                    },
                    expected_closed_day=production["closed_day"],
                )

    def test_repair_paths_never_include_a_real_order_submitter(self):
        planned_paths = {
            fast_refresh.build_publish_existing_dry_run_step(ROOT).script_path.name,
            fast_refresh.build_publish_existing_real_step(ROOT).script_path.name,
            "build_execution_intent_from_strategy_exports.py",
            "prepare_real_order_gate.py",
        }
        self.assertNotIn("submit_controlled_real_order.py", planned_paths)
        self.assertNotIn("hyperliquid_live_canary.py", planned_paths)


if __name__ == "__main__":
    unittest.main()
