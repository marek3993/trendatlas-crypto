from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1")
AUTOMATION_ROOT = PROJECT_ROOT / "automation"

TEMPLATE_CODE_PATCH = AUTOMATION_ROOT / "templates" / "code_patch.template.json"
PENDING_CODE_PATCHES_DIR = AUTOMATION_ROOT / "code_patches" / "pending"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def slugify(value: str) -> str:
    out = []
    for ch in value.strip().lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "code_patch"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_target(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / path_str


def validator_for_target(target_path: Path) -> dict:
    suffix = target_path.suffix.lower()

    if suffix == ".py":
        return {
            "validator_type": "python_py_compile",
            "target_file": str(target_path)
        }

    if suffix == ".json":
        return {
            "validator_type": "json_parse",
            "target_file": str(target_path)
        }

    if suffix == ".md":
        return {
            "validator_type": "file_exists_only",
            "target_file": str(target_path)
        }

    return {
        "validator_type": "manual_review_required",
        "target_file": str(target_path)
    }


def infer_risk_level(target_path: Path) -> str:
    path_lower = str(target_path).lower().replace("/", "\\")

    gated_prefixes = [
        str(PROJECT_ROOT / "source_of_truth").lower(),
        str(PROJECT_ROOT / "scripts" / "execution").lower(),
        str(PROJECT_ROOT / "app").lower(),
    ]

    if any(path_lower.startswith(prefix) for prefix in gated_prefixes):
        return "approval_required"

    if "\\strategy" in path_lower or "\\live" in path_lower:
        return "approval_required"

    return "low"


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(
            "Usage: python create_code_patch.py <target_file> <patch_slug> <reason>"
        )

    target_file_arg = sys.argv[1].strip()
    patch_slug_arg = sys.argv[2].strip()
    reason = sys.argv[3].strip()

    target_path = resolve_target(target_file_arg)
    patch_slug = slugify(patch_slug_arg)
    patch_id = f"code_patch_{now_utc_compact()}_{patch_slug}"

    if not TEMPLATE_CODE_PATCH.exists():
        raise FileNotFoundError(f"Missing template: {TEMPLATE_CODE_PATCH}")

    patch = deepcopy(read_json(TEMPLATE_CODE_PATCH))
    patch["patch_id"] = patch_id
    patch["created_at"] = now_utc_iso()
    patch["task_id"] = f"task_{now_utc_compact()}_{patch_slug}"
    patch["run_id"] = f"run_{now_utc_compact()}_{patch_slug}"
    patch["target_files"] = [str(target_path)]
    patch["reason"] = reason
    patch["patch_type"] = "replace_entire_file"
    patch["proposed_changes"] = [
        {
            "change_type": "replace_entire_file",
            "target": str(target_path),
            "payload": {
                "new_content": ""
            }
        }
    ]
    patch["validation_plan"] = validator_for_target(target_path)
    patch["risk_level"] = infer_risk_level(target_path)
    patch["status"] = "pending"

    patch_path = PENDING_CODE_PATCHES_DIR / f"{patch_id}.json"
    write_json(patch_path, patch)

    print("OK: code patch scaffold created")
    print(f"patch_id={patch_id}")
    print(f"patch_path={patch_path}")
    print(f"target_file={target_path}")
    print(f"risk_level={patch['risk_level']}")
    print(f"validator_type={patch['validation_plan']['validator_type']}")


if __name__ == "__main__":
    main()