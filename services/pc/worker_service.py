from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path, PurePosixPath
from typing import Any

from services.pi.environment_scanner import load_runtime_config
from services.pi.job_queue import JobQueue, QueueMessage, build_queue, consume_exactly_one, publish_exactly_one
from services.pi.registry_service import RegistryService
from services.shared.artifact_writer import ArtifactWriter
from services.shared.openai_responses import describe_openai_operation, invoke_structured_response, serialize_openai_error
from services.shared.runtime_bootstrap import (
    assert_runtime_startup_ready,
    build_service_status,
    collect_runtime_readiness,
)
from services.shared.schemas import (
    CRITIC_STATUS_COMPLETED,
    CRITIC_STATUS_FAILED,
    CRITIC_STATUS_STARTED,
    FAMILY_NEXT_ACTION_CONTINUE,
    FAMILY_NEXT_ACTION_PAUSE,
    FAMILY_NEXT_ACTION_STOP,
    FAMILY_VERDICT_CONTINUE,
    FAMILY_VERDICT_PAUSE,
    FAMILY_VERDICT_STOP,
    HEAVY_VALIDATION_STATUS_COMPLETED,
    HEAVY_VALIDATION_STATUS_FAILED,
    HEAVY_VALIDATION_STATUS_PREPARED_NOT_SUBMITTED,
    HEAVY_VALIDATION_STATUS_QUEUE_PUBLISH_FAILED,
    HEAVY_VALIDATION_STATUS_STARTED,
    HEAVY_VALIDATION_STATUS_SUBMITTED,
    FamilyVerdict,
    HeavyValidationRequest,
    HeavyValidationResult,
    JOB_TYPE_ANALYZE_FAMILY_STATE,
    JOB_TYPE_PROPOSE_NEXT_MUTATION,
    JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB,
    JOB_TYPE_VALIDATION_PLACEHOLDER,
    JOB_STATUS_FAILED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MutationProposal,
    SCHEMA_VERSION,
    WorkerJob,
    WorkerResult,
    utc_now_iso,
)


def validate_safe_job(job: WorkerJob) -> None:
    if job.constraints.get("dev_only") is not True:
        raise ValueError("worker refuses jobs without dev_only=true")
    if job.constraints.get("non_authoritative") is not True:
        raise ValueError("worker refuses jobs without non_authoritative=true")
    if job.constraints.get("live_trading") is not False:
        raise ValueError("worker refuses jobs without live_trading=false")
    if job.constraints.get("source_of_truth_mutation") is not False:
        raise ValueError("worker refuses jobs without source_of_truth_mutation=false")
    if job.constraints.get("official_promotion_logic") is not False:
        raise ValueError("worker refuses jobs without official_promotion_logic=false")
    if job.job_type == JOB_TYPE_PROPOSE_NEXT_MUTATION:
        if not job.payload.get("safe_mutation_planning", False):
            raise ValueError("propose_next_mutation requires safe_mutation_planning=true")
        MutationProposal.from_mapping(job.payload.get("mutation_proposal", {}))
        return
    if job.job_type == JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB:
        if not job.payload.get("safe_heavy_validation_submission", False):
            raise ValueError("submit_heavy_validation_job requires safe_heavy_validation_submission=true")
        if not job.payload.get("validated_mutation_proposal_artifact_path", ""):
            raise ValueError("submit_heavy_validation_job requires validated_mutation_proposal_artifact_path")
        return
    if not job.payload.get("safe_placeholder", False):
        raise ValueError("worker MVP only accepts safe placeholder jobs outside mutation planning")
    if job.job_type not in {JOB_TYPE_VALIDATION_PLACEHOLDER, JOB_TYPE_ANALYZE_FAMILY_STATE}:
        raise ValueError(f"worker MVP refuses unsupported job_type={job.job_type}")


def build_family_analysis(job: WorkerJob) -> dict[str, Any]:
    snapshot = dict(job.payload.get("family_state_snapshot") or {})
    snapshot_path = str(job.payload.get("family_state_snapshot_path", ""))
    if not snapshot and snapshot_path:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8-sig"))
    families = list(snapshot.get("families", []))
    target = next((family for family in families if family.get("family_id") == job.family_id), {})
    if not target:
        raise ValueError(f"family_id not found in snapshot: {job.family_id}")
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job.job_id,
        "job_type": job.job_type,
        "family_id": job.family_id,
        "generated_at": utc_now_iso(),
        "mode": "dev_only_family_state_analysis",
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "live_trading": False,
        "source_of_truth_mutation": False,
        "official_promotion_logic": False,
        "strategy_mutation_execution": False,
        "input_snapshot_path": snapshot_path,
        "family_state": target,
        "analysis": {
            "last_verdict": target.get("last_verdict", ""),
            "attempt_count": target.get("attempt_count", 0),
            "last_metrics": target.get("last_metrics", {}),
            "lineage_artifact_ids": [attempt.get("artifact_id", "") for attempt in target.get("lineage", [])],
            "next_request_placeholder": {
                "request_type": "next_narrow_mutation_candidate_context",
                "execution_allowed": False,
                "reason": "context packaging only; no strategy mutation runner is invoked",
            },
        },
        "notes": [
            "read_only_family_snapshot_analysis",
            "no_live_trading_logic",
            "no_official_promotion_logic",
        ],
    }


def _target_family_from_snapshot(job: WorkerJob) -> dict[str, Any]:
    snapshot = dict(job.payload.get("family_state_snapshot") or {})
    snapshot_path = str(job.payload.get("family_state_snapshot_path", ""))
    if not snapshot and snapshot_path:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8-sig"))
    families = list(snapshot.get("families", []))
    target = next((family for family in families if family.get("family_id") == job.family_id), {})
    if not target:
        raise ValueError(f"family_id not found in snapshot: {job.family_id}")
    return dict(target)


