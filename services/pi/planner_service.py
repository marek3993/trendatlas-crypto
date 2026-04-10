from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from services.shared.schemas import FamilyRegistry, PlannerInput, PlannerOutput, SCHEMA_VERSION, WorkerJob, utc_now_iso


class ResponsesAPIHook:
    """Prepared OpenAI Responses API hook; intentionally does not call the network."""

    def __init__(self, enabled: bool, model: str, prompt_template: str) -> None:
        self.enabled = enabled
        self.model = model
        self.prompt_template = prompt_template

    def describe(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "prompt_template": self.prompt_template,
            "network_call": "disabled_in_mvp",
        }


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


def plan_jobs(planner_input: PlannerInput, artifact_root: str, openai_config: dict[str, Any]) -> PlannerOutput:
    registry = FamilyRegistry.from_mapping(planner_input.family_registry)
    hook = ResponsesAPIHook(
        enabled=bool(openai_config.get("enabled", False)),
        model=str(openai_config.get("model", "placeholder")),
        prompt_template=str(openai_config.get("prompt_template", "research_os_planner_placeholder")),
    )
    jobs: list[dict[str, Any]] = []
    for family in registry.families:
        if family.status != "enabled":
            continue
        job_type = family.allowed_job_types[0] if family.allowed_job_types else "validation_placeholder"
        job = WorkerJob(
            schema_version=SCHEMA_VERSION,
            job_id=f"{planner_input.request_id}_{family.family_id}_validation_placeholder",
            job_type=job_type,
            family_id=family.family_id,
            priority=family.default_priority,
            payload={
                "planner_request_id": planner_input.request_id,
                "description": family.description,
                "safe_placeholder": True,
                "strategy_logic": "not_implemented",
            },
            artifact_root=artifact_root,
            created_at=utc_now_iso(),
            constraints={
                **family.constraints,
                "live_trading": False,
                "source_of_truth_mutation": False,
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
            "deterministic_placeholder_plan",
            "openai_responses_api_hook_prepared_without_network_call",
        ],
        openai_hook=hook.describe(),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pi planner service skeleton")
    parser.add_argument("--family-registry", default="configs/families/family_registry.template.json")
    parser.add_argument("--environment-scan", required=True)
    parser.add_argument("--artifact-root", default="outputs/research_os/dev_only/mvp/artifacts")
    parser.add_argument("--request-id", default="manual_smoke")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_family_registry(args.family_registry)
    scan = json.loads(Path(args.environment_scan).read_text(encoding="utf-8"))
    planner_input = build_planner_input(args.request_id, registry, scan)
    output = plan_jobs(
        planner_input=planner_input,
        artifact_root=args.artifact_root,
        openai_config={"enabled": False, "model": "placeholder", "prompt_template": "manual_smoke"},
    )
    print(json.dumps(output.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
