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
    RESEARCH_OS_ROOT / "runs" / "templates",
    RESEARCH_OS_ROOT / "experiment_specs",
    RESEARCH_OS_ROOT / "experiment_specs" / "templates",
    RESEARCH_OS_ROOT / "promotion_queue",
    RESEARCH_OS_ROOT / "promotion_queue" / "templates",
    RESEARCH_OS_ROOT / "archives",
    RESEARCH_OS_ROOT / "single_truth",
    RESEARCH_OS_ROOT / "schemas",
]

TRUTH_PACK_PATH = RESEARCH_OS_ROOT / "single_truth" / "truth_pack.json"
ROOT_MANIFEST_PATH = RESEARCH_OS_ROOT / "research_os_manifest.json"
SCHEMA_INDEX_PATH = RESEARCH_OS_ROOT / "schemas" / "schema_index.json"

EXPERIMENT_SPEC_TEMPLATE_PATH = RESEARCH_OS_ROOT / "experiment_specs" / "templates" / "experiment_spec.template.json"
EXPERIMENT_SPEC_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "experiment_spec.schema.json"

RUN_FOLDER_CONTRACT_PATH = RESEARCH_OS_ROOT / "runs" / "templates" / "run_folder_contract.json"

CANDIDATE_LIFECYCLE_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "candidate_lifecycle.schema.json"
PROMOTION_DECISION_TEMPLATE_PATH = RESEARCH_OS_ROOT / "promotion_queue" / "templates" / "promotion_decision.template.json"
PROMOTION_DECISION_SCHEMA_PATH = RESEARCH_OS_ROOT / "schemas" / "promotion_decision.schema.json"

