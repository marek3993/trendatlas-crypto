from __future__ import annotations

import json
import shutil
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

PENDING_DIR = AUTOMATION_ROOT / "code_patches" / "pending"
APPROVED_DIR = AUTOMATION_ROOT / "code_patches" / "approved"
REJECTED_DIR = AUTOMATION_ROOT / "code_patches" / "rejected"
APPROVALS_DIR = AUTOMATION_ROOT / "approvals"

APPROVAL_TEMPLATE = AUTOMATION_ROOT / "templates" / "approval_record.template.json"
ALLOWED_DECISIONS = {"approved", "rejected"}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_pending_patch(patch_id: str) -> Path:
    patch_path = PENDING_DIR / f"{patch_id}.json"
    if not patch_path.exists():
        raise FileNotFoundError(f"Pending code patch not found: {patch_path}")
    return patch_path


def validate_patch_contract(patch: dict) -> None:
    target_files = patch.get("target_files", [])
    proposed_changes = patch.get("proposed_changes", [])

    if not target_files:
        raise ValueError("Code patch has no target_files")
    if not proposed_changes:
        raise ValueError("Code patch has no proposed_changes")

    patch_type = str(patch.get("patch_type", "")).strip()
    if patch_type not in {"replace_entire_file", "replace_exact_block"}:
        raise ValueError(f"Unsupported patch_type: {patch_type}")

    risk_level = str(patch.get("risk_level", "")).strip()
    if risk_level not in {"low", "approval_required"}:
        raise ValueError(f"Unsupported risk_level: {risk_level}")


def build_approval_record(patch_id: str, decision: str, approved_by: str, note: str) -> tuple[str, dict]:
    if not APPROVAL_TEMPLATE.exists():
        raise FileNotFoundError(f"Missing template: {APPROVAL_TEMPLATE}")

    approval = deepcopy(read_json(APPROVAL_TEMPLATE))
    approval_id = f"approval_{now_utc_compact()}_{patch_id.removeprefix('code_patch_')}"

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
            "Usage: python approve_code_patch.py <patch_id> <approved|rejected> [approved_by] [note]"
        )

    patch_id = sys.argv[1].strip()
    decision = sys.argv[2].strip().lower()
    approved_by = sys.argv[3].strip() if len(sys.argv) > 3 else "human"
    note = sys.argv[4].strip() if len(sys.argv) > 4 else ""

    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"Unsupported decision: {decision}")

    patch_path = find_pending_patch(patch_id)
    patch = read_json(patch_path)

    validate_patch_contract(patch)

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

    print("OK: code patch approval decision recorded")
    print(f"patch_id={patch_id}")
    print(f"decision={decision}")
    print(f"patch_path={destination_path}")
    print(f"approval_record={approval_record_path}")
    print("repo_write_executed=False")
    print("patch_applied=False")


if __name__ == "__main__":
    main()