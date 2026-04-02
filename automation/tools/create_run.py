from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

TEMPLATE_TASK_SPEC = AUTOMATION_ROOT / "templates" / "task_spec.template.json"
TEMPLATE_RUN_LOG = AUTOMATION_ROOT / "templates" / "run_log.template.json"
TEMPLATE_REPORT = AUTOMATION_ROOT / "templates" / "report.template.json"
TEMPLATE_SCREENSHOT_MANIFEST = AUTOMATION_ROOT / "templates" / "screenshot_manifest.template.json"

TASKS_SPECS_DIR = AUTOMATION_ROOT / "tasks" / "specs"
TASKS_QUEUE_DIR = AUTOMATION_ROOT / "tasks" / "queue"
RUNS_DIR = AUTOMATION_ROOT / "runs"
REPORTS_DIR = AUTOMATION_ROOT / "reports"
SCREENSHOTS_DIR = AUTOMATION_ROOT / "screenshots"


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "task"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")


def build_ids(task_type: str, slug: str) -> tuple[str, str, str, str]:
    stamp = now_utc_compact()
    task_id = f"task_{stamp}_{task_type}_{slug}"
    run_id = f"run_{stamp}_{task_type}_{slug}"
    report_id = f"report_{stamp}_{task_type}_{slug}"
    manifest_id = f"manifest_{stamp}_{task_type}_{slug}"
    return task_id, run_id, report_id, manifest_id


def build_task_spec(task_id: str, task_type: str, requested_by: str, source_refs: list[str]) -> dict:
    data = deepcopy(read_json(TEMPLATE_TASK_SPEC))
    data["task_id"] = task_id
    data["task_type"] = task_type
    data["created_at"] = now_utc_iso()
    data["requested_by"] = requested_by
    data["status"] = "queued"
    data["source_refs"] = source_refs
    return data


def build_run_log(run_id: str, task_id: str) -> dict:
    data = deepcopy(read_json(TEMPLATE_RUN_LOG))
    data["run_id"] = run_id
    data["task_id"] = task_id
    data["started_at"] = now_utc_iso()
    data["ended_at"] = None
    data["status"] = "started"
    data["steps"] = [
        {
            "step_index": 1,
            "timestamp": now_utc_iso(),
            "action": "create_run_scaffold",
            "result": "ok",
            "note": "Initialized run, report, manifest and task spec."
        }
    ]
    return data


def build_report(report_id: str, run_id: str, task_id: str, run_log_path: Path, report_path: Path, manifest_path: Path) -> dict:
    data = deepcopy(read_json(TEMPLATE_REPORT))
    data["report_id"] = report_id
    data["run_id"] = run_id
    data["task_id"] = task_id
    data["summary"] = "Run scaffold created."
    data["findings"] = [
        "Task spec created.",
        "Run log created.",
        "Screenshot manifest created.",
        "No truth patch created yet."
    ]
    data["artifacts"]["run_log_path"] = str(run_log_path)
    data["artifacts"]["screenshot_manifest_paths"] = [str(manifest_path)]
    data["artifacts"]["report_path"] = str(report_path)
    data["pending_truth_patch_ids"] = []
    data["next_action"] = "execute_task_or_capture_evidence"
    return data


def build_manifest(manifest_id: str, run_id: str) -> dict:
    data = deepcopy(read_json(TEMPLATE_SCREENSHOT_MANIFEST))
    data["manifest_id"] = manifest_id
    data["run_id"] = run_id
    data["screenshots"] = []
    return data


def main() -> None:
    ensure_exists(TEMPLATE_TASK_SPEC, "task spec template")
    ensure_exists(TEMPLATE_RUN_LOG, "run log template")
    ensure_exists(TEMPLATE_REPORT, "report template")
    ensure_exists(TEMPLATE_SCREENSHOT_MANIFEST, "screenshot manifest template")

    task_type = sys.argv[1] if len(sys.argv) > 1 else "workflow_run"
    slug_input = sys.argv[2] if len(sys.argv) > 2 else "manual"
    requested_by = sys.argv[3] if len(sys.argv) > 3 else "user"

    allowed_task_types = {
        "browser_check",
        "browser_capture",
        "workflow_run",
        "report_only",
        "truth_patch_prep",
    }
    if task_type not in allowed_task_types:
        raise ValueError(f"Unsupported task_type: {task_type}")

    slug = slugify(slug_input)
    task_id, run_id, report_id, manifest_id = build_ids(task_type, slug)

    task_spec_path = TASKS_SPECS_DIR / f"{task_id}.json"
    queued_marker_path = TASKS_QUEUE_DIR / f"{task_id}.json"
    run_dir = RUNS_DIR / run_id
    report_dir = REPORTS_DIR / run_id
    screenshot_dir = SCREENSHOTS_DIR / run_id

    run_log_path = run_dir / f"{run_id}.run_log.json"
    report_path = report_dir / f"{report_id}.report.json"
    manifest_path = screenshot_dir / f"{manifest_id}.screenshot_manifest.json"

    source_refs = [
        r"C:\Users\benda\Desktop\market_regime_v1\source_of_truth\README.md",
        r"C:\Users\benda\Desktop\market_regime_v1\source_of_truth\master_state.md",
        r"C:\Users\benda\Desktop\market_regime_v1\source_of_truth\chat_roles.md",
        r"C:\Users\benda\Desktop\market_regime_v1\source_of_truth\project_truth.json",
        r"C:\Users\benda\Desktop\market_regime_v1\source_of_truth\paths_registry.json",
        r"C:\Users\benda\Desktop\market_regime_v1\source_of_truth\current_issues.md",
    ]

    task_spec = build_task_spec(task_id, task_type, requested_by, source_refs)
    run_log = build_run_log(run_id, task_id)
    manifest = build_manifest(manifest_id, run_id)
    report = build_report(report_id, run_id, task_id, run_log_path, report_path, manifest_path)

    run_log["artifacts"]["report_paths"] = [str(report_path)]
    run_log["artifacts"]["screenshot_manifest_paths"] = [str(manifest_path)]
    run_log["artifacts"]["pending_truth_patch_paths"] = []

    write_json(task_spec_path, task_spec)
    write_json(queued_marker_path, task_spec)
    write_json(run_log_path, run_log)
    write_json(manifest_path, manifest)
    write_json(report_path, report)

    print("OK: run scaffold created")
    print(f"task_id={task_id}")
    print(f"run_id={run_id}")
    print(f"task_spec={task_spec_path}")
    print(f"queue_entry={queued_marker_path}")
    print(f"run_log={run_log_path}")
    print(f"report={report_path}")
    print(f"screenshot_manifest={manifest_path}")


if __name__ == "__main__":
    main()