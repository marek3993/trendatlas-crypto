from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"

REQUIRED_DIRS = [
    RESEARCH_OS_ROOT,
    RESEARCH_OS_ROOT / "leaderboards",
    RESEARCH_OS_ROOT / "runs",
    RESEARCH_OS_ROOT / "runs" / "templates",
    RESEARCH_OS_ROOT / "experiment_specs",
    RESEARCH_OS_ROOT / "experiment_specs" / "templates",
    RESEARCH_OS_ROOT / "promotion_queue",
    RESEARCH_OS_ROOT / "promotion_queue" / "templates",
    RESEARCH_OS_ROOT / "archives",
    RESEARCH_OS_ROOT / "single_truth",
    RESEARCH_OS_ROOT / "schemas",
    RESEARCH_OS_ROOT / "docs",
]

TRUTH_PACK_PATH = RESEARCH_OS_ROOT / "single_truth" / "truth_pack.json"
ROOT_MANIFEST_PATH = RESEARCH_OS_ROOT / "research_os_manifest.json"
SCHEMA_INDEX_PATH = RESEARCH_OS_ROOT / "schemas" / "schema_index.json"

EXPERIMENT_SPEC_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "experiment_spec.schema.json"
CANDIDATE_LIFECYCLE_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "candidate_lifecycle.schema.json"
PROMOTION_DECISION_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "promotion_decision.schema.json"

EXPERIMENT_SPEC_TEMPLATE_PATH = RESEARCH_OS_ROOT / "experiment_specs" / "templates" / "experiment_spec.template.json"
RUN_STATUS_TEMPLATE_PATH = RESEARCH_OS_ROOT / "runs" / "templates" / "run_status.template.json"
PROMOTION_DECISION_TEMPLATE_PATH = RESEARCH_OS_ROOT / "promotion_queue" / "templates" / "promotion_decision.template.json"

RUN_FOLDER_CONTRACT_PATH = RESEARCH_OS_ROOT / "runs" / "templates" / "run_folder_contract.json"
CONTRACT_DOC_PATH = RESEARCH_OS_ROOT / "docs" / "research_os_v2_contract.md"

REQUIRED_LIFECYCLE_STATUSES = [
    "proposed",
    "spec_ready",
    "queued",
    "running",
    "run_failed",
    "ran",
    "scored",
    "precheck_failed",
    "precheck_passed",
    "forensic_ready",
    "forensic_failed",
    "forensic_passed",
    "master_pending",
    "promoted",
    "archived",
]

REQUIRED_PROMOTION_DECISIONS = [
    "kill",
    "hold",
    "rerun",
    "promote_to_precheck",
    "promote_to_forensic",
    "promote_to_master",
    "promote_to_official",
]

EXPERIMENT_SPEC_REQUIRED_FIELDS = [
    "experiment_id",
    "branch",
    "segment_owner",
    "hypothesis_label",
    "experiment_family",
    "baseline_model",
    "baseline_paper_path",
    "input_paths",
    "script_path",
    "script_args",
    "expected_outputs",
    "scoring_profile",
    "promotion_rule",
    "invalidation_rule",
    "budget_class",
    "priority",
    "created_by",
    "created_at",
    "status",
]

REQUIRED_RUN_ARTIFACTS = [
    "run_manifest.json",
    "run_status.json",
    "stdout.log",
    "stderr.log",
    "artifacts_index.json",
    "quality_report.json",
    "precheck_inputs.json",
]

