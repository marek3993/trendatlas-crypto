from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from execution.authority_publish_helpers import (
    build_authority_manifest_stub,
    build_authority_publish_state,
    publish_authority_refresh_failure,
    publish_authority_refresh_started,
    publish_authority_refresh_success,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "app_refresh_pipeline"
HEAVY_PHASE_FAST_PATH_STATE_PATH = (
    ROOT / "outputs" / "execution" / "refresh_pipeline" / "heavy_phase_fast_path_state.json"
)

LEGACY_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_legacy_ohlcv.py"
MACRO_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_global_liquidity_weekly.py"
TOP100_REFRESH_SCRIPT = ROOT / "scripts" / "refresh_phase67_top100_shortlist_ohlcv.py"
PHASE67_SCRIPT = ROOT / "scripts" / "phase67_top100_build_and_governance.py"
PHASE67B_SCRIPT = ROOT / "scripts" / "phase67b_top100_forensic_prune_and_rerun.py"
PHASE60_SCRIPT = ROOT / "phase60_selective_restore_robustness.py"
PHASE63_SCRIPT = ROOT / "scripts" / "phase63_btc_participation_overlay.py"
PHASE66G_SCRIPT = ROOT / "scripts" / "phase66g_production_candidate_live.py"
PHASE67J_SCRIPT = ROOT / "scripts" / "phase67j_final_narrow_validation_pack.py"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_app_freshness.py"
MATERIALIZE_SCRIPT = ROOT / "scripts" / "execution" / "materialize_execution_app_exports.py"
SCHEDULER_ENTRY_SCRIPT = ROOT / "scripts" / "execution" / "run_full_auto_scheduler_entry.py"
DEV_ONLY_ANOMALY_SCRIPT = ROOT / "scripts" / "dev_only_anomaly_operating_mode_runner.py"
CURRENT_STRATEGY_BUILD_SCRIPT = (
    ROOT / "scripts" / "production" / "build_current_strategy_snapshot.py"
)
CURRENT_STRATEGY_VALIDATE_SCRIPT = (
    ROOT / "scripts" / "production" / "validate_current_strategy_snapshot.py"
)
DATA_HEALTH_BUILD_SCRIPT = ROOT / "scripts" / "production" / "build_data_health_report.py"
DATA_HEALTH_VALIDATE_SCRIPT = (
    ROOT / "scripts" / "production" / "validate_data_health_report.py"
)
PHASE60_PINNED_MODEL = "phase60_restore_trx_sol_base"
PHASE63_PINNED_MODEL = "phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3"
PHASE67J_PINNED_PROFILE = "phase67j_no_neo_main"

PHASE60_OUTPUT_DIR = ROOT / "outputs" / "phase60_selective_restore_robustness"
PHASE63_OUTPUT_DIR = ROOT / "outputs" / "phase63_btc_participation_overlay"
PHASE67_OUTPUT_DIR = ROOT / "outputs" / "phase67_top100_build_and_governance"
PHASE67B_OUTPUT_DIR = ROOT / "outputs" / "phase67b_top100_forensic_prune_and_rerun"
PHASE66G_OUTPUT_DIR = ROOT / "outputs" / "phase66g_production_candidate_live"
PHASE67J_OUTPUT_DIR = ROOT / "outputs" / "phase67j_final_narrow_validation_pack"

PHASE60_PAPER = PHASE60_OUTPUT_DIR / f"{PHASE60_PINNED_MODEL}_paper.csv"
PHASE63_PAPER = PHASE63_OUTPUT_DIR / f"{PHASE63_PINNED_MODEL}_paper.csv"
PHASE63_FAST_DEPENDENCY_ARGS = [
    "--winner-only",
    "--variant-key",
    PHASE63_PINNED_MODEL,
]

PHASE67J_PAPER = ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / "phase67j_no_neo_main_paper.csv"
PHASE67J_SUMMARY = ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / "phase67j_final_narrow_validation_summary.csv"
PHASE67J_LIVE = ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / "phase67j_live_status.csv"

PHASE66G_PAPER = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_production_soft_filters_paper.csv"
PHASE66G_SUMMARY = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_production_candidate_summary.csv"
PHASE66G_LIVE = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_live_status.csv"
PHASE66G_TREND = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_trend_barometer_history.csv"
PHASE67_SUMMARY = ROOT / "outputs" / "phase67_top100_build_and_governance" / "phase67_top100_production_summary.csv"
PHASE67_ASSET_QUALITY = ROOT / "outputs" / "phase67_top100_build_and_governance" / "phase67_top100_asset_quality.csv"

BTC_RAW = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"
TOP100_DIR = ROOT / "data" / "ohlcv_phase67_top100"
SHORTLIST_PATH = ROOT / "outputs" / "phase67b_top100_forensic_prune_and_rerun" / "phase67b_asset_shortlist.csv"
MACRO_FILE = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"

FRESHNESS_REPORT = ROOT / "outputs" / "app_freshness_verification" / "app_freshness_report.json"
MACRO_REFRESH_REPORT = ROOT / "outputs" / "app_freshness_verification" / "macro_refresh_report.json"
MATERIALIZE_REPORT = ROOT / "outputs" / "execution" / "refresh_pipeline" / "materialize_execution_app_exports_report.json"
PRODUCTION_SNAPSHOT = ROOT / "outputs" / "production" / "current_strategy_snapshot.json"
PRODUCTION_TIMESERIES = ROOT / "outputs" / "production" / "current_strategy_timeseries.csv"
PRODUCTION_DIAGNOSTICS = ROOT / "outputs" / "production" / "current_strategy_diagnostics.json"
PRODUCTION_QUALITY = ROOT / "outputs" / "production" / "current_strategy_snapshot.quality.json"
PRODUCTION_MANIFEST = ROOT / "outputs" / "production" / "current_strategy_snapshot.manifest.json"
DATA_HEALTH_REPORT = ROOT / "outputs" / "production" / "data_health_report.json"
DATA_HEALTH_QUALITY = ROOT / "outputs" / "production" / "data_health_report.quality.json"
DATA_HEALTH_MANIFEST = ROOT / "outputs" / "production" / "data_health_report.manifest.json"

HEAVY_SAME_DAY_PHASES = frozenset(
    {
        "phase67_top100_build_and_governance",
        "phase67b_top100_forensic_prune_and_rerun",
        "phase66g_production_candidate_live",
        "phase67j_final_narrow_validation_pack",
    }
)
SKIPPED_FRESH = "SKIPPED_FRESH"
VALID_FAST_PATH_SOURCE_STEP_STATUSES = frozenset({"OK", SKIPPED_FRESH})

REQUIRED_OUTPUTS = [
    PHASE67J_PAPER,
    PHASE67J_SUMMARY,
    PHASE67J_LIVE,
    PHASE66G_PAPER,
    PHASE66G_SUMMARY,
    PHASE66G_LIVE,
    PHASE66G_TREND,
    PHASE67_SUMMARY,
    PHASE67_ASSET_QUALITY,
    BTC_RAW,
    MACRO_FILE,
    FRESHNESS_REPORT,
    MACRO_REFRESH_REPORT,
    MATERIALIZE_REPORT,
]

REQUIRED_PRODUCTION_OUTPUTS = [
    PRODUCTION_SNAPSHOT,
    PRODUCTION_TIMESERIES,
    PRODUCTION_DIAGNOSTICS,
    PRODUCTION_QUALITY,
    PRODUCTION_MANIFEST,
]

REQUIRED_DATA_HEALTH_OUTPUTS = [
    DATA_HEALTH_REPORT,
    DATA_HEALTH_QUALITY,
    DATA_HEALTH_MANIFEST,
]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def latest_closed_utc_date() -> str:
    return (utc_today_start() - timedelta(days=1)).date().isoformat()


def ensure_file(path: Path, label: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required {label}: {path}")


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    wanted = os.pathsep.join([str(ROOT / "src"), str(ROOT / "scripts")])
    current = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = wanted if not current else wanted + os.pathsep + current
    return env


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_last_csv_date(path: Path, date_field: str = "date") -> str:
    rows = read_csv_rows(path)
    if not rows:
        raise ValueError(f"empty_csv::{path}")

    last_value = str(rows[-1].get(date_field, "")).strip()
    if not last_value:
        raise ValueError(f"missing_date_field::{path}")
    return last_value


def read_shortlist_assets(path: Path) -> list[str]:
    rows = read_csv_rows(path)
    assets: list[str] = []
    for row in rows:
        asset = str(row.get("asset", "")).strip().upper()
        if asset:
            assets.append(asset)
    return sorted(set(assets))


def relative_display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_file_signature(path: Path) -> dict[str, Any]:
    ensure_file(path, "fast-path signature file")
    return {
        "kind": "file",
        "path": relative_display_path(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_directory_signature(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"Missing required fast-path signature directory: {path}")

    file_signatures = [
        build_file_signature(candidate)
        for candidate in sorted(
            [candidate for candidate in path.rglob("*") if candidate.is_file()],
            key=lambda candidate: relative_display_path(candidate),
        )
    ]
    if not file_signatures:
        raise ValueError(f"empty_fast_path_signature_directory::{path}")

    return {
        "kind": "directory",
        "path": relative_display_path(path),
        "file_count": len(file_signatures),
        "sha256": sha256_bytes(
            json.dumps(file_signatures, sort_keys=True).encode("utf-8")
        ),
        "files": file_signatures,
    }


def build_signature_bundle(targets: list[tuple[str, Path]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for target_kind, target_path in targets:
        if target_kind == "file":
            entries.append(build_file_signature(target_path))
        elif target_kind == "directory":
            entries.append(build_directory_signature(target_path))
        else:
            raise ValueError(f"Unsupported signature target kind: {target_kind}")

    return {
        "entry_count": len(entries),
        "sha256": sha256_bytes(json.dumps(entries, sort_keys=True).encode("utf-8")),
        "entries": entries,
    }


def build_phase67_input_targets() -> list[tuple[str, Path]]:
    return [
        ("file", PHASE60_PAPER),
        ("file", PHASE63_PAPER),
        ("directory", TOP100_DIR),
    ]


def build_phase67_top100_directory_signature_from_entries(
    file_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    sorted_file_entries = sorted(
        [dict(entry) for entry in file_entries],
        key=lambda entry: str(entry.get("path") or ""),
    )
    if not sorted_file_entries:
        raise ValueError(f"empty_phase67_top100_signature_entries::{TOP100_DIR}")

    return {
        "kind": "directory",
        "path": relative_display_path(TOP100_DIR),
        "file_count": len(sorted_file_entries),
        "sha256": sha256_bytes(
            json.dumps(sorted_file_entries, sort_keys=True).encode("utf-8")
        ),
        "files": sorted_file_entries,
    }


def is_phase67_downstream_input_entry(entry: dict[str, Any]) -> bool:
    entry_path = str(entry.get("path") or "")
    for downstream_dir in (PHASE67B_OUTPUT_DIR, PHASE66G_OUTPUT_DIR, PHASE67J_OUTPUT_DIR):
        downstream_path = relative_display_path(downstream_dir)
        if entry_path == downstream_path or entry_path.startswith(f"{downstream_path}/"):
            return True
    return False


def is_phase67_top100_input_file_entry(entry: dict[str, Any]) -> bool:
    entry_path = str(entry.get("path") or "")
    return (
        entry.get("kind") == "file"
        and entry_path.startswith(f"{relative_display_path(TOP100_DIR)}/")
    )


def is_phase67_top100_input_directory_entry(entry: dict[str, Any]) -> bool:
    return (
        entry.get("kind") == "directory"
        and str(entry.get("path") or "") == relative_display_path(TOP100_DIR)
    )


def normalize_phase67_input_signature(signature: dict[str, Any]) -> dict[str, Any]:
    entries = signature.get("entries")
    if not isinstance(entries, list):
        return signature

    normalized_entries: list[dict[str, Any]] = []
    top100_directory_entry: dict[str, Any] | None = None
    top100_file_entries: list[dict[str, Any]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue

        entry = dict(raw_entry)
        if is_phase67_downstream_input_entry(entry):
            continue
        if is_phase67_top100_input_directory_entry(entry):
            top100_directory_entry = entry
            continue
        if is_phase67_top100_input_file_entry(entry):
            top100_file_entries.append(entry)
            continue
        normalized_entries.append(entry)

    if top100_directory_entry is None and top100_file_entries:
        top100_directory_entry = build_phase67_top100_directory_signature_from_entries(
            top100_file_entries
        )
    if top100_directory_entry is not None:
        normalized_entries.append(top100_directory_entry)

    return {
        "entry_count": len(normalized_entries),
        "sha256": sha256_bytes(
            json.dumps(normalized_entries, sort_keys=True).encode("utf-8")
        ),
        "entries": normalized_entries,
    }


def normalize_input_signature_for_step(
    step_name: str,
    signature: dict[str, Any],
) -> dict[str, Any]:
    if step_name == "phase67_top100_build_and_governance":
        return normalize_phase67_input_signature(signature)
    return signature


def build_phase_fast_path_targets(step_name: str) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]]]:
    if step_name == "phase67_top100_build_and_governance":
        return build_phase67_input_targets(), [("directory", PHASE67_OUTPUT_DIR)]
    if step_name == "phase67b_top100_forensic_prune_and_rerun":
        return [("directory", PHASE67_OUTPUT_DIR)], [("directory", PHASE67B_OUTPUT_DIR)]
    if step_name == "phase66g_production_candidate_live":
        return [("directory", PHASE67B_OUTPUT_DIR)], [("directory", PHASE66G_OUTPUT_DIR)]
    if step_name == "phase67j_final_narrow_validation_pack":
        return [("directory", PHASE66G_OUTPUT_DIR)], [("directory", PHASE67J_OUTPUT_DIR)]
    raise ValueError(f"Unsupported phase fast path step: {step_name}")


def target_closed_day_from_manifest(manifest: dict[str, Any]) -> str | None:
    raw_skip_preflight = manifest.get("raw_skip_preflight")
    if isinstance(raw_skip_preflight, dict):
        target_day = raw_skip_preflight.get("target_last_closed_date")
        if isinstance(target_day, str) and target_day.strip():
            return target_day
    return None


def manifest_status_value(manifest: dict[str, Any]) -> str | None:
    for key in (
        "status",
        "main_refresh_chain_status",
        "refresh_source_status",
        "strategy_refresh_chain_status",
    ):
        value = manifest.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def find_step_status(manifest: dict[str, Any], step_name: str) -> str | None:
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict) or step.get("step_name") != step_name:
            continue
        status = step.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
        if step.get("returncode") == 0:
            return "OK"
        return None
    return None


def build_empty_heavy_phase_fast_path_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state_path": str(HEAVY_PHASE_FAST_PATH_STATE_PATH),
        "updated_at_utc": None,
        "steps": {},
    }


def load_heavy_phase_fast_path_state() -> tuple[dict[str, Any], str | None]:
    if not HEAVY_PHASE_FAST_PATH_STATE_PATH.exists():
        return build_empty_heavy_phase_fast_path_state(), None

    try:
        payload = load_json(HEAVY_PHASE_FAST_PATH_STATE_PATH)
    except Exception as exc:
        return (
            build_empty_heavy_phase_fast_path_state(),
            f"{type(exc).__name__}: {exc}",
        )

    if not isinstance(payload, dict):
        return build_empty_heavy_phase_fast_path_state(), "invalid_heavy_phase_fast_path_state_root"

    steps = payload.get("steps")
    if not isinstance(steps, dict):
        return build_empty_heavy_phase_fast_path_state(), "invalid_heavy_phase_fast_path_state_steps"

    payload.setdefault("schema_version", 1)
    payload["state_path"] = str(HEAVY_PHASE_FAST_PATH_STATE_PATH)
    payload.setdefault("updated_at_utc", None)
    return payload, None


def write_heavy_phase_fast_path_state(state_payload: dict[str, Any]) -> Path:
    HEAVY_PHASE_FAST_PATH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state_payload)
    payload["schema_version"] = int(payload.get("schema_version", 1))
    payload["state_path"] = str(HEAVY_PHASE_FAST_PATH_STATE_PATH)
    payload["updated_at_utc"] = now_utc()
    steps = payload.get("steps")
    payload["steps"] = steps if isinstance(steps, dict) else {}
    HEAVY_PHASE_FAST_PATH_STATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return HEAVY_PHASE_FAST_PATH_STATE_PATH


def build_phase_fast_path_candidate(
    *,
    candidate_source: str,
    reference: dict[str, Any],
    source_run_id: str | None,
    source_manifest_path: str | None,
    source_manifest_status: str | None,
    source_target_closed_day_utc: str | None,
    source_step_status: str | None,
    state_path: str | None = None,
) -> dict[str, Any]:
    return {
        "candidate_source": candidate_source,
        "reference": reference,
        "source_run_id": source_run_id,
        "source_manifest_path": source_manifest_path,
        "source_manifest_status": source_manifest_status,
        "source_target_closed_day_utc": source_target_closed_day_utc,
        "source_step_status": source_step_status,
        "state_path": state_path,
    }


def load_persistent_heavy_phase_fast_path_candidate(
    step_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    state_payload, load_error = load_heavy_phase_fast_path_state()
    steps = state_payload.get("steps")
    if not isinstance(steps, dict):
        return None, load_error

    reference = steps.get(step_name)
    if not isinstance(reference, dict):
        return None, load_error

    return (
        build_phase_fast_path_candidate(
            candidate_source="persistent_state",
            reference=reference,
            source_run_id=str(reference.get("source_run_id") or "").strip() or None,
            source_manifest_path=str(reference.get("source_manifest_path") or "").strip() or None,
            source_manifest_status=str(reference.get("source_manifest_status") or "").strip() or None,
            source_target_closed_day_utc=str(reference.get("target_closed_day_utc") or "").strip() or None,
            source_step_status=str(reference.get("source_step_status") or "").strip() or None,
            state_path=str(HEAVY_PHASE_FAST_PATH_STATE_PATH),
        ),
        load_error,
    )


def load_manifest_phase_fast_path_candidates(
    step_name: str,
    current_run_id: str,
    *,
    require_manifest_ok: bool,
) -> list[dict[str, Any]]:
    manifest_paths = sorted(
        OUTPUT_DIR.glob("*/app_refresh_pipeline_manifest.json"),
        key=lambda candidate: candidate.parent.name,
        reverse=True,
    )
    candidates: list[dict[str, Any]] = []
    for manifest_path in manifest_paths:
        if manifest_path.parent.name == current_run_id:
            continue
        try:
            candidate_manifest = load_json(manifest_path)
        except Exception:
            continue

        is_full_ok_manifest = (
            candidate_manifest.get("status") == "OK"
            and candidate_manifest.get("main_refresh_chain_status") == "OK"
        )
        if require_manifest_ok != is_full_ok_manifest:
            continue

        reference_map = candidate_manifest.get("phase_fast_path_reference")
        if not isinstance(reference_map, dict):
            continue

        reference = reference_map.get(step_name)
        if not isinstance(reference, dict):
            continue

        source_step_status = reference.get("source_step_status")
        if not isinstance(source_step_status, str) or not source_step_status.strip():
            source_step_status = find_step_status(candidate_manifest, step_name)

        source_run_id = (
            str(candidate_manifest.get("run_id") or manifest_path.parent.name).strip()
            or manifest_path.parent.name
        )
        candidates.append(
            build_phase_fast_path_candidate(
                candidate_source=(
                    "manifest_full_ok_reference"
                    if is_full_ok_manifest
                    else "manifest_step_reference_non_ok"
                ),
                reference=reference,
                source_run_id=source_run_id,
                source_manifest_path=str(manifest_path),
                source_manifest_status=manifest_status_value(candidate_manifest),
                source_target_closed_day_utc=target_closed_day_from_manifest(candidate_manifest),
                source_step_status=(
                    str(source_step_status).strip() if source_step_status is not None else None
                ),
            )
        )

    return candidates


def load_phase_fast_path_candidates(
    step_name: str,
    current_run_id: str,
) -> tuple[list[dict[str, Any]], str | None]:
    candidates: list[dict[str, Any]] = []
    state_candidate, state_load_error = load_persistent_heavy_phase_fast_path_candidate(step_name)
    if state_candidate is not None:
        candidates.append(state_candidate)

    candidates.extend(
        load_manifest_phase_fast_path_candidates(
            step_name,
            current_run_id,
            require_manifest_ok=False,
        )
    )
    candidates.extend(
        load_manifest_phase_fast_path_candidates(
            step_name,
            current_run_id,
            require_manifest_ok=True,
        )
    )
    return candidates, state_load_error


def build_phase_fast_path_reference(
    step_name: str,
    target_closed_day_utc: str,
) -> dict[str, Any]:
    input_targets, output_targets = build_phase_fast_path_targets(step_name)
    return {
        "step_name": step_name,
        "target_closed_day_utc": target_closed_day_utc,
        "captured_at_utc": now_utc(),
        "input_signature": build_signature_bundle(input_targets),
        "output_signature": build_signature_bundle(output_targets),
    }


def evaluate_phase_fast_path_candidate(
    candidate: dict[str, Any],
    current_reference: dict[str, Any],
    step_name: str,
    target_closed_day_utc: str,
) -> dict[str, Any]:
    evaluation: dict[str, Any] = {
        "candidate_source": candidate.get("candidate_source"),
        "source_run_id": candidate.get("source_run_id"),
        "source_manifest_path": candidate.get("source_manifest_path"),
        "source_manifest_status": candidate.get("source_manifest_status"),
        "source_target_closed_day_utc": candidate.get("source_target_closed_day_utc"),
        "source_step_status": candidate.get("source_step_status"),
        "state_path": candidate.get("state_path"),
        "status": "RUN_REQUIRED",
        "decision": "RUN",
    }

    reference = candidate.get("reference")
    if not isinstance(reference, dict):
        evaluation["reason"] = "invalid_phase_fast_path_reference"
        return evaluation

    if reference.get("step_name") != step_name:
        evaluation["reason"] = "reference_step_name_mismatch"
        return evaluation

    source_target_day = candidate.get("source_target_closed_day_utc")
    if source_target_day != target_closed_day_utc:
        evaluation["reason"] = (
            "source_manifest_target_closed_day_mismatch::"
            f"reference={source_target_day} current={target_closed_day_utc}"
        )
        return evaluation

    reference_target_day = reference.get("target_closed_day_utc")
    if reference_target_day != target_closed_day_utc:
        evaluation["reason"] = (
            "reference_target_closed_day_mismatch::"
            f"reference={reference_target_day} current={target_closed_day_utc}"
        )
        return evaluation

    reference_input_signature = reference.get("input_signature")
    reference_output_signature = reference.get("output_signature")
    if not isinstance(reference_input_signature, dict) or not isinstance(
        reference_output_signature, dict
    ):
        evaluation["reason"] = "incomplete_phase_fast_path_reference"
        return evaluation
    if not isinstance(reference_input_signature.get("sha256"), str) or not isinstance(
        reference_output_signature.get("sha256"), str
    ):
        evaluation["reason"] = "malformed_phase_fast_path_reference_signatures"
        return evaluation

    source_step_status = reference.get("source_step_status")
    if not isinstance(source_step_status, str) or not source_step_status.strip():
        source_step_status = str(candidate.get("source_step_status") or "").strip()
    evaluation["source_step_status"] = source_step_status
    if source_step_status not in VALID_FAST_PATH_SOURCE_STEP_STATUSES:
        evaluation["reason"] = "invalid_phase_fast_path_reference_source_status"
        return evaluation

    normalized_current_input_signature = normalize_input_signature_for_step(
        step_name,
        current_reference["input_signature"],
    )
    normalized_reference_input_signature = normalize_input_signature_for_step(
        step_name,
        reference_input_signature,
    )

    evaluation["current_input_signature_sha256"] = normalized_current_input_signature.get("sha256")
    evaluation["current_output_signature_sha256"] = current_reference["output_signature"]["sha256"]
    evaluation["reference_input_signature_sha256"] = normalized_reference_input_signature.get(
        "sha256"
    )
    evaluation["reference_output_signature_sha256"] = reference_output_signature.get("sha256")

    input_matches = normalized_current_input_signature == normalized_reference_input_signature
    output_matches = current_reference["output_signature"] == reference_output_signature
    evaluation["input_signature_match"] = input_matches
    evaluation["output_signature_match"] = output_matches

    if not input_matches or not output_matches:
        mismatch_reasons: list[str] = []
        if not input_matches:
            mismatch_reasons.append("input_signature_mismatch")
        if not output_matches:
            mismatch_reasons.append("output_signature_mismatch")
        evaluation["reason"] = ",".join(mismatch_reasons)
        return evaluation

    evaluation["status"] = SKIPPED_FRESH
    evaluation["decision"] = "SKIP"
    evaluation["reason"] = "same_day_reference_signatures_match"
    return evaluation


def build_phase_fast_path_proof(
    step_name: str,
    target_closed_day_utc: str,
    current_run_id: str,
) -> dict[str, Any]:
    proof: dict[str, Any] = {
        "step_name": step_name,
        "target_closed_day_utc": target_closed_day_utc,
        "status": "RUN_REQUIRED",
        "decision": "RUN",
        "reason": "phase_not_eligible",
        "heavy_phase_fast_path_state_path": str(HEAVY_PHASE_FAST_PATH_STATE_PATH),
    }

    if step_name not in HEAVY_SAME_DAY_PHASES:
        return proof

    candidates, state_load_error = load_phase_fast_path_candidates(
        step_name,
        current_run_id,
    )
    if state_load_error:
        proof["heavy_phase_fast_path_state_load_error"] = state_load_error

    if not candidates:
        proof["reason"] = "no_heavy_phase_fast_path_candidate"
        return proof

    try:
        current_reference = build_phase_fast_path_reference(step_name, target_closed_day_utc)
    except Exception as exc:
        proof["reason"] = f"phase_fast_path_proof_incomplete::{type(exc).__name__}: {exc}"
        return proof

    proof["current_input_signature_sha256"] = current_reference["input_signature"]["sha256"]
    proof["current_output_signature_sha256"] = current_reference["output_signature"]["sha256"]
    candidate_attempts: list[dict[str, Any]] = []
    persistent_state_guard: dict[str, Any] | None = None
    for index, candidate in enumerate(candidates):
        evaluation = evaluate_phase_fast_path_candidate(
            candidate,
            current_reference,
            step_name,
            target_closed_day_utc,
        )
        candidate_attempts.append(evaluation)
        if index == 0 and candidate.get("candidate_source") == "persistent_state":
            persistent_state_guard = evaluation
        if evaluation.get("status") != SKIPPED_FRESH:
            continue

        reused_reference = {
            "candidate_source": evaluation.get("candidate_source"),
            "run_id": evaluation.get("source_run_id"),
            "manifest_path": evaluation.get("source_manifest_path"),
            "manifest_status": evaluation.get("source_manifest_status"),
            "step_status": evaluation.get("source_step_status"),
            "target_closed_day_utc": evaluation.get("source_target_closed_day_utc"),
            "state_path": evaluation.get("state_path"),
        }
        proof["status"] = SKIPPED_FRESH
        proof["decision"] = "SKIP"
        proof["reason"] = str(evaluation.get("reason"))
        proof["reference_input_signature_sha256"] = evaluation.get(
            "reference_input_signature_sha256"
        )
        proof["reference_output_signature_sha256"] = evaluation.get(
            "reference_output_signature_sha256"
        )
        proof["input_signature_match"] = evaluation.get("input_signature_match")
        proof["output_signature_match"] = evaluation.get("output_signature_match")
        proof["current_reference"] = current_reference
        proof["reused_reference"] = reused_reference
        proof["latest_successful_reference"] = reused_reference
        proof["selected_candidate"] = evaluation
        proof["candidate_attempts"] = candidate_attempts
        if persistent_state_guard is not None:
            proof["persistent_state_guard"] = persistent_state_guard
        return proof

    proof["candidate_attempts"] = candidate_attempts
    if candidate_attempts:
        proof["reason"] = str(candidate_attempts[0].get("reason") or "no_reusable_phase_fast_path_candidate")
        proof["selected_candidate"] = candidate_attempts[0]
    if persistent_state_guard is not None:
        proof["persistent_state_guard"] = persistent_state_guard
    return proof


def capture_phase_fast_path_reference(
    step_name: str,
    target_closed_day_utc: str,
    source_step_status: str,
    reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        captured_reference = (
            dict(reference)
            if reference is not None
            else build_phase_fast_path_reference(step_name, target_closed_day_utc)
        )
        captured_reference["source_step_status"] = source_step_status
        return captured_reference
    except Exception as exc:
        return {
            "step_name": step_name,
            "target_closed_day_utc": target_closed_day_utc,
            "captured_at_utc": now_utc(),
            "status": "REFERENCE_CAPTURE_FAILED",
            "reason": f"{type(exc).__name__}: {exc}",
            "source_step_status": source_step_status,
        }


def build_heavy_phase_fast_path_state_entry(
    step_name: str,
    target_closed_day_utc: str,
    source_run_id: str,
    source_manifest_path: str,
    source_manifest_status: str,
    source_step_status: str,
    reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    captured_reference = capture_phase_fast_path_reference(
        step_name,
        target_closed_day_utc,
        source_step_status=source_step_status,
        reference=reference,
    )
    state_entry: dict[str, Any] = {
        "step_name": step_name,
        "target_closed_day_utc": target_closed_day_utc,
        "source_run_id": source_run_id,
        "source_manifest_path": source_manifest_path,
        "source_manifest_status": source_manifest_status,
        "source_step_status": source_step_status,
        "input_signature": captured_reference.get("input_signature"),
        "output_signature": captured_reference.get("output_signature"),
        "captured_at_utc": captured_reference.get("captured_at_utc") or now_utc(),
    }
    if "status" in captured_reference:
        state_entry["reference_status"] = captured_reference["status"]
    if "reason" in captured_reference:
        state_entry["reference_reason"] = captured_reference["reason"]
    return state_entry


def persist_heavy_phase_fast_path_state_entry(
    manifest: dict[str, Any],
    run_dir: Path,
    step_name: str,
    target_closed_day_utc: str,
    source_step_status: str,
    *,
    manifest_path: Path | None = None,
    reference: dict[str, Any] | None = None,
) -> Path:
    state_payload, _ = load_heavy_phase_fast_path_state()
    steps = state_payload.get("steps")
    if not isinstance(steps, dict):
        steps = {}
        state_payload["steps"] = steps
    steps[step_name] = build_heavy_phase_fast_path_state_entry(
        step_name,
        target_closed_day_utc,
        source_run_id=str(manifest.get("run_id") or run_dir.name),
        source_manifest_path=str(manifest_path or (run_dir / "app_refresh_pipeline_manifest.json")),
        source_manifest_status=manifest_status_value(manifest) or "RUNNING",
        source_step_status=source_step_status,
        reference=reference,
    )
    return write_heavy_phase_fast_path_state(state_payload)


def sync_heavy_phase_fast_path_state_manifest_status(
    run_id: str,
    manifest_path: Path,
    source_manifest_status: str,
) -> None:
    state_payload, _ = load_heavy_phase_fast_path_state()
    steps = state_payload.get("steps")
    if not isinstance(steps, dict):
        return

    changed = False
    for entry in steps.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("source_run_id") or "").strip() != run_id:
            continue
        if entry.get("source_manifest_path") != str(manifest_path):
            entry["source_manifest_path"] = str(manifest_path)
            changed = True
        if entry.get("source_manifest_status") != source_manifest_status:
            entry["source_manifest_status"] = source_manifest_status
            changed = True

    if changed:
        write_heavy_phase_fast_path_state(state_payload)


def append_heavy_phase_performance_regression_flag(
    manifest: dict[str, Any],
    step_name: str,
    expected_skip_reason: str,
    actual_rerun_reason: str,
) -> None:
    manifest["heavy_phase_performance_regression_flags"].append(
        {
            "code": "PERFORMANCE_REGRESSION_HEAVY_PHASE_RERUN",
            "step_name": step_name,
            "expected_skip_reason": expected_skip_reason,
            "actual_rerun_reason": actual_rerun_reason,
            "captured_at_utc": now_utc(),
        }
    )


def build_skipped_fresh_step_result(
    step_name: str,
    script_path: Path,
    step_logs_dir: Path,
    proof: dict[str, Any],
) -> dict[str, Any]:
    stdout_path = step_logs_dir / f"{step_name}.stdout.log"
    stderr_path = step_logs_dir / f"{step_name}.stderr.log"
    reused_reference = proof.get("reused_reference") or proof.get("latest_successful_reference")
    stdout_payload = {
        "step_name": step_name,
        "status": SKIPPED_FRESH,
        "reason": proof.get("reason"),
        "target_closed_day_utc": proof.get("target_closed_day_utc"),
        "reused_reference": reused_reference,
        "latest_successful_reference": proof.get("latest_successful_reference"),
        "current_input_signature_sha256": proof.get("current_input_signature_sha256"),
        "current_output_signature_sha256": proof.get("current_output_signature_sha256"),
    }
    stdout_path.write_text(
        json.dumps(stdout_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")

    return {
        "step_name": step_name,
        "script_path": str(script_path),
        "status": SKIPPED_FRESH,
        "decision": "SKIP",
        "returncode": None,
        "elapsed_sec": 0.0,
        "executed": False,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "skip_reason": proof.get("reason"),
        "target_closed_day_utc": proof.get("target_closed_day_utc"),
        "reused_reference": reused_reference,
        "latest_successful_reference": proof.get("latest_successful_reference"),
        "input_signature_sha256": proof.get("current_input_signature_sha256"),
        "output_signature_sha256": proof.get("current_output_signature_sha256"),
    }


def run_heavy_phase_with_freshness_fast_path(
    manifest: dict[str, Any],
    run_dir: Path,
    step_name: str,
    script_path: Path,
    env: dict[str, str],
    step_logs_dir: Path,
    script_args: list[str] | None = None,
) -> dict[str, Any]:
    target_closed_day_utc = str(manifest["raw_skip_preflight"]["target_last_closed_date"])
    proof = build_phase_fast_path_proof(
        step_name,
        target_closed_day_utc,
        current_run_id=run_dir.name,
    )
    decision_payload = {
        key: value for key, value in proof.items() if key != "current_reference"
    }
    manifest["phase_fast_path_decisions"][step_name] = decision_payload
    manifest["heavy_phase_fast_path_state_decisions"][step_name] = decision_payload

    if proof.get("status") == SKIPPED_FRESH:
        step_result = build_skipped_fresh_step_result(
            step_name,
            script_path,
            step_logs_dir,
            proof,
        )
        manifest["steps"].append(step_result)
        captured_reference = capture_phase_fast_path_reference(
            step_name,
            target_closed_day_utc,
            source_step_status=SKIPPED_FRESH,
            reference=proof.get("current_reference"),
        )
        manifest["phase_fast_path_reference"][step_name] = captured_reference
        manifest_path = write_manifest(run_dir, manifest)
        persist_heavy_phase_fast_path_state_entry(
            manifest,
            run_dir,
            step_name,
            target_closed_day_utc,
            SKIPPED_FRESH,
            manifest_path=manifest_path,
            reference=captured_reference,
        )
        print(f"[APP-REFRESH] step_skipped_fresh={step_name}", flush=True)
        return step_result

    persistent_state_guard = proof.get("persistent_state_guard")
    if (
        isinstance(persistent_state_guard, dict)
        and persistent_state_guard.get("status") == SKIPPED_FRESH
    ):
        append_heavy_phase_performance_regression_flag(
            manifest,
            step_name,
            expected_skip_reason=str(persistent_state_guard.get("reason")),
            actual_rerun_reason=str(proof.get("reason")),
        )

    step_result = run_step(
        step_name,
        script_path,
        env,
        step_logs_dir,
        script_args=script_args,
    )
    manifest["steps"].append(step_result)
    captured_reference = capture_phase_fast_path_reference(
        step_name,
        target_closed_day_utc,
        source_step_status="OK",
    )
    manifest["phase_fast_path_reference"][step_name] = captured_reference
    manifest_path = write_manifest(run_dir, manifest)
    persist_heavy_phase_fast_path_state_entry(
        manifest,
        run_dir,
        step_name,
        target_closed_day_utc,
        "OK",
        manifest_path=manifest_path,
        reference=captured_reference,
    )
    return step_result


def build_raw_skip_preflight(skip_legacy_refresh: bool, skip_top100_refresh: bool) -> dict[str, Any]:
    target_date = latest_closed_utc_date()
    result: dict[str, Any] = {
        "target_last_closed_date": target_date,
        "skip_legacy_refresh": skip_legacy_refresh,
        "skip_top100_refresh": skip_top100_refresh,
        "status": "NOT_NEEDED",
        "checks": {},
        "errors": [],
    }

    if not skip_legacy_refresh and not skip_top100_refresh:
        return result

    result["status"] = "OK"

    if skip_legacy_refresh:
        if not BTC_RAW.exists():
            result["errors"].append(
                f"skip_legacy_refresh_requested_but_missing::{BTC_RAW}"
            )
        else:
            btc_last_date = read_last_csv_date(BTC_RAW)
            result["checks"]["btc_raw_last_date"] = btc_last_date
            if btc_last_date < target_date:
                result["errors"].append(
                    "skip_legacy_refresh_requested_but_stale::"
                    f"btc_raw_last={btc_last_date} target_last_closed_date={target_date}"
                )

    if skip_top100_refresh:
        if not SHORTLIST_PATH.exists():
            result["errors"].append(
                f"skip_top100_refresh_requested_but_missing_shortlist::{SHORTLIST_PATH}"
            )
        else:
            assets = read_shortlist_assets(SHORTLIST_PATH)
            result["checks"]["top100_assets_checked"] = assets
            if not assets:
                result["errors"].append(
                    f"skip_top100_refresh_requested_but_empty_shortlist::{SHORTLIST_PATH}"
                )
            else:
                asset_dates: dict[str, str] = {}
                stale_assets: list[str] = []
                for asset in assets:
                    asset_path = TOP100_DIR / f"{asset}USDT_1d.csv"
                    if not asset_path.exists():
                        stale_assets.append(f"{asset}:missing")
                        continue
                    last_date = read_last_csv_date(asset_path)
                    asset_dates[asset] = last_date
                    if last_date < target_date:
                        stale_assets.append(f"{asset}:{last_date}")
                result["checks"]["top100_asset_last_dates"] = asset_dates
                if stale_assets:
                    result["errors"].append(
                        "skip_top100_refresh_requested_but_stale::"
                        f"target_last_closed_date={target_date} stale_assets={','.join(stale_assets)}"
                    )

    if result["errors"]:
        result["status"] = "FAIL"

    return result


def run_step(
    step_name: str,
    script_path: Path,
    env: dict[str, str],
    step_logs_dir: Path,
    script_args: list[str] | None = None,
) -> dict[str, Any]:
    ensure_file(script_path, f"script for step {step_name}")

    stdout_path = step_logs_dir / f"{step_name}.stdout.log"
    stderr_path = step_logs_dir / f"{step_name}.stderr.log"
    cmd = [sys.executable, str(script_path)]
    if script_args:
        cmd.extend(script_args)

    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        check=False,
    )
    elapsed = time.monotonic() - started

    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Step failed: {step_name}\n"
            f"script={script_path}\n"
            f"returncode={proc.returncode}\n"
            f"stdout_log={stdout_path}\n"
            f"stderr_log={stderr_path}"
        )

    print(f"[APP-REFRESH] step_ok={step_name} elapsed_sec={elapsed:.2f}", flush=True)

    return {
        "step_name": step_name,
        "script_path": str(script_path),
        "status": "OK",
        "returncode": proc.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }


def run_non_fatal_post_step(
    step_name: str,
    script_path: Path,
    env: dict[str, str],
    step_logs_dir: Path,
    script_args: list[str] | None = None,
    dev_only: bool = True,
    non_authoritative_outputs_only: bool = True,
) -> dict[str, Any]:
    stdout_path = step_logs_dir / f"{step_name}.stdout.log"
    stderr_path = step_logs_dir / f"{step_name}.stderr.log"
    started_at_utc = now_utc()
    cmd = [sys.executable, str(script_path)]
    if script_args:
        cmd.extend(script_args)

    try:
        ensure_file(script_path, f"script for non-fatal post step {step_name}")
        started = time.monotonic()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            check=False,
        )
        elapsed = time.monotonic() - started

        stdout_path.write_text(proc.stdout or "", encoding="utf-8")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8")

        result: dict[str, Any] = {
            "step_name": step_name,
            "script_path": str(script_path),
            "command": cmd,
            "started_at_utc": started_at_utc,
            "finished_at_utc": now_utc(),
            "elapsed_sec": round(elapsed, 3),
            "returncode": proc.returncode,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "status": "OK" if proc.returncode == 0 else "NON_FATAL_FAIL",
            "non_fatal": True,
            "dev_only": dev_only,
            "non_authoritative_outputs_only": non_authoritative_outputs_only,
        }

        if proc.returncode == 0:
            print(f"[APP-REFRESH] post_step_ok={step_name} elapsed_sec={elapsed:.2f}", flush=True)
        else:
            result["failure_details"] = {
                "reason": "non_zero_exit",
                "message": f"Non-fatal post step failed with return code {proc.returncode}.",
            }
            print(
                f"[APP-REFRESH] post_step_non_fatal_fail={step_name} returncode={proc.returncode}",
                flush=True,
            )

        return result
    except Exception as exc:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"[APP-REFRESH] post_step_non_fatal_fail={step_name} error={exc}", flush=True)
        return {
            "step_name": step_name,
            "script_path": str(script_path),
            "command": cmd,
            "started_at_utc": started_at_utc,
            "finished_at_utc": now_utc(),
            "returncode": None,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "status": "NON_FATAL_FAIL",
            "non_fatal": True,
            "dev_only": dev_only,
            "non_authoritative_outputs_only": non_authoritative_outputs_only,
            "failure_details": {
                "reason": "exception",
                "message": str(exc),
                "exception_type": type(exc).__name__,
            },
        }


def verify_required_outputs(paths: list[Path]) -> list[str]:
    missing: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            missing.append(str(path))
    return missing


def load_json(path: Path) -> dict[str, Any]:
    ensure_file(path, "json file")
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(run_dir: Path, manifest: dict[str, Any]) -> Path:
    manifest_path = run_dir / "app_refresh_pipeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def run_step_and_persist(
    manifest: dict[str, Any],
    run_dir: Path,
    step_name: str,
    script_path: Path,
    env: dict[str, str],
    step_logs_dir: Path,
    script_args: list[str] | None = None,
) -> dict[str, Any]:
    step_result = run_step(
        step_name,
        script_path,
        env,
        step_logs_dir,
        script_args=script_args,
    )
    manifest["steps"].append(step_result)
    write_manifest(run_dir, manifest)
    return step_result


def run_post_strategy_runtime_refresh(
    env: dict[str, str],
    logs_dir: Path,
    *,
    authority_run_id: str,
    target_closed_day_utc: str,
) -> dict[str, Any]:
    post_refresh_env = env.copy()
    post_refresh_env["MRV1_ALLOW_IN_PROGRESS_AUTHORITY_FOR_SAME_RUN"] = "1"
    post_refresh_env["MRV1_CURRENT_AUTHORITY_RUN_ID"] = str(authority_run_id).strip()
    post_refresh_env["MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY"] = str(
        target_closed_day_utc
    ).strip()
    return run_step(
        "run_full_auto_scheduler_entry",
        SCHEDULER_ENTRY_SCRIPT,
        post_refresh_env,
        logs_dir,
        script_args=[],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fast production refresh chain for MRV1 app")
    parser.add_argument("--skip-legacy-refresh", action="store_true")
    parser.add_argument("--skip-macro-refresh", action="store_true")
    parser.add_argument("--skip-top100-refresh", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / run_stamp
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    env = build_env()
    authority_publish_state = build_authority_publish_state(
        run_id=run_stamp,
        run_dir=run_dir,
        refresh_started_at_utc=now_utc(),
        target_closed_day_utc=latest_closed_utc_date(),
        env=env,
    )
    authority_success_published = False

    manifest: dict[str, Any] = {
        "run_id": run_stamp,
        "started_at_utc": authority_publish_state["refresh_started_at_utc"],
        "root": str(ROOT),
        "python": sys.executable,
        "mode": "fast_app_refresh",
        "skip_legacy_refresh": bool(args.skip_legacy_refresh),
        "skip_macro_refresh": bool(args.skip_macro_refresh),
        "skip_top100_refresh": bool(args.skip_top100_refresh),
        "main_refresh_chain_status": "RUNNING",
        "strategy_refresh_chain_status": "RUNNING",
        "post_strategy_runtime_refresh_status": "NOT_RUN",
        "refresh_source_status": "NOT_READY",
        "refresh_source_finished_at_utc": None,
        "phase_fast_path_reference": {},
        "phase_fast_path_decisions": {},
        "heavy_phase_fast_path_state_path": str(HEAVY_PHASE_FAST_PATH_STATE_PATH),
        "heavy_phase_fast_path_state_decisions": {},
        "heavy_phase_performance_regression_flags": [],
        "raw_skip_preflight": {
            "target_last_closed_date": latest_closed_utc_date(),
            "skip_legacy_refresh": bool(args.skip_legacy_refresh),
            "skip_top100_refresh": bool(args.skip_top100_refresh),
            "status": "NOT_RUN",
            "checks": {},
            "errors": [],
        },
        "steps": [],
        "dev_only_post_step": {
            "step_name": "dev_only_anomaly_operating_mode_runner",
            "script_path": str(DEV_ONLY_ANOMALY_SCRIPT),
            "status": "NOT_RUN",
            "non_fatal": True,
            "dev_only": True,
            "non_authoritative_outputs_only": True,
            "reason": "main_refresh_chain_not_completed",
        },
        "authority_publish": build_authority_manifest_stub(authority_publish_state),
        "required_outputs": [str(p) for p in REQUIRED_OUTPUTS],
    }
    manifest_path = write_manifest(run_dir, manifest)

    try:
        manifest["raw_skip_preflight"] = build_raw_skip_preflight(
            bool(args.skip_legacy_refresh),
            bool(args.skip_top100_refresh),
        )
        manifest_path = write_manifest(run_dir, manifest)
        if manifest["raw_skip_preflight"]["status"] == "FAIL":
            raise RuntimeError(
                "Raw refresh skip preflight failed.\n"
                + "\n".join(manifest["raw_skip_preflight"]["errors"])
            )

        authority_publish_state["target_closed_day_utc"] = manifest["raw_skip_preflight"]["target_last_closed_date"]
        authority_publish_state["latest_available_closed_utc_day"] = manifest["raw_skip_preflight"]["target_last_closed_date"]
        authority_start_result = publish_authority_refresh_started(
            authority_publish_state,
            env=env,
        )
        manifest["authority_publish"].update(
            {
                "published": bool(authority_start_result.get("published")),
                "successful_snapshot_written": bool(
                    authority_start_result.get("successful_snapshot_written")
                ),
                "status": "ATTEMPT_STARTED"
                if authority_start_result.get("published")
                else "SKIPPED",
                "reason": authority_start_result.get("reason"),
                "last_publish_result": authority_start_result,
            }
        )
        manifest_path = write_manifest(run_dir, manifest)

        if not args.skip_legacy_refresh:
            run_step_and_persist(
                manifest,
                run_dir,
                "refresh_legacy_ohlcv",
                LEGACY_REFRESH_SCRIPT,
                env,
                logs_dir,
            )

        if not args.skip_macro_refresh:
            run_step_and_persist(
                manifest,
                run_dir,
                "refresh_global_liquidity_weekly",
                MACRO_REFRESH_SCRIPT,
                env,
                logs_dir,
            )

        run_step_and_persist(
            manifest,
            run_dir,
            "phase60_selective_restore_robustness",
            PHASE60_SCRIPT,
            env,
            logs_dir,
            script_args=["--only-model", PHASE60_PINNED_MODEL],
        )
        run_step_and_persist(
            manifest,
            run_dir,
            "phase63_btc_participation_overlay",
            PHASE63_SCRIPT,
            env,
            logs_dir,
            script_args=PHASE63_FAST_DEPENDENCY_ARGS,
        )
        if not args.skip_top100_refresh:
            run_step_and_persist(
                manifest,
                run_dir,
                "refresh_phase67_top100_shortlist_ohlcv",
                TOP100_REFRESH_SCRIPT,
                env,
                logs_dir,
            )
        run_heavy_phase_with_freshness_fast_path(
            manifest,
            run_dir,
            "phase67_top100_build_and_governance",
            PHASE67_SCRIPT,
            env,
            logs_dir,
        )
        run_heavy_phase_with_freshness_fast_path(
            manifest,
            run_dir,
            "phase67b_top100_forensic_prune_and_rerun",
            PHASE67B_SCRIPT,
            env,
            logs_dir,
        )
        run_heavy_phase_with_freshness_fast_path(
            manifest,
            run_dir,
            "phase66g_production_candidate_live",
            PHASE66G_SCRIPT,
            env,
            logs_dir,
        )
        run_heavy_phase_with_freshness_fast_path(
            manifest,
            run_dir,
            "phase67j_final_narrow_validation_pack",
            PHASE67J_SCRIPT,
            env,
            logs_dir,
            script_args=["--only-profile", PHASE67J_PINNED_PROFILE],
        )
        run_step_and_persist(
            manifest,
            run_dir,
            "verify_app_freshness",
            VERIFY_SCRIPT,
            env,
            logs_dir,
        )
        manifest["refresh_source_status"] = "OK"
        manifest["refresh_source_finished_at_utc"] = now_utc()
        manifest_path = write_manifest(run_dir, manifest)
        run_step_and_persist(
            manifest,
            run_dir,
            "materialize_execution_app_exports",
            MATERIALIZE_SCRIPT,
            env,
            logs_dir,
        )

        missing_outputs = verify_required_outputs(REQUIRED_OUTPUTS)
        if missing_outputs:
            raise RuntimeError(
                "App refresh finished but required outputs are missing:\n" + "\n".join(missing_outputs)
            )

        freshness = load_json(FRESHNESS_REPORT)
        macro_report = load_json(MACRO_REFRESH_REPORT)
        run_step_and_persist(
            manifest,
            run_dir,
            "build_current_strategy_snapshot",
            CURRENT_STRATEGY_BUILD_SCRIPT,
            env,
            logs_dir,
        )
        run_step_and_persist(
            manifest,
            run_dir,
            "validate_current_strategy_snapshot",
            CURRENT_STRATEGY_VALIDATE_SCRIPT,
            env,
            logs_dir,
        )
        missing_production_outputs = verify_required_outputs(REQUIRED_PRODUCTION_OUTPUTS)
        if missing_production_outputs:
            raise RuntimeError(
                "Production Core refresh finished but required outputs are missing:\n"
                + "\n".join(missing_production_outputs)
            )

        strategy_refresh_finished_at_utc = now_utc()
        manifest["strategy_refresh_chain_finished_at_utc"] = strategy_refresh_finished_at_utc
        manifest["strategy_refresh_chain_status"] = "OK"
        manifest["freshness_report_path"] = str(FRESHNESS_REPORT)
        manifest["macro_refresh_report_path"] = str(MACRO_REFRESH_REPORT)
        manifest["freshness_report"] = freshness
        manifest["macro_refresh_report"] = macro_report
        manifest["production_core_paths"] = {
            "snapshot": str(PRODUCTION_SNAPSHOT),
            "timeseries": str(PRODUCTION_TIMESERIES),
            "diagnostics": str(PRODUCTION_DIAGNOSTICS),
            "quality": str(PRODUCTION_QUALITY),
            "manifest": str(PRODUCTION_MANIFEST),
        }
        manifest["post_strategy_runtime_refresh"] = run_post_strategy_runtime_refresh(
            env,
            logs_dir,
            authority_run_id=run_stamp,
            target_closed_day_utc=str(manifest["raw_skip_preflight"]["target_last_closed_date"]),
        )
        manifest["post_strategy_runtime_refresh_status"] = "OK"
        authority_success_result = publish_authority_refresh_success(
            authority_publish_state,
            refresh_finished_at_utc=now_utc(),
            env=env,
        )
        authority_success_published = bool(
            authority_success_result.get("successful_snapshot_written")
        )
        manifest["authority_publish"].update(
            {
                "published": bool(authority_success_result.get("published")),
                "successful_snapshot_written": bool(
                    authority_success_result.get("successful_snapshot_written")
                ),
                "status": "SUCCESS_SNAPSHOT_WRITTEN"
                if authority_success_result.get("successful_snapshot_written")
                else "SKIPPED",
                "reason": authority_success_result.get("reason"),
                "last_publish_result": authority_success_result,
            }
        )
        run_step_and_persist(
            manifest,
            run_dir,
            "build_data_health_report",
            DATA_HEALTH_BUILD_SCRIPT,
            env,
            logs_dir,
        )
        run_step_and_persist(
            manifest,
            run_dir,
            "validate_data_health_report",
            DATA_HEALTH_VALIDATE_SCRIPT,
            env,
            logs_dir,
        )
        missing_data_health_outputs = verify_required_outputs(REQUIRED_DATA_HEALTH_OUTPUTS)
        if missing_data_health_outputs:
            raise RuntimeError(
                "Data health refresh finished but required outputs are missing:\n"
                + "\n".join(missing_data_health_outputs)
            )
        data_health_report = load_json(DATA_HEALTH_REPORT)
        data_health_quality = load_json(DATA_HEALTH_QUALITY)
        manifest["data_health_paths"] = {
            "report": str(DATA_HEALTH_REPORT),
            "quality": str(DATA_HEALTH_QUALITY),
            "manifest": str(DATA_HEALTH_MANIFEST),
        }
        manifest["data_health_summary"] = data_health_report.get("summary", {})
        manifest["data_health_quality_status"] = data_health_quality.get("status")
        manifest["main_refresh_chain_finished_at_utc"] = now_utc()
        manifest["main_refresh_chain_status"] = "OK"
        manifest["status"] = "OK"
        manifest["dev_only_post_step"] = run_non_fatal_post_step(
            "dev_only_anomaly_operating_mode_runner",
            DEV_ONLY_ANOMALY_SCRIPT,
            env,
            logs_dir,
        )
        manifest["finished_at_utc"] = now_utc()

        manifest_path = write_manifest(run_dir, manifest)
        sync_heavy_phase_fast_path_state_manifest_status(
            run_stamp,
            manifest_path,
            str(manifest.get("status") or "OK"),
        )

        print("[APP-REFRESH] status=OK", flush=True)
        print(f"[APP-REFRESH] manifest={manifest_path}", flush=True)
        print(f"[APP-REFRESH] freshness_report={FRESHNESS_REPORT}", flush=True)
        print(f"[APP-REFRESH] macro_refresh_report={MACRO_REFRESH_REPORT}", flush=True)
        print(f"[APP-REFRESH] phase67j_live={PHASE67J_LIVE}", flush=True)
        print(f"[APP-REFRESH] phase67j_summary={PHASE67J_SUMMARY}", flush=True)
        print(f"[APP-REFRESH] phase67j_paper={PHASE67J_PAPER}", flush=True)

    except Exception as exc:
        manifest["finished_at_utc"] = now_utc()
        if manifest.get("strategy_refresh_chain_status") == "RUNNING":
            manifest["strategy_refresh_chain_status"] = "FAIL"
        if manifest.get("refresh_source_status") == "NOT_READY":
            manifest["refresh_source_status"] = "FAIL"
        if manifest.get("post_strategy_runtime_refresh_status") == "NOT_RUN":
            manifest["post_strategy_runtime_refresh_status"] = "FAIL"
        manifest["main_refresh_chain_status"] = "FAIL"
        manifest["status"] = "FAIL"
        manifest["error"] = str(exc)
        if not authority_success_published:
            authority_failure_result = publish_authority_refresh_failure(
                authority_publish_state,
                refresh_finished_at_utc=manifest["finished_at_utc"],
                error=str(exc),
                env=env,
            )
            manifest["authority_publish"].update(
                {
                    "published": bool(authority_failure_result.get("published")),
                    "successful_snapshot_written": bool(
                        authority_failure_result.get("successful_snapshot_written")
                    ),
                    "status": "FAILURE_ATTEMPT_WRITTEN"
                    if authority_failure_result.get("published")
                    else "SKIPPED",
                    "reason": authority_failure_result.get("reason"),
                    "last_publish_result": authority_failure_result,
                }
            )

        manifest_path = write_manifest(run_dir, manifest)
        sync_heavy_phase_fast_path_state_manifest_status(
            run_stamp,
            manifest_path,
            str(manifest.get("status") or "FAIL"),
        )

        print("[APP-REFRESH] status=FAIL", flush=True)
        print(f"[APP-REFRESH] manifest={manifest_path}", flush=True)
        print(f"[APP-REFRESH] error={exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
