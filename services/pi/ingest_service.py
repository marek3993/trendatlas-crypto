from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from services.pi.environment_scanner import build_family_state_snapshot, build_market_state_snapshot, load_runtime_config, scan_environment
from services.pi.job_queue import build_queue
from services.pi.planner_service import build_planner_input, load_family_registry, plan_jobs
from services.pi.registry_service import RegistryService
from services.shared.artifact_writer import ArtifactWriter
from services.shared.runtime_bootstrap import (
    assert_runtime_startup_ready,
    build_service_status,
    collect_runtime_readiness,
    resolve_project_path,
    resolve_project_root,
)
from services.shared.schemas import (
    JOB_STATUS_SUCCEEDED,
    JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB,
    ResearchCycleSummary,
    SCHEMA_VERSION,
    WorkerJob,
    utc_now_iso,
)

def run_ingest(config_path: str | Path, family_registry_path: str | Path, request_id: str, publish: bool) -> dict[str, object]:
    config = load_runtime_config(config_path)
    assert_runtime_startup_ready(config, config_path=config_path, role=config.role)
    project_root = resolve_project_root(require_env=True)
    family_registry = load_family_registry(resolve_project_path(family_registry_path, project_root))
    registry = RegistryService(config.registry_path)
    writer = ArtifactWriter(config.artifact_root)
    environment_scan = scan_environment(config=config, project_root=project_root)
    scan_record = writer.write_json(f"planner_inputs/{request_id}_environment_scan.json", environment_scan.to_dict())
    runtime_writer = ArtifactWriter(config.runtime_root)
    market_state = build_market_state_snapshot(config=config, project_root=project_root)
    family_state = build_family_state_snapshot(config=config, family_registry=family_registry, project_root=project_root)
    market_state_record = runtime_writer.write_json("market_state/latest_market_state.json", market_state.to_dict())
    family_state_record = runtime_writer.write_json("family_state/latest_family_state_snapshot.json", family_state.to_dict())
    registry.upsert_family_state_snapshot(family_state.to_dict())

    planner_input = build_planner_input(
        request_id=request_id,
        family_registry=family_registry,
        environment_scan={
            **environment_scan.to_dict(),
            "market_state_snapshot": {
                "path": market_state_record.path,
                "payload": market_state.to_dict(),
            },
            "family_state_snapshot": {
                "path": family_state_record.path,
                "payload": family_state.to_dict(),
            },
        },
    )
    planner_input_record = writer.write_json(f"planner_inputs/{request_id}_planner_input.json", planner_input.to_dict())
    planner_output = plan_jobs(
        planner_input=planner_input,
        artifact_root=config.artifact_root,
        openai_config=config.openai,
        planner_config=config.planner,
    )
    planner_output_record = writer.write_json(f"planner_outputs/{request_id}_planner_output.json", planner_output.to_dict())
    if planner_output.openai_hook.get("failure_closed", False):
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "publish": False,
            "jobs_planned": 0,
            "queue_ids": [],
            "status": "planner_failed_closed",
            "planner_openai_hook": dict(planner_output.openai_hook),
            "artifact_records": [
                scan_record.to_dict(),
                market_state_record.to_dict(),
                family_state_record.to_dict(),
                planner_input_record.to_dict(),
                planner_output_record.to_dict(),
            ],
            "registry_path": str(registry.registry_path),
        }

    queue_ids: list[str] = []
    if publish:
        queue = build_queue(config.queue_backend, config.redis_url)
        stream = config.streams["worker_jobs"]
        for raw_job in planner_output.jobs:
            job = WorkerJob.from_mapping(raw_job)
            registry.upsert_job(job)
            queue_ids.append(queue.publish(stream, job.to_dict()))
    else:
        for raw_job in planner_output.jobs:
            registry.upsert_job(WorkerJob.from_mapping(raw_job))

    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "publish": publish,
        "jobs_planned": len(planner_output.jobs),
        "queue_ids": queue_ids,
        "artifact_records": [
            scan_record.to_dict(),
            market_state_record.to_dict(),
            family_state_record.to_dict(),
            planner_input_record.to_dict(),
            planner_output_record.to_dict(),
        ],
        "registry_path": str(registry.registry_path),
    }


