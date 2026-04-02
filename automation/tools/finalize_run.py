from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

TASKS_QUEUE_DIR = AUTOMATION_ROOT / "tasks" / "queue"
TASKS_COMPLETED_DIR = AUTOMATION_ROOT / "tasks" / "completed"
RUNS_DIR = AUTOMATION_ROOT / "runs"
REPORTS_DIR = AUTOMATION_ROOT / "reports"

ALLOWED_FINAL_STATUSES = {"success", "partial", "failed"}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_single_file(directory: Path, suffix: str) -> Path:
    matches = list(directory.glob(f"*{suffix}"))
    if not matches:
        raise FileNotFoundError(f"No file with suffix '{suffix}' in {directory}")
    if len(matches) > 1:
        raise RuntimeError(f"Expected 1 file with suffix '{suffix}' in {directory}, found {len(matches)}")
    return matches[0]


def append_step(run_log: dict, action: str, result: str, note: str) -> None:
    steps = run_log.setdefault("steps", [])
    step_index = len(steps) + 1
    steps.append(
        {
            "step_index": step_index,
            "timestamp": now_utc_iso(),
            "action": action,
            "result": result,
            "note": note,
        }
    )


def finalize_task_file(queue_task_path: Path, final_status: str) -> Path:
    task_data = read_json(queue_task_path)
    task_data["status"] = "completed" if final_status in {"success", "partial"} else "failed"

    completed_task_path = TASKS_COMPLETED_DIR / queue_task_path.name
    write_json(completed_task_path, task_data)
    queue_task_path.unlink()

    return completed_task_path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python finalize_run.py <run_id> [success|partial|failed] [summary]"
        )

    run_id = sys.argv[1].strip()
    final_status = sys.argv[2].strip().lower() if len(sys.argv) > 2 else "success"
    summary = sys.argv[3].strip() if len(sys.argv) > 3 else "Run finalized."

    if final_status not in ALLOWED_FINAL_STATUSES:
        raise ValueError(f"Unsupported final status: {final_status}")

    run_dir = RUNS_DIR / run_id
    report_dir = REPORTS_DIR / run_id

    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    if not report_dir.exists():
        raise FileNotFoundError(f"Report directory not found: {report_dir}")

    run_log_path = find_single_file(run_dir, ".run_log.json")
    report_path = find_single_file(report_dir, ".report.json")

    run_log = read_json(run_log_path)
    report = read_json(report_path)

    task_id = run_log["task_id"]
    queue_task_path = TASKS_QUEUE_DIR / f"{task_id}.json"

    if not queue_task_path.exists():
        raise FileNotFoundError(f"Queue task not found: {queue_task_path}")

    run_log["ended_at"] = now_utc_iso()
    run_log["status"] = final_status
    append_step(
        run_log,
        action="finalize_run",
        result="ok",
        note=f"Run closed with status={final_status}",
    )

    if final_status == "failed":
        run_log.setdefault("errors", []).append(summary)
    elif final_status == "partial":
        run_log.setdefault("warnings", []).append(summary)

    report["summary"] = summary
    report["next_action"] = "review_pending_outputs"
    findings = report.setdefault("findings", [])
    findings.append(f"Run finalized with status={final_status}.")

    completed_task_path = finalize_task_file(queue_task_path, final_status)

    write_json(run_log_path, run_log)
    write_json(report_path, report)

    print("OK: run finalized")
    print(f"run_id={run_id}")
    print(f"status={final_status}")
    print(f"task_id={task_id}")
    print(f"run_log={run_log_path}")
    print(f"report={report_path}")
    print(f"completed_task={completed_task_path}")


if __name__ == "__main__":
    main()