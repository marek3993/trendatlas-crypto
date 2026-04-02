from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

SCHEMAS_DIR = AUTOMATION_ROOT / "schemas"


SCHEMA_RULES = {
    "task_spec": {
        "required": [
            "task_id",
            "task_type",
            "created_at",
            "requested_by",
            "status",
            "inputs",
            "constraints",
            "expected_outputs",
            "approval_gate",
            "source_refs",
        ],
        "enum": {
            "status": {"draft", "queued", "running", "completed", "failed", "cancelled"},
        },
    },
    "run_log": {
        "required": [
            "run_id",
            "task_id",
            "started_at",
            "ended_at",
            "status",
            "executor",
            "steps",
            "artifacts",
            "errors",
            "warnings",
        ],
        "enum": {
            "status": {"started", "success", "partial", "failed"},
        },
    },
    "report": {
        "required": [
            "report_id",
            "run_id",
            "task_id",
            "summary",
            "findings",
            "artifacts",
            "pending_truth_patch_ids",
            "next_action",
        ],
        "enum": {},
    },
    "screenshot_manifest": {
        "required": [
            "manifest_id",
            "run_id",
            "screenshots",
        ],
        "enum": {},
    },
    "pending_truth_patch": {
        "required": [
            "patch_id",
            "created_at",
            "task_id",
            "run_id",
            "target_files",
            "reason",
            "proposed_changes",
            "evidence_refs",
            "status",
        ],
        "enum": {
            "status": {"pending", "approved", "rejected", "applied"},
        },
    },
    "approval_record": {
        "required": [
            "approval_id",
            "patch_id",
            "decision",
            "approved_by",
            "decided_at",
            "note",
        ],
        "enum": {
            "decision": {"approved", "rejected"},
        },
    },
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def guess_doc_type(path: Path, data: dict) -> str:
    name = path.name

    if name.endswith(".run_log.json"):
        return "run_log"
    if name.endswith(".report.json"):
        return "report"
    if name.endswith(".screenshot_manifest.json"):
        return "screenshot_manifest"

    if "task_id" in data and "task_type" in data and "approval_gate" in data:
        return "task_spec"
    if "patch_id" in data and "proposed_changes" in data and "target_files" in data:
        return "pending_truth_patch"
    if "approval_id" in data and "decision" in data and "approved_by" in data:
        return "approval_record"

    raise ValueError(f"Unknown document type: {path}")


def validate_required(data: dict, required: list[str]) -> list[str]:
    errors: list[str] = []
    for key in required:
        if key not in data:
            errors.append(f"missing required key: {key}")
    return errors


def validate_enum(data: dict, enum_rules: dict[str, set[str]]) -> list[str]:
    errors: list[str] = []
    for key, allowed in enum_rules.items():
        if key in data and data[key] not in allowed:
            errors.append(f"invalid enum value for {key}: {data[key]} (allowed: {sorted(allowed)})")
    return errors


def validate_file(path: Path) -> tuple[bool, list[str], str]:
    data = read_json(path)
    doc_type = guess_doc_type(path, data)
    rules = SCHEMA_RULES[doc_type]

    errors: list[str] = []
    errors.extend(validate_required(data, rules["required"]))
    errors.extend(validate_enum(data, rules["enum"]))

    return len(errors) == 0, errors, doc_type


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python validate_json.py <json_file_path>"
        )

    target = Path(sys.argv[1])

    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    if not target.is_file():
        raise ValueError(f"Target is not a file: {target}")

    ok, errors, doc_type = validate_file(target)

    if ok:
        print("OK: json validation passed")
        print(f"type={doc_type}")
        print(f"file={target}")
        return

    print("FAIL: json validation failed")
    print(f"type={doc_type}")
    print(f"file={target}")
    for err in errors:
        print(f"error={err}")
    sys.exit(1)


if __name__ == "__main__":
    main()