from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from services.shared.openai_responses import describe_openai_operation, invoke_structured_response, serialize_openai_error
from services.shared.runtime_bootstrap import load_runtime_config as load_runtime_config_shared
from services.shared.artifact_writer import ArtifactWriter
from services.shared.schemas import (
    CRITIC_STATUS_COMPLETED,
    FAMILY_LIFECYCLE_ACTIVE,
    FAMILY_LIFECYCLE_PAUSED,
    FAMILY_LIFECYCLE_STOPPED,
    FAMILY_NEXT_ACTION_CONTINUE,
    FAMILY_NEXT_ACTION_PAUSE,
    FAMILY_NEXT_ACTION_STOP,
    FAMILY_VERDICT_CONTINUE,
    FAMILY_VERDICT_PAUSE,
    FAMILY_VERDICT_STOP,
    GOVERNOR_STATUS_COMPLETED,
    GOVERNOR_STATUS_FAILED,
    GOVERNOR_STATUS_STARTED,
    FamilyRegistry,
    FamilyGovernorState,
    FamilyVerdict,
    MutationProposal,
    PlannerInput,
    PlannerOutput,
    RuntimeConfig,
    SCHEMA_VERSION,
    WorkerJob,
    JOB_TYPE_PROPOSE_NEXT_MUTATION,
    utc_now_iso,
)
from services.pi.registry_service import RegistryService


def load_family_registry(path: str | Path) -> FamilyRegistry:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return FamilyRegistry.from_mapping(payload)


def build_planner_input(request_id: str, family_registry: FamilyRegistry, environment_scan: dict[str, Any]) -> PlannerInput:
    return PlannerInput(
        schema_version=SCHEMA_VERSION,
        request_id=request_id,
        family_registry=family_registry.to_dict(),
        environment_scan=environment_scan,
        constraints={
            "mode": "dev_only_research_os",
            "live_trading": False,
            "source_of_truth_mutation": False,
        },
    )


def _snapshot_family(family_state_snapshot: dict[str, Any], family_id: str) -> dict[str, Any]:
    families = list(family_state_snapshot.get("families", []))
    return next((dict(family) for family in families if family.get("family_id") == family_id), {})


def _last_attempt(family_state: dict[str, Any]) -> dict[str, Any]:
    lineage = list(family_state.get("lineage", []))
    return dict(lineage[-1]) if lineage else {}


def _previous_attempt(family_state: dict[str, Any]) -> dict[str, Any]:
    lineage = list(family_state.get("lineage", []))
    return dict(lineage[-2]) if len(lineage) >= 2 else {}


