from __future__ import annotations

import json
import subprocess
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
TASKS_COMPLETED_DIR = AUTOMATION_ROOT / "tasks" / "completed"
RUNS_DIR = AUTOMATION_ROOT / "runs"
REPORTS_DIR = AUTOMATION_ROOT / "reports"
SCREENSHOTS_DIR = AUTOMATION_ROOT / "screenshots"

DEFAULT_RUNBOOK = AUTOMATION_ROOT / "config" / "execution_refresh_runbook.json"
VALIDATOR_SCRIPT = AUTOMATION_ROOT / "tools" / "validate_execution_refresh_chain.py"


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")


def slugify(value: str) -> str:
    out = []
    for ch in value.strip().lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "run"


def append_step(run_log: dict, action: str, result: str, note: str) -> None:
    steps = run_log.setdefault("steps", [])
    steps.append(
        {
            "step_index": len(steps) + 1,
            "timestamp": now_utc_iso(),
            "action": action,
            "result": result,
            "note": note,
        }
    )


def build_ids(slug: str) -> tuple[str, str, str, str]:
    stamp = now_utc_compact()
    task_id = f"task_{stamp}_workflow_run_{slug}"
    run_id = f"run_{stamp}_workflow_run_{slug}"
    report_id = f"report_{stamp}_workflow_run_{slug}"
    manifest_id = f"manifest_{stamp}_workflow_run_{slug}"
    return task_id, run_id, report_id, manifest_id


def build_task_spec(task_id: str, runbook_path: Path, requested_by: str) -> dict:
    data = deepcopy(read_json(TEMPLATE_TASK_SPEC))
    data["task_id"] = task_id
    data["task_type"] = "workflow_run"
    data["created_at"] = now_utc_iso()
    data["requested_by"] = requested_by
    data["status"] = "running"
    data["inputs"] = {
        "runbook_path": str(runbook_path),
    }
    data["constraints"] = {
        "safe_mode": True,
        "allow_direct_source_of_truth_write": False,
        "real_orders_allowed": False,
        "app_switching_allowed": False,
    }
    data["expected_outputs"] = [
        "run_log",
        "report",
        "screenshot_manifest",
    ]
    data["approval_gate"] = {
        "required_for_truth_apply": True,
        "approver_role": "human",
    }
    data["source_refs"] = [
        str(PROJECT_ROOT / "source_of_truth" / "README.md"),
        str(PROJECT_ROOT / "source_of_truth" / "master_state.md"),
        str(PROJECT_ROOT / "source_of_truth" / "chat_roles.md"),
        str(PROJECT_ROOT / "source_of_truth" / "project_truth.json"),
        str(PROJECT_ROOT / "source_of_truth" / "paths_registry.json"),
        str(PROJECT_ROOT / "source_of_truth" / "current_issues.md"),
        str(PROJECT_ROOT / "canonical" / "script_registry.json"),
        str(PROJECT_ROOT / "canonical" / "output_registry.json"),
        str(PROJECT_ROOT / "canonical" / "registry_workflow.md"),
    ]
    return data


def build_run_log(run_id: str, task_id: str) -> dict:
    data = deepcopy(read_json(TEMPLATE_RUN_LOG))
    data["run_id"] = run_id
    data["task_id"] = task_id
    data["started_at"] = now_utc_iso()
    data["ended_at"] = None
    data["status"] = "started"
    data["executor"] = "automation_wrapper"
    data["steps"] = []
    data["artifacts"] = {
        "report_paths": [],
        "screenshot_manifest_paths": [],
        "pending_truth_patch_paths": [],
    }
    data["errors"] = []
    data["warnings"] = []
    return data


