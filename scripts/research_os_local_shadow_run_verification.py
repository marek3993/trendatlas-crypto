from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.pc import worker_service
from services.pi import planner_service
from services.shared.openai_responses import StructuredResponseResult
from services.shared.schemas import FamilyRegistry, MutationProposal


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "artifacts" / "trendatlas_shadow_run_verification_demo"
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "configs" / "families" / "family_registry.template.json"
DEFAULT_PLANNER_INPUT_ROOT = PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "mvp" / "artifacts" / "planner_inputs"
DEFAULT_HEAVY_VALIDATION_ROOT = PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "mvp" / "artifacts" / "heavy_validation_outputs"
DEFAULT_GOVERNOR_ROOT = PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "mvp" / "artifacts" / "governor_outputs"
DEFAULT_RETRIEVAL_ROOT = PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "imlayer_retrieval"
DEFAULT_SHADOW_EXECUTION_MODE = "mock"
REAL_OPENAI_SHADOW_EXECUTION_MODE = "real_openai"
SHADOW_MODE_ENV_VAR = "TRENDATLAS_SHADOW_MODE"
USE_REAL_OPENAI_ENV_VAR = "TRENDATLAS_SHADOW_USE_REAL_OPENAI"


class VerificationFailure(RuntimeError):
    pass


def _parse_env_bool(raw_value: str) -> bool:
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _load_mode_config(mode_config_path: str | None) -> dict[str, Any]:
    if not mode_config_path:
        return {}
    path = Path(mode_config_path)
    path = path if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise VerificationFailure(f"mode config must be a JSON object: {path}")
    return dict(payload)


def normalize_shadow_execution_mode(raw_mode: str) -> str:
    normalized = raw_mode.strip().lower().replace("-", "_")
    if normalized in {"", DEFAULT_SHADOW_EXECUTION_MODE}:
        return DEFAULT_SHADOW_EXECUTION_MODE
    if normalized in {REAL_OPENAI_SHADOW_EXECUTION_MODE, "real"}:
        return REAL_OPENAI_SHADOW_EXECUTION_MODE
    raise VerificationFailure(f"Unsupported shadow execution mode: {raw_mode!r}")


