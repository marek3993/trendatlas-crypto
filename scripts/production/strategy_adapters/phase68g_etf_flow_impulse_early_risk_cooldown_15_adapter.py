from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.approved_strategy_net_export_helper import CASH_EQUIVALENT_ASSETS
import scripts.dev_only_phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate as dev_only_rebuild
from scripts.production.strategy_adapters.phase68g_btc_persistence_10d_early_risk_075_adapter import (
    CANDIDATE_ID as BTC_PERSISTENCE_CANDIDATE_ID,
)


PRODUCTION_STRATEGY_ID = "staged_strategy_candidate"
CANDIDATE_ID = "phase68g_etf_flow_impulse_early_risk_cooldown_15"
BASE_STRATEGY_VERSION = BTC_PERSISTENCE_CANDIDATE_ID
ADAPTER_NAME = "phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter"

SNAPSHOT_SCHEMA_VERSION = 1
DIAGNOSTICS_SCHEMA_VERSION = 1
QUALITY_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
COMPARE_SCHEMA_VERSION = 1
SUMMARY_TOLERANCE = 1e-9

EARLY_RISK_ASSET = "BTC"
EARLY_RISK_EXPOSURE = 0.5
FLOW_3D_FLOOR_USD = 500_000_000.0
BTC_EMA_DAYS = 10
COOLDOWN_DAYS = 15

COMPARE_WINDOWS: tuple[tuple[str, str | None], ...] = (
    ("full_etf_overlap", None),
    ("since2025", "2025-01-01"),
)
ISO_DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_MIDNIGHT_PATTERN = re.compile(
    r"^(?P<day>\d{4}-\d{2}-\d{2})[ T]00:00:00(?:\.0+)?(?:Z|[+-]00:?00)?$"
)

EXPECTED_LIVE_TRUTH = BTC_PERSISTENCE_CANDIDATE_ID
EXPECTED_FALLBACK = "phase68g_66g_1p25x_candidate"
LIVE_PRODUCTION_STRATEGY_ID = "current_strategy"
LIVE_STRATEGY_VERSION = CANDIDATE_ID
LIVE_ADAPTER_NAME = "phase68g_etf_flow_impulse_early_risk_cooldown_15_live_adapter"

