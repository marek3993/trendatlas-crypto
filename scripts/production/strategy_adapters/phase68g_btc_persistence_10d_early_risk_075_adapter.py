from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
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
import scripts.dev_only_production_core_btc_candidate_persistence_early_risk_compare as dev_only_compare
from scripts.production.strategy_adapters.phase68g_66g_1p25x_candidate_adapter import (
    Phase68g66g1p25xCandidateAdapter,
    SOURCE_STRATEGY_VERSION as BASE_STRATEGY_VERSION,
)


PRODUCTION_STRATEGY_ID = "current_strategy"
STAGED_STRATEGY_ID = "staged_strategy_candidate"
CANDIDATE_ID = "phase68g_btc_persistence_10d_early_risk_075"
CANDIDATE_LABEL = "BTC candidate persistence 10d / 0.75 EARLY_RISK"
ADAPTER_NAME = "phase68g_btc_persistence_10d_early_risk_075_adapter"

SNAPSHOT_SCHEMA_VERSION = 1
DIAGNOSTICS_SCHEMA_VERSION = 1
QUALITY_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
COMPARE_SCHEMA_VERSION = 1
SUMMARY_TOLERANCE = 1e-9

ACTIVE_SCHEMA_VERSION = 4
EARLY_RISK_EXPOSURE = 0.75
SELECTED_VARIANT_ID = "btc_candidate_persistence_10d_075"

EXPECTED_LIVE_TRUTH = BASE_STRATEGY_VERSION
EXPECTED_FALLBACK = "phase68i_dynamic_ladder_candidate"

DEV_ONLY_CONTRACT_PATH = (
    ROOT
    / "research_os"
    / "dev_only"
    / "contracts"
    / "dev_only_production_core_btc_candidate_persistence_early_risk_compare.contract.json"
)
DEV_ONLY_SPEC_PATH = (
    ROOT
    / "research_os"
    / "dev_only"
    / "specs"
    / "dev_only_production_core_btc_candidate_persistence_early_risk_compare.spec.json"
)
DEV_ONLY_MANIFEST_SEED_PATH = (
    ROOT
    / "research_os"
    / "dev_only"
    / "manifests"
    / "dev_only_production_core_btc_candidate_persistence_early_risk_compare.manifest.json"
)
DEV_ONLY_OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_production_core_btc_candidate_persistence_early_risk_compare"
)

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

ACTIVE_TIMESERIES_COLUMNS = [
    "date",
    "strategy_id",
    "strategy_version",
    "candidate_asset",
    "selected_asset",
    "model_candidate_exposure",
    "trend_permission_active",
    "actual_held_asset",
    "authorized_tradable_asset",
    "held_asset",
    "current_asset",
    "effective_market_exposure",
    "current_exposure",
    "exposure",
    "regime",
    "market_state",
    "execution_state",
    "execution_target_asset",
    "execution_target_exposure",
    "trend_state",
    "trend_score",
    "buy_threshold",
    "model_candidate_return_gross",
    "model_candidate_return_net",
    "model_candidate_equity",
    "authorized_return_gross",
    "authorized_return_net",
    "authorized_equity",
    "btc_close",
    "btc_return",
    "btc_baseline_equity",
    "btc_baseline_index",
    "return_gross",
    "return_net",
    "equity",
    "drawdown_pct",
    "fees_daily",
    "fees_cumulative",
    "funding_daily",
    "funding_cumulative",
    "borrow_cost_daily",
    "borrow_cost_cumulative",
    "slippage_cost_daily",
    "slippage_cost_cumulative",
    "turnover",
    "cash_day",
    "btc_day",
    "in_market",
    "is_rebalance_day",
    "asset_transition_day",
    "trend_block_day",
    "stress_block_day",
    "trend_gate_pass",
    "leverage_active",
    "leverage_state_reason",
    "trend_activation_threshold",
    "reason_code",
    "rolling_return_7d",
    "rolling_return_30d",
    "rolling_return_90d",
    "rolling_vol_30d",
    "rolling_sharpe_90d",
    "source_validated",
]

STAGED_TIMESERIES_COLUMNS = [
    "date",
    "candidate_id",
    "candidate_label",
    "base_strategy_version",
    "strategy_id",
    "strategy_version",
    "candidate_asset",
    "selected_asset",
    "model_candidate_exposure",
    "trend_permission_active",
    "actual_held_asset",
    "authorized_tradable_asset",
    "held_asset",
    "current_asset",
    "effective_market_exposure",
    "current_exposure",
    "exposure",
    "regime",
    "market_state",
    "execution_state",
    "execution_target_asset",
    "execution_target_exposure",
    "trend_state",
    "trend_score",
    "buy_threshold",
    "model_candidate_return_gross",
    "model_candidate_return_net",
    "model_candidate_equity",
    "authorized_return_gross",
    "authorized_return_net",
    "authorized_equity",
    "btc_close",
    "btc_return",
    "btc_baseline_equity",
    "btc_baseline_index",
    "return_gross",
    "return_net",
    "equity",
    "drawdown_pct",
    "fees_daily",
    "fees_cumulative",
    "funding_daily",
    "funding_cumulative",
    "borrow_cost_daily",
    "borrow_cost_cumulative",
    "slippage_cost_daily",
    "slippage_cost_cumulative",
    "turnover",
    "cash_day",
    "btc_day",
    "in_market",
    "is_rebalance_day",
    "asset_transition_day",
    "trend_block_day",
    "stress_block_day",
    "trend_gate_pass",
    "leverage_active",
    "leverage_state_reason",
    "trend_activation_threshold",
    "reason_code",
    "rolling_return_7d",
    "rolling_return_30d",
    "rolling_return_90d",
    "rolling_vol_30d",
    "rolling_sharpe_90d",
    "source_validated",
    "baseline_cash",
    "baseline_full_risk",
    "btc_candidate_persistence_rows",
    "persistence_entry_filter_ready",
    "early_risk_active",
    "candidate_entry_day",
    "candidate_exit_day",
    "hard_invalidation",
    "override_state",
    "candidate_reason",
    "dev_only_source_lineage",
    "non_authoritative_research_input",
    "official_truth",
    "live_truth",
    "app_truth",
    "execution_truth",
    "baseline_candidate_asset",
    "baseline_selected_asset",
    "baseline_model_candidate_exposure",
    "baseline_trend_permission_active",
    "baseline_actual_held_asset",
    "baseline_authorized_tradable_asset",
    "baseline_current_asset",
    "baseline_effective_market_exposure",
    "baseline_execution_target_asset",
    "baseline_execution_target_exposure",
    "baseline_regime",
    "baseline_market_state",
    "baseline_execution_state",
    "baseline_reason_code",
    "baseline_return_gross",
    "baseline_return_net",
    "baseline_equity",
    "baseline_turnover",
    "baseline_fees_daily",
    "baseline_funding_daily",
    "baseline_borrow_cost_daily",
    "baseline_slippage_daily",
    "baseline_cash_day",
    "baseline_in_market",
    "baseline_btc_day",
    "baseline_is_rebalance_day",
    "baseline_asset_transition_day",
]

COMPARE_METRIC_SPECS = [
    ("net_total_return_pct", "baseline_net_total_return_pct", "candidate_net_total_return_pct", "net_total_return_delta_pct"),
    ("net_cagr_pct", "baseline_net_cagr_pct", "candidate_net_cagr_pct", "net_cagr_delta_pct"),
    ("net_max_drawdown_pct", "baseline_net_max_drawdown_pct", "candidate_net_max_drawdown_pct", "net_max_drawdown_delta_pct"),
    ("switch_count", "baseline_switch_count", "candidate_switch_count", "switch_delta"),
    ("turnover_total", "baseline_turnover_total", "candidate_turnover_total", "turnover_delta"),
    ("exposure_days", "baseline_exposure_days", "candidate_exposure_days", "exposure_days_delta"),
    ("total_cost_pct", "baseline_total_cost_pct", "candidate_total_cost_pct", "cost_delta_pct"),
    ("gross_total_return_pct", "baseline_gross_total_return_pct", "candidate_gross_total_return_pct", "gross_total_return_delta_pct"),
    ("early_risk_days", None, "early_risk_days", "early_risk_days"),
    ("activation_window_count", None, "activation_window_count", "activation_window_count"),
    ("successful_handoff_count", None, "successful_handoff_count", "successful_handoff_count"),
    ("false_start_count", None, "false_start_count", "false_start_count"),
    ("lead_days_total", None, "lead_days_total", "lead_days_total"),
    ("lead_days_max", None, "lead_days_max", "lead_days_max"),
    ("strategy_delta_vs_baseline_pct", None, "strategy_delta_vs_baseline_pct", "strategy_delta_vs_baseline_pct"),
    ("missed_btc_move_captured_pct", None, "missed_btc_move_captured_pct", "missed_btc_move_captured_pct"),
    ("strict_pass_through_ok", None, "strict_pass_through_ok", "strict_pass_through_ok"),
]


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


