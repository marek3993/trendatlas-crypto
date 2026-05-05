from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.market_regime_v1.phase1_time_semantics import (
    ATTEMPT_STATUSES,
    ATTEMPT_STATUS_ARTIFACT_TYPE,
    CURRENTNESS_STATUSES,
    SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
)
from scripts.execution.runtime_path_resolution import (
    format_path_resolution_message,
    resolve_runtime_path,
)
from scripts.execution.current_strategy_root_contract import (
    load_current_main_strategy_root_contract,
    validate_authoritative_dependency_closure,
    validate_current_main_strategy_source_files_against_snapshot,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
OUTPUT_DIR = ROOT / "outputs" / "execution" / "source_contract"
LOGS_DIR = ROOT / "outputs" / "execution" / "logs"
AUTHORITY_DIR = ROOT / "outputs" / "execution" / "authority"
PRODUCTION_DIR = ROOT / "outputs" / "production"

PATHS_REGISTRY_PATH = SOURCE_OF_TRUTH_DIR / "paths_registry.json"

REPORT_PATH = OUTPUT_DIR / "execution_source_contract_report.json"
QUALITY_PATH = OUTPUT_DIR / "execution_source_contract_quality.json"
MANIFEST_PATH = OUTPUT_DIR / "execution_source_contract_manifest.json"
LOG_PATH = LOGS_DIR / "validate_execution_source_contract.log"
LATEST_SUCCESSFUL_SNAPSHOT_PATH = AUTHORITY_DIR / "latest_successful_snapshot.json"
LATEST_ATTEMPT_STATUS_PATH = AUTHORITY_DIR / "latest_attempt_status.json"
PRODUCTION_SNAPSHOT_PATH = PRODUCTION_DIR / "current_strategy_snapshot.json"
STRATEGY_CHAIN_FRESHNESS_REPORT_PATH = (
    ROOT / "outputs" / "validation" / "reports" / "strategy_chain_freshness_report.json"
)

REQUIRED_ARTIFACT_KEYS = [
    "authority_latest_successful_snapshot",
    "authority_latest_attempt_status",
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
    resolved_path, _diagnostic = resolve_runtime_path(raw_path, root=ROOT, context="validate")
    return resolved_path


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


def normalize_path_text(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip()


def normalize_iso_day_text(value: Any, *, context: str, errors: list[str]) -> str | None:
    text = str(value or "").strip()
    if not text:
        errors.append(f"{context} is missing")
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        errors.append(f"{context} is not an ISO day: {value}")
        return None
    return text


def require_keys(payload: dict[str, Any], keys: list[str], context: str, errors: list[str]) -> None:
    for key in keys:
        if key not in payload:
            errors.append(f"{context} missing required field: {key}")


def require_dict(payload: dict[str, Any], key: str, context: str, errors: list[str]) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        errors.append(f"{context}.{key} must be an object")
        return {}
    return value


def validate_repo_relative_file(path_value: Any, context: str, errors: list[str]) -> None:
    if not isinstance(path_value, str) or not path_value.strip():
        errors.append(f"{context} missing path string")
        return
    path = resolve_repo_path(path_value)
    if not path.exists() or not path.is_file():
        errors.append(f"{context} points to missing file: {path_value}")


def forbid_keys(payload: dict[str, Any], keys: list[str], context: str, errors: list[str]) -> None:
    for key in keys:
        if key in payload:
            errors.append(f"{context} contains forbidden legacy alias: {key}")


def require_non_empty(payload: dict[str, Any], keys: list[str], context: str, errors: list[str]) -> None:
    for key in keys:
        value = payload.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"{context}.{key} must be present and non-empty")


def validate_product_snapshot_payload(
    payload: dict[str, Any],
    *,
    context: str,
    source_path: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("snapshot_type") != "app_product_snapshot":
        errors.append(f"{context} has wrong snapshot_type")

    require_keys(
        payload,
        [
            "schema_version",
            "app_export_generated_at_utc",
            "product_name",
            "page_scope",
            "main_strategy_model",
            "strategy_last_closed_day",
            "freshness_target_closed_day",
            "freshness",
            "main_strategy_metrics",
            "live_public_state",
            "trend_barometer_summary",
            "chart_source_paths",
            "benchmark_source_path",
            "source_metadata",
        ],
        context,
        errors,
    )
    require_non_empty(
        payload,
        ["strategy_last_closed_day", "freshness_target_closed_day", "app_export_generated_at_utc"],
        context,
        errors,
    )
    forbid_keys(
        payload,
        ["generated_at_utc", "latest_closed_day"],
        context,
        errors,
    )

    freshness = require_dict(payload, "freshness", context, errors)
    forbid_keys(
        freshness,
        ["latest_closed_utc_date"],
        f"{context}.freshness",
        errors,
    )

    metrics = require_dict(payload, "main_strategy_metrics", context, errors)
    require_keys(
        metrics,
        [
            "model",
            "total_return_pct",
            "cagr_pct",
            "max_drawdown_pct",
            "since2023_cagr_pct",
            "since2025_cagr_pct",
            "sharpe",
            "sortino",
            "switch_count",
            "cash_days_pct",
            "btc_days_pct",
        ],
        f"{context}.main_strategy_metrics",
        errors,
    )

    trend = require_dict(payload, "trend_barometer_summary", context, errors)
    require_keys(
        trend,
        ["trend_score", "trend_state_label", "buy_threshold", "trend_calc_date"],
        f"{context}.trend_barometer_summary",
        errors,
    )

    live_state = require_dict(payload, "live_public_state", context, errors)
    require_keys(
        live_state,
        ["held_asset_public", "execution_state", "live_truth_mode", "execution_profile", "leverage_mode"],
        f"{context}.live_public_state",
        errors,
    )

    chart_paths = require_dict(payload, "chart_source_paths", context, errors)
    validate_repo_relative_file(chart_paths.get("main_strategy"), f"{context}.chart_source_paths.main_strategy", errors)
    validate_repo_relative_file(payload.get("benchmark_source_path"), f"{context}.benchmark_source_path", errors)
    if payload.get("trend_history_source_path"):
        validate_repo_relative_file(payload.get("trend_history_source_path"), f"{context}.trend_history_source_path", errors)

    source_metadata = require_dict(payload, "source_metadata", context, errors)
    require_keys(
        source_metadata,
        [
            "main_strategy_metrics",
            "strategy_last_closed_day",
            "freshness_target_closed_day",
            "app_export_generated_at_utc",
            "freshness",
            "trend_barometer_summary",
            "chart_source_paths",
            "benchmark_source_path",
        ],
        f"{context}.source_metadata",
        errors,
    )

    return {
        "path": str(source_path.resolve()),
        "inspection": {
            "exists": True,
            "path": str(source_path.resolve()),
            "file_type": "json",
            "top_level_type": type(payload).__name__,
            "top_level_keys": list(payload.keys()),
        },
        "errors": errors,
        "valid": not errors,
    }


def validate_runtime_snapshot_payload(
    payload: dict[str, Any],
    *,
    context: str,
    source_path: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("snapshot_type") != "app_runtime_snapshot":
        errors.append(f"{context} has wrong snapshot_type")

    require_keys(
        payload,
        [
            "schema_version",
            "app_export_generated_at_utc",
            "page_scope",
            "runtime_last_sync_utc",
            "account_snapshot_as_of_utc",
            "dry_run_generated_at_utc",
            "gate_generated_at_utc",
            "runtime_table_snapshot",
            "account_observability_contract",
            "execution_status",
            "account_snapshot_summary",
            "dry_run_summary",
            "gate_summary",
            "runtime_health_summary",
            "execution_mode_posture",
            "live_order_policy_summary",
            "source_metadata",
        ],
        context,
        errors,
    )
    require_non_empty(
        payload,
        [
            "runtime_last_sync_utc",
            "account_snapshot_as_of_utc",
            "dry_run_generated_at_utc",
            "gate_generated_at_utc",
            "app_export_generated_at_utc",
        ],
        context,
        errors,
    )
    forbid_keys(
        payload,
        ["generated_at_utc", "last_wallet_sync"],
        context,
        errors,
    )

    execution_status = require_dict(payload, "execution_status", context, errors)
    forbid_keys(
        execution_status,
        ["as_of_utc"],
        f"{context}.execution_status",
        errors,
    )

    account_summary = require_dict(payload, "account_snapshot_summary", context, errors)
    require_keys(
        account_summary,
        [
            "status",
            "provider",
            "account_address",
            "mode",
            "account_equity_usd",
            "available_balance_usd",
            "positions_count",
            "open_orders_count",
            "recent_fills_count",
        ],
        f"{context}.account_snapshot_summary",
        errors,
    )
    forbid_keys(
        account_summary,
        ["as_of_utc"],
        f"{context}.account_snapshot_summary",
        errors,
    )

    dry_run = require_dict(payload, "dry_run_summary", context, errors)
    require_keys(
        dry_run,
        ["signal_id", "target_asset", "recommended_action", "simulated_order", "guardrails"],
        f"{context}.dry_run_summary",
        errors,
    )
    forbid_keys(
        dry_run,
        ["generated_at_utc"],
        f"{context}.dry_run_summary",
        errors,
    )

    gate = require_dict(payload, "gate_summary", context, errors)
    require_keys(
        gate,
        ["signal_id", "target_asset", "status", "would_place_real_order", "checks"],
        f"{context}.gate_summary",
        errors,
    )
    forbid_keys(
        gate,
        ["generated_at_utc"],
        f"{context}.gate_summary",
        errors,
    )

    runtime_health = require_dict(payload, "runtime_health_summary", context, errors)
    require_keys(
        runtime_health,
        ["status", "run_active", "stop_reason", "execution_mode_guardrail"],
        f"{context}.runtime_health_summary",
        errors,
    )
    forbid_keys(
        runtime_health,
        ["last_success_utc"],
        f"{context}.runtime_health_summary",
        errors,
    )

    posture = require_dict(payload, "execution_mode_posture", context, errors)
    require_keys(
        posture,
        ["mode", "trading_enabled", "dry_run_enabled", "kill_switch", "trading_operation_mode"],
        f"{context}.execution_mode_posture",
        errors,
    )

    runtime_table = require_dict(payload, "runtime_table_snapshot", context, errors)
    require_keys(
        runtime_table,
        [
            "last_pi_update_utc",
            "last_pc_refresh_utc",
            "last_refresh_status",
            "last_refresh_run_id",
            "last_wallet_sync_utc",
            "currentness_state",
            "currentness_reason",
            "source_metadata",
            "evaluated_at_utc",
        ],
        f"{context}.runtime_table_snapshot",
        errors,
    )
    runtime_table_source_metadata = require_dict(
        runtime_table,
        "source_metadata",
        f"{context}.runtime_table_snapshot",
        errors,
    )
    require_keys(
        runtime_table_source_metadata,
        [
            "last_pi_update_utc",
            "last_pc_refresh_utc",
            "last_refresh_status",
            "last_refresh_run_id",
            "last_wallet_sync_utc",
            "currentness_state",
            "currentness_reason",
        ],
        f"{context}.runtime_table_snapshot.source_metadata",
        errors,
    )

    currentness_state = str(runtime_table.get("currentness_state") or "").strip()
    if currentness_state not in {
        "current",
        "stale",
        "not_run_today",
        "failed_latest_refresh",
        "refresh_in_progress",
        "refresh_failed",
        "missing_runtime_artifact",
        "missing_authority_artifact",
    }:
        errors.append(
            f"{context}.runtime_table_snapshot currentness_state has unsupported value"
        )

    currentness_reason = str(runtime_table.get("currentness_reason") or "").strip()
    if not currentness_reason:
        errors.append(
            f"{context}.runtime_table_snapshot currentness_reason must be non-empty"
        )

    last_refresh_status = str(runtime_table.get("last_refresh_status") or "").strip()
    last_refresh_run_id = runtime_table.get("last_refresh_run_id")
    last_pc_refresh_utc = runtime_table.get("last_pc_refresh_utc")
    if last_refresh_status == "not_run":
        if last_refresh_run_id is not None:
            errors.append(
                f"{context}.runtime_table_snapshot last_refresh_run_id must be null when last_refresh_status=not_run"
            )
        if last_pc_refresh_utc is not None:
            errors.append(
                f"{context}.runtime_table_snapshot last_pc_refresh_utc must be null when last_refresh_status=not_run"
            )

    if last_refresh_status and last_refresh_status != "not_run":
        status_meta = runtime_table_source_metadata.get("last_refresh_status") or {}
        run_id_meta = runtime_table_source_metadata.get("last_refresh_run_id") or {}
        pc_refresh_meta = runtime_table_source_metadata.get("last_pc_refresh_utc") or {}
        status_path = status_meta.get("path")
        run_id_path = run_id_meta.get("path")
        pc_refresh_path = pc_refresh_meta.get("path")
        if not status_path or status_path != run_id_path or status_path != pc_refresh_path:
            errors.append(
                f"{context}.runtime_table_snapshot refresh status/run_id/pc refresh must resolve from the same manifest source"
            )

    source_metadata = require_dict(payload, "source_metadata", context, errors)
    require_keys(
        source_metadata,
        [
            "runtime_table_snapshot",
            "execution_status",
            "account_snapshot_summary",
            "dry_run_summary",
            "gate_summary",
            "runtime_health_summary",
            "execution_mode_posture",
            "runtime_last_sync_utc",
            "account_snapshot_as_of_utc",
            "dry_run_generated_at_utc",
            "gate_generated_at_utc",
        ],
        f"{context}.source_metadata",
        errors,
    )
    forbid_keys(
        source_metadata,
        ["last_wallet_sync"],
        f"{context}.source_metadata",
        errors,
    )

    return {
        "path": str(source_path.resolve()),
        "inspection": {
            "exists": True,
            "path": str(source_path.resolve()),
            "file_type": "json",
            "top_level_type": type(payload).__name__,
            "top_level_keys": list(payload.keys()),
        },
        "errors": errors,
        "valid": not errors,
    }


def validate_authority_latest_successful_snapshot() -> dict[str, Any]:
    errors: list[str] = []
    payload = read_json(LATEST_SUCCESSFUL_SNAPSHOT_PATH)
    if payload.get("artifact_type") != SUCCESS_SNAPSHOT_ARTIFACT_TYPE:
        errors.append("latest_successful_snapshot.json has wrong artifact_type")

    require_keys(
        payload,
        [
            "artifact_type",
            "schema_version",
            "target_closed_day_utc",
            "latest_available_closed_utc_day",
            "refresh_started_at_utc",
            "refresh_finished_at_utc",
            "display_timezone",
            "latest_authoritative_attempt_status",
            "strategy_artifact_closed_day_utc",
            "currentness_status",
            "currentness_reason",
            "generated_at_utc",
            "generated_at_local",
            "run_id",
            "authority_role",
            "automatic_producer_id",
            "manual_recovery_only",
            "github_actions_role",
            "source_manifest_path",
            "app_product_snapshot",
        ],
        "authority_latest_successful_snapshot",
        errors,
    )
    require_non_empty(
        payload,
        [
            "target_closed_day_utc",
            "latest_available_closed_utc_day",
            "refresh_started_at_utc",
            "refresh_finished_at_utc",
            "generated_at_utc",
            "run_id",
            "authority_role",
            "automatic_producer_id",
            "source_manifest_path",
            "currentness_status",
            "currentness_reason",
            "strategy_artifact_closed_day_utc",
        ],
        "authority_latest_successful_snapshot",
        errors,
    )

    attempt_status = str(payload.get("latest_authoritative_attempt_status") or "").strip().lower()
    if attempt_status != "success":
        errors.append("authority_latest_successful_snapshot.latest_authoritative_attempt_status must be success")
    currentness_status = str(payload.get("currentness_status") or "").strip()
    if currentness_status not in CURRENTNESS_STATUSES:
        errors.append("authority_latest_successful_snapshot.currentness_status has unsupported value")
    if str(payload.get("automatic_producer_id") or "").strip().lower() != "raspberry_pi":
        errors.append("authority_latest_successful_snapshot.automatic_producer_id must be raspberry_pi")
    if payload.get("manual_recovery_only") is not True:
        errors.append("authority_latest_successful_snapshot.manual_recovery_only must be true")
    if str(payload.get("github_actions_role") or "").strip() != "validation_only":
        errors.append("authority_latest_successful_snapshot.github_actions_role must be validation_only")

    app_product_snapshot = payload.get("app_product_snapshot")
    if not isinstance(app_product_snapshot, dict):
        errors.append("authority_latest_successful_snapshot.app_product_snapshot must be an object")
    else:
        nested_report = validate_product_snapshot_payload(
            app_product_snapshot,
            context="authority_latest_successful_snapshot.app_product_snapshot",
            source_path=LATEST_SUCCESSFUL_SNAPSHOT_PATH,
        )
        errors.extend(nested_report["errors"])
        try:
            current_strategy_contract = load_current_main_strategy_root_contract()
            validate_current_main_strategy_source_files_against_snapshot(
                app_product_snapshot,
                current_strategy_contract,
                context="authority_latest_successful_snapshot canonical source validation blocked:",
            )
            validate_authoritative_dependency_closure(
                app_product_snapshot,
                current_strategy_contract,
                root=ROOT,
                context="authority_latest_successful_snapshot closure validation blocked:",
            )
        except Exception as exc:
            errors.append(str(exc))
        strategy_last_closed_day = str(app_product_snapshot.get("strategy_last_closed_day") or "").strip()
        freshness_target_closed_day = str(app_product_snapshot.get("freshness_target_closed_day") or "").strip()
        target_closed_day_utc = str(payload.get("target_closed_day_utc") or "").strip()
        latest_available_closed_utc_day = str(payload.get("latest_available_closed_utc_day") or "").strip()
        if strategy_last_closed_day and target_closed_day_utc and strategy_last_closed_day != target_closed_day_utc:
            errors.append(
                "authority_latest_successful_snapshot target_closed_day_utc diverged from "
                f"app_product_snapshot.strategy_last_closed_day (target={target_closed_day_utc} strategy={strategy_last_closed_day})"
            )
        if freshness_target_closed_day and target_closed_day_utc and freshness_target_closed_day != target_closed_day_utc:
            errors.append(
                "authority_latest_successful_snapshot target_closed_day_utc diverged from "
                f"app_product_snapshot.freshness_target_closed_day (target={target_closed_day_utc} freshness={freshness_target_closed_day})"
            )
        if latest_available_closed_utc_day and target_closed_day_utc and latest_available_closed_utc_day != target_closed_day_utc:
            errors.append(
                "authority_latest_successful_snapshot latest_available_closed_utc_day diverged from "
                f"target_closed_day_utc (target={target_closed_day_utc} latest_available={latest_available_closed_utc_day})"
            )

    app_runtime_snapshot = payload.get("app_runtime_snapshot")
    nested_runtime_report = None
    if isinstance(app_runtime_snapshot, dict):
        nested_runtime_report = validate_runtime_snapshot_payload(
            app_runtime_snapshot,
            context="authority_latest_successful_snapshot.app_runtime_snapshot",
            source_path=LATEST_SUCCESSFUL_SNAPSHOT_PATH,
        )
        errors.extend(nested_runtime_report["errors"])

    return {
        "path": str(LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
        "inspection": inspect_json(LATEST_SUCCESSFUL_SNAPSHOT_PATH),
        "errors": errors,
        "valid": not errors,
    }


def validate_authority_latest_attempt_status() -> dict[str, Any]:
    errors: list[str] = []
    payload = read_json(LATEST_ATTEMPT_STATUS_PATH)
    if payload.get("artifact_type") != ATTEMPT_STATUS_ARTIFACT_TYPE:
        errors.append("latest_attempt_status.json has wrong artifact_type")

    require_keys(
        payload,
        [
            "artifact_type",
            "schema_version",
            "target_closed_day_utc",
            "latest_available_closed_utc_day",
            "refresh_started_at_utc",
            "display_timezone",
            "latest_authoritative_attempt_status",
            "currentness_status",
            "currentness_reason",
            "generated_at_utc",
            "generated_at_local",
            "run_id",
            "authority_role",
            "automatic_producer_id",
            "manual_recovery_only",
            "github_actions_role",
            "source_manifest_path",
            "app_runtime_snapshot",
        ],
        "authority_latest_attempt_status",
        errors,
    )
    require_non_empty(
        payload,
        [
            "target_closed_day_utc",
            "latest_available_closed_utc_day",
            "refresh_started_at_utc",
            "generated_at_utc",
            "run_id",
            "authority_role",
            "automatic_producer_id",
            "source_manifest_path",
            "currentness_status",
            "currentness_reason",
        ],
        "authority_latest_attempt_status",
        errors,
    )

    attempt_status = str(payload.get("latest_authoritative_attempt_status") or "").strip().lower()
    if attempt_status not in ATTEMPT_STATUSES:
        errors.append("authority_latest_attempt_status.latest_authoritative_attempt_status has unsupported value")
    if attempt_status != "in_progress" and not str(payload.get("refresh_finished_at_utc") or "").strip():
        errors.append("authority_latest_attempt_status.refresh_finished_at_utc is required when attempt is not in_progress")
    currentness_status = str(payload.get("currentness_status") or "").strip()
    if currentness_status not in CURRENTNESS_STATUSES:
        errors.append("authority_latest_attempt_status.currentness_status has unsupported value")
    if str(payload.get("automatic_producer_id") or "").strip().lower() != "raspberry_pi":
        errors.append("authority_latest_attempt_status.automatic_producer_id must be raspberry_pi")
    if payload.get("manual_recovery_only") is not True:
        errors.append("authority_latest_attempt_status.manual_recovery_only must be true")
    if str(payload.get("github_actions_role") or "").strip() != "validation_only":
        errors.append("authority_latest_attempt_status.github_actions_role must be validation_only")

    app_runtime_snapshot = payload.get("app_runtime_snapshot")
    if not isinstance(app_runtime_snapshot, dict):
        errors.append("authority_latest_attempt_status.app_runtime_snapshot must be an object")
    else:
        nested_report = validate_runtime_snapshot_payload(
            app_runtime_snapshot,
            context="authority_latest_attempt_status.app_runtime_snapshot",
            source_path=LATEST_ATTEMPT_STATUS_PATH,
        )
        errors.extend(nested_report["errors"])
        target_closed_day_utc = str(payload.get("target_closed_day_utc") or "").strip()
        latest_available_closed_utc_date = str(app_runtime_snapshot.get("latest_available_closed_utc_date") or "").strip()
        latest_strategy_artifact_date = str(app_runtime_snapshot.get("latest_strategy_artifact_date") or "").strip()
        if latest_available_closed_utc_date and target_closed_day_utc and latest_available_closed_utc_date != target_closed_day_utc:
            errors.append(
                "authority_latest_attempt_status target_closed_day_utc diverged from "
                f"app_runtime_snapshot.latest_available_closed_utc_date (target={target_closed_day_utc} runtime={latest_available_closed_utc_date})"
            )
        if latest_strategy_artifact_date and target_closed_day_utc and latest_strategy_artifact_date != target_closed_day_utc:
            errors.append(
                "authority_latest_attempt_status target_closed_day_utc diverged from "
                f"app_runtime_snapshot.latest_strategy_artifact_date (target={target_closed_day_utc} strategy={latest_strategy_artifact_date})"
            )

    app_product_snapshot = payload.get("app_product_snapshot")
    if isinstance(app_product_snapshot, dict):
        nested_product_report = validate_product_snapshot_payload(
            app_product_snapshot,
            context="authority_latest_attempt_status.app_product_snapshot",
            source_path=LATEST_ATTEMPT_STATUS_PATH,
        )
        errors.extend(nested_product_report["errors"])
        try:
            current_strategy_contract = load_current_main_strategy_root_contract()
            validate_current_main_strategy_source_files_against_snapshot(
                app_product_snapshot,
                current_strategy_contract,
                context="authority_latest_attempt_status canonical source validation blocked:",
            )
            validate_authoritative_dependency_closure(
                app_product_snapshot,
                current_strategy_contract,
                root=ROOT,
                context="authority_latest_attempt_status closure validation blocked:",
            )
        except Exception as exc:
            errors.append(str(exc))
        strategy_last_closed_day = str(app_product_snapshot.get("strategy_last_closed_day") or "").strip()
        target_closed_day_utc = str(payload.get("target_closed_day_utc") or "").strip()
        if strategy_last_closed_day and target_closed_day_utc and strategy_last_closed_day != target_closed_day_utc:
            errors.append(
                "authority_latest_attempt_status target_closed_day_utc diverged from "
                f"app_product_snapshot.strategy_last_closed_day (target={target_closed_day_utc} strategy={strategy_last_closed_day})"
            )

    return {
        "path": str(LATEST_ATTEMPT_STATUS_PATH.resolve()),
        "inspection": inspect_json(LATEST_ATTEMPT_STATUS_PATH),
        "errors": errors,
        "valid": not errors,
    }


def validate_strategy_chain_freshness_monitoring() -> dict[str, Any]:
    errors: list[str] = []
    inspection = inspect_json(STRATEGY_CHAIN_FRESHNESS_REPORT_PATH)
    if not STRATEGY_CHAIN_FRESHNESS_REPORT_PATH.exists():
        errors.append(
            "strategy_chain_freshness_report.json is missing; monitoring target cannot be verified fail-closed"
        )
        return {
            "path": str(STRATEGY_CHAIN_FRESHNESS_REPORT_PATH.resolve()),
            "inspection": inspection,
            "errors": errors,
            "valid": False,
        }

    payload = read_json(STRATEGY_CHAIN_FRESHNESS_REPORT_PATH)
    current_strategy_contract = load_current_main_strategy_root_contract(root=ROOT, require_files=False)
    expected_model = str(current_strategy_contract["main_strategy_model"]).strip()
    expected_paper_path = normalize_path_text(current_strategy_contract["canonical_paper_source_path"])

    monitored_model = str(payload.get("current_main_strategy_model_monitored") or "").strip()
    if not monitored_model:
        errors.append(
            "strategy_chain_freshness_report.json missing current_main_strategy_model_monitored"
        )
    elif monitored_model != expected_model:
        errors.append(
            "strategy_chain_freshness_report.json monitored model diverged from SSOT "
            f"(expected={expected_model} actual={monitored_model})"
        )

    monitored_paper_path = normalize_path_text(
        payload.get("current_main_strategy_paper_path_monitored")
    )
    if not monitored_paper_path:
        errors.append(
            "strategy_chain_freshness_report.json missing current_main_strategy_paper_path_monitored"
        )
    elif monitored_paper_path != expected_paper_path:
        errors.append(
            "strategy_chain_freshness_report.json monitored paper path diverged from SSOT "
            f"(expected={expected_paper_path} actual={monitored_paper_path})"
        )

    return {
        "path": str(STRATEGY_CHAIN_FRESHNESS_REPORT_PATH.resolve()),
        "inspection": inspection,
        "errors": errors,
        "valid": not errors,
    }


def validate_production_current_strategy_snapshot() -> dict[str, Any]:
    errors: list[str] = []
    inspection = inspect_json(PRODUCTION_SNAPSHOT_PATH)
    if not PRODUCTION_SNAPSHOT_PATH.exists():
        errors.append(
            "outputs/production/current_strategy_snapshot.json is missing; execution signal truth cannot be verified"
        )
        return {
            "path": str(PRODUCTION_SNAPSHOT_PATH.resolve()),
            "inspection": inspection,
            "errors": errors,
            "valid": False,
        }

    payload = read_json(PRODUCTION_SNAPSHOT_PATH)
    if str(payload.get("artifact_type") or "").strip() != "current_strategy_snapshot":
        errors.append("production current_strategy_snapshot has wrong artifact_type")

    closed_day = normalize_iso_day_text(
        payload.get("closed_day"),
        context="production current_strategy_snapshot.closed_day",
        errors=errors,
    )
    strategy_version = str(payload.get("strategy_version") or "").strip()
    if not strategy_version:
        errors.append("production current_strategy_snapshot.strategy_version is missing")

    validation = payload.get("validation")
    if not isinstance(validation, dict):
        errors.append("production current_strategy_snapshot.validation must be an object")
        validation_status = None
    else:
        validation_status = str(validation.get("status") or "").strip().lower()
        if validation_status != "passed":
            errors.append(
                "production current_strategy_snapshot.validation.status must be passed "
                f"(actual={validation_status or 'missing'})"
            )

    execution_intent = payload.get("execution_intent")
    if not isinstance(execution_intent, dict):
        errors.append("production current_strategy_snapshot.execution_intent must be an object")
        signal_id = None
        target_asset = None
        stale_signal = None
    else:
        signal_id = str(execution_intent.get("signal_id") or "").strip()
        target_asset = str(execution_intent.get("target_asset") or "").strip()
        if not signal_id:
            errors.append(
                "production current_strategy_snapshot.execution_intent.signal_id is missing"
            )
        if not target_asset:
            errors.append(
                "production current_strategy_snapshot.execution_intent.target_asset is missing"
            )
        stale_signal = bool(execution_intent.get("stale_signal", False))
        if stale_signal:
            errors.append(
                "production current_strategy_snapshot.execution_intent.stale_signal must be false for execution readiness"
            )

    return {
        "path": str(PRODUCTION_SNAPSHOT_PATH.resolve()),
        "inspection": inspection,
        "errors": errors,
        "valid": not errors,
        "closed_day": closed_day,
        "strategy_version": strategy_version,
        "validation_status": validation_status,
        "signal_id": signal_id,
        "target_asset": target_asset,
        "stale_signal": stale_signal,
    }


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

        canonical_path, path_resolution = resolve_runtime_path(
            canonical_path_raw,
            root=ROOT,
            context=f"validate:{artifact_key}:canonical",
        )
        log(format_path_resolution_message(path_resolution))
        artifact_report = {
            "artifact_key": artifact_key,
            "owner": artifact_entry.get("owner"),
            "artifact_type": artifact_entry.get("artifact_type"),
            "truth_domain": artifact_entry.get("truth_domain"),
            "read_scope": artifact_entry.get("read_scope"),
            "write_mode": artifact_entry.get("write_mode"),
            "path_resolution": path_resolution,
            "inspection": inspect_artifact(canonical_path),
        }

        if not canonical_path.exists():
            missing_files.append(artifact_key)

        artifact_reports[artifact_key] = artifact_report

    authority_reports = {
        "authority_latest_successful_snapshot": validate_authority_latest_successful_snapshot(),
        "authority_latest_attempt_status": validate_authority_latest_attempt_status(),
    }
    production_report = validate_production_current_strategy_snapshot()
    freshness_monitoring_report = validate_strategy_chain_freshness_monitoring()
    authority_errors = [
        error
        for snapshot_report in authority_reports.values()
        for error in snapshot_report.get("errors", [])
    ]
    production_errors = list(production_report.get("errors", []))
    authority_errors.extend(freshness_monitoring_report.get("errors", []))

    success_inspection = authority_reports["authority_latest_successful_snapshot"]["inspection"]
    success_top_level_type = success_inspection.get("top_level_type")
    success_payload = read_json(LATEST_SUCCESSFUL_SNAPSHOT_PATH) if success_top_level_type == "dict" else {}
    success_closed_day = None
    success_closed_day_errors: list[str] = []
    if success_payload:
        success_closed_day = normalize_iso_day_text(
            success_payload.get("target_closed_day_utc"),
            context="authority_latest_successful_snapshot.target_closed_day_utc",
            errors=success_closed_day_errors,
        )

    attempt_inspection = authority_reports["authority_latest_attempt_status"]["inspection"]
    attempt_top_level_type = attempt_inspection.get("top_level_type")
    attempt_payload = read_json(LATEST_ATTEMPT_STATUS_PATH) if attempt_top_level_type == "dict" else {}
    attempt_closed_day = None
    attempt_closed_day_errors: list[str] = []
    if attempt_payload:
        attempt_closed_day = normalize_iso_day_text(
            attempt_payload.get("target_closed_day_utc"),
            context="authority_latest_attempt_status.target_closed_day_utc",
            errors=attempt_closed_day_errors,
        )

    production_closed_day = production_report.get("closed_day")
    alignment_errors = [*success_closed_day_errors, *attempt_closed_day_errors]
    if (
        production_closed_day
        and success_closed_day
        and attempt_closed_day
        and len({production_closed_day, success_closed_day, attempt_closed_day}) != 1
    ):
        alignment_errors.append(
            "production current_strategy_snapshot.closed_day diverged from authority target day "
            f"(production={production_closed_day} success={success_closed_day} attempt={attempt_closed_day})"
        )
    production_errors.extend(alignment_errors)
    production_report["errors"] = production_errors
    production_report["valid"] = not production_errors

    hard_required_for_execution = [
        *REQUIRED_ARTIFACT_KEYS,
        "outputs/production/current_strategy_snapshot.json",
    ]

    hard_required_missing = [
        key for key in hard_required_for_execution
        if key in missing_registry_keys or key in missing_files
    ]
    hard_required_missing.extend(authority_errors)
    hard_required_missing.extend(production_errors)

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
        "authority_reports": authority_reports,
        "production_report": production_report,
        "freshness_monitoring_report": freshness_monitoring_report,
        "contract_status": "valid" if not hard_required_missing else "invalid",
        "notes": [
            "This validator checks existence and basic shape only.",
            "It does not infer trading logic.",
            "Do not treat non-authoritative staging files as app truth.",
            "The app homepage must be served from outputs/execution/authority/latest_successful_snapshot.json.",
            "The app runtime path must be served from outputs/execution/authority/latest_attempt_status.json.",
            "Execution signal truth must read outputs/production/current_strategy_snapshot.json."
        ]
    }

    quality = {
        "validator_ok": True,
        "paths_registry_present": True,
        "missing_registry_key_count": len(missing_registry_keys),
        "missing_file_count": len(missing_files),
        "hard_required_missing_count": len(hard_required_missing),
        "authority_latest_successful_snapshot_valid": authority_reports["authority_latest_successful_snapshot"]["valid"],
        "authority_latest_attempt_status_valid": authority_reports["authority_latest_attempt_status"]["valid"],
        "production_current_strategy_snapshot_valid": production_report["valid"],
        "strategy_chain_freshness_monitoring_valid": freshness_monitoring_report["valid"],
        "authority_error_count": len(authority_errors),
        "production_error_count": len(production_errors),
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
        "validated_authority_paths": [
            str(LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
            str(LATEST_ATTEMPT_STATUS_PATH.resolve()),
        ],
        "validated_production_paths": [
            str(PRODUCTION_SNAPSHOT_PATH.resolve()),
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