def build_mutation_proposal_artifact(job: WorkerJob) -> dict[str, Any]:
    proposal = MutationProposal.from_mapping(job.payload.get("mutation_proposal", {}))
    family_state = _target_family_from_snapshot(job)
    lineage = {
        "planner_request_id": str(job.payload.get("planner_request_id", "")),
        "family_state_snapshot_path": str(job.payload.get("family_state_snapshot_path", "")),
        "market_state_snapshot_path": str(job.payload.get("market_state_snapshot_path", "")),
        "source_attempt_artifact_ids": [
            str(attempt.get("artifact_id", "")) for attempt in family_state.get("lineage", [])
        ],
        "source_last_verdict": str(family_state.get("last_verdict", "")),
        "source_last_metrics": dict(family_state.get("last_metrics", {})),
        "proposal_lineage_refs": dict(proposal.lineage_refs),
    }
    heavy_job_request = {
        "request_type": "dev_only_heavy_mutation_validation_request",
        "status": "prepared_not_submitted",
        "family_id": proposal.family_id,
        "proposal_id": proposal.proposal_id,
        "mutation_target": dict(proposal.mutation_target),
        "expected_impact": dict(proposal.expected_impact),
        "stop_condition": proposal.stop_condition,
        "execution_allowed": False,
        "strategy_code_executed": False,
        "queue_publish_allowed_by_worker": False,
        "constraints": {
            "dev_only": True,
            "non_authoritative": True,
            "official_truth": False,
            "live_trading": False,
            "source_of_truth_mutation": False,
            "official_promotion_logic": False,
            "strategy_mutation_execution": False,
            "single_candidate_only": True,
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job.job_id,
        "job_type": job.job_type,
        "family_id": job.family_id,
        "generated_at": utc_now_iso(),
        "mode": "dev_only_mutation_proposal_validation",
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "live_trading": False,
        "source_of_truth_mutation": False,
        "official_promotion_logic": False,
        "strategy_mutation_execution": False,
        "validation": {
            "status": "validated_queue_ready_request_only",
            "required_fields_present": True,
            "single_mutation_target": True,
            "strategy_code_executed": False,
        },
        "proposal": proposal.to_dict(),
        "proposal_lineage": lineage,
        "queue_ready_heavy_job_request": heavy_job_request,
        "notes": [
            "mutation_proposal_validated_only",
            "heavy_job_request_prepared_not_executed",
            "no_strategy_code_execution",
            "no_official_promotion_logic",
        ],
    }


def load_validated_mutation_proposal_artifact(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if payload.get("validation", {}).get("status") != "validated_queue_ready_request_only":
        raise ValueError("mutation proposal artifact is not validated_queue_ready_request_only")
    proposal = MutationProposal.from_mapping(payload.get("proposal", {}))
    heavy_request = dict(payload.get("queue_ready_heavy_job_request", {}))
    if heavy_request.get("status") != HEAVY_VALIDATION_STATUS_PREPARED_NOT_SUBMITTED:
        raise ValueError("mutation proposal heavy request is not prepared_not_submitted")
    if heavy_request.get("strategy_code_executed") is not False:
        raise ValueError("mutation proposal artifact indicates strategy code execution")
    if heavy_request.get("execution_allowed") is not False:
        raise ValueError("mutation proposal artifact allows execution")
    if heavy_request.get("proposal_id") != proposal.proposal_id:
        raise ValueError("mutation proposal and heavy request proposal_id mismatch")
    return payload


def build_heavy_validation_request(job: WorkerJob) -> HeavyValidationRequest:
    source_path = str(job.payload["validated_mutation_proposal_artifact_path"])
    proposal_artifact = load_validated_mutation_proposal_artifact(source_path)
    proposal = MutationProposal.from_mapping(proposal_artifact["proposal"])
    heavy_request = dict(proposal_artifact["queue_ready_heavy_job_request"])
    if proposal.family_id != job.family_id:
        raise ValueError("submit_heavy_validation_job family_id does not match mutation proposal family_id")
    return HeavyValidationRequest(
        schema_version=SCHEMA_VERSION,
        request_id=job.job_id,
        proposal_id=proposal.proposal_id,
        family_id=proposal.family_id,
        source_mutation_proposal_artifact=str(Path(source_path).resolve()),
        mutation_target=dict(heavy_request["mutation_target"]),
        expected_impact=dict(heavy_request["expected_impact"]),
        stop_condition=str(heavy_request["stop_condition"]),
        constraints={
            **dict(heavy_request.get("constraints", {})),
            "dev_only": True,
            "non_authoritative": True,
            "official_truth": False,
            "live_trading": False,
            "source_of_truth_mutation": False,
            "official_promotion_logic": False,
            "strategy_mutation_execution": False,
            "single_candidate_only": True,
        },
        status=HEAVY_VALIDATION_STATUS_PREPARED_NOT_SUBMITTED,
        dev_only=True,
        non_authoritative=True,
        official_truth=False,
        execution_allowed=False,
        strategy_code_executed=False,
    )


def build_heavy_validation_artifact_payload(
    job: WorkerJob,
    request: HeavyValidationRequest,
    source_artifact: dict[str, Any],
    queue_publish: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job.job_id,
        "job_type": job.job_type,
        "family_id": job.family_id,
        "generated_at": utc_now_iso(),
        "mode": "dev_only_heavy_validation_submission",
        "status": status,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "live_trading": False,
        "source_of_truth_mutation": False,
        "official_promotion_logic": False,
        "strategy_mutation_execution": False,
        "source_mutation_proposal_artifact": request.source_mutation_proposal_artifact,
        "source_mutation_proposal": {
            "job_id": source_artifact.get("job_id", ""),
            "proposal_id": source_artifact.get("proposal", {}).get("proposal_id", ""),
            "validation_status": source_artifact.get("validation", {}).get("status", ""),
        },
        "heavy_validation_request": {
            **request.to_dict(),
            "status": status,
        },
        "queue_publish": queue_publish,
        "notes": [
            "heavy_validation_request_artifact_only",
            "published_one_queue_message" if status == HEAVY_VALIDATION_STATUS_SUBMITTED else "queue_message_not_published",
            "no_heavy_backtest_execution",
            "no_strategy_code_execution",
        ],
    }


def execute_submit_heavy_validation_job(
    job: WorkerJob,
    writer: ArtifactWriter,
    registry: RegistryService,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    request = build_heavy_validation_request(job)
    source_artifact = load_validated_mutation_proposal_artifact(request.source_mutation_proposal_artifact)
    if registry.has_submitted_heavy_validation_request(exclude_request_id=request.request_id):
        raise ValueError("worker refuses to submit more than one active heavy validation request at a time")
    artifact_relative_path = f"worker_outputs/{job.job_id}_heavy_validation_request.json"
    registry.record_heavy_validation_request(
        job_id=job.job_id,
        request=request.to_dict(),
        status=HEAVY_VALIDATION_STATUS_PREPARED_NOT_SUBMITTED,
    )
    queue_backend = str(job.payload.get("queue_backend", "memory"))
    redis_url = str(job.payload.get("redis_url", "redis://localhost:6379/0"))
    queue_stream = str(job.payload.get("heavy_validation_stream", "research_os:heavy_validation_jobs"))
    queue = build_queue(queue_backend, redis_url)
    queue_payload = {
        "schema_version": SCHEMA_VERSION,
        "message_type": "heavy_validation_request",
        "request_artifact_path": str((writer.artifact_root / artifact_relative_path).resolve()),
        "request": request.to_dict(),
        "source_mutation_proposal": {
            "artifact_path": request.source_mutation_proposal_artifact,
            "proposal_id": request.proposal_id,
        },
    }
    try:
        queue_publish = publish_exactly_one(queue=queue, stream=queue_stream, payload=queue_payload)
    except Exception as exc:
        artifact_payload = build_heavy_validation_artifact_payload(
            job=job,
            request=request,
            source_artifact=source_artifact,
            queue_publish={"published_count": 0, "stream": queue_stream, "message_id": "", "error": str(exc)},
            status=HEAVY_VALIDATION_STATUS_QUEUE_PUBLISH_FAILED,
        )
        json_record = writer.write_json(
            artifact_relative_path,
            artifact_payload,
            metadata={"job_id": job.job_id, "job_type": job.job_type},
        )
        registry.record_heavy_validation_request(
            job_id=job.job_id,
            request={**request.to_dict(), "status": HEAVY_VALIDATION_STATUS_QUEUE_PUBLISH_FAILED},
            status=HEAVY_VALIDATION_STATUS_QUEUE_PUBLISH_FAILED,
            artifact_path=json_record.path,
            queue_stream=queue_stream,
            error=str(exc),
        )
        return artifact_payload, [json_record.to_dict()], "heavy validation queue publish failed"
    artifact_payload = build_heavy_validation_artifact_payload(
        job=job,
        request=request,
        source_artifact=source_artifact,
        queue_publish=queue_publish,
        status=HEAVY_VALIDATION_STATUS_SUBMITTED,
    )
    json_record = writer.write_json(
        artifact_relative_path,
        artifact_payload,
        metadata={"job_id": job.job_id, "job_type": job.job_type},
    )
    registry.record_heavy_validation_request(
        job_id=job.job_id,
        request={**request.to_dict(), "status": HEAVY_VALIDATION_STATUS_SUBMITTED},
        status=HEAVY_VALIDATION_STATUS_SUBMITTED,
        artifact_path=json_record.path,
        queue_stream=queue_stream,
        queue_message_id=str(queue_publish["message_id"]),
    )
    return artifact_payload, [json_record.to_dict()], "heavy validation request submitted"


def load_heavy_validation_request_artifact(path: str | Path) -> tuple[dict[str, Any], HeavyValidationRequest]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    request_payload = dict(payload.get("heavy_validation_request", payload.get("request", payload)))
    request = HeavyValidationRequest.from_mapping(request_payload)
    if payload.get("family_id", request.family_id) != request.family_id:
        raise ValueError("heavy validation artifact family_id does not match request family_id")
    if payload.get("dev_only", True) is not True:
        raise ValueError("heavy validation artifact dev_only must be true")
    if payload.get("non_authoritative", True) is not True:
        raise ValueError("heavy validation artifact non_authoritative must be true")
    if payload.get("official_truth", False) is not False:
        raise ValueError("heavy validation artifact official_truth must be false")
    if payload.get("strategy_advancement", False) is not False:
        raise ValueError("heavy validation artifact strategy_advancement must be false")
    if payload.get("strategy_mutation_execution", False) is not False:
        raise ValueError("heavy validation artifact strategy_mutation_execution must be false")
    return payload, request


def validate_heavy_validation_message(
    message: QueueMessage,
    request_artifact: dict[str, Any],
    request: HeavyValidationRequest,
) -> None:
    if message.stream != "research_os:heavy_validation_jobs":
        raise ValueError(f"unexpected heavy validation stream: {message.stream}")
    payload = dict(message.payload)
    if payload.get("message_type") != "heavy_validation_request":
        raise ValueError("heavy validation queue message_type must be heavy_validation_request")
    message_request = payload.get("request", {})
    if message_request:
        queued_request = HeavyValidationRequest.from_mapping(message_request)
        if queued_request.request_id != request.request_id:
            raise ValueError("queued request_id does not match request artifact")
        if queued_request.family_id != request.family_id:
            raise ValueError("queued family_id does not match request artifact")
    if request.family_id != request_artifact.get("family_id", request.family_id):
        raise ValueError("heavy job family does not match request family")


def validate_heavy_validation_source_proposal(request: HeavyValidationRequest) -> dict[str, Any]:
    source_artifact = load_validated_mutation_proposal_artifact(request.source_mutation_proposal_artifact)
    proposal = MutationProposal.from_mapping(source_artifact["proposal"])
    if proposal.family_id != request.family_id:
        raise ValueError("heavy validation request family_id does not match source proposal family_id")
    if proposal.proposal_id != request.proposal_id:
        raise ValueError("heavy validation request proposal_id does not match source proposal proposal_id")
    if source_artifact.get("dev_only", True) is not True:
        raise ValueError("source proposal artifact dev_only must be true")
    if source_artifact.get("non_authoritative", True) is not True:
        raise ValueError("source proposal artifact non_authoritative must be true")
    if source_artifact.get("official_truth", False) is not False:
        raise ValueError("source proposal artifact official_truth must be false")
    if source_artifact.get("strategy_advancement", False) is not False:
        raise ValueError("source proposal artifact strategy_advancement must be false")
    return source_artifact


def run_safe_heavy_validation_adapter(
    request: HeavyValidationRequest,
    source_artifact: dict[str, Any],
    writer: ArtifactWriter,
    job_id: str,
    started_at: str,
) -> tuple[HeavyValidationResult, list[dict[str, Any]]]:
    adapter_id = "safe_dev_only_artifact_adapter_v1"
    impact = {str(key): dict(value) for key, value in request.expected_impact.items()}
    compare_rows = [
        {
            "job_id": job_id,
            "request_id": request.request_id,
            "proposal_id": request.proposal_id,
            "family_id": request.family_id,
            "metric": metric,
            "expected_direction": str(details.get("direction", "")),
            "target": str(details.get("target", "")),
            "basis_json": json.dumps(details.get("basis", {}), sort_keys=True, default=str),
            "adapter_verdict": "queued_for_local_heavy_validation_only",
            "strategy_code_executed": False,
        }
        for metric, details in sorted(impact.items())
    ]
    cost_rows = [
        {
            "job_id": job_id,
            "request_id": request.request_id,
            "proposal_id": request.proposal_id,
            "family_id": request.family_id,
            "metric": "strategy_code_executed",
            "value": "false",
            "unit": "bool",
            "source": adapter_id,
        },
        {
            "job_id": job_id,
            "request_id": request.request_id,
            "proposal_id": request.proposal_id,
            "family_id": request.family_id,
            "metric": "adapter_generated_trade_count",
            "value": "0",
            "unit": "count",
            "source": adapter_id,
        },
        {
            "job_id": job_id,
            "request_id": request.request_id,
            "proposal_id": request.proposal_id,
            "family_id": request.family_id,
            "metric": "adapter_generated_turnover",
            "value": "0.0",
            "unit": "ratio",
            "source": adapter_id,
        },
    ]
    compare_record = writer.write_csv(
        f"heavy_validation_outputs/{job_id}_compare.csv",
        compare_rows,
        fieldnames=[
            "job_id",
            "request_id",
            "proposal_id",
            "family_id",
            "metric",
            "expected_direction",
            "target",
            "basis_json",
            "adapter_verdict",
            "strategy_code_executed",
        ],
        metadata={"job_id": job_id, "request_id": request.request_id, "adapter_id": adapter_id},
    )
    cost_record = writer.write_csv(
        f"heavy_validation_outputs/{job_id}_cost_metrics.csv",
        cost_rows,
        fieldnames=["job_id", "request_id", "proposal_id", "family_id", "metric", "value", "unit", "source"],
        metadata={"job_id": job_id, "request_id": request.request_id, "adapter_id": adapter_id},
    )
    finished_at = utc_now_iso()
    summary_payload = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "request_id": request.request_id,
        "proposal_id": request.proposal_id,
        "family_id": request.family_id,
        "status": HEAVY_VALIDATION_STATUS_COMPLETED,
        "adapter_id": adapter_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "strategy_advancement": False,
        "strategy_code_executed": False,
        "live_trading": False,
        "source_of_truth_mutation": False,
        "official_promotion_logic": False,
        "source_mutation_proposal_artifact": request.source_mutation_proposal_artifact,
        "source_mutation_proposal": {
            "job_id": source_artifact.get("job_id", ""),
            "proposal_id": source_artifact.get("proposal", {}).get("proposal_id", ""),
            "validation_status": source_artifact.get("validation", {}).get("status", ""),
        },
        "mutation_target": request.mutation_target,
        "expected_impact": request.expected_impact,
        "stop_condition": request.stop_condition,
        "artifact_paths": {
            "compare": compare_record.path,
            "cost_metrics": cost_record.path,
        },
        "notes": [
            "safe_dev_only_adapter_only",
            "deterministic_compare_and_cost_pack_from_existing_artifacts",
            "no_strategy_mutation_execution",
            "no_live_trading_logic",
            "no_source_of_truth_mutation",
            "no_official_promotion_logic",
        ],
    }
    summary_record = writer.write_json(
        f"heavy_validation_outputs/{job_id}_summary.json",
        summary_payload,
        metadata={"job_id": job_id, "request_id": request.request_id, "adapter_id": adapter_id},
    )
    artifact_refs = [summary_record.to_dict(), compare_record.to_dict(), cost_record.to_dict()]
    result = HeavyValidationResult(
        schema_version=SCHEMA_VERSION,
        result_id=f"{request.request_id}_heavy_validation_result",
        request_id=request.request_id,
        proposal_id=request.proposal_id,
        job_id=job_id,
        family_id=request.family_id,
        status=HEAVY_VALIDATION_STATUS_COMPLETED,
        started_at=started_at,
        finished_at=finished_at,
        adapter_id=adapter_id,
        summary=summary_payload,
        artifact_refs=artifact_refs,
    )
    HeavyValidationResult.from_mapping(result.to_dict())
    return result, artifact_refs


def execute_heavy_validation_message(
    message: QueueMessage,
    artifact_root: str,
    registry: RegistryService,
) -> WorkerResult:
    started_at = utc_now_iso()
    writer = ArtifactWriter(artifact_root)
    request: HeavyValidationRequest | None = None
    request_artifact: dict[str, Any] = {}
    job_id = "unknown_heavy_validation_job"
    try:
        request_artifact_path = str(message.payload.get("request_artifact_path", ""))
        if not request_artifact_path:
            raise ValueError("heavy validation message requires request_artifact_path")
        request_artifact, request = load_heavy_validation_request_artifact(request_artifact_path)
        validate_heavy_validation_message(message, request_artifact, request)
        source_artifact = validate_heavy_validation_source_proposal(request)
        job_id = request.request_id
        registry.record_heavy_validation_event(
            request_id=request.request_id,
            proposal_id=request.proposal_id,
            job_id=job_id,
            family_id=request.family_id,
            event_type=HEAVY_VALIDATION_STATUS_STARTED,
            event={
                "status": HEAVY_VALIDATION_STATUS_STARTED,
                "request_id": request.request_id,
                "proposal_id": request.proposal_id,
                "job_id": job_id,
                "family_id": request.family_id,
                "queue_stream": message.stream,
                "queue_message_id": message.message_id,
                "request_artifact_path": request_artifact_path,
            },
        )
        result, artifact_refs = run_safe_heavy_validation_adapter(
            request=request,
            source_artifact=source_artifact,
            writer=writer,
            job_id=job_id,
            started_at=started_at,
        )
        paths = {record["format"]: record["path"] for record in artifact_refs}
        summary_path = next(record["path"] for record in artifact_refs if record["path"].endswith("_summary.json"))
        compare_path = next(record["path"] for record in artifact_refs if record["path"].endswith("_compare.csv"))
        cost_metrics_path = next(record["path"] for record in artifact_refs if record["path"].endswith("_cost_metrics.csv"))
        del paths
        registry.record_heavy_validation_result(
            result=result,
            summary_path=summary_path,
            compare_path=compare_path,
            cost_metrics_path=cost_metrics_path,
        )
        for artifact_record in artifact_refs:
            registry.record_artifact(job_id, artifact_record)
        return WorkerResult(
            schema_version=SCHEMA_VERSION,
            job_id=job_id,
            status=JOB_STATUS_SUCCEEDED,
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifact_refs=artifact_refs,
            metrics={"heavy_validation_result_status": HEAVY_VALIDATION_STATUS_COMPLETED},
            notes=["heavy validation safe adapter completed"],
        )
    except Exception as exc:
        if request is not None:
            failed_result = HeavyValidationResult(
                schema_version=SCHEMA_VERSION,
                result_id=f"{request.request_id}_heavy_validation_result",
                request_id=request.request_id,
                proposal_id=request.proposal_id,
                job_id=job_id,
                family_id=request.family_id,
                status=HEAVY_VALIDATION_STATUS_FAILED,
                started_at=started_at,
                finished_at=utc_now_iso(),
                adapter_id="safe_dev_only_artifact_adapter_v1",
                summary={
                    "status": HEAVY_VALIDATION_STATUS_FAILED,
                    "error": str(exc),
                    "request_artifact_job_id": request_artifact.get("job_id", ""),
                },
                artifact_refs=[],
                error=str(exc),
            )
            registry.record_heavy_validation_result(
                result=failed_result,
                summary_path="",
                compare_path="",
                cost_metrics_path="",
            )
        return WorkerResult(
            schema_version=SCHEMA_VERSION,
            job_id=job_id,
            status=JOB_STATUS_FAILED,
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifact_refs=[],
            metrics={},
            notes=["heavy validation safe adapter failed"],
            error=str(exc),
        )


def _read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _require_false(payload: dict[str, Any], key: str, label: str) -> None:
    if payload.get(key) is not False:
        raise ValueError(f"{label}.{key} must be false")


def _require_true(payload: dict[str, Any], key: str, label: str) -> None:
    if payload.get(key) is not True:
        raise ValueError(f"{label}.{key} must be true")


def validate_heavy_validation_result_pack(
    summary: dict[str, Any],
    compare_rows: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
) -> None:
    if summary.get("status") != HEAVY_VALIDATION_STATUS_COMPLETED:
        raise ValueError("critic requires a completed heavy validation result pack")
    _require_true(summary, "dev_only", "heavy_validation_summary")
    _require_true(summary, "non_authoritative", "heavy_validation_summary")
    for key in (
        "official_truth",
        "strategy_advancement",
        "strategy_code_executed",
        "live_trading",
        "source_of_truth_mutation",
        "official_promotion_logic",
    ):
        _require_false(summary, key, "heavy_validation_summary")
    family_id = str(summary.get("family_id", ""))
    if not family_id:
        raise ValueError("heavy validation summary requires family_id")
    if not compare_rows:
        raise ValueError("critic requires a non-empty heavy validation compare artifact")
    for row in compare_rows:
        if str(row.get("family_id", "")) != family_id:
            raise ValueError("compare artifact family_id does not match summary family_id")
        if str(row.get("strategy_code_executed", "false")).strip().lower() not in {"false", "0"}:
            raise ValueError("compare artifact indicates strategy code execution")
    for row in cost_rows:
        if str(row.get("family_id", family_id)) != family_id:
            raise ValueError("cost metrics artifact family_id does not match summary family_id")
        if str(row.get("metric", "")) == "strategy_code_executed":
            if str(row.get("value", "false")).strip().lower() not in {"false", "0"}:
                raise ValueError("cost metrics artifact indicates strategy code execution")


def _compare_basis(compare_rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    for row in compare_rows:
        if str(row.get("metric", "")) == metric:
            raw = str(row.get("basis_json", "{}") or "{}")
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
    return {}


def _heavy_validation_project_root(summary_path: Path) -> Path:
    raw_root = os.environ.get("RESEARCH_OS_ROOT", "").strip()
    if raw_root:
        return Path(raw_root).expanduser().resolve()
    for parent in summary_path.parents:
        if parent.name == "outputs":
            return parent.parent.resolve()
    return Path(__file__).resolve().parents[2]


def _rebase_legacy_project_path(raw_path: str, project_root: Path) -> Path | None:
    if not raw_path.startswith("/"):
        return None
    posix_parts = tuple(part for part in PurePosixPath(raw_path).parts if part not in {"/", ""})
    if not posix_parts:
        return None
    try:
        project_index = posix_parts.index(project_root.name)
    except ValueError:
        return None
    suffix = posix_parts[project_index + 1 :]
    return (project_root / Path(*suffix)).resolve() if suffix else project_root


def _resolve_heavy_validation_path(path_value: str | Path, *, project_root: Path, relative_base: Path) -> Path:
    raw_path = str(path_value).strip()
    if not raw_path:
        raise ValueError("heavy validation path must not be empty")
    rebased_path = _rebase_legacy_project_path(raw_path, project_root)
    if rebased_path is not None:
        return rebased_path
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (relative_base / candidate).resolve()


def load_heavy_validation_result_pack(summary_path: str | Path) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, str],
]:
    summary_path = Path(summary_path).resolve()
    project_root = _heavy_validation_project_root(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    artifact_paths = dict(summary.get("artifact_paths", {}))
    compare_path = _resolve_heavy_validation_path(
        artifact_paths.get("compare") or summary_path.with_name(summary_path.name.replace("_summary.json", "_compare.csv")),
        project_root=project_root,
        relative_base=summary_path.parent,
    )
    cost_metrics_path = _resolve_heavy_validation_path(
        artifact_paths.get("cost_metrics") or summary_path.with_name(summary_path.name.replace("_summary.json", "_cost_metrics.csv")),
        project_root=project_root,
        relative_base=summary_path.parent,
    )
    compare_rows = _read_csv_rows(compare_path)
    cost_rows = _read_csv_rows(cost_metrics_path)
    validate_heavy_validation_result_pack(summary, compare_rows, cost_rows)
    source_mutation_proposal_path = _resolve_heavy_validation_path(
        summary["source_mutation_proposal_artifact"],
        project_root=project_root,
        relative_base=summary_path.parent,
    )
    source_artifact = load_validated_mutation_proposal_artifact(str(source_mutation_proposal_path))
    if source_artifact.get("family_id") != summary.get("family_id"):
        raise ValueError("source mutation proposal family_id does not match heavy validation summary family_id")
    return (
        summary,
        compare_rows,
        cost_rows,
        source_artifact,
        {
            "summary": str(summary_path),
            "compare": str(compare_path),
            "cost_metrics": str(cost_metrics_path),
        },
    )


def _deterministic_family_verdict_data(
    summary: dict[str, Any],
    compare_rows: list[dict[str, Any]],
    source_artifact: dict[str, Any],
) -> dict[str, Any]:
    lineage_metrics = dict(source_artifact.get("proposal_lineage", {}).get("source_last_metrics", {}))
    net_basis = _compare_basis(compare_rows, "net_benefit")
    dd_basis = _compare_basis(compare_rows, "dd")
    switch_basis = _compare_basis(compare_rows, "switch_count")
    churn_basis = _compare_basis(compare_rows, "churn")
    net_return = _first_number(
        lineage_metrics.get("net_total_return_delta_pct"),
        lineage_metrics.get("net_cagr_delta_pct"),
        net_basis.get("latest_net_total_return_delta_pct"),
        net_basis.get("latest_net_cagr_delta_pct"),
    )
    key_metrics = {
        "net_return": net_return,
        "dd": _first_number(
            lineage_metrics.get("max_drawdown_delta_pct"),
            dd_basis.get("latest_max_drawdown_delta_pct"),
        ),
        "trade_days_delta": _number(lineage_metrics.get("trade_days_delta")),
        "switch_count_delta": _first_number(
            lineage_metrics.get("switch_count_delta"),
            switch_basis.get("latest_switch_count_delta"),
        ),
        "turnover_pressure": _first_number(
            lineage_metrics.get("turnover_pressure_delta"),
            churn_basis.get("latest_turnover_pressure_delta"),
        ),
    }
    breaches: list[str] = []
    if key_metrics["dd"] is not None and float(key_metrics["dd"]) < -1.0:
        breaches.append("dd below -1.0")
    if key_metrics["trade_days_delta"] is not None and float(key_metrics["trade_days_delta"]) > 4.0:
        breaches.append("trade days delta above 4")
    if key_metrics["switch_count_delta"] is not None and float(key_metrics["switch_count_delta"]) > 4.0:
        breaches.append("switch count delta above 4")
    if key_metrics["turnover_pressure"] is not None and float(key_metrics["turnover_pressure"]) > 0.0:
        breaches.append("turnover pressure above 0")

    if net_return is None:
        verdict = FAMILY_VERDICT_PAUSE
        next_action = FAMILY_NEXT_ACTION_PAUSE
        verdict_reason = "pause: net return metric is unavailable in the heavy validation pack"
    elif float(net_return) <= 0.0:
        verdict = FAMILY_VERDICT_STOP
        next_action = FAMILY_NEXT_ACTION_STOP
        verdict_reason = "stop: net return is not positive after costs"
    elif breaches:
        verdict = FAMILY_VERDICT_PAUSE
        next_action = FAMILY_NEXT_ACTION_PAUSE
        verdict_reason = f"pause: net return remains positive, but guardrails breached: {', '.join(breaches)}"
    else:
        verdict = FAMILY_VERDICT_CONTINUE
        next_action = FAMILY_NEXT_ACTION_CONTINUE
        verdict_reason = "continue: net return is positive and risk/churn guardrails are not breached"

    proposal = dict(source_artifact.get("proposal", {}))
    mutation_target = dict(proposal.get("mutation_target") or summary.get("mutation_target") or {})
    mechanism_id = str(mutation_target.get("source_artifact_id") or mutation_target.get("target_id") or "")
    return {
        "key_metrics": key_metrics,
        "breaches": breaches,
        "verdict": verdict,
        "next_action": next_action,
        "verdict_reason": verdict_reason,
        "mechanism_id": mechanism_id,
    }


_CRITIC_LINEAGE_METRIC_KEYS = (
    "net_total_return_delta_pct",
    "net_cagr_delta_pct",
    "max_drawdown_delta_pct",
    "switch_count_delta",
    "trade_days_delta",
    "turnover_pressure_delta",
)


def _compact_lineage_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metrics.get(key)
        for key in _CRITIC_LINEAGE_METRIC_KEYS
        if key in metrics
    }


def _compact_compare_rows(compare_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_rows: list[dict[str, Any]] = []
    for row in compare_rows:
        compact_rows.append(
            {
                "metric": str(row.get("metric", "")),
                "expected_direction": str(row.get("expected_direction", "")),
                "target": str(row.get("target", "")),
                "basis": _compare_basis([row], str(row.get("metric", ""))),
            }
        )
    return compact_rows


def _compact_cost_rows(cost_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "metric": str(row.get("metric", "")),
            "value": str(row.get("value", "")),
            "unit": str(row.get("unit", "")),
        }
        for row in cost_rows
    ]


def _critic_review_packet(
    *,
    summary: dict[str, Any],
    compare_rows: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
    source_artifact: dict[str, Any],
    deterministic: dict[str, Any],
) -> dict[str, Any]:
    proposal = dict(source_artifact.get("proposal", {}))
    proposal_lineage = dict(source_artifact.get("proposal_lineage", {}))
    mutation_target = dict(proposal.get("mutation_target", {}))
    return {
        "runtime_mode": {
            "dev_only": True,
            "non_authoritative": True,
            "execution_allowed": False,
        },
        "validation_context": {
            "request_id": str(summary.get("request_id", "")),
            "family_id": str(summary.get("family_id", "")),
            "proposal_id": str(summary.get("proposal_id", "")),
            "status": str(summary.get("status", "")),
            "adapter_id": str(summary.get("adapter_id", "")),
            "compare_metrics": _compact_compare_rows(compare_rows),
            "cost_metrics": _compact_cost_rows(cost_rows),
        },
        "proposal_context": {
            "mechanism_hypothesis": str(proposal.get("mechanism_hypothesis", "")),
            "mutation_target": {
                "target_id": str(mutation_target.get("target_id", "")),
                "target_type": str(mutation_target.get("target_type", "")),
                "source_artifact_id": str(mutation_target.get("source_artifact_id", "")),
                "exact_change": str(mutation_target.get("exact_change", "")),
            },
            "stop_condition": str(proposal.get("stop_condition") or summary.get("stop_condition", "")),
        },
        "lineage_context": {
            "source_last_verdict": str(proposal_lineage.get("source_last_verdict", "")),
            "source_last_metrics": _compact_lineage_metrics(dict(proposal_lineage.get("source_last_metrics", {}))),
            "source_attempt_artifact_ids": list(proposal_lineage.get("source_attempt_artifact_ids", []))[-2:],
        },
        "net_first_policy": {
            "stop_if_net_return_lte": 0.0,
            "pause_if_dd_lt": -1.0,
            "pause_if_trade_days_delta_gt": 4.0,
            "pause_if_switch_count_delta_gt": 4.0,
            "pause_if_turnover_pressure_gt": 0.0,
        },
        "derived_key_metrics": dict(deterministic["key_metrics"]),
        "deterministic_reference": {
            "verdict": str(deterministic["verdict"]),
            "next_action": str(deterministic["next_action"]),
            "guardrail_breaches": list(deterministic["breaches"]),
        },
    }


def _critic_prompt_template(prompt_template: str) -> str:
    if prompt_template == "research_os_critic_family_verdict_v1":
        return (
            "You are the MRV1 critic for a dev-only, non-authoritative research runtime. "
            "Review one heavy-validation result pack and return a single family verdict recommendation. "
            "You must apply the supplied net-first policy exactly, and you must not authorize live trading, "
            "source-of-truth mutation, official promotion logic, or strategy execution. "
            "Keep recommended_reason and policy_alignment_note concise."
        )
    return (
        "You are the MRV1 critic for a dev-only, non-authoritative research runtime. "
        "Return one concise verdict recommendation that strictly follows the supplied policy."
    )


def _critic_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "recommended_verdict": {
                "type": "string",
                "enum": [
                    FAMILY_VERDICT_CONTINUE,
                    FAMILY_VERDICT_PAUSE,
                    FAMILY_VERDICT_STOP,
                ],
            },
            "recommended_next_action": {
                "type": "string",
                "enum": [
                    FAMILY_NEXT_ACTION_CONTINUE,
                    FAMILY_NEXT_ACTION_PAUSE,
                    FAMILY_NEXT_ACTION_STOP,
                ],
            },
            "recommended_reason": {"type": "string"},
            "guardrail_breaches": {
                "type": "array",
                "items": {"type": "string"},
            },
            "policy_alignment_note": {"type": "string"},
        },
        "required": [
            "recommended_verdict",
            "recommended_next_action",
            "recommended_reason",
            "guardrail_breaches",
            "policy_alignment_note",
        ],
    }


