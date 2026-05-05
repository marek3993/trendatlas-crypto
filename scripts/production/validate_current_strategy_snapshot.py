from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_adapters.phase68g_66g_1p25x_candidate_adapter import (
    CASH_EQUIVALENT_ASSETS,
    DIAGNOSTICS_SCHEMA_VERSION,
    PRODUCTION_STRATEGY_ID,
    QUALITY_SCHEMA_VERSION,
    ROOT,
    SNAPSHOT_SCHEMA_VERSION,
    SOURCE_STRATEGY_VERSION,
    Phase68g66g1p25xCandidateAdapter,
    SUMMARY_TOLERANCE,
    build_reason_text,
)


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "production"
DEFAULT_SNAPSHOT_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_snapshot.json"
DEFAULT_TIMESERIES_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_timeseries.csv"
DEFAULT_DIAGNOSTICS_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_diagnostics.json"
DEFAULT_QUALITY_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_snapshot.quality.json"


REQUIRED_SNAPSHOT_KEYS = [
    "artifact_type",
    "schema_version",
    "generated_at_utc",
    "strategy_id",
    "strategy_version",
    "closed_day",
    "strategy_status",
    "candidate_asset",
    "selected_asset",
    "actual_held_asset",
    "authorized_tradable_asset",
    "market_state",
    "current_asset",
    "current_exposure",
    "effective_market_exposure",
    "model_candidate_exposure",
    "trend_permission_active",
    "current_regime",
    "execution_state",
    "trend_state",
    "trend_score",
    "next_rebalance_date",
    "metrics",
    "decision_context",
    "execution_intent",
    "source_inputs",
    "validation",
    "provenance",
]

REQUIRED_TIMESERIES_COLUMNS = [
    "date",
    "strategy_id",
    "strategy_version",
    "candidate_asset",
    "selected_asset",
    "actual_held_asset",
    "authorized_tradable_asset",
    "held_asset",
    "market_state",
    "effective_market_exposure",
    "model_candidate_exposure",
    "trend_permission_active",
    "exposure",
    "regime",
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
    "reason_code",
    "rolling_return_7d",
    "rolling_return_30d",
    "rolling_return_90d",
    "rolling_vol_30d",
    "rolling_sharpe_90d",
    "source_validated",
]

REQUIRED_DIAGNOSTICS_KEYS = [
    "artifact_type",
    "schema_version",
    "generated_at_utc",
    "strategy_id",
    "strategy_version",
    "closed_day",
    "latest_state_explanation",
    "current_flatline_explanation",
    "current_cash_or_risk_reason",
    "current_trade_state",
    "current_pain_points",
    "current_wait_condition",
    "recent_regime_changes",
    "recent_rebalance_events",
    "current_cost_pressure",
    "current_fee_drag_summary",
    "current_data_health_summary",
    "strategy_improvement_signals",
    "validation",
]