def _final_governor_states(registry: RegistryService) -> list[dict[str, Any]]:
    states = registry.list_family_governor_states(limit=1000)
    return [
        {
            "family_id": str(state["family_id"]),
            "lifecycle_state": str(state["lifecycle_state"]),
            "status": str(state["status"]),
            "attempt_count": int(state["attempt_count"]),
            "confirmatory_count": int(state["confirmatory_count"]),
            "last_verdict": str(state["last_verdict"]),
            "last_next_action": str(state["last_next_action"]),
            "planning_eligible": bool(state["planning_eligible"]),
        }
        for state in states
    ]


def _artifact_path_by_suffix(result_artifacts: list[dict[str, Any]], suffix: str) -> str:
    for artifact in result_artifacts:
        path = str(artifact.get("path", ""))
        if path.endswith(suffix):
            return path
    return ""


def _artifact_dicts(*records: Any) -> list[dict[str, Any]]:
    artifact_records: list[dict[str, Any]] = []
    for record in records:
        if record is None:
            continue
        if hasattr(record, "to_dict"):
            artifact_records.append(record.to_dict())
        else:
            artifact_records.append(dict(record))
    return artifact_records


def _write_cycle_summary(
    writer: ArtifactWriter,
    registry: RegistryService,
    cycle_id: str,
    started_at: str,
    planner_jobs_count: int,
    executed_steps: list[str],
    family_ids_touched: list[str],
    final_status: str,
    produced_artifacts: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, Any]:
    summary = ResearchCycleSummary(
        schema_version=SCHEMA_VERSION,
        cycle_id=cycle_id,
        started_at=started_at,
        completed_at=utc_now_iso(),
        planner_jobs_count=planner_jobs_count,
        executed_steps=executed_steps,
        family_ids_touched=sorted(set(family_ids_touched)),
        final_status=final_status,
        final_governor_states=_final_governor_states(registry),
        produced_artifacts=list(produced_artifacts),
        errors=errors,
    )
    summary = ResearchCycleSummary.from_mapping(summary.to_dict())
    record = writer.write_json(
        f"cycle_outputs/{cycle_id}_cycle_summary.json",
        summary.to_dict(),
        metadata={"cycle_id": cycle_id, "final_status": final_status},
    )
    registry.record_artifact(cycle_id, record.to_dict())
    return {"summary": summary.to_dict(), "artifact_record": record.to_dict()}


