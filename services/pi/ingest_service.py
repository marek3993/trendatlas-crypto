from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.pi.environment_scanner import load_runtime_config, scan_environment
from services.pi.job_queue import build_queue
from services.pi.planner_service import build_planner_input, load_family_registry, plan_jobs
from services.pi.registry_service import RegistryService
from services.shared.artifact_writer import ArtifactWriter
from services.shared.schemas import SCHEMA_VERSION, WorkerJob


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_ingest(config_path: str | Path, family_registry_path: str | Path, request_id: str, publish: bool) -> dict[str, object]:
    config = load_runtime_config(config_path)
    family_registry = load_family_registry(family_registry_path)
    registry = RegistryService(config.registry_path)
    writer = ArtifactWriter(config.artifact_root)
    environment_scan = scan_environment(config=config, project_root=PROJECT_ROOT)
    scan_record = writer.write_json(f"planner_inputs/{request_id}_environment_scan.json", environment_scan.to_dict())

    planner_input = build_planner_input(
        request_id=request_id,
        family_registry=family_registry,
        environment_scan=environment_scan.to_dict(),
    )
    planner_input_record = writer.write_json(f"planner_inputs/{request_id}_planner_input.json", planner_input.to_dict())
    planner_output = plan_jobs(planner_input=planner_input, artifact_root=config.artifact_root, openai_config=config.openai)
    planner_output_record = writer.write_json(f"planner_outputs/{request_id}_planner_output.json", planner_output.to_dict())

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
            planner_input_record.to_dict(),
            planner_output_record.to_dict(),
        ],
        "registry_path": str(registry.registry_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pi ingest/orchestrator skeleton")
    parser.add_argument("--config", default="configs/runtime/runtime_config.template.json")
    parser.add_argument("--family-registry", default="configs/families/family_registry.template.json")
    parser.add_argument("--request-id", default="manual_smoke")
    parser.add_argument("--publish", action="store_true", help="Publish jobs to configured queue.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_ingest(
        config_path=args.config,
        family_registry_path=args.family_registry,
        request_id=args.request_id,
        publish=args.publish,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