OPTIONAL_RUN_ARTIFACTS = [
    "summary.csv",
    "paper.csv",
    "compare.csv",
    "summary.json",
    "metrics.json",
    "promotion_decision.json",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def local_now_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


@dataclass
class SavedArtifact:
    kind: str
    path: str
    size_bytes: int


class Runtime:
    def __init__(self, script_name: str) -> None:
        self.script_name = script_name
        self.started = time.monotonic()
        self.saved: List[SavedArtifact] = []
        self.counters: Dict[str, Any] = {}

    def log(self, message: str) -> None:
        print(f"[{local_now_iso()}] [{self.script_name}] {message}", flush=True)

    def set_counter(self, key: str, value: Any) -> None:
        self.counters[key] = value
        self.log(f"{key}={value}")

    def require_dir(self, path: Path, label: str) -> None:
        self.log(f"CHECK dir {label}: {path}")
        if not path.exists() or not path.is_dir():
            raise RuntimeError(f"missing required directory: {path}")
        self.log(f"OK dir {label}")

    def require_file(self, path: Path, label: str) -> None:
        self.log(f"CHECK file {label}: {path}")
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"missing required file: {path}")
        self.log(f"OK file {label}: size_bytes={path.stat().st_size}")

    def save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.saved.append(SavedArtifact("json", str(path), path.stat().st_size))
        self.log(f"SAVED kind=json path={path} size_bytes={path.stat().st_size}")

    def save_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.saved.append(SavedArtifact("txt", str(path), path.stat().st_size))
        self.log(f"SAVED kind=txt path={path} size_bytes={path.stat().st_size}")

    def finish(self) -> None:
        elapsed = time.monotonic() - self.started
        self.log(f"END status=OK elapsed_sec={elapsed:.3f}")
        self.log(f"SUMMARY saved_files_count={len(self.saved)}")
        for k, v in self.counters.items():
            self.log(f"SUMMARY {k}={v}")
        for i, item in enumerate(self.saved, start=1):
            self.log(f"SAVED_FILE[{i}] kind={item.kind} path={item.path} size_bytes={item.size_bytes}")


EXPERIMENT_SPEC_SCHEMA = {
    "schema_version": "2.0",
    "entity": "experiment_spec",
    "required_fields": EXPERIMENT_SPEC_REQUIRED_FIELDS,
    "allowed_status_values": REQUIRED_LIFECYCLE_STATUSES,
    "field_contract": {
        "experiment_id": {"type": "string", "example": "phase70_ai_lab_guardrail_sweep"},
        "branch": {"type": "string", "example": "main"},
        "segment_owner": {"type": "string", "example": "ai_lab"},
        "hypothesis_label": {"type": "string", "example": "guardrail_repair_2025"},
        "experiment_family": {"type": "string", "example": "guardrail_sweep"},
        "baseline_model": {"type": "string", "example": "phase66g_production_soft_filters"},
        "baseline_paper_path": {"type": "string", "example": r"C:\Users\benda\Desktop\market_regime_v1\outputs\phase66g_production_candidate_live\phase66g_production_soft_filters_paper.csv"},
        "input_paths": {"type": "list[str]"},
        "script_path": {"type": "string", "example": r"C:\Users\benda\Desktop\market_regime_v1\scripts\phase66h_core_regime_guardrail_sweep.py"},
        "script_args": {"type": "list[str]"},
        "expected_outputs": {"type": "list[str]"},
        "scoring_profile": {"type": "string", "example": "production_guardrail_score_v1"},
        "promotion_rule": {"type": "string", "example": "if_scored_and_precheck_passed_then_promote_to_forensic"},
        "invalidation_rule": {"type": "string", "example": "kill_if_manifest_missing_or_quality_failed"},
        "budget_class": {"type": "string", "allowed_values": ["tiny", "small", "medium", "large"]},
        "priority": {"type": "string", "allowed_values": ["low", "normal", "high", "critical"]},
        "created_by": {"type": "string", "example": "ai_lab"},
        "created_at": {"type": "string", "format": "YYYY-MM-DD HH:MM:SS UTC"},
        "status": {"type": "string", "allowed_values": REQUIRED_LIFECYCLE_STATUSES},
    },
    "strict_rules": {
        "allow_unknown_top_level_fields": False,
        "allow_custom_status_values": False,
        "allow_empty_input_paths": False,
        "allow_empty_expected_outputs": False,
    },
}

