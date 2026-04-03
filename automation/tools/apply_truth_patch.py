from __future__ import annotations

import difflib
import json
import shutil
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

APPROVED_PATCHES_DIR = AUTOMATION_ROOT / "truth_patches" / "approved"
APPLIED_PATCHES_DIR = AUTOMATION_ROOT / "truth_patches" / "applied"
APPROVALS_DIR = AUTOMATION_ROOT / "approvals"
RUNS_DIR = AUTOMATION_ROOT / "runs"

TRUTH_APPLY_BACKUPS_DIR = AUTOMATION_ROOT / "truth_apply" / "backups"
TRUTH_APPLY_DIFFS_DIR = AUTOMATION_ROOT / "truth_apply" / "diffs"
TRUTH_APPLY_LOGS_DIR = AUTOMATION_ROOT / "truth_apply" / "logs"

APPLY_LOG_TEMPLATE = AUTOMATION_ROOT / "templates" / "apply_log.template.json"

ALLOWED_TARGET_FILES = {
    str(PROJECT_ROOT / "source_of_truth" / "master_state.md"),
    str(PROJECT_ROOT / "source_of_truth" / "project_truth.json"),
    str(PROJECT_ROOT / "source_of_truth" / "paths_registry.json"),
    str(PROJECT_ROOT / "source_of_truth" / "current_issues.md"),
}

ALLOWED_CHANGE_TYPES = {
    "replace_entire_file",
    "replace_json_top_level_key",
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


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def find_single_file(directory: Path, suffix: str) -> Path:
    matches = list(directory.glob(f"*{suffix}"))
    if not matches:
        raise FileNotFoundError(f"No file with suffix '{suffix}' in {directory}")
    if len(matches) > 1:
        raise RuntimeError(f"Expected 1 file with suffix '{suffix}' in {directory}, found {len(matches)}")
    return matches[0]


def find_approved_patch_path(patch_id: str) -> Path:
    patch_path = APPROVED_PATCHES_DIR / f"{patch_id}.json"
    if not patch_path.exists():
        raise FileNotFoundError(f"Approved patch not found: {patch_path}")
    return patch_path


def find_approval_record_for_patch(patch_id: str) -> Path:
    matches = []
    if APPROVALS_DIR.exists():
        for path in APPROVALS_DIR.glob("*.json"):
            data = read_json(path)
            if str(data.get("patch_id", "")).strip() == patch_id and str(data.get("decision", "")).strip() == "approved":
                matches.append(path)

    if not matches:
        raise FileNotFoundError(f"No approval record with decision=approved found for patch: {patch_id}")
    if len(matches) > 1:
        matches.sort()
    return matches[-1]


def find_run_log_path(run_id: str) -> Path:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    return find_single_file(run_dir, ".run_log.json")


def ensure_apply_log_template() -> None:
    if not APPLY_LOG_TEMPLATE.exists():
        raise FileNotFoundError(f"Missing apply log template: {APPLY_LOG_TEMPLATE}")


def ensure_idempotency(patch_id: str) -> None:
    applied_patch_path = APPLIED_PATCHES_DIR / f"{patch_id}.json"
    apply_log_path = TRUTH_APPLY_LOGS_DIR / f"{patch_id}.apply_log.json"

    if applied_patch_path.exists():
        raise RuntimeError(f"Patch already applied: {applied_patch_path}")
    if apply_log_path.exists():
        raise RuntimeError(f"Apply log already exists, patch likely already applied: {apply_log_path}")


def validate_patch_contract(patch: dict) -> tuple[str, dict]:
    if str(patch.get("status", "")).strip() != "approved":
        raise ValueError("Patch status is not approved")

    target_files = patch.get("target_files", [])
    proposed_changes = patch.get("proposed_changes", [])

    if len(target_files) != 1:
        raise ValueError("v1 apply supports exactly one target_file")
    if len(proposed_changes) != 1:
        raise ValueError("v1 apply supports exactly one proposed_change")

    target_file = str(target_files[0]).strip()
    if target_file not in ALLOWED_TARGET_FILES:
        raise ValueError(f"Target file not allowed for apply: {target_file}")

    change = proposed_changes[0]
    if str(change.get("target", "")).strip() != target_file:
        raise ValueError("proposed_changes[0].target does not match target_files[0]")

    change_type = str(change.get("change_type", "")).strip()
    if change_type not in ALLOWED_CHANGE_TYPES:
        raise ValueError(f"Unsupported change_type for v1 apply: {change_type}")

    return target_file, change


def read_target_file(target_path: Path) -> str:
    if not target_path.exists():
        raise FileNotFoundError(f"Target source_of_truth file not found: {target_path}")
    return target_path.read_text(encoding="utf-8")


def build_new_content(target_path: Path, change: dict, old_content: str) -> tuple[str, str]:
    change_type = str(change["change_type"]).strip()
    payload = change.get("payload", {})

    if change_type == "replace_entire_file":
        if "new_content" not in payload:
            raise ValueError("replace_entire_file requires payload.new_content")
        return str(payload["new_content"]), change_type

    if change_type == "replace_json_top_level_key":
        if target_path.suffix.lower() != ".json":
            raise ValueError("replace_json_top_level_key is only allowed for .json targets")
        if "key" not in payload or "value" not in payload:
            raise ValueError("replace_json_top_level_key requires payload.key and payload.value")

        data = json.loads(old_content)
        key = str(payload["key"])
        data[key] = payload["value"]
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n", change_type

    raise ValueError(f"Unsupported change_type: {change_type}")


def build_backup_path(patch_id: str, target_path: Path) -> Path:
    return TRUTH_APPLY_BACKUPS_DIR / f"{patch_id}__{target_path.name}.backup"


def build_diff_path(patch_id: str) -> Path:
    return TRUTH_APPLY_DIFFS_DIR / f"{patch_id}.diff.txt"


def build_apply_log_path(patch_id: str) -> Path:
    return TRUTH_APPLY_LOGS_DIR / f"{patch_id}.apply_log.json"


def write_diff_artifact(diff_path: Path, target_file: str, old_content: str, new_content: str) -> None:
    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"{target_file} (before)",
            tofile=f"{target_file} (after)",
        )
    )

    diff_text = []
    diff_text.append(f"TARGET_FILE: {target_file}\n")
    diff_text.append("\n=== UNIFIED DIFF ===\n")
    diff_text.extend(diff_lines if diff_lines else ["(no diff)\n"])
    diff_text.append("\n=== OLD CONTENT ===\n")
    diff_text.append(old_content)
    diff_text.append("\n=== NEW CONTENT ===\n")
    diff_text.append(new_content)

    write_text(diff_path, "".join(diff_text))


