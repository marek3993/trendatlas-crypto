from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

RUNS_DIR = AUTOMATION_ROOT / "runs"
REPORTS_DIR = AUTOMATION_ROOT / "reports"

PATCH_DIRS = {
    "pending": AUTOMATION_ROOT / "truth_patches" / "pending",
    "approved": AUTOMATION_ROOT / "truth_patches" / "approved",
    "rejected": AUTOMATION_ROOT / "truth_patches" / "rejected",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_single_file(directory: Path, suffix: str) -> Path | None:
    matches = list(directory.glob(f"*{suffix}"))
    if not matches:
        return None
    if len(matches) > 1:
        raise RuntimeError(f"Expected 1 file with suffix '{suffix}' in {directory}, found {len(matches)}")
    return matches[0]


def build_patch_index() -> dict[str, dict[str, int]]:
    idx: dict[str, dict[str, int]] = {}

    for status, directory in PATCH_DIRS.items():
        if not directory.exists():
            continue

        for path in directory.glob("*.json"):
            data = read_json(path)
            run_id = str(data.get("run_id", "")).strip()
            if not run_id:
                continue

            if run_id not in idx:
                idx[run_id] = {"pending": 0, "approved": 0, "rejected": 0}

            idx[run_id][status] += 1

    return idx


def collect_runs(run_id_filter: str | None) -> list[dict]:
    patch_index = build_patch_index()
    rows: list[dict] = []

    if not RUNS_DIR.exists():
        return rows

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue

        run_id = run_dir.name
        if run_id_filter and run_id != run_id_filter:
            continue

        run_log_path = find_single_file(run_dir, ".run_log.json")
        if run_log_path is None:
            continue

        run_log = read_json(run_log_path)

        report_dir = REPORTS_DIR / run_id
        report_path = find_single_file(report_dir, ".report.json") if report_dir.exists() else None

        patch_counts = patch_index.get(run_id, {"pending": 0, "approved": 0, "rejected": 0})

        rows.append(
            {
                "run_id": run_id,
                "task_id": str(run_log.get("task_id", "")),
                "status": str(run_log.get("status", "")),
                "started_at": str(run_log.get("started_at", "")),
                "ended_at": str(run_log.get("ended_at", "")),
                "pending_patch_count": patch_counts["pending"],
                "approved_patch_count": patch_counts["approved"],
                "rejected_patch_count": patch_counts["rejected"],
                "run_log_path": str(run_log_path),
                "report_path": str(report_path) if report_path else "",
            }
        )

    rows.sort(key=lambda x: (x["started_at"], x["run_id"]))
    return rows


def print_rows(rows: list[dict]) -> None:
    if not rows:
        print("OK: no runs found for given filter")
        return

    print(f"count={len(rows)}")
    for row in rows:
        print("---")
        print(f"run_id={row['run_id']}")
        print(f"task_id={row['task_id']}")
        print(f"status={row['status']}")
        print(f"started_at={row['started_at']}")
        print(f"ended_at={row['ended_at']}")
        print(f"pending_patch_count={row['pending_patch_count']}")
        print(f"approved_patch_count={row['approved_patch_count']}")
        print(f"rejected_patch_count={row['rejected_patch_count']}")
        print(f"run_log_path={row['run_log_path']}")
        print(f"report_path={row['report_path']}")


def main() -> None:
    run_id_filter = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None
    rows = collect_runs(run_id_filter)
    print_rows(rows)


if __name__ == "__main__":
    main()