PROTECTED_RELATIVE_PATHS: tuple[str, ...] = (
    "app.py",
    "source_of_truth/master_state.md",
    "source_of_truth/project_truth.json",
    "source_of_truth/export_contract.json",
    "outputs/production/current_strategy_snapshot.json",
    "outputs/production/current_strategy_timeseries.csv",
    "outputs/production/current_strategy_diagnostics.json",
    "outputs/execution/intents/latest_execution_intent.json",
    "outputs/execution/live_gate/latest_real_order_gate_decision.json",
    "outputs/execution/authority/latest_successful_snapshot.json",
    "outputs/execution/authority/latest_attempt_status.json",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _read_dataframe_required(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required CSV file: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if frame.empty:
        raise ValueError(f"CSV has no rows in {path}")
    return frame


def _read_single_csv_row_required(path: Path) -> dict[str, Any]:
    frame = _read_dataframe_required(path)
    return {str(key).strip(): value for key, value in frame.iloc[-1].to_dict().items()}


def _path_for_manifest(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _normalize_iso_day_text(value: Any, *, context: str) -> str:
    if value is None:
        raise ValueError(f"{context} is missing")
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            raise ValueError(f"{context} is missing")
        stamp = value
        if stamp.time() != datetime.min.time() or stamp.nanosecond != 0:
            raise ValueError(f"{context} is not an ISO day: {value}")
        return stamp.strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        stamp = pd.Timestamp(value)
        if stamp.time() != datetime.min.time() or stamp.nanosecond != 0:
            raise ValueError(f"{context} is not an ISO day: {value}")
        return stamp.strftime("%Y-%m-%d")
    if isinstance(value, date_cls):
        return value.isoformat()

    text = str(value).strip()
    if not text:
        raise ValueError(f"{context} is missing")
    if ISO_DAY_PATTERN.fullmatch(text):
        return text
    match = ISO_MIDNIGHT_PATTERN.fullmatch(text)
    if match:
        return match.group("day")
    raise ValueError(f"{context} is not an ISO day: {value}")


def _normalize_asset_code(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized or normalized in {"NONE", "OUT_OF_MARKET", "NAN", "NULL"}:
        return "CASH"
    if normalized in CASH_EQUIVALENT_ASSETS:
        return "CASH"
    return normalized


def _classify_regime(asset: str) -> str:
    normalized = _normalize_asset_code(asset)
    if normalized in CASH_EQUIVALENT_ASSETS:
        return "CASH"
    if normalized == "BTC":
        return "BTC"
    if normalized == "BASE":
        return "BASE"
    return "ALT"


def _to_float_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _to_bool_series(series: pd.Series) -> pd.Series:
    lowered = series.fillna("").astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y"})


def _rolling_compound_return(series: pd.Series, window: int) -> pd.Series:
    return (
        (1.0 + pd.to_numeric(series, errors="coerce").fillna(0.0))
        .rolling(window=window, min_periods=window)
        .apply(np.prod, raw=True)
        - 1.0
    )


def _rolling_sharpe(series: pd.Series, window: int) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0)
    mean = clean.rolling(window=window, min_periods=window).mean()
    std = clean.rolling(window=window, min_periods=window).std(ddof=0)
    sharpe = (mean / std.replace(0.0, np.nan)) * np.sqrt(365.25)
    return sharpe.replace([np.inf, -np.inf], np.nan)


def _annualized_sharpe_from_daily_returns(series: pd.Series) -> float | None:
    daily_returns = pd.to_numeric(series, errors="coerce").dropna().tolist()
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    variance = sum((value - mean_ret) ** 2 for value in daily_returns) / (len(daily_returns) - 1)
    if variance <= 0:
        return None
    std = variance**0.5
    if std == 0:
        return None
    return (mean_ret / std) * (365**0.5)


def _annualized_sortino_from_daily_returns(series: pd.Series) -> float | None:
    daily_returns = pd.to_numeric(series, errors="coerce").dropna().tolist()
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    downside = [value for value in daily_returns if value < 0]
    if len(downside) < 2:
        return None
    downside_mean = sum(downside) / len(downside)
    downside_variance = sum((value - downside_mean) ** 2 for value in downside) / (len(downside) - 1)
    if downside_variance <= 0:
        return None
    downside_std = downside_variance**0.5
    if downside_std == 0:
        return None
    return (mean_ret / downside_std) * (365**0.5)


def _build_equity_curve(series: pd.Series) -> pd.Series:
    return (1.0 + pd.to_numeric(series, errors="coerce").fillna(0.0)).cumprod()


def _compute_total_return_pct(series: pd.Series) -> float:
    equity = _build_equity_curve(series)
    if equity.empty:
        return 0.0
    return float((equity.iloc[-1] - 1.0) * 100.0)


def _compute_cagr_pct(series: pd.Series, date_index: pd.Index) -> float:
    if len(series) < 2:
        return 0.0
    equity = _build_equity_curve(series)
    start_dt = pd.Timestamp(date_index[0])
    end_dt = pd.Timestamp(date_index[-1])
    days = max(int((end_dt - start_dt).days), 1)
    years = days / 365.25
    if years <= 0 or equity.iloc[-1] <= 0:
        return 0.0
    return float(((equity.iloc[-1] ** (1.0 / years)) - 1.0) * 100.0)


def _compute_max_drawdown_pct(series: pd.Series) -> float:
    equity = _build_equity_curve(series)
    if equity.empty:
        return 0.0
    drawdown = (equity / equity.cummax()) - 1.0
    return float(drawdown.min() * 100.0)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_file_metadata(path: Path, *, last_date: str | None = None, row_count: int | None = None) -> dict[str, Any]:
    stat = path.stat()
    payload: dict[str, Any] = {
        "path": _path_for_manifest(path, root=ROOT),
        "sha256": _sha256_file(path),
        "size_bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    if last_date is not None:
        payload["last_date"] = last_date
    if row_count is not None:
        payload["row_count"] = int(row_count)
    return payload


def capture_protected_state(*, root: Path | None = None) -> dict[str, dict[str, Any]]:
    repo_root = (root or ROOT).resolve()
    payload: dict[str, dict[str, Any]] = {}
    for relative_path in PROTECTED_RELATIVE_PATHS:
        path = repo_root / relative_path
        if not path.exists():
            payload[relative_path] = {
                "path": relative_path,
                "exists": False,
            }
            continue
        payload[relative_path] = {
            **_source_file_metadata(path),
            "path": relative_path,
            "exists": True,
        }
    return payload


def read_truth_contract_state(*, root: Path | None = None) -> dict[str, Any]:
    repo_root = (root or ROOT).resolve()
    project_truth = _read_json_required(repo_root / "source_of_truth" / "project_truth.json")
    export_contract = _read_json_required(repo_root / "source_of_truth" / "export_contract.json")
    baseline_snapshot = _read_json_required(repo_root / "outputs" / "production" / "current_strategy_snapshot.json")
    app_product_truth = project_truth.get("app_product_truth", {})
    leverage_truth = project_truth.get("leverage_truth", {})
    production_core_truth = project_truth.get("production_core_truth", {})
    app_live_contract = export_contract.get("app_export_contract", {}).get("app_live_mode_contract", {}).get("current", {})
    production_core_contract = export_contract.get("production_core_truth_contract", {})
    return {
        "project_truth_app_main_strategy_model": str(app_product_truth.get("main_strategy_model") or "").strip(),
        "project_truth_current_live_truth": str(leverage_truth.get("current_live_truth") or "").strip(),
        "project_truth_official_fallback": str(leverage_truth.get("official_softer_fallback") or "").strip(),
        "project_truth_production_core_strategy_version": str(production_core_truth.get("strategy_version") or "").strip(),
        "export_contract_main_strategy_model": str(export_contract.get("app_export_contract", {}).get("main_strategy_model") or "").strip(),
        "export_contract_live_truth_mode": str(app_live_contract.get("live_truth_mode") or "").strip(),
        "export_contract_fallback_profile_label": str(app_live_contract.get("fallback_profile_label") or "").strip(),
        "export_contract_production_core_strategy_version": str(production_core_contract.get("strategy_version") or "").strip(),
        "baseline_snapshot_strategy_version": str(baseline_snapshot.get("strategy_version") or "").strip(),
    }


def expected_truth_contract_state() -> dict[str, str]:
    return {
        "project_truth_app_main_strategy_model": EXPECTED_LIVE_TRUTH,
        "project_truth_current_live_truth": EXPECTED_LIVE_TRUTH,
        "project_truth_official_fallback": EXPECTED_FALLBACK,
        "project_truth_production_core_strategy_version": EXPECTED_LIVE_TRUTH,
        "export_contract_main_strategy_model": EXPECTED_LIVE_TRUTH,
        "export_contract_live_truth_mode": EXPECTED_LIVE_TRUTH,
        "export_contract_fallback_profile_label": EXPECTED_FALLBACK,
        "export_contract_production_core_strategy_version": EXPECTED_LIVE_TRUTH,
        "baseline_snapshot_strategy_version": EXPECTED_LIVE_TRUTH,
    }


def _load_authorized_compare_reference(*, source_paths: dict[str, Path]) -> dict[str, Any]:
    snapshot = _read_json_required(source_paths["baseline_snapshot"])
    diagnostics = _read_json_required(source_paths["baseline_diagnostics"])
    timeseries = _read_dataframe_required(source_paths["baseline_timeseries"])

    closed_day = _normalize_iso_day_text(
        snapshot.get("closed_day"),
        context="baseline_snapshot.closed_day",
    )
    diagnostics_closed_day = _normalize_iso_day_text(
        diagnostics.get("closed_day"),
        context="baseline_diagnostics.closed_day",
    )
    timeseries_last_day = _normalize_iso_day_text(
        timeseries["date"].iloc[-1],
        context="baseline_timeseries.last_row.date",
    )
    if diagnostics_closed_day != closed_day:
        raise ValueError(
            "Baseline diagnostics closed_day mismatch: "
            f"actual={diagnostics_closed_day!r} expected={closed_day!r}"
        )
    if timeseries_last_day != closed_day:
        raise ValueError(
            "Baseline timeseries last_row.date mismatch: "
            f"actual={timeseries_last_day!r} expected={closed_day!r}"
        )
    if str(snapshot.get("strategy_version") or "").strip() != BASE_STRATEGY_VERSION:
        raise ValueError(
            "Baseline snapshot strategy_version mismatch: "
            f"actual={snapshot.get('strategy_version')!r} expected={BASE_STRATEGY_VERSION!r}"
        )

    return {
        "snapshot": snapshot,
        "diagnostics": diagnostics,
        "timeseries": timeseries,
        "closed_day": closed_day,
        "snapshot_path": source_paths["baseline_snapshot"],
        "timeseries_path": source_paths["baseline_timeseries"],
        "diagnostics_path": source_paths["baseline_diagnostics"],
    }


def _compare_authorized_vs_durable_baseline(
    durable_timeseries: pd.DataFrame,
    authorized_timeseries: pd.DataFrame,
) -> None:
    required_columns = [
        "date",
        "candidate_asset",
        "selected_asset",
        "actual_held_asset",
        "authorized_tradable_asset",
        "current_asset",
        "effective_market_exposure",
        "current_exposure",
        "return_gross",
        "return_net",
        "equity",
        "turnover",
        "fees_daily",
        "funding_daily",
        "borrow_cost_daily",
        "slippage_cost_daily",
        "reason_code",
        "trend_permission_active",
    ]
    for column in required_columns:
        if column not in durable_timeseries.columns or column not in authorized_timeseries.columns:
            raise ValueError(f"Missing required baseline comparison column: {column}")
    if len(durable_timeseries) != len(authorized_timeseries):
        raise ValueError(
            "Durable BTC-persistence rebuild does not match authorized baseline row count "
            f"(durable={len(durable_timeseries)} authorized={len(authorized_timeseries)})"
        )
    text_columns = {
        "date",
        "candidate_asset",
        "selected_asset",
        "actual_held_asset",
        "authorized_tradable_asset",
        "current_asset",
        "reason_code",
    }
    for column in required_columns:
        left = durable_timeseries[column]
        right = authorized_timeseries[column]
        if column in text_columns:
            if left.fillna("").astype(str).tolist() != right.fillna("").astype(str).tolist():
                raise ValueError(
                    f"Durable BTC-persistence rebuild diverges from authorized baseline on {column}"
                )
            continue
        if column == "trend_permission_active":
            if _to_bool_series(left).tolist() != _to_bool_series(right).tolist():
                raise ValueError(
                    "Durable BTC-persistence rebuild diverges from authorized baseline on "
                    f"{column}"
                )
            continue
        if (
            _to_float_series(left).round(12) - _to_float_series(right).round(12)
        ).abs().gt(1e-12).any():
            raise ValueError(
                f"Durable BTC-persistence rebuild diverges from authorized baseline on {column}"
            )


def _to_float_value(value: Any, *, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return default
    return float(numeric)


def _normalize_durable_baseline_timeseries(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized = normalized.dropna(subset=["date"]).sort_values("date")
    normalized = normalized.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if normalized.empty:
        raise ValueError("durable BTC-persistence paper has no usable rows after date normalization")
    return normalized


def _normalize_baseline_frame_from_timeseries(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    normalized = _normalize_durable_baseline_timeseries(frame)
    stress_column = "stress_block_day" if "stress_block_day" in normalized.columns else ""
    if stress_column:
        hard_invalidation_note = (
            "stress_block_day is present and is used directly as the hard invalidation / "
            "risk-off equivalent."
        )
        fallback_used = False
        stress_values = normalized[stress_column].fillna(False)
    else:
        hard_invalidation_note = (
            "stress_block_day is unavailable, so hard invalidation falls back to False on all rows."
        )
        fallback_used = True
        stress_values = False

    adapted = normalized.copy()
    adapted["portfolio_held_asset"] = adapted["current_asset"].fillna("CASH").astype(str).str.upper()
    adapted["is_exposed"] = pd.to_numeric(
        adapted["effective_market_exposure"],
        errors="coerce",
    ).fillna(0.0).gt(0.0)
    adapted["effective_leverage"] = pd.to_numeric(
        adapted["current_exposure"],
        errors="coerce",
    ).fillna(0.0)
    adapted["realistic_ret_gross"] = pd.to_numeric(
        adapted["return_gross"],
        errors="coerce",
    ).fillna(0.0)
    adapted["stress_block_active"] = pd.Series(stress_values, index=adapted.index).fillna(False)
    adapted = adapted.drop(columns=[column for column in ["btc_close", "btc_return"] if column in adapted.columns])
    adapted = adapted.set_index("date", drop=False)

    return adapted, {
        "source_column": stress_column or None,
        "fallback_used": fallback_used,
        "detail": hard_invalidation_note,
    }


def _build_durable_baseline_carry_forward_row(
    *,
    last_row: pd.Series,
    target_day: pd.Timestamp,
    benchmark_close: float,
    annual_borrow_cost_pct: float,
) -> pd.Series:
    row = last_row.copy()
    last_day_text = pd.Timestamp(last_row["date"]).strftime("%Y-%m-%d")
    target_day_text = target_day.strftime("%Y-%m-%d")

    held_asset = _normalize_asset_code(
        last_row.get("actual_held_asset", last_row.get("current_asset", last_row.get("held_asset")))
    )
    exposure = _to_float_value(
        last_row.get(
            "effective_market_exposure",
            last_row.get("current_exposure", last_row.get("exposure", 0.0)),
        )
    )
    previous_btc_close = _to_float_value(last_row.get("btc_close"))
    if previous_btc_close <= 0.0:
        raise ValueError(
            "Unable to carry forward durable BTC-persistence paper without a prior BTC close "
            f"(paper_last_day={last_day_text})"
        )
    if held_asset not in CASH_EQUIVALENT_ASSETS and held_asset != "BTC":
        raise ValueError(
            "durable BTC-persistence paper is stale relative to the validated closed day, and the "
            "latest held asset requires fresh non-BTC paper rows to extend safely "
            f"(paper_last_day={last_day_text} target_day={target_day_text} held_asset={held_asset})"
        )

    btc_return = (benchmark_close / previous_btc_close) - 1.0
    gross_return = 0.0
    if held_asset == "BTC" and exposure > SUMMARY_TOLERANCE:
        gross_return = btc_return * exposure
    borrow_cost_daily = 0.0
    leveraged_component = max(exposure - 1.0, 0.0)
    if held_asset == "BTC" and leveraged_component > SUMMARY_TOLERANCE:
        borrow_cost_daily = leveraged_component * (annual_borrow_cost_pct / 100.0) / 365.25
    net_return = gross_return - borrow_cost_daily

    previous_equity = _to_float_value(last_row.get("equity"), default=1.0)
    next_equity = previous_equity * (1.0 + net_return)
    previous_drawdown_pct = _to_float_value(last_row.get("drawdown_pct"))
    previous_peak_equity = previous_equity
    if previous_drawdown_pct < 0.0:
        previous_peak_equity = previous_equity / max(1.0 + (previous_drawdown_pct / 100.0), 1e-12)
    peak_equity = max(previous_peak_equity, next_equity)
    next_drawdown_pct = ((next_equity / peak_equity) - 1.0) * 100.0 if peak_equity > 0.0 else 0.0

    row["date"] = target_day
    row["btc_close"] = round(benchmark_close, 12)
    if "btc_return" in row.index:
        row["btc_return"] = round(btc_return, 12)
    if "btc_baseline_equity" in row.index:
        row["btc_baseline_equity"] = round(
            _to_float_value(last_row.get("btc_baseline_equity"), default=1.0) * (1.0 + btc_return),
            12,
        )
    if "btc_baseline_index" in row.index:
        row["btc_baseline_index"] = round(
            _to_float_value(row.get("btc_baseline_equity"), default=1.0) * 100.0,
            12,
        )
    for column in ("model_candidate_return_gross", "authorized_return_gross", "return_gross"):
        if column in row.index:
            row[column] = round(gross_return, 12)
    for column in ("model_candidate_return_net", "authorized_return_net", "return_net"):
        if column in row.index:
            row[column] = round(net_return, 12)
    for column in ("model_candidate_equity", "authorized_equity", "equity"):
        if column in row.index:
            row[column] = round(next_equity, 12)
    if "drawdown_pct" in row.index:
        row["drawdown_pct"] = round(next_drawdown_pct, 6)
    if "fees_daily" in row.index:
        row["fees_daily"] = 0.0
    if "funding_daily" in row.index:
        row["funding_daily"] = 0.0
    if "borrow_cost_daily" in row.index:
        row["borrow_cost_daily"] = round(borrow_cost_daily, 12)
    if "slippage_cost_daily" in row.index:
        row["slippage_cost_daily"] = 0.0
    if "turnover" in row.index:
        row["turnover"] = 0.0
    if "fees_cumulative" in row.index:
        row["fees_cumulative"] = round(
            _to_float_value(last_row.get("fees_cumulative")) + _to_float_value(row.get("fees_daily")),
            12,
        )
    if "funding_cumulative" in row.index:
        row["funding_cumulative"] = round(
            _to_float_value(last_row.get("funding_cumulative")) + _to_float_value(row.get("funding_daily")),
            12,
        )
    if "borrow_cost_cumulative" in row.index:
        row["borrow_cost_cumulative"] = round(
            _to_float_value(last_row.get("borrow_cost_cumulative"))
            + _to_float_value(row.get("borrow_cost_daily")),
            12,
        )
    if "slippage_cost_cumulative" in row.index:
        row["slippage_cost_cumulative"] = round(
            _to_float_value(last_row.get("slippage_cost_cumulative"))
            + _to_float_value(row.get("slippage_cost_daily")),
            12,
        )
    if "cash_day" in row.index:
        row["cash_day"] = held_asset in CASH_EQUIVALENT_ASSETS or exposure <= SUMMARY_TOLERANCE
    if "btc_day" in row.index:
        row["btc_day"] = held_asset == "BTC" and exposure > SUMMARY_TOLERANCE
    if "in_market" in row.index:
        row["in_market"] = exposure > SUMMARY_TOLERANCE
    if "is_rebalance_day" in row.index:
        row["is_rebalance_day"] = False
    if "asset_transition_day" in row.index:
        row["asset_transition_day"] = False
    return row


def _materialize_durable_baseline_timeseries_to_closed_day(
    *,
    durable_baseline_timeseries: pd.DataFrame,
    summary_row: dict[str, Any],
    benchmark_df: pd.DataFrame,
    target_closed_day: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    materialized = _normalize_durable_baseline_timeseries(durable_baseline_timeseries)
    source_last_day = pd.Timestamp(materialized["date"].iloc[-1]).strftime("%Y-%m-%d")
    target_day = pd.Timestamp(target_closed_day)
    if pd.Timestamp(source_last_day) > target_day:
        raise ValueError(
            "durable BTC-persistence paper last_row.date cannot be ahead of the validated closed day "
            f"(paper={source_last_day} closed_day={target_closed_day})"
        )
    if source_last_day == target_closed_day:
        return materialized, {
            "paper_source_last_day": source_last_day,
            "materialized_closed_day": target_closed_day,
            "carry_forward_rows_added": 0,
        }

    benchmark = benchmark_df.copy()
    benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce")
    benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
    benchmark = benchmark.dropna(subset=["date", "close"]).sort_values("date")
    benchmark = benchmark.drop_duplicates(subset=["date"], keep="last").set_index("date")
    carry_forward_days = benchmark.index[
        (benchmark.index > pd.Timestamp(source_last_day)) & (benchmark.index <= target_day)
    ]
    if carry_forward_days.empty or carry_forward_days[-1] != target_day:
        raise ValueError(
            "btc_ohlcv is missing one or more rows needed to materialize the validated durable closed day "
            f"(paper={source_last_day} closed_day={target_closed_day})"
        )

    annual_borrow_cost_pct = _to_float_value(summary_row.get("annual_borrow_cost_pct"))
    added_rows = 0
    for carry_day in carry_forward_days.tolist():
        next_row = _build_durable_baseline_carry_forward_row(
            last_row=materialized.iloc[-1],
            target_day=pd.Timestamp(carry_day),
            benchmark_close=float(benchmark.loc[carry_day, "close"]),
            annual_borrow_cost_pct=annual_borrow_cost_pct,
        )
        materialized = pd.concat([materialized, pd.DataFrame([next_row])], ignore_index=True)
        added_rows += 1

    return materialized, {
        "paper_source_last_day": source_last_day,
        "materialized_closed_day": pd.Timestamp(materialized["date"].iloc[-1]).strftime("%Y-%m-%d"),
        "carry_forward_rows_added": added_rows,
    }


def _load_shared_inputs(
    *,
    root: Path | None = None,
    source_paths: dict[str, Path],
    require_authorized_compare_reference: bool,
) -> dict[str, Any]:
    repo_root = (root or ROOT).resolve()
    durable_baseline_summary_row = _read_single_csv_row_required(
        source_paths["durable_baseline_summary"]
    )
    durable_baseline_timeseries = _read_dataframe_required(
        source_paths["durable_baseline_paper"]
    )
    durable_baseline_paper_row_count = int(len(durable_baseline_timeseries))
    trend_status_row = _read_single_csv_row_required(
        source_paths["durable_baseline_trend_status"]
    )
    trend_history_df = _read_dataframe_required(
        source_paths["durable_baseline_trend_history"]
    )
    freshness_payload = _read_json_required(
        source_paths["durable_baseline_freshness_report"]
    )
    benchmark_df = _read_dataframe_required(source_paths["btc_ohlcv"])

    durable_baseline_summary_day = _normalize_iso_day_text(
        durable_baseline_summary_row.get("latest_available_date"),
        context="durable_baseline_summary.latest_available_date",
    )
    durable_baseline_paper_last_day = _normalize_iso_day_text(
        durable_baseline_timeseries["date"].iloc[-1],
        context="durable_baseline_paper.last_row.date",
    )
    trend_status_day = _normalize_iso_day_text(
        trend_status_row.get("latest_available_date"),
        context="durable_baseline_trend_status.latest_available_date",
    )
    trend_history_last_day = _normalize_iso_day_text(
        trend_history_df["trend_calc_date"].iloc[-1]
        if "trend_calc_date" in trend_history_df.columns
        else trend_history_df["date"].iloc[-1],
        context="durable_baseline_trend_history.last_row.day",
    )
    freshness_closed_day = _normalize_iso_day_text(
        freshness_payload.get("latest_closed_utc_date"),
        context="durable_baseline_freshness_report.latest_closed_utc_date",
    )
    benchmark_dates = pd.to_datetime(benchmark_df["date"], errors="coerce")
    benchmark_day_set = {
        stamp.strftime("%Y-%m-%d") for stamp in benchmark_dates.dropna().tolist()
    }
    benchmark_last_day = _normalize_iso_day_text(
        benchmark_dates.iloc[-1].strftime("%Y-%m-%d"),
        context="btc_ohlcv.last_row.date",
    )
    baseline_source_closed_day = trend_status_day
    baseline_closed_day = benchmark_last_day

    freshness_status = str(freshness_payload.get("status") or "").strip().lower()
    freshness_errors = freshness_payload.get("errors")
    if freshness_status not in {"ok", "success", "current"}:
        raise ValueError(
            "durable baseline freshness_report.status must be green for production build "
            f"(actual={freshness_status or 'missing'})"
        )
    if isinstance(freshness_errors, list) and freshness_errors:
        raise ValueError(
            "durable baseline freshness_report.errors must be empty for production build"
        )
    if trend_history_last_day != baseline_source_closed_day:
        raise ValueError(
            "durable BTC-persistence trend_history last day must match trend_status latest_available_date "
            f"(trend_history={trend_history_last_day} trend_status={baseline_source_closed_day})"
        )
    if freshness_closed_day != baseline_source_closed_day:
        raise ValueError(
            "durable BTC-persistence freshness closed_day must match trend_status latest_available_date "
            f"(freshness={freshness_closed_day} trend_status={baseline_source_closed_day})"
        )
    if pd.Timestamp(baseline_closed_day) < pd.Timestamp(baseline_source_closed_day):
        raise ValueError(
            "btc_ohlcv cannot be behind the validated durable BTC-persistence source day "
            f"(btc_last_day={benchmark_last_day} source_day={baseline_source_closed_day})"
        )
    if pd.Timestamp(baseline_closed_day) > pd.Timestamp(baseline_source_closed_day):
        next_rebalance_text = str(trend_status_row.get("next_rebalance_date") or "").strip()
        if not next_rebalance_text:
            raise ValueError(
                "durable BTC-persistence baseline cannot be carried forward without "
                "next_rebalance_date on the trend status row"
            )
        next_rebalance_day = _normalize_iso_day_text(
            next_rebalance_text,
            context="durable_baseline_trend_status.next_rebalance_date",
        )
        if pd.Timestamp(baseline_closed_day) >= pd.Timestamp(next_rebalance_day):
            raise ValueError(
                "durable BTC-persistence baseline carry-forward would cross a rebalance boundary "
                f"(source_day={baseline_source_closed_day} target_day={baseline_closed_day} "
                f"next_rebalance_date={next_rebalance_day})"
            )
    if baseline_closed_day not in benchmark_day_set:
        raise ValueError(
            "btc_ohlcv must contain the validated durable BTC-persistence closed day "
            f"(closed_day={baseline_closed_day} btc_last_day={benchmark_last_day})"
        )
    durable_baseline_timeseries, paper_materialization_meta = (
        _materialize_durable_baseline_timeseries_to_closed_day(
            durable_baseline_timeseries=durable_baseline_timeseries,
            summary_row=durable_baseline_summary_row,
            benchmark_df=benchmark_df,
            target_closed_day=baseline_closed_day,
        )
    )
    materialized_paper_last_day = _normalize_iso_day_text(
        pd.Timestamp(durable_baseline_timeseries["date"].iloc[-1]).strftime("%Y-%m-%d"),
        context="materialized_durable_baseline_paper.last_row.date",
    )
    if materialized_paper_last_day != baseline_closed_day:
        raise ValueError(
            "materialized durable BTC-persistence paper last_row.date must match the validated closed day "
            f"(paper={materialized_paper_last_day} closed_day={baseline_closed_day})"
        )

    durable_baseline_source_inputs = {
        "strategy_version": BASE_STRATEGY_VERSION,
        "validated_closed_day": baseline_closed_day,
        "paper_materialization": {
            "summary_latest_available_date": durable_baseline_summary_day,
            **paper_materialization_meta,
        },
        "files": {
            "durable_baseline_summary": _source_file_metadata(
                source_paths["durable_baseline_summary"],
                last_date=durable_baseline_summary_day,
                row_count=1,
            ),
            "durable_baseline_paper": _source_file_metadata(
                source_paths["durable_baseline_paper"],
                last_date=durable_baseline_paper_last_day,
                row_count=durable_baseline_paper_row_count,
            ),
            "durable_baseline_trend_status": _source_file_metadata(
                source_paths["durable_baseline_trend_status"],
                last_date=trend_status_day,
                row_count=1,
            ),
            "durable_baseline_trend_history": _source_file_metadata(
                source_paths["durable_baseline_trend_history"],
                last_date=trend_history_last_day,
                row_count=len(trend_history_df),
            ),
            "durable_baseline_freshness_report": {
                **_source_file_metadata(source_paths["durable_baseline_freshness_report"]),
                "closed_day": freshness_closed_day,
                "status": freshness_status,
            },
            "benchmark_ohlcv": _source_file_metadata(
                source_paths["btc_ohlcv"],
                last_date=benchmark_last_day,
                row_count=len(benchmark_df),
            ),
        },
    }
    current_closed_day = baseline_closed_day
    authorized_compare_reference = None

    if require_authorized_compare_reference:
        authorized_compare_reference = _load_authorized_compare_reference(
            source_paths=source_paths
        )
        current_closed_day = authorized_compare_reference["closed_day"]
        if current_closed_day != baseline_closed_day:
            raise ValueError(
                "Durable BTC-persistence baseline closed_day does not match the current "
                "authorized compare baseline "
                f"(durable={baseline_closed_day} current={current_closed_day})"
            )
        _compare_authorized_vs_durable_baseline(
            durable_baseline_timeseries,
            authorized_compare_reference["timeseries"],
        )

    cost_config, cost_config_meta = dev_only_rebuild.derive_cost_config(
        durable_baseline_timeseries
    )
    input_refs = dev_only_rebuild.build_input_refs(cost_config_meta)

    baseline_probe_frame, hard_invalidation_meta = _normalize_baseline_frame_from_timeseries(
        durable_baseline_timeseries
    )
    probe_mod, cooldown_mod = dev_only_rebuild.load_phase68g_helpers()
    etf_df = probe_mod.load_etf_panel(source_paths["etf_panel"])
    btc_df = probe_mod.load_btc_frame(source_paths["btc_ohlcv"])
    etf_panel_last_day = _normalize_iso_day_text(
        pd.Timestamp(etf_df.index[-1]).strftime("%Y-%m-%d"),
        context="etf_panel.last_row.date",
    )
    if pd.Timestamp(etf_panel_last_day) < pd.Timestamp(baseline_closed_day):
        raise ValueError(
            "ETF-flow causal panel must cover the validated durable BTC-persistence closed day "
            f"(etf_panel={etf_panel_last_day} closed_day={baseline_closed_day})"
        )
    overlap_frame = probe_mod.build_overlap_frame(baseline_probe_frame, etf_df, btc_df)
    if "date" in overlap_frame.columns:
        overlap_frame = overlap_frame.drop(columns=["date"])
    if overlap_frame.empty:
        raise ValueError("No overlap between the Production Core baseline and ETF-flow inputs.")
    full_history_frame = probe_mod.build_full_history_frame(
        baseline_probe_frame,
        etf_df,
        btc_df,
    )
    if "date" in full_history_frame.columns:
        full_history_frame = full_history_frame.drop(columns=["date"])
    if full_history_frame.empty:
        raise ValueError("No full-history baseline date universe is available for ETF-flow inputs.")
    etf_evidence_feature_mask = _to_bool_series(full_history_frame["etf_flow_feature_available"])
    if not bool(etf_evidence_feature_mask.any()):
        raise ValueError("ETF-flow full-history rebuild has no causal feature rows.")
    etf_evidence_window_start = pd.Timestamp(
        full_history_frame.index[etf_evidence_feature_mask].min()
    ).strftime("%Y-%m-%d")

    state_frame, cooldown_events = cooldown_mod.build_cooldown_state_machine(
        full_history_frame,
        COOLDOWN_DAYS,
    )
    baseline_export, probe_export, enriched = probe_mod.build_export_metrics(
        state_frame,
        cost_config,
    )
    baseline_export, probe_export, enriched = dev_only_rebuild.enforce_baseline_full_risk_pass_through(
        baseline_export,
        probe_export,
        enriched,
    )
    baseline_export_standard = _standardize_export_frame(
        baseline_export,
        prefix="baseline",
    )
    probe_export_standard = _standardize_export_frame(probe_export, prefix="probe")
    candidate_source_frame = enriched.reset_index().rename(columns={"index": "date"}).copy()
    candidate_source_frame["date"] = pd.to_datetime(
        candidate_source_frame["date"],
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    candidate_source_frame = candidate_source_frame.loc[
        :,
        dev_only_rebuild.front_loaded_columns(candidate_source_frame),
    ]

    variant_context = {
        "variant_id": "cooldown_15_days",
        "model_id": CANDIDATE_ID,
        "model_label": "ETF-flow impulse EARLY_RISK cooldown_15 staged candidate",
        "cooldown_days": COOLDOWN_DAYS,
    }
    decorated_cooldown_events = cooldown_mod.decorate_cooldown_events(
        cooldown_events,
        variant_context,
    )
    activation_windows = probe_mod.build_activation_windows(enriched)
    blocker_rows_list = cooldown_mod.build_blocker_rows(enriched, variant_context)
    blocker_rows = {row["period"]: row for row in blocker_rows_list}
    window_counts = dev_only_rebuild.build_window_counts(activation_windows)
    candidate_overlap_closed_day = pd.Timestamp(enriched.index.max()).strftime("%Y-%m-%d")
    evidence_start_stamp = pd.Timestamp(etf_evidence_window_start)
    evidence_enriched = enriched.loc[enriched.index >= evidence_start_stamp].copy()
    evidence_baseline_export_standard = baseline_export_standard.loc[
        baseline_export_standard.index >= evidence_start_stamp
    ].copy()
    evidence_probe_export_standard = probe_export_standard.loc[
        probe_export_standard.index >= evidence_start_stamp
    ].copy()

    baseline_snapshot = (
        authorized_compare_reference["snapshot"]
        if authorized_compare_reference is not None
        else None
    )
    baseline_diagnostics = (
        authorized_compare_reference["diagnostics"]
        if authorized_compare_reference is not None
        else None
    )
    baseline_timeseries = (
        authorized_compare_reference["timeseries"]
        if authorized_compare_reference is not None
        else durable_baseline_timeseries
    )

    return {
        "repo_root": repo_root,
        "source_paths": source_paths,
        "baseline_snapshot": baseline_snapshot,
        "baseline_diagnostics": baseline_diagnostics,
        "baseline_timeseries": baseline_timeseries,
        "project_truth": _read_json_required(source_paths["project_truth"]),
        "export_contract": _read_json_required(source_paths["export_contract"]),
        "baseline_probe_frame": baseline_probe_frame,
        "cost_config": cost_config,
        "cost_config_meta": cost_config_meta,
        "input_refs": input_refs,
        "probe_mod": probe_mod,
        "cooldown_mod": cooldown_mod,
        "etf_df": etf_df,
        "btc_df": btc_df,
        "overlap_frame": overlap_frame,
        "full_history_frame": full_history_frame,
        "state_frame": state_frame,
        "cooldown_events": cooldown_events,
        "decorated_cooldown_events": decorated_cooldown_events,
        "activation_windows": activation_windows,
        "baseline_export": baseline_export,
        "probe_export": probe_export,
        "baseline_export_standard": baseline_export_standard,
        "probe_export_standard": probe_export_standard,
        "enriched": enriched,
        "evidence_enriched": evidence_enriched,
        "evidence_baseline_export_standard": evidence_baseline_export_standard,
        "evidence_probe_export_standard": evidence_probe_export_standard,
        "candidate_source_frame": candidate_source_frame,
        "blocker_rows_list": blocker_rows_list,
        "blocker_rows": blocker_rows,
        "window_counts": window_counts,
        "hard_invalidation_meta": hard_invalidation_meta,
        "candidate_overlap_closed_day": candidate_overlap_closed_day,
        "etf_evidence_window_start": etf_evidence_window_start,
        "baseline_closed_day": baseline_closed_day,
        "current_closed_day": current_closed_day,
        "paper_last_day": durable_baseline_paper_last_day,
        "trend_status_row": trend_status_row,
        "trend_status_day": trend_status_day,
        "trend_history_last_day": trend_history_last_day,
        "freshness_closed_day": freshness_closed_day,
        "benchmark_last_day": benchmark_last_day,
        "durable_baseline_timeseries": durable_baseline_timeseries,
        "durable_baseline_source_inputs": durable_baseline_source_inputs,
        "authorized_compare_reference": authorized_compare_reference,
        "authorized_compare_closed_day": (
            None
            if authorized_compare_reference is None
            else authorized_compare_reference["closed_day"]
        ),
        "authorized_compare_available": authorized_compare_reference is not None,
    }


def _consecutive_tail_length(series: pd.Series) -> int:
    if series.empty:
        return 0
    last_value = series.iloc[-1]
    streak = 0
    for value in reversed(series.tolist()):
        if value != last_value:
            break
        streak += 1
    return streak


def _days_since_last_true(mask: pd.Series, dates: pd.Series) -> int | None:
    hits = dates.loc[mask.fillna(False)]
    if hits.empty:
        return None
    return int((pd.Timestamp(dates.iloc[-1]) - pd.Timestamp(hits.iloc[-1])).days)


def _desired_candidate_asset(raw: pd.DataFrame) -> pd.Series:
    baseline_candidate = raw["candidate_asset"].map(_normalize_asset_code)
    etf_signal_mask = (
        _to_bool_series(raw["permission_on"])
        | _to_bool_series(raw["cooldown_blocked_entry"])
        | _to_bool_series(raw["early_risk_active"])
    )
    return pd.Series(
        np.where(etf_signal_mask, EARLY_RISK_ASSET, baseline_candidate),
        index=raw.index,
        dtype="object",
    )


def _desired_candidate_exposure(raw: pd.DataFrame, candidate_asset: pd.Series) -> pd.Series:
    baseline_exposure = _to_float_series(raw["model_candidate_exposure"])
    desired = baseline_exposure.copy()
    early_risk_mask = (
        _to_bool_series(raw["permission_on"])
        | _to_bool_series(raw["cooldown_blocked_entry"])
        | _to_bool_series(raw["early_risk_active"])
    ) & _to_bool_series(raw["baseline_cash"])
    desired.loc[early_risk_mask] = EARLY_RISK_EXPOSURE
    desired.loc[candidate_asset.isin(CASH_EQUIVALENT_ASSETS)] = 0.0
    return desired


def _candidate_reason_code(raw_row: pd.Series) -> str:
    if bool(raw_row["early_risk_active"]):
        return "early_risk_etf_flow_impulse"
    if bool(raw_row["cooldown_blocked_entry"]):
        return "early_risk_cooldown_block"
    if bool(raw_row["baseline_full_risk"]):
        return "baseline_full_risk_pass_through"
    if bool(raw_row["permission_inputs_true"]) and not bool(raw_row["permission_on"]):
        return "early_risk_permission_vetoed"
    return str(raw_row["reason_code"])


def build_candidate_reason_text(row: pd.Series) -> str:
    actual_asset = _normalize_asset_code(row["actual_held_asset"])
    candidate_asset = _normalize_asset_code(row["candidate_asset"])
    exposure = float(row["effective_market_exposure"])
    flow_3d_sum = float(row["flow_3d_sum_usd"])
    if bool(row["early_risk_active"]):
        return (
            f"The staged candidate takes {actual_asset} at {exposure:.2f}x because the ETF-flow EARLY_RISK "
            f"permission is active ({flow_3d_sum:.0f} USD over 3 sessions) and the 15-day cooldown is clear."
        )
    if bool(row["cooldown_blocked_entry"]):
        return (
            "ETF-flow EARLY_RISK permission is active, but the staged candidate stays in CASH because the "
            "15-day cooldown still blocks a new entry."
        )
    if bool(row["baseline_full_risk"]):
        return (
            f"The staged candidate passes through the baseline FULL_RISK row unchanged, so authorized exposure "
            f"remains {actual_asset} at {exposure:.2f}x."
        )
    if bool(row["permission_inputs_true"]) and not bool(row["permission_on"]):
        return (
            f"{candidate_asset} is the staged candidate, but the ETF-flow entry veto remains active, so the "
            "candidate stays in CASH."
        )
    if actual_asset in CASH_EQUIVALENT_ASSETS:
        return (
            "The staged candidate remains in CASH because neither the baseline FULL_RISK state nor the ETF-flow "
            "EARLY_RISK entry conditions authorize market exposure."
        )
    return f"The staged candidate holds {actual_asset} with authorized exposure at {exposure:.2f}x."


def _resolve_compare_window_start_date(
    period_name: str,
    start_date: str | None,
    *,
    etf_evidence_window_start: str,
) -> str | None:
    if period_name == "full_etf_overlap" and start_date is None:
        return etf_evidence_window_start
    return start_date


def _build_compare_window_payloads(*, etf_evidence_window_start: str) -> list[dict[str, Any]]:
    return [
        {
            "name": period_name,
            "start_date": _resolve_compare_window_start_date(
                period_name,
                start_date,
                etf_evidence_window_start=etf_evidence_window_start,
            ),
        }
        for period_name, start_date in COMPARE_WINDOWS
    ]


def _period_metrics(
    *,
    export_df: pd.DataFrame,
    state_series: pd.Series,
    early_risk_series: pd.Series | None,
    cooldown_blocked_entry_series: pd.Series | None,
) -> dict[str, Any]:
    if export_df.empty:
        return {
            "period_start": None,
            "period_end": None,
            "row_count": 0,
            "gross_total_return_pct": 0.0,
            "net_total_return_pct": 0.0,
            "gross_cagr_pct": 0.0,
            "net_cagr_pct": 0.0,
            "gross_max_drawdown_pct": 0.0,
            "net_max_drawdown_pct": 0.0,
            "switch_count": 0,
            "trade_count": 0,
            "turnover_total": 0.0,
            "exposure_days": 0,
            "cash_days_pct": 0.0,
            "trading_fees_total_pct": 0.0,
            "funding_total_pct": 0.0,
            "borrow_cost_total_pct": 0.0,
            "slippage_cost_total_pct": 0.0,
            "total_cost_pct": 0.0,
            "early_risk_days": 0,
            "cooldown_blocked_entry_days": 0,
            "gross_and_net_status": "gross_and_net_reported",
            "net_costs_included": True,
        }

    gross_return = pd.to_numeric(export_df["gross_return"], errors="coerce").fillna(0.0)
    net_return = pd.to_numeric(export_df["net_return"], errors="coerce").fillna(0.0)
    fees = pd.to_numeric(export_df["trading_fees_daily"], errors="coerce").fillna(0.0)
    funding = pd.to_numeric(export_df["funding_daily"], errors="coerce").fillna(0.0)
    borrow = pd.to_numeric(export_df["daily_borrow_cost"], errors="coerce").fillna(0.0)
    slippage = pd.to_numeric(export_df["tradable_slippage_cost"], errors="coerce").fillna(0.0)
    held_asset = export_df["held_asset"].map(_normalize_asset_code)

    return {
        "period_start": pd.Timestamp(export_df.index.min()).strftime("%Y-%m-%d"),
        "period_end": pd.Timestamp(export_df.index.max()).strftime("%Y-%m-%d"),
        "row_count": int(len(export_df)),
        "gross_total_return_pct": round(_compute_total_return_pct(gross_return), 6),
        "net_total_return_pct": round(_compute_total_return_pct(net_return), 6),
        "gross_cagr_pct": round(_compute_cagr_pct(gross_return, export_df.index), 6),
        "net_cagr_pct": round(_compute_cagr_pct(net_return, export_df.index), 6),
        "gross_max_drawdown_pct": round(_compute_max_drawdown_pct(gross_return), 6),
        "net_max_drawdown_pct": round(_compute_max_drawdown_pct(net_return), 6),
        "switch_count": int(dev_only_rebuild.count_switches(state_series)),
        "trade_count": int(pd.to_numeric(export_df["asset_transition_day"], errors="coerce").fillna(0.0).astype(bool).sum()),
        "turnover_total": round(float(pd.to_numeric(export_df["trading_turnover_notional"], errors="coerce").fillna(0.0).sum()), 6),
        "exposure_days": int((~held_asset.isin(CASH_EQUIVALENT_ASSETS)).sum()),
        "cash_days_pct": round(float(held_asset.isin(CASH_EQUIVALENT_ASSETS).mean() * 100.0), 6),
        "trading_fees_total_pct": round(float(fees.sum() * 100.0), 6),
        "funding_total_pct": round(float(funding.sum() * 100.0), 6),
        "borrow_cost_total_pct": round(float(borrow.sum() * 100.0), 6),
        "slippage_cost_total_pct": round(float(slippage.sum() * 100.0), 6),
        "total_cost_pct": round(float((fees + funding + borrow + slippage).sum() * 100.0), 6),
        "early_risk_days": int(early_risk_series.fillna(False).astype(bool).sum()) if early_risk_series is not None else 0,
        "cooldown_blocked_entry_days": int(cooldown_blocked_entry_series.fillna(False).astype(bool).sum())
        if cooldown_blocked_entry_series is not None
        else 0,
        "gross_and_net_status": "gross_and_net_reported",
        "net_costs_included": True,
    }


def _delta_metrics(candidate_metrics: dict[str, Any], baseline_metrics: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for field in (
        "gross_total_return_pct",
        "net_total_return_pct",
        "gross_cagr_pct",
        "net_cagr_pct",
        "gross_max_drawdown_pct",
        "net_max_drawdown_pct",
        "switch_count",
        "trade_count",
        "turnover_total",
        "exposure_days",
        "cash_days_pct",
        "trading_fees_total_pct",
        "funding_total_pct",
        "borrow_cost_total_pct",
        "slippage_cost_total_pct",
        "total_cost_pct",
        "early_risk_days",
        "cooldown_blocked_entry_days",
    ):
        delta[field] = round(float(candidate_metrics[field]) - float(baseline_metrics[field]), 6)
    return delta


def _standardize_export_frame(export_df: pd.DataFrame, *, prefix: str) -> pd.DataFrame:
    rename_map = {
        f"{prefix}_gross_return": "gross_return",
        f"{prefix}_held_asset": "held_asset",
        f"{prefix}_effective_leverage": "effective_leverage",
        f"{prefix}_asset_transition_day": "asset_transition_day",
        f"{prefix}_trading_turnover_notional": "trading_turnover_notional",
        f"{prefix}_daily_borrow_cost": "daily_borrow_cost",
        f"{prefix}_tradable_slippage_cost": "tradable_slippage_cost",
        f"{prefix}_trading_fees_daily": "trading_fees_daily",
        f"{prefix}_funding_daily": "funding_daily",
        f"{prefix}_net_return": "net_return",
        f"{prefix}_equity_curve_gross": "equity_curve_gross",
        f"{prefix}_equity_curve_net": "equity_curve_net",
        f"{prefix}_fee_side_mode": "fee_side_mode",
        f"{prefix}_taker_fee_bps": "taker_fee_bps",
        f"{prefix}_maker_fee_bps": "maker_fee_bps",
        f"{prefix}_staking_discount_pct": "staking_discount_pct",
        f"{prefix}_referral_discount_pct": "referral_discount_pct",
        f"{prefix}_effective_trading_fee_bps": "effective_trading_fee_bps",
        f"{prefix}_annual_borrow_cost_pct": "annual_borrow_cost_pct",
        f"{prefix}_tradable_transition_slippage_bps": "tradable_transition_slippage_bps",
    }
    standardized = export_df.rename(columns=rename_map).copy()
    standardized.index = export_df.index
    return standardized


@dataclass(frozen=True)
class Phase68gEtfFlowImpulseEarlyRiskCooldown15Adapter:
    candidate_id: str = CANDIDATE_ID
    base_strategy_version: str = BASE_STRATEGY_VERSION
    adapter_name: str = ADAPTER_NAME

    def resolve_source_paths(self, *, root: Path | None = None) -> dict[str, Path]:
        repo_root = (root or ROOT).resolve()
        return {
            "baseline_snapshot": repo_root / "outputs" / "production" / "current_strategy_snapshot.json",
            "baseline_timeseries": repo_root / "outputs" / "production" / "current_strategy_timeseries.csv",
            "baseline_diagnostics": repo_root / "outputs" / "production" / "current_strategy_diagnostics.json",
            "durable_baseline_summary": repo_root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase68g_btc_persistence_10d_early_risk_075_authoritative_net_compare_export.csv",
            "durable_baseline_paper": repo_root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase68g_btc_persistence_10d_early_risk_075_paper.csv",
            "durable_baseline_trend_status": repo_root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase66g_live_status.csv",
            "durable_baseline_trend_history": repo_root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase66g_trend_barometer_history.csv",
            "durable_baseline_freshness_report": repo_root
            / "outputs"
            / "execution"
            / "freshness"
            / "app_freshness_report.json",
            "etf_panel": repo_root
            / "outputs"
            / "research_os"
            / "dev_only"
            / "non_authoritative_btc_etf_flow_daily_panel"
            / "btc_etf_flow_daily_panel.csv",
            "btc_ohlcv": repo_root / "data" / "ohlcv" / "BTCUSDT_1d.csv",
            "dev_only_script": repo_root / "scripts" / "dev_only_phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate.py",
            "project_truth": repo_root / "source_of_truth" / "project_truth.json",
            "export_contract": repo_root / "source_of_truth" / "export_contract.json",
            "probe_helper_source": repo_root
            / "scripts"
            / "dev_only_phase68g_etf_flow_impulse_probe.py",
            "cooldown_helper_source": repo_root
            / "scripts"
            / "dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity.py",
        }

    def load_inputs(self, *, root: Path | None = None) -> dict[str, Any]:
        repo_root = (root or ROOT).resolve()
        source_paths = self.resolve_source_paths(root=repo_root)
        return _load_shared_inputs(
            root=repo_root,
            source_paths=source_paths,
            require_authorized_compare_reference=True,
        )

    def build_candidate_timeseries(self, inputs: dict[str, Any]) -> pd.DataFrame:
        raw = inputs["enriched"].reset_index().rename(columns={"index": "date"}).copy()
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        raw = raw.dropna(subset=["date"]).reset_index(drop=True)
        baseline_reference = inputs["baseline_timeseries"].copy()
        baseline_reference["date"] = pd.to_datetime(
            baseline_reference["date"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")
        baseline_reference = baseline_reference.dropna(subset=["date"]).drop_duplicates(
            subset=["date"],
            keep="last",
        )
        baseline_reference = baseline_reference.set_index("date").reindex(raw["date"]).reset_index(drop=True)

        candidate_asset = _desired_candidate_asset(raw)
        actual_asset = raw["probe_held_asset"].map(_normalize_asset_code)
        actual_exposure = _to_float_series(raw["probe_effective_leverage"])
        model_candidate_exposure = _desired_candidate_exposure(raw, candidate_asset)

        frame = pd.DataFrame()
        frame["date"] = raw["date"]
        frame["candidate_id"] = self.candidate_id
        frame["base_strategy_version"] = self.base_strategy_version
        frame["strategy_id"] = PRODUCTION_STRATEGY_ID
        frame["strategy_version"] = self.candidate_id
        frame["candidate_asset"] = candidate_asset
        frame["selected_asset"] = candidate_asset
        frame["model_candidate_exposure"] = model_candidate_exposure.round(6)
        frame["trend_permission_active"] = actual_exposure > SUMMARY_TOLERANCE
        frame["actual_held_asset"] = actual_asset
        frame["authorized_tradable_asset"] = actual_asset
        frame["held_asset"] = actual_asset
        frame["current_asset"] = actual_asset
        frame["effective_market_exposure"] = actual_exposure.round(6)
        frame["current_exposure"] = actual_exposure.round(6)
        frame["exposure"] = actual_exposure.round(6)
        frame["regime"] = actual_asset.map(_classify_regime)
        frame["market_state"] = np.where(actual_exposure > SUMMARY_TOLERANCE, "IN_MARKET", "OUT_OF_MARKET")
        frame["execution_state"] = frame["market_state"]
        frame["execution_target_asset"] = actual_asset
        frame["execution_target_exposure"] = actual_exposure.round(6)
        frame["trend_state"] = raw["trend_state"].fillna("").astype(str)
        frame["trend_score"] = _to_float_series(raw["trend_score"]).round(6)
        frame["buy_threshold"] = _to_float_series(raw["buy_threshold"]).round(6)
        frame["reason_code"] = raw.apply(_candidate_reason_code, axis=1)

        frame["us_trading_session_date"] = (
            pd.to_datetime(raw["us_trading_session_date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
        )
        frame["causal_available_for_btc_utc_day"] = (
            pd.to_datetime(raw["causal_available_for_btc_utc_day"], errors="coerce")
            .dt.strftime("%Y-%m-%d")
            .fillna("")
        )
        frame["etf_flow_feature_available"] = _to_bool_series(raw["etf_flow_feature_available"])
        frame["etf_flow_evidence_window"] = _to_bool_series(raw["etf_flow_evidence_window"])
        frame["etf_flow_causal_date_available"] = frame["causal_available_for_btc_utc_day"]
        frame["baseline_cash"] = _to_bool_series(raw["baseline_cash"])
        frame["baseline_full_risk"] = _to_bool_series(raw["baseline_full_risk"])
        frame["permission_inputs_true"] = _to_bool_series(raw["permission_inputs_true"])
        frame["permission_on"] = _to_bool_series(raw["permission_on"])
        frame["permission_on_while_baseline_full_risk"] = _to_bool_series(raw["permission_on_while_baseline_full_risk"])
        frame["hard_invalidation_on"] = _to_bool_series(raw["hard_invalidation_on"])
        frame["probe_input_ready_flag"] = _to_bool_series(raw["probe_input_ready_flag"])
        frame["flow_2_of_last_3_positive_flag"] = _to_bool_series(raw["flow_2_of_last_3_positive_flag"])
        frame["flow_3d_sum_usd"] = pd.to_numeric(raw["flow_3d_sum_usd"], errors="coerce").round(6)
        frame["flow_3d_sum_pass"] = _to_bool_series(raw["flow_3d_sum_pass"])
        frame["btc_close"] = _to_float_series(raw["btc_close"]).round(6)
        frame["btc_ema10"] = _to_float_series(raw["btc_ema10"]).round(6)
        frame["btc_price_filter_pass"] = _to_bool_series(raw["btc_price_filter_pass"])
        frame["probe_state"] = raw["probe_state"].fillna("").astype(str)
        frame["probe_window_id"] = raw["probe_window_id"].fillna("").astype(str)
        frame["probe_exit_reason"] = raw["probe_exit_reason"].fillna("").astype(str)
        frame["baseline_handoff_day"] = _to_bool_series(raw["baseline_handoff_day"])
        frame["early_risk_active"] = _to_bool_series(raw["early_risk_active"])
        frame["cooldown_active"] = _to_bool_series(raw["cooldown_active"])
        frame["cooldown_blocked_entry"] = _to_bool_series(raw["cooldown_blocked_entry"])
        frame["etf_flow_rule_active"] = frame["early_risk_active"] | frame["cooldown_blocked_entry"]
        frame["cooldown_event_id"] = raw["cooldown_event_id"].fillna("").astype(str)

        frame["model_candidate_return_gross"] = _to_float_series(raw["probe_strategy_return_gross"]).round(12)
        frame["model_candidate_return_net"] = _to_float_series(raw["probe_net_return"]).round(12)
        frame["model_candidate_equity"] = _to_float_series(raw["probe_equity_curve_net"]).round(12)
        frame["authorized_return_gross"] = _to_float_series(raw["probe_gross_return"]).round(12)
        frame["authorized_return_net"] = _to_float_series(raw["probe_net_return"]).round(12)
        frame["authorized_equity"] = _to_float_series(raw["probe_equity_curve_net"]).round(12)
        frame["btc_return"] = _to_float_series(raw["btc_return"]).round(12)
        frame["btc_baseline_equity"] = _build_equity_curve(frame["btc_return"]).round(12)
        frame["btc_baseline_index"] = (frame["btc_baseline_equity"] * 100.0).round(12)
        frame["return_gross"] = frame["authorized_return_gross"]
        frame["return_net"] = frame["authorized_return_net"]
        frame["equity"] = frame["authorized_equity"]
        frame["drawdown_pct"] = (((frame["equity"] / frame["equity"].cummax()) - 1.0) * 100.0).round(6)
        frame["fees_daily"] = _to_float_series(raw["probe_trading_fees_daily"]).round(12)
        frame["fees_cumulative"] = frame["fees_daily"].cumsum().round(12)
        frame["funding_daily"] = _to_float_series(raw["probe_funding_daily"]).round(12)
        frame["funding_cumulative"] = frame["funding_daily"].cumsum().round(12)
        frame["borrow_cost_daily"] = _to_float_series(raw["probe_daily_borrow_cost"]).round(12)
        frame["borrow_cost_cumulative"] = frame["borrow_cost_daily"].cumsum().round(12)
        frame["slippage_cost_daily"] = _to_float_series(raw["probe_tradable_slippage_cost"]).round(12)
        frame["slippage_cumulative"] = frame["slippage_cost_daily"].cumsum().round(12)
        frame["turnover"] = _to_float_series(raw["probe_trading_turnover_notional"]).round(12)
        frame["cash_day"] = frame["effective_market_exposure"] <= SUMMARY_TOLERANCE
        frame["btc_day"] = (frame["actual_held_asset"] == "BTC") & (frame["effective_market_exposure"] > SUMMARY_TOLERANCE)
        frame["in_market"] = frame["effective_market_exposure"] > SUMMARY_TOLERANCE
        frame["is_rebalance_day"] = _to_bool_series(raw["probe_asset_transition_day"])
        frame["asset_transition_day"] = frame["is_rebalance_day"]
        frame["trend_block_day"] = _to_bool_series(raw["trend_block_day"])
        frame["stress_block_day"] = _to_bool_series(raw["stress_block_day"])
        frame["trend_gate_pass"] = _to_bool_series(raw["trend_gate_pass"])
        frame["leverage_active"] = frame["effective_market_exposure"] > (1.0 + SUMMARY_TOLERANCE)
        frame["leverage_state_reason"] = np.where(
            frame["early_risk_active"],
            "early_risk",
            np.where(
                frame["cooldown_blocked_entry"],
                "cooldown_block",
                np.where(frame["baseline_full_risk"], "baseline_pass_through", "cash"),
            ),
        )
        frame["trend_activation_threshold"] = _to_float_series(raw["trend_activation_threshold"]).round(6)
        frame["rolling_return_7d"] = _rolling_compound_return(frame["return_net"], 7).round(12)
        frame["rolling_return_30d"] = _rolling_compound_return(frame["return_net"], 30).round(12)
        frame["rolling_return_90d"] = _rolling_compound_return(frame["return_net"], 90).round(12)
        frame["rolling_vol_30d"] = (
            frame["return_net"].rolling(window=30, min_periods=30).std(ddof=0) * np.sqrt(365.25)
        ).round(12)
        frame["rolling_sharpe_90d"] = _rolling_sharpe(frame["return_net"], 90).round(12)
        frame["source_validated"] = True

        frame["dev_only_source_lineage"] = True
        frame["non_authoritative_research_input"] = True
        frame["official_truth"] = False
        frame["live_truth"] = False
        frame["app_truth"] = False
        frame["execution_truth"] = False

        frame["baseline_strategy_id"] = baseline_reference["strategy_id"].fillna("").astype(str)
        frame["baseline_strategy_version"] = baseline_reference["strategy_version"].fillna("").astype(str)
        frame["baseline_candidate_asset"] = baseline_reference["candidate_asset"].map(_normalize_asset_code)
        frame["baseline_selected_asset"] = baseline_reference["selected_asset"].map(_normalize_asset_code)
        frame["baseline_model_candidate_exposure"] = _to_float_series(
            baseline_reference["model_candidate_exposure"]
        ).round(6)
        frame["baseline_trend_permission_active"] = _to_bool_series(
            baseline_reference["trend_permission_active"]
        )
        frame["baseline_actual_held_asset"] = baseline_reference["actual_held_asset"].map(
            _normalize_asset_code
        )
        frame["baseline_authorized_tradable_asset"] = baseline_reference[
            "authorized_tradable_asset"
        ].map(_normalize_asset_code)
        frame["baseline_current_asset"] = baseline_reference["current_asset"].map(_normalize_asset_code)
        frame["baseline_effective_market_exposure"] = _to_float_series(
            baseline_reference["effective_market_exposure"]
        ).round(6)
        frame["baseline_execution_target_asset"] = baseline_reference["execution_target_asset"].map(
            _normalize_asset_code
        )
        frame["baseline_execution_target_exposure"] = _to_float_series(
            baseline_reference["execution_target_exposure"]
        ).round(6)
        frame["baseline_regime"] = baseline_reference["regime"].fillna("").astype(str)
        frame["baseline_market_state"] = baseline_reference["market_state"].fillna("").astype(str)
        frame["baseline_execution_state"] = baseline_reference["execution_state"].fillna("").astype(str)
        frame["baseline_reason_code"] = baseline_reference["reason_code"].fillna("").astype(str)
        frame["baseline_return_gross"] = _to_float_series(
            baseline_reference["authorized_return_gross"]
        ).round(12)
        frame["baseline_return_net"] = _to_float_series(
            baseline_reference["authorized_return_net"]
        ).round(12)
        frame["baseline_equity"] = _to_float_series(baseline_reference["authorized_equity"]).round(12)
        frame["baseline_turnover"] = _to_float_series(baseline_reference["turnover"]).round(12)
        frame["baseline_fees_daily"] = _to_float_series(baseline_reference["fees_daily"]).round(12)
        frame["baseline_funding_daily"] = _to_float_series(baseline_reference["funding_daily"]).round(12)
        frame["baseline_borrow_cost_daily"] = _to_float_series(
            baseline_reference["borrow_cost_daily"]
        ).round(12)
        frame["baseline_slippage_daily"] = _to_float_series(
            baseline_reference["slippage_cost_daily"]
        ).round(12)
        frame["baseline_cash_day"] = frame["baseline_effective_market_exposure"] <= SUMMARY_TOLERANCE
        frame["baseline_in_market"] = frame["baseline_effective_market_exposure"] > SUMMARY_TOLERANCE
        frame["baseline_btc_day"] = (
            (frame["baseline_actual_held_asset"] == "BTC") & frame["baseline_in_market"]
        )
        frame["baseline_is_rebalance_day"] = _to_bool_series(raw["baseline_asset_transition_day"])
        frame["baseline_asset_transition_day"] = frame["baseline_is_rebalance_day"]

        pre_evidence_mask = ~frame["etf_flow_evidence_window"]
        if bool(pre_evidence_mask.any()):
            frame.loc[pre_evidence_mask, "model_candidate_exposure"] = frame.loc[
                pre_evidence_mask,
                "baseline_model_candidate_exposure",
            ]
            frame.loc[pre_evidence_mask, "trend_permission_active"] = frame.loc[
                pre_evidence_mask,
                "baseline_trend_permission_active",
            ]
            frame.loc[pre_evidence_mask, "actual_held_asset"] = frame.loc[
                pre_evidence_mask,
                "baseline_actual_held_asset",
            ]
            frame.loc[pre_evidence_mask, "authorized_tradable_asset"] = frame.loc[
                pre_evidence_mask,
                "baseline_authorized_tradable_asset",
            ]
            frame.loc[pre_evidence_mask, "held_asset"] = frame.loc[
                pre_evidence_mask,
                "baseline_actual_held_asset",
            ]
            frame.loc[pre_evidence_mask, "current_asset"] = frame.loc[
                pre_evidence_mask,
                "baseline_current_asset",
            ]
            frame.loc[pre_evidence_mask, "effective_market_exposure"] = frame.loc[
                pre_evidence_mask,
                "baseline_effective_market_exposure",
            ]
            frame.loc[pre_evidence_mask, "current_exposure"] = frame.loc[
                pre_evidence_mask,
                "baseline_effective_market_exposure",
            ]
            frame.loc[pre_evidence_mask, "exposure"] = frame.loc[
                pre_evidence_mask,
                "baseline_effective_market_exposure",
            ]
            frame.loc[pre_evidence_mask, "regime"] = frame.loc[
                pre_evidence_mask,
                "baseline_regime",
            ]
            frame.loc[pre_evidence_mask, "market_state"] = frame.loc[
                pre_evidence_mask,
                "baseline_market_state",
            ]
            frame.loc[pre_evidence_mask, "execution_state"] = frame.loc[
                pre_evidence_mask,
                "baseline_execution_state",
            ]
            frame.loc[pre_evidence_mask, "execution_target_asset"] = frame.loc[
                pre_evidence_mask,
                "baseline_execution_target_asset",
            ]
            frame.loc[pre_evidence_mask, "execution_target_exposure"] = frame.loc[
                pre_evidence_mask,
                "baseline_execution_target_exposure",
            ]
            frame.loc[pre_evidence_mask, "reason_code"] = frame.loc[
                pre_evidence_mask,
                "baseline_reason_code",
            ]
            frame.loc[pre_evidence_mask, "model_candidate_return_gross"] = frame.loc[
                pre_evidence_mask,
                "baseline_return_gross",
            ]
            frame.loc[pre_evidence_mask, "model_candidate_return_net"] = frame.loc[
                pre_evidence_mask,
                "baseline_return_net",
            ]
            frame.loc[pre_evidence_mask, "authorized_return_gross"] = frame.loc[
                pre_evidence_mask,
                "baseline_return_gross",
            ]
            frame.loc[pre_evidence_mask, "authorized_return_net"] = frame.loc[
                pre_evidence_mask,
                "baseline_return_net",
            ]
            frame.loc[pre_evidence_mask, "fees_daily"] = frame.loc[
                pre_evidence_mask,
                "baseline_fees_daily",
            ]
            frame.loc[pre_evidence_mask, "funding_daily"] = frame.loc[
                pre_evidence_mask,
                "baseline_funding_daily",
            ]
            frame.loc[pre_evidence_mask, "borrow_cost_daily"] = frame.loc[
                pre_evidence_mask,
                "baseline_borrow_cost_daily",
            ]
            frame.loc[pre_evidence_mask, "slippage_cost_daily"] = frame.loc[
                pre_evidence_mask,
                "baseline_slippage_daily",
            ]
            frame.loc[pre_evidence_mask, "turnover"] = frame.loc[
                pre_evidence_mask,
                "baseline_turnover",
            ]
            frame.loc[pre_evidence_mask, "is_rebalance_day"] = frame.loc[
                pre_evidence_mask,
                "baseline_is_rebalance_day",
            ]
            frame.loc[pre_evidence_mask, "asset_transition_day"] = frame.loc[
                pre_evidence_mask,
                "baseline_asset_transition_day",
            ]
            frame.loc[pre_evidence_mask, "early_risk_active"] = False
            frame.loc[pre_evidence_mask, "cooldown_active"] = False
            frame.loc[pre_evidence_mask, "cooldown_blocked_entry"] = False
            frame.loc[pre_evidence_mask, "etf_flow_rule_active"] = False
            frame.loc[pre_evidence_mask, "cooldown_event_id"] = ""
            frame.loc[pre_evidence_mask, "probe_state"] = np.where(
                frame.loc[pre_evidence_mask, "baseline_cash_day"],
                "CASH",
                "FULL_RISK",
            )
            frame.loc[pre_evidence_mask, "probe_window_id"] = ""
            frame.loc[pre_evidence_mask, "probe_exit_reason"] = ""
            frame.loc[pre_evidence_mask, "baseline_handoff_day"] = False

        frame["model_candidate_equity"] = _build_equity_curve(frame["model_candidate_return_net"]).round(12)
        frame["authorized_equity"] = _build_equity_curve(frame["authorized_return_net"]).round(12)
        frame["return_gross"] = frame["authorized_return_gross"]
        frame["return_net"] = frame["authorized_return_net"]
        frame["equity"] = frame["authorized_equity"]
        frame["drawdown_pct"] = (((frame["equity"] / frame["equity"].cummax()) - 1.0) * 100.0).round(6)
        frame["fees_cumulative"] = frame["fees_daily"].cumsum().round(12)
        frame["funding_cumulative"] = frame["funding_daily"].cumsum().round(12)
        frame["borrow_cost_cumulative"] = frame["borrow_cost_daily"].cumsum().round(12)
        frame["slippage_cumulative"] = frame["slippage_cost_daily"].cumsum().round(12)
        frame["cash_day"] = frame["effective_market_exposure"] <= SUMMARY_TOLERANCE
        frame["btc_day"] = (
            (frame["actual_held_asset"] == "BTC") & (frame["effective_market_exposure"] > SUMMARY_TOLERANCE)
        )
        frame["in_market"] = frame["effective_market_exposure"] > SUMMARY_TOLERANCE
        frame["leverage_active"] = frame["effective_market_exposure"] > (1.0 + SUMMARY_TOLERANCE)
        frame["rolling_return_7d"] = _rolling_compound_return(frame["return_net"], 7).round(12)
        frame["rolling_return_30d"] = _rolling_compound_return(frame["return_net"], 30).round(12)
        frame["rolling_return_90d"] = _rolling_compound_return(frame["return_net"], 90).round(12)
        frame["rolling_vol_30d"] = (
            frame["return_net"].rolling(window=30, min_periods=30).std(ddof=0) * np.sqrt(365.25)
        ).round(12)
        frame["rolling_sharpe_90d"] = _rolling_sharpe(frame["return_net"], 90).round(12)

        return frame

    def build_compare_payload(self, inputs: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        enriched = inputs["enriched"]
        baseline_export = inputs["baseline_export_standard"]
        probe_export = inputs["probe_export_standard"]
        windows: dict[str, Any] = {}
        compare_rows: list[dict[str, Any]] = []

        metric_fields = (
            "gross_total_return_pct",
            "net_total_return_pct",
            "gross_cagr_pct",
            "net_cagr_pct",
            "gross_max_drawdown_pct",
            "net_max_drawdown_pct",
            "switch_count",
            "trade_count",
            "turnover_total",
            "exposure_days",
            "cash_days_pct",
            "trading_fees_total_pct",
            "funding_total_pct",
            "borrow_cost_total_pct",
            "slippage_cost_total_pct",
            "total_cost_pct",
            "early_risk_days",
            "cooldown_blocked_entry_days",
        )

        for period_name, start_date in COMPARE_WINDOWS:
            resolved_start_date = _resolve_compare_window_start_date(
                period_name,
                start_date,
                etf_evidence_window_start=inputs["etf_evidence_window_start"],
            )
            if resolved_start_date is None:
                period_enriched = enriched.copy()
                period_baseline_export = baseline_export.copy()
                period_probe_export = probe_export.copy()
            else:
                start_stamp = pd.Timestamp(resolved_start_date)
                period_enriched = enriched.loc[enriched.index >= start_stamp].copy()
                period_baseline_export = baseline_export.loc[baseline_export.index >= start_stamp].copy()
                period_probe_export = probe_export.loc[probe_export.index >= start_stamp].copy()

            baseline_metrics = _period_metrics(
                export_df=period_baseline_export,
                state_series=period_enriched["baseline_state"],
                early_risk_series=None,
                cooldown_blocked_entry_series=None,
            )
            candidate_metrics = _period_metrics(
                export_df=period_probe_export,
                state_series=period_enriched["probe_state"],
                early_risk_series=_to_bool_series(period_enriched["early_risk_active"]),
                cooldown_blocked_entry_series=_to_bool_series(period_enriched["cooldown_blocked_entry"]),
            )
            deltas = _delta_metrics(candidate_metrics, baseline_metrics)

            windows[period_name] = {
                "period_start": baseline_metrics["period_start"],
                "period_end": baseline_metrics["period_end"],
                "row_count": baseline_metrics["row_count"],
                "compare_basis": {
                    "baseline_source_path": "outputs/production/current_strategy_timeseries.csv",
                    "gross_and_net_status": "gross_and_net_reported",
                    "net_costs_included": True,
                },
                "baseline": baseline_metrics,
                "candidate": candidate_metrics,
                "delta_candidate_minus_baseline": deltas,
            }

            for field in metric_fields:
                compare_rows.append(
                    {
                        "period": period_name,
                        "metric": field,
                        "baseline_value": baseline_metrics[field],
                        "candidate_value": candidate_metrics[field],
                        "delta_candidate_minus_baseline": deltas[field],
                        "return_basis_status": "gross_and_net_reported",
                        "net_costs_included": True,
                    }
                )

        compare_payload = {
            "artifact_type": "staged_strategy_candidate_compare",
            "schema_version": COMPARE_SCHEMA_VERSION,
            "generated_at_utc": utc_now_iso(),
            "candidate_id": self.candidate_id,
            "base_strategy_version": self.base_strategy_version,
            "baseline_source_path": "outputs/production/current_strategy_timeseries.csv",
            "candidate_universe_rule": (
                "Candidate timeseries covers the full baseline date universe, while ETF-flow edge/delta windows "
                "start only from the first causal ETF-flow evidence day."
            ),
            "comparison_status": {
                "gross_and_net_status": "gross_and_net_reported",
                "net_costs_included": True,
            },
            "windows": windows,
            "window_counts": inputs["window_counts"],
            "blocker_rows": inputs["blocker_rows"],
        }
        return compare_payload, compare_rows

    def build_source_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        source_paths = inputs["source_paths"]
        baseline_timeseries = inputs["baseline_timeseries"]
        etf_df = inputs["etf_df"]
        btc_df = inputs["btc_df"]
        baseline_snapshot = inputs["baseline_snapshot"]
        baseline_diagnostics = inputs["baseline_diagnostics"]

        return {
            "adapter_name": self.adapter_name,
            "candidate_id": self.candidate_id,
            "base_strategy_version": self.base_strategy_version,
            "candidate_compare_closed_day": inputs["candidate_overlap_closed_day"],
            "baseline_closed_day": inputs["baseline_closed_day"],
            "authorized_compare_baseline_closed_day": inputs["current_closed_day"],
            "authorized_compare_baseline_path": "outputs/production/current_strategy_timeseries.csv",
            "full_history_window": {
                "start_date": _normalize_iso_day_text(
                    baseline_timeseries["date"].iloc[0],
                    context="baseline_timeseries.first_row.date",
                ),
                "end_date": inputs["baseline_closed_day"],
                "row_count": int(len(baseline_timeseries)),
            },
            "etf_flow_evidence_window": {
                "start_date": inputs["etf_evidence_window_start"],
                "end_date": inputs["baseline_closed_day"],
                "feature_row_count": int(_to_bool_series(inputs["enriched"]["etf_flow_feature_available"]).sum()),
            },
            "durable_baseline_route": {
                "strategy_version": self.base_strategy_version,
                "closed_day": inputs["baseline_closed_day"],
                "source": "phase68g_btc_persistence_10d_early_risk_075_adapter",
                "lineage": (
                    "phase68g_etf_flow_impulse_early_risk_cooldown_15"
                    " -> phase68g_btc_persistence_10d_early_risk_075"
                    " -> phase68g_66g_1p25x_candidate"
                ),
                "source_inputs": inputs["durable_baseline_source_inputs"],
            },
            "compare_windows": _build_compare_window_payloads(
                etf_evidence_window_start=inputs["etf_evidence_window_start"]
            ),
            "lineage": {
                "dev_only_source_lineage": True,
                "non_authoritative_research_input": True,
                "official_truth": False,
                "live_truth": False,
                "app_truth": False,
                "execution_truth": False,
            },
            "files": {
                "baseline_snapshot": {
                    **_source_file_metadata(source_paths["baseline_snapshot"]),
                    "closed_day": str(baseline_snapshot.get("closed_day") or "").strip(),
                    "strategy_version": str(baseline_snapshot.get("strategy_version") or "").strip(),
                },
                "baseline_timeseries": _source_file_metadata(
                    source_paths["baseline_timeseries"],
                    last_date=_normalize_iso_day_text(
                        baseline_timeseries["date"].iloc[-1],
                        context="baseline_timeseries.last_row.date",
                    ),
                    row_count=len(baseline_timeseries),
                ),
                "baseline_diagnostics": {
                    **_source_file_metadata(source_paths["baseline_diagnostics"]),
                    "closed_day": str(baseline_diagnostics.get("closed_day") or "").strip(),
                },
                "etf_panel": _source_file_metadata(
                    source_paths["etf_panel"],
                    last_date=_normalize_iso_day_text(
                        pd.Timestamp(etf_df.index[-1]).strftime("%Y-%m-%d"),
                        context="etf_panel.last_row.date",
                    ),
                    row_count=len(etf_df),
                ),
                "btc_ohlcv": _source_file_metadata(
                    source_paths["btc_ohlcv"],
                    last_date=_normalize_iso_day_text(
                        pd.Timestamp(btc_df.index[-1]).strftime("%Y-%m-%d"),
                        context="btc_ohlcv.last_row.date",
                    ),
                    row_count=len(btc_df),
                ),
                "dev_only_script": _source_file_metadata(source_paths["dev_only_script"]),
                "probe_helper_source": _source_file_metadata(source_paths["probe_helper_source"]),
                "cooldown_helper_source": _source_file_metadata(source_paths["cooldown_helper_source"]),
                "project_truth": _source_file_metadata(source_paths["project_truth"]),
                "export_contract": _source_file_metadata(source_paths["export_contract"]),
            },
            "cost_model": {
                **inputs["cost_config_meta"],
                "flow_3d_floor_usd": FLOW_3D_FLOOR_USD,
                "btc_ema_days": BTC_EMA_DAYS,
                "cooldown_days": COOLDOWN_DAYS,
            },
            "hard_invalidation_rule": dict(inputs["hard_invalidation_meta"]),
        }

    def build_snapshot_metrics(self, inputs: dict[str, Any]) -> dict[str, Any]:
        candidate_full = _period_metrics(
            export_df=inputs["probe_export_standard"],
            state_series=inputs["enriched"]["probe_state"],
            early_risk_series=_to_bool_series(inputs["enriched"]["early_risk_active"]),
            cooldown_blocked_entry_series=_to_bool_series(inputs["enriched"]["cooldown_blocked_entry"]),
        )
        since2025_enriched = inputs["enriched"].loc[inputs["enriched"].index >= pd.Timestamp("2025-01-01")].copy()
        since2025_export = inputs["probe_export_standard"].loc[
            inputs["probe_export_standard"].index >= pd.Timestamp("2025-01-01")
        ].copy()
        since2025_metrics = _period_metrics(
            export_df=since2025_export,
            state_series=since2025_enriched["probe_state"],
            early_risk_series=_to_bool_series(since2025_enriched["early_risk_active"]),
            cooldown_blocked_entry_series=_to_bool_series(since2025_enriched["cooldown_blocked_entry"]),
        )
        sharpe = _annualized_sharpe_from_daily_returns(inputs["probe_export_standard"]["net_return"])
        sortino = _annualized_sortino_from_daily_returns(inputs["probe_export_standard"]["net_return"])
        if sharpe is None or sortino is None:
            raise ValueError("Unable to compute staged candidate Sharpe/Sortino from probe export.")
        return {
            "gross_total_return_pct": candidate_full["gross_total_return_pct"],
            "net_total_return_pct": candidate_full["net_total_return_pct"],
            "gross_cagr_pct": candidate_full["gross_cagr_pct"],
            "net_cagr_pct": candidate_full["net_cagr_pct"],
            "gross_max_drawdown_pct": candidate_full["gross_max_drawdown_pct"],
            "net_max_drawdown_pct": candidate_full["net_max_drawdown_pct"],
            "since2025_gross_cagr_pct": since2025_metrics["gross_cagr_pct"],
            "since2025_net_cagr_pct": since2025_metrics["net_cagr_pct"],
            "trading_fees_total_pct": candidate_full["trading_fees_total_pct"],
            "funding_total_pct": candidate_full["funding_total_pct"],
            "borrow_cost_total_pct": candidate_full["borrow_cost_total_pct"],
            "slippage_cost_total_pct": candidate_full["slippage_cost_total_pct"],
            "total_cost_pct": candidate_full["total_cost_pct"],
            "cash_days_pct": candidate_full["cash_days_pct"],
            "exposure_days": candidate_full["exposure_days"],
            "switch_count": candidate_full["switch_count"],
            "trade_count": candidate_full["trade_count"],
            "turnover_total": candidate_full["turnover_total"],
            "early_risk_days": candidate_full["early_risk_days"],
            "cooldown_blocked_entry_days": candidate_full["cooldown_blocked_entry_days"],
            "sharpe": round(float(sharpe), 6),
            "sortino": round(float(sortino), 6),
        }

    def build_decision_context(self, timeseries: pd.DataFrame) -> dict[str, Any]:
        current_row = timeseries.iloc[-1]
        dates = pd.to_datetime(timeseries["date"], errors="coerce")
        current_cash_streak_days = _consecutive_tail_length(timeseries["cash_day"]) if bool(current_row["cash_day"]) else 0
        latest_rebalance_rows = timeseries.loc[timeseries["is_rebalance_day"]]
        latest_rebalance_date = None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["date"])
        return {
            "current_reason_code": str(current_row["reason_code"]),
            "current_reason_text": build_candidate_reason_text(current_row),
            "current_regime_duration_days": int(_consecutive_tail_length(timeseries["regime"])),
            "current_cash_streak_days": int(current_cash_streak_days),
            "days_since_last_trade": _days_since_last_true(timeseries["is_rebalance_day"], dates),
            "days_since_last_early_risk": _days_since_last_true(timeseries["early_risk_active"], dates),
            "latest_rebalance_date": latest_rebalance_date,
            "latest_rebalance_reason": None
            if latest_rebalance_rows.empty
            else str(latest_rebalance_rows.iloc[-1]["reason_code"]),
            "current_drawdown_pct": round(float(current_row["drawdown_pct"]), 6),
        }

    def build_diagnostics_payload(
        self,
        *,
        generated_at_utc: str,
        inputs: dict[str, Any],
        timeseries: pd.DataFrame,
        compare_payload: dict[str, Any],
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        current_row = timeseries.iloc[-1]
        recent_activation_windows = inputs["activation_windows"][-5:]
        recent_rebalance_rows = timeseries.loc[timeseries["is_rebalance_day"]].tail(5)
        metrics = self.build_snapshot_metrics(inputs)
        return {
            "artifact_type": "staged_strategy_candidate_diagnostics",
            "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
            "generated_at_utc": generated_at_utc,
            "candidate_id": self.candidate_id,
            "base_strategy_version": self.base_strategy_version,
            "closed_day": inputs["candidate_overlap_closed_day"],
            "compare_universe": {
                "start_date": str(timeseries["date"].iloc[0]),
                "end_date": str(timeseries["date"].iloc[-1]),
                "row_count": int(len(timeseries)),
                "baseline_closed_day": inputs["baseline_closed_day"],
            },
            "latest_state_explanation": build_candidate_reason_text(current_row),
            "baseline_separation_explanation": (
                "The staged candidate is a hypothetical bundle only. Baseline authorized/live truth remains on "
                f"{EXPECTED_LIVE_TRUTH}, and all baseline series are preserved under explicit baseline_* columns."
            ),
            "current_candidate_trade_state": {
                "candidate_asset": str(current_row["candidate_asset"]),
                "selected_asset": str(current_row["selected_asset"]),
                "actual_held_asset": str(current_row["actual_held_asset"]),
                "effective_market_exposure": round(float(current_row["effective_market_exposure"]), 6),
                "model_candidate_exposure": round(float(current_row["model_candidate_exposure"]), 6),
                "trend_permission_active": bool(current_row["trend_permission_active"]),
                "execution_target_asset": str(current_row["execution_target_asset"]),
                "execution_target_exposure": round(float(current_row["execution_target_exposure"]), 6),
                "reason_code": str(current_row["reason_code"]),
                "reason_text": build_candidate_reason_text(current_row),
                "early_risk_active": bool(current_row["early_risk_active"]),
                "cooldown_active": bool(current_row["cooldown_active"]),
                "cooldown_blocked_entry": bool(current_row["cooldown_blocked_entry"]),
            },
            "current_baseline_trade_state": {
                "candidate_asset": str(current_row["baseline_candidate_asset"]),
                "actual_held_asset": str(current_row["baseline_actual_held_asset"]),
                "effective_market_exposure": round(float(current_row["baseline_effective_market_exposure"]), 6),
                "trend_permission_active": bool(current_row["baseline_trend_permission_active"]),
                "reason_code": str(current_row["baseline_reason_code"]),
            },
            "metrics": metrics,
            "window_counts": inputs["window_counts"],
            "blocker_rows": inputs["blocker_rows"],
            "recent_activation_windows": recent_activation_windows,
            "handoff_row_audit": dev_only_rebuild.build_handoff_row_audit(inputs["candidate_source_frame"]).to_dict(
                orient="records"
            ),
            "recent_rebalance_events": [
                {
                    "date": str(row["date"]),
                    "actual_held_asset": str(row["actual_held_asset"]),
                    "effective_market_exposure": round(float(row["effective_market_exposure"]), 6),
                    "reason_code": str(row["reason_code"]),
                    "reason_text": build_candidate_reason_text(row),
                }
                for _, row in recent_rebalance_rows.iterrows()
            ],
            "lineage": {
                "dev_only_source_lineage": True,
                "non_authoritative_research_input": True,
                "official_truth": False,
                "live_truth": False,
                "app_truth": False,
                "execution_truth": False,
            },
            "compare_summary": compare_payload["windows"],
            "validation": {
                "status": validation["status"],
                "errors": list(validation["errors"]),
                "warnings": list(validation["warnings"]),
            },
        }


@dataclass(frozen=True)
class Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter:
    strategy_id: str = LIVE_PRODUCTION_STRATEGY_ID
    strategy_version: str = LIVE_STRATEGY_VERSION
    adapter_name: str = LIVE_ADAPTER_NAME
    base_strategy_version: str = BASE_STRATEGY_VERSION

    def resolve_source_paths(self, *, root: Path | None = None) -> dict[str, Path]:
        repo_root = (root or ROOT).resolve()
        return Phase68gEtfFlowImpulseEarlyRiskCooldown15Adapter().resolve_source_paths(
            root=repo_root
        )

    def load_inputs(self, *, root: Path | None = None) -> dict[str, Any]:
        repo_root = (root or ROOT).resolve()
        shared = _load_shared_inputs(
            root=repo_root,
            source_paths=self.resolve_source_paths(root=repo_root),
            require_authorized_compare_reference=False,
        )
        if shared["candidate_overlap_closed_day"] != shared["baseline_closed_day"]:
            raise ValueError(
                "ETF-flow overlap day diverged from the durable BTC-persistence closed day "
                f"(etf_flow={shared['candidate_overlap_closed_day']} "
                f"baseline={shared['baseline_closed_day']})"
            )
        shared["closed_day"] = shared["baseline_closed_day"]
        return shared

    def build_timeseries(self, inputs: dict[str, Any]) -> pd.DataFrame:
        from scripts.production.staged_candidate_promotion_support import (
            transform_candidate_timeseries_to_active,
        )

        candidate_timeseries = Phase68gEtfFlowImpulseEarlyRiskCooldown15Adapter().build_candidate_timeseries(inputs)
        active_timeseries = transform_candidate_timeseries_to_active(candidate_timeseries)
        active_timeseries["strategy_id"] = self.strategy_id
        active_timeseries["strategy_version"] = self.strategy_version
        return active_timeseries

    def build_reason_text(self, row: pd.Series) -> str:
        from scripts.production.staged_candidate_promotion_support import (
            build_promoted_reason_text,
        )

        return build_promoted_reason_text(row)

    def build_wait_condition(
        self,
        current_row: pd.Series,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        from scripts.production.staged_candidate_promotion_support import (
            build_promoted_wait_condition,
        )

        del metrics
        return build_promoted_wait_condition(current_row)

    def build_source_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        durable_baseline_source_inputs = dict(inputs["durable_baseline_source_inputs"])
        durable_baseline_files = dict(durable_baseline_source_inputs["files"])
        return {
            "adapter_name": self.adapter_name,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "validated_closed_day": inputs["closed_day"],
            "base_strategy_version": self.base_strategy_version,
            "baseline_closed_day": inputs["baseline_closed_day"],
            "candidate_compare_closed_day": inputs["candidate_overlap_closed_day"],
            "full_history_window": {
                "start_date": _normalize_iso_day_text(
                    inputs["baseline_timeseries"]["date"].iloc[0],
                    context="baseline_timeseries.first_row.date",
                ),
                "end_date": inputs["baseline_closed_day"],
                "row_count": int(len(inputs["baseline_timeseries"])),
            },
            "etf_flow_evidence_window": {
                "start_date": inputs["etf_evidence_window_start"],
                "end_date": inputs["baseline_closed_day"],
                "feature_row_count": int(_to_bool_series(inputs["enriched"]["etf_flow_feature_available"]).sum()),
            },
            "durable_non_circular_route": {
                "softer_fallback_strategy_version": self.base_strategy_version,
                "secondary_baseline_strategy_version": "phase68g_66g_1p25x_candidate",
                "lineage": (
                    "phase68g_etf_flow_impulse_early_risk_cooldown_15"
                    " -> phase68g_btc_persistence_10d_early_risk_075"
                    " -> phase68g_66g_1p25x_candidate"
                ),
                "softer_fallback_source_inputs": durable_baseline_source_inputs,
            },
            "compare_windows": _build_compare_window_payloads(
                etf_evidence_window_start=inputs["etf_evidence_window_start"]
            ),
            "lineage": {
                "dev_only_source_lineage": True,
                "non_authoritative_research_input": True,
                "official_truth": True,
                "live_truth": True,
                "app_truth": True,
                "execution_truth": True,
            },
            "files": {
                **durable_baseline_files,
                "etf_panel": _source_file_metadata(
                    inputs["source_paths"]["etf_panel"],
                    last_date=_normalize_iso_day_text(
                        pd.Timestamp(inputs["etf_df"].index[-1]).strftime("%Y-%m-%d"),
                        context="etf_panel.last_row.date",
                    ),
                    row_count=len(inputs["etf_df"]),
                ),
                "btc_ohlcv": _source_file_metadata(
                    inputs["source_paths"]["btc_ohlcv"],
                    last_date=_normalize_iso_day_text(
                        pd.Timestamp(inputs["btc_df"].index[-1]).strftime("%Y-%m-%d"),
                        context="btc_ohlcv.last_row.date",
                    ),
                    row_count=len(inputs["btc_df"]),
                ),
                "dev_only_script": _source_file_metadata(inputs["source_paths"]["dev_only_script"]),
                "probe_helper_source": _source_file_metadata(inputs["source_paths"]["probe_helper_source"]),
                "cooldown_helper_source": _source_file_metadata(inputs["source_paths"]["cooldown_helper_source"]),
                "project_truth": _source_file_metadata(inputs["source_paths"]["project_truth"]),
                "export_contract": _source_file_metadata(inputs["source_paths"]["export_contract"]),
            },
            "cost_model": {
                **inputs["cost_config_meta"],
                "flow_3d_floor_usd": FLOW_3D_FLOOR_USD,
                "btc_ema_days": BTC_EMA_DAYS,
                "cooldown_days": COOLDOWN_DAYS,
            },
            "hard_invalidation_rule": dict(inputs["hard_invalidation_meta"]),
            "window_counts": dict(inputs["window_counts"]),
            "blocker_rows": dict(inputs["blocker_rows"]),
        }

    def build_snapshot_metrics(
        self,
        inputs: dict[str, Any],
        timeseries: pd.DataFrame,
    ) -> dict[str, Any]:
        from scripts.production.staged_candidate_promotion_support import (
            build_promoted_snapshot_metrics,
        )

        del inputs
        return build_promoted_snapshot_metrics(timeseries)

    def build_decision_context(self, timeseries: pd.DataFrame) -> dict[str, Any]:
        from scripts.production.staged_candidate_promotion_support import (
            build_promoted_decision_context,
        )

        return build_promoted_decision_context(timeseries)

    def build_diagnostics_payload(
        self,
        *,
        generated_at_utc: str,
        inputs: dict[str, Any],
        timeseries: pd.DataFrame,
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        from scripts.production.staged_candidate_promotion_support import (
            build_promoted_reason_text,
        )

        current_row = timeseries.iloc[-1]
        recent_regime_rows = timeseries.loc[
            timeseries["regime"]
            != timeseries["regime"].shift(1, fill_value=timeseries["regime"].iloc[0])
        ].tail(5)
        recent_rebalance_rows = timeseries.loc[timeseries["is_rebalance_day"]].tail(5)
        trailing_30 = timeseries.tail(30)
        trailing_90 = timeseries.tail(90)
        metrics = self.build_snapshot_metrics(inputs, timeseries)
        flatline_days = (
            _consecutive_tail_length(timeseries["cash_day"])
            if bool(current_row["cash_day"])
            else 0
        )
        lifetime_cost_pct = (
            float(timeseries["fees_daily"].sum())
            + float(timeseries["funding_daily"].sum())
            + float(timeseries["borrow_cost_daily"].sum())
            + float(timeseries["slippage_cost_daily"].sum())
        ) * 100.0
        return {
            "artifact_type": "current_strategy_diagnostics",
            "schema_version": 4,
            "generated_at_utc": generated_at_utc,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "closed_day": inputs["closed_day"],
            "latest_state_explanation": build_promoted_reason_text(current_row),
            "current_flatline_explanation": (
                f"Authorized capital should stay flat during the current CASH streak of "
                f"{flatline_days} days because no market exposure is currently authorized."
                if flatline_days > 0
                else None
            ),
            "current_cash_or_risk_reason": build_promoted_reason_text(current_row),
            "recent_regime_changes": [
                {
                    "date": str(row["date"]),
                    "held_asset": str(row["held_asset"]),
                    "regime": str(row["regime"]),
                    "reason_code": str(row["reason_code"]),
                }
                for _, row in recent_regime_rows.iterrows()
            ],
            "recent_rebalance_events": [
                {
                    "date": str(row["date"]),
                    "held_asset": str(row["held_asset"]),
                    "exposure": round(float(row["exposure"]), 6),
                    "reason_code": str(row["reason_code"]),
                    "reason_text": build_promoted_reason_text(row),
                }
                for _, row in recent_rebalance_rows.iterrows()
            ],
            "current_cost_pressure": {
                "current_effective_exposure": round(float(current_row["exposure"]), 6),
                "trailing_30d_fees_pct": round(float(trailing_30["fees_daily"].sum() * 100.0), 6),
                "trailing_30d_funding_pct": round(float(trailing_30["funding_daily"].sum() * 100.0), 6),
                "trailing_30d_borrow_pct": round(float(trailing_30["borrow_cost_daily"].sum() * 100.0), 6),
                "trailing_30d_slippage_pct": round(float(trailing_30["slippage_cost_daily"].sum() * 100.0), 6),
            },
            "current_fee_drag_summary": {
                "lifetime_trading_fees_total_pct": round(float(timeseries["fees_daily"].sum() * 100.0), 6),
                "lifetime_funding_total_pct": round(float(timeseries["funding_daily"].sum() * 100.0), 6),
                "lifetime_borrow_cost_total_pct": round(float(timeseries["borrow_cost_daily"].sum() * 100.0), 6),
                "lifetime_slippage_cost_total_pct": round(float(timeseries["slippage_cost_daily"].sum() * 100.0), 6),
                "lifetime_total_cost_pct": round(lifetime_cost_pct, 6),
                "trailing_90d_turnover": round(float(trailing_90["turnover"].sum()), 6),
            },
            "current_data_health_summary": {
                "status": validation["status"],
                "closed_day": inputs["closed_day"],
                "softer_fallback_closed_day": inputs["baseline_closed_day"],
                "full_history_start_date": _normalize_iso_day_text(
                    timeseries["date"].iloc[0],
                    context="timeseries.first_row.date",
                ),
                "etf_flow_evidence_window_start": inputs["etf_evidence_window_start"],
                "etf_flow_evidence_window_end": inputs["baseline_closed_day"],
                "trend_status_day": inputs["trend_status_day"],
                "trend_history_last_day": inputs["trend_history_last_day"],
                "freshness_closed_day": inputs["freshness_closed_day"],
                "benchmark_last_day": inputs["benchmark_last_day"],
                "warnings": validation["warnings"],
            },
            "strategy_improvement_signals": {
                "etf_flow_activation_windows": {
                    "window_count": int(len(inputs["activation_windows"])),
                    "recent_windows": inputs["activation_windows"][-5:],
                },
                "cooldown_blockers": {
                    "status": "active" if inputs["blocker_rows"] else "clear",
                    "rows": list(inputs["blocker_rows"].values()),
                },
                "cash_drag": {
                    "status": "elevated" if float(metrics["cash_days_pct"]) >= 40.0 else "contained",
                    "cash_days_pct": float(metrics["cash_days_pct"]),
                    "current_cash_streak_days": int(flatline_days),
                },
                "current_research_questions": [
                    "Does the ETF-flow cooldown still improve net performance once BTC persistence is the softer fallback?",
                    "How often does the 15-day cooldown defer otherwise valid early-risk entries?",
                    "Can the same net profile be preserved with lower transition-driven slippage?",
                ],
            },
            "validation": {
                "status": validation["status"],
                "errors": list(validation["errors"]),
                "warnings": list(validation["warnings"]),
            },
        }

    def compare_summary_metrics(
        self,
        *,
        inputs: dict[str, Any],
        timeseries: pd.DataFrame,
    ) -> list[str]:
        del timeseries
        mismatches: list[str] = []
        actual_truth_contract_state = read_truth_contract_state(root=inputs["repo_root"])
        expected_contract_state = {
            "project_truth_app_main_strategy_model": self.strategy_version,
            "project_truth_current_live_truth": self.strategy_version,
            "project_truth_official_fallback": self.base_strategy_version,
            "project_truth_production_core_strategy_version": self.strategy_version,
            "export_contract_main_strategy_model": self.strategy_version,
            "export_contract_live_truth_mode": self.strategy_version,
            "export_contract_fallback_profile_label": self.base_strategy_version,
            "export_contract_production_core_strategy_version": self.strategy_version,
            "baseline_snapshot_strategy_version": self.strategy_version,
        }
        for key, expected_value in expected_contract_state.items():
            actual_value = str(actual_truth_contract_state.get(key) or "").strip()
            if actual_value != expected_value:
                mismatches.append(
                    "truth contract drift detected for "
                    f"{key}: actual={actual_value!r} expected={expected_value!r}"
                )
        return mismatches