def _is_cash_like_asset(value: Any) -> bool:
    normalized = str(value or "").strip().upper()
    return normalized in CASH_EQUIVALENT_ASSETS or normalized in {"OUT_OF_MARKET", "NONE", ""}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _read_csv_required(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required CSV file: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if frame.empty:
        raise ValueError(f"CSV has no rows in {path}")
    return frame


def _normalize_iso_day_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        raise ValueError(f"{context} is not an ISO day: {value}")
    return text


def _to_float(value: Any, *, context: str) -> float:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    return float(text)


def _check_required_keys(payload: dict[str, Any], keys: list[str], *, context: str, errors: list[str]) -> None:
    for key in keys:
        if key not in payload:
            errors.append(f"{context} missing required field: {key}")


def _compare_float(actual: Any, expected: float, *, context: str, errors: list[str], tolerance: float = SUMMARY_TOLERANCE) -> None:
    try:
        actual_value = float(actual)
    except Exception:
        errors.append(f"{context} must be numeric")
        return
    if abs(actual_value - expected) > tolerance:
        errors.append(f"{context} mismatch: actual={actual_value} expected={expected}")


def _compare_text(actual: Any, expected: str, *, context: str, errors: list[str]) -> None:
    actual_text = str(actual or "").strip()
    if actual_text != expected:
        errors.append(f"{context} mismatch: actual={actual_text!r} expected={expected!r}")


def _summarize_bad_dates(mask: pd.Series, dates: pd.Series, *, limit: int = 5) -> str:
    bad_dates = dates.loc[mask.fillna(False)].astype(str).head(limit).tolist()
    return ", ".join(bad_dates)


def validate_production_payloads(
    *,
    snapshot: dict[str, Any],
    timeseries: pd.DataFrame,
    diagnostics: dict[str, Any],
    adapter: Phase68g66g1p25xCandidateAdapter,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    _check_required_keys(snapshot, REQUIRED_SNAPSHOT_KEYS, context="snapshot", errors=errors)
    _check_required_keys(diagnostics, REQUIRED_DIAGNOSTICS_KEYS, context="diagnostics", errors=errors)

    missing_columns = [column for column in REQUIRED_TIMESERIES_COLUMNS if column not in timeseries.columns]
    if missing_columns:
        errors.append(f"timeseries missing required columns: {', '.join(missing_columns)}")

    if int(snapshot.get("schema_version") or 0) != SNAPSHOT_SCHEMA_VERSION:
        errors.append(
            f"snapshot.schema_version mismatch: actual={snapshot.get('schema_version')} expected={SNAPSHOT_SCHEMA_VERSION}"
        )
    if int(diagnostics.get("schema_version") or 0) != DIAGNOSTICS_SCHEMA_VERSION:
        errors.append(
            f"diagnostics.schema_version mismatch: actual={diagnostics.get('schema_version')} expected={DIAGNOSTICS_SCHEMA_VERSION}"
        )

    _compare_text(snapshot.get("strategy_id"), PRODUCTION_STRATEGY_ID, context="snapshot.strategy_id", errors=errors)
    _compare_text(
        snapshot.get("strategy_version"),
        SOURCE_STRATEGY_VERSION,
        context="snapshot.strategy_version",
        errors=errors,
    )
    _compare_text(diagnostics.get("strategy_id"), PRODUCTION_STRATEGY_ID, context="diagnostics.strategy_id", errors=errors)
    _compare_text(
        diagnostics.get("strategy_version"),
        SOURCE_STRATEGY_VERSION,
        context="diagnostics.strategy_version",
        errors=errors,
    )

    closed_day = inputs["closed_day"]
    _compare_text(snapshot.get("closed_day"), closed_day, context="snapshot.closed_day", errors=errors)
    _compare_text(diagnostics.get("closed_day"), closed_day, context="diagnostics.closed_day", errors=errors)
    timeseries_last_day = _normalize_iso_day_text(timeseries["date"].iloc[-1], context="timeseries.last_row.date")
    _compare_text(timeseries_last_day, closed_day, context="timeseries.last_row.date", errors=errors)
    checks["source_day_alignment"] = (
        inputs["paper_last_day"] == closed_day
        and inputs["trend_status_day"] == closed_day
        and inputs["trend_history_last_day"] == closed_day
        and inputs["freshness_closed_day"] == closed_day
        and inputs["benchmark_last_day"] == closed_day
        and timeseries_last_day == closed_day
    )
    if not checks["source_day_alignment"]:
        errors.append("source closed-day alignment failed across canonical inputs and production outputs")

    checks["strategy_status_ready"] = str(snapshot.get("strategy_status") or "").strip() == "ready"
    if not checks["strategy_status_ready"]:
        errors.append("snapshot.strategy_status must be 'ready'")

    if str(snapshot.get("artifact_type") or "").strip() != "current_strategy_snapshot":
        errors.append("snapshot.artifact_type must be current_strategy_snapshot")
    if str(diagnostics.get("artifact_type") or "").strip() != "current_strategy_diagnostics":
        errors.append("diagnostics.artifact_type must be current_strategy_diagnostics")

    last_row = timeseries.iloc[-1]
    _compare_text(
        snapshot.get("candidate_asset"),
        str(last_row["candidate_asset"]),
        context="snapshot.candidate_asset",
        errors=errors,
    )
    _compare_text(
        snapshot.get("selected_asset"),
        str(last_row["selected_asset"]),
        context="snapshot.selected_asset",
        errors=errors,
    )
    _compare_text(
        snapshot.get("actual_held_asset"),
        str(last_row["actual_held_asset"]),
        context="snapshot.actual_held_asset",
        errors=errors,
    )
    _compare_text(
        snapshot.get("authorized_tradable_asset"),
        str(last_row["authorized_tradable_asset"]),
        context="snapshot.authorized_tradable_asset",
        errors=errors,
    )
    _compare_text(
        snapshot.get("market_state"),
        str(last_row["market_state"]),
        context="snapshot.market_state",
        errors=errors,
    )
    _compare_text(snapshot.get("current_asset"), str(last_row["held_asset"]), context="snapshot.current_asset", errors=errors)
    _compare_float(snapshot.get("current_exposure"), float(last_row["exposure"]), context="snapshot.current_exposure", errors=errors)
    _compare_float(
        snapshot.get("effective_market_exposure"),
        float(last_row["effective_market_exposure"]),
        context="snapshot.effective_market_exposure",
        errors=errors,
    )
    _compare_float(
        snapshot.get("model_candidate_exposure"),
        float(last_row["model_candidate_exposure"]),
        context="snapshot.model_candidate_exposure",
        errors=errors,
    )
    if bool(snapshot.get("trend_permission_active")) != bool(last_row["trend_permission_active"]):
        errors.append("snapshot.trend_permission_active mismatch between snapshot and timeseries")
    _compare_text(snapshot.get("current_regime"), str(last_row["regime"]), context="snapshot.current_regime", errors=errors)
    _compare_text(
        snapshot.get("execution_state"),
        str(last_row["execution_state"]),
        context="snapshot.execution_state",
        errors=errors,
    )
    _compare_text(snapshot.get("trend_state"), str(last_row["trend_state"]), context="snapshot.trend_state", errors=errors)
    _compare_float(snapshot.get("trend_score"), float(last_row["trend_score"]), context="snapshot.trend_score", errors=errors)

    next_rebalance_expected = str(inputs["trend_status_row"].get("next_rebalance_date") or "").strip()
    _compare_text(
        snapshot.get("next_rebalance_date"),
        next_rebalance_expected,
        context="snapshot.next_rebalance_date",
        errors=errors,
    )

    metrics = snapshot.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("snapshot.metrics must be an object")
    else:
        source_metrics = adapter.build_snapshot_metrics(inputs, timeseries)
        for field_name, expected_value in source_metrics.items():
            _compare_float(
                metrics.get(field_name),
                float(expected_value),
                context=f"snapshot.metrics.{field_name}",
                errors=errors,
                tolerance=1e-4,
            )

    summary_mismatches = adapter.compare_summary_metrics(inputs=inputs, timeseries=timeseries)
    if summary_mismatches:
        errors.extend(summary_mismatches)
    checks["summary_parity"] = not summary_mismatches

    decision_context = snapshot.get("decision_context")
    if not isinstance(decision_context, dict):
        errors.append("snapshot.decision_context must be an object")
    else:
        expected_reason_code = str(last_row["reason_code"])
        expected_reason_text = build_reason_text(last_row)
        _compare_text(
            decision_context.get("current_reason_code"),
            expected_reason_code,
            context="snapshot.decision_context.current_reason_code",
            errors=errors,
        )
        _compare_text(
            decision_context.get("current_reason_text"),
            expected_reason_text,
            context="snapshot.decision_context.current_reason_text",
            errors=errors,
        )

    execution_intent = snapshot.get("execution_intent")
    if not isinstance(execution_intent, dict):
        errors.append("snapshot.execution_intent must be an object")
    else:
        _compare_text(
            execution_intent.get("target_asset"),
            str(last_row["execution_target_asset"]),
            context="snapshot.execution_intent.target_asset",
            errors=errors,
        )
        _compare_float(
            execution_intent.get("target_exposure"),
            float(last_row["execution_target_exposure"]),
            context="snapshot.execution_intent.target_exposure",
            errors=errors,
        )
        if bool(execution_intent.get("stale_signal")):
            errors.append("snapshot.execution_intent.stale_signal must be false for a validated build")

    trend_permission_active = bool(snapshot.get("trend_permission_active"))
    current_asset = str(snapshot.get("current_asset") or "").strip().upper()
    candidate_asset = str(snapshot.get("candidate_asset") or "").strip().upper()
    effective_market_exposure = float(snapshot.get("effective_market_exposure") or 0.0)
    current_exposure = float(snapshot.get("current_exposure") or 0.0)
    model_candidate_exposure = float(snapshot.get("model_candidate_exposure") or 0.0)
    execution_target_asset = str((execution_intent or {}).get("target_asset") or "").strip().upper()
    execution_target_exposure = float((execution_intent or {}).get("target_exposure") or 0.0)
    allow_live_order_candidate = bool((execution_intent or {}).get("allow_live_order_candidate"))

    checks["candidate_asset_separated_from_actual_exposure"] = (
        not trend_permission_active
        and candidate_asset not in CASH_EQUIVALENT_ASSETS
        and _is_cash_like_asset(current_asset)
        and _is_cash_like_asset(execution_target_asset)
        and effective_market_exposure <= SUMMARY_TOLERANCE
    ) or trend_permission_active
    checks["trend_permission_blocks_market_exposure"] = (
        trend_permission_active or effective_market_exposure <= SUMMARY_TOLERANCE
    )
    checks["trend_permission_blocks_execution_target"] = (
        trend_permission_active
        or (_is_cash_like_asset(execution_target_asset) and execution_target_exposure <= SUMMARY_TOLERANCE)
    )
    if not checks["trend_permission_blocks_market_exposure"]:
        errors.append("trend_permission_active=false but effective_market_exposure is above zero")
    if not checks["trend_permission_blocks_execution_target"]:
        errors.append("trend_permission_active=false but execution_intent target is not CASH/0.0")
    if not trend_permission_active and not _is_cash_like_asset(current_asset):
        errors.append("trend_permission_active=false but current_asset is not CASH")
    if not trend_permission_active and current_exposure > SUMMARY_TOLERANCE:
        errors.append("trend_permission_active=false but current_exposure is above zero")
    if effective_market_exposure <= SUMMARY_TOLERANCE and not _is_cash_like_asset(current_asset):
        errors.append("effective_market_exposure is zero but current_asset is not CASH")
    if effective_market_exposure > SUMMARY_TOLERANCE and _is_cash_like_asset(current_asset):
        errors.append("effective_market_exposure is above zero but current_asset is CASH")
    if not trend_permission_active and candidate_asset == current_asset and not _is_cash_like_asset(candidate_asset):
        errors.append("candidate asset is incorrectly mixed into current_asset while trend permission is inactive")
    if not trend_permission_active and allow_live_order_candidate:
        errors.append("trend_permission_active=false but allow_live_order_candidate is true")
    if trend_permission_active and execution_target_exposure <= SUMMARY_TOLERANCE:
        errors.append("trend_permission_active=true but execution target exposure is zero")
    if trend_permission_active and _is_cash_like_asset(execution_target_asset):
        errors.append("trend_permission_active=true but execution target asset is CASH")
    if model_candidate_exposure < effective_market_exposure - SUMMARY_TOLERANCE:
        errors.append("model_candidate_exposure must be greater than or equal to effective_market_exposure")

    primary_return_gross = pd.to_numeric(timeseries["return_gross"], errors="coerce").fillna(0.0)
    primary_return_net = pd.to_numeric(timeseries["return_net"], errors="coerce").fillna(0.0)
    primary_equity = pd.to_numeric(timeseries["equity"], errors="coerce")
    authorized_return_gross = pd.to_numeric(timeseries["authorized_return_gross"], errors="coerce").fillna(0.0)
    authorized_return_net = pd.to_numeric(timeseries["authorized_return_net"], errors="coerce").fillna(0.0)
    authorized_equity = pd.to_numeric(timeseries["authorized_equity"], errors="coerce")
    btc_close = pd.to_numeric(timeseries["btc_close"], errors="coerce")
    btc_return = pd.to_numeric(timeseries["btc_return"], errors="coerce").fillna(0.0)
    btc_baseline_equity = pd.to_numeric(timeseries["btc_baseline_equity"], errors="coerce")
    btc_baseline_index = pd.to_numeric(timeseries["btc_baseline_index"], errors="coerce")
    model_candidate_return_net = pd.to_numeric(
        timeseries["model_candidate_return_net"],
        errors="coerce",
    ).fillna(0.0)
    model_candidate_equity = pd.to_numeric(timeseries["model_candidate_equity"], errors="coerce")
    effective_exposure_series = pd.to_numeric(
        timeseries["effective_market_exposure"],
        errors="coerce",
    ).fillna(0.0)
    transition_mask = timeseries["asset_transition_day"].fillna(False).astype(bool)
    daily_costs = (
        pd.to_numeric(timeseries["fees_daily"], errors="coerce").fillna(0.0)
        + pd.to_numeric(timeseries["funding_daily"], errors="coerce").fillna(0.0)
        + pd.to_numeric(timeseries["borrow_cost_daily"], errors="coerce").fillna(0.0)
        + pd.to_numeric(timeseries["slippage_cost_daily"], errors="coerce").fillna(0.0)
    )
    out_of_market_mask = effective_exposure_series.abs() <= SUMMARY_TOLERANCE
    equity_delta = authorized_equity.diff().fillna(0.0)
    row_dates = timeseries["date"].astype(str)

    primary_gross_mismatch = (primary_return_gross - authorized_return_gross).abs() > SUMMARY_TOLERANCE
    primary_net_mismatch = (primary_return_net - authorized_return_net).abs() > SUMMARY_TOLERANCE
    primary_equity_mismatch = (primary_equity - authorized_equity).abs() > SUMMARY_TOLERANCE
    if primary_gross_mismatch.any():
        errors.append(
            "timeseries.return_gross must equal authorized_return_gross on every row "
            f"(examples: {_summarize_bad_dates(primary_gross_mismatch, row_dates)})"
        )
    if primary_net_mismatch.any():
        errors.append(
            "timeseries.return_net must equal authorized_return_net on every row "
            f"(examples: {_summarize_bad_dates(primary_net_mismatch, row_dates)})"
        )
    if primary_equity_mismatch.any():
        errors.append(
            "timeseries.equity must equal authorized_equity on every row "
            f"(examples: {_summarize_bad_dates(primary_equity_mismatch, row_dates)})"
        )

    candidate_equity_leak = primary_equity_mismatch & (
        (primary_equity - model_candidate_equity).abs() <= SUMMARY_TOLERANCE
    )
    candidate_return_leak = primary_net_mismatch & (
        (primary_return_net - model_candidate_return_net).abs() <= SUMMARY_TOLERANCE
    )
    if candidate_equity_leak.any() or candidate_return_leak.any():
        errors.append(
            "model/candidate equity semantics leaked into primary production fields "
            f"(examples: {_summarize_bad_dates(candidate_equity_leak | candidate_return_leak, row_dates)})"
        )

    out_of_market_gross_move = out_of_market_mask & (authorized_return_gross.abs() > SUMMARY_TOLERANCE)
    if out_of_market_gross_move.any():
        errors.append(
            "effective_market_exposure=0.0 but authorized gross return is nonzero "
            f"(examples: {_summarize_bad_dates(out_of_market_gross_move, row_dates)})"
        )

    out_of_market_non_transition_cost = out_of_market_mask & (~transition_mask) & (
        daily_costs.abs() > SUMMARY_TOLERANCE
    )
    if out_of_market_non_transition_cost.any():
        errors.append(
            "effective_market_exposure=0.0 but costs appear on non-transition rows "
            f"(examples: {_summarize_bad_dates(out_of_market_non_transition_cost, row_dates)})"
        )

    out_of_market_non_transition_net_move = out_of_market_mask & (~transition_mask) & (
        authorized_return_net.abs() > SUMMARY_TOLERANCE
    )
    if out_of_market_non_transition_net_move.any():
        errors.append(
            "effective_market_exposure=0.0 but authorized net return is nonzero on non-transition rows "
            f"(examples: {_summarize_bad_dates(out_of_market_non_transition_net_move, row_dates)})"
        )

    out_of_market_non_transition_equity_move = out_of_market_mask & (~transition_mask) & (
        equity_delta.abs() > SUMMARY_TOLERANCE
    )
    if out_of_market_non_transition_equity_move.any():
        errors.append(
            "effective_market_exposure=0.0 but authorized equity changes on non-transition rows "
            f"(examples: {_summarize_bad_dates(out_of_market_non_transition_equity_move, row_dates)})"
        )

    out_of_market_transition_net_mismatch = out_of_market_mask & transition_mask & (
        (authorized_return_net + daily_costs).abs() > SUMMARY_TOLERANCE
    )
    if out_of_market_transition_net_mismatch.any():
        errors.append(
            "out-of-market transition rows must only move by explicit modeled costs "
            f"(examples: {_summarize_bad_dates(out_of_market_transition_net_mismatch, row_dates)})"
        )

    reconstructed_authorized_equity = (1.0 + authorized_return_net).cumprod()
    authorized_equity_curve_mismatch = (
        reconstructed_authorized_equity - authorized_equity
    ).abs() > SUMMARY_TOLERANCE
    if authorized_equity_curve_mismatch.any():
        errors.append(
            "authorized_equity must equal the cumulative authorized_return_net curve "
            f"(examples: {_summarize_bad_dates(authorized_equity_curve_mismatch, row_dates)})"
        )

    if btc_close.isna().any():
        errors.append(
            "btc_close must be numeric on every row "
            f"(examples: {_summarize_bad_dates(btc_close.isna(), row_dates)})"
        )
    elif (btc_close <= 0).any():
        errors.append(
            "btc_close must stay strictly positive "
            f"(examples: {_summarize_bad_dates(btc_close <= 0, row_dates)})"
        )

    if btc_baseline_equity.isna().any():
        errors.append(
            "btc_baseline_equity must be numeric on every row "
            f"(examples: {_summarize_bad_dates(btc_baseline_equity.isna(), row_dates)})"
        )
    if btc_baseline_index.isna().any():
        errors.append(
            "btc_baseline_index must be numeric on every row "
            f"(examples: {_summarize_bad_dates(btc_baseline_index.isna(), row_dates)})"
        )
    if not btc_close.isna().any():
        reconstructed_btc_return = btc_close.pct_change().fillna(0.0)
        btc_return_mismatch = (reconstructed_btc_return - btc_return).abs() > SUMMARY_TOLERANCE
        if btc_return_mismatch.any():
            errors.append(
                "btc_return must match close-to-close BTC benchmark moves "
                f"(examples: {_summarize_bad_dates(btc_return_mismatch, row_dates)})"
            )
        reconstructed_btc_baseline_equity = (1.0 + btc_return).cumprod()
        btc_equity_mismatch = (
            reconstructed_btc_baseline_equity - btc_baseline_equity
        ).abs() > SUMMARY_TOLERANCE
        if btc_equity_mismatch.any():
            errors.append(
                "btc_baseline_equity must equal the cumulative btc_return curve "
                f"(examples: {_summarize_bad_dates(btc_equity_mismatch, row_dates)})"
            )
        btc_index_mismatch = (
            (btc_baseline_equity * 100.0) - btc_baseline_index
        ).abs() > SUMMARY_TOLERANCE
        if btc_index_mismatch.any():
            errors.append(
                "btc_baseline_index must equal btc_baseline_equity * 100 "
                f"(examples: {_summarize_bad_dates(btc_index_mismatch, row_dates)})"
            )

    checks["primary_series_use_authorized_equity_semantics"] = not (
        primary_gross_mismatch.any()
        or primary_net_mismatch.any()
        or primary_equity_mismatch.any()
    )
    checks["out_of_market_rows_have_zero_authorized_gross_return"] = not out_of_market_gross_move.any()
    checks["out_of_market_rows_only_move_on_transition_costs"] = not (
        out_of_market_non_transition_cost.any()
        or out_of_market_non_transition_net_move.any()
        or out_of_market_non_transition_equity_move.any()
        or out_of_market_transition_net_mismatch.any()
    )
    checks["authorized_equity_curve_reconstructs_from_returns"] = not authorized_equity_curve_mismatch.any()
    checks["btc_baseline_reconstructs_from_close_series"] = not (
        btc_close.isna().any()
        or (btc_close <= 0).any()
        or btc_baseline_equity.isna().any()
        or btc_baseline_index.isna().any()
        or ((btc_close.pct_change().fillna(0.0) - btc_return).abs() > SUMMARY_TOLERANCE).any()
        or (((1.0 + btc_return).cumprod() - btc_baseline_equity).abs() > SUMMARY_TOLERANCE).any()
        or ((((btc_baseline_equity * 100.0) - btc_baseline_index).abs()) > SUMMARY_TOLERANCE).any()
    )

    expected_source_inputs = adapter.build_source_inputs(inputs)
    source_inputs = snapshot.get("source_inputs")
    if not isinstance(source_inputs, dict):
        errors.append("snapshot.source_inputs must be an object")
    else:
        current_files = source_inputs.get("files")
        expected_files = expected_source_inputs["files"]
        if not isinstance(current_files, dict):
            errors.append("snapshot.source_inputs.files must be an object")
        else:
            for key, expected_file_meta in expected_files.items():
                actual_file_meta = current_files.get(key)
                if not isinstance(actual_file_meta, dict):
                    errors.append(f"snapshot.source_inputs.files.{key} must be an object")
                    continue
                _compare_text(
                    actual_file_meta.get("path"),
                    expected_file_meta["path"],
                    context=f"snapshot.source_inputs.files.{key}.path",
                    errors=errors,
                )
                _compare_text(
                    actual_file_meta.get("sha256"),
                    expected_file_meta["sha256"],
                    context=f"snapshot.source_inputs.files.{key}.sha256",
                    errors=errors,
                )
                if "last_date" in expected_file_meta:
                    _compare_text(
                        actual_file_meta.get("last_date"),
                        expected_file_meta["last_date"],
                        context=f"snapshot.source_inputs.files.{key}.last_date",
                        errors=errors,
                    )

    trade_state = diagnostics.get("current_trade_state")
    if not isinstance(trade_state, dict):
        errors.append("diagnostics.current_trade_state must be an object")
    else:
        _compare_text(
            trade_state.get("candidate_asset"),
            candidate_asset,
            context="diagnostics.current_trade_state.candidate_asset",
            errors=errors,
        )
        _compare_text(
            trade_state.get("actual_held_asset"),
            current_asset,
            context="diagnostics.current_trade_state.actual_held_asset",
            errors=errors,
        )
        _compare_float(
            trade_state.get("effective_market_exposure"),
            effective_market_exposure,
            context="diagnostics.current_trade_state.effective_market_exposure",
            errors=errors,
        )
        _compare_float(
            trade_state.get("model_candidate_exposure"),
            model_candidate_exposure,
            context="diagnostics.current_trade_state.model_candidate_exposure",
            errors=errors,
        )
        if bool(trade_state.get("trend_permission_active")) != trend_permission_active:
            errors.append("diagnostics.current_trade_state.trend_permission_active mismatch")
        _compare_text(
            trade_state.get("waiting_reason_code"),
            str(last_row["reason_code"]),
            context="diagnostics.current_trade_state.waiting_reason_code",
            errors=errors,
        )
        _compare_text(
            trade_state.get("waiting_reason_text"),
            build_reason_text(last_row),
            context="diagnostics.current_trade_state.waiting_reason_text",
            errors=errors,
        )
        if not isinstance(trade_state.get("pain_points"), list):
            errors.append("diagnostics.current_trade_state.pain_points must be a list")

    current_pain_points = diagnostics.get("current_pain_points")
    if not isinstance(current_pain_points, list):
        errors.append("diagnostics.current_pain_points must be a list")
    current_wait_condition = diagnostics.get("current_wait_condition")
    if not isinstance(current_wait_condition, dict):
        errors.append("diagnostics.current_wait_condition must be an object")

    diagnostics_validation = diagnostics.get("validation")
    if not isinstance(diagnostics_validation, dict):
        errors.append("diagnostics.validation must be an object")

    current_data_health_summary = diagnostics.get("current_data_health_summary")
    if not isinstance(current_data_health_summary, dict):
        errors.append("diagnostics.current_data_health_summary must be an object")
    else:
        _compare_text(
            current_data_health_summary.get("closed_day"),
            closed_day,
            context="diagnostics.current_data_health_summary.closed_day",
            errors=errors,
        )

    status = "passed" if not errors else "failed"
    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def build_quality_payload(
    *,
    validation: dict[str, Any],
    snapshot_path: Path,
    timeseries_path: Path,
    diagnostics_path: Path,
) -> dict[str, Any]:
    return {
        "artifact_type": "current_strategy_snapshot_quality",
        "schema_version": QUALITY_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "status": validation["status"],
        "error_count": len(validation["errors"]),
        "warning_count": len(validation["warnings"]),
        "errors": list(validation["errors"]),
        "warnings": list(validation["warnings"]),
        "checks": dict(validation["checks"]),
        "validated_paths": {
            "snapshot_path": str(snapshot_path.resolve()),
            "timeseries_path": str(timeseries_path.resolve()),
            "diagnostics_path": str(diagnostics_path.resolve()),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed validator for Production Core v1 current strategy outputs.")
    parser.add_argument("--snapshot-path", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--timeseries-path", type=Path, default=DEFAULT_TIMESERIES_PATH)
    parser.add_argument("--diagnostics-path", type=Path, default=DEFAULT_DIAGNOSTICS_PATH)
    parser.add_argument("--quality-path", type=Path, default=DEFAULT_QUALITY_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    adapter = Phase68g66g1p25xCandidateAdapter()
    snapshot = _read_json_required(args.snapshot_path)
    timeseries = _read_csv_required(args.timeseries_path)
    diagnostics = _read_json_required(args.diagnostics_path)
    inputs = adapter.load_inputs(root=ROOT)
    validation = validate_production_payloads(
        snapshot=snapshot,
        timeseries=timeseries,
        diagnostics=diagnostics,
        adapter=adapter,
        inputs=inputs,
    )
    quality = build_quality_payload(
        validation=validation,
        snapshot_path=args.snapshot_path,
        timeseries_path=args.timeseries_path,
        diagnostics_path=args.diagnostics_path,
    )
    args.quality_path.parent.mkdir(parents=True, exist_ok=True)
    args.quality_path.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(quality, indent=2, ensure_ascii=False))
    if validation["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
