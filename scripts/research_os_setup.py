from __future__ import annotations

import csv
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
    RESEARCH_OS_ROOT / "experiment_specs",
    RESEARCH_OS_ROOT / "promotion_queue",
    RESEARCH_OS_ROOT / "archives",
    RESEARCH_OS_ROOT / "single_truth",
    RESEARCH_OS_ROOT / "schemas",
]

TRUTH_PACK_PATH = RESEARCH_OS_ROOT / "single_truth" / "truth_pack.json"
CANDIDATES_REGISTRY_PATH = RESEARCH_OS_ROOT / "candidates_registry.csv"
LEADERBOARD_SUMMARY_PATH = RESEARCH_OS_ROOT / "leaderboards" / "leaderboard_summary.csv"
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

TRUTH_PACK_TEMPLATE = {
    "schema_version": "1.0",
    "pack_id": "truth_pack_v1",
    "project_root": str(PROJECT_ROOT),
    "research_os_root": str(RESEARCH_OS_ROOT),
    "current_truth": {
        "baseline_candidate_id": None,
        "baseline_run_id": None,
        "production_candidate_id": None,
        "production_run_id": None,
        "latest_validated_leaderboard_id": None,
        "last_promotion_utc": None,
        "truth_status": "bootstrap",
    },
    "registry_files": {
        "candidates_registry_csv": str(CANDIDATES_REGISTRY_PATH),
        "leaderboard_summary_csv": str(LEADERBOARD_SUMMARY_PATH),
    },
    "required_run_manifest_fields": [
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
    ],
    "required_candidate_statuses": [
        "draft",
        "queued",
        "active",
        "shadow",
        "promoted",
        "rejected",
        "archived",
    ],
    "notes": "Single source of truth pre AI Research Registry v1.",
}

RUN_MANIFEST_SCHEMA_TEMPLATE = {
    "schema_version": "1.0",
    "run_id": "example_run_id",
    "experiment_id": "example_experiment_id",
    "candidate_id": "example_candidate_id",
    "status": "created",
    "started_utc": "2026-01-01 00:00:00 UTC",
    "ended_utc": None,
    "artifact_root": "research_os/runs/example_run_id",
    "spec_path": "research_os/experiment_specs/example_experiment.json",
    "input_refs": [],
    "output_refs": [],
    "metrics": {},
    "quality_checks": {
        "status": "pending",
        "checks": [],
    },
    "notes": None,
}


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

    def save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.saved.append(SavedArtifact("json", str(path), path.stat().st_size))
        self.log(f"SAVED kind=json path={path} size_bytes={path.stat().st_size}")

    def save_csv_headers_only(self, path: Path, headers: List[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
        self.saved.append(SavedArtifact("csv", str(path), path.stat().st_size))
        self.log(f"SAVED kind=csv path={path} size_bytes={path.stat().st_size}")

    def finish(self) -> None:
        elapsed = time.monotonic() - self.started
        self.log(f"END status=OK elapsed_sec={elapsed:.3f}")
        self.log(f"SUMMARY saved_files_count={len(self.saved)}")
        for k, v in self.counters.items():
            self.log(f"SUMMARY {k}={v}")
        for i, item in enumerate(self.saved, start=1):
            self.log(f"SAVED_FILE[{i}] kind={item.kind} path={item.path} size_bytes={item.size_bytes}")


def build_root_manifest() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "registry_id": "ai_research_registry_v1",
        "created_utc": utc_now_iso(),
        "project_root": str(PROJECT_ROOT),
        "research_os_root": str(RESEARCH_OS_ROOT),
        "required_dirs": [str(p) for p in REQUIRED_DIRS],
        "truth_pack_path": str(TRUTH_PACK_PATH),
        "candidates_registry_path": str(CANDIDATES_REGISTRY_PATH),
        "leaderboard_summary_path": str(LEADERBOARD_SUMMARY_PATH),
        "schema_templates": {
            "truth_pack": str(TRUTH_PACK_PATH),
            "run_manifest_schema": str(RESEARCH_OS_ROOT / "schemas" / "run_manifest.schema.json"),
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


def main() -> None:
    rt = Runtime("research_os_setup.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    ensure_dirs(rt)

    for path in REQUIRED_DIRS:
        rt.require_dir(path, label=path.name or "research_os_root")

    rt.save_json(TRUTH_PACK_PATH, TRUTH_PACK_TEMPLATE)
    rt.save_csv_headers_only(CANDIDATES_REGISTRY_PATH, CANDIDATES_REGISTRY_HEADERS)
    rt.save_csv_headers_only(LEADERBOARD_SUMMARY_PATH, LEADERBOARD_SUMMARY_HEADERS)
    rt.save_json(RESEARCH_OS_ROOT / "schemas" / "run_manifest.schema.json", RUN_MANIFEST_SCHEMA_TEMPLATE)
    rt.save_json(ROOT_MANIFEST_PATH, build_root_manifest())

    rt.finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[{local_now_iso()}] [research_os_setup.py] EXCEPTION type={type(exc).__name__} message={exc}", flush=True)
        for line in traceback.format_exc().rstrip().splitlines():
            print(f"[{local_now_iso()}] [research_os_setup.py] TRACE {line}", flush=True)
        raise