def build_mutation_proposal(
    request_id: str,
    family_id: str,
    family_state: dict[str, Any],
    market_state_snapshot: dict[str, Any],
) -> MutationProposal:
    last_attempt = _last_attempt(family_state)
    previous_attempt = _previous_attempt(family_state)
    last_metrics = dict(family_state.get("last_metrics", {}))
    previous_metrics = dict(previous_attempt.get("metrics", {}))
    proposal_id = f"{request_id}_{family_id}_mutation_proposal"
    return MutationProposal(
        schema_version=SCHEMA_VERSION,
        proposal_id=proposal_id,
        family_id=family_id,
        mechanism_hypothesis=(
            "The cost-aware CASH -> PILOT -> FULL family has positive net capture, "
            "but the recap-confirm variant triggered the stop condition by increasing "
            "switches and worsening DD; a narrower entry cap should reduce churn and DD "
            "while preserving some after-cost net benefit."
        ),
        mutation_target={
            "target_id": "state_machine.pilot_entry.recap_confirm_gate",
            "target_type": "single_rule_restriction",
            "source_artifact_id": str(last_attempt.get("artifact_id", "")),
            "exact_change": (
                "Keep the CASH/PILOT/FULL states, 0.00/0.15/1.00 weights, pilot_to_full rules, "
                "exit rules, and cost model unchanged; replace the recap-and-hold pilot_entry "
                "clause with: setup persists 2 days, fresh benchmark/pilot recapture occurs "
                "within 7 days, and at most one PILOT entry is allowed per constructive window."
            ),
            "execution_allowed": False,
            "scope": "dev_only_queue_ready_heavy_job_request_only",
        },
        expected_impact={
            "churn": {
                "direction": "decrease",
                "basis": {
                    "latest_turnover_pressure_delta": last_metrics.get("turnover_pressure_delta"),
                    "previous_turnover_pressure_delta": previous_metrics.get("turnover_pressure_delta"),
                },
                "target": "turnover_pressure_delta <= 0.0",
            },
            "switch_count": {
                "direction": "decrease",
                "basis": {
                    "latest_switch_count_delta": last_metrics.get("switch_count_delta"),
                    "previous_switch_count_delta": previous_metrics.get("switch_count_delta"),
                },
                "target": "switch_count_delta <= 4",
            },
            "dd": {
                "direction": "improve",
                "basis": {
                    "latest_max_drawdown_delta_pct": last_metrics.get("max_drawdown_delta_pct"),
                    "previous_max_drawdown_delta_pct": previous_metrics.get("max_drawdown_delta_pct"),
                },
                "target": "max_drawdown_delta_pct >= -1.0",
            },
            "net_benefit": {
                "direction": "retain_positive_after_costs",
                "basis": {
                    "latest_net_cagr_delta_pct": last_metrics.get("net_cagr_delta_pct"),
                    "previous_net_cagr_delta_pct": previous_metrics.get("net_cagr_delta_pct"),
                },
                "target": "net_cagr_delta_pct > 0.0 and net_total_return_delta_pct > 0.0",
            },
        },
        stop_condition=(
            "Reject if switch_count_delta > 4, turnover_pressure_delta > 0.0, "
            "max_drawdown_delta_pct < -1.0, net_cagr_delta_pct <= 0.0 after costs, "
            "or the mutation broadens into a parameter sweep or alternate mechanism."
        ),
        lineage_refs={
            "planner_request_id": request_id,
            "family_last_artifact_id": str(family_state.get("last_artifact_id", "")),
            "family_last_verdict": str(family_state.get("last_verdict", "")),
            "family_attempt_artifact_ids": [
                str(attempt.get("artifact_id", "")) for attempt in family_state.get("lineage", [])
            ],
            "market_snapshot_id": str(market_state_snapshot.get("snapshot_id", "")),
            "market_artifact_ids": list(market_state_snapshot.get("market_context", {}).get("artifact_ids", [])),
        },
    )


def _planner_prompt_template(prompt_template: str) -> str:
    if prompt_template == "research_os_planner_mutation_proposal_v1":
        return (
            "You are the MRV1 planner for a dev-only, non-authoritative research runtime. "
            "Produce exactly one narrow mutation proposal for the already-selected family. "
            "Do not broaden into a sweep, do not permit execution, do not reference live trading, "
            "and do not mutate any source of truth. Keep the proposal bounded to a single rule restriction."
        )
    return (
        "You are the MRV1 planner for a dev-only, non-authoritative research runtime. "
        "Return one narrow, execution-disabled mutation proposal that preserves all hard safety boundaries."
    )


def _planner_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mechanism_hypothesis": {"type": "string"},
            "selection_rationale": {"type": "string"},
            "mutation_target": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "target_id": {"type": "string"},
                    "target_type": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "exact_change": {"type": "string"},
                },
                "required": ["target_id", "target_type", "source_artifact_id", "exact_change"],
            },
            "stop_condition": {"type": "string"},
        },
        "required": [
            "mechanism_hypothesis",
            "selection_rationale",
            "mutation_target",
            "stop_condition",
        ],
    }


