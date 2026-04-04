from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

APPROVED_DIR = AUTOMATION_ROOT / "code_patches" / "approved"
APPLIED_DIR = AUTOMATION_ROOT / "code_patches" / "applied"
FAILED_APPLY_DIR = AUTOMATION_ROOT / "code_patches" / "failed_apply"
APPROVALS_DIR = AUTOMATION_ROOT / "approvals"

BACKUPS_DIR = AUTOMATION_ROOT / "code_apply" / "backups"
DIFFS_DIR = AUTOMATION_ROOT / "code_apply" / "diffs"
LOGS_DIR = AUTOMATION_ROOT / "code_apply" / "logs"
VALIDATION_DIR = AUTOMATION_ROOT / "code_apply" / "validation"

APPLY_LOG_TEMPLATE = AUTOMATION_ROOT / "templates" / "apply_log.template.json"
VALIDATOR_SCRIPT = AUTOMATION_ROOT / "tools" / "validate_code_patch.py"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def resolve_target(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / path_str


def find_approved_patch(patch_id: str) -> Path:
    path = APPROVED_DIR / f"{patch_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Approved code patch not found: {path}")
    return path


def ensure_idempotency(patch_id: str) -> None:
    if (APPLIED_DIR / f"{patch_id}.json").exists():
        raise RuntimeError(f"Code patch already applied: {patch_id}")
    if (LOGS_DIR / f"{patch_id}.apply_log.json").exists():
        raise RuntimeError(f"Apply log already exists for patch: {patch_id}")


def find_approval_record(patch_id: str) -> Path:
    matches = []
    for path in APPROVALS_DIR.glob("*.json"):
        try:
            data = read_json(path)
        except Exception:
            continue
        if str(data.get("patch_id", "")).strip() == patch_id and str(data.get("decision", "")).strip() == "approved":
            matches.append(path)

    if not matches:
        raise FileNotFoundError(f"No approval record with decision=approved found for code patch: {patch_id}")

    matches.sort()
    return matches[-1]


def validate_patch_contract(patch: dict) -> tuple[Path, dict]:
    if str(patch.get("status", "")).strip() != "approved":
        raise ValueError("Code patch status is not approved")

    target_files = patch.get("target_files", [])
    proposed_changes = patch.get("proposed_changes", [])
    patch_type = str(patch.get("patch_type", "")).strip()

    if len(target_files) != 1:
        raise ValueError("MVP apply_code_patch supports exactly one target file")

    if len(proposed_changes) != 1:
        raise ValueError("MVP apply_code_patch supports exactly one proposed change")

    if patch_type != "replace_entire_file":
        raise ValueError("MVP apply_code_patch currently supports only replace_entire_file")

    target_path = resolve_target(str(target_files[0]))
    change = proposed_changes[0]

    if str(change.get("change_type", "")).strip() != "replace_entire_file":
        raise ValueError("Only replace_entire_file change_type is supported in MVP")

    if resolve_target(str(change.get("target", ""))) != target_path:
        raise ValueError("proposed_changes[0].target does not match target_files[0]")

    payload = change.get("payload", {})
    if "new_content" not in payload:
        raise ValueError("replace_entire_file requires payload.new_content")

    return target_path, change


def build_backup_path(patch_id: str, target_path: Path) -> Path:
    return BACKUPS_DIR / f"{patch_id}__{target_path.name}.backup"


def build_diff_path(patch_id: str) -> Path:
    return DIFFS_DIR / f"{patch_id}.diff.txt"


def build_apply_log_path(patch_id: str) -> Path:
    return LOGS_DIR / f"{patch_id}.apply_log.json"


def read_old_content(target_path: Path) -> str:
    if target_path.exists():
        return target_path.read_text(encoding="utf-8")
    return ""


def write_diff_artifact(diff_path: Path, target_file: str, old_content: str, new_content: str) -> None:
    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"{target_file} (before)",
            tofile=f"{target_file} (after)",
        )
    )

    body = []
    body.append(f"TARGET_FILE: {target_file}\n")
    body.append("\n=== UNIFIED DIFF ===\n")
    body.extend(diff_lines if diff_lines else ["(no diff)\n"])
    body.append("\n=== OLD CONTENT ===\n")
    body.append(old_content)
    body.append("\n=== NEW CONTENT ===\n")
    body.append(new_content)
    write_text(diff_path, "".join(body))