def _path_for_manifest(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _normalize_iso_day_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        raise ValueError(f"{context} is not an ISO day: {value}")
    return text


def _to_float_series(series: Any) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _to_bool_series(series: Any) -> pd.Series:
    lowered = pd.Series(series).fillna("").astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y"})


def _classify_regime(asset: Any) -> str:
    normalized = dev_only_compare.normalize_asset(asset)
    if normalized in CASH_EQUIVALENT_ASSETS:
        return "CASH"
    if normalized == "BTC":
        return "BTC"
    if normalized == "BASE":
        return "BASE"
    return "ALT"


def _market_state(exposure: float) -> str:
    return "IN_MARKET" if exposure > SUMMARY_TOLERANCE else "OUT_OF_MARKET"


def _execution_state(asset: str, exposure: float) -> str:
    return asset if exposure > SUMMARY_TOLERANCE else "OUT_OF_MARKET"


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
    return (mean_ret / std) * (365.0**0.5)


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
    return (mean_ret / downside_std) * (365.0**0.5)


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


def _compute_total_return_pct(series: pd.Series) -> float:
    curve = (1.0 + pd.to_numeric(series, errors="coerce").fillna(0.0)).cumprod()
    if curve.empty:
        return 0.0
    return float((curve.iloc[-1] - 1.0) * 100.0)


def _compute_cagr_pct(series: pd.Series, dates: pd.Series) -> float:
    clean_returns = pd.to_numeric(series, errors="coerce").fillna(0.0)
    clean_dates = pd.to_datetime(dates, errors="coerce")
    valid_mask = clean_dates.notna()
    clean_returns = clean_returns.loc[valid_mask]
    clean_dates = clean_dates.loc[valid_mask]
    if len(clean_returns) < 2:
        return 0.0
    start_dt = pd.Timestamp(clean_dates.iloc[0])
    end_dt = pd.Timestamp(clean_dates.iloc[-1])
    day_count = max(int((end_dt - start_dt).days), 1)
    years = day_count / 365.25
    if years <= 0:
        return 0.0
    ending_equity = float((1.0 + clean_returns).cumprod().iloc[-1])
    if ending_equity <= 0:
        return 0.0
    return float(((ending_equity ** (1.0 / years)) - 1.0) * 100.0)


def _compute_cagr_since(series: pd.Series, dates: pd.Series, start_day: str) -> float:
    clean_dates = pd.to_datetime(dates, errors="coerce")
    mask = clean_dates >= pd.Timestamp(start_day)
    if not mask.any():
        return _compute_cagr_pct(series, dates)
    return _compute_cagr_pct(series.loc[mask], clean_dates.loc[mask])


def _compute_max_drawdown_pct(series: pd.Series) -> float:
    curve = (1.0 + pd.to_numeric(series, errors="coerce").fillna(0.0)).cumprod()
    if curve.empty:
        return 0.0
    drawdown = (curve / curve.cummax()) - 1.0
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


def _sanitize_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    return value


def capture_protected_state(*, root: Path | None = None) -> dict[str, dict[str, Any]]:
    repo_root = (root or ROOT).resolve()
    payload: dict[str, dict[str, Any]] = {}
    for relative_path in PROTECTED_RELATIVE_PATHS:
        path = repo_root / relative_path
        if not path.exists():
            payload[relative_path] = {"path": relative_path, "exists": False}
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


def _prepare_baseline_frame_from_timeseries(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    df = frame.copy()
    df.columns = [str(column).strip() for column in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").copy()

    for column in [
        "candidate_asset",
        "selected_asset",
        "actual_held_asset",
        "authorized_tradable_asset",
        "held_asset",
        "current_asset",
        "execution_target_asset",
    ]:
        if column in df.columns:
            df[column] = df[column].map(dev_only_compare.normalize_asset)

    for column in [
        "model_candidate_exposure",
        "effective_market_exposure",
        "current_exposure",
        "trend_score",
        "buy_threshold",
        "trend_activation_threshold",
        "return_gross",
        "return_net",
        "fees_daily",
        "funding_daily",
        "borrow_cost_daily",
        "slippage_cost_daily",
        "turnover",
        "btc_return",
        "btc_close",
        "equity",
    ]:
        if column in df.columns:
            df[column] = dev_only_compare.parse_float_series(df[column]).fillna(0.0)

    for column in [
        "trend_permission_active",
        "is_rebalance_day",
        "asset_transition_day",
        "trend_block_day",
        "stress_block_day",
        "trend_gate_pass",
    ]:
        if column in df.columns:
            df[column] = dev_only_compare.parse_bool_series(df[column])
        else:
            df[column] = False

    hard_invalidation, hard_invalidation_meta = dev_only_compare.detect_hard_invalidation(df)
    df["hard_invalidation"] = hard_invalidation
    df["baseline_cash"] = df["current_asset"].eq("CASH") & df["effective_market_exposure"].abs().le(1e-12)
    df["baseline_non_cash"] = ~df["baseline_cash"]
    df["baseline_state"] = np.where(df["baseline_cash"], "CASH", "FULL_RISK")
    df["baseline_total_cost_daily"] = (
        df["fees_daily"] + df["funding_daily"] + df["borrow_cost_daily"] + df["slippage_cost_daily"]
    )
    df["baseline_equity_gross"] = (1.0 + df["return_gross"]).cumprod()
    df["baseline_equity_net"] = (1.0 + df["return_net"]).cumprod()
    df["btc_candidate_persistence_rows"] = dev_only_compare.compute_btc_candidate_persistence_rows(df)
    df["persistence_entry_filter_ready"] = (
        df["baseline_cash"]
        & df["candidate_asset"].eq("BTC")
        & df["btc_candidate_persistence_rows"].ge(dev_only_compare.PERSISTENCE_ROWS_REQUIRED)
        & (~df["trend_permission_active"])
        & df["trend_score"].gt(-0.20)
        & df["trend_score"].lt(0.10)
        & (~df["stress_block_day"])
        & (~df["hard_invalidation"])
    )
    return df.reset_index(drop=True), hard_invalidation_meta, dev_only_compare.derive_cost_model(df)


def _compare_baseline_route(canonical: pd.DataFrame, authorized: pd.DataFrame) -> None:
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
        if column not in canonical.columns or column not in authorized.columns:
            raise ValueError(f"Missing required baseline comparison column: {column}")
    if len(canonical) != len(authorized):
        raise ValueError(
            "Canonical phase68g rebuild does not match authorized baseline row count "
            f"(canonical={len(canonical)} authorized={len(authorized)})"
        )
    for column in required_columns:
        left = canonical[column]
        right = authorized[column]
        if column in {"date", "candidate_asset", "selected_asset", "actual_held_asset", "authorized_tradable_asset", "current_asset", "reason_code"}:
            if left.fillna("").astype(str).tolist() != right.fillna("").astype(str).tolist():
                raise ValueError(f"Canonical phase68g rebuild diverges from authorized baseline on {column}")
            continue
        if column == "trend_permission_active":
            if _to_bool_series(left).tolist() != _to_bool_series(right).tolist():
                raise ValueError(f"Canonical phase68g rebuild diverges from authorized baseline on {column}")
            continue
        if (
            _to_float_series(left).round(12) - _to_float_series(right).round(12)
        ).abs().gt(1e-12).any():
            raise ValueError(f"Canonical phase68g rebuild diverges from authorized baseline on {column}")


def _build_variant_state(baseline_frame: pd.DataFrame, cost_model: dict[str, Any]) -> dict[str, Any]:
    variant_frames = {
        variant_id: dev_only_compare.build_variant_frame(
            baseline_frame,
            variant_id=variant_id,
            cost_model=cost_model,
        )
        for variant_id in dev_only_compare.VARIANT_SPECS
    }
    activation_windows = pd.concat(
        [dev_only_compare.build_activation_windows(frame) for frame in variant_frames.values()],
        ignore_index=True,
    )
    handoff_audit = pd.concat(
        [dev_only_compare.build_handoff_row_audit(frame) for frame in variant_frames.values()],
        ignore_index=True,
    )
    period_rows: list[dict[str, Any]] = []
    for variant_id, frame in variant_frames.items():
        windows = activation_windows.loc[activation_windows["variant_id"] == variant_id].copy()
        audit = handoff_audit.loc[handoff_audit["variant_id"] == variant_id].copy()
        for _period_name, start_date, end_date in dev_only_compare.PERIOD_DEFS:
            period_rows.append(
                dev_only_compare.build_period_metrics(
                    frame,
                    windows,
                    audit,
                    variant_id=variant_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
    period_compare = pd.DataFrame(period_rows)
    blocker_counts = dev_only_compare.build_blocker_counts(variant_frames)
    cost_metrics = dev_only_compare.build_cost_metrics(variant_frames)
    variant_compare = dev_only_compare.build_variant_compare(period_compare)
    selected_variant_row = variant_compare.loc[variant_compare["variant_id"] == SELECTED_VARIANT_ID].iloc[0].to_dict()
    return {
        "variant_frames": variant_frames,
        "activation_windows": activation_windows,
        "handoff_audit": handoff_audit,
        "period_compare": period_compare,
        "blocker_counts": blocker_counts,
        "cost_metrics": cost_metrics,
        "variant_compare": variant_compare,
        "selected_variant_row": selected_variant_row,
        "selected_variant_frame": variant_frames[SELECTED_VARIANT_ID].copy(),
        "selected_activation_windows": activation_windows.loc[activation_windows["variant_id"] == SELECTED_VARIANT_ID].copy(),
        "selected_handoff_audit": handoff_audit.loc[handoff_audit["variant_id"] == SELECTED_VARIANT_ID].copy(),
        "selected_period_compare": period_compare.loc[period_compare["variant_id"] == SELECTED_VARIANT_ID].copy(),
        "selected_blocker_counts": blocker_counts.loc[blocker_counts["variant_id"] == SELECTED_VARIANT_ID].copy(),
        "selected_cost_metrics": cost_metrics.loc[cost_metrics["variant_id"] == SELECTED_VARIANT_ID].copy(),
    }


def _build_model_candidate_returns(baseline_timeseries: pd.DataFrame, selected_variant_frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    gross = _to_float_series(baseline_timeseries["model_candidate_return_gross"]).copy()
    net = _to_float_series(baseline_timeseries["model_candidate_return_net"]).copy()
    btc_cash_mask = selected_variant_frame["baseline_cash"] & selected_variant_frame["candidate_asset"].eq("BTC")
    gross.loc[btc_cash_mask] = (
        _to_float_series(selected_variant_frame.loc[btc_cash_mask, "btc_return"]) * EARLY_RISK_EXPOSURE
    )
    net.loc[btc_cash_mask] = gross.loc[btc_cash_mask]
    equity = (1.0 + net).cumprod()
    return gross.round(12), net.round(12), equity.round(12)


def _build_active_timeseries(shared: dict[str, Any]) -> pd.DataFrame:
    baseline_timeseries = shared["canonical_baseline_timeseries"].copy().reset_index(drop=True)
    selected_variant_frame = shared["selected_variant_frame"].copy().reset_index(drop=True)
    frame = baseline_timeseries.copy()
    if len(frame) != len(selected_variant_frame):
        raise ValueError("Candidate variant frame length does not match canonical baseline timeseries length")

    exposure = _to_float_series(selected_variant_frame["candidate_effective_leverage"]).round(12)
    held_asset = selected_variant_frame["candidate_held_asset"].map(dev_only_compare.normalize_asset)
    trend_permission_active = exposure > SUMMARY_TOLERANCE
    model_candidate_return_gross, model_candidate_return_net, model_candidate_equity = _build_model_candidate_returns(
        baseline_timeseries,
        selected_variant_frame,
    )

    frame["strategy_id"] = PRODUCTION_STRATEGY_ID
    frame["strategy_version"] = CANDIDATE_ID
    frame["candidate_asset"] = selected_variant_frame["candidate_asset"].astype(str)
    frame["selected_asset"] = selected_variant_frame["selected_asset"].astype(str)
    frame["model_candidate_exposure"] = _to_float_series(baseline_timeseries["model_candidate_exposure"]).round(12)
    btc_cash_mask = selected_variant_frame["baseline_cash"] & selected_variant_frame["candidate_asset"].eq("BTC")
    frame.loc[btc_cash_mask, "model_candidate_exposure"] = EARLY_RISK_EXPOSURE
    frame["trend_permission_active"] = trend_permission_active
    frame["actual_held_asset"] = held_asset
    frame["authorized_tradable_asset"] = held_asset
    frame["held_asset"] = held_asset
    frame["current_asset"] = held_asset
    frame["effective_market_exposure"] = exposure
    frame["current_exposure"] = exposure
    frame["exposure"] = exposure
    frame["regime"] = held_asset.map(_classify_regime)
    frame["market_state"] = exposure.map(_market_state)
    frame["execution_state"] = [
        _execution_state(asset=str(asset), exposure=float(local_exposure))
        for asset, local_exposure in zip(held_asset.tolist(), exposure.tolist())
    ]
    frame["execution_target_asset"] = [
        str(asset) if float(local_exposure) > SUMMARY_TOLERANCE else "CASH"
        for asset, local_exposure in zip(held_asset.tolist(), exposure.tolist())
    ]
    frame["execution_target_exposure"] = exposure
    frame["model_candidate_return_gross"] = model_candidate_return_gross
    frame["model_candidate_return_net"] = model_candidate_return_net
    frame["model_candidate_equity"] = model_candidate_equity
    frame["authorized_return_gross"] = _to_float_series(selected_variant_frame["candidate_return_gross"]).round(12)
    frame["authorized_return_net"] = _to_float_series(selected_variant_frame["candidate_return_net"]).round(12)
    frame["authorized_equity"] = _to_float_series(selected_variant_frame["candidate_equity_net"]).round(12)
    frame["return_gross"] = frame["authorized_return_gross"]
    frame["return_net"] = frame["authorized_return_net"]
    frame["equity"] = frame["authorized_equity"]
    frame["drawdown_pct"] = (((frame["equity"] / frame["equity"].cummax()) - 1.0) * 100.0).round(12)
    frame["fees_daily"] = _to_float_series(selected_variant_frame["candidate_fees_daily"]).round(12)
    frame["fees_cumulative"] = frame["fees_daily"].cumsum().round(12)
    frame["funding_daily"] = _to_float_series(selected_variant_frame["candidate_funding_daily"]).round(12)
    frame["funding_cumulative"] = frame["funding_daily"].cumsum().round(12)
    frame["borrow_cost_daily"] = _to_float_series(selected_variant_frame["candidate_borrow_cost_daily"]).round(12)
    frame["borrow_cost_cumulative"] = frame["borrow_cost_daily"].cumsum().round(12)
    frame["slippage_cost_daily"] = _to_float_series(selected_variant_frame["candidate_slippage_cost_daily"]).round(12)
    frame["slippage_cost_cumulative"] = frame["slippage_cost_daily"].cumsum().round(12)
    frame["turnover"] = _to_float_series(selected_variant_frame["candidate_turnover"]).round(12)
    frame["cash_day"] = frame["effective_market_exposure"] <= SUMMARY_TOLERANCE
    frame["btc_day"] = (frame["held_asset"] == "BTC") & (~frame["cash_day"])
    frame["in_market"] = ~frame["cash_day"]
    frame["is_rebalance_day"] = _to_bool_series(selected_variant_frame["candidate_asset_transition_day"])
    frame["asset_transition_day"] = frame["is_rebalance_day"]
    frame["leverage_active"] = frame["effective_market_exposure"] > (1.0 + SUMMARY_TOLERANCE)
    frame["leverage_state_reason"] = baseline_timeseries["leverage_state_reason"].fillna("").astype(str)
    frame.loc[selected_variant_frame["early_risk_active"], "leverage_state_reason"] = "early_risk_075"
    frame["reason_code"] = selected_variant_frame["candidate_reason"].astype(str)
    frame["rolling_return_7d"] = _rolling_compound_return(frame["return_net"], 7)
    frame["rolling_return_30d"] = _rolling_compound_return(frame["return_net"], 30)
    frame["rolling_return_90d"] = _rolling_compound_return(frame["return_net"], 90)
    frame["rolling_vol_30d"] = frame["return_net"].rolling(window=30, min_periods=30).std(ddof=0) * np.sqrt(365.25)
    frame["rolling_sharpe_90d"] = _rolling_sharpe(frame["return_net"], 90)
    frame["source_validated"] = True
    frame["baseline_cash"] = selected_variant_frame["baseline_cash"].astype(bool)
    frame["baseline_full_risk"] = selected_variant_frame["baseline_non_cash"].astype(bool)
    frame["btc_candidate_persistence_rows"] = selected_variant_frame["btc_candidate_persistence_rows"].astype(int)
    frame["persistence_entry_filter_ready"] = selected_variant_frame["persistence_entry_filter_ready"].astype(bool)
    frame["early_risk_active"] = selected_variant_frame["early_risk_active"].astype(bool)
    frame["candidate_entry_day"] = selected_variant_frame["candidate_entry_day"].astype(bool)
    frame["candidate_exit_day"] = selected_variant_frame["candidate_exit_day"].astype(bool)
    frame["hard_invalidation"] = selected_variant_frame["hard_invalidation"].astype(bool)
    frame["override_state"] = selected_variant_frame["override_state"].astype(str)
    frame["candidate_reason"] = selected_variant_frame["candidate_reason"].astype(str)
    return frame


def _build_staged_timeseries(shared: dict[str, Any]) -> pd.DataFrame:
    active_timeseries = shared["active_candidate_timeseries"].copy().reset_index(drop=True)
    baseline_timeseries = shared["canonical_baseline_timeseries"].copy().reset_index(drop=True)
    frame = active_timeseries.copy()
    frame["candidate_id"] = CANDIDATE_ID
    frame["candidate_label"] = CANDIDATE_LABEL
    frame["base_strategy_version"] = BASE_STRATEGY_VERSION
    frame["strategy_id"] = STAGED_STRATEGY_ID
    frame["strategy_version"] = CANDIDATE_ID
    frame["dev_only_source_lineage"] = True
    frame["non_authoritative_research_input"] = True
    frame["official_truth"] = False
    frame["live_truth"] = False
    frame["app_truth"] = False
    frame["execution_truth"] = False
    frame["baseline_candidate_asset"] = baseline_timeseries["candidate_asset"].astype(str)
    frame["baseline_selected_asset"] = baseline_timeseries["selected_asset"].astype(str)
    frame["baseline_model_candidate_exposure"] = _to_float_series(baseline_timeseries["model_candidate_exposure"]).round(12)
    frame["baseline_trend_permission_active"] = _to_bool_series(baseline_timeseries["trend_permission_active"])
    frame["baseline_actual_held_asset"] = baseline_timeseries["actual_held_asset"].astype(str)
    frame["baseline_authorized_tradable_asset"] = baseline_timeseries["authorized_tradable_asset"].astype(str)
    frame["baseline_current_asset"] = baseline_timeseries["current_asset"].astype(str)
    frame["baseline_effective_market_exposure"] = _to_float_series(baseline_timeseries["effective_market_exposure"]).round(12)
    frame["baseline_execution_target_asset"] = baseline_timeseries["execution_target_asset"].astype(str)
    frame["baseline_execution_target_exposure"] = _to_float_series(baseline_timeseries["execution_target_exposure"]).round(12)
    frame["baseline_regime"] = baseline_timeseries["regime"].astype(str)
    frame["baseline_market_state"] = baseline_timeseries["market_state"].astype(str)
    frame["baseline_execution_state"] = baseline_timeseries["execution_state"].astype(str)
    frame["baseline_reason_code"] = baseline_timeseries["reason_code"].astype(str)
    frame["baseline_return_gross"] = _to_float_series(baseline_timeseries["return_gross"]).round(12)
    frame["baseline_return_net"] = _to_float_series(baseline_timeseries["return_net"]).round(12)
    frame["baseline_equity"] = _to_float_series(baseline_timeseries["equity"]).round(12)
    frame["baseline_turnover"] = _to_float_series(baseline_timeseries["turnover"]).round(12)
    frame["baseline_fees_daily"] = _to_float_series(baseline_timeseries["fees_daily"]).round(12)
    frame["baseline_funding_daily"] = _to_float_series(baseline_timeseries["funding_daily"]).round(12)
    frame["baseline_borrow_cost_daily"] = _to_float_series(baseline_timeseries["borrow_cost_daily"]).round(12)
    frame["baseline_slippage_daily"] = _to_float_series(baseline_timeseries["slippage_cost_daily"]).round(12)
    frame["baseline_cash_day"] = _to_bool_series(baseline_timeseries["cash_day"])
    frame["baseline_in_market"] = _to_bool_series(baseline_timeseries["in_market"])
    frame["baseline_btc_day"] = _to_bool_series(baseline_timeseries["btc_day"])
    frame["baseline_is_rebalance_day"] = _to_bool_series(baseline_timeseries["is_rebalance_day"])
    frame["baseline_asset_transition_day"] = _to_bool_series(baseline_timeseries["asset_transition_day"])
    return frame


def _period_record_sections(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    baseline: dict[str, Any] = {}
    candidate: dict[str, Any] = {}
    delta: dict[str, Any] = {}
    for metric_name, baseline_key, candidate_key, delta_key in COMPARE_METRIC_SPECS:
        baseline[metric_name] = _sanitize_scalar(0 if baseline_key is None else row[baseline_key])
        candidate[metric_name] = _sanitize_scalar(row[candidate_key])
        delta[metric_name] = _sanitize_scalar(row[delta_key])
    return baseline, candidate, delta


def _build_compare_payload(shared: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected_period_compare = shared["selected_period_compare"]
    windows: dict[str, Any] = {}
    compare_rows: list[dict[str, Any]] = []
    for row in selected_period_compare.to_dict(orient="records"):
        baseline, candidate, delta = _period_record_sections(row)
        period_name = str(row["period"])
        windows[period_name] = {
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "row_count": int(row["row_count"]),
            "compare_basis": {
                "baseline_source_path": "outputs/production/current_strategy_timeseries.csv",
                "gross_and_net_status": "gross_and_net_reported",
                "net_costs_included": True,
            },
            "baseline": baseline,
            "candidate": candidate,
            "delta_candidate_minus_baseline": delta,
        }
        for metric_name, baseline_key, candidate_key, delta_key in COMPARE_METRIC_SPECS:
            compare_rows.append(
                {
                    "period": period_name,
                    "metric": metric_name,
                    "baseline_value": _sanitize_scalar(0 if baseline_key is None else row[baseline_key]),
                    "candidate_value": _sanitize_scalar(row[candidate_key]),
                    "delta_candidate_minus_baseline": _sanitize_scalar(row[delta_key]),
                    "return_basis_status": "gross_and_net_reported",
                    "net_costs_included": True,
                }
            )

    window_counts = {
        "activation_windows_count": int(len(shared["selected_activation_windows"])),
        "successful_handoff_count": int((~shared["selected_activation_windows"]["false_start"]).sum())
        if not shared["selected_activation_windows"].empty
        else 0,
        "false_start_count": int(shared["selected_activation_windows"]["false_start"].sum())
        if not shared["selected_activation_windows"].empty
        else 0,
    }
    compare_payload = {
        "artifact_type": "staged_strategy_candidate_compare",
        "schema_version": COMPARE_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "candidate_id": CANDIDATE_ID,
        "candidate_label": CANDIDATE_LABEL,
        "base_strategy_version": BASE_STRATEGY_VERSION,
        "baseline_source_path": "outputs/production/current_strategy_timeseries.csv",
        "candidate_universe_rule": (
            "Candidate compare rows use the current Production Core date universe, while the durable fallback "
            "baseline route is rebuilt independently from canonical phase68g source exports."
        ),
        "comparison_status": {
            "gross_and_net_status": "gross_and_net_reported",
            "net_costs_included": True,
        },
        "window_counts": window_counts,
        "selected_variant": {key: _sanitize_scalar(value) for key, value in shared["selected_variant_row"].items()},
        "durable_baseline_route": {
            "mode": "canonical_phase68g_source_rebuild",
            "independent_of_active_current_strategy": True,
            "base_strategy_version": BASE_STRATEGY_VERSION,
        },
        "windows": windows,
        "blocker_rows": [
            {key: _sanitize_scalar(value) for key, value in row.items()}
            for row in shared["selected_blocker_counts"].to_dict(orient="records")
        ],
    }
    return compare_payload, compare_rows


def _build_active_snapshot_metrics(timeseries: pd.DataFrame) -> dict[str, Any]:
    sharpe = _annualized_sharpe_from_daily_returns(timeseries["authorized_return_net"])
    sortino = _annualized_sortino_from_daily_returns(timeseries["authorized_return_net"])
    if sharpe is None or sortino is None:
        raise ValueError("Unable to compute Production Core candidate Sharpe/Sortino from authorized returns.")
    return {
        "total_return_pct_net": round(_compute_total_return_pct(timeseries["authorized_return_net"]), 4),
        "cagr_pct_net": round(_compute_cagr_pct(timeseries["authorized_return_net"], timeseries["date"]), 4),
        "max_drawdown_pct_net": round(_compute_max_drawdown_pct(timeseries["authorized_return_net"]), 4),
        "since2023_cagr_pct_net": round(
            _compute_cagr_since(timeseries["authorized_return_net"], timeseries["date"], "2023-01-01"),
            4,
        ),
        "since2025_cagr_pct_net": round(
            _compute_cagr_since(timeseries["authorized_return_net"], timeseries["date"], "2025-01-01"),
            4,
        ),
        "sharpe": round(float(sharpe), 4),
        "sortino": round(float(sortino), 4),
        "trading_fees_total_pct": round(float(_to_float_series(timeseries["fees_daily"]).sum() * 100.0), 6),
        "funding_total_pct": round(float(_to_float_series(timeseries["funding_daily"]).sum() * 100.0), 6),
        "borrow_cost_total_pct": round(float(_to_float_series(timeseries["borrow_cost_daily"]).sum() * 100.0), 6),
        "slippage_cost_total_pct": round(float(_to_float_series(timeseries["slippage_cost_daily"]).sum() * 100.0), 6),
        "cash_days_pct": round(float(_to_bool_series(timeseries["cash_day"]).mean() * 100.0), 6),
        "btc_days_pct": round(float(_to_bool_series(timeseries["btc_day"]).mean() * 100.0), 6),
        "switch_count": int(_to_bool_series(timeseries["asset_transition_day"]).sum()),
        "trade_count": int(_to_bool_series(timeseries["asset_transition_day"]).sum()),
    }


def _build_staged_snapshot_metrics(shared: dict[str, Any]) -> dict[str, Any]:
    active_metrics = _build_active_snapshot_metrics(shared["active_candidate_timeseries"])
    active_timeseries = shared["active_candidate_timeseries"]
    full_row = shared["selected_period_compare"].loc[shared["selected_period_compare"]["period"] == "full_available"].iloc[0]
    since2025_row = shared["selected_period_compare"].loc[shared["selected_period_compare"]["period"] == "since2025"].iloc[0]
    missed_row = shared["selected_period_compare"].loc[shared["selected_period_compare"]["period"] == "missed_window_2025"].iloc[0]
    since2025_mask = pd.to_datetime(active_timeseries["date"], errors="coerce") >= pd.Timestamp("2025-01-01")
    return {
        "gross_total_return_pct": round(float(full_row["candidate_gross_total_return_pct"]), 6),
        "net_total_return_pct": round(float(full_row["candidate_net_total_return_pct"]), 6),
        "gross_cagr_pct": round(_compute_cagr_pct(active_timeseries["authorized_return_gross"], active_timeseries["date"]), 6),
        "net_cagr_pct": round(float(full_row["candidate_net_cagr_pct"]), 6),
        "gross_max_drawdown_pct": round(_compute_max_drawdown_pct(active_timeseries["authorized_return_gross"]), 6),
        "net_max_drawdown_pct": round(float(full_row["candidate_net_max_drawdown_pct"]), 6),
        "since2025_gross_cagr_pct": round(
            _compute_cagr_pct(
                active_timeseries.loc[since2025_mask, "authorized_return_gross"],
                active_timeseries.loc[since2025_mask, "date"],
            ),
            6,
        ),
        "since2025_net_cagr_pct": round(float(since2025_row["candidate_net_cagr_pct"]), 6),
        "trading_fees_total_pct": active_metrics["trading_fees_total_pct"],
        "funding_total_pct": active_metrics["funding_total_pct"],
        "borrow_cost_total_pct": active_metrics["borrow_cost_total_pct"],
        "slippage_cost_total_pct": active_metrics["slippage_cost_total_pct"],
        "total_cost_pct": round(
            active_metrics["trading_fees_total_pct"]
            + active_metrics["funding_total_pct"]
            + active_metrics["borrow_cost_total_pct"]
            + active_metrics["slippage_cost_total_pct"],
            6,
        ),
        "cash_days_pct": round(float(active_metrics["cash_days_pct"]), 6),
        "exposure_days": int(full_row["candidate_exposure_days"]),
        "switch_count": int(full_row["candidate_switch_count"]),
        "trade_count": int(full_row["candidate_switch_count"]),
        "turnover_total": round(float(full_row["candidate_turnover_total"]), 6),
        "early_risk_days": int(full_row["early_risk_days"]),
        "successful_handoff_count": int(full_row["successful_handoff_count"]),
        "false_start_count": int(full_row["false_start_count"]),
        "missed_window_capture_pct": round(float(missed_row["missed_btc_move_captured_pct"] or 0.0), 6),
        "sharpe": active_metrics["sharpe"],
        "sortino": active_metrics["sortino"],
    }


def build_reason_text(row: pd.Series) -> str:
    reason_code = str(row.get("reason_code") or "").strip()
    candidate_asset = dev_only_compare.normalize_asset(row.get("candidate_asset"))
    actual_asset = dev_only_compare.normalize_asset(row.get("actual_held_asset", row.get("held_asset")))
    exposure = float(row.get("effective_market_exposure", row.get("current_exposure", 0.0)) or 0.0)
    trend_score = float(row.get("trend_score", 0.0) or 0.0)
    persistence_rows = int(float(row.get("btc_candidate_persistence_rows", 0) or 0))
    if reason_code in {"btc_candidate_persistence_10d_entry", "btc_candidate_persistence_maintenance"}:
        return (
            "BTC EARLY_RISK is active at 0.75x because BTC persisted as the candidate for at least 10 "
            "consecutive rows and the pre-authorization trend band stayed inside -0.20 < trend_score < 0.10."
        )
    if reason_code == "baseline_non_cash_strict_pass_through":
        return (
            f"The strategy passes through the baseline FULL_RISK row unchanged, so authorized exposure remains "
            f"{actual_asset} at {exposure:.2f}x."
        )
    if reason_code == "candidate_persistence_lt_10_rows":
        return (
            f"BTC remains only the candidate. The strategy stays in CASH because the 10-row persistence gate is "
            f"not ready yet ({persistence_rows}/10 rows)."
        )
    if reason_code == "trend_score_le_minus_020":
        return (
            f"BTC remains only the candidate. The strategy stays in CASH because trend_score {trend_score:.4f} "
            "is at or below the -0.20 early-risk floor."
        )
    if reason_code == "stress_or_hard_invalidation_on":
        return "The strategy stays in CASH because the stress or hard-invalidation blocker is active."
    if reason_code == "candidate_asset_not_btc":
        return (
            f"{candidate_asset} is the current baseline candidate, so the BTC persistence EARLY_RISK overlay stays "
            "inactive and authorized exposure remains in CASH."
        )
    if reason_code == "trend_score_ge_0p10_pre_entry":
        return (
            f"BTC remains only the candidate. The strategy stays in CASH because trend_score {trend_score:.4f} is "
            "already above the early-risk band and the overlay does not force a late pre-entry."
        )
    if actual_asset in CASH_EQUIVALENT_ASSETS:
        return "The strategy remains in CASH because the BTC persistence EARLY_RISK filter is not active."
    return f"The strategy holds {actual_asset} with authorized market exposure at {exposure:.2f}x."


def build_wait_condition(row: pd.Series, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    del metrics
    candidate_asset = dev_only_compare.normalize_asset(row.get("candidate_asset"))
    actual_asset = dev_only_compare.normalize_asset(row.get("actual_held_asset", row.get("held_asset")))
    exposure = float(row.get("effective_market_exposure", 0.0) or 0.0)
    reason_code = str(row.get("reason_code") or "").strip()
    if exposure > SUMMARY_TOLERANCE:
        return {
            "code": "already_in_target_state",
            "text": f"The strategy is already in its current authorized state for {actual_asset}.",
            "current_values": {
                "candidate_asset": candidate_asset,
                "actual_held_asset": actual_asset,
                "current_exposure": exposure,
            },
            "target_condition": {"next_rebalance_date": None},
        }
    if reason_code == "candidate_persistence_lt_10_rows":
        persistence_rows = int(float(row.get("btc_candidate_persistence_rows", 0) or 0))
        return {
            "code": "candidate_persistence_wait",
            "text": (
                f"BTC is the candidate, but the strategy waits for 10 consecutive candidate rows "
                f"before EARLY_RISK can activate ({persistence_rows}/10 so far)."
            ),
            "current_values": {
                "candidate_asset": candidate_asset,
                "persistence_rows": persistence_rows,
                "required_rows": 10,
            },
            "target_condition": {"persistence_rows_min": 10},
        }
    if reason_code == "trend_score_le_minus_020":
        return {
            "code": "early_risk_trend_floor_block",
            "text": "BTC is the candidate, but the strategy waits for trend_score to rise above -0.20.",
            "current_values": {
                "candidate_asset": candidate_asset,
                "trend_score": float(row.get("trend_score", 0.0) or 0.0),
                "early_risk_floor": -0.20,
            },
            "target_condition": {"trend_score_gt": -0.20},
        }
    if reason_code == "stress_or_hard_invalidation_on":
        return {
            "code": "stress_or_hard_invalidation_block",
            "text": "The strategy waits for the stress or hard-invalidation blocker to clear.",
            "current_values": {
                "stress_block_day": bool(row.get("stress_block_day", False)),
                "hard_invalidation": bool(row.get("hard_invalidation", False)),
            },
            "target_condition": {"stress_block_day": False, "hard_invalidation": False},
        }
    return {
        "code": "candidate_filter_not_active",
        "text": build_reason_text(row),
        "current_values": {
            "candidate_asset": candidate_asset,
            "actual_held_asset": actual_asset,
            "trend_score": float(row.get("trend_score", 0.0) or 0.0),
        },
        "target_condition": {"entry_filter_ready": True},
    }


def _load_shared_inputs(*, root: Path | None = None, require_durable_baseline: bool = True) -> dict[str, Any]:
    repo_root = (root or ROOT).resolve()
    baseline_adapter = Phase68g66g1p25xCandidateAdapter()
    canonical_source_paths = baseline_adapter.resolve_source_paths(root=repo_root)

    current_snapshot_path = repo_root / "outputs" / "production" / "current_strategy_snapshot.json"
    current_timeseries_path = repo_root / "outputs" / "production" / "current_strategy_timeseries.csv"
    current_diagnostics_path = repo_root / "outputs" / "production" / "current_strategy_diagnostics.json"
    current_snapshot = _read_json_required(current_snapshot_path)
    current_timeseries = _read_dataframe_required(current_timeseries_path)
    current_diagnostics = _read_json_required(current_diagnostics_path)
    if str(current_snapshot.get("strategy_version") or "").strip() != BASE_STRATEGY_VERSION:
        raise ValueError(
            "Authorized Production Core baseline is not phase68g_66g_1p25x_candidate; "
            f"actual={current_snapshot.get('strategy_version')!r}"
        )
    current_closed_day = _normalize_iso_day_text(current_snapshot.get("closed_day"), context="current_snapshot.closed_day")
    if _normalize_iso_day_text(current_timeseries["date"].iloc[-1], context="current_timeseries.last_row.date") != current_closed_day:
        raise ValueError("Authorized baseline timeseries last date does not match current_strategy_snapshot.closed_day")
    if _normalize_iso_day_text(current_diagnostics.get("closed_day"), context="current_diagnostics.closed_day") != current_closed_day:
        raise ValueError("Authorized baseline diagnostics closed_day does not match current_strategy_snapshot.closed_day")

    canonical_baseline_inputs = None
    canonical_baseline_timeseries = current_timeseries.copy()
    durable_baseline_ready = False
    durability_gap_reason = None
    try:
        canonical_baseline_inputs = baseline_adapter.load_inputs(root=repo_root)
        canonical_baseline_timeseries = baseline_adapter.build_timeseries(canonical_baseline_inputs)
        if canonical_baseline_inputs["closed_day"] != current_closed_day:
            raise ValueError(
                "Canonical phase68g rebuild closed_day does not match authorized baseline closed_day "
                f"(canonical={canonical_baseline_inputs['closed_day']} authorized={current_closed_day})"
            )
        _compare_baseline_route(canonical_baseline_timeseries, current_timeseries)
        durable_baseline_ready = True
    except Exception as exc:
        durability_gap_reason = str(exc)
        if require_durable_baseline:
            raise

    evidence_summary_path = DEV_ONLY_OUTPUT_DIR / "summary.json"
    evidence_quality_path = DEV_ONLY_OUTPUT_DIR / "quality.json"
    evidence_variant_compare_path = DEV_ONLY_OUTPUT_DIR / "variant_compare.csv"
    evidence_summary = _read_json_required(evidence_summary_path)
    evidence_quality = _read_json_required(evidence_quality_path)
    evidence_variant_compare = _read_dataframe_required(evidence_variant_compare_path)
    if str(evidence_quality.get("status") or "").strip() != "passed":
        raise ValueError("Dev-only BTC persistence evidence quality must be passed before staged build.")
    if str(evidence_summary.get("selected_variant_id") or "").strip() != SELECTED_VARIANT_ID:
        raise ValueError(
            "Dev-only BTC persistence evidence does not select btc_candidate_persistence_10d_075 "
            f"(actual={evidence_summary.get('selected_variant_id')!r})"
        )
    if SELECTED_VARIANT_ID not in evidence_variant_compare["variant_id"].astype(str).tolist():
        raise ValueError("Dev-only BTC persistence evidence variant_compare.csv is missing btc_candidate_persistence_10d_075.")

    baseline_frame, hard_invalidation_meta, cost_model = _prepare_baseline_frame_from_timeseries(canonical_baseline_timeseries)
    variant_state = _build_variant_state(baseline_frame, cost_model)
    active_candidate_timeseries = _build_active_timeseries(
        {
            "canonical_baseline_timeseries": canonical_baseline_timeseries,
            "selected_variant_frame": variant_state["selected_variant_frame"],
        }
    )

    source_paths = {
        "authorized_baseline_snapshot": current_snapshot_path,
        "authorized_baseline_timeseries": current_timeseries_path,
        "authorized_baseline_diagnostics": current_diagnostics_path,
        "dev_only_contract": DEV_ONLY_CONTRACT_PATH,
        "dev_only_spec": DEV_ONLY_SPEC_PATH,
        "dev_only_manifest_seed": DEV_ONLY_MANIFEST_SEED_PATH,
        "dev_only_summary": evidence_summary_path,
        "dev_only_quality": evidence_quality_path,
        "dev_only_variant_compare": evidence_variant_compare_path,
        "dev_only_script": repo_root / "scripts" / "dev_only_production_core_btc_candidate_persistence_early_risk_compare.py",
    }
    if canonical_baseline_inputs is not None:
        source_paths.update(canonical_baseline_inputs["source_paths"])

    shared = {
        "repo_root": repo_root,
        "baseline_adapter": baseline_adapter,
        "canonical_baseline_inputs": canonical_baseline_inputs,
        "canonical_baseline_timeseries": canonical_baseline_timeseries,
        "current_snapshot": current_snapshot,
        "current_timeseries": current_timeseries,
        "current_diagnostics": current_diagnostics,
        "current_closed_day": current_closed_day,
        "evidence_summary": evidence_summary,
        "evidence_quality": evidence_quality,
        "evidence_variant_compare": evidence_variant_compare,
        "baseline_frame": baseline_frame,
        "hard_invalidation_meta": hard_invalidation_meta,
        "cost_model": cost_model,
        "source_paths": source_paths,
        "active_candidate_timeseries": active_candidate_timeseries,
        "durable_baseline_ready": durable_baseline_ready,
        "durability_gap_reason": durability_gap_reason,
        "canonical_source_paths": canonical_source_paths,
    }
    shared.update(variant_state)
    return shared


@dataclass(frozen=True)
class Phase68gBtcPersistence10dEarlyRisk075Adapter:
    strategy_id: str = PRODUCTION_STRATEGY_ID
    strategy_version: str = CANDIDATE_ID
    adapter_name: str = ADAPTER_NAME

    def load_inputs(self, *, root: Path | None = None) -> dict[str, Any]:
        return _load_shared_inputs(root=root, require_durable_baseline=True)

    def build_timeseries(self, inputs: dict[str, Any]) -> pd.DataFrame:
        return inputs["active_candidate_timeseries"].copy()

    def build_reason_text(self, row: pd.Series) -> str:
        return build_reason_text(row)

    def build_wait_condition(self, row: pd.Series, metrics: dict[str, Any]) -> dict[str, Any]:
        return build_wait_condition(row, metrics)

    def build_source_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        canonical_inputs = inputs.get("canonical_baseline_inputs")
        source_paths = inputs["source_paths"]
        evidence_variant_row = inputs["evidence_variant_compare"].loc[
            inputs["evidence_variant_compare"]["variant_id"].astype(str) == SELECTED_VARIANT_ID
        ].iloc[0]
        files: dict[str, Any] = {
            "authorized_baseline_snapshot": {
                **_source_file_metadata(source_paths["authorized_baseline_snapshot"]),
                "closed_day": inputs["current_closed_day"],
                "strategy_version": BASE_STRATEGY_VERSION,
            },
            "authorized_baseline_timeseries": _source_file_metadata(
                source_paths["authorized_baseline_timeseries"],
                last_date=inputs["current_closed_day"],
                row_count=len(inputs["current_timeseries"]),
            ),
            "authorized_baseline_diagnostics": {
                **_source_file_metadata(source_paths["authorized_baseline_diagnostics"]),
                "closed_day": inputs["current_closed_day"],
            },
            "dev_only_contract": _source_file_metadata(source_paths["dev_only_contract"]),
            "dev_only_spec": _source_file_metadata(source_paths["dev_only_spec"]),
            "dev_only_manifest_seed": _source_file_metadata(source_paths["dev_only_manifest_seed"]),
            "dev_only_summary": _source_file_metadata(source_paths["dev_only_summary"]),
            "dev_only_quality": {
                **_source_file_metadata(source_paths["dev_only_quality"]),
                "status": str(inputs["evidence_quality"].get("status") or "").strip(),
            },
            "dev_only_variant_compare": _source_file_metadata(
                source_paths["dev_only_variant_compare"],
                row_count=len(inputs["evidence_variant_compare"]),
            ),
            "dev_only_script": _source_file_metadata(source_paths["dev_only_script"]),
        }
        if canonical_inputs is not None:
            files.update(
                {
                    "phase68g_strategy_summary": _source_file_metadata(
                        canonical_inputs["source_paths"]["strategy_summary"],
                        last_date=inputs["current_closed_day"],
                        row_count=1,
                    ),
                    "phase68g_strategy_paper": _source_file_metadata(
                        canonical_inputs["source_paths"]["strategy_paper"],
                        last_date=canonical_inputs["paper_last_day"],
                        row_count=len(canonical_inputs["paper_df"]),
                    ),
                    "phase68g_trend_status": _source_file_metadata(
                        canonical_inputs["source_paths"]["trend_status"],
                        last_date=canonical_inputs["trend_status_day"],
                        row_count=1,
                    ),
                    "phase68g_trend_history": _source_file_metadata(
                        canonical_inputs["source_paths"]["trend_history"],
                        last_date=canonical_inputs["trend_history_last_day"],
                        row_count=len(canonical_inputs["trend_history_df"]),
                    ),
                    "phase68g_freshness_report": {
                        **_source_file_metadata(
                            canonical_inputs["source_paths"]["freshness_report"],
                            last_date=canonical_inputs["freshness_closed_day"],
                        ),
                        "status": str(canonical_inputs["freshness_payload"].get("status") or "").strip().lower(),
                    },
                    "btc_ohlcv": _source_file_metadata(
                        canonical_inputs["source_paths"]["benchmark_ohlcv"],
                        last_date=canonical_inputs["benchmark_last_day"],
                        row_count=len(canonical_inputs["benchmark_df"]),
                    ),
                }
            )
        else:
            files["phase68g_source_route_error"] = {
                "path": _path_for_manifest(inputs["canonical_source_paths"]["benchmark_ohlcv"], root=ROOT),
                "error": str(inputs.get("durability_gap_reason") or "").strip(),
            }
        return {
            "adapter_name": self.adapter_name,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "validated_closed_day": inputs["current_closed_day"],
            "candidate_label": CANDIDATE_LABEL,
            "base_strategy_version": BASE_STRATEGY_VERSION,
            "durable_baseline_route": {
                "mode": "canonical_phase68g_source_rebuild",
                "independent_of_active_current_strategy": True,
                "base_adapter_name": inputs["baseline_adapter"].adapter_name,
                "status": "ready" if inputs.get("durable_baseline_ready") else "blocked",
                "gap_reason": None if inputs.get("durable_baseline_ready") else str(inputs.get("durability_gap_reason") or "").strip(),
            },
            "evidence_status": {
                "selected_variant_id": str(inputs["evidence_summary"].get("selected_variant_id") or "").strip(),
                "evidence_quality_status": str(inputs["evidence_quality"].get("status") or "").strip(),
                "recommendation": str(evidence_variant_row["recommendation"]),
                "recommendation_reason": str(evidence_variant_row["recommendation_reason"]),
            },
            "lineage": {
                "dev_only_source_lineage": True,
                "non_authoritative_research_input": True,
                "official_truth": False,
                "live_truth": False,
                "app_truth": False,
                "execution_truth": False,
            },
            "files": files,
        }

    def build_snapshot_metrics(self, inputs: dict[str, Any], timeseries: pd.DataFrame) -> dict[str, Any]:
        del inputs
        return _build_active_snapshot_metrics(timeseries)

    def build_decision_context(self, timeseries: pd.DataFrame) -> dict[str, Any]:
        current_row = timeseries.iloc[-1]
        dates = pd.to_datetime(timeseries["date"], errors="coerce")
        latest_rebalance_rows = timeseries.loc[_to_bool_series(timeseries["is_rebalance_day"])]
        latest_rebalance_date = None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["date"])
        risk_on_entry_mask = (~_to_bool_series(timeseries["cash_day"])) & _to_bool_series(
            timeseries["cash_day"].shift(1, fill_value=True)
        )
        current_cash_streak_days = _consecutive_tail_length(_to_bool_series(timeseries["cash_day"])) if bool(current_row["cash_day"]) else 0
        return {
            "current_reason_code": str(current_row["reason_code"]),
            "current_reason_text": build_reason_text(current_row),
            "current_regime_duration_days": int(_consecutive_tail_length(timeseries["regime"])),
            "days_since_last_trade": _days_since_last_true(_to_bool_series(timeseries["is_rebalance_day"]), dates),
            "days_since_last_risk_on": _days_since_last_true(risk_on_entry_mask, dates),
            "days_since_last_equity_high": _days_since_last_true(
                _to_float_series(timeseries["equity"]).round(12) == _to_float_series(timeseries["equity"]).cummax().round(12),
                dates,
            ),
            "current_drawdown_pct": round(float(current_row["drawdown_pct"]), 6),
            "current_cash_streak_days": int(current_cash_streak_days),
            "latest_rebalance_date": latest_rebalance_date,
            "latest_rebalance_reason": None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["reason_code"]),
        }

    def build_diagnostics_payload(
        self,
        *,
        generated_at_utc: str,
        inputs: dict[str, Any],
        timeseries: pd.DataFrame,
        validation: dict[str, Any],
    ) -> dict[str, Any]:
        current_row = timeseries.iloc[-1]
        latest_rebalance_rows = timeseries.loc[_to_bool_series(timeseries["is_rebalance_day"])].tail(5)
        recent_regime_rows = timeseries.loc[
            timeseries["regime"] != timeseries["regime"].shift(1, fill_value=timeseries["regime"].iloc[0])
        ].tail(5)
        trailing_30 = timeseries.tail(30)
        trailing_90 = timeseries.tail(90)
        lifetime_cost_pct = (
            float(_to_float_series(timeseries["fees_daily"]).sum())
            + float(_to_float_series(timeseries["funding_daily"]).sum())
            + float(_to_float_series(timeseries["borrow_cost_daily"]).sum())
            + float(_to_float_series(timeseries["slippage_cost_daily"]).sum())
        ) * 100.0
        metrics = self.build_snapshot_metrics(inputs, timeseries)
        return {
            "artifact_type": "current_strategy_diagnostics",
            "schema_version": ACTIVE_SCHEMA_VERSION,
            "generated_at_utc": generated_at_utc,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "closed_day": inputs["current_closed_day"],
            "latest_state_explanation": build_reason_text(current_row),
            "current_flatline_explanation": (
                f"Authorized capital should stay flat during the current CASH streak of "
                f"{self.build_decision_context(timeseries)['current_cash_streak_days']} days because no market "
                "exposure is currently allowed."
                if bool(current_row["cash_day"])
                else None
            ),
            "current_cash_or_risk_reason": build_reason_text(current_row),
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
                    "reason_text": build_reason_text(row),
                }
                for _, row in latest_rebalance_rows.iterrows()
            ],
            "current_cost_pressure": {
                "current_effective_exposure": round(float(current_row["exposure"]), 6),
                "trailing_30d_fees_pct": round(float(_to_float_series(trailing_30["fees_daily"]).sum() * 100.0), 6),
                "trailing_30d_funding_pct": round(float(_to_float_series(trailing_30["funding_daily"]).sum() * 100.0), 6),
                "trailing_30d_borrow_pct": round(float(_to_float_series(trailing_30["borrow_cost_daily"]).sum() * 100.0), 6),
                "trailing_30d_slippage_pct": round(float(_to_float_series(trailing_30["slippage_cost_daily"]).sum() * 100.0), 6),
            },
            "current_fee_drag_summary": {
                "lifetime_trading_fees_total_pct": metrics["trading_fees_total_pct"],
                "lifetime_funding_total_pct": metrics["funding_total_pct"],
                "lifetime_borrow_cost_total_pct": metrics["borrow_cost_total_pct"],
                "lifetime_slippage_cost_total_pct": metrics["slippage_cost_total_pct"],
                "lifetime_total_cost_pct": round(lifetime_cost_pct, 6),
                "trailing_90d_turnover": round(float(_to_float_series(trailing_90["turnover"]).sum()), 6),
            },
            "current_data_health_summary": {
                "status": validation["status"],
                "closed_day": inputs["current_closed_day"],
                "authorized_compare_baseline_closed_day": inputs["current_closed_day"],
                "canonical_baseline_closed_day": inputs["canonical_baseline_inputs"]["closed_day"],
                "evidence_quality_status": str(inputs["evidence_quality"].get("status") or "").strip(),
                "warnings": list(validation["warnings"]),
            },
            "strategy_improvement_signals": {
                "churn_pressure": {
                    "status": "contained" if float(_to_float_series(trailing_90["turnover"]).sum()) < 8.0 else "elevated",
                    "trade_count": int(metrics["trade_count"]),
                    "switch_count": int(metrics["switch_count"]),
                    "trailing_90d_turnover": round(float(_to_float_series(trailing_90["turnover"]).sum()), 6),
                },
                "fee_sensitivity": {
                    "status": "contained" if lifetime_cost_pct < 20.0 else "elevated",
                    "lifetime_total_cost_pct": round(lifetime_cost_pct, 6),
                    "early_risk_sleeve": EARLY_RISK_EXPOSURE,
                },
                "cash_drag": {
                    "status": "elevated" if float(metrics["cash_days_pct"]) >= 40.0 else "contained",
                    "cash_days_pct": float(metrics["cash_days_pct"]),
                    "current_cash_streak_days": int(self.build_decision_context(timeseries)["current_cash_streak_days"]),
                },
                "flatline_duration": {
                    "status": "active" if bool(current_row["cash_day"]) else "inactive",
                    "current_cash_streak_days": int(self.build_decision_context(timeseries)["current_cash_streak_days"]),
                },
                "current_research_questions": [
                    "Does the BTC 10-row persistence gate still add value after current 2026 data?",
                    "Do false starts remain bounded without materially worsening drawdown?",
                    "Is the 0.75 EARLY_RISK sleeve still the preferred durable candidate over 0.50?",
                ],
            },
            "validation": {
                "status": validation["status"],
                "errors": list(validation["errors"]),
                "warnings": list(validation["warnings"]),
            },
        }

    def compare_summary_metrics(self, *, inputs: dict[str, Any], timeseries: pd.DataFrame) -> list[str]:
        del inputs, timeseries
        return []


@dataclass(frozen=True)
class Phase68gBtcPersistence10dEarlyRisk075StagedAdapter:
    candidate_id: str = CANDIDATE_ID
    candidate_label: str = CANDIDATE_LABEL
    base_strategy_version: str = BASE_STRATEGY_VERSION
    adapter_name: str = ADAPTER_NAME

    def load_inputs(self, *, root: Path | None = None) -> dict[str, Any]:
        shared = _load_shared_inputs(root=root, require_durable_baseline=False)
        shared["active_candidate_timeseries"] = shared["active_candidate_timeseries"].copy()
        return shared

    def build_candidate_timeseries(self, inputs: dict[str, Any]) -> pd.DataFrame:
        return _build_staged_timeseries(inputs)

    def build_candidate_reason_text(self, row: pd.Series) -> str:
        return build_reason_text(row)

    def build_source_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        active_source_inputs = Phase68gBtcPersistence10dEarlyRisk075Adapter().build_source_inputs(inputs)
        return {
            "adapter_name": self.adapter_name,
            "candidate_id": self.candidate_id,
            "candidate_label": self.candidate_label,
            "base_strategy_version": self.base_strategy_version,
            "candidate_compare_closed_day": inputs["current_closed_day"],
            "authorized_compare_baseline_closed_day": inputs["current_closed_day"],
            "authorized_compare_baseline_path": "outputs/production/current_strategy_timeseries.csv",
            "durable_baseline_route": active_source_inputs["durable_baseline_route"],
            "evidence_status": active_source_inputs["evidence_status"],
            "lineage": active_source_inputs["lineage"],
            "files": active_source_inputs["files"],
        }

    def build_snapshot_metrics(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return _build_staged_snapshot_metrics(inputs)

    def build_decision_context(self, timeseries: pd.DataFrame) -> dict[str, Any]:
        current_row = timeseries.iloc[-1]
        dates = pd.to_datetime(timeseries["date"], errors="coerce")
        latest_rebalance_rows = timeseries.loc[_to_bool_series(timeseries["is_rebalance_day"])]
        latest_rebalance_date = None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["date"])
        return {
            "current_reason_code": str(current_row["reason_code"]),
            "current_reason_text": build_reason_text(current_row),
            "current_regime_duration_days": int(_consecutive_tail_length(timeseries["regime"])),
            "current_cash_streak_days": int(_consecutive_tail_length(_to_bool_series(timeseries["cash_day"]))) if bool(current_row["cash_day"]) else 0,
            "days_since_last_trade": _days_since_last_true(_to_bool_series(timeseries["is_rebalance_day"]), dates),
            "days_since_last_early_risk": _days_since_last_true(_to_bool_series(timeseries["early_risk_active"]), dates),
            "latest_rebalance_date": latest_rebalance_date,
            "latest_rebalance_reason": None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["reason_code"]),
            "current_drawdown_pct": round(float(current_row["drawdown_pct"]), 6),
        }

    def build_compare_payload(self, inputs: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return _build_compare_payload(inputs)

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
        recent_rebalance_rows = timeseries.loc[_to_bool_series(timeseries["is_rebalance_day"])].tail(5)
        return {
            "artifact_type": "staged_strategy_candidate_diagnostics",
            "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
            "generated_at_utc": generated_at_utc,
            "candidate_id": self.candidate_id,
            "candidate_label": self.candidate_label,
            "base_strategy_version": self.base_strategy_version,
            "closed_day": inputs["current_closed_day"],
            "compare_universe": {
                "start_date": str(timeseries["date"].iloc[0]),
                "end_date": str(timeseries["date"].iloc[-1]),
                "row_count": int(len(timeseries)),
                "baseline_closed_day": inputs["current_closed_day"],
            },
            "latest_state_explanation": build_reason_text(current_row),
            "baseline_separation_explanation": (
                "This staged bundle is hypothetical only. Live/app/execution truth remains on "
                f"{EXPECTED_LIVE_TRUTH}, while the durable fallback baseline route is rebuilt independently from "
                "canonical phase68g exports rather than from active current_strategy_* outputs."
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
                "reason_text": build_reason_text(current_row),
                "early_risk_active": bool(current_row["early_risk_active"]),
                "candidate_entry_day": bool(current_row["candidate_entry_day"]),
                "candidate_exit_day": bool(current_row["candidate_exit_day"]),
            },
            "current_baseline_trade_state": {
                "candidate_asset": str(current_row["baseline_candidate_asset"]),
                "actual_held_asset": str(current_row["baseline_actual_held_asset"]),
                "effective_market_exposure": round(float(current_row["baseline_effective_market_exposure"]), 6),
                "trend_permission_active": bool(current_row["baseline_trend_permission_active"]),
                "reason_code": str(current_row["baseline_reason_code"]),
            },
            "metrics": self.build_snapshot_metrics(inputs),
            "window_counts": compare_payload["window_counts"],
            "blocker_rows": compare_payload["blocker_rows"],
            "recent_activation_windows": inputs["selected_activation_windows"].tail(5).to_dict(orient="records"),
            "handoff_row_audit": inputs["selected_handoff_audit"].to_dict(orient="records"),
            "recent_rebalance_events": [
                {
                    "date": str(row["date"]),
                    "actual_held_asset": str(row["actual_held_asset"]),
                    "effective_market_exposure": round(float(row["effective_market_exposure"]), 6),
                    "reason_code": str(row["reason_code"]),
                    "reason_text": build_reason_text(row),
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
