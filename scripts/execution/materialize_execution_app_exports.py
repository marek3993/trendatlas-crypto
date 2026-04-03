from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
APP_EXPORTS_DIR = OUTPUTS_DIR / "app_exports"
FRESHNESS_DIR = OUTPUTS_DIR / "freshness"
LOGS_DIR = OUTPUTS_DIR / "logs"

PATHS_REGISTRY_PATH = SOURCE_OF_TRUTH_DIR / "paths_registry.json"
PROJECT_TRUTH_PATH = SOURCE_OF_TRUTH_DIR / "project_truth.json"

REPORT_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_report.json"
MANIFEST_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_manifest.json"
QUALITY_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_quality.json"
LOG_PATH = LOGS_DIR / "materialize_execution_app_exports.log"

REQUIRED_ARTIFACT_KEYS = [
    "phase67j_winner_paper",
    "phase67j_live_status",
    "phase66g_core_paper",
    "phase66g_live_status",
    "app_freshness_report",
]

REQUIRED_APP_LIVE_MODE_FIELDS = [
    "live_truth_mode",
    "execution_profile",
    "leverage_mode",
    "deployment_candidate_label",
    "fallback_profile_label",
    "approval_gate_status",
]


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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


def ensure_dirs() -> None:
    APP_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    FRESHNESS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "refresh_pipeline").mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def find_existing_source(artifact_entry: dict[str, Any]) -> Path | None:
    legacy_aliases = artifact_entry.get("legacy_aliases", [])
    if not isinstance(legacy_aliases, list):
        return None

    for raw_path in legacy_aliases:
        try:
            candidate = Path(raw_path)
        except Exception:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def safe_stat(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def load_app_live_mode_contract() -> dict[str, str]:
    truth = read_json(PROJECT_TRUTH_PATH)
    contract_root = truth.get("app_live_mode_contract")
    if not isinstance(contract_root, dict):
        fail("source_of_truth/project_truth.json missing app_live_mode_contract")

    current_contract = contract_root.get("current")
    if not isinstance(current_contract, dict):
        fail("source_of_truth/project_truth.json missing app_live_mode_contract.current")

    normalized: dict[str, str] = {}
    for field in REQUIRED_APP_LIVE_MODE_FIELDS:
        value = str(current_contract.get(field, "")).strip()
        if not value:
            fail(f"app_live_mode_contract.current missing required field: {field}")
        normalized[field] = value
    return normalized


def copy_plain_artifact(source_path: Path, canonical_path: Path) -> dict[str, Any]:
    shutil.copy2(source_path, canonical_path)
    return {
        "status": "copied_from_legacy_alias",
        "source_path": str(source_path),
        "source_info": safe_stat(source_path),
        "canonical_info": safe_stat(canonical_path),
    }


def materialize_phase67j_live_status_with_contract(
    source_path: Path,
    canonical_path: Path,
    app_live_mode_contract: dict[str, str],
) -> dict[str, Any]:
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            source_header = reader.fieldnames or []
            rows = list(reader)
    except Exception as e:
        fail(f"Failed reading source CSV {source_path}: {e}")

    if len(rows) != 1:
        fail(f"Expected exactly 1 row in phase67j live status source, got {len(rows)}")

    row = dict(rows[0])
    output_header = list(source_header)
    for field in REQUIRED_APP_LIVE_MODE_FIELDS:
        if field not in output_header:
            output_header.append(field)
        row[field] = app_live_mode_contract[field]

    try:
        with canonical_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_header)
            writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        fail(f"Failed writing canonical CSV {canonical_path}: {e}")

    return {
        "status": "materialized_with_app_live_mode_contract",
        "source_path": str(source_path),
        "source_info": safe_stat(source_path),
        "canonical_info": safe_stat(canonical_path),
        "added_fields": REQUIRED_APP_LIVE_MODE_FIELDS,
    }


