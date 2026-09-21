import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.execution import mrv1_self_healing_watchdog as watchdog
from scripts.production import data_health_common as health


def source(source_id="data_ohlcv_btcusdt_1d", status="stale", criticality="production_critical", action="block_execution"):
    return {"source_id": source_id, "status": status, "criticality": criticality,
            "action": action, "user_message_sk": "", "user_message_en": ""}


def state(incident="DEPENDENCY_UNHEALTHY", sources=None):
    return {"incident_class": incident, "sources": [source()] if sources is None else sources,
            "cache_stale": True, "errors": [], "expected_closed_utc_day": "2026-09-20",
            "production": {"known": True, "inactive": True, "timer_ready": True, "pending": False}}


class DependencyScopedWatchdogTests(unittest.TestCase):
    def test_real_stale_btc_blocks_only_new_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data/ohlcv/BTCUSDT_1d.csv"
            path.parent.mkdir(parents=True)
            path.write_text("date,open,high,low,close,volume\n2026-09-18,10,11,9,10,100\n")
            observed = health.evaluate_source(spec=health.SOURCE_INDEX["data_ohlcv_btcusdt_1d"],
                root=root, reference_now=datetime(2026, 9, 21, tzinfo=timezone.utc),
                context={"latest_closed_utc_day": "2026-09-20"}, path_overrides={}, env_overrides={})
        self.assertEqual(observed["status"], "stale")
        summary = health.summarize_sources([observed])
        self.assertEqual(summary["blocked_action_ids"], ["new_trade_transition"])
        self.assertEqual(summary["affected_capability_ids"], ["new_trade_transition"])
        self.assertTrue(summary["block_execution"])
        self.assertTrue(summary["system_available"])
        self.assertFalse(summary["block_app"])
        self.assertEqual(summary["app_status"], "ok")
        report = {"sources": [observed], "summary": summary}
        for action_id in ["dashboard", "account_status", "scheduler", "independent_research"]:
            self.assertEqual(health.execution_blocking_sources(report, action_id=action_id), [])
        self.assertFalse(health.homepage_data_health_view(report)["block_app"])

    def test_research_failure_only_degrades_its_capability(self):
        s = source("research_btc_derivatives_daily_panel_csv", "missing", "research_only", "block_research_probe")
        summary = health.summarize_sources([s])
        self.assertEqual(summary["affected_capability_ids"], ["research_btc_derivatives"])
        self.assertEqual(summary["blocked_action_ids"], ["run_research_btc_derivatives"])
        self.assertFalse(summary["block_execution"])
        self.assertFalse(summary["block_app"])
        self.assertTrue(summary["system_available"])

    def test_dynamic_etf_production_dependency_keeps_trade_block(self):
        s = source("research_btc_etf_flow_daily_panel_csv")
        self.assertEqual(health.dependency_impact(s)["blocked_action_ids"], ["new_trade_transition"])

    def test_unknown_incident_never_disables_system(self):
        with patch.object(watchdog, "collect_state", return_value=state("unrecognized", [])):
            report, _ = watchdog.build_report(remediation_enabled=True)
        self.assertTrue(report["system_available"])
        self.assertTrue(report["needs_human"])
        self.assertFalse(report["block_app"])
        self.assertEqual(report["action_taken"], "none")

    def ai(self, observed, response=None, error=None):
        action = watchdog.choose_safe_action(observed["incident_class"], observed)
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unit-test-placeholder"}, clear=True), patch.object(
                watchdog.openai_responses, "invoke_structured_response", return_value=response, side_effect=error) as invoke:
            result = watchdog.ai_diagnose(observed, action, enabled=True)
        return result, invoke

    def test_ai_cannot_select_action_outside_incident_allowlist(self):
        for observed, action_id in [(state(), "run_pi_fast_daily_authority_refresh"),
                                    (state("UNKNOWN_NEEDS_HUMAN"), watchdog.ACTION_ID)]:
            result, _ = self.ai(observed, SimpleNamespace(status="completed", parsed={
                "action_id": action_id, "needs_human": False, "reason_code": "eligible_repair"}))
            self.assertEqual(result["action_id"], "none")
            self.assertTrue(result["needs_human"])

    def test_healthy_and_not_time_yet_never_call_api(self):
        for incident in ["OK_CURRENT", "NOT_TIME_YET", "DIAGNOSTIC_CACHE_STALE", "PRODUCTION_BUSY"]:
            result, invoke = self.ai(state(incident))
            invoke.assert_not_called()
            self.assertFalse(result["api_request_sent"])

    def test_ai_sends_only_sanitized_metadata_and_strict_schema(self):
        observed = state()
        observed["sources"][0].update(failure_reason="PRIVATE CONTENT", path="SECRET PATH", account="WALLET")
        result, invoke = self.ai(observed, SimpleNamespace(status="completed", parsed={
            "action_id": watchdog.ACTION_ID, "needs_human": False, "reason_code": "eligible_repair"}))
        self.assertEqual(result["action_id"], watchdog.ACTION_ID)
        sent = invoke.call_args.kwargs
        self.assertNotIn("PRIVATE", json.dumps(sent))
        self.assertNotIn("WALLET", json.dumps(sent))
        self.assertFalse(sent["schema"]["additionalProperties"])
        self.assertEqual(sent["schema"]["properties"]["action_id"]["enum"], ["none", watchdog.ACTION_ID])
        self.assertEqual(invoke.call_args.args[0]["model"], "gpt-5.4")

    def test_missing_key_and_api_failure_leave_deterministic_action(self):
        observed = state()
        action = watchdog.choose_safe_action(observed["incident_class"], observed)
        with patch.dict("os.environ", {}, clear=True), patch.object(watchdog.openai_responses, "invoke_structured_response") as call:
            result = watchdog.ai_diagnose(observed, action, enabled=True)
        call.assert_not_called()
        self.assertEqual(result["warning"], "missing_api_key")
        self.assertEqual(result["action_id"], watchdog.ACTION_ID)
        result, _ = self.ai(observed, error=watchdog.openai_responses.OpenAIResponsesError("timeout", "PRIVATE ERROR"))
        self.assertEqual(result["action_id"], watchdog.ACTION_ID)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_incomplete_and_malformed_ai_results_cannot_execute(self):
        for response in [SimpleNamespace(status="incomplete", parsed={}),
                         SimpleNamespace(status="completed", parsed={"action_id": watchdog.ACTION_ID})]:
            result, _ = self.ai(state(), response)
            self.assertEqual(result["action_id"], "none")
            self.assertTrue(result["needs_human"])

    def test_bad_ai_choice_overrides_deterministic_repair(self):
        with patch.object(watchdog, "collect_state", return_value=state()), patch.object(watchdog, "ai_diagnose", return_value={
            "action_id": "none", "needs_human": True, "warning": "invalid_ai_decision"}), patch.object(watchdog, "run_safe_action") as run:
            report, _ = watchdog.build_report(remediation_enabled=True, ai_enabled=True)
        run.assert_not_called()
        self.assertEqual(report["action_taken"], "none")

    def test_check_only_never_repairs_or_calls_api(self):
        with patch.object(watchdog, "collect_state", return_value=state()), patch.object(watchdog, "run_safe_action") as run, patch.object(
                watchdog.openai_responses, "invoke_structured_response") as api:
            report, _ = watchdog.build_report(remediation_enabled=False, ai_enabled=True)
        run.assert_not_called(); api.assert_not_called()
        self.assertEqual(report["action_taken"], "none")

    def test_production_start_race_skips_remediation(self):
        action = watchdog.choose_safe_action("DEPENDENCY_UNHEALTHY", state())
        changed = state(); changed["production"]["inactive"] = False
        with patch.object(watchdog, "collect_state", return_value=changed), patch.object(watchdog, "atomic_json") as write:
            result = watchdog.run_safe_action(action, state())
        write.assert_not_called()
        self.assertEqual(result["status"], "skipped")

    def test_arbitrary_command_or_legacy_action_never_runs(self):
        with patch.object(watchdog, "collect_state", return_value=state()), patch.object(watchdog, "atomic_json") as write:
            result = watchdog.run_safe_action({"eligible": True, "action": "submit_order", "command": ["anything"]}, state())
        write.assert_not_called(); self.assertEqual(result["status"], "skipped")
        self.assertFalse(watchdog.choose_safe_action("SCHEDULER_NOT_RUN", state())["eligible"])

    def test_atomic_cache_repair_only_changes_watchdog_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "watchdog/data_health"
            with patch.object(watchdog, "CACHE_DIR", cache), patch.object(watchdog, "collect_state", return_value=state()):
                result = watchdog.run_safe_action(watchdog.choose_safe_action("DEPENDENCY_UNHEALTHY", state()), state())
            self.assertEqual(result["status"], "completed")
            files = [p.relative_to(directory).as_posix() for p in Path(directory).rglob("*") if p.is_file()]
            self.assertEqual(files, ["watchdog/data_health/dependency_health_cache.json"])

    def test_interrupted_atomic_write_keeps_previous_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            watchdog.atomic_json(path, {"previous": True})
            with patch.object(watchdog.os, "replace", side_effect=OSError("interrupted")), self.assertRaises(OSError):
                watchdog.atomic_json(path, {"previous": False})
            self.assertEqual(json.loads(path.read_text()), {"previous": True})

    def test_timer_four_times_daily_and_resource_limits(self):
        root = Path(watchdog.ROOT)
        timer = (root / "deployment/systemd/mrv1-watchdog.timer").read_text()
        unit = (root / "deployment/systemd/mrv1-watchdog.service").read_text()
        self.assertIn("01,07,13,19:25:00 UTC", timer)
        self.assertNotIn("*:25:00 UTC", timer)
        self.assertIn("RandomizedDelaySec=5min", timer)
        for required in ["Nice=10", "CPUQuota=50%", "MemoryMax=1G", "User=trendatlas",
                         "--remediate-safe --ai-diagnose --json", "ProtectSystem=strict",
                         "EnvironmentFile=-/etc/default/trendatlas-watchdog"]:
            self.assertIn(required, unit)
        self.assertNotIn("Conflicts=", unit)

    def test_only_read_only_systemctl_subprocesses_exist(self):
        tree = ast.parse(Path(watchdog.__file__).read_text())
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any("exchange" in n or "run_pi_authoritative" in n for n in imports))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                self.assertEqual(node.func.attr, "check_output")
                self.assertEqual(node.args[0].elts[0].value, "systemctl")
                self.assertIn(node.args[0].elts[1].value, ["show", "list-jobs"])

    def test_shared_client_sends_strict_responses_schema_without_tools(self):
        import io
        decision = {"action_id": "none", "needs_human": True, "reason_code": "human_review"}
        envelope = {"id": "fixture", "status": "completed", "model": "gpt-5.4", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(decision)}]}]}
        with patch.dict("os.environ", {"OPENAI_API_KEY": "unit-test-placeholder"}, clear=True), patch.object(
                watchdog.openai_responses.request, "urlopen", return_value=io.BytesIO(json.dumps(envelope).encode())) as http:
            observed = state()
            result = watchdog.ai_diagnose(observed, watchdog.choose_safe_action(observed["incident_class"], observed), enabled=True)
        sent = json.loads(http.call_args.args[0].data)
        self.assertTrue(sent["text"]["format"]["strict"])
        self.assertEqual(sent["reasoning"]["effort"], "low")
        self.assertNotIn("tools", sent)
        self.assertEqual(result["action_id"], "none")

    def test_api_endpoint_and_key_name_cannot_be_redirected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = watchdog.load_ai_config()
            config["responses_api"] = "https://unapproved.invalid"
            path.write_text(json.dumps(config))
            with patch.object(watchdog, "CONFIG_PATH", path):
                result, call = self.ai(state())
        call.assert_not_called()
        self.assertEqual(result["warning"], "invalid_ai_config")


if __name__ == "__main__":
    unittest.main()
