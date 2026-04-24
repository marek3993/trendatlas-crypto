from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.approved_strategy_net_export_helper import (
    NetCostExportConfig,
    build_net_cost_export_frame,
    summarize_net_cost_export,
)
from scripts.execution.authority_metric_derivation import (
    derive_strategy_day_metrics_from_csv,
)
from scripts.execution.runtime_path_resolution import (
    format_path_resolution_message,
    resolve_runtime_path,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
APP_EXPORTS_DIR = OUTPUTS_DIR / "app_exports"
FRESHNESS_DIR = OUTPUTS_DIR / "freshness"
APP_SNAPSHOT_DIR = OUTPUTS_DIR / "app_snapshot"
LOGS_DIR = OUTPUTS_DIR / "logs"
APP_REFRESH_PIPELINE_DIR = ROOT / "outputs" / "app_refresh_pipeline"

PATHS_REGISTRY_PATH = SOURCE_OF_TRUTH_DIR / "paths_registry.json"
PROJECT_TRUTH_PATH = SOURCE_OF_TRUTH_DIR / "project_truth.json"
EXPORT_CONTRACT_PATH = SOURCE_OF_TRUTH_DIR / "export_contract.json"

REPORT_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_report.json"
MANIFEST_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_manifest.json"
QUALITY_PATH = OUTPUTS_DIR / "refresh_pipeline" / "materialize_execution_app_exports_quality.json"
LOG_PATH = LOGS_DIR / "materialize_execution_app_exports.log"
APP_PRODUCT_SNAPSHOT_PATH = APP_SNAPSHOT_DIR / "app_product_snapshot.json"
APP_RUNTIME_SNAPSHOT_PATH = APP_SNAPSHOT_DIR / "app_runtime_snapshot.json"

REQUIRED_ARTIFACT_KEYS = [
    "phase67j_winner_paper",
    "phase67j_live_status",
    "phase66g_core_paper",
    "phase66g_live_status",
    "phase66g_trend_barometer_history",
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

PHASE68I_SUMMARY_OUTPUT_PATH = APP_EXPORTS_DIR / "phase68i_dynamic_ladder_candidate_summary.csv"
PHASE68I_AUTHORITATIVE_EXPORT_PATH = APP_EXPORTS_DIR / "phase68i_dynamic_ladder_candidate_authoritative_net_compare_export.csv"
PHASE68I_PAPER_INPUT_PATH = APP_EXPORTS_DIR / "phase68i_dynamic_ladder_candidate_paper.csv"
PHASE67J_PAPER_PATH = APP_EXPORTS_DIR / "phase67j_no_neo_main_paper.csv"
PHASE67J_LIVE_STATUS_PATH = APP_EXPORTS_DIR / "phase67j_live_status.csv"
PHASE66G_LIVE_STATUS_PATH = APP_EXPORTS_DIR / "phase66g_live_status.csv"
PHASE66G_TREND_HISTORY_PATH = APP_EXPORTS_DIR / "phase66g_trend_barometer_history.csv"
APP_FRESHNESS_REPORT_PATH = FRESHNESS_DIR / "app_freshness_report.json"
BENCHMARK_BTC_SOURCE_PATH = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"
EXECUTION_STATUS_PATH = OUTPUTS_DIR / "live_status" / "execution_status.json"
ACCOUNT_SNAPSHOT_PATH = OUTPUTS_DIR / "read_only" / "hyperliquid_account_snapshot.json"
RUNTIME_HEALTH_PATH = OUTPUTS_DIR / "runtime_health" / "latest_runtime_health.json"
FULL_AUTO_SCHEDULER_MANIFEST_PATH = OUTPUTS_DIR / "full_auto_scheduler" / "latest_scheduler_entry_manifest.json"
DRY_RUN_DECISION_PATH = OUTPUTS_DIR / "dry_run" / "latest_dry_run_decision.json"
REAL_ORDER_GATE_PATH = OUTPUTS_DIR / "live_gate" / "latest_real_order_gate_decision.json"
EXECUTION_MODE_CONFIG_PATH = ROOT / "execution" / "config" / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = ROOT / "execution" / "config" / "live_order_policy.json"
TRADING_OPERATION_MODE_PATH = ROOT / "execution" / "config" / "trading_operation_mode.json"
PHASE68H_SUMMARY_INPUT_PATH = ROOT / "outputs" / "phase68h_dynamic_leverage_ladder_candidate" / "phase68h_dynamic_leverage_ladder_summary.csv"
PHASE68H_DYNAMIC_PAPER_INPUT_PATH = ROOT / "outputs" / "phase68h_dynamic_leverage_ladder_candidate" / "papers" / "phase68h_dynamic_ladder_candidate_paper.csv"
PHASE68H_SCRIPT_PATH = ROOT / "scripts" / "phase68h_dynamic_leverage_ladder_candidate.py"
PHASE66G_PRODUCTION_PAPER_PATH = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_production_soft_filters_paper.csv"

SUCCESS_REFRESH_STATUSES = {"OK", "SUCCESS", "PASS", "PASSED"}
FRESHNESS_SUMMARY_TEXT = {
    "current": "Current: the latest refresh succeeded and strategy data is aligned with the latest available closed UTC day.",
    "stale": "Stale: strategy data is not aligned with the latest available closed UTC day.",
    "not_run_today": "Not run today: the required refresh for the latest available closed UTC day has not completed successfully.",
    "failed_latest_refresh": "Failed latest refresh: the most recent daily refresh failed.",
    "missing_runtime_artifact": "Missing runtime artifact: app_runtime_snapshot.json is missing or invalid.",
}


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


def read_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_date_from_iso(value: Any) -> str | None:
    parsed = parse_utc_datetime(value)
    if parsed is None:
        return None
    return parsed.date().isoformat()


def normalize_refresh_status(payload: dict[str, Any]) -> str:
    status = str(
        payload.get("refresh_source_status")
        or payload.get("main_refresh_chain_status")
        or payload.get("status")
        or ""
    ).strip().upper()
    return status or "UNKNOWN"


def refresh_manifest_finished_at(payload: dict[str, Any]) -> str | None:
    return (
        str(
            payload.get("refresh_source_finished_at_utc")
            or payload.get("main_refresh_chain_finished_at_utc")
            or payload.get("finished_at_utc")
            or payload.get("generated_at_utc")
            or payload.get("started_at_utc")
            or ""
        ).strip()
        or None
    )


def load_refresh_manifests() -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    if not APP_REFRESH_PIPELINE_DIR.exists():
        return manifests
    for manifest_path in APP_REFRESH_PIPELINE_DIR.glob("*/app_refresh_pipeline_manifest.json"):
        payload = read_json_optional(manifest_path)
        if not payload:
            continue
        run_id = manifest_path.parent.name
        finished_at_utc = refresh_manifest_finished_at(payload)
        manifests.append(
            {
                "run_id": run_id,
                "manifest_path": path_for_app(manifest_path),
                "status": normalize_refresh_status(payload),
                "success": normalize_refresh_status(payload) in SUCCESS_REFRESH_STATUSES,
                "started_at_utc": payload.get("started_at_utc"),
                "finished_at_utc": finished_at_utc,
                "sort_at_utc": finished_at_utc or payload.get("started_at_utc"),
                "error": payload.get("error"),
            }
        )
    return sorted(
        manifests,
        key=lambda item: parse_utc_datetime(item.get("sort_at_utc")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def read_last_csv_date_optional(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return read_last_csv_date(path)
    except SystemExit:
        raise
    except Exception:
        return None


def read_trend_calculation_date_optional(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        row = read_optional_single_csv_row(path)
    except SystemExit:
        raise
    except Exception:
        return None
    return str(row.get("trend_calc_date") or row.get("latest_available_date") or "").strip() or None


def read_live_status_date_required(path: Path, field: str = "latest_available_date") -> str:
    row = read_single_csv_row(path)
    return parse_iso_date_required(row.get(field), f"{path} {field}")


def build_canonical_product_freshness_checks(freshness_payload: dict[str, Any]) -> dict[str, Any]:
    base_checks = freshness_payload.get("checks", {})
    checks = dict(base_checks) if isinstance(base_checks, dict) else {}
    phase66g_canonical_date = read_last_csv_date(PHASE66G_TREND_HISTORY_PATH)

    checks.update(
        {
            "btc_raw_last_date": read_last_csv_date(BENCHMARK_BTC_SOURCE_PATH),
            "phase66g_paper_last_date": phase66g_canonical_date,
            "phase66g_live_latest_available_date": read_live_status_date_required(PHASE66G_LIVE_STATUS_PATH),
            "phase66g_trend_last_date": phase66g_canonical_date,
            "phase67j_paper_last_date": read_last_csv_date(PHASE67J_PAPER_PATH),
            "phase67j_live_latest_available_date": read_live_status_date_required(PHASE67J_LIVE_STATUS_PATH),
        }
    )
    return checks


def freshness_detail(
    state: str,
    *,
    latest_refresh: dict[str, Any] | None,
    latest_strategy_artifact_date: str | None,
    latest_available_closed_utc_date: str | None,
) -> tuple[str, str]:
    if state == "current":
        return (
            "strategy_refresh_current",
            FRESHNESS_SUMMARY_TEXT[state],
        )
    if state == "stale":
        return (
            "strategy_artifact_not_aligned_with_latest_closed_day",
            (
                f"{FRESHNESS_SUMMARY_TEXT[state]} "
                f"strategy_date={latest_strategy_artifact_date or 'missing'} "
                f"latest_available_closed_utc_date={latest_available_closed_utc_date or 'missing'}."
            ),
        )
    if state == "failed_latest_refresh":
        return (
            "latest_refresh_failed",
            (
                f"{FRESHNESS_SUMMARY_TEXT[state]} "
                f"run_id={(latest_refresh or {}).get('run_id') or 'missing'} "
                f"finished_at_utc={(latest_refresh or {}).get('finished_at_utc') or 'missing'}."
            ),
        )
    if state == "not_run_today":
        return (
            "required_refresh_not_completed_for_latest_closed_day",
            (
                f"{FRESHNESS_SUMMARY_TEXT[state]} "
                f"latest_refresh_run_id={(latest_refresh or {}).get('run_id') or 'missing'} "
                f"latest_refresh_run_status={(latest_refresh or {}).get('status') or 'missing'} "
                f"latest_strategy_artifact_date={latest_strategy_artifact_date or 'missing'} "
                f"latest_available_closed_utc_date={latest_available_closed_utc_date or 'missing'} "
                f"latest_refresh_finished_at_utc={(latest_refresh or {}).get('finished_at_utc') or 'missing'}."
            ),
        )
    return (
        "runtime_artifact_missing",
        FRESHNESS_SUMMARY_TEXT["missing_runtime_artifact"],
    )


def build_strategy_freshness_summary(
    *,
    latest_strategy_artifact_date: str | None,
    latest_trend_calculation_date: str | None,
    latest_wallet_sync_utc: str | None,
    latest_available_closed_utc_date: str | None,
) -> dict[str, Any]:
    refresh_manifests = load_refresh_manifests()
    latest_refresh = refresh_manifests[0] if refresh_manifests else None
    latest_successful_refresh = next((item for item in refresh_manifests if item.get("success")), None)
    latest_refresh_success = bool(latest_refresh and latest_refresh.get("success"))
    strategy_dates_aligned = bool(
        latest_strategy_artifact_date
        and latest_available_closed_utc_date
        and latest_strategy_artifact_date == latest_available_closed_utc_date
    )

    if latest_refresh is None:
        state = "not_run_today"
    elif latest_refresh_success and strategy_dates_aligned:
        state = "current"
    elif not latest_refresh_success:
        state = "failed_latest_refresh"
    else:
        state = "stale"

    detail_code, detail_text = freshness_detail(
        state,
        latest_refresh=latest_refresh,
        latest_strategy_artifact_date=latest_strategy_artifact_date,
        latest_available_closed_utc_date=latest_available_closed_utc_date,
    )

    return {
        "latest_refresh_run_id": None if latest_refresh is None else latest_refresh.get("run_id"),
        "latest_refresh_run_status": None if latest_refresh is None else latest_refresh.get("status"),
        "refresh_currentness_state": state,
        "refresh_currentness_reason_code": detail_code,
        "refresh_currentness_reason": detail_text,
        "freshness_state": state,
        "freshness_detail_code": detail_code,
        "freshness_summary_text": FRESHNESS_SUMMARY_TEXT[state],
        "freshness_detail_text": detail_text,
        "refresh_run_id": None if latest_refresh is None else latest_refresh.get("run_id"),
        "refresh_success": None if latest_refresh is None else bool(latest_refresh.get("success")),
        "refresh_status": None if latest_refresh is None else latest_refresh.get("status"),
        "refresh_finished_at_utc": None if latest_refresh is None else latest_refresh.get("finished_at_utc"),
        "refresh_manifest_path": None if latest_refresh is None else latest_refresh.get("manifest_path"),
        "latest_successful_refresh_runtime_utc": (
            None if latest_successful_refresh is None else latest_successful_refresh.get("finished_at_utc")
        ),
        "latest_successful_refresh_run_id": (
            None if latest_successful_refresh is None else latest_successful_refresh.get("run_id")
        ),
        "latest_strategy_artifact_date": latest_strategy_artifact_date,
        "latest_trend_calculation_date": latest_trend_calculation_date,
        "latest_wallet_sync_utc": latest_wallet_sync_utc,
        "latest_available_closed_utc_date": latest_available_closed_utc_date,
        "evaluated_at_utc": utc_now_iso(),
    }


def build_runtime_table_snapshot(
    *,
    last_pi_update_utc: str | None,
    last_pi_update_metadata: dict[str, Any],
    last_wallet_sync_utc: str | None,
    strategy_freshness: dict[str, Any],
    evaluated_at_utc: str,
) -> dict[str, Any]:
    product_contract = load_app_product_export_contract()
    main_paper_path = product_contract["main_paper_path"]
    latest_refresh_manifest_metadata = source_metadata_from_path_text(
        strategy_freshness.get("refresh_manifest_path"),
        "app_refresh_pipeline_manifest",
    )
    wallet_snapshot_metadata = source_metadata(ACCOUNT_SNAPSHOT_PATH, "read_only_account_snapshot")
    freshness_report_metadata = source_metadata(APP_FRESHNESS_REPORT_PATH, "canonical_product_freshness_report")
    strategy_artifact_metadata = source_metadata(main_paper_path, "canonical_app_paper")
    trend_calculation_metadata = source_metadata(PHASE66G_LIVE_STATUS_PATH, "canonical_trend_live_status")

    last_refresh_run_id = strategy_freshness.get("latest_refresh_run_id")
    last_refresh_status = strategy_freshness.get("latest_refresh_run_status")
    last_pc_refresh_utc = strategy_freshness.get("refresh_finished_at_utc")
    currentness_state = (
        str(strategy_freshness.get("refresh_currentness_state") or "").strip()
        or "missing_runtime_artifact"
    )
    currentness_reason = (
        str(strategy_freshness.get("refresh_currentness_reason") or "").strip()
        or FRESHNESS_SUMMARY_TEXT.get(currentness_state, FRESHNESS_SUMMARY_TEXT["missing_runtime_artifact"])
    )

    if last_refresh_run_id is None and not str(last_refresh_status or "").strip():
        last_refresh_status = "not_run"

    return {
        "last_pi_update_utc": last_pi_update_utc,
        "last_pc_refresh_utc": last_pc_refresh_utc,
        "last_refresh_status": last_refresh_status,
        "last_refresh_run_id": last_refresh_run_id,
        "last_wallet_sync_utc": last_wallet_sync_utc,
        "currentness_state": currentness_state,
        "currentness_reason": currentness_reason,
        "source_metadata": {
            "last_pi_update_utc": field_source_metadata(
                source_path_metadata=last_pi_update_metadata,
                source_field="generated_at_utc",
                value=last_pi_update_utc,
            ),
            "last_pc_refresh_utc": field_source_metadata(
                source_path_metadata=latest_refresh_manifest_metadata,
                source_field="main_refresh_chain_finished_at_utc|finished_at_utc|generated_at_utc|started_at_utc",
                value=last_pc_refresh_utc,
            ),
            "last_refresh_status": field_source_metadata(
                source_path_metadata=latest_refresh_manifest_metadata,
                source_field="main_refresh_chain_status|status",
                value=last_refresh_status,
            ),
            "last_refresh_run_id": field_source_metadata(
                source_path_metadata=latest_refresh_manifest_metadata,
                source_field="manifest_parent_dir_name",
                value=last_refresh_run_id,
            ),
            "last_wallet_sync_utc": field_source_metadata(
                source_path_metadata=wallet_snapshot_metadata,
                source_field="as_of_utc",
                value=last_wallet_sync_utc,
            ),
            "currentness_state": field_source_metadata(
                source_path_metadata=freshness_report_metadata,
                source_field="latest_closed_utc_date",
                value=currentness_state,
                derived_from=["strategy_freshness.refresh_currentness_state"],
                extra_inputs={
                    "refresh_manifest": latest_refresh_manifest_metadata,
                    "strategy_artifact": strategy_artifact_metadata,
                    "trend_calculation": trend_calculation_metadata,
                },
            ),
            "currentness_reason": field_source_metadata(
                source_path_metadata=freshness_report_metadata,
                source_field="latest_closed_utc_date",
                value=currentness_reason,
                derived_from=["strategy_freshness.refresh_currentness_reason"],
                extra_inputs={
                    "refresh_manifest": latest_refresh_manifest_metadata,
                    "strategy_artifact": strategy_artifact_metadata,
                    "trend_calculation": trend_calculation_metadata,
                },
            ),
        },
        "evaluated_at_utc": evaluated_at_utc,
    }


def resolve_last_pi_update_signal() -> tuple[str | None, dict[str, Any]]:
    metadata = source_metadata(
        FULL_AUTO_SCHEDULER_MANIFEST_PATH,
        "full_auto_scheduler_entry_manifest",
    )
    payload = read_json_optional(FULL_AUTO_SCHEDULER_MANIFEST_PATH)
    if not payload:
        return None, metadata
    value = str(payload.get("generated_at_utc") or "").strip() or None
    return value, metadata


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_dirs() -> None:
    APP_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    FRESHNESS_DIR.mkdir(parents=True, exist_ok=True)
    APP_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "refresh_pipeline").mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def find_existing_source(
    artifact_key: str,
    artifact_entry: dict[str, Any],
) -> tuple[Path | None, dict[str, Any] | None]:
    legacy_aliases = artifact_entry.get("legacy_aliases", [])
    if not isinstance(legacy_aliases, list):
        return None, None

    for raw_path in legacy_aliases:
        try:
            candidate, diagnostic = resolve_runtime_path(
                raw_path,
                root=ROOT,
                context=f"legacy:{artifact_key}",
            )
        except Exception:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate, diagnostic
    return None, None


def read_single_csv_row(path: Path) -> dict[str, str]:
    header, rows = read_csv_rows(path)
    if not header:
        fail(f"CSV has no header: {path}")
    if not rows:
        fail(f"CSV has no data rows: {path}")
    return rows[0]


def phase66g_live_status_refresh_tuple(path: Path) -> tuple[str, str]:
    row = read_single_csv_row(path)
    return (
        str(row.get("latest_available_date", "")).strip(),
        str(row.get("trend_calc_date", "")).strip(),
    )


def should_refresh_phase66g_live_status(source_path: Path, canonical_path: Path) -> bool:
    if not canonical_path.exists() or not canonical_path.is_file():
        return True

    source_tuple = phase66g_live_status_refresh_tuple(source_path)
    canonical_tuple = phase66g_live_status_refresh_tuple(canonical_path)
    return source_tuple > canonical_tuple


def safe_stat(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def path_for_app(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def source_metadata(path: Path, source_type: str, owner: str = "DATA") -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "path": path_for_app(path),
        "source_type": source_type,
        "owner": owner,
        "exists": path.exists(),
    }
    if path.exists():
        stat = path.stat()
        metadata["size_bytes"] = stat.st_size
        metadata["modified_utc"] = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return metadata


def source_metadata_from_path_text(path_text: str | None, source_type: str, owner: str = "DATA") -> dict[str, Any]:
    text = str(path_text or "").strip()
    if not text:
        return {
            "path": None,
            "source_type": source_type,
            "owner": owner,
            "exists": False,
        }
    path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return source_metadata(path, source_type, owner)


def field_source_metadata(
    *,
    source_path_metadata: dict[str, Any],
    source_field: str,
    value: Any,
    derived_from: list[str] | None = None,
    extra_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value_text = str(value).strip() if value is not None else ""
    metadata = dict(source_path_metadata)
    metadata["source_field"] = source_field
    metadata["value_present"] = bool(value_text)
    if derived_from:
        metadata["derived_from"] = list(derived_from)
    if extra_inputs:
        metadata["inputs"] = dict(extra_inputs)
    return metadata


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


def resolve_export_contract_path(raw_path: Any, *, context: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        fail(f"source_of_truth/export_contract.json missing {context}")
    path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return path


def load_app_product_export_contract() -> dict[str, Any]:
    export_contract = read_json(EXPORT_CONTRACT_PATH)
    app_export_contract = export_contract.get("app_export_contract")
    if not isinstance(app_export_contract, dict):
        fail("source_of_truth/export_contract.json missing app_export_contract")

    model_sources = app_export_contract.get("model_sources")
    if not isinstance(model_sources, dict):
        fail("source_of_truth/export_contract.json missing app_export_contract.model_sources")

    main_strategy_model = str(app_export_contract.get("main_strategy_model") or "").strip()
    if not main_strategy_model:
        fail("source_of_truth/export_contract.json missing app_export_contract.main_strategy_model")

    reference_strategy_model = str(app_export_contract.get("reference_strategy_model") or "").strip()
    if not reference_strategy_model:
        fail("source_of_truth/export_contract.json missing app_export_contract.reference_strategy_model")

    benchmark = str(app_export_contract.get("benchmark") or "").strip()
    if not benchmark:
        fail("source_of_truth/export_contract.json missing app_export_contract.benchmark")

    main_source_entry = model_sources.get(main_strategy_model)
    if not isinstance(main_source_entry, dict):
        fail(
            "source_of_truth/export_contract.json missing model_sources entry "
            f"for main strategy '{main_strategy_model}'"
        )

    reference_source_entry = model_sources.get(reference_strategy_model)
    if not isinstance(reference_source_entry, dict):
        fail(
            "source_of_truth/export_contract.json missing model_sources entry "
            f"for reference strategy '{reference_strategy_model}'"
        )

    display_names = app_export_contract.get("display_names")
    if not isinstance(display_names, dict):
        display_names = {}

    return {
        "product_name": str(app_export_contract.get("product_name") or "TrendAtlas Crypto").strip()
        or "TrendAtlas Crypto",
        "main_strategy_model": main_strategy_model,
        "reference_strategy_model": reference_strategy_model,
        "benchmark": benchmark,
        "display_names": display_names,
        "main_summary_path": resolve_export_contract_path(
            main_source_entry.get("summary_path"),
            context=f"app_export_contract.model_sources.{main_strategy_model}.summary_path",
        ),
        "main_paper_path": resolve_export_contract_path(
            main_source_entry.get("paper_path"),
            context=f"app_export_contract.model_sources.{main_strategy_model}.paper_path",
        ),
        "reference_paper_path": resolve_export_contract_path(
            reference_source_entry.get("paper_path"),
            context=f"app_export_contract.model_sources.{reference_strategy_model}.paper_path",
        ),
    }


def copy_plain_artifact(source_path: Path, canonical_path: Path) -> dict[str, Any]:
    shutil.copy2(source_path, canonical_path)
    return {
        "status": "copied_from_legacy_alias",
        "source_path": str(source_path),
        "source_info": safe_stat(source_path),
        "canonical_info": safe_stat(canonical_path),
    }


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        fail(f"Missing required CSV: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = list(reader)
            return header, rows
    except Exception as e:
        fail(f"Failed reading CSV {path}: {e}")
    raise RuntimeError("unreachable")


def parse_iso_date_required(raw: str | None, context: str) -> str:
    text = str(raw or "").strip()
    if not text:
        fail(f"Missing required ISO date in {context}")
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except Exception:
        fail(f"Invalid ISO date in {context}: {text}")
    raise RuntimeError("unreachable")


def read_last_csv_date(path: Path) -> str:
    header, rows = read_csv_rows(path)
    if not rows:
        fail(f"No rows found in {path}")

    date_field = None
    for candidate in ["date", "ts", "datetime", "timestamp"]:
        if candidate in header:
            date_field = candidate
            break

    if date_field is None:
        fail(f"Missing date-like column in {path}")

    return parse_iso_date_required(rows[-1].get(date_field), f"{path} {date_field}")


def refresh_phase68h_dynamic_paper_if_needed() -> dict[str, Any]:
    if not PHASE66G_PRODUCTION_PAPER_PATH.exists():
        fail(f"Missing required phase66g production paper: {PHASE66G_PRODUCTION_PAPER_PATH}")
    if not PHASE68H_SCRIPT_PATH.exists():
        fail(f"Missing required phase68h producer script: {PHASE68H_SCRIPT_PATH}")

    phase66g_last_date = read_last_csv_date(PHASE66G_PRODUCTION_PAPER_PATH)
    phase68h_last_date = (
        read_last_csv_date(PHASE68H_DYNAMIC_PAPER_INPUT_PATH)
        if PHASE68H_DYNAMIC_PAPER_INPUT_PATH.exists()
        else ""
    )

    refreshed = False
    if phase68h_last_date < phase66g_last_date:
        log("[REFRESH] phase68h dynamic paper is stale vs phase66g production paper")
        log(f"          phase68h_last_date={phase68h_last_date or 'missing'}")
        log(f"          phase66g_last_date={phase66g_last_date}")
        try:
            subprocess.run(
                [sys.executable, str(PHASE68H_SCRIPT_PATH)],
                check=True,
                cwd=str(ROOT),
            )
        except subprocess.CalledProcessError as e:
            fail(f"Failed refreshing phase68h dynamic paper via {PHASE68H_SCRIPT_PATH}: {e}")
        refreshed = True

    if not PHASE68H_DYNAMIC_PAPER_INPUT_PATH.exists():
        fail(f"Missing required phase68h dynamic paper: {PHASE68H_DYNAMIC_PAPER_INPUT_PATH}")

    refreshed_phase68h_last_date = read_last_csv_date(PHASE68H_DYNAMIC_PAPER_INPUT_PATH)
    if refreshed_phase68h_last_date < phase66g_last_date:
        fail(
            "phase68h dynamic paper remained stale after refresh "
            f"(phase68h_last_date={refreshed_phase68h_last_date}, phase66g_last_date={phase66g_last_date})"
        )

    return {
        "phase66g_last_date": phase66g_last_date,
        "phase68h_last_date_before_refresh": phase68h_last_date or None,
        "phase68h_last_date_after_refresh": refreshed_phase68h_last_date,
        "phase68h_refresh_triggered": refreshed,
    }


def newer_phase66g_live_status_available(
    source_path: Path,
    canonical_path: Path,
) -> dict[str, str] | None:
    _, source_rows = read_csv_rows(source_path)
    _, canonical_rows = read_csv_rows(canonical_path)

    if len(source_rows) != 1:
        fail(f"Expected exactly 1 row in phase66g live status source, got {len(source_rows)}")
    if len(canonical_rows) != 1:
        fail(f"Expected exactly 1 row in phase66g live status canonical, got {len(canonical_rows)}")

    source_date = parse_iso_date_required(
        source_rows[0].get("latest_available_date"),
        f"{source_path} latest_available_date",
    )
    canonical_date = parse_iso_date_required(
        canonical_rows[0].get("latest_available_date"),
        f"{canonical_path} latest_available_date",
    )

    if source_date <= canonical_date:
        return None

    return {
        "source_latest_available_date": source_date,
        "canonical_latest_available_date": canonical_date,
    }


def parse_float_required(row: dict[str, str], key: str) -> float:
    raw = str(row.get(key, "")).strip()
    if raw == "":
        fail(f"Missing required numeric field '{key}' in summary source row")
    try:
        return float(raw)
    except Exception:
        fail(f"Invalid numeric field '{key}' in summary source row: {raw}")
    raise RuntimeError("unreachable")


def parse_float_maybe(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    try:
        return float(text)
    except Exception:
        return None


def annualized_sharpe_from_daily_returns(daily_returns: list[float]) -> float | None:
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    var = sum((x - mean_ret) ** 2 for x in daily_returns) / (len(daily_returns) - 1)
    if var <= 0:
        return None
    std = var ** 0.5
    if std == 0:
        return None
    return (mean_ret / std) * (365 ** 0.5)


def annualized_sortino_from_daily_returns(daily_returns: list[float]) -> float | None:
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    downside = [x for x in daily_returns if x < 0]
    if len(downside) < 2:
        return None
    downside_mean = sum(downside) / len(downside)
    downside_var = sum((x - downside_mean) ** 2 for x in downside) / (len(downside) - 1)
    if downside_var <= 0:
        return None
    downside_std = downside_var ** 0.5
    if downside_std == 0:
        return None
    return (mean_ret / downside_std) * (365 ** 0.5)


def format_float(value: float | None, decimals: int = 4) -> str:
    if value is None:
        return ""
    return f"{value:.{decimals}f}"


def build_phase68i_summary_export() -> dict[str, Any]:
    phase68h_refresh_info = refresh_phase68h_dynamic_paper_if_needed()

    _, summary_rows = read_csv_rows(PHASE68H_SUMMARY_INPUT_PATH)
    if not summary_rows:
        fail(f"No rows found in {PHASE68H_SUMMARY_INPUT_PATH}")

    target_row = None
    for row in summary_rows:
        if str(row.get("model", "")).strip() == "phase68h_dynamic_ladder_candidate":
            target_row = row
            break

    if target_row is None:
        fail("Could not find phase68h_dynamic_ladder_candidate row in phase68h summary source")

    if not PHASE68H_DYNAMIC_PAPER_INPUT_PATH.exists():
        fail(f"Missing required phase68h dynamic paper: {PHASE68H_DYNAMIC_PAPER_INPUT_PATH}")

    try:
        shutil.copy2(PHASE68H_DYNAMIC_PAPER_INPUT_PATH, PHASE68I_PAPER_INPUT_PATH)
    except Exception as e:
        fail(f"Failed refreshing phase68i canonical paper from phase68h producer output: {e}")

    paper_header, paper_rows = read_csv_rows(PHASE68I_PAPER_INPUT_PATH)
    if not paper_rows:
        fail(f"No rows found in {PHASE68I_PAPER_INPUT_PATH}")

    paper_date_col = "date" if "date" in paper_header else "ts" if "ts" in paper_header else None
    if paper_date_col is None:
        fail("phase68i paper export missing date/ts column")

    if "equity_curve" not in paper_header and "equity" not in paper_header:
        fail("phase68i paper export missing equity-compatible column")
    if "equity_curve_gross" not in paper_header:
        fail("phase68i paper export missing equity_curve_gross required for gross/net export")
    if "equity_curve_net" not in paper_header:
        fail("phase68i paper export missing equity_curve_net required for gross/net export")

    if "realistic_ret" not in paper_header:
        fail("phase68i paper export missing realistic_ret required for sharpe/sortino")
    if "trading_fees_daily" not in paper_header:
        fail("phase68i paper export missing trading_fees_daily required for fee decomposition")
    if "trading_fees_cumulative" not in paper_header:
        fail("phase68i paper export missing trading_fees_cumulative required for fee decomposition")
    if "funding_daily" not in paper_header:
        fail("phase68i paper export missing funding_daily required for funding decomposition")
    if "funding_cumulative" not in paper_header:
        fail("phase68i paper export missing funding_cumulative required for funding decomposition")
    if "portfolio_held_asset" not in paper_header:
        fail("phase68i paper export missing portfolio_held_asset required for switch/cash/btc metrics")

    returns: list[float] = []
    held_assets: list[str] = []
    borrow_cost_total = 0.0
    tradable_slippage_cost_total = 0.0
    for row in paper_rows:
        ret = parse_float_maybe(row.get("realistic_ret"))
        if ret is None:
            fail("phase68i paper export contains empty/invalid realistic_ret")
        returns.append(ret)
        held_assets.append(str(row.get("portfolio_held_asset", "")).strip().upper())
        borrow_cost_total += parse_float_maybe(row.get("daily_borrow_cost")) or 0.0
        tradable_slippage_cost_total += parse_float_maybe(row.get("tradable_slippage_cost")) or 0.0

    sharpe = annualized_sharpe_from_daily_returns(returns)
    sortino = annualized_sortino_from_daily_returns(returns)
    if sharpe is None:
        fail("Could not compute sharpe reliably from realistic_ret")
    if sortino is None:
        fail("Could not compute sortino reliably from realistic_ret")

    switch_count = 0
    prev_asset = None
    for asset in held_assets:
        if prev_asset is None:
            prev_asset = asset
            continue
        if asset != prev_asset:
            switch_count += 1
        prev_asset = asset

    total_days = len(held_assets)
    if total_days == 0:
        fail("No held asset rows found in phase68i paper export")

    derived_day_metrics = derive_strategy_day_metrics_from_csv(PHASE68I_PAPER_INPUT_PATH)
    if derived_day_metrics is None:
        fail("phase68i paper export day metrics are unsupported by authoritative strategy semantics")
    if "cash_days_pct" not in derived_day_metrics or "btc_days_pct" not in derived_day_metrics:
        fail("phase68i paper export missing authoritative day metrics")

    cash_days_pct = float(derived_day_metrics["cash_days_pct"])
    btc_days_pct = float(derived_day_metrics["btc_days_pct"])

    last_paper_row = paper_rows[-1]
    total_return_pct_gross = (parse_float_required(last_paper_row, "equity_curve_gross") - 1.0) * 100.0
    total_return_pct_net = (parse_float_required(last_paper_row, "equity_curve_net") - 1.0) * 100.0
    trading_fees_total_pct = parse_float_required(last_paper_row, "trading_fees_cumulative") * 100.0
    funding_total_pct = parse_float_required(last_paper_row, "funding_cumulative") * 100.0

    output_header = [
        "model",
        "total_return_pct",
        "total_return_pct_gross",
        "total_return_pct_net",
        "cagr_pct",
        "cagr_pct_gross",
        "cagr_pct_net",
        "max_drawdown_pct",
        "max_drawdown_pct_gross",
        "max_drawdown_pct_net",
        "since2023_cagr_pct",
        "since2023_cagr_pct_gross",
        "since2023_cagr_pct_net",
        "since2025_cagr_pct",
        "since2025_cagr_pct_gross",
        "since2025_cagr_pct_net",
        "sharpe",
        "sortino",
        "switch_count",
        "trade_count",
        "cash_days_pct",
        "btc_days_pct",
        "trading_fees_total_pct",
        "funding_total_pct",
        "borrow_cost_total_pct",
        "tradable_slippage_cost_total_pct",
        "annual_borrow_cost_pct",
        "tradable_transition_slippage_bps",
        "fee_side_mode",
        "taker_fee_bps",
        "maker_fee_bps",
        "staking_discount_pct",
        "referral_discount_pct",
        "effective_trading_fee_bps",
    ]

    output_row = {
        "model": "phase68i_dynamic_ladder_candidate",
        "total_return_pct": format_float(total_return_pct_net, 2),
        "total_return_pct_gross": format_float(total_return_pct_gross, 2),
        "total_return_pct_net": format_float(total_return_pct_net, 2),
        "cagr_pct": format_float(parse_float_required(target_row, "cagr_pct_net"), 2),
        "cagr_pct_gross": format_float(parse_float_required(target_row, "cagr_pct_gross"), 2),
        "cagr_pct_net": format_float(parse_float_required(target_row, "cagr_pct_net"), 2),
        "max_drawdown_pct": format_float(parse_float_required(target_row, "max_drawdown_pct_net"), 2),
        "max_drawdown_pct_gross": format_float(parse_float_required(target_row, "max_drawdown_pct_gross"), 2),
        "max_drawdown_pct_net": format_float(parse_float_required(target_row, "max_drawdown_pct_net"), 2),
        "since2023_cagr_pct": format_float(parse_float_required(target_row, "since2023_cagr_pct_net"), 2),
        "since2023_cagr_pct_gross": format_float(parse_float_required(target_row, "since2023_cagr_pct_gross"), 2),
        "since2023_cagr_pct_net": format_float(parse_float_required(target_row, "since2023_cagr_pct_net"), 2),
        "since2025_cagr_pct": format_float(parse_float_required(target_row, "since2025_cagr_pct_net"), 2),
        "since2025_cagr_pct_gross": format_float(parse_float_required(target_row, "since2025_cagr_pct_gross"), 2),
        "since2025_cagr_pct_net": format_float(parse_float_required(target_row, "since2025_cagr_pct_net"), 2),
        "sharpe": format_float(sharpe, 4),
        "sortino": format_float(sortino, 4),
        "switch_count": str(switch_count),
        "trade_count": str(switch_count),
        "cash_days_pct": format_float(cash_days_pct, 4),
        "btc_days_pct": format_float(btc_days_pct, 4),
        "trading_fees_total_pct": format_float(trading_fees_total_pct, 4),
        "funding_total_pct": format_float(funding_total_pct, 4),
        "borrow_cost_total_pct": format_float(borrow_cost_total * 100.0, 4),
        "tradable_slippage_cost_total_pct": format_float(tradable_slippage_cost_total * 100.0, 4),
        "annual_borrow_cost_pct": format_float(parse_float_required(target_row, "annual_borrow_cost_pct"), 4),
        "tradable_transition_slippage_bps": format_float(parse_float_required(target_row, "tradable_transition_slippage_bps"), 4),
        "fee_side_mode": str(target_row.get("fee_side_mode", "")).strip(),
        "taker_fee_bps": format_float(parse_float_required(target_row, "taker_fee_bps"), 4),
        "maker_fee_bps": format_float(parse_float_required(target_row, "maker_fee_bps"), 4),
        "staking_discount_pct": format_float(parse_float_required(target_row, "staking_discount_pct"), 4),
        "referral_discount_pct": format_float(parse_float_required(target_row, "referral_discount_pct"), 4),
        "effective_trading_fee_bps": format_float(parse_float_required(target_row, "effective_trading_fee_bps"), 4),
    }

    authoritative_export = summarize_net_cost_export(
        build_net_cost_export_frame(
            pd.read_csv(PHASE68I_PAPER_INPUT_PATH),
            date_col=paper_date_col,
            gross_return_col="realistic_ret_gross",
            held_asset_col="portfolio_held_asset",
            leverage_col="effective_leverage",
            daily_borrow_cost_col="daily_borrow_cost",
            tradable_slippage_cost_col="tradable_slippage_cost",
            trading_fees_daily_col="trading_fees_daily",
            funding_daily_col="funding_daily",
            config=NetCostExportConfig(
                annual_borrow_cost=parse_float_required(target_row, "annual_borrow_cost_pct") / 100.0,
                tradable_transition_slippage_bps=parse_float_required(target_row, "tradable_transition_slippage_bps"),
                fee_side_mode=str(target_row.get("fee_side_mode", "")).strip(),
                taker_fee_bps=parse_float_required(target_row, "taker_fee_bps"),
                maker_fee_bps=parse_float_required(target_row, "maker_fee_bps"),
                staking_discount_pct=parse_float_required(target_row, "staking_discount_pct"),
                referral_discount_pct=parse_float_required(target_row, "referral_discount_pct"),
            ),
        ),
        model="phase68i_dynamic_ladder_candidate",
        switch_count=switch_count,
        trade_count=switch_count,
    )

    try:
        with PHASE68I_SUMMARY_OUTPUT_PATH.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_header)
            writer.writeheader()
            writer.writerow(output_row)
        pd.DataFrame([authoritative_export]).to_csv(PHASE68I_AUTHORITATIVE_EXPORT_PATH, index=False)
    except Exception as e:
        fail(f"Failed writing phase68i exports ({PHASE68I_SUMMARY_OUTPUT_PATH}, {PHASE68I_AUTHORITATIVE_EXPORT_PATH}): {e}")

    return {
        "status": "phase68i_summary_export_written",
        "summary_source_path": str(PHASE68H_SUMMARY_INPUT_PATH),
        "paper_source_path": str(PHASE68I_PAPER_INPUT_PATH),
        "paper_refresh_source_path": str(PHASE68H_DYNAMIC_PAPER_INPUT_PATH),
        "paper_refresh_info": phase68h_refresh_info,
        "output_path": str(PHASE68I_SUMMARY_OUTPUT_PATH),
        "output_info": safe_stat(PHASE68I_SUMMARY_OUTPUT_PATH),
        "authoritative_export_path": str(PHASE68I_AUTHORITATIVE_EXPORT_PATH),
        "authoritative_export_info": safe_stat(PHASE68I_AUTHORITATIVE_EXPORT_PATH),
        "computed_fields": [
            "total_return_pct",
            "total_return_pct_gross",
            "total_return_pct_net",
            "sharpe",
            "sortino",
            "switch_count",
            "trade_count",
            "cash_days_pct",
            "btc_days_pct",
            "trading_fees_total_pct",
            "funding_total_pct",
            "borrow_cost_total_pct",
            "tradable_slippage_cost_total_pct",
            "annual_borrow_cost_pct",
            "tradable_transition_slippage_bps",
        ],
        "copied_fields_from_summary_source": [
            "annual_borrow_cost_pct",
            "tradable_transition_slippage_bps",
            "fee_side_mode",
            "taker_fee_bps",
            "maker_fee_bps",
            "staking_discount_pct",
            "referral_discount_pct",
            "effective_trading_fee_bps",
            "cagr_pct",
            "cagr_pct_gross",
            "cagr_pct_net",
            "max_drawdown_pct",
            "max_drawdown_pct_gross",
            "max_drawdown_pct_net",
            "since2023_cagr_pct",
            "since2023_cagr_pct_gross",
            "since2023_cagr_pct_net",
            "since2025_cagr_pct",
            "since2025_cagr_pct_gross",
            "since2025_cagr_pct_net",
        ],
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


def csv_json_value(raw: Any) -> Any:
    text = str(raw or "").strip()
    if text == "":
        return None
    lowered = text.lower()
    if lowered in {"nan", "none", "null"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def normalized_row(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {field: csv_json_value(row.get(field)) for field in fields if field in row}


def read_optional_single_csv_row(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    _, rows = read_csv_rows(path)
    if not rows:
        return {}
    return rows[0]


def read_last_csv_row(path: Path) -> dict[str, str]:
    _, rows = read_csv_rows(path)
    if not rows:
        fail(f"No rows found in {path}")
    return rows[-1]


def derive_sharpe_sortino_from_paper(path: Path) -> dict[str, float]:
    header, rows = read_csv_rows(path)
    if "realistic_ret" not in header or not rows:
        return {}

    returns: list[float] = []
    for row in rows:
        ret = parse_float_maybe(row.get("realistic_ret"))
        if ret is None:
            return {}
        returns.append(ret)

    derived: dict[str, float] = {}
    sharpe = annualized_sharpe_from_daily_returns(returns)
    sortino = annualized_sortino_from_daily_returns(returns)
    if sharpe is not None:
        derived["sharpe"] = round(sharpe, 4)
    if sortino is not None:
        derived["sortino"] = round(sortino, 4)
    return derived


def normalize_homepage_main_strategy_metrics(
    summary_row: dict[str, Any],
    *,
    main_strategy_model: str,
    main_paper_path: Path,
    metric_fields: list[str],
) -> dict[str, Any]:
    metrics = normalized_row(summary_row, metric_fields)

    fallback_fields = {
        "total_return_pct": ["total_return_pct_net", "total_return_pct_gross"],
        "cagr_pct": ["cagr_pct_net", "cagr_pct_gross"],
        "max_drawdown_pct": ["max_drawdown_pct_net", "max_drawdown_pct_gross"],
        "since2023_cagr_pct": ["since2023_cagr_pct_net", "since2023_cagr_pct_gross"],
        "since2025_cagr_pct": ["since2025_cagr_pct_net", "since2025_cagr_pct_gross"],
    }
    for field, candidates in fallback_fields.items():
        if field in metrics:
            continue
        for candidate in candidates:
            if candidate in metrics:
                metrics[field] = metrics[candidate]
                break

    if "sharpe" not in metrics or "sortino" not in metrics:
        derived_risk_metrics = derive_sharpe_sortino_from_paper(main_paper_path)
        for field in ("sharpe", "sortino"):
            if field not in metrics and field in derived_risk_metrics:
                metrics[field] = derived_risk_metrics[field]

    metrics.pop("cash_days_pct", None)
    metrics.pop("btc_days_pct", None)
    derived_day_metrics = derive_strategy_day_metrics_from_csv(main_paper_path)
    if derived_day_metrics:
        for field, value in derived_day_metrics.items():
            metrics[field] = value

    metrics["model"] = main_strategy_model
    return metrics


def validate_homepage_snapshot_contract(
    snapshot: dict[str, Any],
    *,
    product_contract: dict[str, Any],
) -> None:
    expected_main_strategy_model = str(product_contract["main_strategy_model"]).strip()
    expected_main_summary_path = path_for_app(product_contract["main_summary_path"])
    expected_main_chart_path = path_for_app(product_contract["main_paper_path"])

    actual_main_strategy_model = str(snapshot.get("main_strategy_model") or "").strip()
    if actual_main_strategy_model != expected_main_strategy_model:
        fail(
            "app_product_snapshot.main_strategy_model diverged from source_of_truth/export_contract.json: "
            f"expected={expected_main_strategy_model} actual={actual_main_strategy_model or 'missing'}"
        )

    main_strategy_metrics = (
        snapshot.get("main_strategy_metrics")
        if isinstance(snapshot.get("main_strategy_metrics"), dict)
        else {}
    )
    actual_metrics_model = str(main_strategy_metrics.get("model") or "").strip()
    if actual_metrics_model != expected_main_strategy_model:
        fail(
            "app_product_snapshot.main_strategy_metrics.model diverged from source_of_truth/export_contract.json: "
            f"expected={expected_main_strategy_model} actual={actual_metrics_model or 'missing'}"
        )

    chart_source_paths = (
        snapshot.get("chart_source_paths")
        if isinstance(snapshot.get("chart_source_paths"), dict)
        else {}
    )
    actual_main_chart_path = str(chart_source_paths.get("main_strategy") or "").strip()
    if actual_main_chart_path != expected_main_chart_path:
        fail(
            "app_product_snapshot.chart_source_paths.main_strategy diverged from source_of_truth/export_contract.json: "
            f"expected={expected_main_chart_path} actual={actual_main_chart_path or 'missing'}"
        )

    source_metadata = snapshot.get("source_metadata") if isinstance(snapshot.get("source_metadata"), dict) else {}
    metrics_metadata = (
        source_metadata.get("main_strategy_metrics")
        if isinstance(source_metadata.get("main_strategy_metrics"), dict)
        else {}
    )
    actual_main_summary_path = str(metrics_metadata.get("path") or "").strip()
    if actual_main_summary_path != expected_main_summary_path:
        fail(
            "app_product_snapshot.source_metadata.main_strategy_metrics.path diverged from "
            "source_of_truth/export_contract.json: "
            f"expected={expected_main_summary_path} actual={actual_main_summary_path or 'missing'}"
        )


def build_runtime_account_summary(status_payload: dict[str, Any], snapshot_payload: dict[str, Any]) -> dict[str, Any]:
    snapshot_summary = snapshot_payload.get("summary", {}) if isinstance(snapshot_payload, dict) else {}
    snapshot_source = snapshot_payload.get("source", {}) if isinstance(snapshot_payload, dict) else {}
    summary: dict[str, Any] = {
        "status": status_payload.get("status") or ("ok" if snapshot_payload else None),
        "provider": status_payload.get("provider") or snapshot_source.get("provider"),
        "account_address": status_payload.get("account_address") or snapshot_payload.get("account_address"),
        "mode": status_payload.get("mode") or snapshot_payload.get("execution_mode"),
        "trading_enabled": status_payload.get("trading_enabled") if "trading_enabled" in status_payload else snapshot_payload.get("trading_enabled"),
        "kill_switch": status_payload.get("kill_switch") if "kill_switch" in status_payload else snapshot_payload.get("kill_switch"),
        "account_equity_usd": status_payload.get("account_equity_usd") or snapshot_summary.get("account_equity_usd"),
        "available_balance_usd": status_payload.get("available_balance_usd") or snapshot_summary.get("available_balance_usd"),
        "balance_source_of_truth": status_payload.get("balance_source_of_truth") or snapshot_summary.get("balance_source_of_truth"),
        "positions_count": status_payload.get("positions_count") if "positions_count" in status_payload else snapshot_summary.get("positions_count"),
        "open_orders_count": status_payload.get("open_orders_count") if "open_orders_count" in status_payload else snapshot_summary.get("open_orders_count"),
        "recent_fills_count": status_payload.get("recent_fills_count") if "recent_fills_count" in status_payload else snapshot_summary.get("recent_fills_count"),
        "current_position": status_payload.get("current_position") or "CASH",
        "open_position": status_payload.get("open_position"),
        "last_action": status_payload.get("last_action"),
        "last_action_result": status_payload.get("last_action_result"),
        "error": status_payload.get("error"),
    }
    return summary


def build_product_snapshot(app_live_mode_contract: dict[str, str]) -> dict[str, Any]:
    product_contract = load_app_product_export_contract()
    main_strategy_model = product_contract["main_strategy_model"]
    reference_strategy_model = product_contract["reference_strategy_model"]
    main_summary_path = product_contract["main_summary_path"]
    main_paper_path = product_contract["main_paper_path"]
    reference_paper_path = product_contract["reference_paper_path"]
    summary_row = read_single_csv_row(main_summary_path)
    main_paper_row = read_last_csv_row(main_paper_path)
    trend_row = read_optional_single_csv_row(PHASE66G_LIVE_STATUS_PATH)
    freshness_payload = read_json_optional(APP_FRESHNESS_REPORT_PATH)
    freshness_checks = build_canonical_product_freshness_checks(freshness_payload)

    metric_fields = [
        "model",
        "total_return_pct",
        "total_return_pct_gross",
        "total_return_pct_net",
        "cagr_pct",
        "cagr_pct_gross",
        "cagr_pct_net",
        "max_drawdown_pct",
        "max_drawdown_pct_gross",
        "max_drawdown_pct_net",
        "since2023_cagr_pct",
        "since2023_cagr_pct_gross",
        "since2023_cagr_pct_net",
        "since2025_cagr_pct",
        "since2025_cagr_pct_gross",
        "since2025_cagr_pct_net",
        "sharpe",
        "sortino",
        "switch_count",
        "cash_days_pct",
        "btc_days_pct",
        "trading_fees_total_pct",
        "funding_total_pct",
        "borrow_cost_total_pct",
        "tradable_slippage_cost_total_pct",
        "fee_side_mode",
        "taker_fee_bps",
        "maker_fee_bps",
        "staking_discount_pct",
        "referral_discount_pct",
        "effective_trading_fee_bps",
    ]
    trend_fields = [
        "model",
        "latest_available_date",
        "current_asset",
        "latest_decision_date",
        "latest_period_start",
        "latest_period_end",
        "next_rebalance_date",
        "latest_keep_reason",
        "candidate_assets_loaded",
        "failed_assets_count",
        "suspended_assets_now",
        "trend_score",
        "trend_state_label",
        "buy_threshold",
        "prev_trend_score",
        "crossed_up_today",
        "crossed_down_today",
        "trend_input_raw",
        "trend_threshold_raw",
        "trend_band",
        "trend_score_raw",
        "trend_calc_date",
    ]
    live_fields = [
        "date",
        "portfolio_held_asset",
        "baseline_held_asset",
        "tradable_governed_asset",
        "trend_state_label",
        "trend_score",
        "buy_threshold",
        "crossed_up_today",
        "crossed_down_today",
        "cash_day",
        "leverage_state_reason",
    ]

    strategy_last_closed_day = parse_iso_date_required(main_paper_row.get("date"), f"{main_paper_path} date")
    freshness_target_closed_day = freshness_payload.get("latest_closed_utc_date") or strategy_last_closed_day
    app_export_generated_at_utc = utc_now_iso()
    main_strategy_metrics = normalize_homepage_main_strategy_metrics(
        summary_row,
        main_strategy_model=main_strategy_model,
        main_paper_path=main_paper_path,
        metric_fields=metric_fields,
    )
    live_public_state = normalized_row(main_paper_row, live_fields)
    live_public_state.update({
        "model": main_strategy_model,
        "held_asset_public": csv_json_value(main_paper_row.get("portfolio_held_asset")),
        "held_state_label": csv_json_value(main_paper_row.get("trend_state_label")),
        "execution_state": csv_json_value(main_paper_row.get("portfolio_held_asset")),
        **app_live_mode_contract,
    })

    source_sections = {
        "main_strategy_metrics": source_metadata(main_summary_path, "canonical_app_summary"),
        "strategy_last_closed_day": {
            **source_metadata(main_paper_path, "canonical_app_paper"),
            "source_field": "last_row.date",
        },
        "freshness_target_closed_day": {
            **source_metadata(APP_FRESHNESS_REPORT_PATH, "canonical_product_freshness_report"),
            "source_field": "latest_closed_utc_date",
        },
        "app_export_generated_at_utc": {
            **source_metadata(APP_PRODUCT_SNAPSHOT_PATH, "app_product_snapshot"),
            "source_field": "generated_by_materializer_clock",
        },
        "live_public_state": {
            **source_metadata(main_paper_path, "canonical_app_paper"),
            "source_fields": live_fields,
        },
        "freshness": source_metadata(APP_FRESHNESS_REPORT_PATH, "canonical_product_freshness_report"),
        "trend_barometer_summary": source_metadata(PHASE66G_LIVE_STATUS_PATH, "canonical_trend_live_status"),
        "chart_source_paths": {
            "main_strategy": source_metadata(main_paper_path, "canonical_app_paper"),
            "reference_strategy": source_metadata(reference_paper_path, "canonical_app_paper"),
        },
        "benchmark_source_path": source_metadata(BENCHMARK_BTC_SOURCE_PATH, "benchmark_ohlcv"),
        "trend_history_source_path": source_metadata(PHASE66G_TREND_HISTORY_PATH, "canonical_trend_history"),
    }

    snapshot = {
        "snapshot_type": "app_product_snapshot",
        "schema_version": 1,
        "app_export_generated_at_utc": app_export_generated_at_utc,
        "product_name": product_contract["product_name"],
        "page_scope": "homepage",
        "main_strategy_model": main_strategy_model,
        "reference_strategy_model": reference_strategy_model,
        "benchmark": product_contract["benchmark"],
        "strategy_last_closed_day": strategy_last_closed_day,
        "freshness_target_closed_day": freshness_target_closed_day,
        "freshness": {
            "status": freshness_payload.get("status"),
            "generated_at_utc": freshness_payload.get("generated_at_utc"),
            "checks": freshness_checks,
            "warnings": freshness_payload.get("warnings", []),
            "errors": freshness_payload.get("errors", []),
        },
        "main_strategy_metrics": main_strategy_metrics,
        "live_public_state": live_public_state,
        "trend_barometer_summary": normalized_row(trend_row, trend_fields),
        "chart_source_paths": {
            "main_strategy": path_for_app(main_paper_path),
            "reference_strategy": path_for_app(reference_paper_path),
        },
        "benchmark_source_path": path_for_app(BENCHMARK_BTC_SOURCE_PATH),
        "trend_history_source_path": path_for_app(PHASE66G_TREND_HISTORY_PATH),
        "display_names": product_contract["display_names"],
        "source_metadata": source_sections,
    }
    validate_homepage_snapshot_contract(snapshot, product_contract=product_contract)
    return snapshot


def build_runtime_snapshot(app_export_generated_at_utc: str | None = None) -> dict[str, Any]:
    status_payload = read_json_optional(EXECUTION_STATUS_PATH)
    account_snapshot_payload = read_json_optional(ACCOUNT_SNAPSHOT_PATH)
    runtime_health_payload = read_json_optional(RUNTIME_HEALTH_PATH)
    dry_run_payload = read_json_optional(DRY_RUN_DECISION_PATH)
    gate_payload = read_json_optional(REAL_ORDER_GATE_PATH)
    execution_mode_payload = read_json_optional(EXECUTION_MODE_CONFIG_PATH)
    live_order_policy_payload = read_json_optional(LIVE_ORDER_POLICY_PATH)
    trading_operation_mode_payload = read_json_optional(TRADING_OPERATION_MODE_PATH)
    product_snapshot_payload = read_json_optional(APP_PRODUCT_SNAPSHOT_PATH)

    account_summary = build_runtime_account_summary(status_payload, account_snapshot_payload)
    runtime_last_sync_utc = runtime_health_payload.get("last_success_utc")
    last_pi_update_utc, last_pi_update_metadata = resolve_last_pi_update_signal()
    account_snapshot_as_of_utc = account_snapshot_payload.get("as_of_utc")
    dry_run_generated_at_utc = dry_run_payload.get("generated_at_utc")
    gate_generated_at_utc = gate_payload.get("generated_at_utc")
    app_runtime_generated_at_utc = utc_now_iso()
    resolved_app_export_generated_at_utc = (
        app_export_generated_at_utc
        or product_snapshot_payload.get("app_export_generated_at_utc")
        or app_runtime_generated_at_utc
    )
    product_contract = load_app_product_export_contract()
    main_paper_path = product_contract["main_paper_path"]
    freshness_payload = read_json_optional(APP_FRESHNESS_REPORT_PATH)
    latest_strategy_artifact_date = read_last_csv_date_optional(main_paper_path)
    latest_trend_calculation_date = read_trend_calculation_date_optional(PHASE66G_LIVE_STATUS_PATH)
    latest_available_closed_utc_date = (
        str(freshness_payload.get("latest_closed_utc_date") or "").strip() or None
    )
    latest_wallet_sync_utc = account_snapshot_as_of_utc
    strategy_freshness = build_strategy_freshness_summary(
        latest_strategy_artifact_date=latest_strategy_artifact_date,
        latest_trend_calculation_date=latest_trend_calculation_date,
        latest_wallet_sync_utc=latest_wallet_sync_utc,
        latest_available_closed_utc_date=latest_available_closed_utc_date,
    )
    runtime_table_snapshot = build_runtime_table_snapshot(
        last_pi_update_utc=last_pi_update_utc,
        last_pi_update_metadata=last_pi_update_metadata,
        last_wallet_sync_utc=latest_wallet_sync_utc,
        strategy_freshness=strategy_freshness,
        evaluated_at_utc=app_runtime_generated_at_utc,
    )
    execution_mode_posture = {
        "mode": execution_mode_payload.get("mode"),
        "trading_enabled": execution_mode_payload.get("trading_enabled"),
        "dry_run_enabled": execution_mode_payload.get("dry_run_enabled"),
        "kill_switch": execution_mode_payload.get("kill_switch"),
        "source_path": path_for_app(EXECUTION_MODE_CONFIG_PATH),
        "trading_operation_mode": {
            "mode": trading_operation_mode_payload.get("mode"),
            "updated_at_utc": trading_operation_mode_payload.get("updated_at_utc"),
            "updated_by": trading_operation_mode_payload.get("updated_by"),
            "fail_closed": trading_operation_mode_payload.get("fail_closed"),
            "error": trading_operation_mode_payload.get("error"),
            "source_path": path_for_app(TRADING_OPERATION_MODE_PATH),
        },
    }

    return {
        "snapshot_type": "app_runtime_snapshot",
        "schema_version": 2,
        "app_export_generated_at_utc": resolved_app_export_generated_at_utc,
        "app_runtime_snapshot_generated_at_utc": app_runtime_generated_at_utc,
        "page_scope": "account_page",
        "runtime_last_sync_utc": runtime_last_sync_utc,
        "account_snapshot_as_of_utc": account_snapshot_as_of_utc,
        "dry_run_generated_at_utc": dry_run_generated_at_utc,
        "gate_generated_at_utc": gate_generated_at_utc,
        "latest_refresh_run_id": strategy_freshness["latest_refresh_run_id"],
        "latest_refresh_run_status": strategy_freshness["latest_refresh_run_status"],
        "refresh_run_id": strategy_freshness["refresh_run_id"],
        "refresh_success": strategy_freshness["refresh_success"],
        "refresh_status": strategy_freshness["refresh_status"],
        "refresh_finished_at_utc": strategy_freshness["refresh_finished_at_utc"],
        "latest_strategy_artifact_date": latest_strategy_artifact_date,
        "latest_successful_refresh_runtime_utc": strategy_freshness["latest_successful_refresh_runtime_utc"],
        "latest_trend_calculation_date": latest_trend_calculation_date,
        "latest_wallet_sync_utc": latest_wallet_sync_utc,
        "latest_available_closed_utc_date": latest_available_closed_utc_date,
        "refresh_currentness_state": strategy_freshness["refresh_currentness_state"],
        "refresh_currentness_reason": strategy_freshness["refresh_currentness_reason"],
        "refresh_currentness_reason_code": strategy_freshness["refresh_currentness_reason_code"],
        "freshness_state": strategy_freshness["freshness_state"],
        "freshness_detail_code": strategy_freshness["freshness_detail_code"],
        "freshness_detail_text": strategy_freshness["freshness_detail_text"],
        "freshness_summary_text": strategy_freshness["freshness_summary_text"],
        "strategy_freshness": strategy_freshness,
        "runtime_table_snapshot": runtime_table_snapshot,
        "account_observability_contract": {
            "enabled": True,
            "read_mode": "read_only_operational_view",
            "ui_sections": [
                "proof_banner",
                "overview",
                "balances",
                "positions",
                "activity",
            ],
        },
        "execution_status": {
            "status": status_payload.get("status"),
            "mode": status_payload.get("mode"),
            "trading_enabled": status_payload.get("trading_enabled"),
            "kill_switch": status_payload.get("kill_switch"),
            "guardrails_ok": status_payload.get("guardrails_ok"),
            "stale_signal": status_payload.get("stale_signal"),
            "signal_id": status_payload.get("signal_id"),
            "target_asset": status_payload.get("target_asset"),
            "error": status_payload.get("error"),
        },
        "account_snapshot_summary": account_summary,
        "dry_run_summary": {
            "signal_id": dry_run_payload.get("signal_id"),
            "strategy_model": dry_run_payload.get("strategy_model"),
            "as_of_source": dry_run_payload.get("as_of_source"),
            "target_asset": dry_run_payload.get("target_asset"),
            "target_regime": dry_run_payload.get("target_regime"),
            "current_state": dry_run_payload.get("current_state"),
            "open_orders_count": dry_run_payload.get("open_orders_count"),
            "duplicate_order_risk": dry_run_payload.get("duplicate_order_risk"),
            "stale_signal": dry_run_payload.get("stale_signal"),
            "recommended_action": dry_run_payload.get("recommended_action"),
            "decision_reason": dry_run_payload.get("decision_reason"),
            "simulated_order": dry_run_payload.get("simulated_order", {}),
            "guardrails": dry_run_payload.get("guardrails", {}),
        },
        "gate_summary": {
            "signal_id": gate_payload.get("signal_id"),
            "target_asset": gate_payload.get("target_asset"),
            "mode": gate_payload.get("mode"),
            "approval_gate_status": gate_payload.get("approval_gate_status"),
            "would_place_real_order": gate_payload.get("would_place_real_order"),
            "real_orders_enabled": gate_payload.get("real_orders_enabled"),
            "status": gate_payload.get("status"),
            "block_reasons": gate_payload.get("block_reasons", []),
            "checks": gate_payload.get("checks", {}),
        },
        "runtime_health_summary": {
            "runtime_type": runtime_health_payload.get("runtime_type"),
            "runtime_label": runtime_health_payload.get("runtime_label"),
            "run_id": runtime_health_payload.get("run_id"),
            "mode": runtime_health_payload.get("mode"),
            "run_active": runtime_health_payload.get("run_active"),
            "status": runtime_health_payload.get("status"),
            "error": runtime_health_payload.get("error"),
            "stop_reason": runtime_health_payload.get("stop_reason"),
            "started_at_utc": runtime_health_payload.get("started_at_utc"),
            "updated_at_utc": runtime_health_payload.get("updated_at_utc"),
            "finished_at_utc": runtime_health_payload.get("finished_at_utc"),
            "outputs_possibly_stale_or_partial": runtime_health_payload.get("outputs_possibly_stale_or_partial"),
            "execution_mode_guardrail": runtime_health_payload.get("execution_mode_guardrail")
            or ((runtime_health_payload.get("preflight_check") or {}).get("execution_mode_guardrail") if isinstance(runtime_health_payload.get("preflight_check"), dict) else {}),
        },
        "execution_mode_posture": execution_mode_posture,
        "live_order_policy_summary": {
            "allow_live_orders": live_order_policy_payload.get("allow_live_orders"),
            "manual_approval_required": live_order_policy_payload.get("manual_approval_required"),
            "require_kill_switch_off": live_order_policy_payload.get("require_kill_switch_off"),
            "max_order_notional_usd": live_order_policy_payload.get("max_order_notional_usd"),
            "allowed_assets": live_order_policy_payload.get("allowed_assets", []),
            "allowed_approval_gate_statuses": live_order_policy_payload.get("allowed_approval_gate_statuses", []),
        },
        "source_metadata": {
            "strategy_freshness": {
                "refresh_manifest_path": strategy_freshness["refresh_manifest_path"],
                "latest_successful_refresh_run_id": strategy_freshness["latest_successful_refresh_run_id"],
                "freshness_report": source_metadata(APP_FRESHNESS_REPORT_PATH, "canonical_product_freshness_report"),
                "strategy_artifact": source_metadata(main_paper_path, "canonical_app_paper"),
                "trend_calculation": source_metadata(PHASE66G_LIVE_STATUS_PATH, "canonical_trend_live_status"),
                "wallet_sync": source_metadata(ACCOUNT_SNAPSHOT_PATH, "read_only_account_snapshot"),
            },
            "runtime_table_snapshot": {
                "source_type": "authoritative_runtime_table_snapshot",
                "owner": "DATA",
                "evaluated_at_utc": runtime_table_snapshot["evaluated_at_utc"],
                "fields": {
                    key: dict(value)
                    for key, value in runtime_table_snapshot["source_metadata"].items()
                },
            },
            "execution_status": source_metadata(EXECUTION_STATUS_PATH, "execution_status"),
            "account_snapshot_summary": source_metadata(ACCOUNT_SNAPSHOT_PATH, "read_only_account_snapshot"),
            "dry_run_summary": source_metadata(DRY_RUN_DECISION_PATH, "dry_run_decision"),
            "gate_summary": source_metadata(REAL_ORDER_GATE_PATH, "real_order_gate_decision"),
            "runtime_health_summary": source_metadata(RUNTIME_HEALTH_PATH, "runtime_health"),
            "execution_mode_posture": source_metadata(EXECUTION_MODE_CONFIG_PATH, "execution_mode_config"),
            "live_order_policy_summary": source_metadata(LIVE_ORDER_POLICY_PATH, "live_order_policy_config"),
            "trading_operation_mode": source_metadata(TRADING_OPERATION_MODE_PATH, "trading_operation_mode_config"),
            "runtime_last_sync_utc": source_metadata(RUNTIME_HEALTH_PATH, "runtime_health"),
            "account_snapshot_as_of_utc": source_metadata(ACCOUNT_SNAPSHOT_PATH, "read_only_account_snapshot"),
            "dry_run_generated_at_utc": source_metadata(DRY_RUN_DECISION_PATH, "dry_run_decision"),
            "gate_generated_at_utc": source_metadata(REAL_ORDER_GATE_PATH, "real_order_gate_decision"),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize canonical execution app exports and non-authoritative app staging snapshots."
    )
    parser.add_argument(
        "--runtime-snapshot-only",
        action="store_true",
        help="Only refresh the non-authoritative staging file outputs/execution/app_snapshot/app_runtime_snapshot.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dirs()
    started_at = utc_now_iso()
    log("[START] materialize_execution_app_exports")

    if args.runtime_snapshot_only:
        runtime_snapshot = build_runtime_snapshot()
        write_json(APP_RUNTIME_SNAPSHOT_PATH, runtime_snapshot)
        log(f"[MATERIALIZED] app_runtime_snapshot -> {APP_RUNTIME_SNAPSHOT_PATH}")
        log("[END] materialize_execution_app_exports runtime_snapshot_only")
        return

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

        canonical_path, canonical_diagnostic = resolve_runtime_path(
            canonical_raw,
            root=ROOT,
            context=f"materialize:{artifact_key}:canonical",
        )
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        log(format_path_resolution_message(canonical_diagnostic))

        row: dict[str, Any] = {
            "artifact_key": artifact_key,
            "canonical_path": str(canonical_path),
            "artifact_type": entry.get("artifact_type"),
            "owner": entry.get("owner"),
            "truth_domain": entry.get("truth_domain"),
            "path_resolution": canonical_diagnostic,
        }

        source_path, source_diagnostic = find_existing_source(artifact_key, entry)
        if source_diagnostic is not None:
            row["legacy_source_path_resolution"] = source_diagnostic
            log(format_path_resolution_message(source_diagnostic))
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

        if (
            artifact_key == "phase66g_live_status"
            and source_path is not None
            and canonical_path.exists()
            and canonical_path.is_file()
        ):
            refresh_metadata = newer_phase66g_live_status_available(
                source_path=source_path,
                canonical_path=canonical_path,
            )
            if refresh_metadata is not None:
                copy_result = copy_plain_artifact(source_path, canonical_path)
                copied_count += 1
                row.update(copy_result)
                row["status"] = "refreshed_from_newer_legacy_alias"
                row.update(refresh_metadata)
                report_rows.append(row)
                log(f"[REFRESHED] {artifact_key}")
                log(f"            source={source_path}")
                log(f"            target={canonical_path}")
                continue

        if artifact_key == "phase66g_live_status":
            if source_path is None:
                fail("phase66g_live_status requires legacy source for freshness-aware rematerialization")
            if should_refresh_phase66g_live_status(source_path, canonical_path):
                copy_result = copy_plain_artifact(source_path, canonical_path)
                copied_count += 1
                row.update(copy_result)
                row["status"] = "refreshed_from_newer_upstream"
                row["refresh_reason"] = "upstream_phase66g_live_status_is_newer_than_canonical"
                report_rows.append(row)
                log(f"[REFRESHED] {artifact_key}")
                log(f"           source={source_path}")
                log(f"           target={canonical_path}")
            else:
                already_present_count += 1
                row["status"] = "already_present"
                row["canonical_info"] = safe_stat(canonical_path)
                row["refresh_reason"] = "canonical_phase66g_live_status_is_not_older_than_upstream"
                report_rows.append(row)
                log(f"[OK] already present: {artifact_key} -> {canonical_path}")
            continue

        if (
            artifact_key in {
                "app_freshness_report",
                "phase66g_trend_barometer_history",
                "phase67j_winner_paper",
                "phase66g_core_paper",
            }
            and source_path is not None
            and canonical_path.exists()
            and canonical_path.is_file()
            and source_path.stat().st_mtime > canonical_path.stat().st_mtime
        ):
            copy_result = copy_plain_artifact(source_path, canonical_path)
            copied_count += 1
            row.update(copy_result)
            row["status"] = "refreshed_from_newer_legacy_alias"
            row["refresh_reason"] = "legacy_alias_mtime_newer_than_canonical"
            report_rows.append(row)
            log(f"[REFRESHED] {artifact_key}")
            log(f"            source={source_path}")
            log(f"            target={canonical_path}")
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

    phase68i_summary_result = build_phase68i_summary_export()
    report_rows.append({
        "artifact_key": "phase68i_dynamic_ladder_candidate_summary",
        **phase68i_summary_result,
    })
    transformed_count += 1
    log(f"[MATERIALIZED] phase68i_dynamic_ladder_candidate_summary")
    log(f"              target={PHASE68I_SUMMARY_OUTPUT_PATH}")
    log(f"[MATERIALIZED] phase68i_dynamic_ladder_candidate_authoritative_net_compare_export")
    log(f"              target={PHASE68I_AUTHORITATIVE_EXPORT_PATH}")

    product_snapshot = build_product_snapshot(app_live_mode_contract)
    runtime_snapshot = build_runtime_snapshot(
        app_export_generated_at_utc=product_snapshot.get("app_export_generated_at_utc")
    )
    write_json(APP_PRODUCT_SNAPSHOT_PATH, product_snapshot)
    write_json(APP_RUNTIME_SNAPSHOT_PATH, runtime_snapshot)
    transformed_count += 2
    report_rows.extend([
        {
            "artifact_key": "app_product_snapshot",
            "status": "snapshot_written",
            "output_path": str(APP_PRODUCT_SNAPSHOT_PATH),
            "output_info": safe_stat(APP_PRODUCT_SNAPSHOT_PATH),
        },
        {
            "artifact_key": "app_runtime_snapshot",
            "status": "snapshot_written",
            "output_path": str(APP_RUNTIME_SNAPSHOT_PATH),
            "output_info": safe_stat(APP_RUNTIME_SNAPSHOT_PATH),
        },
    ])
    log(f"[MATERIALIZED] app_product_snapshot -> {APP_PRODUCT_SNAPSHOT_PATH}")
    log(f"[MATERIALIZED] app_runtime_snapshot -> {APP_RUNTIME_SNAPSHOT_PATH}")

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
            "phase68i dynamic ladder summary export is built from phase68h summary source plus phase68i app paper-derived metrics.",
            "Other artifacts are copied from existing legacy aliases only.",
            "app_product_snapshot and app_runtime_snapshot remain non-authoritative internal staging after authority cutover."
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
        "phase68i_summary_written": PHASE68I_SUMMARY_OUTPUT_PATH.exists(),
        "phase68i_authoritative_net_compare_export_written": PHASE68I_AUTHORITATIVE_EXPORT_PATH.exists(),
        "app_product_snapshot_written": APP_PRODUCT_SNAPSHOT_PATH.exists(),
        "app_runtime_snapshot_written": APP_RUNTIME_SNAPSHOT_PATH.exists(),
    }

    manifest = {
        "artifact_name": "materialize_execution_app_exports",
        "generated_at_utc": utc_now_iso(),
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(PATHS_REGISTRY_PATH.resolve()),
            str(PROJECT_TRUTH_PATH.resolve()),
            str(PHASE68H_SUMMARY_INPUT_PATH.resolve()),
            str(PHASE68I_PAPER_INPUT_PATH.resolve()),
        ],
        "output_paths": [
            str(REPORT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
            str(PHASE68I_SUMMARY_OUTPUT_PATH.resolve()),
            str(PHASE68I_AUTHORITATIVE_EXPORT_PATH.resolve()),
            str(APP_PRODUCT_SNAPSHOT_PATH.resolve()),
            str(APP_RUNTIME_SNAPSHOT_PATH.resolve()),
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

