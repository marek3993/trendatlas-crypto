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

EXPERIMENT_SPEC_TEMPLATE_PATH = RESEARCH_OS_ROOT / "experiment_specs" / "templates" / "experiment_spec.template.json"
EXPERIMENT_SPEC_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "experiment_spec.schema.json"
RUN_FOLDER_CONTRACT_PATH = RESEARCH_OS_ROOT / "runs" / "templates" / "run_folder_contract.json"
CANDIDATE_LIFECYCLE_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "candidate_lifecycle.schema.json"
PROMOTION_DECISION_TEMPLATE_PATH = RESEARCH_OS_ROOT / "promotion_queue" / "templates" / "promotion_decision.template.json"
PROMOTION_DECISION_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "promotion_decision.schema.json"

REQUIRED_FILES = [
    TRUTH_PACK_PATH,
    ROOT_MANIFEST_PATH,
    SCHEMA_INDEX_PATH,
    EXPERIMENT_SPEC_TEMPLATE_PATH,
    EXPERIMENT_SPEC_SCHEMA_PATH,
    RUN_FOLDER_CONTRACT_PATH,
    CANDIDATE_LIFECYCLE_SCHEMA_PATH,
    PROMOTION_DECISION_TEMPLATE_PATH,
    PROMOTION_DECISION_SCHEMA_PATH,
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


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_file(rt: Runtime, path: Path, label: str) -> None:
    rt.log(f"CHECK file {label}: {path}")
    if not path.exists() or not path.is_file():
        rt.fail(f"missing file: {path}")
    rt.log(f"OK file {label}: size_bytes={path.stat().st_size}")


def validate_experiment_spec_template(rt: Runtime) -> None:
    payload = read_json(EXPERIMENT_SPEC_TEMPLATE_PATH)
    schema = read_json(EXPERIMENT_SPEC_SCHEMA_PATH)

    missing = [k for k in schema["required_top_level_keys"] if k not in payload]
    if missing:
        rt.fail(f"experiment_spec template missing keys: {missing}")

    required_input_keys = schema["required_input_keys"]
    if not payload["inputs"] or not isinstance(payload["inputs"], list):
        rt.fail("experiment_spec template inputs invalid")
    first_input = payload["inputs"][0]
    missing_input = [k for k in required_input_keys if k not in first_input]
    if missing_input:
        rt.fail(f"experiment_spec template input missing keys: {missing_input}")

    metrics_keys = schema["required_metrics_contract_keys"]
    missing_metrics = [k for k in metrics_keys if k not in payload["metrics_contract"]]
    if missing_metrics:
        rt.fail(f"experiment_spec template metrics_contract missing keys: {missing_metrics}")

    artifact_keys = schema["required_artifact_contract_keys"]
    missing_artifact = [k for k in artifact_keys if k not in payload["artifact_contract"]]
    if missing_artifact:
        rt.fail(f"experiment_spec template artifact_contract missing keys: {missing_artifact}")

    rt.log("OK experiment_spec template/schema")


def validate_run_folder_contract(rt: Runtime) -> None:
    payload = read_json(RUN_FOLDER_CONTRACT_PATH)
    for key in ["schema_version", "contract_id", "required_run_root_files", "optional_run_root_files", "required_subdirs"]:
        if key not in payload:
            rt.fail(f"run_folder_contract missing key: {key}")
    if "run_manifest.json" not in payload["required_run_root_files"]:
        rt.fail("run_folder_contract missing run_manifest.json in required_run_root_files")
    rt.log("OK run_folder_contract")


def validate_candidate_lifecycle(rt: Runtime) -> None:
    payload = read_json(CANDIDATE_LIFECYCLE_SCHEMA_PATH)
    for key in ["schema_version", "entity", "id_field", "required_statuses", "required_fields", "allowed_transitions"]:
        if key not in payload:
            rt.fail(f"candidate_lifecycle schema missing key: {key}")

    statuses = payload["required_statuses"]
    transitions = payload["allowed_transitions"]
    for status in statuses:
        if status not in transitions:
            rt.fail(f"candidate_lifecycle missing transition entry for status={status}")

    rt.log("OK candidate_lifecycle schema")


def validate_promotion_decision(rt: Runtime) -> None:
    payload = read_json(PROMOTION_DECISION_TEMPLATE_PATH)
    schema = read_json(PROMOTION_DECISION_SCHEMA_PATH)

    missing = [k for k in schema["required_top_level_keys"] if k not in payload]
    if missing:
        rt.fail(f"promotion_decision template missing keys: {missing}")

    if payload["decision"] not in schema["allowed_decisions"]:
        rt.fail("promotion_decision template decision is outside allowed_decisions")

    rt.log("OK promotion_decision template/schema")


def validate_truth_and_manifest_links(rt: Runtime) -> None:
    truth_pack = read_json(TRUTH_PACK_PATH)
    root_manifest = read_json(ROOT_MANIFEST_PATH)
    schema_index = read_json(SCHEMA_INDEX_PATH)

    if "registry_extensions" not in truth_pack:
        rt.fail("truth_pack missing registry_extensions")
    if "v2_extensions" not in root_manifest:
        rt.fail("research_os_manifest missing v2_extensions")

    truth_ext = truth_pack["registry_extensions"]
    manifest_ext = root_manifest["v2_extensions"]

    expected_keys = [
        "experiment_spec_template",
        "experiment_spec_schema",
        "run_folder_contract",
        "candidate_lifecycle_schema",
        "promotion_decision_template",
        "promotion_decision_schema",
    ]
    for key in expected_keys:
        if key not in truth_ext:
            rt.fail(f"truth_pack registry_extensions missing key: {key}")
        if key not in manifest_ext:
            rt.fail(f"research_os_manifest v2_extensions missing key: {key}")

    if "schemas" not in schema_index or "templates" not in schema_index:
        rt.fail("schema_index missing schemas/templates")

    rt.log("OK truth_pack / research_os_manifest / schema_index linkage")


def main() -> None:
    rt = Runtime("research_os_v2_validate.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    for path in REQUIRED_FILES:
        require_file(rt, path, path.name)

    validate_experiment_spec_template(rt)
    validate_run_folder_contract(rt)
    validate_candidate_lifecycle(rt)
    validate_promotion_decision(rt)
    validate_truth_and_manifest_links(rt)

    rt.set_counter("files_checked", len(REQUIRED_FILES))
    rt.set_counter("validation_status", "passed")
    rt.finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[{local_now_iso()}] [research_os_v2_validate.py] EXCEPTION type={type(exc).__name__} message={exc}", flush=True)
        for line in traceback.format_exc().rstrip().splitlines():
            print(f"[{local_now_iso()}] [research_os_v2_validate.py] TRACE {line}", flush=True)
        raise