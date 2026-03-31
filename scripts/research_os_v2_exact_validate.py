from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"

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

REQUIRED_FILES = [
    TRUTH_PACK_PATH,
    ROOT_MANIFEST_PATH,
    SCHEMA_INDEX_PATH,
    EXPERIMENT_SPEC_SCHEMA_PATH,
    CANDIDATE_LIFECYCLE_SCHEMA_PATH,
    PROMOTION_DECISION_SCHEMA_PATH,
    EXPERIMENT_SPEC_TEMPLATE_PATH,
    RUN_STATUS_TEMPLATE_PATH,
    PROMOTION_DECISION_TEMPLATE_PATH,
    RUN_FOLDER_CONTRACT_PATH,
    CONTRACT_DOC_PATH,
]

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


def local_now_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


class Runtime:
    def __init__(self, script_name: str) -> None:
        self.script_name = script_name
        self.started = time.monotonic()
        self.counters: Dict[str, Any] = {}

    def log(self, message: str) -> None:
        print(f"[{local_now_iso()}] [{self.script_name}] {message}", flush=True)

    def set_counter(self, key: str, value: Any) -> None:
        self.counters[key] = value
        self.log(f"{key}={value}")

    def fail(self, message: str) -> None:
        self.log(f"FAIL {message}")
        raise RuntimeError(message)

    def finish(self) -> None:
        elapsed = time.monotonic() - self.started
        self.log(f"END status=OK elapsed_sec={elapsed:.3f}")
        for k, v in self.counters.items():
            self.log(f"SUMMARY {k}={v}")


def require_file(rt: Runtime, path: Path, label: str) -> None:
    rt.log(f"CHECK file {label}: {path}")
    if not path.exists() or not path.is_file():
        rt.fail(f"missing file: {path}")
    rt.log(f"OK file {label}: size_bytes={path.stat().st_size}")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_experiment_spec(rt: Runtime) -> None:
    schema = read_json(EXPERIMENT_SPEC_SCHEMA_PATH)
    template = read_json(EXPERIMENT_SPEC_TEMPLATE_PATH)

    required_fields = schema["required_fields"]
    if required_fields != EXPERIMENT_SPEC_REQUIRED_FIELDS:
        rt.fail("experiment_spec.schema.json required_fields mismatch against exact AI LAB spec")

    missing = [k for k in required_fields if k not in template]
    if missing:
        rt.fail(f"experiment_spec.template.json missing fields: {missing}")

    allowed_statuses = schema["allowed_status_values"]
    if allowed_statuses != REQUIRED_LIFECYCLE_STATUSES:
        rt.fail("experiment_spec.schema.json allowed_status_values mismatch against exact AI LAB spec")

    if template["status"] not in allowed_statuses:
        rt.fail("experiment_spec.template.json status outside allowed lifecycle statuses")

    if not isinstance(template["input_paths"], list) or not template["input_paths"]:
        rt.fail("experiment_spec.template.json input_paths invalid/empty")
    if not isinstance(template["script_args"], list):
        rt.fail("experiment_spec.template.json script_args must be list")
    if not isinstance(template["expected_outputs"], list) or not template["expected_outputs"]:
        rt.fail("experiment_spec.template.json expected_outputs invalid/empty")

    rt.log("OK experiment_spec exact contract")


def validate_candidate_lifecycle(rt: Runtime) -> None:
    schema = read_json(CANDIDATE_LIFECYCLE_SCHEMA_PATH)
    statuses = schema["required_statuses"]
    if statuses != REQUIRED_LIFECYCLE_STATUSES:
        rt.fail("candidate_lifecycle.schema.json required_statuses mismatch against exact AI LAB spec")

    transitions = schema["allowed_transitions"]
    for status in REQUIRED_LIFECYCLE_STATUSES:
        if status not in transitions:
            rt.fail(f"candidate_lifecycle.schema.json missing transition bucket for {status}")

    rt.log("OK candidate_lifecycle exact contract")