def run_research_cycle(
    config_path: str | Path,
    family_registry_path: str | Path,
    cycle_id: str,
    cycle_overrides: dict[str, Any] | None = None,
    governor_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = utc_now_iso()
    config = load_runtime_config(config_path)
    assert_runtime_startup_ready(config, config_path=config_path, role=config.role)
    project_root = resolve_project_root(require_env=True)
    cycle_config = {**dict(config.research_cycle), **dict(cycle_overrides or {})}
    governor_config = {**dict(config.governor), **dict(governor_overrides or {})}
    family_registry = load_family_registry(resolve_project_path(family_registry_path, project_root))
    registry = RegistryService(config.registry_path)
    writer = ArtifactWriter(config.artifact_root)
    runtime_writer = ArtifactWriter(config.runtime_root)
    executed_steps: list[str] = []
    errors: list[str] = []
    family_ids_touched: list[str] = []
    produced_artifacts: list[dict[str, Any]] = []
    planner_jobs_count = 0
    final_status = "cycle_completed"

    try:
        if int(cycle_config.get("max_planner_jobs", 1)) != 1:
            raise ValueError("run_research_cycle requires max_planner_jobs=1")
        full_pipeline_enabled = bool(cycle_config.get("full_pipeline_enabled", False))
        environment_scan = scan_environment(config=config, project_root=project_root)
        scan_record = writer.write_json(f"planner_inputs/{cycle_id}_environment_scan.json", environment_scan.to_dict())
        produced_artifacts.extend(_artifact_dicts(scan_record))
        executed_steps.append("environment_scan")

        market_state = build_market_state_snapshot(config=config, project_root=project_root)
        market_state_record = runtime_writer.write_json("market_state/latest_market_state.json", market_state.to_dict())
        produced_artifacts.extend(_artifact_dicts(market_state_record))
        executed_steps.append("market_snapshot")

        family_state = build_family_state_snapshot(config=config, family_registry=family_registry, project_root=project_root)
        family_state_record = runtime_writer.write_json("family_state/latest_family_state_snapshot.json", family_state.to_dict())
        produced_artifacts.extend(_artifact_dicts(family_state_record))
        registry.upsert_family_state_snapshot(family_state.to_dict())
        executed_steps.append("family_snapshot")

        planner_input = build_planner_input(
            request_id=cycle_id,
            family_registry=family_registry,
            environment_scan={
                **environment_scan.to_dict(),
                "market_state_snapshot": {
                    "path": market_state_record.path,
                    "payload": market_state.to_dict(),
                },
                "family_state_snapshot": {
                    "path": family_state_record.path,
                    "payload": family_state.to_dict(),
                },
            },
        )
        planner_input_record = writer.write_json(f"planner_inputs/{cycle_id}_planner_input.json", planner_input.to_dict())
        produced_artifacts.extend(_artifact_dicts(planner_input_record))
        planner_output = plan_jobs(
            planner_input=planner_input,
            artifact_root=config.artifact_root,
            openai_config=config.openai,
            planner_config=config.planner,
            governor_config=governor_config,
        )
        planner_jobs_count = len(planner_output.jobs)
        if planner_jobs_count > 1:
            raise ValueError(f"run_research_cycle expected one planner job max, got {planner_jobs_count}")
        planner_output_record = writer.write_json(f"planner_outputs/{cycle_id}_planner_output.json", planner_output.to_dict())
        produced_artifacts.extend(_artifact_dicts(planner_output_record))
        for artifact_record in (scan_record, market_state_record, family_state_record, planner_input_record, planner_output_record):
            registry.record_artifact(cycle_id, artifact_record.to_dict())
        executed_steps.append("planner")
        if planner_output.openai_hook.get("failure_closed", False):
            raise RuntimeError(str(planner_output.openai_hook.get("error_message", "planner failed closed")))

        if planner_jobs_count == 0:
            final_status = "completed_no_planner_jobs"
            result = _write_cycle_summary(
                writer=writer,
                registry=registry,
                cycle_id=cycle_id,
                started_at=started_at,
                planner_jobs_count=planner_jobs_count,
                executed_steps=executed_steps,
                family_ids_touched=family_ids_touched,
                final_status=final_status,
                produced_artifacts=produced_artifacts,
                errors=errors,
            )
            return {
                "schema_version": SCHEMA_VERSION,
                "cycle_id": cycle_id,
                "final_status": final_status,
                "summary_artifact": result["artifact_record"],
                "summary": result["summary"],
            }

        job = WorkerJob.from_mapping(planner_output.jobs[0])
        family_ids_touched.append(job.family_id)
        registry.upsert_job(job)
        executed_steps.append("planner_job_registered")

        proposal_artifact_path = ""
        heavy_request_artifact_path = ""
        heavy_summary_path = ""
        critic_artifact_path = ""
        if full_pipeline_enabled or bool(cycle_config.get("handle_worker_proposal", False)):
            from services.pc.worker_service import execute_job

            worker_result = execute_job(job, registry=registry)
            executed_steps.append("worker_proposal")
            if worker_result.status != JOB_STATUS_SUCCEEDED:
                raise RuntimeError(worker_result.error or "worker proposal handling failed")
            produced_artifacts.extend(worker_result.artifact_refs)
            proposal_artifact_path = _artifact_path_by_suffix(worker_result.artifact_refs, "_mutation_proposal.json")

        if full_pipeline_enabled or bool(cycle_config.get("submit_heavy_validation", False)):
            if not proposal_artifact_path:
                raise ValueError("submit_heavy_validation requires worker proposal artifact")
            from services.pc.worker_service import execute_job, load_validated_mutation_proposal_artifact
            from services.shared.schemas import MutationProposal

            source_artifact = load_validated_mutation_proposal_artifact(proposal_artifact_path)
            proposal = MutationProposal.from_mapping(source_artifact["proposal"])
            submit_job = WorkerJob(
                schema_version=SCHEMA_VERSION,
                job_id=f"{cycle_id}_{job.family_id}_{JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB}",
                job_type=JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB,
                family_id=proposal.family_id,
                priority=job.priority,
                payload={
                    "safe_heavy_validation_submission": True,
                    "validated_mutation_proposal_artifact_path": proposal_artifact_path,
                    "queue_backend": config.queue_backend,
                    "redis_url": config.redis_url,
                    "heavy_validation_stream": config.streams["heavy_validation_jobs"],
                },
                artifact_root=config.artifact_root,
                created_at=utc_now_iso(),
                constraints={
                    "dev_only": True,
                    "non_authoritative": True,
                    "live_trading": False,
                    "source_of_truth_mutation": False,
                    "official_promotion_logic": False,
                    "strategy_mutation_execution": False,
                    "single_candidate_only": True,
                },
            )
            submit_result = execute_job(submit_job, registry=registry)
            executed_steps.append("heavy_validation_submission")
            if submit_result.status != JOB_STATUS_SUCCEEDED:
                raise RuntimeError(submit_result.error or "heavy validation submission failed")
            produced_artifacts.extend(submit_result.artifact_refs)
            heavy_request_artifact_path = _artifact_path_by_suffix(submit_result.artifact_refs, "_heavy_validation_request.json")

        if full_pipeline_enabled or bool(cycle_config.get("run_heavy_validation_adapter", False)):
            if not heavy_request_artifact_path:
                raise ValueError("run_heavy_validation_adapter requires heavy validation request artifact")
            from services.pc.worker_service import smoke_heavy_validation_once

            heavy_results = smoke_heavy_validation_once(config_path=config_path, request_artifact_path=heavy_request_artifact_path)
            executed_steps.append("heavy_validation_adapter")
            if not heavy_results or any(result.status != JOB_STATUS_SUCCEEDED for result in heavy_results):
                raise RuntimeError("heavy validation adapter failed")
            produced_artifacts.extend(heavy_results[0].artifact_refs)
            heavy_summary_path = _artifact_path_by_suffix(heavy_results[0].artifact_refs, "_summary.json")

        if full_pipeline_enabled or bool(cycle_config.get("run_critic", False)):
            if not heavy_summary_path:
                raise ValueError("run_critic requires heavy validation summary artifact")
            from services.pc.worker_service import execute_critic_for_heavy_validation_result

            critic_result = execute_critic_for_heavy_validation_result(
                summary_path=heavy_summary_path,
                artifact_root=config.artifact_root,
                registry=registry,
                critic_job_id=f"{cycle_id}_{job.family_id}_critic",
                critic_config=dict(config.critic),
                runtime_openai_config=dict(config.openai),
            )
            executed_steps.append("critic")
            if critic_result.status != JOB_STATUS_SUCCEEDED:
                raise RuntimeError(critic_result.error or "critic failed")
            produced_artifacts.extend(critic_result.artifact_refs)
            critic_artifact_path = _artifact_path_by_suffix(critic_result.artifact_refs, "_family_verdict.json")

        if full_pipeline_enabled or bool(cycle_config.get("run_governor", False)):
            if not critic_artifact_path:
                raise ValueError("run_governor requires critic verdict artifact")
            from services.pi.planner_service import execute_family_governor

            governor_result = execute_family_governor(
                verdict_artifact_path=critic_artifact_path,
                artifact_root=config.artifact_root,
                registry=registry,
                governor_job_id=f"{cycle_id}_{job.family_id}_governor",
            )
            executed_steps.append("governor")
            if governor_result["status"] != "governor_completed":
                raise RuntimeError(str(governor_result.get("error", "governor failed")))
            produced_artifacts.extend(_artifact_dicts(*governor_result.get("artifact_refs", [])))

    except Exception as exc:
        final_status = "cycle_failed"
        errors.append(str(exc))

    result = _write_cycle_summary(
        writer=writer,
        registry=registry,
        cycle_id=cycle_id,
        started_at=started_at,
        planner_jobs_count=planner_jobs_count,
        executed_steps=executed_steps,
        family_ids_touched=family_ids_touched,
        final_status=final_status,
        produced_artifacts=produced_artifacts,
        errors=errors,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "final_status": final_status,
        "summary_artifact": result["artifact_record"],
        "summary": result["summary"],
    }


def _runtime_cycle_id(prefix: str) -> str:
    stamp = utc_now_iso().replace("-", "").replace(":", "").split("+", maxsplit=1)[0]
    return f"{prefix}_{stamp}Z"


def run_pi_orchestrator_cycle(
    config_path: str | Path,
    family_registry_path: str | Path,
    cycle_id: str = "",
    full_pipeline: bool = False,
    allow_governor_override: bool = False,
) -> dict[str, Any]:
    config = load_runtime_config(config_path)
    if config.role != "pi_orchestrator":
        raise ValueError(f"run_pi_orchestrator_cycle requires role=pi_orchestrator, got {config.role}")
    return run_research_cycle(
        config_path=config_path,
        family_registry_path=family_registry_path,
        cycle_id=cycle_id or _runtime_cycle_id("pi_orchestrator_cycle"),
        cycle_overrides={"full_pipeline_enabled": True} if full_pipeline else None,
        governor_overrides=(
            {"allow_paused_stopped_family_planning_override": True}
            if allow_governor_override
            else None
        ),
    )


def pi_health(config_path: str | Path) -> dict[str, Any]:
    config = load_runtime_config(config_path)
    readiness = collect_runtime_readiness(
        config,
        config_path=config_path,
        role=config.role,
        require_root_env=False,
    )
    return {
        "service": "pi_orchestrator",
        "status": "ok" if readiness["ok"] else "degraded",
        "readiness": readiness,
    }


def pi_status(config_path: str | Path) -> dict[str, Any]:
    config = load_runtime_config(config_path)
    registry = RegistryService(config.registry_path)
    return build_service_status(
        service_name="pi_orchestrator",
        role=config.role,
        config=config,
        config_path=config_path,
        registry=registry,
        require_root_env=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pi ingest/orchestrator skeleton")
    parser.add_argument("--config", default="configs/runtime/runtime_config.template.json")
    parser.add_argument("--family-registry", default="configs/families/family_registry.template.json")
    parser.add_argument("--request-id", default="manual_smoke")
    parser.add_argument("--health", action="store_true", help="Print Pi runtime readiness checks.")
    parser.add_argument("--status", action="store_true", help="Print Pi runtime readiness plus registry status.")
    parser.add_argument("--publish", action="store_true", help="Publish jobs to configured queue.")
    parser.add_argument("--run-research-cycle", action="store_true", help="Run one dev-only research cycle.")
    parser.add_argument("--run-pi-orchestrator-cycle", action="store_true", help="Runtime entrypoint: run one Pi orchestrator cycle.")
    parser.add_argument("--cycle-id", default="", help="Optional cycle id for --run-research-cycle.")
    parser.add_argument("--full-pipeline", action="store_true", help="Enable the config-gated full pipeline mode for this run.")
    parser.add_argument(
        "--allow-governor-override",
        action="store_true",
        help="Allow paused/stopped family planning for this run when the governor gate would otherwise block it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.health:
        result = pi_health(args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "ok" else 1
    if args.status:
        result = pi_status(args.config)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "ok" else 1
    if args.run_pi_orchestrator_cycle:
        result = run_pi_orchestrator_cycle(
            config_path=args.config,
            family_registry_path=args.family_registry,
            cycle_id=args.cycle_id,
            full_pipeline=args.full_pipeline,
            allow_governor_override=args.allow_governor_override,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["final_status"] != "cycle_failed" else 1
    if args.run_research_cycle:
        result = run_research_cycle(
            config_path=args.config,
            family_registry_path=args.family_registry,
            cycle_id=args.cycle_id or args.request_id,
            cycle_overrides={"full_pipeline_enabled": True} if args.full_pipeline else None,
            governor_overrides=(
                {"allow_paused_stopped_family_planning_override": True}
                if args.allow_governor_override
                else None
            ),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["final_status"] != "cycle_failed" else 1
    result = run_ingest(
        config_path=args.config,
        family_registry_path=args.family_registry,
        request_id=args.request_id,
        publish=args.publish,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if str(result.get("status", "")) == "planner_failed_closed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
