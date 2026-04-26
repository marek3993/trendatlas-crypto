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
from scripts.execution.current_strategy_root_contract import (
    load_current_main_strategy_root_contract,
    resolve_homepage_top_performance_source_contract,
    serialize_current_main_strategy_root_contract,
    validate_product_snapshot_current_strategy_contract,
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
PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH = APP_EXPORTS_DIR / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
PHASE68G_MAIN_PAPER_OUTPUT_PATH = APP_EXPORTS_DIR / "phase68g_66g_1p25x_candidate_paper.csv"
PHASE68G_SOURCE_DIR = ROOT / "outputs" / "phase68g_portfolio_exposure_leverage_validation"
PHASE68G_SOURCE_PAPER_PATH = PHASE68G_SOURCE_DIR / "papers" / "phase68g_66g_1p25x_candidate_paper.csv"
PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH = (
    PHASE68G_SOURCE_DIR / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
)
PHASE68G_SCRIPT_PATH = ROOT / "scripts" / "phase68g_portfolio_exposure_leverage_validation.py"
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
PHASE66G_DECISIONS_PATH = ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_production_candidate_decisions.csv"

SUCCESS_REFRESH_STATUSES = {"OK", "SUCCESS", "PASS", "PASSED"}
FRESHNESS_SUMMARY_TEXT = {
    "current": "Current: the latest refresh succeeded and strategy data is aligned with the latest available closed UTC day.",
    "stale": "Stale: strategy data is not aligned with the latest available closed UTC day.",
    "not_run_today": "Not run today: the required refresh for the latest available closed UTC day has not completed successfully.",
    "failed_latest_refresh": "Failed latest refresh: the most recent daily refresh failed.",
    "missing_runtime_artifact": "Missing runtime artifact: app_runtime_snapshot.json is missing or invalid.",
}

HOMEPAGE_MAIN_STRATEGY_METRIC_FIELDS = [
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

NET_ALIAS_METRIC_FALLBACKS = {
    "total_return_pct": ["total_return_pct_net", "total_return_pct_gross"],
    "cagr_pct": ["cagr_pct_net", "cagr_pct_gross"],
    "max_drawdown_pct": ["max_drawdown_pct_net", "max_drawdown_pct_gross"],
    "since2023_cagr_pct": ["since2023_cagr_pct_net", "since2023_cagr_pct_gross"],
    "since2025_cagr_pct": ["since2025_cagr_pct_net", "since2025_cagr_pct_gross"],
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


def refresh_phase68g_native_outputs_if_needed() -> dict[str, Any]:
    if not PHASE66G_PRODUCTION_PAPER_PATH.exists():
        fail(f"Missing required phase66g production paper: {PHASE66G_PRODUCTION_PAPER_PATH}")
    if not PHASE68G_SCRIPT_PATH.exists():
        fail(f"Missing required phase68g producer script: {PHASE68G_SCRIPT_PATH}")
    if not PHASE67J_PAPER_PATH.exists():
        fail(f"Missing required phase68g baseline paper: {PHASE67J_PAPER_PATH}")
    if not PHASE66G_DECISIONS_PATH.exists():
        fail(f"Missing required phase68g decisions source: {PHASE66G_DECISIONS_PATH}")

    phase66g_last_date = read_last_csv_date(PHASE66G_PRODUCTION_PAPER_PATH)
    phase68g_last_date = (
        read_last_csv_date(PHASE68G_SOURCE_PAPER_PATH)
        if PHASE68G_SOURCE_PAPER_PATH.exists()
        else ""
    )

    refreshed = False
    if phase68g_last_date < phase66g_last_date:
        log("[REFRESH] phase68g native paper is stale vs phase66g production paper")
        log(f"          phase68g_last_date={phase68g_last_date or 'missing'}")
        log(f"          phase66g_last_date={phase66g_last_date}")
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(PHASE68G_SCRIPT_PATH),
                    "--baseline-paper",
                    str(PHASE67J_PAPER_PATH),
                    "--governance-paper",
                    str(PHASE66G_PRODUCTION_PAPER_PATH),
                    "--trend-history",
                    str(PHASE66G_TREND_HISTORY_PATH),
                    "--decisions",
                    str(PHASE66G_DECISIONS_PATH),
                ],
                check=True,
                cwd=str(ROOT),
            )
        except subprocess.CalledProcessError as e:
            fail(f"Failed refreshing phase68g native outputs via {PHASE68G_SCRIPT_PATH}: {e}")
        refreshed = True

    if not PHASE68G_SOURCE_PAPER_PATH.exists():
        fail(f"Missing required phase68g native paper: {PHASE68G_SOURCE_PAPER_PATH}")
    if not PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH.exists():
        fail(
            "Missing required phase68g native authoritative export: "
            f"{PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH}"
        )

    refreshed_phase68g_last_date = read_last_csv_date(PHASE68G_SOURCE_PAPER_PATH)
    if refreshed_phase68g_last_date < phase66g_last_date:
        fail(
            "phase68g native paper remained stale after refresh "
            f"(phase68g_last_date={refreshed_phase68g_last_date}, phase66g_last_date={phase66g_last_date})"
        )

    source_export_row = read_single_csv_row(PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH)
    source_export_last_date = str(source_export_row.get("latest_available_date") or "").strip()
    if source_export_last_date != refreshed_phase68g_last_date:
        fail(
            "phase68g native authoritative export diverged from its refreshed paper date "
            f"(export_latest_available_date={source_export_last_date or 'missing'}, "
            f"paper_last_date={refreshed_phase68g_last_date})"
        )

    return {
        "phase66g_last_date": phase66g_last_date,
        "phase68g_last_date_before_refresh": phase68g_last_date or None,
        "phase68g_last_date_after_refresh": refreshed_phase68g_last_date,
        "phase68g_export_latest_available_date": source_export_last_date or None,
        "phase68g_refresh_triggered": refreshed,
        "phase68g_baseline_paper_path": str(PHASE67J_PAPER_PATH),
        "phase68g_source_paper_path": str(PHASE68G_SOURCE_PAPER_PATH),
        "phase68g_source_authoritative_export_path": str(PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH),
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


def find_summary_row_required(
    rows: list[dict[str, Any]],
    *,
    model: str,
    context: str,
) -> dict[str, Any]:
    for row in rows:
        if str(row.get("model", "")).strip() == model:
            return row
    fail(f"Could not find {model} row in {context}")
    raise RuntimeError("unreachable")


def require_uniform_paper_value(
    rows: list[dict[str, Any]],
    *,
    field: str,
    context: Path,
) -> str:
    values = sorted({
        str(row.get(field, "")).strip()
        for row in rows
        if str(row.get(field, "")).strip() != ""
    })
    if not values:
        fail(f"{context} missing required non-empty paper field '{field}'")
    if len(values) != 1:
        fail(f"{context} expected uniform paper field '{field}', got {values}")
    return values[0]


def infer_annual_borrow_cost_pct_from_paper(
    rows: list[dict[str, Any]],
    *,
    context: Path,
) -> float:
    derived_values: list[float] = []
    for row in rows:
        effective_leverage = parse_float_maybe(row.get("effective_leverage"))
        daily_borrow_cost = parse_float_maybe(row.get("daily_borrow_cost"))
        if effective_leverage is None or daily_borrow_cost is None:
            continue
        borrowed_fraction = effective_leverage - 1.0
        if borrowed_fraction <= 0.0 or daily_borrow_cost <= 0.0:
            continue
        derived_values.append((daily_borrow_cost * 365.25 / borrowed_fraction) * 100.0)

    if not derived_values:
        fail(f"{context} could not infer annual_borrow_cost_pct from live paper rows")

    baseline = derived_values[0]
    for value in derived_values[1:]:
        if abs(value - baseline) > 1e-6:
            fail(
                f"{context} produced inconsistent inferred annual_borrow_cost_pct values: "
                f"{baseline} vs {value}"
            )
    return round(baseline, 4)


def build_current_paper_backed_authoritative_export_payload(
    *,
    source_paper_path: Path,
    output_model: str,
) -> dict[str, Any]:
    if not source_paper_path.exists():
        fail(f"Missing required source paper for {output_model}: {source_paper_path}")

    paper_header, paper_rows = read_csv_rows(source_paper_path)
    if not paper_rows:
        fail(f"No rows found in {source_paper_path}")

    paper_date_col = "date" if "date" in paper_header else "ts" if "ts" in paper_header else None
    if paper_date_col is None:
        fail(f"{source_paper_path} missing date/ts column")

    required_fields = [
        "realistic_ret_gross",
        "realistic_ret",
        "portfolio_held_asset",
        "effective_leverage",
        "daily_borrow_cost",
        "tradable_slippage_cost",
        "trading_fees_daily",
        "funding_daily",
        "fee_side_mode",
        "taker_fee_bps",
        "maker_fee_bps",
        "staking_discount_pct",
        "referral_discount_pct",
        "tradable_transition_slippage_bps",
    ]
    missing_fields = [field for field in required_fields if field not in paper_header]
    if missing_fields:
        fail(f"{source_paper_path} missing required paper fields: {missing_fields}")

    annual_borrow_cost_pct = (
        parse_float_maybe(require_uniform_paper_value(paper_rows, field="annual_borrow_cost_pct", context=source_paper_path))
        if "annual_borrow_cost_pct" in paper_header
        else infer_annual_borrow_cost_pct_from_paper(paper_rows, context=source_paper_path)
    )
    if annual_borrow_cost_pct is None:
        fail(f"{source_paper_path} annual_borrow_cost_pct could not be resolved from live paper")

    config = NetCostExportConfig(
        annual_borrow_cost=annual_borrow_cost_pct / 100.0,
        tradable_transition_slippage_bps=parse_float_required(
            {"value": require_uniform_paper_value(paper_rows, field="tradable_transition_slippage_bps", context=source_paper_path)},
            "value",
        ),
        fee_side_mode=require_uniform_paper_value(paper_rows, field="fee_side_mode", context=source_paper_path),
        taker_fee_bps=parse_float_required(
            {"value": require_uniform_paper_value(paper_rows, field="taker_fee_bps", context=source_paper_path)},
            "value",
        ),
        maker_fee_bps=parse_float_required(
            {"value": require_uniform_paper_value(paper_rows, field="maker_fee_bps", context=source_paper_path)},
            "value",
        ),
        staking_discount_pct=parse_float_required(
            {"value": require_uniform_paper_value(paper_rows, field="staking_discount_pct", context=source_paper_path)},
            "value",
        ),
        referral_discount_pct=parse_float_required(
            {"value": require_uniform_paper_value(paper_rows, field="referral_discount_pct", context=source_paper_path)},
            "value",
        ),
    )

    export_frame = build_net_cost_export_frame(
        pd.read_csv(source_paper_path),
        date_col=paper_date_col,
        gross_return_col="realistic_ret_gross",
        held_asset_col="portfolio_held_asset",
        leverage_col="effective_leverage",
        daily_borrow_cost_col="daily_borrow_cost",
        tradable_slippage_cost_col="tradable_slippage_cost",
        trading_fees_daily_col="trading_fees_daily",
        funding_daily_col="funding_daily",
        config=config,
    )
    switch_count = int(export_frame["asset_transition_day"].sum())
    authoritative_export = summarize_net_cost_export(
        export_frame,
        model=output_model,
        switch_count=switch_count,
        trade_count=switch_count,
    )
    authoritative_export.update(derive_sharpe_sortino_from_paper(source_paper_path))

    last_paper_row = paper_rows[-1]
    return {
        "authoritative_export": authoritative_export,
        "source_paper_path": str(source_paper_path),
        "source_latest_available_date": str(last_paper_row.get(paper_date_col) or "").strip() or None,
    }


def build_phase68h_backed_authoritative_export_payload(
    summary_row: dict[str, Any],
    *,
    source_summary_model: str,
    source_paper_path: Path,
    output_model: str,
) -> dict[str, Any]:
    if not source_paper_path.exists():
        fail(f"Missing required source paper for {output_model}: {source_paper_path}")

    paper_header, paper_rows = read_csv_rows(source_paper_path)
    if not paper_rows:
        fail(f"No rows found in {source_paper_path}")

    paper_date_col = "date" if "date" in paper_header else "ts" if "ts" in paper_header else None
    if paper_date_col is None:
        fail(f"{source_paper_path} missing date/ts column")

    if "equity_curve" not in paper_header and "equity" not in paper_header:
        fail(f"{source_paper_path} missing equity-compatible column")
    if "equity_curve_gross" not in paper_header:
        fail(f"{source_paper_path} missing equity_curve_gross required for gross/net export")
    if "equity_curve_net" not in paper_header:
        fail(f"{source_paper_path} missing equity_curve_net required for gross/net export")
    if "realistic_ret" not in paper_header:
        fail(f"{source_paper_path} missing realistic_ret required for sharpe/sortino")
    if "trading_fees_daily" not in paper_header:
        fail(f"{source_paper_path} missing trading_fees_daily required for fee decomposition")
    if "trading_fees_cumulative" not in paper_header:
        fail(f"{source_paper_path} missing trading_fees_cumulative required for fee decomposition")
    if "funding_daily" not in paper_header:
        fail(f"{source_paper_path} missing funding_daily required for funding decomposition")
    if "funding_cumulative" not in paper_header:
        fail(f"{source_paper_path} missing funding_cumulative required for funding decomposition")
    if "portfolio_held_asset" not in paper_header:
        fail(f"{source_paper_path} missing portfolio_held_asset required for switch/cash/btc metrics")

    returns: list[float] = []
    held_assets: list[str] = []
    borrow_cost_total = 0.0
    tradable_slippage_cost_total = 0.0
    for row in paper_rows:
        ret = parse_float_maybe(row.get("realistic_ret"))
        if ret is None:
            fail(f"{source_paper_path} contains empty/invalid realistic_ret")
        returns.append(ret)
        held_assets.append(str(row.get("portfolio_held_asset", "")).strip().upper())
        borrow_cost_total += parse_float_maybe(row.get("daily_borrow_cost")) or 0.0
        tradable_slippage_cost_total += parse_float_maybe(row.get("tradable_slippage_cost")) or 0.0

    sharpe = annualized_sharpe_from_daily_returns(returns)
    sortino = annualized_sortino_from_daily_returns(returns)
    if sharpe is None:
        fail(f"Could not compute sharpe reliably from {source_paper_path}")
    if sortino is None:
        fail(f"Could not compute sortino reliably from {source_paper_path}")

    switch_count = 0
    prev_asset = None
    for asset in held_assets:
        if prev_asset is None:
            prev_asset = asset
            continue
        if asset != prev_asset:
            switch_count += 1
        prev_asset = asset

    if not held_assets:
        fail(f"No held asset rows found in {source_paper_path}")

    derived_day_metrics = derive_strategy_day_metrics_from_csv(
        source_paper_path,
        model=output_model,
    )
    if derived_day_metrics is None:
        fail(f"{source_paper_path} day metrics are unsupported by authoritative strategy semantics")
    if "cash_days_pct" not in derived_day_metrics or "btc_days_pct" not in derived_day_metrics:
        fail(f"{source_paper_path} missing authoritative day metrics")

    cash_days_pct = float(derived_day_metrics["cash_days_pct"])
    btc_days_pct = float(derived_day_metrics["btc_days_pct"])

    last_paper_row = paper_rows[-1]
    total_return_pct_gross = (parse_float_required(last_paper_row, "equity_curve_gross") - 1.0) * 100.0
    total_return_pct_net = (parse_float_required(last_paper_row, "equity_curve_net") - 1.0) * 100.0
    trading_fees_total_pct = parse_float_required(last_paper_row, "trading_fees_cumulative") * 100.0
    funding_total_pct = parse_float_required(last_paper_row, "funding_cumulative") * 100.0

    summary_export_row = {
        "model": output_model,
        "total_return_pct": format_float(total_return_pct_net, 2),
        "total_return_pct_gross": format_float(total_return_pct_gross, 2),
        "total_return_pct_net": format_float(total_return_pct_net, 2),
        "cagr_pct": format_float(parse_float_required(summary_row, "cagr_pct_net"), 2),
        "cagr_pct_gross": format_float(parse_float_required(summary_row, "cagr_pct_gross"), 2),
        "cagr_pct_net": format_float(parse_float_required(summary_row, "cagr_pct_net"), 2),
        "max_drawdown_pct": format_float(parse_float_required(summary_row, "max_drawdown_pct_net"), 2),
        "max_drawdown_pct_gross": format_float(parse_float_required(summary_row, "max_drawdown_pct_gross"), 2),
        "max_drawdown_pct_net": format_float(parse_float_required(summary_row, "max_drawdown_pct_net"), 2),
        "since2023_cagr_pct": format_float(parse_float_required(summary_row, "since2023_cagr_pct_net"), 2),
        "since2023_cagr_pct_gross": format_float(parse_float_required(summary_row, "since2023_cagr_pct_gross"), 2),
        "since2023_cagr_pct_net": format_float(parse_float_required(summary_row, "since2023_cagr_pct_net"), 2),
        "since2025_cagr_pct": format_float(parse_float_required(summary_row, "since2025_cagr_pct_net"), 2),
        "since2025_cagr_pct_gross": format_float(parse_float_required(summary_row, "since2025_cagr_pct_gross"), 2),
        "since2025_cagr_pct_net": format_float(parse_float_required(summary_row, "since2025_cagr_pct_net"), 2),
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
        "annual_borrow_cost_pct": format_float(parse_float_required(summary_row, "annual_borrow_cost_pct"), 4),
        "tradable_transition_slippage_bps": format_float(parse_float_required(summary_row, "tradable_transition_slippage_bps"), 4),
        "fee_side_mode": str(summary_row.get("fee_side_mode", "")).strip(),
        "taker_fee_bps": format_float(parse_float_required(summary_row, "taker_fee_bps"), 4),
        "maker_fee_bps": format_float(parse_float_required(summary_row, "maker_fee_bps"), 4),
        "staking_discount_pct": format_float(parse_float_required(summary_row, "staking_discount_pct"), 4),
        "referral_discount_pct": format_float(parse_float_required(summary_row, "referral_discount_pct"), 4),
        "effective_trading_fee_bps": format_float(parse_float_required(summary_row, "effective_trading_fee_bps"), 4),
    }

    authoritative_export = summarize_net_cost_export(
        build_net_cost_export_frame(
            pd.read_csv(source_paper_path),
            date_col=paper_date_col,
            gross_return_col="realistic_ret_gross",
            held_asset_col="portfolio_held_asset",
            leverage_col="effective_leverage",
            daily_borrow_cost_col="daily_borrow_cost",
            tradable_slippage_cost_col="tradable_slippage_cost",
            trading_fees_daily_col="trading_fees_daily",
            funding_daily_col="funding_daily",
            config=NetCostExportConfig(
                annual_borrow_cost=parse_float_required(summary_row, "annual_borrow_cost_pct") / 100.0,
                tradable_transition_slippage_bps=parse_float_required(summary_row, "tradable_transition_slippage_bps"),
                fee_side_mode=str(summary_row.get("fee_side_mode", "")).strip(),
                taker_fee_bps=parse_float_required(summary_row, "taker_fee_bps"),
                maker_fee_bps=parse_float_required(summary_row, "maker_fee_bps"),
                staking_discount_pct=parse_float_required(summary_row, "staking_discount_pct"),
                referral_discount_pct=parse_float_required(summary_row, "referral_discount_pct"),
            ),
        ),
        model=output_model,
        switch_count=switch_count,
        trade_count=switch_count,
    )

    return {
        "summary_export_row": summary_export_row,
        "authoritative_export": authoritative_export,
        "source_summary_model": source_summary_model,
        "source_paper_path": str(source_paper_path),
        "source_latest_available_date": str(last_paper_row.get(paper_date_col) or "").strip() or None,
    }


def build_phase68i_summary_export() -> dict[str, Any]:
    phase68h_refresh_info = refresh_phase68h_dynamic_paper_if_needed()

    _, summary_rows = read_csv_rows(PHASE68H_SUMMARY_INPUT_PATH)
    if not summary_rows:
        fail(f"No rows found in {PHASE68H_SUMMARY_INPUT_PATH}")

    phase68i_summary_source_row = find_summary_row_required(
        summary_rows,
        model="phase68h_dynamic_ladder_candidate",
        context=str(PHASE68H_SUMMARY_INPUT_PATH),
    )

    if not PHASE68H_DYNAMIC_PAPER_INPUT_PATH.exists():
        fail(f"Missing required phase68h dynamic paper: {PHASE68H_DYNAMIC_PAPER_INPUT_PATH}")

    try:
        shutil.copy2(PHASE68H_DYNAMIC_PAPER_INPUT_PATH, PHASE68I_PAPER_INPUT_PATH)
    except Exception as e:
        fail(f"Failed refreshing phase68i canonical paper from phase68h producer output: {e}")

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

    phase68i_payload = build_phase68h_backed_authoritative_export_payload(
        phase68i_summary_source_row,
        source_summary_model="phase68h_dynamic_ladder_candidate",
        source_paper_path=PHASE68I_PAPER_INPUT_PATH,
        output_model="phase68i_dynamic_ladder_candidate",
    )
    phase68g_refresh_info = refresh_phase68g_native_outputs_if_needed()
    phase68g_source_export_row = read_single_csv_row(PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH)
    phase68g_canonical_metrics_row = build_full_canonical_main_strategy_metrics_row(
        phase68g_source_export_row,
        main_strategy_model="phase68g_66g_1p25x_candidate",
        main_paper_path=PHASE68G_SOURCE_PAPER_PATH,
        metric_fields=HOMEPAGE_MAIN_STRATEGY_METRIC_FIELDS,
    )

    try:
        with PHASE68I_SUMMARY_OUTPUT_PATH.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_header)
            writer.writeheader()
            writer.writerow(phase68i_payload["summary_export_row"])
        pd.DataFrame([phase68i_payload["authoritative_export"]]).to_csv(PHASE68I_AUTHORITATIVE_EXPORT_PATH, index=False)
        shutil.copy2(PHASE68G_SOURCE_PAPER_PATH, PHASE68G_MAIN_PAPER_OUTPUT_PATH)
        with PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(phase68g_canonical_metrics_row.keys()))
            writer.writeheader()
            writer.writerow(phase68g_canonical_metrics_row)
    except Exception as e:
        fail(
            "Failed writing canonical main strategy exports "
            f"({PHASE68I_SUMMARY_OUTPUT_PATH}, {PHASE68I_AUTHORITATIVE_EXPORT_PATH}, "
            f"{PHASE68G_MAIN_PAPER_OUTPUT_PATH}, {PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH}): {e}"
        )

    return {
        "status": "phase68i_summary_export_and_phase68g_exact_metrics_written",
        "summary_source_path": str(PHASE68H_SUMMARY_INPUT_PATH),
        "paper_source_path": str(PHASE68I_PAPER_INPUT_PATH),
        "paper_refresh_source_path": str(PHASE68H_DYNAMIC_PAPER_INPUT_PATH),
        "paper_refresh_info": phase68h_refresh_info,
        "phase68i_source_summary_model": phase68i_payload["source_summary_model"],
        "phase68i_source_paper_path": phase68i_payload["source_paper_path"],
        "output_path": str(PHASE68I_SUMMARY_OUTPUT_PATH),
        "output_info": safe_stat(PHASE68I_SUMMARY_OUTPUT_PATH),
        "authoritative_export_path": str(PHASE68I_AUTHORITATIVE_EXPORT_PATH),
        "authoritative_export_info": safe_stat(PHASE68I_AUTHORITATIVE_EXPORT_PATH),
        "phase68g_refresh_info": phase68g_refresh_info,
        "phase68g_metrics_source_kind": "native_phase68g_authoritative_export_and_paper",
        "phase68g_source_paper_path": str(PHASE68G_SOURCE_PAPER_PATH),
        "phase68g_source_authoritative_export_path": str(PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH),
        "phase68g_source_latest_available_date": phase68g_refresh_info["phase68g_last_date_after_refresh"],
        "main_strategy_paper_alias_path": str(PHASE68G_MAIN_PAPER_OUTPUT_PATH),
        "main_strategy_paper_alias_info": safe_stat(PHASE68G_MAIN_PAPER_OUTPUT_PATH),
        "main_strategy_authoritative_export_alias_path": str(PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH),
        "main_strategy_authoritative_export_alias_info": safe_stat(PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH),
        "computed_fields": [
            "total_return_pct",
            "total_return_pct_gross",
            "total_return_pct_net",
            "cagr_pct",
            "cagr_pct_gross",
            "cagr_pct_net",
            "since2023_cagr_pct",
            "since2023_cagr_pct_gross",
            "since2023_cagr_pct_net",
            "since2025_cagr_pct",
            "since2025_cagr_pct_gross",
            "since2025_cagr_pct_net",
            "max_drawdown_pct",
            "max_drawdown_pct_gross",
            "max_drawdown_pct_net",
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
            "total_return_pct_gross",
            "total_return_pct_net",
            "annual_borrow_cost_pct",
            "tradable_transition_slippage_bps",
            "fee_side_mode",
            "taker_fee_bps",
            "maker_fee_bps",
            "staking_discount_pct",
            "referral_discount_pct",
            "effective_trading_fee_bps",
            "cagr_pct_gross",
            "cagr_pct_net",
            "max_drawdown_pct_gross",
            "max_drawdown_pct_net",
            "since2023_cagr_pct_gross",
            "since2023_cagr_pct_net",
            "since2025_cagr_pct_gross",
            "since2025_cagr_pct_net",
            "switch_count",
            "cash_days_pct",
            "btc_days_pct",
            "trading_fees_total_pct",
            "funding_total_pct",
            "borrow_cost_total_pct",
            "tradable_slippage_cost_total_pct",
        ],
        "derived_fields_written_into_canonical_phase68g_metrics_row": [
            "total_return_pct",
            "cagr_pct",
            "since2023_cagr_pct",
            "since2025_cagr_pct",
            "max_drawdown_pct",
            "sharpe",
            "sortino",
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


def csv_text_value(raw: Any) -> str:
    return str(raw).strip() if raw is not None else ""


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


def derive_switch_count_from_paper(path: Path) -> int | None:
    header, rows = read_csv_rows(path)
    if not rows:
        return None

    for field in ("tradable_transition_day", "asset_transition_day"):
        if field not in header:
            continue
        count = 0
        for row in rows:
            value = csv_json_value(row.get(field))
            if value is True:
                count += 1
            elif isinstance(value, (int, float)) and float(value) != 0.0:
                count += 1
        return count
    return None


def normalize_homepage_main_strategy_metrics(
    summary_row: dict[str, Any],
    *,
    main_strategy_model: str,
    metric_fields: list[str],
    summary_path: Path,
) -> dict[str, Any]:
    metrics = normalized_row(summary_row, metric_fields)

    metrics["model"] = main_strategy_model
    missing_fields = [field for field in metric_fields if field not in metrics]
    if missing_fields:
        fail(
            f"{summary_path} missing required canonical main strategy metric fields: {missing_fields}"
        )
    return metrics


def build_full_canonical_main_strategy_metrics_row(
    summary_row: dict[str, Any],
    *,
    main_strategy_model: str,
    main_paper_path: Path,
    metric_fields: list[str],
) -> dict[str, str]:
    canonical_row = {
        str(key): csv_text_value(value)
        for key, value in summary_row.items()
    }

    for field, candidates in NET_ALIAS_METRIC_FALLBACKS.items():
        resolved_value = ""
        for candidate in candidates:
            candidate_value = canonical_row.get(candidate)
            if candidate_value:
                resolved_value = candidate_value
                break
        if resolved_value:
            canonical_row[field] = resolved_value

    if not canonical_row.get("sharpe") or not canonical_row.get("sortino"):
        derived_risk_metrics = derive_sharpe_sortino_from_paper(main_paper_path)
        for field in ("sharpe", "sortino"):
            if canonical_row.get(field):
                continue
            fallback_value = csv_text_value(derived_risk_metrics.get(field))
            if fallback_value:
                canonical_row[field] = fallback_value

    if not canonical_row.get("cash_days_pct") or not canonical_row.get("btc_days_pct"):
        derived_day_metrics = derive_strategy_day_metrics_from_csv(
            main_paper_path,
            model=main_strategy_model,
        )
        if isinstance(derived_day_metrics, dict):
            for field in ("cash_days_pct", "btc_days_pct"):
                if canonical_row.get(field):
                    continue
                fallback_value = csv_text_value(derived_day_metrics.get(field))
                if fallback_value:
                    canonical_row[field] = fallback_value

    if not canonical_row.get("switch_count"):
        derived_switch_count = derive_switch_count_from_paper(main_paper_path)
        if derived_switch_count is not None:
            canonical_row["switch_count"] = csv_text_value(derived_switch_count)

    canonical_row["model"] = main_strategy_model

    missing_fields = [field for field in metric_fields if not canonical_row.get(field)]
    if missing_fields:
        fail(
            "Full canonical phase68g metrics record is incomplete after materialization "
            f"for {main_paper_path}: missing {missing_fields}"
        )
    return canonical_row


def build_homepage_top_performance_metrics(
    *,
    main_strategy_model: str,
    fallback_metrics: dict[str, Any],
    fallback_summary_path: Path,
) -> tuple[dict[str, Any], Path, str, list[str]]:
    source_contract = resolve_homepage_top_performance_source_contract(
        main_strategy_model,
        root=ROOT,
        require_file=False,
    )
    if source_contract is None:
        return (
            {
                "cagr_pct": fallback_metrics.get("cagr_pct"),
                "since2023_cagr_pct": fallback_metrics.get("since2023_cagr_pct"),
                "since2025_cagr_pct": fallback_metrics.get("since2025_cagr_pct"),
            },
            fallback_summary_path,
            "canonical_app_summary_top_performance_fallback",
            ["cagr_pct", "since2023_cagr_pct", "since2025_cagr_pct"],
        )

    source_path = Path(source_contract["metrics_path"])
    source_row = read_single_csv_row(source_path)
    expected_model = str(main_strategy_model or "").strip()
    actual_model = str(source_row.get("model") or "").strip()
    if expected_model and actual_model and actual_model != expected_model:
        fail(
            "Homepage top performance metric source model diverged "
            f"(expected={expected_model} actual={actual_model} path={source_path})"
        )

    resolved_metrics: dict[str, Any] = {}
    source_fields: list[str] = []
    for display_field, source_field in dict(source_contract["metric_aliases"]).items():
        source_fields.append(source_field)
        value = csv_json_value(source_row.get(source_field))
        if value is None:
            fail(
                "Homepage top performance metric source is missing required field "
                f"{source_field} for {main_strategy_model} in {source_path}"
            )
        resolved_metrics[display_field] = value

    return (
        resolved_metrics,
        source_path,
        str(source_contract["source_family"]),
        source_fields,
    )


def validate_homepage_snapshot_contract(
    snapshot: dict[str, Any],
    current_strategy_contract: dict[str, Any],
) -> None:
    try:
        validate_product_snapshot_current_strategy_contract(
            snapshot,
            current_strategy_contract,
            context="app_product_snapshot build blocked:",
        )
    except ValueError as exc:
        fail(str(exc))


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
    current_strategy_contract = load_current_main_strategy_root_contract()
    main_strategy_model = product_contract["main_strategy_model"]
    reference_strategy_model = product_contract["reference_strategy_model"]
    main_summary_path = current_strategy_contract["metrics_path"]
    main_paper_path = current_strategy_contract["paper_path"]
    reference_paper_path = product_contract["reference_paper_path"]
    summary_row = read_single_csv_row(main_summary_path)
    main_paper_row = read_last_csv_row(main_paper_path)
    trend_row = read_optional_single_csv_row(PHASE66G_LIVE_STATUS_PATH)
    freshness_payload = read_json_optional(APP_FRESHNESS_REPORT_PATH)
    freshness_checks = build_canonical_product_freshness_checks(freshness_payload)

    metric_fields = list(HOMEPAGE_MAIN_STRATEGY_METRIC_FIELDS)
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
        metric_fields=metric_fields,
        summary_path=main_summary_path,
    )
    main_strategy_top_performance_metrics, top_performance_source_path, top_performance_source_type, top_performance_source_fields = (
        build_homepage_top_performance_metrics(
            main_strategy_model=main_strategy_model,
            fallback_metrics=main_strategy_metrics,
            fallback_summary_path=main_summary_path,
        )
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
        "main_strategy_top_performance_metrics": {
            **source_metadata(top_performance_source_path, top_performance_source_type),
            "source_fields": top_performance_source_fields,
        },
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
        "schema_version": 2,
        "app_export_generated_at_utc": app_export_generated_at_utc,
        "product_name": product_contract["product_name"],
        "page_scope": "homepage",
        "current_main_strategy_root_contract": serialize_current_main_strategy_root_contract(
            current_strategy_contract
        ),
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
        "main_strategy_top_performance_metrics": main_strategy_top_performance_metrics,
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
    validate_homepage_snapshot_contract(snapshot, current_strategy_contract=current_strategy_contract)
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
            "phase68g canonical main strategy paper/export aliases are refreshed from the native phase68g validation family with the official phase67j baseline paper, never from any phase68h static-reference row.",
            "phase68g current main strategy contract paths remain canonical aliases under outputs/execution/app_exports/ while sourcing their contents from refreshed native phase68g producer outputs.",
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
        "phase68g_main_strategy_paper_alias_written": PHASE68G_MAIN_PAPER_OUTPUT_PATH.exists(),
        "phase68g_main_strategy_authoritative_export_alias_written": PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH.exists(),
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
            str(PHASE68G_MAIN_PAPER_OUTPUT_PATH.resolve()),
            str(PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH.resolve()),
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