def build_report(report_id: str, run_id: str, task_id: str) -> dict:
    data = deepcopy(read_json(TEMPLATE_REPORT))
    data["report_id"] = report_id
    data["run_id"] = run_id
    data["task_id"] = task_id
    data["summary"] = "Execution refresh wrapper run created."
    data["findings"] = []
    data["artifacts"] = {
        "run_log_path": "",
        "screenshot_manifest_paths": [],
        "report_path": "",
    }
    data["pending_truth_patch_ids"] = []
    data["next_action"] = "run_execution_chain"
    return data


def build_manifest(manifest_id: str, run_id: str) -> dict:
    data = deepcopy(read_json(TEMPLATE_SCREENSHOT_MANIFEST))
    data["manifest_id"] = manifest_id
    data["run_id"] = run_id
    data["screenshots"] = []
    return data


def ensure_parent_dirs() -> None:
    for p in [
        TASKS_SPECS_DIR,
        TASKS_QUEUE_DIR,
        TASKS_COMPLETED_DIR,
        RUNS_DIR,
        REPORTS_DIR,
        SCREENSHOTS_DIR,
    ]:
        p.mkdir(parents=True, exist_ok=True)


def create_run_scaffold(runbook_path: Path, requested_by: str, slug: str) -> dict:
    ensure_parent_dirs()

    task_id, run_id, report_id, manifest_id = build_ids(slug)

    task_spec_path = TASKS_SPECS_DIR / f"{task_id}.json"
    queue_path = TASKS_QUEUE_DIR / f"{task_id}.json"
    run_dir = RUNS_DIR / run_id
    report_dir = REPORTS_DIR / run_id
    screenshot_dir = SCREENSHOTS_DIR / run_id

    run_log_path = run_dir / f"{run_id}.run_log.json"
    report_path = report_dir / f"{report_id}.report.json"
    manifest_path = screenshot_dir / f"{manifest_id}.screenshot_manifest.json"

    task_spec = build_task_spec(task_id, runbook_path, requested_by)
    run_log = build_run_log(run_id, task_id)
    report = build_report(report_id, run_id, task_id)
    manifest = build_manifest(manifest_id, run_id)

    report["artifacts"]["run_log_path"] = str(run_log_path)
    report["artifacts"]["report_path"] = str(report_path)
    report["artifacts"]["screenshot_manifest_paths"] = [str(manifest_path)]

    run_log["artifacts"]["report_paths"] = [str(report_path)]
    run_log["artifacts"]["screenshot_manifest_paths"] = [str(manifest_path)]

    append_step(run_log, "create_run_scaffold", "ok", "Execution refresh wrapper run scaffold created.")

    write_json(task_spec_path, task_spec)
    write_json(queue_path, task_spec)
    write_json(run_log_path, run_log)
    write_json(report_path, report)
    write_json(manifest_path, manifest)

    return {
        "task_id": task_id,
        "run_id": run_id,
        "task_spec_path": task_spec_path,
        "queue_path": queue_path,
        "run_log_path": run_log_path,
        "report_path": report_path,
        "manifest_path": manifest_path,
    }


def run_stage(stage: dict) -> tuple[bool, str]:
    name = str(stage["name"])
    command = stage.get("command", [])
    if not isinstance(command, list) or not command:
        return False, f"Stage '{name}' has invalid command list"

    cmd = [str(part) for part in command]
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    note_parts = [f"stage={name}", f"returncode={result.returncode}"]
    if stdout:
        note_parts.append(f"stdout={stdout}")
    if stderr:
        note_parts.append(f"stderr={stderr}")

    ok = result.returncode == 0
    return ok, " | ".join(note_parts)


def run_validator(runbook_path: Path) -> tuple[bool, str, list[str], list[str]]:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_SCRIPT), str(runbook_path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    stdout_lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    stderr_lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]

    chain_status = "broken"
    findings: list[str] = []
    errors: list[str] = []

    for line in stdout_lines:
        if line.startswith("chain_status="):
            chain_status = line.split("=", 1)[1].strip()
        elif line.startswith("finding="):
            findings.append(line.split("=", 1)[1].strip())
        elif line.startswith("error="):
            errors.append(line.split("=", 1)[1].strip())

    for line in stderr_lines:
        errors.append(line)

    ok = result.returncode == 0 and chain_status == "healthy"
    note = f"validator_returncode={result.returncode} | chain_status={chain_status}"
    return ok, note, findings, errors