def build_apply_log(
    patch: dict,
    patch_id: str,
    applied_by: str,
    target_file: str,
    backup_path: Path,
    diff_path: Path,
    validation_result_path: Path,
    status: str,
    write_executed: bool,
    note: str,
) -> dict:
    if not APPLY_LOG_TEMPLATE.exists():
        raise FileNotFoundError(f"Missing apply log template: {APPLY_LOG_TEMPLATE}")

    log = deepcopy(read_json(APPLY_LOG_TEMPLATE))
    log["apply_id"] = f"apply_{now_utc_compact()}_{patch_id.removeprefix('code_patch_')}"
    log["patch_id"] = patch_id
    log["run_id"] = patch.get("run_id", "")
    log["task_id"] = patch.get("task_id", "")
    log["applied_at"] = now_utc_iso()
    log["applied_by"] = applied_by
    log["target_file"] = target_file
    log["change_type"] = "replace_entire_file"
    log["backup_path"] = str(backup_path)
    log["diff_path"] = str(diff_path)
    log["status"] = status
    log["source_of_truth_write_executed"] = write_executed
    log["note"] = f"{note} | validation_result={validation_result_path}"
    return log


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python apply_code_patch.py <patch_id> [applied_by]")

    patch_id = sys.argv[1].strip()
    applied_by = sys.argv[2].strip() if len(sys.argv) > 2 else "human"

    patch_path = find_approved_patch(patch_id)
    patch = read_json(patch_path)

    find_approval_record(patch_id)
    ensure_idempotency(patch_id)

    target_path, change = validate_patch_contract(patch)
    new_content = str(change["payload"]["new_content"])
    old_content = read_old_content(target_path)

    backup_path = build_backup_path(patch_id, target_path)
    diff_path = build_diff_path(patch_id)
    apply_log_path = build_apply_log_path(patch_id)

    write_text(backup_path, old_content)
    write_diff_artifact(diff_path, str(target_path), old_content, new_content)
    write_text(target_path, new_content)

    validation_proc = subprocess.run(
        [sys.executable, str(VALIDATOR_SCRIPT), patch_id],
        capture_output=True,
        text=True,
    )

    validation_result_path = VALIDATION_DIR / f"{patch_id}.validation_result.json"
    validation_ok = validation_proc.returncode == 0 and validation_result_path.exists()

    if validation_ok:
        patch["status"] = "applied"
        write_json(patch_path, patch)
        shutil.move(str(patch_path), str(APPLIED_DIR / patch_path.name))

        apply_log = build_apply_log(
            patch=patch,
            patch_id=patch_id,
            applied_by=applied_by,
            target_file=str(target_path),
            backup_path=backup_path,
            diff_path=diff_path,
            validation_result_path=validation_result_path,
            status="success",
            write_executed=True,
            note="Code patch applied and validation passed.",
        )
        write_json(apply_log_path, apply_log)

        print("OK: code patch applied")
        print(f"patch_id={patch_id}")
        print(f"target_file={target_path}")
        print(f"backup_path={backup_path}")
        print(f"diff_path={diff_path}")
        print(f"validation_result={validation_result_path}")
        print(f"apply_log={apply_log_path}")
        print("repo_write_executed=True")
        return

    patch["status"] = "failed_apply"
    write_json(patch_path, patch)
    shutil.move(str(patch_path), str(FAILED_APPLY_DIR / patch_path.name))

    apply_log = build_apply_log(
        patch=patch,
        patch_id=patch_id,
        applied_by=applied_by,
        target_file=str(target_path),
        backup_path=backup_path,
        diff_path=diff_path,
        validation_result_path=validation_result_path,
        status="failed",
        write_executed=True,
        note=f"Code patch apply wrote file but validation failed. validator_returncode={validation_proc.returncode}",
    )
    write_json(apply_log_path, apply_log)

    print("FAIL: code patch apply failed validation")
    print(f"patch_id={patch_id}")
    print(f"target_file={target_path}")
    print(f"backup_path={backup_path}")
    print(f"diff_path={diff_path}")
    print(f"validation_result={validation_result_path}")
    print(f"apply_log={apply_log_path}")
    print("repo_write_executed=True")
    sys.exit(1)


if __name__ == "__main__":
    main()