def _planner_user_payload(
    *,
    planner_input: PlannerInput,
    selected_family: Any,
    selected_family_state: dict[str, Any],
    market_state_payload: dict[str, Any],
    blocked_families: list[dict[str, str]],
    fallback_proposal: MutationProposal,
) -> dict[str, Any]:
    lineage = list(selected_family_state.get("lineage", []))
    return {
        "request_id": planner_input.request_id,
        "constraints": {
            "dev_only": True,
            "non_authoritative": True,
            "live_trading": False,
            "source_of_truth_mutation": False,
            "official_promotion_logic": False,
            "single_candidate_only": True,
            "execution_allowed": False,
        },
        "selected_family": {
            "family_id": selected_family.family_id,
            "description": selected_family.description,
            "default_priority": selected_family.default_priority,
            "allowed_job_types": list(selected_family.allowed_job_types),
            "constraints": dict(selected_family.constraints),
        },
        "selected_family_state": {
            "last_artifact_id": str(selected_family_state.get("last_artifact_id", "")),
            "last_verdict": str(selected_family_state.get("last_verdict", "")),
            "last_metrics": dict(selected_family_state.get("last_metrics", {})),
            "lineage_excerpt": [dict(item) for item in lineage[-2:]],
        },
        "market_state": {
            "snapshot_id": str(market_state_payload.get("snapshot_id", "")),
            "artifact_ids": list(market_state_payload.get("market_context", {}).get("artifact_ids", [])),
            "notes": list(market_state_payload.get("notes", [])),
        },
        "blocked_families": list(blocked_families),
        "fallback_proposal": fallback_proposal.to_dict(),
    }


def _build_openai_mutation_proposal(
    *,
    planner_input: PlannerInput,
    selected_family: Any,
    selected_family_state: dict[str, Any],
    market_state_payload: dict[str, Any],
    blocked_families: list[dict[str, str]],
    fallback_proposal: MutationProposal,
    openai_config: dict[str, Any],
) -> tuple[MutationProposal, dict[str, Any], str]:
    response = invoke_structured_response(
        openai_config,
        system_prompt=_planner_prompt_template(str(openai_config.get("prompt_template", ""))),
        user_payload=_planner_user_payload(
            planner_input=planner_input,
            selected_family=selected_family,
            selected_family_state=selected_family_state,
            market_state_payload=market_state_payload,
            blocked_families=blocked_families,
            fallback_proposal=fallback_proposal,
        ),
        schema_name="research_os_planner_mutation_proposal",
        schema=_planner_response_schema(),
    )
    fallback_payload = fallback_proposal.to_dict()
    model_target = dict(response.parsed["mutation_target"])
    mutation_target = {
        **dict(fallback_payload["mutation_target"]),
        "target_id": str(model_target["target_id"]),
        "target_type": str(model_target["target_type"]),
        "source_artifact_id": str(model_target["source_artifact_id"]),
        "exact_change": str(model_target["exact_change"]),
        "execution_allowed": False,
        "scope": str(fallback_payload["mutation_target"].get("scope", "dev_only_queue_ready_heavy_job_request_only")),
    }
    proposal = MutationProposal.from_mapping(
        {
            **fallback_payload,
            "mechanism_hypothesis": str(response.parsed["mechanism_hypothesis"]),
            "mutation_target": mutation_target,
            "stop_condition": str(response.parsed["stop_condition"]),
        }
    )
    hook = {
        **describe_openai_operation(openai_config),
        "network_call": "completed",
        "response_id": response.response_id,
        "response_status": response.status,
        "response_model": response.model,
        "usage": response.usage,
        "selection_rationale": str(response.parsed.get("selection_rationale", "")),
    }
    return proposal, hook, "planner_openai_response_applied"


def _write_planner_openai_error_artifact(
    *,
    artifact_root: str,
    request_id: str,
    family_id: str,
    openai_config: dict[str, Any],
    error: Exception,
    blocked_families: list[dict[str, str]],
) -> dict[str, Any]:
    writer = ArtifactWriter(artifact_root)
    error_payload = serialize_openai_error(error)
    record = writer.write_json(
        f"planner_outputs/{request_id}_planner_openai_error.json",
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "family_id": family_id,
            "component": "planner",
            "status": "failed_closed",
            "generated_at": utc_now_iso(),
            "dev_only": True,
            "non_authoritative": True,
            "official_truth": False,
            "live_trading": False,
            "source_of_truth_mutation": False,
            "official_promotion_logic": False,
            "error": error_payload,
            "openai_operation": describe_openai_operation(openai_config),
            "blocked_families": list(blocked_families),
            "notes": [
                "planner_openai_failed_closed",
                "no_downstream_job_emitted",
                "no_strategy_code_execution",
            ],
        },
        metadata={"request_id": request_id, "family_id": family_id, "component": "planner"},
    )
    return record.to_dict()


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    return load_runtime_config_shared(path)


