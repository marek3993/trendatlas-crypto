from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

RUNS_DIR = AUTOMATION_ROOT / "runs"
REPORTS_DIR = AUTOMATION_ROOT / "reports"
APPROVALS_DIR = AUTOMATION_ROOT / "approvals"

PATCH_DIRS = {
    "pending": AUTOMATION_ROOT / "truth_patches" / "pending",
    "approved": AUTOMATION_ROOT / "truth_patches" / "approved",
    "rejected": AUTOMATION_ROOT / "truth_patches" / "rejected",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
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
    steps.append(
        {
            "step_index": len(steps) + 1,
            "timestamp": now_utc_iso(),
            "action": action,
            "result": result,
            "note": note,
        }
    )


def collect_patch_rows(run_id: str) -> list[dict]:
    rows: list[dict] = []

    for status_bucket, directory in PATCH_DIRS.items():
        if not directory.exists():
            continue

        for path in sorted(directory.glob("*.json")):
            data = read_json(path)
            if str(data.get("run_id", "")).strip() != run_id:
                continue

            rows.append(
                {
                    "status_bucket": status_bucket,
                    "patch_id": str(data.get("patch_id", "")).strip(),
                    "path": str(path),
                }
            )

    return rows


def collect_approval_patch_ids() -> set[str]:
    patch_ids: set[str] = set()

    if not APPROVALS_DIR.exists():
        return patch_ids

    for path in APPROVALS_DIR.glob("*.json"):
        data = read_json(path)
        patch_id = str(data.get("patch_id", "")).strip()
        if patch_id:
            patch_ids.add(patch_id)

    return patch_ids


def decide_next_action(patches: list[dict], approved_patch_ids: set[str]) -> str:
    if not patches:
        return "no_truth_patch_created"

    pending_count = sum(1 for p in patches if p["status_bucket"] == "pending")
    rejected_count = sum(1 for p in patches if p["status_bucket"] == "rejected")
    approved_count = sum(1 for p in patches if p["status_bucket"] == "approved")

    if pending_count > 0:
        return "human_review_patch"

    if approved_count > 0:
        approved_with_record = sum(1 for p in patches if p["status_bucket"] == "approved" and p["patch_id"] in approved_patch_ids)
        if approved_with_record == approved_count:
            return "approved_patch_ready_for_apply"
        return "approval_record_check_needed"

    if rejected_count > 0:
        return "patch_rejected_no_apply"

    return "review_pending_outputs"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python reconcile_run_state.py <run_id>")

    run_id = sys.argv[1].strip()

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

    patches = collect_patch_rows(run_id)
    approved_patch_ids = collect_approval_patch_ids()
    next_action = decide_next_action(patches, approved_patch_ids)

    report["next_action"] = next_action

    findings = report.setdefault("findings", [])
    findings.append(f"Run state reconciled. next_action={next_action}")

    append_step(
        run_log,
        action="reconcile_run_state",
        result="ok",
        note=f"Updated report.next_action to {next_action}; no source_of_truth write executed.",
    )

    write_json(report_path, report)
    write_json(run_log_path, run_log)

    print("OK: run state reconciled")
    print(f"run_id={run_id}")
    print(f"next_action={next_action}")
    print(f"report={report_path}")
    print(f"run_log={run_log_path}")
    print("source_of_truth_write_executed=False")


if __name__ == "__main__":
    main()