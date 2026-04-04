from __future__ import annotations

import json
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
VALIDATION_DIR = AUTOMATION_ROOT / "code_apply" / "validation"
VALIDATION_TEMPLATE = AUTOMATION_ROOT / "templates" / "code_validation_result.template.json"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_patch(patch_id: str) -> Path:
    approved = APPROVED_DIR / f"{patch_id}.json"
    if approved.exists():
        return approved

    applied = APPLIED_DIR / f"{patch_id}.json"
    if applied.exists():
        return applied

    failed = FAILED_APPLY_DIR / f"{patch_id}.json"
    if failed.exists():
        return failed

    raise FileNotFoundError(f"Code patch not found in approved/applied/failed_apply: {patch_id}")


def resolve_target(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / path_str


def build_validation_path(patch_id: str) -> Path:
    return VALIDATION_DIR / f"{patch_id}.validation_result.json"


def validate_json_parse(target_file: Path) -> tuple[str, list[str], str, str]:
    command = [
        "python",
        "-c",
        f"import json, pathlib; json.loads(pathlib.Path(r'{str(target_file)}').read_text(encoding='utf-8'))",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    return (
        "passed" if result.returncode == 0 else "failed",
        command,
        (result.stdout or "").strip(),
        (result.stderr or "").strip(),
    )


def validate_python_py_compile(target_file: Path) -> tuple[str, list[str], str, str]:
    command = [sys.executable, "-m", "py_compile", str(target_file)]
    result = subprocess.run(command, capture_output=True, text=True)
    return (
        "passed" if result.returncode == 0 else "failed",
        command,
        (result.stdout or "").strip(),
        (result.stderr or "").strip(),
    )


def validate_file_exists_only(target_file: Path) -> tuple[str, list[str], str, str]:
    exists = target_file.exists()
    return (
        "passed" if exists else "failed",
        ["file_exists_only", str(target_file)],
        "",
        "" if exists else f"File not found: {target_file}",
    )


def run_validation(validator_type: str, target_file: Path) -> tuple[str, list[str], str, str]:
    if validator_type == "json_parse":
        return validate_json_parse(target_file)

    if validator_type == "python_py_compile":
        return validate_python_py_compile(target_file)

    if validator_type == "file_exists_only":
        return validate_file_exists_only(target_file)

    if validator_type == "manual_review_required":
        return (
            "failed",
            ["manual_review_required", str(target_file)],
            "",
            "Validator type requires manual review.",
        )

    raise ValueError(f"Unsupported validator_type: {validator_type}")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python validate_code_patch.py <patch_id>")

    patch_id = sys.argv[1].strip()

    if not VALIDATION_TEMPLATE.exists():
        raise FileNotFoundError(f"Missing template: {VALIDATION_TEMPLATE}")

    patch_path = find_patch(patch_id)
    patch = read_json(patch_path)

    validation_plan = patch.get("validation_plan", {})
    validator_type = str(validation_plan.get("validator_type", "")).strip()
    target_file = resolve_target(str(validation_plan.get("target_file", "")).strip())

    validation = deepcopy(read_json(VALIDATION_TEMPLATE))
    validation["validation_id"] = f"validation_{now_utc_compact()}_{patch_id.removeprefix('code_patch_')}"
    validation["patch_id"] = patch_id
    validation["target_file"] = str(target_file)
    validation["validator_type"] = validator_type

    status, command, stdout, stderr = run_validation(validator_type, target_file)

    validation["command"] = command
    validation["status"] = status
    validation["stdout"] = stdout
    validation["stderr"] = stderr
    validation["validated_at"] = now_utc_iso()

    validation_path = build_validation_path(patch_id)
    write_json(validation_path, validation)

    print("OK: code patch validation finished")
    print(f"patch_id={patch_id}")
    print(f"validation_result={validation_path}")
    print(f"validator_type={validator_type}")
    print(f"status={status}")

    if status != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()