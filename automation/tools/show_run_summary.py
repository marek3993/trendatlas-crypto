from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

RUNS_DIR = AUTOMATION_ROOT / "runs"
REPORTS_DIR = AUTOMATION_ROOT / "reports"
SCREENSHOTS_DIR = AUTOMATION_ROOT / "screenshots"
APPROVALS_DIR = AUTOMATION_ROOT / "approvals"

PATCH_DIRS = {
    "pending": AUTOMATION_ROOT / "truth_patches" / "pending",
    "approved": AUTOMATION_ROOT / "truth_patches" / "approved",
    "rejected": AUTOMATION_ROOT / "truth_patches" / "rejected",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_single_file(directory: Path, suffix: str) -> Path:
    matches = list(directory.glob(f"*{suffix}"))
    if not matches:
        raise FileNotFoundError(f"No file with suffix '{suffix}' in {directory}")
    if len(matches) > 1:
        raise RuntimeError(f"Expected 1 file with suffix '{suffix}' in {directory}, found {len(matches)}")
    return matches[0]


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
                    "patch_id": str(data.get("patch_id", "")),
                    "created_at": str(data.get("created_at", "")),
                    "target_files": data.get("target_files", []),
                    "path": str(path),
                }
            )

    rows.sort(key=lambda x: (x["status_bucket"], x["created_at"], x["patch_id"]))
    return rows


def collect_approval_rows(patch_ids: set[str]) -> list[dict]:
    rows: list[dict] = []

    if not APPROVALS_DIR.exists():
        return rows

    for path in sorted(APPROVALS_DIR.glob("*.json")):
        data = read_json(path)
        patch_id = str(data.get("patch_id", "")).strip()
        if patch_id not in patch_ids:
            continue

        rows.append(
            {
                "approval_id": str(data.get("approval_id", "")),
                "patch_id": patch_id,
                "decision": str(data.get("decision", "")),
                "approved_by": str(data.get("approved_by", "")),
                "decided_at": str(data.get("decided_at", "")),
                "path": str(path),
            }
        )

    rows.sort(key=lambda x: (x["decided_at"], x["approval_id"]))
    return rows


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python show_run_summary.py <run_id>")

    run_id = sys.argv[1].strip()

    run_dir = RUNS_DIR / run_id
    report_dir = REPORTS_DIR / run_id
    screenshot_dir = SCREENSHOTS_DIR / run_id

    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    if not report_dir.exists():
        raise FileNotFoundError(f"Report directory not found: {report_dir}")
    if not screenshot_dir.exists():
        raise FileNotFoundError(f"Screenshot directory not found: {screenshot_dir}")

    run_log_path = find_single_file(run_dir, ".run_log.json")
    report_path = find_single_file(report_dir, ".report.json")
    screenshot_manifest_path = find_single_file(screenshot_dir, ".screenshot_manifest.json")

    run_log = read_json(run_log_path)
    report = read_json(report_path)
    patches = collect_patch_rows(run_id)
    patch_ids = {row["patch_id"] for row in patches}
    approvals = collect_approval_rows(patch_ids)

    pending_count = sum(1 for p in patches if p["status_bucket"] == "pending")
    approved_count = sum(1 for p in patches if p["status_bucket"] == "approved")
    rejected_count = sum(1 for p in patches if p["status_bucket"] == "rejected")

    print(f"run_id={run_id}")
    print(f"task_id={run_log.get('task_id', '')}")
    print(f"status={run_log.get('status', '')}")
    print(f"started_at={run_log.get('started_at', '')}")
    print(f"ended_at={run_log.get('ended_at', '')}")
    print(f"report_summary={report.get('summary', '')}")
    print(f"report_next_action={report.get('next_action', '')}")
    print(f"pending_patch_count={pending_count}")
    print(f"approved_patch_count={approved_count}")
    print(f"rejected_patch_count={rejected_count}")
    print(f"approval_count={len(approvals)}")
    print(f"run_log_path={run_log_path}")
    print(f"report_path={report_path}")
    print(f"screenshot_manifest_path={screenshot_manifest_path}")

    for patch in patches:
        targets = " | ".join(patch["target_files"]) if patch["target_files"] else "-"
        print("---")
        print(f"patch_id={patch['patch_id']}")
        print(f"patch_status_bucket={patch['status_bucket']}")
        print(f"patch_created_at={patch['created_at']}")
        print(f"patch_target_files={targets}")
        print(f"patch_path={patch['path']}")

    for approval in approvals:
        print("---")
        print(f"approval_id={approval['approval_id']}")
        print(f"approval_patch_id={approval['patch_id']}")
        print(f"approval_decision={approval['decision']}")
        print(f"approval_approved_by={approval['approved_by']}")
        print(f"approval_decided_at={approval['decided_at']}")
        print(f"approval_path={approval['path']}")


if __name__ == "__main__":
    main()