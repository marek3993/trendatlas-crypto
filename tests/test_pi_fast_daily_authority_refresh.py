import subprocess
import sys
import unittest
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
    def _run_with_fake_subprocess(self, env: dict[str, str]) -> tuple[dict, list[list[str]]]:
        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(fast_refresh.subprocess, "run", side_effect=fake_run):
            result = fast_refresh.run_fast_daily_authority_refresh(env=env, root=ROOT)

        return result, calls

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
                fast_refresh.build_publish_existing_dry_run_step(ROOT),
                fast_refresh.build_publish_existing_real_step(ROOT),
            )
        )
        self.assertNotIn("full-refresh", command_text)
        for fragment in fast_refresh.FORBIDDEN_LIVE_ORDER_PATH_FRAGMENTS:
            self.assertNotIn(fragment, command_text)

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

        with mock.patch.object(fast_refresh.subprocess, "run", side_effect=fake_run):
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

    def test_source_contract_documents_fast_nightly_wrapper(self):
        text = (ROOT / "source_of_truth" / "pi_codex_runtime_workflow.md").read_text(
            encoding="utf-8"
        )
        required_snippets = [
            "scripts/execution/run_pi_fast_daily_authority_refresh.py",
            "phase60_selective_restore_robustness.py --dependency-only --model-key phase60_restore_trx_sol_base",
            "scripts/phase63_btc_participation_overlay.py --winner-only --variant-key phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3",
            "scripts/execution/run_pi_authoritative_producer.py --mode publish-existing --dry-run",
            "MRV1_ENABLE_AUTHORITY_PUBLISH=1",
            "MRV1_AUTHORITY_MODE=authoritative",
            "must not invoke `--mode full-refresh`",
        ]
        missing = [snippet for snippet in required_snippets if snippet not in text]
        self.assertFalse(missing, f"Missing fast nightly wrapper contract snippets: {missing}")


if __name__ == "__main__":
    unittest.main()