def validate_promotion_decision(rt: Runtime) -> None:
    schema = read_json(PROMOTION_DECISION_SCHEMA_PATH)
    template = read_json(PROMOTION_DECISION_TEMPLATE_PATH)

    if schema["allowed_decision_values"] != REQUIRED_PROMOTION_DECISIONS:
        rt.fail("promotion_decision.schema.json allowed_decision_values mismatch against exact AI LAB spec")

    missing = [k for k in schema["required_fields"] if k not in template]
    if missing:
        rt.fail(f"promotion_decision.template.json missing fields: {missing}")

    if template["decision"] not in REQUIRED_PROMOTION_DECISIONS:
        rt.fail("promotion_decision.template.json decision outside exact AI LAB spec")

    rt.log("OK promotion_decision exact contract")


def validate_run_status(rt: Runtime) -> None:
    template = read_json(RUN_STATUS_TEMPLATE_PATH)

    required = [
        "schema_version",
        "run_id",
        "experiment_id",
        "candidate_id",
        "status",
        "allowed_status_values",
        "started_at",
        "ended_at",
        "status_reason",
        "current_step",
        "promotion_decision",
        "updated_at",
    ]
    missing = [k for k in required if k not in template]
    if missing:
        rt.fail(f"run_status.template.json missing fields: {missing}")

    if template["allowed_status_values"] != REQUIRED_LIFECYCLE_STATUSES:
        rt.fail("run_status.template.json allowed_status_values mismatch against exact AI LAB spec")

    if template["status"] not in REQUIRED_LIFECYCLE_STATUSES:
        rt.fail("run_status.template.json status outside exact AI LAB spec")

    rt.log("OK run_status exact contract")


def validate_run_folder_contract(rt: Runtime) -> None:
    contract = read_json(RUN_FOLDER_CONTRACT_PATH)
    artifacts = contract["required_run_artifacts"]
    if artifacts != REQUIRED_RUN_ARTIFACTS:
        rt.fail("run_folder_contract.json required_run_artifacts mismatch against exact AI LAB spec")

    rt.log("OK run_folder exact contract")


def validate_contract_doc(rt: Runtime) -> None:
    text = CONTRACT_DOC_PATH.read_text(encoding="utf-8")
    required_snippets = [
        "Required fields",
        "Allowed status values",
        "Required run artifacts",
        "Promotion decision types",
        "Naming conventions",
        "run_manifest.json",
        "run_status.json",
        "promote_to_official",
    ]
    for snippet in required_snippets:
        if snippet not in text:
            rt.fail(f"research_os_v2_contract.md missing snippet: {snippet}")

    rt.log("OK contract doc")


def validate_linkage(rt: Runtime) -> None:
    truth_pack = read_json(TRUTH_PACK_PATH)
    root_manifest = read_json(ROOT_MANIFEST_PATH)
    schema_index = read_json(SCHEMA_INDEX_PATH)

    if "registry_extensions" not in truth_pack:
        rt.fail("truth_pack.json missing registry_extensions")
    if "v2_contract_pack" not in root_manifest:
        rt.fail("research_os_manifest.json missing v2_contract_pack")

    extensions = truth_pack["registry_extensions"]
    required_extension_keys = [
        "experiment_spec_schema",
        "candidate_lifecycle_schema",
        "promotion_decision_schema",
        "experiment_spec_template",
        "run_status_template",
        "promotion_decision_template",
        "run_folder_contract",
        "research_os_v2_contract_doc",
    ]
    missing = [k for k in required_extension_keys if k not in extensions]
    if missing:
        rt.fail(f"truth_pack.json registry_extensions missing keys: {missing}")

    if "schemas" not in schema_index or "templates" not in schema_index or "docs" not in schema_index:
        rt.fail("schema_index.json missing schemas/templates/docs sections")

    rt.log("OK linkage")


def main() -> None:
    rt = Runtime("research_os_v2_exact_validate.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    for path in REQUIRED_FILES:
        require_file(rt, path, path.name)

    validate_experiment_spec(rt)
    validate_candidate_lifecycle(rt)
    validate_promotion_decision(rt)
    validate_run_status(rt)
    validate_run_folder_contract(rt)
    validate_contract_doc(rt)
    validate_linkage(rt)

    rt.set_counter("files_checked", len(REQUIRED_FILES))
    rt.set_counter("validation_status", "passed")
    rt.finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[{local_now_iso()}] [research_os_v2_exact_validate.py] EXCEPTION type={type(exc).__name__} message={exc}", flush=True)
        for line in traceback.format_exc().rstrip().splitlines():
            print(f"[{local_now_iso()}] [research_os_v2_exact_validate.py] TRACE {line}", flush=True)
        raise