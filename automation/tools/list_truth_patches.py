from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

PATCH_DIRS = {
    "pending": AUTOMATION_ROOT / "truth_patches" / "pending",
    "approved": AUTOMATION_ROOT / "truth_patches" / "approved",
    "rejected": AUTOMATION_ROOT / "truth_patches" / "rejected",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_patches(status_filter: str | None, run_id_filter: str | None) -> list[dict]:
    rows: list[dict] = []

    for status, directory in PATCH_DIRS.items():
        if status_filter and status != status_filter:
            continue
        if not directory.exists():
            continue

        for path in sorted(directory.glob("*.json")):
            data = read_json(path)

            run_id = str(data.get("run_id", ""))
            if run_id_filter and run_id != run_id_filter:
                continue

            rows.append(
                {
                    "status_bucket": status,
                    "patch_id": str(data.get("patch_id", "")),
                    "run_id": run_id,
                    "task_id": str(data.get("task_id", "")),
                    "created_at": str(data.get("created_at", "")),
                    "target_files": data.get("target_files", []),
                    "path": str(path),
                }
            )

    rows.sort(key=lambda x: (x["status_bucket"], x["created_at"], x["patch_id"]))
    return rows


def print_rows(rows: list[dict]) -> None:
    if not rows:
        print("OK: no truth patches found for given filter")
        return

    print(f"count={len(rows)}")
    for row in rows:
        targets = " | ".join(row["target_files"]) if row["target_files"] else "-"
        print("---")
        print(f"status_bucket={row['status_bucket']}")
        print(f"patch_id={row['patch_id']}")
        print(f"run_id={row['run_id']}")
        print(f"task_id={row['task_id']}")
        print(f"created_at={row['created_at']}")
        print(f"target_files={targets}")
        print(f"path={row['path']}")


def main() -> None:
    status_filter = sys.argv[1].strip().lower() if len(sys.argv) > 1 and sys.argv[1].strip() else None
    run_id_filter = sys.argv[2].strip() if len(sys.argv) > 2 and sys.argv[2].strip() else None

    allowed_statuses = {"pending", "approved", "rejected"}
    if status_filter and status_filter not in allowed_statuses:
        raise ValueError(f"Unsupported status filter: {status_filter}")

    rows = collect_patches(status_filter, run_id_filter)
    print_rows(rows)


if __name__ == "__main__":
    main()