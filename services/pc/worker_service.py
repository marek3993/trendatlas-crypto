from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from services.pi.environment_scanner import load_runtime_config
from services.pi.job_queue import build_queue
from services.pi.registry_service import RegistryService
from services.shared.artifact_writer import ArtifactWriter
from services.shared.schemas import (
    JOB_STATUS_FAILED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    SCHEMA_VERSION,
    WorkerJob,
    WorkerResult,
    utc_now_iso,
)


def validate_placeholder_job(job: WorkerJob) -> None:
    if job.constraints.get("live_trading") is not False:
        raise ValueError("worker refuses jobs without live_trading=false")
    if job.constraints.get("source_of_truth_mutation") is not False:
        raise ValueError("worker refuses jobs without source_of_truth_mutation=false")
    if not job.payload.get("safe_placeholder", False):
        raise ValueError("worker MVP only accepts safe placeholder jobs")


def execute_job(job: WorkerJob, registry: RegistryService | None = None) -> WorkerResult:
    started_at = utc_now_iso()
    writer = ArtifactWriter(job.artifact_root)
    registry = registry or RegistryService(Path(job.artifact_root) / "research_os_mvp.sqlite")
    registry.upsert_job(job)
    registry.update_job_status(job.job_id, JOB_STATUS_RUNNING)
    try:
        validate_placeholder_job(job)
        result_payload: dict[str, Any] = {
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
        result = WorkerResult(
            schema_version=SCHEMA_VERSION,
            job_id=job.job_id,
            status=JOB_STATUS_SUCCEEDED,
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifact_refs=[json_record.to_dict(), csv_record.to_dict()],
            metrics={},
            notes=["placeholder validation completed"],
        )
        registry.record_artifact(job.job_id, json_record.to_dict())
        registry.record_artifact(job.job_id, csv_record.to_dict())
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
            notes=["placeholder validation failed"],
            error=str(exc),
        )
        registry.update_job_status(job.job_id, JOB_STATUS_FAILED, result=result)
        return result


def consume_once(config_path: str | Path) -> list[WorkerResult]:
    config = load_runtime_config(config_path)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PC worker service skeleton")
    parser.add_argument("--config", default="configs/runtime/runtime_config.template.json")
    parser.add_argument("--consume-once", action="store_true", help="Consume one batch from configured queue.")
    parser.add_argument("--job-json", help="Run one local job JSON payload without queue IO.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.job_json:
        config = load_runtime_config(args.config)
        registry = RegistryService(config.registry_path)
        job = WorkerJob.from_mapping(json.loads(Path(args.job_json).read_text(encoding="utf-8-sig")))
        registry.upsert_job(job)
        result = execute_job(job, registry=registry)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.status == JOB_STATUS_SUCCEEDED else 1
    if args.consume_once:
        results = consume_once(args.config)
        print(json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True))
        return 0
    raise SystemExit("Choose --consume-once or --job-json.")


if __name__ == "__main__":
    raise SystemExit(main())
