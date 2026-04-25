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
    SCHEMA_VERSION,
    WorkerJob,
    utc_now_iso,
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


def write_retrieval_packet(root: Path, *, family_id: str) -> Path:
    packet_path = root / "20260424T220103Z" / f"{family_id}.latest.retrieval_packet.json"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(
        json.dumps(
            {
                "schema_version": "trendatlas.imlayer.retrieval_packet.v1",
                "retrieval_generated_at_utc": "2026-04-24T22:01:03Z",
                "query": {
                    "family_id": family_id,
                    "memory_query_target": "latest",
                    "resolved_batch_id": "20260424T175234Z",
                },
                "family_summary": {
                    "latest_cycle_id": "openai_token_opt_rerun",
                    "latest_memory_id": f"trendatlas.crypto.decision_episode.openai_token_opt_rerun.{family_id}",
                    "latest_verdict": "pause",
                    "latest_action": "pause_family",
                    "selected_count": 1,
                    "risk_flag_union": ["dd below -1.0"],
                },
                "records": [
                    {
                        "decision": {
                            "verdict": "pause",
                            "action": "pause_family",
                        },
                        "decision_packet": {
                            "semantic_sha256": "abc123",
                        },
                        "run_context": {
                            "family_id": family_id,
                            "proposal_id": "proposal_01",
                            "critic_run_id": "critic_01",
                            "governor_run_id": "governor_01",
                            "validation_job_id": "validation_01",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return packet_path


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

    def test_plan_jobs_threads_retrieval_packet_passively_without_changing_openai_input(self):
        planner_input = planner_service.build_planner_input(
            request_id="planner_retrieval_packet_test",
            family_registry=build_family_registry(),
            environment_scan=build_environment_scan(),
        )
        retrieval_root = Path.cwd() / "tests_runtime_retrieval_packet_case"
        shutil.rmtree(retrieval_root, ignore_errors=True)
        try:
            write_retrieval_packet(retrieval_root, family_id="cost_aware_hysteretic_pilot_to_full")
            mocked_response = StructuredResponseResult(
                response_id="resp_planner_retrieval_packet_123",
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

            with mock.patch.object(planner_service, "invoke_structured_response", return_value=mocked_response) as invoke_mock:
                output = planner_service.plan_jobs(
                    planner_input=planner_input,
                    artifact_root="outputs/research_os/dev_only/test_openai_runtime_artifacts",
                    openai_config={
                        "enabled": True,
                        "model": "gpt-5.4",
                        "prompt_template": "research_os_planner_mutation_proposal_v1",
                        "responses_api": "https://api.openai.com/v1/responses",
                    },
                    planner_config={
                        "enabled": True,
                        "retrieval_packet": {
                            "enabled": True,
                            "root_dir": str(retrieval_root),
                        },
                    },
                )
        finally:
            shutil.rmtree(retrieval_root, ignore_errors=True)

        retrieval_packet = output.jobs[0]["payload"]["optional_input_artifacts"]["retrieval_packet"]
        self.assertEqual(retrieval_packet["status"], "loaded")
        self.assertEqual(retrieval_packet["summary"]["latest_memory_id"], "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full")
        self.assertTrue(output.openai_hook["passive_retrieval_comparison"]["retrieval_packet_present"])
        self.assertEqual(
            output.openai_hook["passive_retrieval_comparison"]["comparison_bucket"],
            "with_retrieval_packet",
        )
        self.assertEqual(
            output.jobs[0]["payload"]["runtime_debug"]["passive_retrieval_comparison"]["comparison_bucket"],
            "with_retrieval_packet",
        )
        controlled = output.openai_hook["controlled_retrieval_comparison"]
        self.assertEqual(controlled["authoritative_variant"], "without_retrieval_packet")
        self.assertEqual(controlled["candidate_variant"], "with_retrieval_packet")
        self.assertTrue(controlled["candidate_available"])
        self.assertFalse(controlled["constrained_influence"]["enabled"])
        self.assertEqual(
            controlled["constrained_influence"]["allowed_influence_fields"],
            ["mechanism_hypothesis", "selection_rationale"],
        )
        self.assertEqual(controlled["observations"]["candidate"]["status"], "disabled")
        self.assertGreater(
            controlled["candidate_prompt_metrics"]["json_char_count"],
            controlled["authoritative_prompt_metrics"]["json_char_count"],
        )
        self.assertIn("passive_retrieval_packet_status=loaded", output.notes)
        self.assertIn("passive_retrieval_packet_present=true", output.notes)
        self.assertIn("passive_retrieval_comparison_bucket=with_retrieval_packet", output.notes)
        self.assertIn("controlled_retrieval_comparison_disabled", output.notes)
        self.assertIn("controlled_retrieval_candidate_status=disabled", output.notes)
        self.assertNotIn("optional_input_artifacts", invoke_mock.call_args.kwargs["user_payload"])

    def test_plan_jobs_surfaces_missing_retrieval_packet_as_without_packet_bucket(self):
        planner_input = planner_service.build_planner_input(
            request_id="planner_missing_retrieval_packet_test",
            family_registry=build_family_registry(),
            environment_scan=build_environment_scan(),
        )

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
                "retrieval_packet": {
                    "enabled": True,
                    "root_dir": str(Path.cwd() / "tests_runtime_missing_retrieval_packet_case"),
                },
            },
        )

        self.assertFalse(output.openai_hook["passive_retrieval_comparison"]["retrieval_packet_present"])
        self.assertEqual(
            output.openai_hook["passive_retrieval_comparison"]["comparison_bucket"],
            "without_retrieval_packet",
        )
        self.assertEqual(
            output.jobs[0]["payload"]["runtime_debug"]["passive_retrieval_comparison"]["retrieval_packet_status"],
            "missing",
        )
        controlled = output.openai_hook["controlled_retrieval_comparison"]
        self.assertFalse(controlled["candidate_available"])
        self.assertFalse(controlled["constrained_influence"]["enabled"])
        self.assertEqual(controlled["candidate_prompt_metrics"], {})
        self.assertEqual(controlled["observations"]["candidate"]["status"], "disabled")
        self.assertIn("passive_retrieval_packet_status=missing", output.notes)
        self.assertIn("passive_retrieval_packet_present=false", output.notes)
        self.assertIn("passive_retrieval_comparison_bucket=without_retrieval_packet", output.notes)

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

    def test_build_family_verdict_surfaces_retrieval_packet_only_in_evidence(self):
        mocked_response = StructuredResponseResult(
            response_id="resp_critic_retrieval_packet_123",
            model="gpt-5.4",
            status="completed",
            parsed={
                "recommended_verdict": "pause",
                "recommended_next_action": "pause_family",
                "recommended_reason": "pause: guardrails remain breached.",
                "guardrail_breaches": ["dd below -1.0"],
                "policy_alignment_note": "Matches policy.",
            },
            output_text="{}",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )
        summary = {
            "request_id": "critic_retrieval_packet_request",
            "proposal_id": "critic_retrieval_packet_proposal",
            "family_id": "cost_aware_hysteretic_pilot_to_full",
            "job_id": "critic_retrieval_packet_job",
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
            "optional_input_artifacts": {
                "retrieval_packet": {
                    "status": "loaded",
                    "family_id": "cost_aware_hysteretic_pilot_to_full",
                    "summary": {
                        "latest_memory_id": "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
                    },
                    "payload": {
                        "schema_version": "trendatlas.imlayer.retrieval_packet.v1",
                    },
                }
            },
        }
        source_paths = {
            "summary": "summary.json",
            "compare": "compare.csv",
            "cost_metrics": "cost.csv",
        }

        with mock.patch.object(worker_service, "invoke_structured_response", return_value=mocked_response) as invoke_mock:
            verdict = worker_service.build_family_verdict(
                summary=summary,
                compare_rows=compare_rows,
                cost_rows=cost_rows,
                source_artifact=source_artifact,
                source_paths=source_paths,
                critic_job_id="critic_job_retrieval_packet_01",
                critic_openai_config={
                    "enabled": True,
                    "model": "gpt-5.4",
                    "prompt_template": "research_os_critic_family_verdict_v1",
                    "responses_api": "https://api.openai.com/v1/responses",
                },
            )

        self.assertIn("optional_input_artifacts", verdict.evidence)
        self.assertEqual(
            verdict.evidence["optional_input_artifacts"]["retrieval_packet"]["summary"]["latest_memory_id"],
            "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
        )
        self.assertTrue(verdict.evidence["passive_retrieval_comparison"]["retrieval_packet_present"])
        self.assertEqual(
            verdict.evidence["passive_retrieval_comparison"]["comparison_bucket"],
            "with_retrieval_packet",
        )
        self.assertEqual(
            verdict.evidence["openai_review"]["passive_retrieval_comparison"]["comparison_bucket"],
            "with_retrieval_packet",
        )
        controlled = verdict.evidence["controlled_retrieval_comparison"]
        self.assertTrue(controlled["candidate_available"])
        self.assertFalse(controlled["constrained_influence"]["enabled"])
        self.assertEqual(controlled["candidate_prompt_mode"], "compact")
        self.assertEqual(
            controlled["constrained_influence"]["allowed_influence_fields"],
            ["policy_alignment_note", "recommended_reason"],
        )
        self.assertEqual(controlled["observations"]["candidate"]["status"], "disabled")
        self.assertEqual(
            controlled["candidate_prompt_metrics"]["payload_sha256"],
            controlled["retrieval_prompt_observability"]["compact_retrieval_mode"]["prompt_metrics"]["payload_sha256"],
        )
        self.assertGreater(
            controlled["retrieval_prompt_observability"]["full_retrieval_mode"]["prompt_metrics"]["json_char_count"],
            controlled["retrieval_prompt_observability"]["compact_retrieval_mode"]["prompt_metrics"]["json_char_count"],
        )
        self.assertLess(
            controlled["retrieval_prompt_observability"]["token_delta_impact"]["compact_vs_full"]["estimated_input_tokens_char_div4_delta"],
            0,
        )
        self.assertNotIn("optional_input_artifacts", invoke_mock.call_args.kwargs["user_payload"])

    def test_plan_jobs_runs_shadow_retrieval_comparison_only_when_explicitly_enabled(self):
        planner_input = planner_service.build_planner_input(
            request_id="planner_shadow_retrieval_packet_test",
            family_registry=build_family_registry(),
            environment_scan=build_environment_scan(),
        )
        retrieval_root = Path.cwd() / "tests_runtime_shadow_retrieval_packet_case"
        shutil.rmtree(retrieval_root, ignore_errors=True)
        try:
            write_retrieval_packet(retrieval_root, family_id="cost_aware_hysteretic_pilot_to_full")
            authoritative_response = StructuredResponseResult(
                response_id="resp_planner_authoritative_123",
                model="gpt-5.4",
                status="completed",
                parsed={
                    "mechanism_hypothesis": "Keep the same family, but narrow the recap gate.",
                    "selection_rationale": "Authoritative path keeps the baseline packet-free prompt.",
                    "mutation_target": {
                        "target_id": "state_machine.pilot_entry.narrow_recap_gate",
                        "target_type": "single_rule_restriction",
                        "source_artifact_id": "cost_probe_recap_confirm",
                        "exact_change": "Cap PILOT re-entry attempts at one per constructive stretch.",
                    },
                    "stop_condition": "Reject if turnover pressure remains above 0.",
                },
                output_text="{}",
                usage={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
            )
            shadow_response = StructuredResponseResult(
                response_id="resp_planner_shadow_123",
                model="gpt-5.4",
                status="completed",
                parsed={
                    "mechanism_hypothesis": "Keep the same family, but use the retrieved episode context as a sidecar.",
                    "selection_rationale": "Shadow path observed retrieval context but did not affect the proposal.",
                    "mutation_target": {
                        "target_id": "state_machine.pilot_entry.narrow_recap_gate",
                        "target_type": "single_rule_restriction",
                        "source_artifact_id": "cost_probe_recap_confirm",
                        "exact_change": "Cap PILOT re-entry attempts at one per constructive stretch.",
                    },
                    "stop_condition": "Reject if turnover pressure remains above 0.",
                },
                output_text="{}",
                usage={"input_tokens": 22, "output_tokens": 1, "total_tokens": 23},
            )

            with mock.patch.object(
                planner_service,
                "invoke_structured_response",
                side_effect=[authoritative_response, shadow_response],
            ) as invoke_mock:
                output = planner_service.plan_jobs(
                    planner_input=planner_input,
                    artifact_root="outputs/research_os/dev_only/test_openai_runtime_artifacts",
                    openai_config={
                        "enabled": True,
                        "model": "gpt-5.4",
                        "prompt_template": "research_os_planner_mutation_proposal_v1",
                        "responses_api": "https://api.openai.com/v1/responses",
                    },
                    planner_config={
                        "enabled": True,
                        "retrieval_packet": {
                            "enabled": True,
                            "root_dir": str(retrieval_root),
                        },
                        "controlled_comparison": {
                            "enabled": True,
                        },
                    },
                )
        finally:
            shutil.rmtree(retrieval_root, ignore_errors=True)

        controlled = output.openai_hook["controlled_retrieval_comparison"]
        self.assertTrue(controlled["explicitly_enabled"])
        self.assertFalse(controlled["constrained_influence"]["enabled"])
        self.assertEqual(controlled["observations"]["candidate"]["status"], "completed")
        self.assertEqual(controlled["observations"]["authoritative"]["usage"]["input_tokens"], 10)
        self.assertEqual(controlled["observations"]["candidate"]["usage"]["input_tokens"], 22)
        self.assertTrue(controlled["observations"]["diff"]["has_note_differences"])
        self.assertEqual(invoke_mock.call_count, 2)
        self.assertNotIn("optional_input_artifacts", invoke_mock.call_args_list[0].kwargs["user_payload"])
        self.assertIn("optional_input_artifacts", invoke_mock.call_args_list[1].kwargs["user_payload"])
        candidate_packet = invoke_mock.call_args_list[1].kwargs["user_payload"]["optional_input_artifacts"]["retrieval_packet"]
        self.assertEqual(controlled["candidate_prompt_mode"], "compact")
        self.assertEqual(candidate_packet["retrieval_prompt_mode"], "compact")
        self.assertEqual(candidate_packet["top_k"], 1)
        self.assertEqual(
            candidate_packet["latest_memory_id"],
            "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
        )
        self.assertIn("latest_verdict", candidate_packet)
        self.assertIn("latest_action", candidate_packet)
        self.assertIn("risk_failure_bullets", candidate_packet)
        self.assertIn("memory_summary", candidate_packet)
        self.assertNotIn("payload", candidate_packet)
        self.assertNotIn("path", candidate_packet)
        self.assertLess(
            controlled["retrieval_prompt_observability"]["token_delta_impact"]["compact_vs_full"]["estimated_input_tokens_char_div4_delta"],
            0,
        )
        self.assertNotIn("retrieval_influence_contract", invoke_mock.call_args_list[1].kwargs["user_payload"])

    def test_plan_jobs_v2_constrains_shadow_retrieval_influence_to_allowed_fields(self):
        planner_input = planner_service.build_planner_input(
            request_id="planner_v2_shadow_retrieval_packet_test",
            family_registry=build_family_registry(),
            environment_scan=build_environment_scan(),
        )
        retrieval_root = Path.cwd() / "tests_runtime_shadow_retrieval_packet_case_v2"
        shutil.rmtree(retrieval_root, ignore_errors=True)
        try:
            write_retrieval_packet(retrieval_root, family_id="cost_aware_hysteretic_pilot_to_full")
            authoritative_response = StructuredResponseResult(
                response_id="resp_planner_authoritative_v2_123",
                model="gpt-5.4",
                status="completed",
                parsed={
                    "mechanism_hypothesis": "Authoritative planner reasoning.",
                    "selection_rationale": "Authoritative packet-free rationale.",
                    "mutation_target": {
                        "target_id": "state_machine.pilot_entry.narrow_recap_gate",
                        "target_type": "single_rule_restriction",
                        "source_artifact_id": "cost_probe_recap_confirm",
                        "exact_change": "Cap PILOT re-entry attempts at one per constructive stretch.",
                    },
                    "stop_condition": "Reject if turnover pressure remains above 0.",
                },
                output_text="{}",
                usage={"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
            )
            shadow_response = StructuredResponseResult(
                response_id="resp_planner_shadow_v2_123",
                model="gpt-5.4",
                status="completed",
                parsed={
                    "mechanism_hypothesis": "Retrieval-enhanced planner reasoning.",
                    "selection_rationale": "Retrieval-enhanced rationale.",
                    "mutation_target": {
                        "target_id": "state_machine.pilot_entry.changed_target",
                        "target_type": "broader_rule_type",
                        "source_artifact_id": "different_artifact",
                        "exact_change": "Broaden the change in a forbidden way.",
                    },
                    "stop_condition": "Different forbidden stop condition.",
                },
                output_text="{}",
                usage={"input_tokens": 22, "output_tokens": 1, "total_tokens": 23},
            )

            with mock.patch.object(
                planner_service,
                "invoke_structured_response",
                side_effect=[authoritative_response, shadow_response],
            ) as invoke_mock:
                output = planner_service.plan_jobs(
                    planner_input=planner_input,
                    artifact_root="outputs/research_os/dev_only/test_openai_runtime_artifacts",
                    openai_config={
                        "enabled": True,
                        "model": "gpt-5.4",
                        "prompt_template": "research_os_planner_mutation_proposal_v1",
                        "responses_api": "https://api.openai.com/v1/responses",
                    },
                    planner_config={
                        "enabled": True,
                        "retrieval_packet": {
                            "enabled": True,
                            "root_dir": str(retrieval_root),
                        },
                        "controlled_comparison": {
                            "enabled": True,
                            "constrained_influence_v2": {
                                "enabled": True,
                            },
                        },
                    },
                )
        finally:
            shutil.rmtree(retrieval_root, ignore_errors=True)

        controlled = output.openai_hook["controlled_retrieval_comparison"]
        candidate = controlled["observations"]["candidate"]
        diff = controlled["observations"]["diff"]
        self.assertTrue(controlled["constrained_influence"]["enabled"])
        self.assertEqual(
            controlled["constrained_influence"]["allowed_influence_fields"],
            ["mechanism_hypothesis", "selection_rationale"],
        )
        self.assertTrue(candidate["enforcement"]["blocked_fields_frozen"])
        self.assertTrue(candidate["enforcement"]["forbidden_field_change_attempted"])
        self.assertEqual(candidate["note_fields"]["mechanism_hypothesis"], "Retrieval-enhanced planner reasoning.")
        self.assertEqual(
            candidate["proposal_content_fields"]["target_id"],
            "state_machine.pilot_entry.narrow_recap_gate",
        )
        self.assertEqual(
            candidate["raw_proposal_content_fields"]["target_id"],
            "state_machine.pilot_entry.changed_target",
        )
        self.assertTrue(diff["proposal_content_fields_preserved"])
        self.assertTrue(diff["forbidden_field_change_attempted"])
        self.assertEqual(invoke_mock.call_count, 2)
        candidate_packet = invoke_mock.call_args_list[1].kwargs["user_payload"]["optional_input_artifacts"]["retrieval_packet"]
        self.assertEqual(controlled["candidate_prompt_mode"], "compact")
        self.assertEqual(candidate_packet["retrieval_prompt_mode"], "compact")
        self.assertEqual(candidate_packet["top_k"], 1)
        self.assertEqual(
            candidate_packet["latest_memory_id"],
            "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
        )
        self.assertIn("latest_verdict", candidate_packet)
        self.assertIn("latest_action", candidate_packet)
        self.assertNotIn("payload", candidate_packet)
        self.assertNotIn("path", candidate_packet)
        self.assertLess(
            controlled["retrieval_prompt_observability"]["token_delta_impact"]["compact_vs_full"]["estimated_input_tokens_char_div4_delta"],
            0,
        )
        self.assertIn("retrieval_influence_contract", invoke_mock.call_args_list[1].kwargs["user_payload"])

    def test_build_family_verdict_runs_shadow_retrieval_comparison_only_when_explicitly_enabled(self):
        authoritative_response = StructuredResponseResult(
            response_id="resp_critic_authoritative_123",
            model="gpt-5.4",
            status="completed",
            parsed={
                "recommended_verdict": "pause",
                "recommended_next_action": "pause_family",
                "recommended_reason": "Authoritative path follows the packet-free review.",
                "guardrail_breaches": ["dd below -1.0"],
                "policy_alignment_note": "Authoritative packet-free note.",
            },
            output_text="{}",
            usage={"input_tokens": 14, "output_tokens": 1, "total_tokens": 15},
        )
        shadow_response = StructuredResponseResult(
            response_id="resp_critic_shadow_123",
            model="gpt-5.4",
            status="completed",
            parsed={
                "recommended_verdict": "pause",
                "recommended_next_action": "pause_family",
                "recommended_reason": "Shadow path saw retrieval context but did not change the verdict.",
                "guardrail_breaches": ["dd below -1.0"],
                "policy_alignment_note": "Shadow retrieval note.",
            },
            output_text="{}",
            usage={"input_tokens": 29, "output_tokens": 1, "total_tokens": 30},
        )
        summary = {
            "request_id": "critic_shadow_retrieval_packet_request",
            "proposal_id": "critic_shadow_retrieval_packet_proposal",
            "family_id": "cost_aware_hysteretic_pilot_to_full",
            "job_id": "critic_shadow_retrieval_packet_job",
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
            "optional_input_artifacts": {
                "retrieval_packet": {
                    "status": "loaded",
                    "family_id": "cost_aware_hysteretic_pilot_to_full",
                    "summary": {
                        "latest_memory_id": "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
                    },
                    "payload": {
                        "schema_version": "trendatlas.imlayer.retrieval_packet.v1",
                    },
                }
            },
        }
        source_paths = {
            "summary": "summary.json",
            "compare": "compare.csv",
            "cost_metrics": "cost.csv",
        }

        with mock.patch.object(
            worker_service,
            "invoke_structured_response",
            side_effect=[authoritative_response, shadow_response],
        ) as invoke_mock:
            verdict = worker_service.build_family_verdict(
                summary=summary,
                compare_rows=compare_rows,
                cost_rows=cost_rows,
                source_artifact=source_artifact,
                source_paths=source_paths,
                critic_job_id="critic_job_shadow_retrieval_packet_01",
                critic_openai_config={
                    "enabled": True,
                    "model": "gpt-5.4",
                    "prompt_template": "research_os_critic_family_verdict_v1",
                    "responses_api": "https://api.openai.com/v1/responses",
                },
                critic_config={
                    "controlled_comparison": {
                        "enabled": True,
                    }
                },
            )

        controlled = verdict.evidence["controlled_retrieval_comparison"]
        self.assertTrue(controlled["explicitly_enabled"])
        self.assertFalse(controlled["constrained_influence"]["enabled"])
        self.assertEqual(controlled["observations"]["candidate"]["status"], "completed")
        self.assertEqual(controlled["observations"]["authoritative"]["usage"]["input_tokens"], 14)
        self.assertEqual(controlled["observations"]["candidate"]["usage"]["input_tokens"], 29)
        self.assertTrue(controlled["observations"]["diff"]["has_note_differences"])
        self.assertEqual(invoke_mock.call_count, 2)
        self.assertNotIn("optional_input_artifacts", invoke_mock.call_args_list[0].kwargs["user_payload"])
        self.assertIn("optional_input_artifacts", invoke_mock.call_args_list[1].kwargs["user_payload"])
        candidate_packet = invoke_mock.call_args_list[1].kwargs["user_payload"]["optional_input_artifacts"]["retrieval_packet"]
        self.assertEqual(controlled["candidate_prompt_mode"], "compact")
        self.assertEqual(candidate_packet["retrieval_prompt_mode"], "compact")
        self.assertEqual(candidate_packet["top_k"], 1)
        self.assertEqual(
            candidate_packet["latest_memory_id"],
            "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
        )
        self.assertIn("latest_verdict", candidate_packet)
        self.assertIn("latest_action", candidate_packet)
        self.assertNotIn("payload", candidate_packet)
        self.assertNotIn("path", candidate_packet)
        self.assertLess(
            controlled["retrieval_prompt_observability"]["token_delta_impact"]["compact_vs_full"]["estimated_input_tokens_char_div4_delta"],
            0,
        )
        self.assertNotIn("retrieval_influence_contract", invoke_mock.call_args_list[1].kwargs["user_payload"])

    def test_build_family_verdict_v2_freezes_forbidden_shadow_fields(self):
        authoritative_response = StructuredResponseResult(
            response_id="resp_critic_authoritative_v2_123",
            model="gpt-5.4",
            status="completed",
            parsed={
                "recommended_verdict": "pause",
                "recommended_next_action": "pause_family",
                "recommended_reason": "Authoritative path follows the packet-free review.",
                "guardrail_breaches": ["dd below -1.0"],
                "policy_alignment_note": "Authoritative packet-free note.",
            },
            output_text="{}",
            usage={"input_tokens": 14, "output_tokens": 1, "total_tokens": 15},
        )
        shadow_response = StructuredResponseResult(
            response_id="resp_critic_shadow_v2_123",
            model="gpt-5.4",
            status="completed",
            parsed={
                "recommended_verdict": "continue",
                "recommended_next_action": "continue_family",
                "recommended_reason": "Retrieval-enhanced reason.",
                "guardrail_breaches": ["dd below -1.0"],
                "policy_alignment_note": "Retrieval-enhanced note.",
            },
            output_text="{}",
            usage={"input_tokens": 29, "output_tokens": 1, "total_tokens": 30},
        )
        summary = {
            "request_id": "critic_shadow_retrieval_packet_request_v2",
            "proposal_id": "critic_shadow_retrieval_packet_proposal_v2",
            "family_id": "cost_aware_hysteretic_pilot_to_full",
            "job_id": "critic_shadow_retrieval_packet_job_v2",
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
            "optional_input_artifacts": {
                "retrieval_packet": {
                    "status": "loaded",
                    "family_id": "cost_aware_hysteretic_pilot_to_full",
                    "summary": {
                        "latest_memory_id": "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
                    },
                    "payload": {
                        "schema_version": "trendatlas.imlayer.retrieval_packet.v1",
                    },
                }
            },
        }
        source_paths = {
            "summary": "summary.json",
            "compare": "compare.csv",
            "cost_metrics": "cost.csv",
        }

        with mock.patch.object(
            worker_service,
            "invoke_structured_response",
            side_effect=[authoritative_response, shadow_response],
        ) as invoke_mock:
            verdict = worker_service.build_family_verdict(
                summary=summary,
                compare_rows=compare_rows,
                cost_rows=cost_rows,
                source_artifact=source_artifact,
                source_paths=source_paths,
                critic_job_id="critic_job_shadow_retrieval_packet_v2_01",
                critic_openai_config={
                    "enabled": True,
                    "model": "gpt-5.4",
                    "prompt_template": "research_os_critic_family_verdict_v1",
                    "responses_api": "https://api.openai.com/v1/responses",
                },
                critic_config={
                    "controlled_comparison": {
                        "enabled": True,
                        "constrained_influence_v2": {
                            "enabled": True,
                        },
                    }
                },
            )

        controlled = verdict.evidence["controlled_retrieval_comparison"]
        candidate = controlled["observations"]["candidate"]
        diff = controlled["observations"]["diff"]
        self.assertTrue(controlled["constrained_influence"]["enabled"])
        self.assertTrue(candidate["enforcement"]["blocked_fields_frozen"])
        self.assertTrue(candidate["enforcement"]["forbidden_field_change_attempted"])
        self.assertEqual(candidate["note_fields"]["recommended_verdict"], "pause")
        self.assertEqual(candidate["note_fields"]["recommended_next_action"], "pause_family")
        self.assertEqual(candidate["raw_note_fields"]["recommended_verdict"], "continue")
        self.assertEqual(candidate["raw_note_fields"]["recommended_next_action"], "continue_family")
        self.assertEqual(diff["changed_fields"], ["policy_alignment_note", "recommended_reason"])
        self.assertTrue(diff["forbidden_field_change_attempted"])
        self.assertEqual(
            diff["forbidden_fields_changed"],
            ["recommended_next_action", "recommended_verdict"],
        )
        self.assertEqual(invoke_mock.call_count, 2)
        candidate_packet = invoke_mock.call_args_list[1].kwargs["user_payload"]["optional_input_artifacts"]["retrieval_packet"]
        self.assertEqual(controlled["candidate_prompt_mode"], "compact")
        self.assertEqual(candidate_packet["retrieval_prompt_mode"], "compact")
        self.assertEqual(candidate_packet["top_k"], 1)
        self.assertEqual(
            candidate_packet["latest_memory_id"],
            "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
        )
        self.assertIn("latest_verdict", candidate_packet)
        self.assertIn("latest_action", candidate_packet)
        self.assertNotIn("payload", candidate_packet)
        self.assertNotIn("path", candidate_packet)
        self.assertLess(
            controlled["retrieval_prompt_observability"]["token_delta_impact"]["compact_vs_full"]["estimated_input_tokens_char_div4_delta"],
            0,
        )
        self.assertIn("retrieval_influence_contract", invoke_mock.call_args_list[1].kwargs["user_payload"])

    def test_build_mutation_proposal_artifact_carries_optional_retrieval_packet(self):
        job = WorkerJob(
            schema_version=SCHEMA_VERSION,
            job_id="planner_retrieval_packet_job",
            job_type=JOB_TYPE_PROPOSE_NEXT_MUTATION,
            family_id="cost_aware_hysteretic_pilot_to_full",
            priority=1,
            payload={
                "planner_request_id": "planner_retrieval_packet_request",
                "mutation_proposal": planner_service.build_mutation_proposal(
                    request_id="planner_retrieval_packet_request",
                    family_id="cost_aware_hysteretic_pilot_to_full",
                    family_state=build_environment_scan()["family_state_snapshot"]["payload"]["families"][0],
                    market_state_snapshot=build_environment_scan()["market_state_snapshot"]["payload"],
                ).to_dict(),
                "family_state_snapshot": build_environment_scan()["family_state_snapshot"]["payload"],
                "family_state_snapshot_path": "family_state.json",
                "market_state_snapshot": build_environment_scan()["market_state_snapshot"]["payload"],
                "market_state_snapshot_path": "market_state.json",
                "optional_input_artifacts": {
                    "retrieval_packet": {
                        "status": "loaded",
                        "family_id": "cost_aware_hysteretic_pilot_to_full",
                        "summary": {
                            "latest_memory_id": "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
                        },
                    }
                },
            },
            artifact_root="outputs/research_os/dev_only/test_openai_runtime_artifacts",
            created_at=utc_now_iso(),
            constraints={
                "dev_only": True,
                "non_authoritative": True,
                "live_trading": False,
                "source_of_truth_mutation": False,
                "official_promotion_logic": False,
            },
        )

        artifact = worker_service.build_mutation_proposal_artifact(job)

        self.assertIn("optional_input_artifacts", artifact)
        self.assertEqual(
            artifact["optional_input_artifacts"]["retrieval_packet"]["summary"]["latest_memory_id"],
            "trendatlas.crypto.decision_episode.openai_token_opt_rerun.cost_aware_hysteretic_pilot_to_full",
        )


if __name__ == "__main__":
    unittest.main()