CANDIDATE_LIFECYCLE_SCHEMA = {
    "schema_version": "2.0",
    "entity": "candidate_lifecycle",
    "id_field": "candidate_id",
    "required_statuses": REQUIRED_LIFECYCLE_STATUSES,
    "strict_rules": {
        "allow_custom_status_values": False,
        "allow_unknown_status_transitions": False,
    },
    "allowed_transitions": {
        "proposed": ["spec_ready", "archived"],
        "spec_ready": ["queued", "archived"],
        "queued": ["running", "archived"],
        "running": ["run_failed", "ran", "archived"],
        "run_failed": ["queued", "archived"],
        "ran": ["scored", "archived"],
        "scored": ["precheck_failed", "precheck_passed", "archived"],
        "precheck_failed": ["queued", "archived"],
        "precheck_passed": ["forensic_ready", "archived"],
        "forensic_ready": ["forensic_failed", "forensic_passed", "archived"],
        "forensic_failed": ["queued", "archived"],
        "forensic_passed": ["master_pending", "archived"],
        "master_pending": ["promoted", "archived"],
        "promoted": ["archived"],
        "archived": [],
    },
}

PROMOTION_DECISION_SCHEMA = {
    "schema_version": "2.0",
    "entity": "promotion_decision",
    "required_fields": [
        "decision_id",
        "candidate_id",
        "source_run_id",
        "decision",
        "decision_reason",
        "decided_by",
        "decided_at",
        "evidence_refs",
    ],
    "allowed_decision_values": REQUIRED_PROMOTION_DECISIONS,
    "strict_rules": {
        "allow_custom_decision_values": False,
        "allow_unknown_top_level_fields": False,
    },
}

EXPERIMENT_SPEC_TEMPLATE = {
    "experiment_id": "phase70_ai_lab_example",
    "branch": "main",
    "segment_owner": "ai_lab",
    "hypothesis_label": "example_hypothesis",
    "experiment_family": "registry_contract_test",
    "baseline_model": "phase66g_production_soft_filters",
    "baseline_paper_path": r"C:\Users\benda\Desktop\market_regime_v1\outputs\phase66g_production_candidate_live\phase66g_production_soft_filters_paper.csv",
    "input_paths": [
        r"C:\Users\benda\Desktop\market_regime_v1\outputs\phase66g_production_candidate_live\phase66g_production_soft_filters_paper.csv"
    ],
    "script_path": r"C:\Users\benda\Desktop\market_regime_v1\scripts\phase70_ai_lab_example.py",
    "script_args": [
        "--mode",
        "example",
    ],
    "expected_outputs": [
        "summary.csv",
        "paper.csv",
        "compare.csv",
        "run_manifest.json",
        "quality_report.json",
    ],
    "scoring_profile": "production_guardrail_score_v1",
    "promotion_rule": "promote_to_precheck_if_primary_score_beats_baseline_and_required_outputs_exist",
    "invalidation_rule": "kill_if_required_outputs_missing_or_quality_failed",
    "budget_class": "small",
    "priority": "normal",
    "created_by": "ai_lab",
    "created_at": utc_now_iso(),
    "status": "proposed",
}

RUN_STATUS_TEMPLATE = {
    "schema_version": "2.0",
    "run_id": "run_example_0001",
    "experiment_id": "phase70_ai_lab_example",
    "candidate_id": "candidate_example",
    "status": "queued",
    "allowed_status_values": REQUIRED_LIFECYCLE_STATUSES,
    "started_at": None,
    "ended_at": None,
    "status_reason": None,
    "current_step": "waiting_for_execution",
    "promotion_decision": None,
    "updated_at": utc_now_iso(),
}

PROMOTION_DECISION_TEMPLATE = {
    "decision_id": "decision_example_0001",
    "candidate_id": "candidate_example",
    "source_run_id": "run_example_0001",
    "decision": "hold",
    "decision_reason": "Awaiting precheck/forensic evidence.",
    "decided_by": "ai_lab",
    "decided_at": utc_now_iso(),
    "evidence_refs": [],
}