def load_family_verdict_artifact(path: str | Path) -> FamilyVerdict:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    verdict = FamilyVerdict.from_mapping(payload)
    if verdict.status != CRITIC_STATUS_COMPLETED:
        raise ValueError("governor requires a critic_completed family verdict")
    return verdict


def _lifecycle_state_for_verdict(verdict: str) -> str:
    if verdict == FAMILY_VERDICT_CONTINUE:
        return FAMILY_LIFECYCLE_ACTIVE
    if verdict == FAMILY_VERDICT_PAUSE:
        return FAMILY_LIFECYCLE_PAUSED
    if verdict == FAMILY_VERDICT_STOP:
        return FAMILY_LIFECYCLE_STOPPED
    raise ValueError(f"unsupported family verdict: {verdict}")


def _next_action_for_lifecycle(lifecycle_state: str) -> str:
    if lifecycle_state == FAMILY_LIFECYCLE_ACTIVE:
        return FAMILY_NEXT_ACTION_CONTINUE
    if lifecycle_state == FAMILY_LIFECYCLE_PAUSED:
        return FAMILY_NEXT_ACTION_PAUSE
    if lifecycle_state == FAMILY_LIFECYCLE_STOPPED:
        return FAMILY_NEXT_ACTION_STOP
    raise ValueError(f"unsupported family lifecycle_state: {lifecycle_state}")


def _count_confirmatory_attempts(lineage: list[dict[str, Any]], mechanism_id: str) -> int:
    count = 0
    for attempt in lineage:
        labels = [
            str(attempt.get("artifact_id", "")),
            str(attempt.get("mechanism_id", "")),
            str(attempt.get("verdict", "")),
        ]
        if any("confirm" in label.lower() for label in labels):
            count += 1
    if count == 0 and "confirm" in mechanism_id.lower():
        return 1
    return count


def build_family_governor_state(
    verdict: FamilyVerdict,
    registry: RegistryService,
    job_id: str,
    source_verdict_artifact_path: str,
) -> FamilyGovernorState:
    family_state = registry.get_family_state(verdict.family_id) or {}
    lineage = json.loads(str(family_state.get("lineage_json", "[]"))) if family_state else []
    if not isinstance(lineage, list):
        lineage = []
    attempt_count = int(family_state.get("attempt_count", len(lineage)) or len(lineage))
    lifecycle_state = _lifecycle_state_for_verdict(verdict.verdict)
    last_next_action = _next_action_for_lifecycle(lifecycle_state)
    last_updated_at = utc_now_iso()
    state = FamilyGovernorState(
        schema_version=SCHEMA_VERSION,
        state_id=f"{job_id}_family_governor_state",
        job_id=job_id,
        verdict_id=verdict.verdict_id,
        family_id=verdict.family_id,
        mechanism_id=verdict.mechanism_id,
        lifecycle_state=lifecycle_state,
        status=GOVERNOR_STATUS_COMPLETED,
        attempt_count=attempt_count,
        confirmatory_count=_count_confirmatory_attempts([dict(item) for item in lineage], verdict.mechanism_id),
        last_verdict=verdict.verdict,
        last_next_action=last_next_action,
        last_updated_at=last_updated_at,
        source_verdict_artifact_path=str(Path(source_verdict_artifact_path).resolve()),
        planning_eligible=lifecycle_state == FAMILY_LIFECYCLE_ACTIVE,
        governance={
            "dev_only": True,
            "non_authoritative": True,
            "official_truth": False,
            "strategy_advancement": False,
            "source_of_truth_mutation": False,
            "live_trading": False,
            "official_promotion_logic": False,
            "planner_blocked_without_override": lifecycle_state in {FAMILY_LIFECYCLE_PAUSED, FAMILY_LIFECYCLE_STOPPED},
        },
    )
    return FamilyGovernorState.from_mapping(state.to_dict())


