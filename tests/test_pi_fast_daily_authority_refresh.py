import subprocess
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.execution import run_pi_fast_daily_authority_refresh as fast_refresh
from scripts.execution import mrv1_self_healing_watchdog as watchdog


class TestPiFastDailyAuthorityRefresh(unittest.TestCase):
    def _aligned_sync_summary(self) -> dict[str, object]:
        return {
            "production_closed_day": "2026-05-16",
            "intent_closed_day": "2026-05-16",
            "intent_target_asset": "CASH",
            "gate_target_asset": "CASH",
            "data_health_block_execution": False,
        }

    def _no_boundary_check(self) -> fast_refresh.RebalanceBoundaryDependencyCheck:
        return fast_refresh.RebalanceBoundaryDependencyCheck(
            status="not_crossed",
            needs_refresh=False,
            source_day="2026-05-16",
            target_day="2026-05-16",
            next_rebalance_date="2026-05-17",
            reason="unit_test_default_no_boundary",
        )

    def _run_with_fake_subprocess(self, env: dict[str, str]) -> tuple[dict, list[list[str]]]:
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(
            fast_refresh,
            "detect_rebalance_boundary_dependency_refresh",
            return_value=self._no_boundary_check(),
        ), mock.patch.object(
            fast_refresh,
            "validate_canonical_execution_chain_sync",
            return_value=self._aligned_sync_summary(),
        ), mock.patch.object(fast_refresh.subprocess, "run", side_effect=fake_run):
            result = fast_refresh.run_fast_daily_authority_refresh(env=env, root=ROOT)

        return result, calls

    def _make_temp_fast_root(
        self,
        *,
        source_day: str,
        target_day: str,
        next_rebalance_date: str,
    ) -> Path:
        tmp_base = ROOT / "tmp_test_artifacts"
        tmp_base.mkdir(parents=True, exist_ok=True)
        root = tmp_base / f"fast_daily_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, root, True)

        live_status_path = root / "outputs" / "execution" / "app_exports" / "phase66g_live_status.csv"
        live_status_path.parent.mkdir(parents=True, exist_ok=True)
        live_status_path.write_text(
            "latest_available_date,next_rebalance_date\n"
            f"{source_day},{next_rebalance_date}\n",
            encoding="utf-8",
        )
        btc_path = root / "data" / "ohlcv" / "BTCUSDT_1d.csv"
        btc_path.parent.mkdir(parents=True, exist_ok=True)
        btc_path.write_text(
            "date,close\n"
            f"{target_day},100000.0\n",
            encoding="utf-8",
        )
        return root

    def test_fast_dependency_plan_matches_required_order_and_flags(self):
        steps = fast_refresh.build_fast_dependency_steps(ROOT)
        self.assertEqual(
            [step.name for step in steps],
            [
                "refresh_legacy_ohlcv",
                "refresh_phase67_top100_shortlist_ohlcv",
                "phase60_selective_restore_robustness",
                "phase63_btc_participation_overlay",
                "phase66g_production_candidate_live",
                "phase67j_final_narrow_validation_pack",
                "dev_only_build_btc_etf_flow_daily_panel",
                "verify_app_freshness",
                "hyperliquid_read_only_snapshot",
                "hyperliquid_real_performance_ledger",
            ],
        )

        phase60_step = next(step for step in steps if step.name == "phase60_selective_restore_robustness")
        phase63_step = next(step for step in steps if step.name == "phase63_btc_participation_overlay")
        self.assertEqual(
            phase60_step.args,
            (
                "--dependency-only",
                "--model-key",
                "phase60_restore_trx_sol_base",
            ),
        )
        self.assertEqual(phase63_step.args[0], "--winner-only")
        self.assertEqual(phase63_step.args[1], "--variant-key")
        self.assertEqual(
            phase63_step.args[2],
            "phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3",
        )

        command_text = "\n".join(
            " ".join(fast_refresh.build_command(step))
            for step in (
                *steps,
                fast_refresh.build_production_core_dependency_materialize_step(ROOT),
                fast_refresh.build_current_strategy_snapshot_step(ROOT),
                fast_refresh.build_publish_existing_dry_run_step(ROOT),
                fast_refresh.build_publish_existing_real_step(ROOT),
            )
        )
        self.assertNotIn("full-refresh", command_text)
        for fragment in fast_refresh.FORBIDDEN_LIVE_ORDER_PATH_FRAGMENTS:
            self.assertNotIn(fragment, command_text)

        snapshot_step = next(step for step in steps if step.name == "hyperliquid_read_only_snapshot")
        self.assertEqual(Path(snapshot_step.script_path).name, "hyperliquid_read_only_snapshot.py")
        self.assertIn("scripts/execution/hyperliquid_read_only_snapshot.py", command_text.replace("\\", "/"))
        dependency_step = fast_refresh.build_production_core_dependency_materialize_step(ROOT)
        self.assertEqual(
            dependency_step.args,
            ("--production-core-dependencies-only",),
        )

    def test_rebalance_boundary_check_detects_crossed_boundary(self):
        root = self._make_temp_fast_root(
            source_day="2026-05-16",
            target_day="2026-05-18",
            next_rebalance_date="2026-05-17",
        )

        check = fast_refresh.detect_rebalance_boundary_dependency_refresh(root=root)

        self.assertTrue(check.needs_refresh)
        self.assertEqual(check.status, "rebalance_boundary_crossed")
        self.assertEqual(check.source_day, "2026-05-16")
        self.assertEqual(check.target_day, "2026-05-18")
        self.assertEqual(check.next_rebalance_date, "2026-05-17")

    def test_boundary_day_inserts_dependency_refresh_before_publish_existing(self):
        root = self._make_temp_fast_root(
            source_day="2026-05-16",
            target_day="2026-05-18",
            next_rebalance_date="2026-05-17",
        )
        calls: list[list[str]] = []

        def fake_step(step, *, env, root):
            command = fast_refresh.build_command(step)
            calls.append(command)
            return {
                "step_name": step.name,
                "script_path": fast_refresh.relative_display_path(step.script_path, root=root),
                "args": list(step.args),
                "returncode": 0,
            }

        with mock.patch.object(
            fast_refresh, "run_python_step", side_effect=fake_step
        ), mock.patch.object(
            fast_refresh,
            "validate_canonical_execution_chain_sync",
            return_value=self._aligned_sync_summary(),
        ):
            result = fast_refresh.run_fast_daily_authority_refresh(env={}, root=root)

        command_names = [Path(command[1]).name for command in calls]
        materialize_index = command_names.index("materialize_execution_app_exports.py")
        build_index = command_names.index("build_current_strategy_snapshot.py")
        producer_index = command_names.index("run_pi_authoritative_producer.py")

        self.assertLess(materialize_index, build_index)
        self.assertLess(build_index, producer_index)
        self.assertIn("--production-core-dependencies-only", calls[materialize_index])
        self.assertIn("--dry-run", calls[producer_index])
        self.assertEqual(result["rebalance_boundary_dependency_refresh"], "completed")
        self.assertEqual(
            result["rebalance_boundary_check"]["status"],
            "rebalance_boundary_crossed",
        )

    def test_non_boundary_day_keeps_existing_fast_path_before_publish(self):
        root = self._make_temp_fast_root(
            source_day="2026-05-16",
            target_day="2026-05-18",
            next_rebalance_date="2026-05-19",
        )
        calls: list[list[str]] = []

        def fake_step(step, *, env, root):
            command = fast_refresh.build_command(step)
            calls.append(command)
            return {
                "step_name": step.name,
                "script_path": fast_refresh.relative_display_path(step.script_path, root=root),
                "args": list(step.args),
                "returncode": 0,
            }

        with mock.patch.object(
            fast_refresh, "run_python_step", side_effect=fake_step
        ), mock.patch.object(
            fast_refresh,
            "validate_canonical_execution_chain_sync",
            return_value=self._aligned_sync_summary(),
        ):
            result = fast_refresh.run_fast_daily_authority_refresh(env={}, root=root)

        command_names = [Path(command[1]).name for command in calls]
        self.assertNotIn("materialize_execution_app_exports.py", command_names)
        self.assertNotIn("build_current_strategy_snapshot.py", command_names)
        self.assertEqual(command_names[-1], "run_pi_authoritative_producer.py")
        self.assertEqual(result["rebalance_boundary_dependency_refresh"], "skipped_no_boundary")

    def test_missing_safe_dependency_refresh_blocks_before_publish_existing(self):
        check = fast_refresh.RebalanceBoundaryDependencyCheck(
            status="not_evaluated",
            needs_refresh=True,
            reason="missing canonical dependency state",
        )
        calls: list[str] = []

        def fake_step(step, *, env, root):
            calls.append(step.name)
            if step.name == "materialize_production_core_dependencies":
                raise RuntimeError("dependency materialization unavailable")
            return {
                "step_name": step.name,
                "script_path": fast_refresh.relative_display_path(step.script_path, root=root),
                "args": list(step.args),
                "returncode": 0,
            }

        with mock.patch.object(
            fast_refresh,
            "detect_rebalance_boundary_dependency_refresh",
            return_value=check,
        ), mock.patch.object(fast_refresh, "run_python_step", side_effect=fake_step):
            with self.assertRaisesRegex(
                RuntimeError,
                fast_refresh.REBALANCE_BOUNDARY_BLOCKED_CODE,
            ):
                fast_refresh.run_fast_daily_authority_refresh(env={}, root=ROOT)

        self.assertIn("materialize_production_core_dependencies", calls)
        self.assertNotIn("publish_existing_dry_run", calls)

    def test_read_only_wallet_snapshot_precedes_publish_existing_dry_run(self):
        result, calls = self._run_with_fake_subprocess(
            {
                "MRV1_ENABLE_AUTHORITY_PUBLISH": "1",
                "MRV1_AUTHORITY_MODE": "authoritative",
            }
        )

        command_names = [Path(command[1]).name for command in calls]
        snapshot_index = command_names.index("hyperliquid_read_only_snapshot.py")
        producer_indices = [
            index
            for index, command in enumerate(calls)
            if Path(command[1]).name == "run_pi_authoritative_producer.py"
        ]

        self.assertEqual(len(producer_indices), 2)
        self.assertLess(snapshot_index, producer_indices[0])
        self.assertIn("--dry-run", calls[producer_indices[0]])
        self.assertEqual(result["hyperliquid_read_only_snapshot"], "completed")

    def test_publish_existing_dry_run_precedes_real_publish_when_env_gated(self):
        result, calls = self._run_with_fake_subprocess(
            {
                "MRV1_ENABLE_AUTHORITY_PUBLISH": "1",
                "MRV1_AUTHORITY_MODE": "authoritative",
            }
        )

        producer_calls = [
            command
            for command in calls
            if Path(command[1]).name == "run_pi_authoritative_producer.py"
        ]
        self.assertEqual(len(producer_calls), 2)
        self.assertIn("--dry-run", producer_calls[0])
        self.assertNotIn("--dry-run", producer_calls[1])
        self.assertEqual(producer_calls[0][-3:], ["--mode", "publish-existing", "--dry-run"])
        self.assertEqual(producer_calls[1][-2:], ["--mode", "publish-existing"])
        self.assertEqual(result["publish_existing_dry_run"], "completed")
        self.assertEqual(result["publish_existing_real"], "completed")
        self.assertEqual(result["live_order_chain"], "not_invoked")
        self.assertEqual(result["full_refresh_mode"], "not_invoked")

    def test_fast_cycle_validates_canonical_chain_after_dry_run_and_real_publish(self):
        sync_summary = self._aligned_sync_summary()
        with mock.patch.object(
            fast_refresh,
            "detect_rebalance_boundary_dependency_refresh",
            return_value=self._no_boundary_check(),
        ), mock.patch.object(
            fast_refresh,
            "run_python_step",
            return_value={"returncode": 0},
        ), mock.patch.object(
            fast_refresh,
            "validate_canonical_execution_chain_sync",
            return_value=sync_summary,
        ) as validate_sync:
            result = fast_refresh.run_fast_daily_authority_refresh(
                env={
                    "MRV1_ENABLE_AUTHORITY_PUBLISH": "1",
                    "MRV1_AUTHORITY_MODE": "authoritative",
                },
                root=ROOT,
            )

        self.assertEqual(
            validate_sync.call_args_list,
            [
                mock.call(root=ROOT, require_execution_health=False),
                mock.call(root=ROOT, require_execution_health=True),
            ],
        )
        self.assertEqual(result["canonical_execution_sync"], sync_summary)

    def test_real_publish_skipped_without_authority_env_gate(self):
        result, calls = self._run_with_fake_subprocess({})

        producer_calls = [
            command
            for command in calls
            if Path(command[1]).name == "run_pi_authoritative_producer.py"
        ]
        self.assertEqual(len(producer_calls), 1)
        self.assertIn("--dry-run", producer_calls[0])
        self.assertEqual(result["publish_existing_real"], "skipped_env_gate")

    def test_dry_run_failure_blocks_real_publish(self):
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            returncode = 1 if "--dry-run" in command else 0
            return subprocess.CompletedProcess(command, returncode)

        with mock.patch.object(
            fast_refresh,
            "detect_rebalance_boundary_dependency_refresh",
            return_value=self._no_boundary_check(),
        ), mock.patch.object(fast_refresh.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "publish_existing_dry_run failed"):
                fast_refresh.run_fast_daily_authority_refresh(
                    env={
                        "MRV1_ENABLE_AUTHORITY_PUBLISH": "1",
                        "MRV1_AUTHORITY_MODE": "authoritative",
                    },
                    root=ROOT,
                )

        producer_calls = [
            command
            for command in calls
            if Path(command[1]).name == "run_pi_authoritative_producer.py"
        ]
        self.assertEqual(len(producer_calls), 1)
        self.assertIn("--dry-run", producer_calls[0])

    def test_systemd_services_point_to_safe_wrapper(self):
        for relative_path in (
            "deploy/systemd/mrv1-nightly-runtime.service",
            "deploy/systemd/mrv1-daily-live.service",
        ):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("run_pi_fast_daily_authority_refresh.py", text)
            self.assertIn("MRV1_ENABLE_AUTHORITY_PUBLISH=1", text)
            self.assertIn("MRV1_AUTHORITY_MODE=authoritative", text)
            self.assertNotIn(
                "ExecStart=/opt/market_regime_v1/.venv/bin/python "
                "/opt/market_regime_v1/scripts/execution/run_pi_authoritative_producer.py",
                text,
            )

    def test_watchdog_scheduler_remediation_uses_safe_wrapper(self):
        action = watchdog.choose_safe_action("SCHEDULER_NOT_RUN", {})

        self.assertTrue(action["eligible"])
        self.assertEqual(action["action"], "run_pi_fast_daily_authority_refresh")
        self.assertEqual(
            Path(action["command"][1]).name,
            "run_pi_fast_daily_authority_refresh.py",
        )

    def test_source_contract_documents_single_production_orchestrator_and_internal_fast_path(self):
        text = (ROOT / "source_of_truth" / "pi_codex_runtime_workflow.md").read_text(
            encoding="utf-8"
        )
        required_snippets = [
            "scripts/execution/run_trendatlas_production.py",
            "run_pi_fast_daily_authority_refresh.py",
            "phase60_selective_restore_robustness.py --dependency-only --model-key phase60_restore_trx_sol_base",
            "scripts/phase63_btc_participation_overlay.py --winner-only --variant-key phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3",
            "scripts/execution/hyperliquid_read_only_snapshot.py",
            "scripts/execution/materialize_execution_app_exports.py --production-core-dependencies-only",
            "scripts/production/build_current_strategy_snapshot.py",
            "scripts/execution/run_pi_authoritative_producer.py --mode publish-existing --dry-run",
            "scripts/execution/build_execution_intent_from_strategy_exports.py",
            "scripts/execution/prepare_real_order_gate.py",
            "temporary execution-source path overrides are forbidden",
            "MRV1_ENABLE_AUTHORITY_PUBLISH=1",
            "MRV1_AUTHORITY_MODE=authoritative",
            "BLOCKED_REBALANCE_BOUNDARY_NEEDS_BASELINE_REFRESH",
            "must not invoke `--mode full-refresh`",
        ]
        missing = [snippet for snippet in required_snippets if snippet not in text]
        self.assertFalse(missing, f"Missing fast nightly wrapper contract snippets: {missing}")


if __name__ == "__main__":
    unittest.main()
