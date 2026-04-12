import json
import shutil
import unittest
from unittest import mock
from pathlib import Path

from services.pc import worker_service
from services.pi import planner_service
from services.shared.openai_responses import StructuredResponseResult
from services.shared.runtime_bootstrap import collect_runtime_readiness, load_runtime_config
from services.shared.schemas import (
    FamilyRegistry,
    JOB_TYPE_PROPOSE_NEXT_MUTATION,
)


def build_family_registry() -> FamilyRegistry:
    return FamilyRegistry.from_mapping(
        {
            "schema_version": "research_os_mvp.v1",
            "registry_id": "test_registry",
            "owner": "MRV1 AI LAB",
            "families": [
                {
                    "family_id": "cost_aware_hysteretic_pilot_to_full",
                    "owner": "MRV1 AI LAB",
                    "status": "enabled",
                    "description": "Test family for planner OpenAI integration.",
                    "allowed_job_types": [JOB_TYPE_PROPOSE_NEXT_MUTATION],
                    "default_priority": 1,
                    "constraints": {
                        "dev_only": True,
                        "non_authoritative": True,
                        "live_trading": False,
                        "source_of_truth_mutation": False,
                        "official_promotion_logic": False,
                    },
                }
            ],
            "constraints": {
                "dev_only": True,
                "non_authoritative": True,
            },
        }
    )


def build_environment_scan() -> dict:
    return {
        "family_state_snapshot": {
            "path": "family_state.json",
            "payload": {
                "families": [
                    {
                        "family_id": "cost_aware_hysteretic_pilot_to_full",
                        "last_artifact_id": "cost_probe_recap_confirm",
                        "last_verdict": "stop_condition_triggered",
                        "last_metrics": {
                            "net_total_return_delta_pct": 125.0,
                            "net_cagr_delta_pct": 5.0,
                            "max_drawdown_delta_pct": -4.0,
                            "trade_days_delta": 6,
                            "switch_count_delta": 8,
                            "turnover_pressure_delta": 1.0,
                        },
                        "lineage": [
                            {
                                "artifact_id": "cost_probe_base",
                                "metrics": {
                                    "net_total_return_delta_pct": 40.0,
                                    "net_cagr_delta_pct": 2.0,
                                    "switch_count_delta": 2,
                                    "turnover_pressure_delta": 0.0,
                                },
                            },
                            {
                                "artifact_id": "cost_probe_recap_confirm",
                                "metrics": {
                                    "net_total_return_delta_pct": 125.0,
                                    "net_cagr_delta_pct": 5.0,
                                    "max_drawdown_delta_pct": -4.0,
                                    "trade_days_delta": 6,
                                    "switch_count_delta": 8,
                                    "turnover_pressure_delta": 1.0,
                                },
                            },
                        ],
                    }
                ]
            },
        },
        "market_state_snapshot": {
            "path": "market_state.json",
            "payload": {
                "snapshot_id": "latest_market_state",
                "market_context": {
                    "artifact_ids": ["cost_probe_base", "cost_probe_recap_confirm"],
                },
                "notes": ["dev_only_snapshot"],
            },
        },
    }