def execute_family_governor(
    verdict_artifact_path: str | Path,
    artifact_root: str | Path,
    registry: RegistryService,
    governor_job_id: str = "",
) -> dict[str, Any]:
    started_at = utc_now_iso()
    job_id = governor_job_id or "unknown_governor_job"
    state_id = f"{job_id}_family_governor_state"
    verdict_id = "unknown_verdict"
    family_id = "unknown_family"
    try:
        verdict = load_family_verdict_artifact(verdict_artifact_path)
        job_id = governor_job_id or f"{verdict.job_id}_governor"
        state_id = f"{job_id}_family_governor_state"
        verdict_id = verdict.verdict_id
        family_id = verdict.family_id
        registry.record_family_governor_event(
            state_id=state_id,
            job_id=job_id,
            verdict_id=verdict_id,
            family_id=family_id,
            event_type=GOVERNOR_STATUS_STARTED,
            event={
                "status": GOVERNOR_STATUS_STARTED,
                "state_id": state_id,
                "job_id": job_id,
                "verdict_id": verdict_id,
                "family_id": family_id,
                "verdict_artifact_path": str(Path(verdict_artifact_path).resolve()),
                "dev_only": True,
                "non_authoritative": True,
                "official_truth": False,
                "strategy_advancement": False,
            },
        )
        state = build_family_governor_state(
            verdict=verdict,
            registry=registry,
            job_id=job_id,
            source_verdict_artifact_path=str(verdict_artifact_path),
        )
        writer = ArtifactWriter(artifact_root)
        state_record = writer.write_json(
            f"governor_outputs/{job_id}_family_governor_state.json",
            state.to_dict(),
            metadata={
                "job_id": job_id,
                "verdict_id": verdict.verdict_id,
                "family_id": verdict.family_id,
                "lifecycle_state": state.lifecycle_state,
            },
        )
        registry.record_family_governor_state(state=state, artifact_path=state_record.path)
        registry.record_artifact(job_id, state_record.to_dict())
        return {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "status": GOVERNOR_STATUS_COMPLETED,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "artifact_refs": [state_record.to_dict()],
            "family_governor_state": state.to_dict(),
            "notes": [
                "dev_only_family_lifecycle_registry_update",
                "planner_eligibility_updated_without_source_of_truth_mutation",
                "no_live_trading_logic",
            ],
            "error": "",
        }
    except Exception as exc:
        registry.record_family_governor_event(
            state_id=state_id,
            job_id=job_id,
            verdict_id=verdict_id,
            family_id=family_id,
            event_type=GOVERNOR_STATUS_FAILED,
            event={
                "status": GOVERNOR_STATUS_FAILED,
                "state_id": state_id,
                "job_id": job_id,
                "verdict_id": verdict_id,
                "family_id": family_id,
                "verdict_artifact_path": str(Path(verdict_artifact_path).resolve()),
                "error": str(exc),
                "dev_only": True,
                "non_authoritative": True,
                "official_truth": False,
                "strategy_advancement": False,
            },
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "status": GOVERNOR_STATUS_FAILED,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "artifact_refs": [],
            "notes": ["dev_only_family_lifecycle_registry_update_failed"],
            "error": str(exc),
        }


def _load_governor_state_by_family(artifact_root: str) -> dict[str, dict[str, Any]]:
    registry_path = Path(artifact_root).resolve().parent / "registry" / "research_os_mvp.sqlite"
    if not registry_path.exists():
        return {}
    registry = RegistryService(registry_path)
    return {str(row["family_id"]): dict(row) for row in registry.list_family_governor_states(limit=1000)}


def _planning_lifecycle_state(raw_state: dict[str, Any]) -> str:
    if not raw_state:
        return FAMILY_LIFECYCLE_ACTIVE
    if "lifecycle_state" in raw_state:
        return str(raw_state["lifecycle_state"])
    state_json = raw_state.get("state_json")
    if state_json:
        parsed = json.loads(str(state_json))
        if isinstance(parsed, dict):
            return str(parsed.get("lifecycle_state", FAMILY_LIFECYCLE_ACTIVE))
    return FAMILY_LIFECYCLE_ACTIVE


