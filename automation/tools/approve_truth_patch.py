from __future__ import annotations

import json
import shutil
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

PENDING_DIR = AUTOMATION_ROOT / "truth_patches" / "pending"
APPROVED_DIR = AUTOMATION_ROOT / "truth_patches" / "approved"
REJECTED_DIR = AUTOMATION_ROOT / "truth_patches" / "rejected"
APPROVALS_DIR = AUTOMATION_ROOT / "approvals"
RUNS_DIR = AUTOMATION_ROOT / "runs"

APPROVAL_TEMPLATE = AUTOMATION_ROOT / "templates" / "approval_record.template.json"

ALLOWED_DECISIONS = {"approved", "rejected"}

# Toto NIE SU files, ktoré sa teraz budú meniť.
# Toto sú len files, ktoré smú byť neskôr cieľom SAMOSTATNÉHO apply kroku.
ALLOWED_APPLY_TARGET_FILES = {
    str(PROJECT_ROOT / "source_of_truth" / "master_state.md"),
    str(PROJECT_ROOT / "source_of_truth" / "project_truth.json"),
    str(PROJECT_ROOT / "source_of_truth" / "paths_registry.json"),
    str(PROJECT_ROOT / "source_of_truth" / "current_issues.md"),
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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


def find_patch_in_pending(patch_id: str) -> Path:
    patch_path = PENDING_DIR / f"{patch_id}.json"
    if not patch_path.exists():
        raise FileNotFoundError(f"Pending patch not found: {patch_path}")
    return patch_path


def find_run_log_path(run_id: str) -> Path:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    matches = list(run_dir.glob("*.run_log.json"))
    if not matches:
        raise FileNotFoundError(f"No run_log found in: {run_dir}")
    if len(matches) > 1:
        raise RuntimeError(f"Expected one run_log in {run_dir}, found {len(matches)}")
    return matches[0]


def validate_patch_targets_are_apply_eligible_only(patch: dict) -> None:
    target_files = patch.get("target_files", [])
    if not target_files:
        raise ValueError("Patch has no target_files")

    disallowed = [p for p in target_files if p not in ALLOWED_APPLY_TARGET_FILES]
    if disallowed:
        raise ValueError(f"Patch contains non-apply-eligible target_files: {disallowed}")


def build_approval_record(patch_id: str, decision: str, approved_by: str, note: str) -> tuple[str, dict]:
    if not APPROVAL_TEMPLATE.exists():
        raise FileNotFoundError(f"Missing template: {APPROVAL_TEMPLATE}")

    approval = deepcopy(read_json(APPROVAL_TEMPLATE))
    approval_id = f"approval_{now_utc_compact()}_{patch_id.removeprefix('patch_')}"

    approval["approval_id"] = approval_id
    approval["patch_id"] = patch_id
    approval["decision"] = decision
    approval["approved_by"] = approved_by
    approval["decided_at"] = now_utc_iso()
    approval["note"] = note

    return approval_id, approval


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: python approve_truth_patch.py <patch_id> <approved|rejected> [approved_by] [note]"
        )

    patch_id = sys.argv[1].strip()
    decision = sys.argv[2].strip().lower()
    approved_by = sys.argv[3].strip() if len(sys.argv) > 3 else "human"
    note = sys.argv[4].strip() if len(sys.argv) > 4 else ""

    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"Unsupported decision: {decision}")

    patch_path = find_patch_in_pending(patch_id)
    patch = read_json(patch_path)

    # Approval len overí, že patch cieli na apply-eligible SSOT files.
    # Nič do source_of_truth tu nezapisujeme.
    validate_patch_targets_are_apply_eligible_only(patch)

    run_id = patch["run_id"]
    run_log_path = find_run_log_path(run_id)
    run_log = read_json(run_log_path)

    patch["status"] = decision

    destination_dir = APPROVED_DIR if decision == "approved" else REJECTED_DIR
    destination_path = destination_dir / patch_path.name

    approval_id, approval_record = build_approval_record(
        patch_id=patch_id,
        decision=decision,
        approved_by=approved_by,
        note=note,
    )
    approval_record_path = APPROVALS_DIR / f"{approval_id}.json"

    write_json(approval_record_path, approval_record)
    write_json(patch_path, patch)
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(patch_path), str(destination_path))

    append_step(
        run_log,
        action="approve_truth_patch",
        result="ok",
        note=f"Patch {patch_id} marked as {decision}; approval recorded only; no source_of_truth write executed.",
    )
    write_json(run_log_path, run_log)

    print("OK: truth patch approval decision recorded")
    print(f"patch_id={patch_id}")
    print(f"decision={decision}")
    print(f"patch_path={destination_path}")
    print(f"approval_record={approval_record_path}")
    print(f"run_log={run_log_path}")
    print("source_of_truth_write_executed=False")
    print("patch_applied=False")
    print("patch_is_only_apply_eligible=True")


if __name__ == "__main__":
    main()