class TestResearchOSOpenAIRuntime(unittest.TestCase):
    def test_load_runtime_config_promotes_component_openai_enable_flags_when_runtime_block_is_missing(self):
        project_root = Path.cwd() / "tests_runtime_openai_component_enable_case"
        shutil.rmtree(project_root, ignore_errors=True)
        try:
            (project_root / "outputs/research_os/dev_only/mvp/registry").mkdir(parents=True)
            (project_root / "outputs/research_os/dev_only/mvp/artifacts").mkdir(parents=True)
            (project_root / "outputs/research_os/dev_only/mvp/runtime").mkdir(parents=True)
            config_path = project_root / "runtime_config.test.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "research_os_mvp.v1",
                        "role": "pi_orchestrator",
                        "registry_path": "outputs/research_os/dev_only/mvp/registry/research_os_mvp.sqlite",
                        "artifact_root": "outputs/research_os/dev_only/mvp/artifacts",
                        "runtime_root": "outputs/research_os/dev_only/mvp/runtime",
                        "queue_backend": "memory",
                        "redis_url": "redis://127.0.0.1:6379/0",
                        "streams": {
                            "worker_jobs": "research_os:worker_jobs",
                            "worker_results": "research_os:worker_results",
                            "heavy_validation_jobs": "research_os:heavy_validation_jobs",
                        },
                        "consumer_group": "research_os_pc_workers",
                        "consumer_name": "pi_orchestrator_01",
                        "planner": {
                            "enabled": True,
                            "openai": {
                                "enabled": True,
                                "model": "planner-model",
                                "prompt_template": "research_os_planner_mutation_proposal_v1",
                                "responses_api": "https://api.openai.com/v1/responses",
                            },
                        },
                        "critic": {
                            "enabled": True,
                            "openai": {
                                "enabled": True,
                                "model": "critic-model",
                                "prompt_template": "research_os_critic_family_verdict_v1",
                                "responses_api": "https://api.openai.com/v1/responses",
                            },
                        },
                        "scanner_paths": [],
                        "scanner_env_keys": [],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"RESEARCH_OS_ROOT": str(project_root)}, clear=False):
                config = load_runtime_config(config_path.name, require_root_env=True)
        finally:
            shutil.rmtree(project_root, ignore_errors=True)

        self.assertTrue(config.openai["enabled"])
        self.assertTrue(config.planner["openai"]["enabled"])
        self.assertTrue(config.critic["openai"]["enabled"])

    def test_load_runtime_config_applies_runtime_openai_enable_flag_to_planner_and_critic(self):
        project_root = Path.cwd() / "tests_runtime_openai_config_case"
        shutil.rmtree(project_root, ignore_errors=True)
        try:
            (project_root / "outputs/research_os/dev_only/mvp/registry").mkdir(parents=True)
            (project_root / "outputs/research_os/dev_only/mvp/artifacts").mkdir(parents=True)
            (project_root / "outputs/research_os/dev_only/mvp/runtime").mkdir(parents=True)
            config_path = project_root / "runtime_config.test.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "research_os_mvp.v1",
                        "role": "pi_orchestrator",
                        "registry_path": "outputs/research_os/dev_only/mvp/registry/research_os_mvp.sqlite",
                        "artifact_root": "outputs/research_os/dev_only/mvp/artifacts",
                        "runtime_root": "outputs/research_os/dev_only/mvp/runtime",
                        "queue_backend": "memory",
                        "redis_url": "redis://127.0.0.1:6379/0",
                        "streams": {
                            "worker_jobs": "research_os:worker_jobs",
                            "worker_results": "research_os:worker_results",
                            "heavy_validation_jobs": "research_os:heavy_validation_jobs",
                        },
                        "consumer_group": "research_os_pc_workers",
                        "consumer_name": "pi_orchestrator_01",
                        "openai": {
                            "enabled": True,
                            "model": "gpt-5.4",
                            "responses_api": "https://api.openai.com/v1/responses",
                            "timeout_seconds": 60,
                            "reasoning_effort": "medium",
                            "reasoning_summary": "auto",
                            "strict_schema_validation": True,
                            "fail_closed": True,
                        },
                        "planner": {
                            "enabled": True,
                            "openai": {
                                "enabled": False,
                                "model": "planner-model",
                                "prompt_template": "research_os_planner_mutation_proposal_v1",
                            },
                        },
                        "critic": {
                            "enabled": True,
                            "openai": {
                                "enabled": False,
                                "model": "critic-model",
                                "prompt_template": "research_os_critic_family_verdict_v1",
                            },
                        },
                        "scanner_paths": [],
                        "scanner_env_keys": [],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"RESEARCH_OS_ROOT": str(project_root)}, clear=False):
                config = load_runtime_config(config_path.name, require_root_env=True)
        finally:
            shutil.rmtree(project_root, ignore_errors=True)

        self.assertTrue(config.openai["enabled"])
        self.assertTrue(config.planner["openai"]["enabled"])
        self.assertTrue(config.critic["openai"]["enabled"])
        self.assertEqual(config.planner["openai"]["prompt_template"], "research_os_planner_mutation_proposal_v1")
        self.assertEqual(config.critic["openai"]["prompt_template"], "research_os_critic_family_verdict_v1")

    def test_collect_runtime_readiness_resolves_runtime_roots_against_research_os_root(self):
        project_root = Path.cwd() / "tests_runtime_readiness_paths_case"
        shutil.rmtree(project_root, ignore_errors=True)
        try:
            (project_root / "outputs/research_os/dev_only/mvp/registry").mkdir(parents=True)
            (project_root / "outputs/research_os/dev_only/mvp/artifacts").mkdir(parents=True)
            (project_root / "outputs/research_os/dev_only/mvp/runtime").mkdir(parents=True)
            config_path = project_root / "runtime_config.test.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "research_os_mvp.v1",
                        "role": "pi_orchestrator",
                        "registry_path": "outputs/research_os/dev_only/mvp/registry/research_os_mvp.sqlite",
                        "artifact_root": "outputs/research_os/dev_only/mvp/artifacts",
                        "runtime_root": "outputs/research_os/dev_only/mvp/runtime",
                        "queue_backend": "memory",
                        "redis_url": "redis://127.0.0.1:6379/0",
                        "streams": {
                            "worker_jobs": "research_os:worker_jobs",
                            "worker_results": "research_os:worker_results",
                            "heavy_validation_jobs": "research_os:heavy_validation_jobs",
                        },
                        "consumer_group": "research_os_pc_workers",
                        "consumer_name": "pi_orchestrator_01",
                        "openai": {"enabled": False},
                        "planner": {"enabled": True},
                        "critic": {"enabled": True},
                        "scanner_paths": [],
                        "scanner_env_keys": [],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"RESEARCH_OS_ROOT": str(project_root)}, clear=False):
                config = load_runtime_config(config_path.name, require_root_env=False)
                readiness = collect_runtime_readiness(
                    config,
                    config_path=config_path.name,
                    role=config.role,
                    require_root_env=False,
                )
        finally:
            shutil.rmtree(project_root, ignore_errors=True)

        checks = {check["name"]: check for check in readiness["checks"]}
        self.assertTrue(checks["artifact_root"]["ok"])
        self.assertEqual(checks["artifact_root"]["detail"], str((project_root / "outputs/research_os/dev_only/mvp/artifacts").resolve()))
        self.assertTrue(checks["runtime_root"]["ok"])
        self.assertEqual(checks["runtime_root"]["detail"], str((project_root / "outputs/research_os/dev_only/mvp/runtime").resolve()))
        self.assertTrue(checks["registry_parent"]["ok"])
        self.assertEqual(
            checks["registry_parent"]["detail"],
            str((project_root / "outputs/research_os/dev_only/mvp/registry").resolve()),
        )

    def test_planner_component_enable_flag_is_not_lost_when_runtime_default_is_disabled(self):
        planner_input = planner_service.build_planner_input(
            request_id="planner_component_enable_test",
            family_registry=build_family_registry(),
            environment_scan=build_environment_scan(),
        )
        mocked_response = StructuredResponseResult(
            response_id="resp_planner_component_enable_123",
            model="gpt-5.4",
            status="completed",
            parsed={
                "mechanism_hypothesis": "Keep the same family, but narrow the recap gate.",
                "selection_rationale": "A single rule restriction is the narrowest valid next step.",
                "mutation_target": {
                    "target_id": "state_machine.pilot_entry.narrow_recap_gate",
                    "target_type": "single_rule_restriction",
                    "source_artifact_id": "cost_probe_recap_confirm",
                    "exact_change": "Cap PILOT re-entry attempts at one per constructive stretch.",
                },
                "stop_condition": "Reject if turnover pressure remains above 0.",
            },
            output_text="{}",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )

        with mock.patch.object(planner_service, "invoke_structured_response", return_value=mocked_response):
            output = planner_service.plan_jobs(
                planner_input=planner_input,
                artifact_root="outputs/research_os/dev_only/test_openai_runtime_artifacts",
                openai_config={
                    "enabled": False,
                    "model": "gpt-5.4",
                    "prompt_template": "research_os_planner_mutation_proposal_v1",
                    "responses_api": "https://api.openai.com/v1/responses",
                },
                planner_config={
                    "enabled": True,
                    "openai": {
                        "enabled": True,
                        "model": "gpt-5.4",
                        "prompt_template": "research_os_planner_mutation_proposal_v1",
                        "responses_api": "https://api.openai.com/v1/responses",
                    },
                },
            )

        self.assertTrue(output.openai_hook["enabled"])
        self.assertEqual(output.openai_hook["effective_openai_source"]["enabled_from"], "planner.openai.enabled")
        self.assertEqual(output.openai_hook["network_call"], "completed")

    def test_critic_component_enable_flag_is_not_lost_when_runtime_default_is_disabled(self):
        effective_config, effective_source = worker_service._resolve_critic_openai_config(
            runtime_openai_config={
                "enabled": False,
                "model": "gpt-5.4",
                "responses_api": "https://api.openai.com/v1/responses",
            },
            critic_component_openai_config={
                "enabled": True,
                "model": "gpt-5.4",
                "prompt_template": "research_os_critic_family_verdict_v1",
                "responses_api": "https://api.openai.com/v1/responses",
            },
        )

        self.assertTrue(effective_config["enabled"])
        self.assertEqual(effective_source["enabled_from"], "critic.openai.enabled")

    def test_plan_jobs_applies_openai_mutation_fields(self):
        planner_input = planner_service.build_planner_input(
            request_id="planner_openai_test",
            family_registry=build_family_registry(),
            environment_scan=build_environment_scan(),
        )
        mocked_response = StructuredResponseResult(
            response_id="resp_planner_123",
            model="gpt-5.4",
            status="completed",
            parsed={
                "mechanism_hypothesis": "Narrow the recap gate to reduce churn while keeping the family structure unchanged.",
                "selection_rationale": "The latest attempt remains net positive but breaches churn and DD guardrails.",
                "mutation_target": {
                    "target_id": "state_machine.pilot_entry.narrow_recap_gate",
                    "target_type": "single_rule_restriction",
                    "source_artifact_id": "cost_probe_recap_confirm",
                    "exact_change": "Require one recapture window and cap PILOT re-entry attempts at one per constructive stretch.",
                },
                "stop_condition": "Reject if the narrowed recap gate still leaves turnover pressure above 0 or DD below -1.0.",
            },
            output_text="{}",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )

        with mock.patch.object(planner_service, "invoke_structured_response", return_value=mocked_response):
            output = planner_service.plan_jobs(
                planner_input=planner_input,
                artifact_root="outputs/research_os/dev_only/test_openai_runtime_artifacts",
                openai_config={
                    "enabled": True,
                    "model": "gpt-5.4",
                    "prompt_template": "research_os_planner_mutation_proposal_v1",
                    "responses_api": "https://api.openai.com/v1/responses",
                },
            )

        self.assertEqual(output.openai_hook["network_call"], "completed")
        self.assertEqual(output.openai_hook["response_id"], "resp_planner_123")
        self.assertEqual(output.notes[1], "planner_openai_response_applied")
        self.assertEqual(len(output.jobs), 1)
        proposal = output.jobs[0]["payload"]["mutation_proposal"]
        self.assertEqual(
            proposal["mechanism_hypothesis"],
            "Narrow the recap gate to reduce churn while keeping the family structure unchanged.",
        )
        self.assertEqual(proposal["mutation_target"]["target_id"], "state_machine.pilot_entry.narrow_recap_gate")
        self.assertFalse(proposal["mutation_target"]["execution_allowed"])
        self.assertEqual(proposal["mutation_target"]["scope"], "dev_only_queue_ready_heavy_job_request_only")

    def test_build_family_verdict_keeps_deterministic_guardrails_authoritative(self):
        mocked_response = StructuredResponseResult(
            response_id="resp_critic_123",
            model="gpt-5.4",
            status="completed",
            parsed={
                "recommended_verdict": "continue",
                "recommended_next_action": "continue_family",
                "recommended_reason": "continue: the candidate still looks attractive overall.",
                "guardrail_breaches": [],
                "policy_alignment_note": "The candidate remains promising.",
            },
            output_text="{}",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )
        summary = {
            "request_id": "critic_test_request",
            "proposal_id": "critic_test_proposal",
            "family_id": "cost_aware_hysteretic_pilot_to_full",
            "job_id": "critic_test_job",
            "adapter_id": "safe_dev_only_artifact_adapter_v1",
            "stop_condition": "Reject if switch_count_delta > 4 or turnover_pressure_delta > 0.0.",
            "mutation_target": {
                "source_artifact_id": "cost_probe_recap_confirm",
            },
        }
        compare_rows = [
            {
                "metric": "net_benefit",
                "basis_json": "{\"latest_net_total_return_delta_pct\": 125.0}",
            },
            {
                "metric": "dd",
                "basis_json": "{\"latest_max_drawdown_delta_pct\": -4.0}",
            },
            {
                "metric": "switch_count",
                "basis_json": "{\"latest_switch_count_delta\": 8}",
            },
            {
                "metric": "churn",
                "basis_json": "{\"latest_turnover_pressure_delta\": 1.0}",
            },
        ]
        cost_rows = [
            {
                "metric": "strategy_code_executed",
                "value": "false",
            }
        ]
        source_artifact = {
            "proposal": {
                "mutation_target": {
                    "source_artifact_id": "cost_probe_recap_confirm",
                    "target_id": "state_machine.pilot_entry.recap_confirm_gate",
                }
            },
            "proposal_lineage": {
                "source_last_metrics": {
                    "net_total_return_delta_pct": 125.0,
                    "max_drawdown_delta_pct": -4.0,
                    "trade_days_delta": 6,
                    "switch_count_delta": 8,
                    "turnover_pressure_delta": 1.0,
                }
            },
        }
        source_paths = {
            "summary": "summary.json",
            "compare": "compare.csv",
            "cost_metrics": "cost.csv",
        }

        with mock.patch.object(worker_service, "invoke_structured_response", return_value=mocked_response):
            verdict = worker_service.build_family_verdict(
                summary=summary,
                compare_rows=compare_rows,
                cost_rows=cost_rows,
                source_artifact=source_artifact,
                source_paths=source_paths,
                critic_job_id="critic_job_01",
                critic_openai_config={
                    "enabled": True,
                    "model": "gpt-5.4",
                    "prompt_template": "research_os_critic_family_verdict_v1",
                    "responses_api": "https://api.openai.com/v1/responses",
                },
            )

        self.assertEqual(verdict.verdict, "pause")
        self.assertEqual(verdict.next_action, "pause_family")
        self.assertIn("guardrails breached", verdict.verdict_reason)
        self.assertEqual(verdict.evidence["openai_review"]["network_call"], "completed")
        self.assertFalse(verdict.evidence["openai_review"]["recommendation_applied"])
        self.assertEqual(verdict.evidence["deterministic_policy_result"]["verdict"], "pause")


if __name__ == "__main__":
    unittest.main()