def _critic_user_payload(
    *,
    summary: dict[str, Any],
    compare_rows: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
    source_artifact: dict[str, Any],
    deterministic: dict[str, Any],
) -> dict[str, Any]:
    return _critic_review_packet(
        summary=summary,
        compare_rows=compare_rows,
        cost_rows=cost_rows,
        source_artifact=source_artifact,
        deterministic=deterministic,
    )


def _run_openai_critic_review(
    *,
    summary: dict[str, Any],
    compare_rows: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
    source_artifact: dict[str, Any],
    deterministic: dict[str, Any],
    critic_openai_config: dict[str, Any],
) -> dict[str, Any]:
    response = invoke_structured_response(
        critic_openai_config,
        system_prompt=_critic_prompt_template(str(critic_openai_config.get("prompt_template", ""))),
        user_payload=_critic_user_payload(
            summary=summary,
            compare_rows=compare_rows,
            cost_rows=cost_rows,
            source_artifact=source_artifact,
            deterministic=deterministic,
        ),
        schema_name="research_os_critic_family_verdict",
        schema=_critic_response_schema(),
    )
    return {
        **describe_openai_operation(critic_openai_config),
        "network_call": "completed",
        "response_id": response.response_id,
        "response_status": response.status,
        "response_model": response.model,
        "usage": response.usage,
        "recommended_verdict": str(response.parsed.get("recommended_verdict", "")),
        "recommended_next_action": str(response.parsed.get("recommended_next_action", "")),
        "recommended_reason": str(response.parsed.get("recommended_reason", "")),
        "guardrail_breaches": [str(item) for item in list(response.parsed.get("guardrail_breaches", []))],
        "policy_alignment_note": str(response.parsed.get("policy_alignment_note", "")),
    }