def finalize_run(queue_path: Path, run_log_path: Path, report_path: Path, final_status: str, summary: str) -> None:
    run_log = read_json(run_log_path)
    report = read_json(report_path)
    task_data = read_json(queue_path)

    run_log["ended_at"] = now_utc_iso()
    run_log["status"] = final_status
    append_step(run_log, "finalize_run", "ok", f"Run finalized with status={final_status}")

    report["summary"] = summary
    report["next_action"] = "review_execution_refresh_report"

    task_data["status"] = "completed" if final_status in {"success", "partial"} else "failed"

    completed_path = TASKS_COMPLETED_DIR / queue_path.name
    write_json(completed_path, task_data)
    if queue_path.exists():
        queue_path.unlink()

    write_json(run_log_path, run_log)
    write_json(report_path, report)


def main() -> None:
    requested_by = sys.argv[1].strip() if len(sys.argv) > 1 else "user"
    runbook_path = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else DEFAULT_RUNBOOK

    ensure_exists(TEMPLATE_TASK_SPEC, "task spec template")
    ensure_exists(TEMPLATE_RUN_LOG, "run log template")
    ensure_exists(TEMPLATE_REPORT, "report template")
    ensure_exists(TEMPLATE_SCREENSHOT_MANIFEST, "screenshot manifest template")
    ensure_exists(runbook_path, "execution refresh runbook")
    ensure_exists(VALIDATOR_SCRIPT, "execution refresh chain validator")

    runbook = read_json(runbook_path)
    slug = slugify(str(runbook.get("slug", "execution_refresh")))

    scaffold = create_run_scaffold(runbook_path, requested_by, slug)

    task_id = scaffold["task_id"]
    run_id = scaffold["run_id"]
    queue_path = scaffold["queue_path"]
    run_log_path = scaffold["run_log_path"]
    report_path = scaffold["report_path"]

    run_log = read_json(run_log_path)
    report = read_json(report_path)

    append_step(run_log, "load_runbook", "ok", f"Loaded runbook: {runbook_path}")

    any_stage_failed = False

    for stage in runbook.get("stages", []):
        stage_name = str(stage["name"])
        ok, note = run_stage(stage)
        append_step(run_log, f"run_stage:{stage_name}", "ok" if ok else "failed", note)
        if not ok:
            run_log.setdefault("errors", []).append(note)
            any_stage_failed = True
            break

    validator_ok, validator_note, findings, errors = run_validator(runbook_path)
    append_step(run_log, "validate_execution_chain", "ok" if validator_ok else "failed", validator_note)

    report["findings"].extend(findings)
    if errors:
        report["findings"].extend([f"ERROR: {x}" for x in errors])
        run_log.setdefault("errors", []).extend(errors)

    report["findings"].append("official_truth_changed=False")
    report["findings"].append("real_orders_allowed=False")
    report["findings"].append("source_of_truth_write_executed=False")

    if any_stage_failed or not validator_ok:
        final_status = "failed"
        summary = "Execution refresh wrapper failed due to broken stage or validator failure."
    else:
        final_status = "success"
        summary = "Execution refresh wrapper completed successfully with healthy validator result."

    write_json(run_log_path, run_log)
    write_json(report_path, report)
    finalize_run(queue_path, run_log_path, report_path, final_status, summary)

    print("OK: execution refresh wrapper finished")
    print(f"task_id={task_id}")
    print(f"run_id={run_id}")
    print(f"status={final_status}")
    print(f"run_log={run_log_path}")
    print(f"report={report_path}")
    print("source_of_truth_write_executed=False")
    print("real_orders_allowed=False")


if __name__ == "__main__":
    main()