RUN_FOLDER_CONTRACT = {
    "schema_version": "2.0",
    "required_run_artifacts": REQUIRED_RUN_ARTIFACTS,
    "conditional_artifacts": {
        "when_applicable": [
            "summary.csv",
            "paper.csv",
            "compare.csv",
        ]
    },
    "notes": "Každý run folder pod research_os/runs/<run_id>/ musí obsahovať required artifacts. conditional artifacts sú povinné keď ich experiment family očakáva.",
}

CONTRACT_DOC = """# Research OS v2 Contract

## Required fields

### experiment_spec.template.json
Required fields:
- experiment_id
- branch
- segment_owner
- hypothesis_label
- experiment_family
- baseline_model
- baseline_paper_path
- input_paths
- script_path
- script_args
- expected_outputs
- scoring_profile
- promotion_rule
- invalidation_rule
- budget_class
- priority
- created_by
- created_at
- status

### promotion_decision.template.json
Required fields:
- decision_id
- candidate_id
- source_run_id
- decision
- decision_reason
- decided_by
- decided_at
- evidence_refs

### run_status.template.json
Required fields:
- schema_version
- run_id
- experiment_id
- candidate_id
- status
- allowed_status_values
- started_at
- ended_at
- status_reason
- current_step
- promotion_decision
- updated_at

## Allowed status values

Strict allowed lifecycle statuses:
- proposed
- spec_ready
- queued
- running
- run_failed
- ran
- scored
- precheck_failed
- precheck_passed
- forensic_ready
- forensic_failed
- forensic_passed
- master_pending
- promoted
- archived

No custom statuses allowed.

## Required run artifacts

Every run folder under `research_os/runs/<run_id>/` must contain:
- run_manifest.json
- run_status.json
- stdout.log
- stderr.log
- artifacts_index.json
- quality_report.json
- precheck_inputs.json

Plus summary/paper/compare artifacts when applicable:
- summary.csv
- paper.csv
- compare.csv

## Promotion decision types

Strict allowed decisions:
- kill
- hold
- rerun
- promote_to_precheck
- promote_to_forensic
- promote_to_master
- promote_to_official

No custom promotion decisions allowed.

## Naming conventions

- experiment_id: lowercase snake_case or phase-style identifier, e.g. `phase70_ai_lab_example`
- run_id: deterministic unique ID per run, e.g. `run_20260330_0001`
- decision_id: deterministic unique ID per decision, e.g. `decision_20260330_0001`
- all JSON templates/schemas live under `research_os/` only
- no broad autodiscovery for contracts
- orchestrator must use strict file paths from manifests/contracts
"""


def build_schema_index() -> Dict[str, Any]:
    return {
        "schema_version": "2.0",
        "updated_at": utc_now_iso(),
        "schemas": {
            "experiment_spec": str(EXPERIMENT_SPEC_SCHEMA_PATH),
            "candidate_lifecycle": str(CANDIDATE_LIFECYCLE_SCHEMA_PATH),
            "promotion_decision": str(PROMOTION_DECISION_SCHEMA_PATH),
            "run_folder_contract": str(RUN_FOLDER_CONTRACT_PATH),
        },
        "templates": {
            "experiment_spec": str(EXPERIMENT_SPEC_TEMPLATE_PATH),
            "run_status": str(RUN_STATUS_TEMPLATE_PATH),
            "promotion_decision": str(PROMOTION_DECISION_TEMPLATE_PATH),
        },
        "docs": {
            "research_os_v2_contract": str(CONTRACT_DOC_PATH),
        },
    }


def ensure_dirs(rt: Runtime) -> None:
    created = 0
    for path in REQUIRED_DIRS:
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        rt.log(f"ENSURE dir path={path} existed={existed}")
        if not existed:
            created += 1
    rt.set_counter("dirs_total", len(REQUIRED_DIRS))
    rt.set_counter("dirs_created", created)


