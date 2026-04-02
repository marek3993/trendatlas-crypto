from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

TEMPLATE_PATCH = AUTOMATION_ROOT / "templates" / "pending_truth_patch.template.json"
RUNS_DIR = AUTOMATION_ROOT / "runs"
REPORTS_DIR = AUTOMATION_ROOT / "reports"
PENDING_PATCH_DIR = AUTOMATION_ROOT / "truth_patches" / "pending"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def build_patch_id(run_id: str) -> str:
    run_slug = run_id.removeprefix("run_")
    return f"patch_{now_utc_compact()}_{run_slug}"


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


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "Usage: python create_pending_truth_patch.py <run_id> <target_file> <reason> [evidence_ref]"
        )

    run_id = sys.argv[1].strip()
    target_file = sys.argv[2].strip()
    reason = sys.argv[3].strip()
    evidence_ref = sys.argv[4].strip() if len(sys.argv) > 4 else ""

    if not TEMPLATE_PATCH.exists():
        raise FileNotFoundError(f"Missing template: {TEMPLATE_PATCH}")

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
    patch = deepcopy(read_json(TEMPLATE_PATCH))

    task_id = run_log["task_id"]
    patch_id = build_patch_id(run_id)
    patch_path = PENDING_PATCH_DIR / f"{patch_id}.json"

    patch["patch_id"] = patch_id
    patch["created_at"] = now_utc_iso()
    patch["task_id"] = task_id
    patch["run_id"] = run_id
    patch["target_files"] = [target_file]
    patch["reason"] = reason
    patch["proposed_changes"] = [
        {
            "change_type": "manual_review_required",
            "target": target_file,
            "payload": {
                "note": "Automation prepared pending truth patch only. Human review/apply required."
            }
        }
    ]
    patch["evidence_refs"] = [evidence_ref] if evidence_ref else [str(report_path)]
    patch["status"] = "pending"

    write_json(patch_path, patch)

    pending_paths = run_log.setdefault("artifacts", {}).setdefault("pending_truth_patch_paths", [])
    if str(patch_path) not in pending_paths:
        pending_paths.append(str(patch_path))

    append_step(
        run_log,
        action="create_pending_truth_patch",
        result="ok",
        note=f"Pending patch created: {patch_id}",
    )

    patch_ids = report.setdefault("pending_truth_patch_ids", [])
    if patch_id not in patch_ids:
        patch_ids.append(patch_id)

    findings = report.setdefault("findings", [])
    findings.append(f"Pending truth patch created: {patch_id}")
    report["next_action"] = "human_review_patch"

    write_json(run_log_path, run_log)
    write_json(report_path, report)

    print("OK: pending truth patch created")
    print(f"run_id={run_id}")
    print(f"task_id={task_id}")
    print(f"patch_id={patch_id}")
    print(f"patch_path={patch_path}")
    print(f"run_log={run_log_path}")
    print(f"report={report_path}")


if __name__ == "__main__":
    main()