def plan_jobs(
    planner_input: PlannerInput,
    artifact_root: str,
    openai_config: dict[str, Any],
    planner_config: dict[str, Any] | None = None,
    governor_config: dict[str, Any] | None = None,
    governor_state_by_family: dict[str, dict[str, Any]] | None = None,
) -> PlannerOutput:
    registry = FamilyRegistry.from_mapping(planner_input.family_registry)
    planner_config = dict(planner_config or {})
    planner_enabled = bool(planner_config.get("enabled", True))
    openai_config = dict(planner_config.get("openai") or openai_config)
    openai_hook = {
        **describe_openai_operation(openai_config),
        "planner_enabled": planner_enabled,
        "failure_closed": False,
    }
    governor_config = dict(governor_config or {})
    allow_governor_override = bool(governor_config.get("allow_paused_stopped_family_planning_override", False))
    governor_state_by_family = (
        dict(governor_state_by_family)
        if governor_state_by_family is not None
        else _load_governor_state_by_family(artifact_root)
    )
    blocked_families: list[dict[str, str]] = []
    enabled_families = [
        family
        for family in registry.families
        if family.status == "enabled" and JOB_TYPE_PROPOSE_NEXT_MUTATION in family.allowed_job_types
    ]
    eligible_families = []
    for family in enabled_families:
        lifecycle_state = _planning_lifecycle_state(governor_state_by_family.get(family.family_id, {}))
        if lifecycle_state in {FAMILY_LIFECYCLE_PAUSED, FAMILY_LIFECYCLE_STOPPED} and not allow_governor_override:
            blocked_families.append({"family_id": family.family_id, "lifecycle_state": lifecycle_state})
            continue
        eligible_families.append(family)
    selected_family = sorted(eligible_families, key=lambda family: family.default_priority)[0] if eligible_families else None
    jobs: list[dict[str, Any]] = []
    family_state_snapshot = planner_input.environment_scan.get("family_state_snapshot", {})
    market_state_snapshot = planner_input.environment_scan.get("market_state_snapshot", {})
    openai_note = f"planner_openai_{openai_hook['network_call']}"
    if not planner_enabled:
        return PlannerOutput(
            schema_version=SCHEMA_VERSION,
            planner_id="pi_planner_service",
            created_at=utc_now_iso(),
            request_id=planner_input.request_id,
            jobs=[],
            notes=[
                "planner_disabled_by_config",
                "no_strategy_code_execution",
                "no_live_trading_logic",
            ],
            openai_hook=openai_hook,
        )
    if selected_family:
        family_state_payload = dict(family_state_snapshot.get("payload", {}))
        market_state_payload = dict(market_state_snapshot.get("payload", {}))
        selected_family_state = _snapshot_family(family_state_payload, selected_family.family_id)
        if not selected_family_state:
            raise ValueError(f"family_id not found in planner family state snapshot: {selected_family.family_id}")
        proposal = build_mutation_proposal(
            request_id=planner_input.request_id,
            family_id=selected_family.family_id,
            family_state=selected_family_state,
            market_state_snapshot=market_state_payload,
        )
        if bool(openai_config.get("enabled", False)):
            try:
                proposal, openai_hook, openai_note = _build_openai_mutation_proposal(
                    planner_input=planner_input,
                    selected_family=selected_family,
                    selected_family_state=selected_family_state,
                    market_state_payload=market_state_payload,
                    blocked_families=blocked_families,
                    fallback_proposal=proposal,
                    openai_config=openai_config,
                )
            except Exception as exc:
                error_record = _write_planner_openai_error_artifact(
                    artifact_root=artifact_root,
                    request_id=planner_input.request_id,
                    family_id=selected_family.family_id,
                    openai_config=openai_config,
                    error=exc,
                    blocked_families=blocked_families,
                )
                openai_hook = {
                    **describe_openai_operation(openai_config),
                    **serialize_openai_error(exc),
                    "planner_enabled": planner_enabled,
                    "network_call": "failed_closed",
                    "failure_closed": True,
                    "error_artifact": error_record,
                }
                return PlannerOutput(
                    schema_version=SCHEMA_VERSION,
                    planner_id="pi_planner_service",
                    created_at=utc_now_iso(),
                    request_id=planner_input.request_id,
                    jobs=[],
                    notes=[
                        "planner_openai_failed_closed",
                        "no_downstream_job_emitted",
                        "no_strategy_code_execution",
                    ],
                    openai_hook=openai_hook,
                )
        job = WorkerJob(
            schema_version=SCHEMA_VERSION,
            job_id=f"{planner_input.request_id}_{selected_family.family_id}_{JOB_TYPE_PROPOSE_NEXT_MUTATION}",
            job_type=JOB_TYPE_PROPOSE_NEXT_MUTATION,
            family_id=selected_family.family_id,
            priority=selected_family.default_priority,
            payload={
                "planner_request_id": planner_input.request_id,
                "description": selected_family.description,
                "safe_mutation_planning": True,
                "strategy_logic": "not_executed",
                "mutation_proposal": proposal.to_dict(),
                "family_state_snapshot_path": family_state_snapshot.get("path", ""),
                "family_state_snapshot": family_state_snapshot.get("payload", {}),
                "market_state_snapshot_path": market_state_snapshot.get("path", ""),
                "market_state_snapshot": market_state_snapshot.get("payload", {}),
            },
            artifact_root=artifact_root,
            created_at=utc_now_iso(),
            constraints={
                **selected_family.constraints,
                "dev_only": True,
                "non_authoritative": True,
                "live_trading": False,
                "source_of_truth_mutation": False,
                "official_promotion_logic": False,
                "strategy_mutation_execution": False,
                "queue_ready_request_only": True,
            },
        )
        jobs.append(job.to_dict())
    return PlannerOutput(
        schema_version=SCHEMA_VERSION,
        planner_id="pi_planner_service",
        created_at=utc_now_iso(),
        request_id=planner_input.request_id,
        jobs=jobs,
        notes=[
            "single_mutation_proposal_plan",
            openai_note,
            "job_type_propose_next_mutation_only",
            "no_strategy_code_execution",
            "planner_governor_override_enabled" if allow_governor_override else "planner_governor_override_disabled",
            f"governor_blocked_families={json.dumps(blocked_families, sort_keys=True)}",
        ],
        openai_hook=openai_hook,
    )