def _resolve_critic_openai_config(
    runtime_openai_config: dict[str, Any] | None,
    critic_component_openai_config: dict[str, Any] | None,
    critic_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime_openai = dict(runtime_openai_config or {})
    critic_component_openai = dict(critic_component_openai_config or {})
    critic_config = dict(critic_config or {})
    effective_openai_config = dict(runtime_openai)
    effective_openai_config.update(critic_component_openai)
    enabled_source = "default_false"
    runtime_enabled_present = bool(critic_config.get("_runtime_openai_enabled_present", "enabled" in runtime_openai))
    runtime_enabled = bool(critic_config.get("_runtime_openai_enabled_value", runtime_openai.get("enabled", False)))
    component_enabled_present = bool(
        critic_config.get("_component_openai_enabled_present", "enabled" in critic_component_openai)
    )
    component_enabled = bool(
        critic_config.get("_component_openai_enabled_value", critic_component_openai.get("enabled", False))
    )
    raw_config_enabled_value = False
    resolved_enabled_value = runtime_enabled or component_enabled
    effective_openai_config["enabled"] = resolved_enabled_value
    if component_enabled_present and component_enabled:
        enabled_source = "critic.openai.enabled"
        raw_config_enabled_value = component_enabled
    elif runtime_enabled_present and runtime_enabled:
        enabled_source = "runtime.openai.enabled"
        raw_config_enabled_value = runtime_enabled
    elif component_enabled_present:
        enabled_source = "critic.openai.enabled"
        raw_config_enabled_value = component_enabled
    elif runtime_enabled_present:
        enabled_source = "runtime.openai.enabled"
        raw_config_enabled_value = runtime_enabled
    return effective_openai_config, {
        "base": "runtime.openai",
        "overlay": "critic.openai",
        "enabled_from": enabled_source,
        "enabled_resolution_debug": {
            "raw_config_enabled_value": raw_config_enabled_value,
            "resolved_enabled_value": resolved_enabled_value,
            "where_override_happened": (
                "none"
                if raw_config_enabled_value == resolved_enabled_value
                else "services/pc/worker_service.py:_resolve_critic_openai_config"
            ),
        },
        "runtime_keys": sorted(str(key) for key in runtime_openai.keys()),
        "component_keys": sorted(str(key) for key in critic_component_openai.keys()),
    }


def build_family_verdict(
    summary: dict[str, Any],
    compare_rows: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
    source_artifact: dict[str, Any],
    source_paths: dict[str, str],
    critic_job_id: str,
    critic_openai_config: dict[str, Any] | None = None,
    effective_openai_source: dict[str, Any] | None = None,
) -> FamilyVerdict:
    deterministic = _deterministic_family_verdict_data(summary, compare_rows, source_artifact)
    critic_openai_config = dict(critic_openai_config or {})
    openai_review = {
        **describe_openai_operation(critic_openai_config),
        "effective_openai_config": dict(critic_openai_config),
        "effective_openai_source": dict(effective_openai_source or {}),
    }
    verdict_reason = str(deterministic["verdict_reason"])
    breaches = list(deterministic["breaches"])
    if bool(critic_openai_config.get("enabled", False)):
        openai_review = _run_openai_critic_review(
            summary=summary,
            compare_rows=compare_rows,
            cost_rows=cost_rows,
            source_artifact=source_artifact,
            deterministic=deterministic,
            critic_openai_config=critic_openai_config,
        )
        openai_review["effective_openai_config"] = dict(critic_openai_config)
        openai_review["effective_openai_source"] = dict(effective_openai_source or {})
        for item in list(openai_review.get("guardrail_breaches", [])):
            value = str(item).strip()
            if value and value not in breaches:
                breaches.append(value)
        if (
            str(openai_review.get("recommended_verdict", "")) == str(deterministic["verdict"])
            and str(openai_review.get("recommended_next_action", "")) == str(deterministic["next_action"])
        ):
            candidate_reason = str(openai_review.get("recommended_reason", "")).strip()
            if candidate_reason:
                verdict_reason = candidate_reason
            openai_review["recommendation_applied"] = True
        else:
            openai_review["recommendation_applied"] = False
            openai_review["deterministic_verdict"] = str(deterministic["verdict"])
            openai_review["deterministic_next_action"] = str(deterministic["next_action"])
    family_verdict = FamilyVerdict(
        schema_version=SCHEMA_VERSION,
        verdict_id=f"{critic_job_id}_family_verdict",
        job_id=critic_job_id,
        result_id=f"{summary['request_id']}_heavy_validation_result",
        request_id=str(summary["request_id"]),
        proposal_id=str(summary["proposal_id"]),
        family_id=str(summary["family_id"]),
        mechanism_id=str(deterministic["mechanism_id"]),
        status=CRITIC_STATUS_COMPLETED,
        verdict=str(deterministic["verdict"]),
        verdict_reason=verdict_reason,
        key_metrics=dict(deterministic["key_metrics"]),
        next_action=str(deterministic["next_action"]),
        generated_at=utc_now_iso(),
        source_summary_path=source_paths["summary"],
        source_compare_path=source_paths["compare"],
        source_cost_metrics_path=source_paths["cost_metrics"],
        evidence={
            "adapter_id": str(summary.get("adapter_id", "")),
            "stop_condition": str(summary.get("stop_condition", "")),
            "net_first_rules": {
                "stop_if_net_return_lte": 0.0,
                "pause_if_dd_lt": -1.0,
                "pause_if_trade_days_delta_gt": 4.0,
                "pause_if_switch_count_delta_gt": 4.0,
                "pause_if_turnover_pressure_gt": 0.0,
            },
            "deterministic_policy_result": {
                "verdict": str(deterministic["verdict"]),
                "next_action": str(deterministic["next_action"]),
                "verdict_reason": str(deterministic["verdict_reason"]),
            },
            "guardrail_breaches": breaches,
            "compare_metric_count": len(compare_rows),
            "openai_review": openai_review,
        },
    )
    return FamilyVerdict.from_mapping(family_verdict.to_dict())


def _write_critic_error_artifact(
    *,
    writer: ArtifactWriter,
    summary_path: str | Path,
    job_id: str,
    family_id: str,
    critic_config: dict[str, Any],
    effective_openai_source: dict[str, Any] | None,
    error: Exception,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "family_id": family_id,
        "component": "critic",
        "status": "failed_closed",
        "generated_at": utc_now_iso(),
        "summary_path": str(Path(summary_path).resolve()),
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "live_trading": False,
        "source_of_truth_mutation": False,
        "official_promotion_logic": False,
        "error": serialize_openai_error(error),
        "openai_operation": {
            **describe_openai_operation(critic_config),
            "effective_openai_config": dict(critic_config),
            "effective_openai_source": dict(effective_openai_source or {}),
        },
        "notes": [
            "critic_failed_closed",
            "no_family_verdict_emitted",
            "no_governor_transition_allowed",
        ],
    }
    record = writer.write_json(
        f"critic_outputs/{job_id}_family_verdict_error.json",
        payload,
        metadata={"job_id": job_id, "family_id": family_id, "component": "critic"},
    )
    return record.to_dict()


def execute_critic_for_heavy_validation_result(
    summary_path: str | Path,
    artifact_root: str | Path,
    registry: RegistryService,
    critic_job_id: str = "",
    critic_config: dict[str, Any] | None = None,
    runtime_openai_config: dict[str, Any] | None = None,
) -> WorkerResult:
    started_at = utc_now_iso()
    writer = ArtifactWriter(artifact_root)
    family_id = "unknown_family"
    job_id = critic_job_id or "unknown_critic_job"
    verdict_id = f"{job_id}_family_verdict"
    critic_component = dict(critic_config or {})
    critic_enabled = bool(critic_component.get("enabled", True))
    critic_openai_config, effective_openai_source = _resolve_critic_openai_config(
        runtime_openai_config,
        dict(critic_component.get("openai") or {}),
        critic_component,
    )
    try:
        raw_summary = json.loads(Path(summary_path).read_text(encoding="utf-8-sig"))
        job_id = critic_job_id or f"{raw_summary['job_id']}_critic"
        family_id = str(raw_summary.get("family_id", family_id))
        verdict_id = f"{job_id}_family_verdict"
        if not critic_enabled:
            raise ValueError("critic is disabled by config")
        registry.record_family_verdict_event(
            verdict_id=verdict_id,
            job_id=job_id,
            family_id=family_id,
            event_type=CRITIC_STATUS_STARTED,
            event={
                "status": CRITIC_STATUS_STARTED,
                "verdict_id": verdict_id,
                "job_id": job_id,
                "family_id": family_id,
                "summary_path": str(Path(summary_path).resolve()),
                "dev_only": True,
                "non_authoritative": True,
                "official_truth": False,
                "strategy_advancement": False,
            },
        )
        summary, compare_rows, cost_rows, source_artifact, source_paths = load_heavy_validation_result_pack(summary_path)
        verdict = build_family_verdict(
            summary=summary,
            compare_rows=compare_rows,
            cost_rows=cost_rows,
            source_artifact=source_artifact,
            source_paths=source_paths,
            critic_job_id=job_id,
            critic_openai_config=critic_openai_config,
            effective_openai_source=effective_openai_source,
        )
        verdict_record = writer.write_json(
            f"critic_outputs/{job_id}_family_verdict.json",
            verdict.to_dict(),
            metadata={
                "job_id": job_id,
                "request_id": verdict.request_id,
                "result_id": verdict.result_id,
                "family_id": verdict.family_id,
            },
        )
        artifact_refs = [verdict_record.to_dict()]
        registry.record_family_verdict(verdict=verdict, artifact_path=verdict_record.path)
        registry.record_artifact(job_id, verdict_record.to_dict())
        return WorkerResult(
            schema_version=SCHEMA_VERSION,
            job_id=job_id,
            status=JOB_STATUS_SUCCEEDED,
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifact_refs=artifact_refs,
            metrics={"critic_status": CRITIC_STATUS_COMPLETED, "family_verdict": verdict.verdict},
            notes=["critic family verdict completed"],
        )
    except Exception as exc:
        error_record = _write_critic_error_artifact(
            writer=writer,
            summary_path=summary_path,
            job_id=job_id,
            family_id=family_id,
            critic_config=critic_openai_config,
            effective_openai_source=effective_openai_source,
            error=exc,
        )
        registry.record_artifact(job_id, error_record)
        registry.record_family_verdict_event(
            verdict_id=verdict_id,
            job_id=job_id,
            family_id=family_id,
            event_type=CRITIC_STATUS_FAILED,
            event={
                "status": CRITIC_STATUS_FAILED,
                "verdict_id": verdict_id,
                "job_id": job_id,
                "family_id": family_id,
                "summary_path": str(Path(summary_path).resolve()),
                "error": str(exc),
                "dev_only": True,
                "non_authoritative": True,
                "official_truth": False,
                "strategy_advancement": False,
            },
        )
        return WorkerResult(
            schema_version=SCHEMA_VERSION,
            job_id=job_id,
            status=JOB_STATUS_FAILED,
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifact_refs=[error_record],
            metrics={"critic_status": CRITIC_STATUS_FAILED},
            notes=["critic family verdict failed"],
            error=str(exc),
        )


def execute_job(job: WorkerJob, registry: RegistryService | None = None) -> WorkerResult:
    started_at = utc_now_iso()
    writer = ArtifactWriter(job.artifact_root)
    registry = registry or RegistryService(Path(job.artifact_root) / "research_os_mvp.sqlite")
    registry.upsert_job(job)
    registry.update_job_status(job.job_id, JOB_STATUS_RUNNING)
    try:
        validate_safe_job(job)
        artifact_records: list[dict[str, Any]]
        result_note = "placeholder validation completed"
        if job.job_type == JOB_TYPE_PROPOSE_NEXT_MUTATION:
            result_payload = build_mutation_proposal_artifact(job)
            json_record = writer.write_json(
                f"worker_outputs/{job.job_id}_mutation_proposal.json",
                result_payload,
                metadata={"job_id": job.job_id, "job_type": job.job_type},
            )
            registry.record_mutation_proposal(
                job_id=job.job_id,
                proposal=result_payload["proposal"],
                lineage=result_payload["proposal_lineage"],
                status="validated_queue_ready_request_prepared",
            )
            artifact_records = [json_record.to_dict()]
            result_note = "mutation proposal validation completed"
        elif job.job_type == JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB:
            result_payload, artifact_records, result_note = execute_submit_heavy_validation_job(
                job=job,
                writer=writer,
                registry=registry,
            )
        elif job.job_type == JOB_TYPE_ANALYZE_FAMILY_STATE:
            result_payload = build_family_analysis(job)
            json_record = writer.write_json(
                f"worker_outputs/{job.job_id}_family_analysis.json",
                result_payload,
                metadata={"job_id": job.job_id, "job_type": job.job_type},
            )
            csv_record = writer.write_csv(
                f"worker_outputs/{job.job_id}_summary.csv",
                [
                    {
                        "job_id": job.job_id,
                        "job_type": job.job_type,
                        "family_id": job.family_id,
                        "status": "analyzed_family_state",
                    }
                ],
                metadata={"job_id": job.job_id},
            )
            artifact_records = [json_record.to_dict(), csv_record.to_dict()]
            result_note = "family state analysis completed"
        else:
            result_payload = {
                "schema_version": SCHEMA_VERSION,
                "job_id": job.job_id,
                "job_type": job.job_type,
                "family_id": job.family_id,
                "status": "validated_placeholder",
                "metrics": {},
                "notes": [
                    "pc_worker_skeleton_only",
                    "heavy_validation_not_implemented",
                    "no_live_trading_logic",
                ],
            }
            json_record = writer.write_json(
                f"worker_results/{job.job_id}/result.json",
                result_payload,
                metadata={"job_id": job.job_id},
            )
            csv_record = writer.write_csv(
                f"worker_results/{job.job_id}/summary.csv",
                [
                    {
                        "job_id": job.job_id,
                        "job_type": job.job_type,
                        "family_id": job.family_id,
                        "status": "validated_placeholder",
                    }
                ],
                metadata={"job_id": job.job_id},
            )
            artifact_records = [json_record.to_dict(), csv_record.to_dict()]
        result = WorkerResult(
            schema_version=SCHEMA_VERSION,
            job_id=job.job_id,
            status=JOB_STATUS_SUCCEEDED,
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifact_refs=artifact_records,
            metrics={},
            notes=[result_note],
        )
        for artifact_record in artifact_records:
            registry.record_artifact(job.job_id, artifact_record)
        registry.update_job_status(job.job_id, JOB_STATUS_SUCCEEDED, result=result)
        return result
    except Exception as exc:
        result = WorkerResult(
            schema_version=SCHEMA_VERSION,
            job_id=job.job_id,
            status=JOB_STATUS_FAILED,
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifact_refs=[],
            metrics={},
            notes=["safe worker validation failed"],
            error=str(exc),
        )
        registry.update_job_status(job.job_id, JOB_STATUS_FAILED, result=result)
        return result


def consume_once(config_path: str | Path) -> list[WorkerResult]:
    config = load_runtime_config(config_path)
    assert_runtime_startup_ready(config, config_path=config_path, role=config.role)
    queue = build_queue(config.queue_backend, config.redis_url)
    registry = RegistryService(config.registry_path)
    messages = queue.consume(
        stream=config.streams["worker_jobs"],
        group=config.consumer_group,
        consumer=config.consumer_name,
        count=config.max_jobs_per_cycle,
    )
    results: list[WorkerResult] = []
    for message in messages:
        job = WorkerJob.from_mapping(message.payload)
        registry.upsert_job(job)
        result = execute_job(job, registry=registry)
        if result.status == JOB_STATUS_SUCCEEDED:
            queue.ack(message.stream, config.consumer_group, message.message_id)
        results.append(result)
    return results


def consume_heavy_validation_once(config_path: str | Path, queue: JobQueue | None = None) -> list[WorkerResult]:
    config = load_runtime_config(config_path)
    assert_runtime_startup_ready(config, config_path=config_path, role=config.role)
    queue = queue or build_queue(config.queue_backend, config.redis_url)
    registry = RegistryService(config.registry_path)
    message = consume_exactly_one(
        queue=queue,
        stream=config.streams["heavy_validation_jobs"],
        group=config.consumer_group,
        consumer=f"{config.consumer_name}_heavy_validation",
    )
    if message is None:
        return []
    result = execute_heavy_validation_message(
        message=message,
        artifact_root=config.artifact_root,
        registry=registry,
    )
    if result.status == JOB_STATUS_SUCCEEDED:
        queue.ack(message.stream, config.consumer_group, message.message_id)
    return [result]


def run_pc_worker_consumer(
    config_path: str | Path,
    run_once: bool = False,
    idle_sleep_seconds: float = 15.0,
) -> list[WorkerResult]:
    config = load_runtime_config(config_path)
    if config.role != "pc_worker":
        raise ValueError(f"run_pc_worker_consumer requires role=pc_worker, got {config.role}")
    assert_runtime_startup_ready(config, config_path=config_path, role=config.role)
    collected: list[WorkerResult] = []
    while True:
        results = consume_heavy_validation_once(config_path=config_path)
        if results:
            print(json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True), flush=True)
            collected.extend(results)
        if run_once:
            return collected
        if not results:
            time.sleep(max(1.0, idle_sleep_seconds))


