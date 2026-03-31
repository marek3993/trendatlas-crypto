from __future__ import annotations

import csv
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
RESEARCH_OS_ROOT = PROJECT_ROOT / "research_os"

REQUIRED_DIRS = [
    RESEARCH_OS_ROOT,
    RESEARCH_OS_ROOT / "leaderboards",
    RESEARCH_OS_ROOT / "runs",
    RESEARCH_OS_ROOT / "experiment_specs",
    RESEARCH_OS_ROOT / "promotion_queue",
    RESEARCH_OS_ROOT / "archives",
    RESEARCH_OS_ROOT / "single_truth",
    RESEARCH_OS_ROOT / "schemas",
]

TRUTH_PACK_PATH = RESEARCH_OS_ROOT / "single_truth" / "truth_pack.json"
CANDIDATES_REGISTRY_PATH = RESEARCH_OS_ROOT / "candidates_registry.csv"
LEADERBOARD_SUMMARY_PATH = RESEARCH_OS_ROOT / "leaderboards" / "leaderboard_summary.csv"
RUN_MANIFEST_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "run_manifest.schema.json"
ROOT_MANIFEST_PATH = RESEARCH_OS_ROOT / "research_os_manifest.json"

CANDIDATES_REGISTRY_HEADERS = [
    "candidate_id",
    "candidate_name",
    "family",
    "scope",
    "baseline_ref",
    "spec_path",
    "owner",
    "status",
    "lifecycle_stage",
    "current_truth_tier",
    "latest_run_id",
    "latest_score",
    "latest_rank",
    "promotion_decision",
    "demotion_reason",
    "created_utc",
    "updated_utc",
    "notes",
]

LEADERBOARD_SUMMARY_HEADERS = [
    "leaderboard_id",
    "scope",
    "window",
    "baseline_ref",
    "candidate_id",
    "candidate_name",
    "run_id",
    "primary_metric_name",
    "primary_metric_value",
    "secondary_metric_name",
    "secondary_metric_value",
    "risk_metric_name",
    "risk_metric_value",
    "rank",
    "is_current_leader",
    "truth_status",
    "source_manifest_path",
    "updated_utc",
]

TRUTH_PACK_REQUIRED_KEYS = [
    "schema_version",
    "pack_id",
    "project_root",
    "research_os_root",
    "current_truth",
    "registry_files",
    "required_run_manifest_fields",
    "required_candidate_statuses",
]

RUN_MANIFEST_REQUIRED_KEYS = [
    "schema_version",
    "run_id",
    "experiment_id",
    "candidate_id",
    "status",
    "started_utc",
    "ended_utc",
    "artifact_root",
    "spec_path",
    "input_refs",
    "output_refs",
    "metrics",
    "quality_checks",
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
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_csv_headers(path: Path) -> List[str]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            return next(reader)
        except StopIteration:
            return []


def validate_required_dirs(rt: Runtime) -> None:
    for path in REQUIRED_DIRS:
        rt.log(f"CHECK dir {path}")
        if not path.exists():
            rt.fail(f"missing directory: {path}")
        if not path.is_dir():
            rt.fail(f"path is not directory: {path}")
    rt.set_counter("dirs_checked", len(REQUIRED_DIRS))


def validate_required_files(rt: Runtime) -> None:
    required_files = [
        TRUTH_PACK_PATH,
        CANDIDATES_REGISTRY_PATH,
        LEADERBOARD_SUMMARY_PATH,
        RUN_MANIFEST_SCHEMA_PATH,
        ROOT_MANIFEST_PATH,
    ]
    for path in required_files:
        rt.log(f"CHECK file {path}")
        if not path.exists():
            rt.fail(f"missing file: {path}")
        if not path.is_file():
            rt.fail(f"path is not file: {path}")
    rt.set_counter("files_checked", len(required_files))


def validate_truth_pack(rt: Runtime) -> None:
    payload = read_json(TRUTH_PACK_PATH)
    missing = [k for k in TRUTH_PACK_REQUIRED_KEYS if k not in payload]
    if missing:
        rt.fail(f"truth_pack.json missing keys: {missing}")

    registry_files = payload["registry_files"]
    if "candidates_registry_csv" not in registry_files or "leaderboard_summary_csv" not in registry_files:
        rt.fail("truth_pack.json registry_files missing required paths")

    if str(PROJECT_ROOT) != payload["project_root"]:
        rt.fail("truth_pack.json project_root mismatch")

    if str(RESEARCH_OS_ROOT) != payload["research_os_root"]:
        rt.fail("truth_pack.json research_os_root mismatch")

    rt.log("OK truth_pack.json")


def validate_run_manifest_schema(rt: Runtime) -> None:
    payload = read_json(RUN_MANIFEST_SCHEMA_PATH)
    missing = [k for k in RUN_MANIFEST_REQUIRED_KEYS if k not in payload]
    if missing:
        rt.fail(f"run_manifest.schema.json missing keys: {missing}")
    rt.log("OK run_manifest.schema.json")


def validate_csv_headers(rt: Runtime, path: Path, expected: List[str], label: str) -> None:
    headers = read_csv_headers(path)
    if headers != expected:
        rt.fail(f"{label} headers mismatch. expected={expected} actual={headers}")
    rt.log(f"OK {label} headers")


def validate_root_manifest(rt: Runtime) -> None:
    payload = read_json(ROOT_MANIFEST_PATH)
    for key in ["schema_version", "registry_id", "created_utc", "project_root", "research_os_root", "required_dirs"]:
        if key not in payload:
            rt.fail(f"research_os_manifest.json missing key: {key}")
    if payload["project_root"] != str(PROJECT_ROOT):
        rt.fail("research_os_manifest.json project_root mismatch")
    if payload["research_os_root"] != str(RESEARCH_OS_ROOT):
        rt.fail("research_os_manifest.json research_os_root mismatch")
    rt.log("OK research_os_manifest.json")


def main() -> None:
    rt = Runtime("research_os_validate.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    validate_required_dirs(rt)
    validate_required_files(rt)
    validate_truth_pack(rt)
    validate_run_manifest_schema(rt)
    validate_csv_headers(rt, CANDIDATES_REGISTRY_PATH, CANDIDATES_REGISTRY_HEADERS, "candidates_registry.csv")
    validate_csv_headers(rt, LEADERBOARD_SUMMARY_PATH, LEADERBOARD_SUMMARY_HEADERS, "leaderboard_summary.csv")
    validate_root_manifest(rt)

    rt.set_counter("validation_status", "passed")
    rt.finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[{local_now_iso()}] [research_os_validate.py] EXCEPTION type={type(exc).__name__} message={exc}", flush=True)
        for line in traceback.format_exc().rstrip().splitlines():
            print(f"[{local_now_iso()}] [research_os_validate.py] TRACE {line}", flush=True)
        raise