def load_family_state_snapshot(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pi planner service skeleton")
    parser.add_argument("--config", default="configs/runtime/runtime_config.template.json")
    parser.add_argument("--family-registry", default="configs/families/family_registry.template.json")
    parser.add_argument("--environment-scan", default="")
    parser.add_argument("--family-state-snapshot", default="")
    parser.add_argument("--artifact-root", default="outputs/research_os/dev_only/mvp/artifacts")
    parser.add_argument("--request-id", default="manual_smoke")
    parser.add_argument("--write-output", action="store_true")
    parser.add_argument("--governor-verdict-artifact", help="Apply one critic family verdict to the governor registry.")
    parser.add_argument("--governor-job-id", default="", help="Optional job id for --governor-verdict-artifact.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    artifact_root = args.artifact_root
    if artifact_root == "outputs/research_os/dev_only/mvp/artifacts":
        artifact_root = config.artifact_root
    registry_service = RegistryService(config.registry_path)
    if args.governor_verdict_artifact:
        result = execute_family_governor(
            verdict_artifact_path=args.governor_verdict_artifact,
            artifact_root=artifact_root,
            registry=registry_service,
            governor_job_id=args.governor_job_id,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == GOVERNOR_STATUS_COMPLETED else 1
    registry = load_family_registry(args.family_registry)
    if not args.environment_scan:
        raise SystemExit("Choose --governor-verdict-artifact or provide --environment-scan.")
    scan = json.loads(Path(args.environment_scan).read_text(encoding="utf-8"))
    if args.family_state_snapshot:
        scan["family_state_snapshot"] = {
            "path": str(Path(args.family_state_snapshot).resolve()),
            "payload": load_family_state_snapshot(args.family_state_snapshot),
        }
    planner_input = build_planner_input(args.request_id, registry, scan)
    output = plan_jobs(
        planner_input=planner_input,
        artifact_root=artifact_root,
        openai_config=config.openai,
        planner_config=config.planner,
        governor_config=config.governor,
    )
    if args.write_output:
        record = ArtifactWriter(artifact_root).write_json(
            f"planner_outputs/{args.request_id}_planner_output.json",
            output.to_dict(),
        )
        print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
        return 1 if output.openai_hook.get("failure_closed", False) else 0
    print(json.dumps(output.to_dict(), indent=2, sort_keys=True))
    return 1 if output.openai_hook.get("failure_closed", False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