def update_truth_pack(rt: Runtime) -> None:
    rt.require_file(TRUTH_PACK_PATH, "truth_pack")
    payload = json.loads(TRUTH_PACK_PATH.read_text(encoding="utf-8"))
    payload["registry_extensions"] = {
        "experiment_spec_schema": str(EXPERIMENT_SPEC_SCHEMA_PATH),
        "candidate_lifecycle_schema": str(CANDIDATE_LIFECYCLE_SCHEMA_PATH),
        "promotion_decision_schema": str(PROMOTION_DECISION_SCHEMA_PATH),
        "experiment_spec_template": str(EXPERIMENT_SPEC_TEMPLATE_PATH),
        "run_status_template": str(RUN_STATUS_TEMPLATE_PATH),
        "promotion_decision_template": str(PROMOTION_DECISION_TEMPLATE_PATH),
        "run_folder_contract": str(RUN_FOLDER_CONTRACT_PATH),
        "research_os_v2_contract_doc": str(CONTRACT_DOC_PATH),
    }
    payload["updated_utc"] = utc_now_iso()
    rt.save_json(TRUTH_PACK_PATH, payload)


def update_root_manifest(rt: Runtime) -> None:
    rt.require_file(ROOT_MANIFEST_PATH, "research_os_manifest")
    payload = json.loads(ROOT_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["updated_utc"] = utc_now_iso()
    payload["v2_contract_pack"] = {
        "schema_index": str(SCHEMA_INDEX_PATH),
        "doc_path": str(CONTRACT_DOC_PATH),
        "required_lifecycle_statuses": REQUIRED_LIFECYCLE_STATUSES,
        "required_promotion_decisions": REQUIRED_PROMOTION_DECISIONS,
        "required_run_artifacts": REQUIRED_RUN_ARTIFACTS,
    }
    rt.save_json(ROOT_MANIFEST_PATH, payload)


def main() -> None:
    rt = Runtime("research_os_v2_exact_setup.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    ensure_dirs(rt)
    for path in REQUIRED_DIRS:
        rt.require_dir(path, path.name or "research_os_root")

    rt.save_json(EXPERIMENT_SPEC_SCHEMA_PATH, EXPERIMENT_SPEC_SCHEMA)
    rt.save_json(CANDIDATE_LIFECYCLE_SCHEMA_PATH, CANDIDATE_LIFECYCLE_SCHEMA)
    rt.save_json(PROMOTION_DECISION_SCHEMA_PATH, PROMOTION_DECISION_SCHEMA)

    rt.save_json(EXPERIMENT_SPEC_TEMPLATE_PATH, EXPERIMENT_SPEC_TEMPLATE)
    rt.save_json(RUN_STATUS_TEMPLATE_PATH, RUN_STATUS_TEMPLATE)
    rt.save_json(PROMOTION_DECISION_TEMPLATE_PATH, PROMOTION_DECISION_TEMPLATE)

    rt.save_json(RUN_FOLDER_CONTRACT_PATH, RUN_FOLDER_CONTRACT)
    rt.save_text(CONTRACT_DOC_PATH, CONTRACT_DOC)
    rt.save_json(SCHEMA_INDEX_PATH, build_schema_index())

    update_truth_pack(rt)
    update_root_manifest(rt)

    rt.set_counter("schemas_written", 3)
    rt.set_counter("templates_written", 3)
    rt.set_counter("docs_written", 1)
    rt.finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[{local_now_iso()}] [research_os_v2_exact_setup.py] EXCEPTION type={type(exc).__name__} message={exc}", flush=True)
        for line in traceback.format_exc().rstrip().splitlines():
            print(f"[{local_now_iso()}] [research_os_v2_exact_setup.py] TRACE {line}", flush=True)
        raise