def main() -> None:
    ensure_dirs()
    started_at = utc_now_iso()
    log("[START] materialize_execution_app_exports")

    registry = read_json(PATHS_REGISTRY_PATH)
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, dict):
        fail("paths_registry.json missing top-level 'artifacts' object")

    app_live_mode_contract = load_app_live_mode_contract()

    report_rows: list[dict[str, Any]] = []
    missing_registry_keys: list[str] = []
    missing_legacy_sources: list[str] = []
    copied_count = 0
    transformed_count = 0
    already_present_count = 0

    for artifact_key in REQUIRED_ARTIFACT_KEYS:
        entry = artifacts.get(artifact_key)
        if not isinstance(entry, dict):
            missing_registry_keys.append(artifact_key)
            continue

        canonical_raw = entry.get("canonical")
        if not isinstance(canonical_raw, str) or not canonical_raw.strip():
            missing_registry_keys.append(artifact_key)
            continue

        canonical_path = Path(canonical_raw)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)

        row: dict[str, Any] = {
          "artifact_key": artifact_key,
          "canonical_path": str(canonical_path),
          "artifact_type": entry.get("artifact_type"),
          "owner": entry.get("owner"),
          "truth_domain": entry.get("truth_domain"),
        }

        source_path = find_existing_source(entry)
        if source_path is None and not canonical_path.exists():
            missing_legacy_sources.append(artifact_key)
            row["status"] = "missing_legacy_source"
            row["legacy_aliases"] = entry.get("legacy_aliases", [])
            report_rows.append(row)
            log(f"[MISS] no existing legacy alias for: {artifact_key}")
            continue

        if artifact_key == "phase67j_live_status":
            if source_path is None:
                fail("phase67j_live_status requires legacy source for deterministic rematerialization")
            transform_result = materialize_phase67j_live_status_with_contract(
                source_path=source_path,
                canonical_path=canonical_path,
                app_live_mode_contract=app_live_mode_contract,
            )
            transformed_count += 1
            row.update(transform_result)
            report_rows.append(row)
            log(f"[MATERIALIZED] {artifact_key}")
            log(f"              source={source_path}")
            log(f"              target={canonical_path}")
            continue

        if canonical_path.exists() and canonical_path.is_file():
            already_present_count += 1
            row["status"] = "already_present"
            row["canonical_info"] = safe_stat(canonical_path)
            report_rows.append(row)
            log(f"[OK] already present: {artifact_key} -> {canonical_path}")
            continue

        if source_path is None:
            fail(f"Missing source path for required artifact: {artifact_key}")

        copy_result = copy_plain_artifact(source_path, canonical_path)
        copied_count += 1
        row.update(copy_result)
        report_rows.append(row)
        log(f"[COPIED] {artifact_key}")
        log(f"         source={source_path}")
        log(f"         target={canonical_path}")

    hard_required = [
        "phase67j_winner_paper",
        "phase67j_live_status",
    ]

    hard_required_missing = [
        key for key in hard_required
        if key in missing_registry_keys or key in missing_legacy_sources
    ]

    report = {
        "report_type": "materialize_execution_app_exports_report",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "paths_registry_path": str(PATHS_REGISTRY_PATH.resolve()),
        "project_truth_path": str(PROJECT_TRUTH_PATH.resolve()),
        "required_artifact_keys": REQUIRED_ARTIFACT_KEYS,
        "required_app_live_mode_fields": REQUIRED_APP_LIVE_MODE_FIELDS,
        "hard_required_for_execution": hard_required,
        "missing_registry_keys": missing_registry_keys,
        "missing_legacy_sources": missing_legacy_sources,
        "hard_required_missing": hard_required_missing,
        "copied_count": copied_count,
        "transformed_count": transformed_count,
        "already_present_count": already_present_count,
        "rows": report_rows,
        "status": "success" if not hard_required_missing else "partial_failure",
        "notes": [
            "This script never fabricates strategy data.",
            "phase67j_live_status is rematerialized deterministically with official app_live_mode_contract.current fields from source_of_truth/project_truth.json.",
            "Other artifacts are copied from existing legacy aliases only."
        ],
    }

    quality = {
        "materializer_ok": True,
        "missing_registry_key_count": len(missing_registry_keys),
        "missing_legacy_source_count": len(missing_legacy_sources),
        "hard_required_missing_count": len(hard_required_missing),
        "copied_count": copied_count,
        "transformed_count": transformed_count,
        "already_present_count": already_present_count,
        "contract_ready_after_materialization": len(hard_required_missing) == 0,
        "app_live_mode_fields_written": True,
    }

    manifest = {
        "artifact_name": "materialize_execution_app_exports",
        "generated_at_utc": utc_now_iso(),
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(PATHS_REGISTRY_PATH.resolve()),
            str(PROJECT_TRUTH_PATH.resolve()),
        ],
        "output_paths": [
            str(REPORT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "status": report["status"],
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {REPORT_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[END] materialize_execution_app_exports status={report['status']}")


if __name__ == "__main__":
    main()