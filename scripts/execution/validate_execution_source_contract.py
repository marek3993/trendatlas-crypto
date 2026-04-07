from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
OUTPUT_DIR = ROOT / "outputs" / "execution" / "source_contract"
LOGS_DIR = ROOT / "outputs" / "execution" / "logs"

PATHS_REGISTRY_PATH = SOURCE_OF_TRUTH_DIR / "paths_registry.json"

REPORT_PATH = OUTPUT_DIR / "execution_source_contract_report.json"
QUALITY_PATH = OUTPUT_DIR / "execution_source_contract_quality.json"
MANIFEST_PATH = OUTPUT_DIR / "execution_source_contract_manifest.json"
LOG_PATH = LOGS_DIR / "validate_execution_source_contract.log"

REQUIRED_ARTIFACT_KEYS = [
    "phase67j_winner_paper",
    "phase67j_live_status",
    "phase66g_core_paper",
    "phase66g_live_status",
    "app_freshness_report",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_utc_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(msg: str) -> None:
    print(msg)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def fail(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"Invalid JSON in {path}: {e}")
    except Exception as e:
        fail(f"Failed reading {path}: {e}")
    raise RuntimeError("unreachable")


def resolve_repo_path(raw_path: str | Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        return ROOT / candidate
    if candidate.exists():
        return candidate

    root_name = ROOT.name.lower()
    lowered_parts = [part.lower() for part in candidate.parts]
    if root_name in lowered_parts:
        root_index = lowered_parts.index(root_name)
        suffix_parts = candidate.parts[root_index + 1 :]
        if suffix_parts:
            return ROOT.joinpath(*suffix_parts)
    return candidate


def safe_file_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "exists": path.exists(),
        "path": str(path),
    }
    if not path.exists():
        return info

    stat = path.stat()
    info["size_bytes"] = stat.st_size
    info["modified_utc"] = format_utc_timestamp(stat.st_mtime)
    return info


def inspect_csv(path: Path) -> dict[str, Any]:
    result = safe_file_info(path)
    result["file_type"] = "csv"

    if not path.exists():
        return result

    header: list[str] = []
    row_count = 0
    sample_first_row: dict[str, Any] | None = None
    sample_last_row: dict[str, Any] | None = None

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            for row in reader:
                row_count += 1
                if sample_first_row is None:
                    sample_first_row = row
                sample_last_row = row
    except Exception as e:
        result["read_error"] = str(e)
        return result

    result["header"] = header
    result["row_count"] = row_count
    result["sample_first_row"] = sample_first_row
    result["sample_last_row"] = sample_last_row
    return result


def inspect_json(path: Path) -> dict[str, Any]:
    result = safe_file_info(path)
    result["file_type"] = "json"

    if not path.exists():
        return result

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        result["read_error"] = str(e)
        return result

    result["top_level_type"] = type(payload).__name__
    if isinstance(payload, dict):
        result["top_level_keys"] = list(payload.keys())
    elif isinstance(payload, list):
        result["list_length"] = len(payload)
    return result


def inspect_artifact(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return inspect_csv(path)
    if suffix == ".json":
        return inspect_json(path)
    result = safe_file_info(path)
    result["file_type"] = suffix or "unknown"
    return result


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] validate_execution_source_contract")

    registry = read_json(PATHS_REGISTRY_PATH)
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, dict):
        fail("paths_registry.json missing top-level 'artifacts' object")

    artifact_reports: dict[str, Any] = {}
    missing_registry_keys: list[str] = []
    missing_files: list[str] = []

    for artifact_key in REQUIRED_ARTIFACT_KEYS:
        artifact_entry = artifacts.get(artifact_key)
        if not isinstance(artifact_entry, dict):
            missing_registry_keys.append(artifact_key)
            continue

        canonical_path_raw = artifact_entry.get("canonical")
        if not isinstance(canonical_path_raw, str) or not canonical_path_raw.strip():
            missing_registry_keys.append(artifact_key)
            continue

        canonical_path = resolve_repo_path(canonical_path_raw)
        artifact_report = {
            "artifact_key": artifact_key,
            "owner": artifact_entry.get("owner"),
            "artifact_type": artifact_entry.get("artifact_type"),
            "truth_domain": artifact_entry.get("truth_domain"),
            "read_scope": artifact_entry.get("read_scope"),
            "write_mode": artifact_entry.get("write_mode"),
            "inspection": inspect_artifact(canonical_path),
        }

        if not canonical_path.exists():
            missing_files.append(artifact_key)

        artifact_reports[artifact_key] = artifact_report

    hard_required_for_execution = [
        "phase67j_winner_paper",
        "phase67j_live_status",
    ]

    hard_required_missing = [
        key for key in hard_required_for_execution
        if key in missing_registry_keys or key in missing_files
    ]

    report = {
        "report_type": "execution_source_contract_report",
        "generated_at_utc": utc_now_iso(),
        "source_of_truth_path": str(PATHS_REGISTRY_PATH.resolve()),
        "required_artifact_keys": REQUIRED_ARTIFACT_KEYS,
        "hard_required_for_execution": hard_required_for_execution,
        "missing_registry_keys": missing_registry_keys,
        "missing_files": missing_files,
        "hard_required_missing": hard_required_missing,
        "artifact_reports": artifact_reports,
        "contract_status": "valid" if not hard_required_missing else "invalid",
        "notes": [
            "This validator checks existence and basic shape only.",
            "It does not infer trading logic.",
            "Do not build execution intent until contract_status is valid."
        ]
    }

    quality = {
        "validator_ok": True,
        "paths_registry_present": True,
        "missing_registry_key_count": len(missing_registry_keys),
        "missing_file_count": len(missing_files),
        "hard_required_missing_count": len(hard_required_missing),
        "contract_status": report["contract_status"],
        "ready_for_intent_builder": len(hard_required_missing) == 0,
    }

    manifest = {
        "artifact_name": "execution_source_contract_validation",
        "generated_at_utc": utc_now_iso(),
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [str(PATHS_REGISTRY_PATH.resolve())],
        "output_paths": [
            str(REPORT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "started_at_utc": started_at,
        "status": "success",
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {REPORT_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[END] validate_execution_source_contract success contract_status={report['contract_status']}")


if __name__ == "__main__":
    main()