def build_apply_log(
    patch: dict,
    patch_id: str,
    applied_by: str,
    target_file: str,
    change_type: str,
    backup_path: Path,
    diff_path: Path,
    status: str,
    source_of_truth_write_executed: bool,
    note: str,
) -> dict:
    ensure_apply_log_template()
    apply_log = deepcopy(read_json(APPLY_LOG_TEMPLATE))

    apply_id = f"apply_{now_utc_compact()}_{patch_id.removeprefix('patch_')}"

    apply_log["apply_id"] = apply_id
    apply_log["patch_id"] = patch_id
    apply_log["run_id"] = patch["run_id"]
    apply_log["task_id"] = patch["task_id"]
    apply_log["applied_at"] = now_utc_iso()
    apply_log["applied_by"] = applied_by
    apply_log["target_file"] = target_file
    apply_log["change_type"] = change_type
    apply_log["backup_path"] = str(backup_path)
    apply_log["diff_path"] = str(diff_path)
    apply_log["status"] = status
    apply_log["source_of_truth_write_executed"] = source_of_truth_write_executed
    apply_log["note"] = note

    return apply_log


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python apply_truth_patch.py <patch_id> [applied_by]")

    patch_id = sys.argv[1].strip()
    applied_by = sys.argv[2].strip() if len(sys.argv) > 2 else "human"

    patch_path = find_approved_patch_path(patch_id)
    patch = read_json(patch_path)

    find_approval_record_for_patch(patch_id)
    ensure_idempotency(patch_id)

    target_file, change = validate_patch_contract(patch)
    target_path = Path(target_file)

    run_log_path = find_run_log_path(str(patch["run_id"]))
    run_log = read_json(run_log_path)

    old_content = read_target_file(target_path)
    new_content, change_type = build_new_content(target_path, change, old_content)

    backup_path = build_backup_path(patch_id, target_path)
    diff_path = build_diff_path(patch_id)
    apply_log_path = build_apply_log_path(patch_id)

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    apply_log_path.parent.mkdir(parents=True, exist_ok=True)
    APPLIED_PATCHES_DIR.mkdir(parents=True, exist_ok=True)

    write_text(backup_path, old_content)
    write_diff_artifact(diff_path, target_file, old_content, new_content)

    try:
        write_text(target_path, new_content)

        patch["status"] = "applied"

        apply_log = build_apply_log(
            patch=patch,
            patch_id=patch_id,
            applied_by=applied_by,
            target_file=target_file,
            change_type=change_type,
            backup_path=backup_path,
            diff_path=diff_path,
            status="success",
            source_of_truth_write_executed=True,
            note="Approved truth patch applied successfully.",
        )
        write_json(apply_log_path, apply_log)

        append_step(
            run_log,
            action="apply_truth_patch",
            result="ok",
            note=f"Patch {patch_id} applied to {target_file}",
        )
        write_json(run_log_path, run_log)

        temp_patch_path = patch_path
        write_json(temp_patch_path, patch)
        shutil.move(str(temp_patch_path), str(APPLIED_PATCHES_DIR / patch_path.name))

        print("OK: truth patch applied")
        print(f"patch_id={patch_id}")
        print(f"target_file={target_file}")
        print(f"backup_path={backup_path}")
        print(f"diff_path={diff_path}")
        print(f"apply_log={apply_log_path}")
        print(f"run_log={run_log_path}")
        print("source_of_truth_write_executed=True")

    except Exception as exc:
        apply_log = build_apply_log(
            patch=patch,
            patch_id=patch_id,
            applied_by=applied_by,
            target_file=target_file,
            change_type=change_type,
            backup_path=backup_path,
            diff_path=diff_path,
            status="failed",
            source_of_truth_write_executed=False,
            note=f"Apply failed: {exc}",
        )
        write_json(apply_log_path, apply_log)

        append_step(
            run_log,
            action="apply_truth_patch",
            result="failed",
            note=f"Patch {patch_id} failed before successful apply: {exc}",
        )
        write_json(run_log_path, run_log)

        print("FAIL: truth patch apply failed")
        print(f"patch_id={patch_id}")
        print(f"error={exc}")
        print(f"apply_log={apply_log_path}")
        print("source_of_truth_write_executed=False")
        sys.exit(1)


if __name__ == "__main__":
    main()