def resolve_shadow_execution_mode(
    *,
    use_real_openai: bool = False,
    mode_config_path: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    if use_real_openai:
        return REAL_OPENAI_SHADOW_EXECUTION_MODE
    mode_config = _load_mode_config(mode_config_path)
    env_map = env or os.environ
    for candidate in (
        str(mode_config.get("shadow_mode", "")),
        str(env_map.get(SHADOW_MODE_ENV_VAR, "")),
    ):
        if candidate.strip():
            return normalize_shadow_execution_mode(candidate)
    if bool(mode_config.get("use_real_openai", False)):
        return REAL_OPENAI_SHADOW_EXECUTION_MODE
    if _parse_env_bool(str(env_map.get(USE_REAL_OPENAI_ENV_VAR, ""))):
        return REAL_OPENAI_SHADOW_EXECUTION_MODE
    return DEFAULT_SHADOW_EXECUTION_MODE


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def newest_file(root: Path, pattern: str) -> Path:
    candidates = [path for path in root.glob(pattern) if path.is_file()]
    if not candidates:
        raise VerificationFailure(f"No files matched {pattern!r} under {root}")
    return max(candidates, key=lambda path: (path.stat().st_mtime, str(path)))


def resolve_retrieval_packet_path(explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    return newest_file(DEFAULT_RETRIEVAL_ROOT, "**/*.latest.retrieval_packet.json")


def resolve_planner_input_path(explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    return newest_file(DEFAULT_PLANNER_INPUT_ROOT, "*_planner_input.json")


def resolve_heavy_validation_summary_path(family_id: str, explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    return newest_file(DEFAULT_HEAVY_VALIDATION_ROOT, f"*{family_id}*_summary.json")


def resolve_latest_governor_artifact_path(family_id: str) -> Path | None:
    candidates = [path for path in DEFAULT_GOVERNOR_ROOT.glob(f"*{family_id}*_family_governor_state.json") if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, str(path)))


def load_filtered_registry(path: Path, family_id: str) -> FamilyRegistry:
    registry = planner_service.load_family_registry(path)
    filtered = [family.to_dict() for family in registry.families if family.family_id == family_id]
    if len(filtered) != 1:
        raise VerificationFailure(f"Expected exactly one registry family match for {family_id!r}, found {len(filtered)}")
    return FamilyRegistry.from_mapping(
        {
            "schema_version": registry.schema_version,
            "registry_id": registry.registry_id,
            "owner": registry.owner,
            "constraints": dict(registry.constraints),
            "families": filtered,
        }
    )


def resolve_family_state(environment_scan: dict[str, Any], family_id: str) -> dict[str, Any]:
    snapshot = dict(environment_scan.get("family_state_snapshot", {}))
    payload = dict(snapshot.get("payload", {}))
    families = list(payload.get("families", []))
    for family in families:
        candidate = dict(family)
        if str(candidate.get("family_id", "")) == family_id:
            return candidate
    raise VerificationFailure(f"family_state_snapshot does not contain family_id={family_id!r}")


def sanitize_planner_input_payload(payload: dict[str, Any], family_id: str) -> dict[str, Any]:
    cleaned = deepcopy(payload)
    env_scan = dict(cleaned.get("environment_scan", {}))
    family_snapshot = dict(env_scan.get("family_state_snapshot", {}))
    family_payload = dict(family_snapshot.get("payload", {}))
    family_payload["families"] = [
        dict(item)
        for item in list(family_payload.get("families", []))
        if str(dict(item).get("family_id", "")) == family_id
    ]
    family_snapshot["payload"] = family_payload
    env_scan["family_state_snapshot"] = family_snapshot
    cleaned["environment_scan"] = env_scan
    return cleaned


def build_planner_mock_response(
    *,
    proposal: MutationProposal,
    response_id: str,
    mechanism_hypothesis: str,
    selection_rationale: str,
    exact_change: str,
    usage: dict[str, Any],
) -> StructuredResponseResult:
    return StructuredResponseResult(
        response_id=response_id,
        model="gpt-5.4-local-shadow-verifier",
        status="completed",
        parsed={
            "mechanism_hypothesis": mechanism_hypothesis,
            "selection_rationale": selection_rationale,
            "mutation_target": {
                "target_id": str(proposal.mutation_target.get("target_id", "")),
                "target_type": str(proposal.mutation_target.get("target_type", "")),
                "source_artifact_id": str(proposal.mutation_target.get("source_artifact_id", "")),
                "exact_change": exact_change,
            },
            "stop_condition": proposal.stop_condition,
        },
        output_text="{}",
        usage=usage,
    )


def build_critic_mock_response(
    *,
    deterministic: dict[str, Any],
    response_id: str,
    recommended_reason: str,
    policy_alignment_note: str,
    usage: dict[str, Any],
) -> StructuredResponseResult:
    return StructuredResponseResult(
        response_id=response_id,
        model="gpt-5.4-local-shadow-verifier",
        status="completed",
        parsed={
            "recommended_verdict": str(deterministic["verdict"]),
            "recommended_next_action": str(deterministic["next_action"]),
            "recommended_reason": recommended_reason,
            "guardrail_breaches": list(deterministic["breaches"]),
            "policy_alignment_note": policy_alignment_note,
        },
        output_text="{}",
        usage=usage,
    )


def assert_planner_invariants(output: Any) -> None:
    openai_hook = dict(output.openai_hook)
    if bool(openai_hook.get("failure_closed", False)):
        error_code = str(openai_hook.get("error_code", "unexpected_openai_error"))
        error_message = str(openai_hook.get("error_message", "planner authoritative OpenAI failed closed"))
        raise VerificationFailure(f"planner authoritative OpenAI failed closed: {error_code}: {error_message}")
    controlled = dict(openai_hook.get("controlled_retrieval_comparison", {}))
    passive = dict(openai_hook.get("passive_retrieval_comparison", {}))
    if not controlled.get("explicitly_enabled", False):
        raise VerificationFailure("planner controlled retrieval comparison was not explicitly enabled")
    if controlled.get("decision_behavior_changed", True):
        raise VerificationFailure("planner controlled retrieval comparison changed authoritative decision behavior")
    if not controlled.get("fail_closed_preserved", False):
        raise VerificationFailure("planner controlled retrieval comparison did not preserve fail-closed behavior")
    if passive.get("comparison_bucket") != "with_retrieval_packet":
        raise VerificationFailure("planner passive retrieval comparison did not load a retrieval packet")
    candidate = dict(dict(controlled.get("observations", {})).get("candidate", {}))
    if candidate.get("status") != "completed":
        raise VerificationFailure(
            "planner shadow candidate did not complete"
            f": status={candidate.get('status', '')} error={candidate.get('error', '')}"
        )
    diff = dict(dict(controlled.get("observations", {})).get("diff", {}))
    if not diff.get("proposal_content_fields_preserved", False):
        raise VerificationFailure(
            "planner shadow candidate changed proposal content fields"
            f": changed={list(diff.get('proposal_content_fields_changed', []))}"
        )


def assert_critic_invariants(verdict: Any) -> None:
    evidence = dict(verdict.evidence)
    controlled = dict(evidence.get("controlled_retrieval_comparison", {}))
    passive = dict(evidence.get("passive_retrieval_comparison", {}))
    if not controlled.get("explicitly_enabled", False):
        raise VerificationFailure("critic controlled retrieval comparison was not explicitly enabled")
    if controlled.get("decision_behavior_changed", True):
        raise VerificationFailure("critic controlled retrieval comparison changed authoritative verdict behavior")
    if not controlled.get("fail_closed_preserved", False):
        raise VerificationFailure("critic controlled retrieval comparison did not preserve fail-closed behavior")
    if passive.get("comparison_bucket") != "with_retrieval_packet":
        raise VerificationFailure("critic passive retrieval comparison did not load a retrieval packet")
    candidate = dict(dict(controlled.get("observations", {})).get("candidate", {}))
    if candidate.get("status") != "completed":
        raise VerificationFailure(
            "critic shadow candidate did not complete"
            f": status={candidate.get('status', '')} error={candidate.get('error', '')}"
        )


def summarize_planner(output: Any) -> dict[str, Any]:
    job = dict(output.jobs[0])
    payload = dict(job.get("payload", {}))
    proposal = dict(payload.get("mutation_proposal", {}))
    runtime_debug = dict(payload.get("runtime_debug", {}))
    retrieval_packet = compact_retrieval_packet(dict(dict(payload.get("optional_input_artifacts", {})).get("retrieval_packet", {})))
    return {
        "job_id": str(job.get("job_id", "")),
        "family_id": str(job.get("family_id", "")),
        "authoritative_mutation_target": dict(proposal.get("mutation_target", {})),
        "authoritative_stop_condition": str(proposal.get("stop_condition", "")),
        "notes": list(output.notes),
        "openai_hook": dict(output.openai_hook),
        "passive_retrieval_comparison": dict(runtime_debug.get("passive_retrieval_comparison", {})),
        "controlled_retrieval_comparison": dict(runtime_debug.get("controlled_retrieval_comparison", {})),
        "retrieval_packet": retrieval_packet,
    }


def summarize_critic(verdict: Any) -> dict[str, Any]:
    evidence = dict(verdict.evidence)
    return {
        "job_id": verdict.job_id,
        "family_id": verdict.family_id,
        "verdict": verdict.verdict,
        "next_action": verdict.next_action,
        "verdict_reason": verdict.verdict_reason,
        "guardrail_breaches": list(evidence.get("guardrail_breaches", [])),
        "passive_retrieval_comparison": dict(evidence.get("passive_retrieval_comparison", {})),
        "controlled_retrieval_comparison": dict(evidence.get("controlled_retrieval_comparison", {})),
        "openai_review": dict(evidence.get("openai_review", {})),
        "retrieval_packet": compact_retrieval_packet(dict(dict(evidence.get("optional_input_artifacts", {})).get("retrieval_packet", {}))),
    }


def compact_retrieval_packet(packet: dict[str, Any]) -> dict[str, Any]:
    summary = dict(packet.get("summary", {}))
    return {
        "artifact_type": str(packet.get("artifact_type", "")),
        "family_id": str(packet.get("family_id", "")),
        "status": str(packet.get("status", "")),
        "path": str(packet.get("path", "")),
        "schema_version": str(packet.get("schema_version", "")),
        "retrieval_generated_at_utc": str(packet.get("retrieval_generated_at_utc", "")),
        "load_error": str(packet.get("load_error", "")),
        "summary": {
            "resolved_batch_id": str(summary.get("resolved_batch_id", "")),
            "memory_query_target": str(summary.get("memory_query_target", "")),
            "latest_memory_id": str(summary.get("latest_memory_id", "")),
            "latest_cycle_id": str(summary.get("latest_cycle_id", "")),
            "latest_verdict": str(summary.get("latest_verdict", "")),
            "latest_action": str(summary.get("latest_action", "")),
            "selected_count": int(summary.get("selected_count", 0) or 0),
            "semantic_sha256": str(summary.get("semantic_sha256", "")),
        },
    }


@contextmanager
def temporary_openai_api_key() -> Iterator[None]:
    previous = os.environ.get("OPENAI_API_KEY")
    if not previous:
        os.environ["OPENAI_API_KEY"] = "local-shadow-verification-token"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OPENAI_API_KEY", None)


def build_markdown_report(summary: dict[str, Any]) -> str:
    planner = dict(summary["planner"])
    critic = dict(summary["critic"])
    planner_controlled = dict(planner["controlled_retrieval_comparison"])
    critic_controlled = dict(critic["controlled_retrieval_comparison"])
    planner_candidate = dict(dict(planner_controlled.get("observations", {})).get("candidate", {}))
    critic_candidate = dict(dict(critic_controlled.get("observations", {})).get("candidate", {}))
    planner_diff = dict(dict(planner_controlled.get("observations", {})).get("diff", {}))
    critic_diff = dict(dict(critic_controlled.get("observations", {})).get("diff", {}))
    retrieval_packet = dict(summary["inputs"]["retrieval_packet"])
    governor_reference = dict(summary["governor_reference"])
    return f"""# TrendAtlas Local Shadow-Run Verification

- Verified at: `{summary["verified_at_utc"]}`
- Family: `{summary["family_id"]}`
- Execution mode: `{summary.get("execution_mode", DEFAULT_SHADOW_EXECUTION_MODE)}`
- Final status: `{summary["final_status"]}`
- Retrieval packet: `{retrieval_packet["path"]}`
- Retrieval memory id: `{retrieval_packet["latest_memory_id"]}`
- Retrieval semantic sha256: `{retrieval_packet["semantic_sha256"]}`

## Planner

- Passive comparison bucket: `{planner["passive_retrieval_comparison"]["comparison_bucket"]}`
- Controlled enabled: `{planner_controlled["explicitly_enabled"]}`
- Candidate status: `{planner_candidate["status"]}`
- Fail-closed preserved: `{planner_controlled["fail_closed_preserved"]}`
- Authoritative mutation target: `{planner["authoritative_mutation_target"].get("target_id", "")}`
- Changed note fields: `{", ".join(planner_diff.get("changed_fields", [])) or "none"}`

## Critic

- Passive comparison bucket: `{critic["passive_retrieval_comparison"]["comparison_bucket"]}`
- Controlled enabled: `{critic_controlled["explicitly_enabled"]}`
- Candidate status: `{critic_candidate["status"]}`
- Fail-closed preserved: `{critic_controlled["fail_closed_preserved"]}`
- Authoritative verdict: `{critic["verdict"]}`
- Authoritative next action: `{critic["next_action"]}`
- Changed note fields: `{", ".join(critic_diff.get("changed_fields", [])) or "none"}`

## Governor

- Invoked by verifier: `{governor_reference["invoked"]}`
- Unchanged by verifier: `{governor_reference["unchanged_by_verification"]}`
- Latest existing governor artifact: `{governor_reference["latest_existing_artifact_path"]}`
"""


def evaluate_verification_case(
    *,
    retrieval_packet_path: str | None,
    planner_input_path: str | None,
    heavy_validation_summary_path: str | None,
    execution_mode: str = DEFAULT_SHADOW_EXECUTION_MODE,
) -> dict[str, Any]:
    execution_mode = normalize_shadow_execution_mode(execution_mode)
    resolved_retrieval_packet_path = resolve_retrieval_packet_path(retrieval_packet_path)
    retrieval_payload = read_json(resolved_retrieval_packet_path)
    family_id = str(dict(retrieval_payload.get("query", {})).get("family_id", "")).strip()
    if not family_id:
        raise VerificationFailure("retrieval packet query.family_id is required")

    resolved_planner_input_path = resolve_planner_input_path(planner_input_path)
    planner_input_payload = sanitize_planner_input_payload(read_json(resolved_planner_input_path), family_id)
    environment_scan = dict(planner_input_payload.get("environment_scan", {}))
    registry = load_filtered_registry(DEFAULT_REGISTRY_PATH, family_id)
    selected_family = registry.families[0]
    selected_family_state = resolve_family_state(environment_scan, family_id)
    market_state_payload = dict(dict(environment_scan.get("market_state_snapshot", {})).get("payload", {}))
    request_id = f"shadow_run_verification_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ').lower()}"
    fallback_proposal = planner_service.build_mutation_proposal(
        request_id=request_id,
        family_id=family_id,
        family_state=selected_family_state,
        market_state_snapshot=market_state_payload,
    )

    planner_input = planner_service.build_planner_input(
        request_id=request_id,
        family_registry=registry,
        environment_scan=environment_scan,
    )
    planner_openai_config = {
        "enabled": True,
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-5.4",
        "prompt_template": "research_os_planner_mutation_proposal_v1",
        "responses_api": "https://api.openai.com/v1/responses",
        "timeout_seconds": 60,
        "reasoning_effort": "medium",
        "reasoning_summary": "auto",
        "strict_schema_validation": True,
        "fail_closed": True,
    }
    planner_config = {
        "enabled": True,
        "retrieval_packet": {
            "enabled": True,
            "path": str(resolved_retrieval_packet_path),
        },
        "controlled_comparison": {
            "enabled": True,
        },
        "openai": dict(planner_openai_config),
    }

    planner_authoritative = build_planner_mock_response(
        proposal=fallback_proposal,
        response_id="resp_planner_authoritative_shadow_verify",
        mechanism_hypothesis=fallback_proposal.mechanism_hypothesis,
        selection_rationale="Authoritative packet-free planner prompt remained decision owner.",
        exact_change=str(fallback_proposal.mutation_target.get("exact_change", "")),
        usage={"input_tokens": 110, "output_tokens": 18, "total_tokens": 128},
    )
    planner_shadow = build_planner_mock_response(
        proposal=fallback_proposal,
        response_id="resp_planner_candidate_shadow_verify",
        mechanism_hypothesis=(
            f"{fallback_proposal.mechanism_hypothesis} Shadow comparison observed retrieval packet context only."
        ),
        selection_rationale="Shadow planner prompt observed retrieval packet context without changing the authoritative proposal.",
        exact_change=str(fallback_proposal.mutation_target.get("exact_change", "")),
        usage={"input_tokens": 146, "output_tokens": 21, "total_tokens": 167},
    )

    if execution_mode == REAL_OPENAI_SHADOW_EXECUTION_MODE:
        planner_output = planner_service.plan_jobs(
            planner_input=planner_input,
            artifact_root=str(PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "mvp" / "artifacts"),
            openai_config=dict(planner_openai_config),
            planner_config=planner_config,
            governor_config={"allow_paused_stopped_family_planning_override": True},
            governor_state_by_family={},
        )
    else:
        with temporary_openai_api_key(), mock.patch.object(
            planner_service,
            "invoke_structured_response",
            side_effect=[planner_authoritative, planner_shadow],
        ):
            planner_output = planner_service.plan_jobs(
                planner_input=planner_input,
                artifact_root=str(PROJECT_ROOT / "outputs" / "research_os" / "dev_only" / "mvp" / "artifacts"),
                openai_config=dict(planner_openai_config),
                planner_config=planner_config,
                governor_config={"allow_paused_stopped_family_planning_override": True},
                governor_state_by_family={},
            )
    assert_planner_invariants(planner_output)

    resolved_summary_path = resolve_heavy_validation_summary_path(family_id, heavy_validation_summary_path)
    summary, compare_rows, cost_rows, source_artifact, source_paths = worker_service.load_heavy_validation_result_pack(
        resolved_summary_path
    )
    retrieval_packet = planner_service.load_passive_retrieval_packet(
        family_id,
        {"enabled": True, "path": str(resolved_retrieval_packet_path)},
    )
    source_artifact = {
        **dict(source_artifact),
        "optional_input_artifacts": {
            **dict(source_artifact.get("optional_input_artifacts", {})),
            "retrieval_packet": retrieval_packet,
        },
    }
    deterministic = worker_service._deterministic_family_verdict_data(summary, compare_rows, source_artifact)
    critic_openai_config = {
        "enabled": True,
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-5.4",
        "prompt_template": "research_os_critic_family_verdict_v1",
        "responses_api": "https://api.openai.com/v1/responses",
        "timeout_seconds": 60,
        "reasoning_effort": "medium",
        "reasoning_summary": "auto",
        "strict_schema_validation": True,
        "fail_closed": True,
    }
    critic_authoritative = build_critic_mock_response(
        deterministic=deterministic,
        response_id="resp_critic_authoritative_shadow_verify",
        recommended_reason=str(deterministic["verdict_reason"]),
        policy_alignment_note="Authoritative critic path kept the packet-free review authoritative and fail-closed.",
        usage={"input_tokens": 138, "output_tokens": 20, "total_tokens": 158},
    )
    critic_shadow = build_critic_mock_response(
        deterministic=deterministic,
        response_id="resp_critic_candidate_shadow_verify",
        recommended_reason=(
            f"{deterministic['verdict_reason']} Shadow comparison observed retrieval packet context only."
        ),
        policy_alignment_note="Shadow critic path observed retrieval packet context without changing the verdict.",
        usage={"input_tokens": 176, "output_tokens": 24, "total_tokens": 200},
    )

    if execution_mode == REAL_OPENAI_SHADOW_EXECUTION_MODE:
        critic_verdict = worker_service.build_family_verdict(
            summary=summary,
            compare_rows=compare_rows,
            cost_rows=cost_rows,
            source_artifact=source_artifact,
            source_paths=source_paths,
            critic_job_id=f"{request_id}_{family_id}_critic",
            critic_openai_config=dict(critic_openai_config),
            effective_openai_source={"base": "local_shadow_run_verification_real_openai"},
            critic_config={"controlled_comparison": {"enabled": True}},
        )
    else:
        with temporary_openai_api_key(), mock.patch.object(
            worker_service,
            "invoke_structured_response",
            side_effect=[critic_authoritative, critic_shadow],
        ):
            critic_verdict = worker_service.build_family_verdict(
                summary=summary,
                compare_rows=compare_rows,
                cost_rows=cost_rows,
                source_artifact=source_artifact,
                source_paths=source_paths,
                critic_job_id=f"{request_id}_{family_id}_critic",
                critic_openai_config=dict(critic_openai_config),
                effective_openai_source={"base": "local_shadow_run_verification"},
                critic_config={"controlled_comparison": {"enabled": True}},
            )
    assert_critic_invariants(critic_verdict)

    latest_governor_artifact = resolve_latest_governor_artifact_path(family_id)
    governor_reference = {
        "invoked": False,
        "unchanged_by_verification": True,
        "latest_existing_artifact_path": str(latest_governor_artifact) if latest_governor_artifact else "",
    }
    if latest_governor_artifact is not None:
        governor_payload = read_json(latest_governor_artifact)
        governor_reference["latest_existing_artifact"] = {
            "state_id": str(governor_payload.get("state_id", "")),
            "job_id": str(governor_payload.get("job_id", "")),
            "family_id": str(governor_payload.get("family_id", "")),
            "lifecycle_state": str(governor_payload.get("lifecycle_state", "")),
            "planning_eligible": bool(governor_payload.get("planning_eligible", False)),
            "planner_blocked_without_override": bool(
                dict(governor_payload.get("governance", {})).get("planner_blocked_without_override", False)
            ),
        }

    planner_summary = summarize_planner(planner_output)
    critic_summary = summarize_critic(critic_verdict)
    return {
        "schema_version": "trendatlas.shadow_run_verification.v1",
        "verified_at_utc": utc_now_iso(),
        "family_id": family_id,
        "final_status": "working",
        "execution_mode": execution_mode,
        "policy": {
            "authoritative_decision_behavior_changed": False,
            "fail_closed_preserved": True,
            "source_of_truth_mutation": False,
            "strategy_logic_mutation": False,
            "production_changes_required": False,
            "governor_mutated": False,
        },
        "inputs": {
            "registry_path": str(DEFAULT_REGISTRY_PATH),
            "planner_input_path": str(resolved_planner_input_path),
            "heavy_validation_summary_path": str(resolved_summary_path),
            "heavy_validation_compare_path": str(source_paths["compare"]),
            "heavy_validation_cost_metrics_path": str(source_paths["cost_metrics"]),
            "retrieval_packet": {
                "path": str(resolved_retrieval_packet_path),
                "latest_memory_id": str(dict(retrieval_packet.get("summary", {})).get("latest_memory_id", "")),
                "semantic_sha256": str(dict(retrieval_packet.get("summary", {})).get("semantic_sha256", "")),
                "resolved_batch_id": str(dict(retrieval_packet.get("summary", {})).get("resolved_batch_id", "")),
            },
        },
        "planner": planner_summary,
        "critic": critic_summary,
        "governor_reference": governor_reference,
    }


def run_verification(
    *,
    retrieval_packet_path: str | None,
    planner_input_path: str | None,
    heavy_validation_summary_path: str | None,
    output_dir: str | None,
    execution_mode: str = DEFAULT_SHADOW_EXECUTION_MODE,
) -> dict[str, Any]:
    summary_payload = evaluate_verification_case(
        retrieval_packet_path=retrieval_packet_path,
        planner_input_path=planner_input_path,
        heavy_validation_summary_path=heavy_validation_summary_path,
        execution_mode=execution_mode,
    )
    output_root = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    output_root = output_root if output_root.is_absolute() else (PROJECT_ROOT / output_root).resolve()
    json_path = output_root / "shadow_run_verification.json"
    md_path = output_root / "shadow_run_verification.md"
    write_json(json_path, summary_payload)
    write_text(md_path, build_markdown_report(summary_payload))
    return {
        "output_dir": str(output_root),
        "json_path": str(json_path),
        "md_path": str(md_path),
        "summary": summary_payload,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a local, safe TrendAtlas controlled retrieval shadow verification against current repo artifacts."
    )
    parser.add_argument("--retrieval-packet-path", default="")
    parser.add_argument("--planner-input-path", default="")
    parser.add_argument("--heavy-validation-summary-path", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--mode-config", default="")
    parser.add_argument("--use-real-openai", action="store_true")
    args = parser.parse_args()
    execution_mode = resolve_shadow_execution_mode(
        use_real_openai=bool(args.use_real_openai),
        mode_config_path=args.mode_config or None,
    )
    result = run_verification(
        retrieval_packet_path=args.retrieval_packet_path or None,
        planner_input_path=args.planner_input_path or None,
        heavy_validation_summary_path=args.heavy_validation_summary_path or None,
        output_dir=args.output_dir or None,
        execution_mode=execution_mode,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