def smoke_heavy_validation_once(config_path: str | Path, request_artifact_path: str | Path) -> list[WorkerResult]:
    config = load_runtime_config(config_path)
    request_artifact_path = Path(request_artifact_path).resolve()
    request_artifact, request = load_heavy_validation_request_artifact(request_artifact_path)
    del request_artifact
    queue = build_queue("memory", config.redis_url)
    publish_exactly_one(
        queue=queue,
        stream=config.streams["heavy_validation_jobs"],
        payload={
            "schema_version": SCHEMA_VERSION,
            "message_type": "heavy_validation_request",
            "request_artifact_path": str(request_artifact_path),
            "request": request.to_dict(),
            "source_mutation_proposal": {
                "artifact_path": request.source_mutation_proposal_artifact,
                "proposal_id": request.proposal_id,
            },
        },
    )
    return consume_heavy_validation_once(config_path=config_path, queue=queue)


def pc_health(config_path: str | Path) -> dict[str, Any]:
    config = load_runtime_config(config_path)
    readiness = collect_runtime_readiness(
        config,
        config_path=config_path,
        role=config.role,
        require_root_env=False,
    )
    return {
        "service": "pc_worker",
        "status": "ok" if readiness["ok"] else "degraded",
        "readiness": readiness,
    }


def pc_status(config_path: str | Path) -> dict[str, Any]:
    config = load_runtime_config(config_path)
    registry = RegistryService(config.registry_path)
    return build_service_status(
        service_name="pc_worker",
        role=config.role,
        config=config,
        config_path=config_path,
        registry=registry,
        require_root_env=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PC worker service skeleton")
    parser.add_argument("--config", default="configs/runtime/runtime_config.template.json")
    parser.add_argument("--health", action="store_true", help="Print PC worker runtime readiness checks.")
    parser.add_argument("--status", action="store_true", help="Print PC worker runtime readiness plus registry status.")
    parser.add_argument("--consume-once", action="store_true", help="Consume one batch from configured queue.")
    parser.add_argument(
        "--consume-heavy-validation-once",
        action="store_true",
        help="Consume exactly one heavy-validation queue message and ack only on success.",
    )
    parser.add_argument(
        "--run-pc-worker-consumer",
        action="store_true",
        help="Runtime entrypoint: consume heavy-validation jobs until the process is stopped.",
    )
    parser.add_argument(
        "--pc-worker-consumer-once",
        action="store_true",
        help="With --run-pc-worker-consumer, consume at most one heavy-validation message and exit.",
    )
    parser.add_argument(
        "--idle-sleep-seconds",
        type=float,
        default=15.0,
        help="Idle sleep between empty PC worker consumer polls.",
    )
    parser.add_argument("--job-json", help="Run one local job JSON payload without queue IO.")
    parser.add_argument("--planner-output", help="Run the first job from a planner output JSON without queue IO.")
    parser.add_argument(
        "--mutation-proposal-artifact",
        help="Submit one validated mutation proposal artifact to the heavy-validation queue without running it.",
    )
    parser.add_argument("--submission-id", default="", help="Optional job id for --mutation-proposal-artifact.")
    parser.add_argument(
        "--smoke-heavy-validation-artifact",
        help="Seed one in-memory heavy-validation queue message from an existing request artifact and consume it.",
    )
    parser.add_argument(
        "--critic-heavy-validation-summary",
        help="Run the safe critic path for one completed heavy-validation summary artifact.",
    )
    parser.add_argument("--critic-job-id", default="", help="Optional job id for --critic-heavy-validation-summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.health:
        result = pc_health(args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "ok" else 1
    if args.status:
        result = pc_status(args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "ok" else 1
    if args.run_pc_worker_consumer:
        results = run_pc_worker_consumer(
            config_path=args.config,
            run_once=args.pc_worker_consumer_once,
            idle_sleep_seconds=args.idle_sleep_seconds,
        )
        return 0 if all(result.status == JOB_STATUS_SUCCEEDED for result in results) else 1
    if args.job_json or args.planner_output or args.mutation_proposal_artifact:
        config = load_runtime_config(args.config)
        registry = RegistryService(config.registry_path)
        if args.job_json:
            job_payload = json.loads(Path(args.job_json).read_text(encoding="utf-8-sig"))
        elif args.planner_output:
            planner_output = json.loads(Path(args.planner_output).read_text(encoding="utf-8-sig"))
            jobs = planner_output.get("jobs", [])
            if len(jobs) != 1:
                raise ValueError(f"expected exactly one planner job, got {len(jobs)}")
            job_payload = jobs[0]
        else:
            source_artifact_path = str(Path(args.mutation_proposal_artifact).resolve())
            source_artifact = load_validated_mutation_proposal_artifact(source_artifact_path)
            proposal = MutationProposal.from_mapping(source_artifact["proposal"])
            source_job_id = str(source_artifact.get("job_id", proposal.proposal_id))
            job_id = args.submission_id or f"{source_job_id}_{JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB}"
            job_payload = {
                "schema_version": SCHEMA_VERSION,
                "job_id": job_id,
                "job_type": JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB,
                "family_id": proposal.family_id,
                "priority": 1,
                "payload": {
                    "safe_heavy_validation_submission": True,
                    "validated_mutation_proposal_artifact_path": source_artifact_path,
                    "queue_backend": config.queue_backend,
                    "redis_url": config.redis_url,
                    "heavy_validation_stream": config.streams["heavy_validation_jobs"],
                },
                "artifact_root": config.artifact_root,
                "created_at": utc_now_iso(),
                "constraints": {
                    "dev_only": True,
                    "non_authoritative": True,
                    "live_trading": False,
                    "source_of_truth_mutation": False,
                    "official_promotion_logic": False,
                    "strategy_mutation_execution": False,
                    "single_candidate_only": True,
                },
            }
        job = WorkerJob.from_mapping(job_payload)
        registry.upsert_job(job)
        result = execute_job(job, registry=registry)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.status == JOB_STATUS_SUCCEEDED else 1
    if args.consume_once:
        results = consume_once(args.config)
        print(json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True))
        return 0
    if args.consume_heavy_validation_once:
        results = consume_heavy_validation_once(args.config)
        print(json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True))
        return 0 if all(result.status == JOB_STATUS_SUCCEEDED for result in results) else 1
    if args.smoke_heavy_validation_artifact:
        results = smoke_heavy_validation_once(args.config, args.smoke_heavy_validation_artifact)
        print(json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True))
        return 0 if results and all(result.status == JOB_STATUS_SUCCEEDED for result in results) else 1
    if args.critic_heavy_validation_summary:
        config = load_runtime_config(args.config)
        registry = RegistryService(config.registry_path)
        result = execute_critic_for_heavy_validation_result(
            summary_path=args.critic_heavy_validation_summary,
            artifact_root=config.artifact_root,
            registry=registry,
            critic_job_id=args.critic_job_id,
            critic_config=dict(config.critic),
            runtime_openai_config=dict(config.openai),
        )
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.status == JOB_STATUS_SUCCEEDED else 1
    raise SystemExit("Choose --consume-once, --job-json, or --critic-heavy-validation-summary.")


if __name__ == "__main__":
    raise SystemExit(main())
