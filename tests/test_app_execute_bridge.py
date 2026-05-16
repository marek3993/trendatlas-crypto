import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution import app_execute_bridge as bridge


class TestAppExecuteBridgeDryRun(unittest.TestCase):
    def _fake_payload_for_path(self, path: Path) -> dict:
        path = Path(path)
        if path == bridge.SOURCE_CONTRACT_QUALITY_PATH:
            return {
                "contract_status": "valid",
                "ready_for_intent_builder": True,
            }
        if path == bridge.SOURCE_CONTRACT_REPORT_PATH:
            return {
                "contract_status": "valid",
                "hard_required_missing": [],
            }
        if path == bridge.DRY_RUN_DECISION_PATH:
            return {
                "generated_at_utc": "2026-05-15T11:35:00Z",
                "recommended_action": "hold_cash",
                "target_asset": "CASH",
                "simulated_order": {"would_place_order": False},
            }
        if path == bridge.GATE_PATH:
            return {
                "status": "blocked",
                "would_place_real_order": False,
            }
        if path == bridge.RECON_PATH:
            return {
                "current_state": "CASH",
                "reconciled": True,
            }
        raise AssertionError(f"Unexpected read_json path: {path}")

    def test_dry_run_validates_source_contract_before_intent_gate_without_full_materialize(self):
        calls: list[dict] = []

        def fake_run_allowlisted_script(*, script_path, step_name, arguments=None, timeout_sec=300):
            calls.append(
                {
                    "script_path": Path(script_path),
                    "step_name": step_name,
                    "arguments": tuple(arguments or ()),
                }
            )
            return {
                "step_name": step_name,
                "ok": True,
                "command": [sys.executable, str(script_path), *(arguments or [])],
            }

        with mock.patch.object(
            bridge,
            "run_allowlisted_script",
            side_effect=fake_run_allowlisted_script,
        ), mock.patch.object(
            bridge,
            "read_json",
            side_effect=self._fake_payload_for_path,
        ):
            result = bridge.run_dry_run_action()

        step_names = [call["step_name"] for call in calls]
        self.assertLess(
            step_names.index("validate_execution_source_contract"),
            step_names.index("build_execution_intent_from_strategy_exports"),
        )
        self.assertLess(
            step_names.index("validate_execution_source_contract"),
            step_names.index("run_dry_execution_bridge"),
        )
        self.assertLess(
            step_names.index("validate_execution_source_contract"),
            step_names.index("prepare_real_order_gate"),
        )

        materialize_calls = [
            call
            for call in calls
            if call["script_path"].resolve() == bridge.MATERIALIZE_SCRIPT_PATH.resolve()
        ]
        self.assertEqual(
            [call["arguments"] for call in materialize_calls],
            [("--runtime-snapshot-only",)],
        )
        command_text = "\n".join(
            " ".join([str(call["script_path"]), *call["arguments"]])
            for call in calls
        )
        self.assertNotIn("full-refresh", command_text)
        self.assertNotIn("submit_controlled_real_order.py", command_text)
        self.assertNotIn(str(bridge.SUBMIT_SCRIPT_PATH), command_text)
        self.assertEqual(result["status"], "dry_run_no_action")

    def test_source_contract_failure_blocks_intent_gate_and_marks_stale_artifacts_unusable(self):
        calls: list[str] = []

        def fake_run_allowlisted_script(*, script_path, step_name, arguments=None, timeout_sec=300):
            calls.append(step_name)
            if step_name == "validate_execution_source_contract":
                raise bridge.AppBridgeError(
                    "source contract invalid: phase66g_paper_last_date actual=2026-04-19",
                    status="failed",
                    details={"failed_step": {"step_name": step_name}},
                )
            return {
                "step_name": step_name,
                "ok": True,
                "command": [sys.executable, str(script_path), *(arguments or [])],
            }

        with mock.patch.object(
            bridge,
            "run_allowlisted_script",
            side_effect=fake_run_allowlisted_script,
        ), mock.patch.object(bridge, "log", return_value=None):
            result = bridge.run_app_execute_action(action="dry_run")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["intent_gate_mutation_status"], "not_started")
        self.assertFalse(result["stale_execution_artifacts_usable"])
        self.assertNotIn("build_execution_intent_from_strategy_exports", calls)
        self.assertNotIn("run_dry_execution_bridge", calls)
        self.assertNotIn("prepare_real_order_gate", calls)


if __name__ == "__main__":
    unittest.main()