CANDIDATES_REGISTRY_PATH = RESEARCH_OS_ROOT / "candidates_registry.csv"
LEADERBOARD_SUMMARY_PATH = RESEARCH_OS_ROOT / "leaderboards" / "leaderboard_summary.csv"


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

    def save_csv_headers_only(self, path: Path, headers: List[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            self.saved.append(SavedArtifact("csv", str(path), path.stat().st_size))
            self.log(f"SAVED kind=csv path={path} size_bytes={path.stat().st_size}")
        else:
            self.log(f"SKIP existing csv path={path}")

    def finish(self) -> None:
        elapsed = time.monotonic() - self.started
        self.log(f"END status=OK elapsed_sec={elapsed:.3f}")
        self.log(f"SUMMARY saved_files_count={len(self.saved)}")
        for k, v in self.counters.items():
            self.log(f"SUMMARY {k}={v}")
        for i, item in enumerate(self.saved, start=1):
            self.log(f"SAVED_FILE[{i}] kind={item.kind} path={item.path} size_bytes={item.size_bytes}")


EXPERIMENT_SPEC_TEMPLATE = {
    "schema_version": "1.0",
    "experiment_id": "phaseXX_example_experiment",
    "candidate_id": "candidate_example",
    "title": "Example experiment spec",
    "owner": "ai_lab",
    "scope": "core_strategy",
    "family": "guardrail_sweep",
    "status": "draft",
    "baseline_ref": "phase66g_production_soft_filters",
    "objective": "Define one deterministic experiment spec.",
    "hypothesis": "Example hypothesis text.",
    "entry_script": r"C:\Users\benda\Desktop\market_regime_v1\scripts\example.py",
    "runner_import_path": None,
    "runner_callable": None,
    "inputs": [
        {
            "label": "baseline_paper",
            "path": r"C:\Users\benda\Desktop\market_regime_v1\outputs\example\baseline_paper.csv",
            "required": True,
        }
    ],
    "parameter_grid": {
        "param_a": [1, 2],
        "param_b": [0.01, 0.02],
    },
    "metrics_contract": {
        "primary_metric_name": "cagr_pct",
        "secondary_metric_name": "max_drawdown_pct",
        "risk_metric_name": "since2025_cagr_pct",
    },
    "artifact_contract": {
        "required_files": [
            "run_manifest.json",
            "stdout.log",
            "metrics.json",
            "quality_report.json",
        ]
    },
    "created_utc": utc_now_iso(),
    "updated_utc": utc_now_iso(),
    "notes": None,
}

EXPERIMENT_SPEC_SCHEMA = {
    "schema_version": "1.0",
    "required_top_level_keys": [
        "schema_version",
        "experiment_id",
        "candidate_id",
        "title",
        "owner",
        "scope",
        "family",
        "status",
        "baseline_ref",
        "objective",
        "hypothesis",
        "entry_script",
        "inputs",
        "parameter_grid",
        "metrics_contract",
        "artifact_contract",
        "created_utc",
        "updated_utc",
    ],
    "allowed_statuses": [
        "draft",
        "queued",
        "active",
        "paused",
        "completed",
        "archived",
        "rejected",
    ],
    "required_input_keys": [
        "label",
        "path",
        "required",
    ],
    "required_metrics_contract_keys": [
        "primary_metric_name",
        "secondary_metric_name",
        "risk_metric_name",
    ],
    "required_artifact_contract_keys": [
        "required_files",
    ],
}

RUN_FOLDER_CONTRACT = {
    "schema_version": "1.0",
    "contract_id": "run_folder_contract_v1",
    "required_run_root_files": [
        "run_manifest.json",
        "stdout.log",
        "metrics.json",
        "quality_report.json",
    ],
    "optional_run_root_files": [
        "stderr.log",
        "leaderboard_row.json",
        "promotion_decision.json",
    ],
    "required_subdirs": [
        "artifacts",
        "inputs_snapshot",
    ],
    "notes": "Každý run má mať deterministic folder pod research_os/runs/<run_id>/.",
}

CANDIDATE_LIFECYCLE_SCHEMA = {
    "schema_version": "1.0",
    "entity": "candidate",
    "id_field": "candidate_id",
    "required_statuses": [
        "draft",
        "queued",
        "active",
        "shadow",
        "promoted",
        "rejected",
        "archived",
    ],
    "required_fields": [
        "candidate_id",
        "candidate_name",
        "family",
        "scope",
        "baseline_ref",
        "status",
        "lifecycle_stage",
        "current_truth_tier",
        "latest_run_id",
        "promotion_decision",
        "created_utc",
        "updated_utc",
    ],
    "allowed_transitions": {
        "draft": ["queued", "archived"],
        "queued": ["active", "rejected", "archived"],
        "active": ["shadow", "promoted", "rejected", "archived"],
        "shadow": ["promoted", "rejected", "archived"],
        "promoted": ["archived"],
        "rejected": ["archived"],
        "archived": [],
    },
    "notes": "Lifecycle truth pre candidates_registry.csv.",
}

PROMOTION_DECISION_TEMPLATE = {
    "schema_version": "1.0",
    "decision_id": "promotion_decision_example",
    "candidate_id": "candidate_example",
    "source_run_id": "run_example",
    "baseline_ref": "phase66g_production_soft_filters",
    "decision": "hold",
    "decision_reason": "Awaiting more evidence.",
    "decision_owner": "ai_lab",
    "evidence_refs": [],
    "effective_utc": None,
    "created_utc": utc_now_iso(),
    "updated_utc": utc_now_iso(),
    "notes": None,
}

PROMOTION_DECISION_SCHEMA = {
    "schema_version": "1.0",
    "required_top_level_keys": [
        "schema_version",
        "decision_id",
        "candidate_id",
        "source_run_id",
        "baseline_ref",
        "decision",
        "decision_reason",
        "decision_owner",
        "evidence_refs",
        "created_utc",
        "updated_utc",
    ],
    "allowed_decisions": [
        "promote",
        "hold",
        "reject",
        "archive",
    ],
}

TRUTH_PACK_REQUIRED_UPDATES = {
    "registry_extensions": {
        "experiment_spec_template": str(EXPERIMENT_SPEC_TEMPLATE_PATH),
        "experiment_spec_schema": str(EXPERIMENT_SPEC_SCHEMA_PATH),
        "run_folder_contract": str(RUN_FOLDER_CONTRACT_PATH),
        "candidate_lifecycle_schema": str(CANDIDATE_LIFECYCLE_SCHEMA_PATH),
        "promotion_decision_template": str(PROMOTION_DECISION_TEMPLATE_PATH),
        "promotion_decision_schema": str(PROMOTION_DECISION_SCHEMA_PATH),
    }
}


def update_truth_pack(rt: Runtime) -> None:
    rt.require_file(TRUTH_PACK_PATH, label="truth_pack")
    payload = json.loads(TRUTH_PACK_PATH.read_text(encoding="utf-8"))
    payload["registry_extensions"] = TRUTH_PACK_REQUIRED_UPDATES["registry_extensions"]
    payload["updated_utc"] = utc_now_iso()
    rt.save_json(TRUTH_PACK_PATH, payload)


def update_root_manifest(rt: Runtime) -> None:
    rt.require_file(ROOT_MANIFEST_PATH, label="research_os_manifest")
    payload = json.loads(ROOT_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["updated_utc"] = utc_now_iso()
    payload["v2_extensions"] = TRUTH_PACK_REQUIRED_UPDATES["registry_extensions"]
    rt.save_json(ROOT_MANIFEST_PATH, payload)


def build_schema_index() -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "updated_utc": utc_now_iso(),
        "schemas": {
            "experiment_spec": str(EXPERIMENT_SPEC_SCHEMA_PATH),
            "run_folder_contract": str(RUN_FOLDER_CONTRACT_PATH),
            "candidate_lifecycle": str(CANDIDATE_LIFECYCLE_SCHEMA_PATH),
            "promotion_decision": str(PROMOTION_DECISION_SCHEMA_PATH),
        },
        "templates": {
            "experiment_spec": str(EXPERIMENT_SPEC_TEMPLATE_PATH),
            "promotion_decision": str(PROMOTION_DECISION_TEMPLATE_PATH),
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
    rt = Runtime("research_os_v2_setup.py")
    rt.log("START")
    rt.log(f"cwd={Path.cwd()}")
    rt.log(f"python={sys.executable}")
    rt.log(f"argv={' '.join(sys.argv)}")

    ensure_dirs(rt)

    for path in REQUIRED_DIRS:
        rt.require_dir(path, label=path.name or "research_os_root")

    rt.save_csv_headers_only(CANDIDATES_REGISTRY_PATH, [])
    rt.save_csv_headers_only(LEADERBOARD_SUMMARY_PATH, [])

    rt.save_json(EXPERIMENT_SPEC_TEMPLATE_PATH, EXPERIMENT_SPEC_TEMPLATE)
    rt.save_json(EXPERIMENT_SPEC_SCHEMA_PATH, EXPERIMENT_SPEC_SCHEMA)
    rt.save_json(RUN_FOLDER_CONTRACT_PATH, RUN_FOLDER_CONTRACT)
    rt.save_json(CANDIDATE_LIFECYCLE_SCHEMA_PATH, CANDIDATE_LIFECYCLE_SCHEMA)
    rt.save_json(PROMOTION_DECISION_TEMPLATE_PATH, PROMOTION_DECISION_TEMPLATE)
    rt.save_json(PROMOTION_DECISION_SCHEMA_PATH, PROMOTION_DECISION_SCHEMA)
    rt.save_json(SCHEMA_INDEX_PATH, build_schema_index())

    update_truth_pack(rt)
    update_root_manifest(rt)

    rt.set_counter("v2_templates_created", 2)
    rt.set_counter("v2_schemas_created", 4)
    rt.finish()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[{local_now_iso()}] [research_os_v2_setup.py] EXCEPTION type={type(exc).__name__} message={exc}", flush=True)
        for line in traceback.format_exc().rstrip().splitlines():
            print(f"[{local_now_iso()}] [research_os_v2_setup.py] TRACE {line}", flush=True)
        raise