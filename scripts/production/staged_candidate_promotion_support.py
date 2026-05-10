from __future__ import annotations

import hashlib
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
    MANIFEST_SCHEMA_VERSION,
    PRODUCTION_STRATEGY_ID,
    QUALITY_SCHEMA_VERSION,
    ROOT,
    SNAPSHOT_SCHEMA_VERSION,
    SUMMARY_TOLERANCE,
)
from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import (
    CANDIDATE_ID as PROMOTED_CANDIDATE_ID,
)


PROMOTED_CANDIDATE_DIR = (
    ROOT / "outputs" / "production" / "candidates" / PROMOTED_CANDIDATE_ID
)
PROMOTED_CANDIDATE_SNAPSHOT_PATH = PROMOTED_CANDIDATE_DIR / "candidate_strategy_snapshot.json"
PROMOTED_CANDIDATE_TIMESERIES_PATH = PROMOTED_CANDIDATE_DIR / "candidate_strategy_timeseries.csv"
PROMOTED_CANDIDATE_DIAGNOSTICS_PATH = PROMOTED_CANDIDATE_DIR / "candidate_strategy_diagnostics.json"
PROMOTED_CANDIDATE_QUALITY_PATH = PROMOTED_CANDIDATE_DIR / "candidate_strategy_snapshot.quality.json"
PROMOTED_CANDIDATE_MANIFEST_PATH = PROMOTED_CANDIDATE_DIR / "candidate_strategy_snapshot.manifest.json"
PROMOTED_CANDIDATE_COMPARE_JSON_PATH = PROMOTED_CANDIDATE_DIR / "compare_vs_current_production_core.json"
PROMOTED_CANDIDATE_COMPARE_CSV_PATH = PROMOTED_CANDIDATE_DIR / "compare_vs_current_production_core.csv"

PROMOTION_ADAPTER_NAME = "promoted_staged_strategy_candidate"

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
    "early_risk_active",
    "cooldown_blocked_entry",
    "etf_flow_feature_available",
    "etf_flow_evidence_window",
    "etf_flow_rule_active",
    "etf_flow_causal_date_available",
    "rolling_return_7d",
    "rolling_return_30d",
    "rolling_return_90d",
    "rolling_vol_30d",
    "rolling_sharpe_90d",
    "source_validated",
]

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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_for_manifest(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _source_file_metadata(
    path: Path,
    *,
    last_date: str | None = None,
    row_count: int | None = None,
) -> dict[str, Any]:
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


def _normalize_iso_day_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        raise ValueError(f"{context} is not an ISO day: {value}")
    return text


def _to_float_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _to_bool_series(series: pd.Series) -> pd.Series:
    lowered = series.fillna("").astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y"})


def _is_cash_like_asset(value: Any) -> bool:
    normalized = str(value or "").strip().upper()
    return normalized in CASH_EQUIVALENT_ASSETS or normalized in {"OUT_OF_MARKET", "NONE", ""}


def _rolling_compound_return(series: pd.Series, window: int) -> pd.Series:
    return (
        (1.0 + _to_float_series(series))
        .rolling(window=window, min_periods=window)
        .apply(lambda values: values.prod(), raw=True)
        - 1.0
    )


def _rolling_sharpe(series: pd.Series, window: int) -> pd.Series:
    clean = _to_float_series(series)
    mean = clean.rolling(window=window, min_periods=window).mean()
    std = clean.rolling(window=window, min_periods=window).std(ddof=0)
    sharpe = (mean / std.replace(0.0, float("nan"))) * (365.25 ** 0.5)
    return sharpe.replace([float("inf"), float("-inf")], float("nan"))


def _compute_total_return_pct(series: pd.Series) -> float:
    curve = (1.0 + _to_float_series(series)).cumprod()
    if curve.empty:
        return 0.0
    return float((curve.iloc[-1] - 1.0) * 100.0)


def _compute_cagr_pct(series: pd.Series, dates: pd.Series) -> float:
    clean_returns = _to_float_series(series)
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
    curve = (1.0 + _to_float_series(series)).cumprod()
    if curve.empty:
        return 0.0
    drawdown = (curve / curve.cummax()) - 1.0
    return float(drawdown.min() * 100.0)


def _annualized_sharpe_from_daily_returns(series: pd.Series) -> float | None:
    daily_returns = _to_float_series(series).dropna().tolist()
    if len(daily_returns) < 2:
        return None
    mean_ret = sum(daily_returns) / len(daily_returns)
    variance = sum((value - mean_ret) ** 2 for value in daily_returns) / (len(daily_returns) - 1)
    if variance <= 0:
        return None
    std = variance ** 0.5
    if std == 0:
        return None
    return (mean_ret / std) * (365.0 ** 0.5)


def _annualized_sortino_from_daily_returns(series: pd.Series) -> float | None:
    daily_returns = _to_float_series(series).dropna().tolist()
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
    downside_std = downside_variance ** 0.5
    if downside_std == 0:
        return None
    return (mean_ret / downside_std) * (365.0 ** 0.5)


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


def _check_required_keys(payload: dict[str, Any], keys: list[str], *, context: str, errors: list[str]) -> None:
    for key in keys:
        if key not in payload:
            errors.append(f"{context} missing required field: {key}")


def _compare_text(actual: Any, expected: str, *, context: str, errors: list[str]) -> None:
    actual_text = str(actual or "").strip()
    if actual_text != expected:
        errors.append(f"{context} mismatch: actual={actual_text!r} expected={expected!r}")


def _compare_float(
    actual: Any,
    expected: float,
    *,
    context: str,
    errors: list[str],
    tolerance: float = SUMMARY_TOLERANCE,
) -> None:
    try:
        actual_value = float(actual)
    except Exception:
        errors.append(f"{context} must be numeric")
        return
    if abs(actual_value - expected) > tolerance:
        errors.append(f"{context} mismatch: actual={actual_value} expected={expected}")


def _summarize_bad_dates(mask: pd.Series, dates: pd.Series, *, limit: int = 5) -> str:
    bad_dates = dates.loc[mask.fillna(False)].astype(str).head(limit).tolist()
    return ", ".join(bad_dates)


def load_promoted_candidate_inputs(
    *,
    root: Path | None = None,
    candidate_id: str = PROMOTED_CANDIDATE_ID,
) -> dict[str, Any]:
    repo_root = (root or ROOT).resolve()
    if candidate_id != PROMOTED_CANDIDATE_ID:
        raise ValueError(f"Unsupported promoted candidate: {candidate_id!r}")

    bundle_dir = repo_root / "outputs" / "production" / "candidates" / candidate_id
    paths = {
        "snapshot": bundle_dir / "candidate_strategy_snapshot.json",
        "timeseries": bundle_dir / "candidate_strategy_timeseries.csv",
        "diagnostics": bundle_dir / "candidate_strategy_diagnostics.json",
        "quality": bundle_dir / "candidate_strategy_snapshot.quality.json",
        "manifest": bundle_dir / "candidate_strategy_snapshot.manifest.json",
        "compare_json": bundle_dir / "compare_vs_current_production_core.json",
        "compare_csv": bundle_dir / "compare_vs_current_production_core.csv",
    }

    snapshot = _read_json_required(paths["snapshot"])
    timeseries = _read_csv_required(paths["timeseries"])
    diagnostics = _read_json_required(paths["diagnostics"])
    quality = _read_json_required(paths["quality"])
    manifest = _read_json_required(paths["manifest"])
    compare_json = _read_json_required(paths["compare_json"])
    compare_csv = _read_csv_required(paths["compare_csv"])

    closed_day = _normalize_iso_day_text(snapshot.get("closed_day"), context="candidate_snapshot.closed_day")
    timeseries_last_day = _normalize_iso_day_text(
        timeseries["date"].iloc[-1],
        context="candidate_timeseries.last_row.date",
    )
    diagnostics_closed_day = _normalize_iso_day_text(
        diagnostics.get("closed_day"),
        context="candidate_diagnostics.closed_day",
    )
    if timeseries_last_day != closed_day:
        raise ValueError(
            "Candidate timeseries last date does not match candidate snapshot closed_day "
            f"(actual={timeseries_last_day} expected={closed_day})"
        )
    if diagnostics_closed_day != closed_day:
        raise ValueError(
            "Candidate diagnostics closed_day does not match candidate snapshot closed_day "
            f"(actual={diagnostics_closed_day} expected={closed_day})"
        )
    if str(quality.get("status") or "").strip() != "passed":
        raise ValueError("Candidate quality status must be passed before promotion")
    if str(manifest.get("validation_status") or "").strip() != "passed":
        raise ValueError("Candidate manifest validation_status must be passed before promotion")

    return {
        "repo_root": repo_root,
        "bundle_dir": bundle_dir,
        "paths": paths,
        "snapshot": snapshot,
        "timeseries": timeseries,
        "diagnostics": diagnostics,
        "quality": quality,
        "manifest": manifest,
        "compare_json": compare_json,
        "compare_csv": compare_csv,
        "closed_day": closed_day,
        "timeseries_last_day": timeseries_last_day,
    }


def transform_candidate_timeseries_to_active(candidate_timeseries: pd.DataFrame) -> pd.DataFrame:
    source = candidate_timeseries.copy()
    active = pd.DataFrame(index=source.index)
    active["date"] = source["date"].astype(str)
    active["strategy_id"] = PRODUCTION_STRATEGY_ID
    active["strategy_version"] = PROMOTED_CANDIDATE_ID
    active["candidate_asset"] = source["candidate_asset"].astype(str)
    active["selected_asset"] = source["selected_asset"].astype(str)
    active["model_candidate_exposure"] = _to_float_series(source["model_candidate_exposure"]).round(12)
    active["trend_permission_active"] = _to_bool_series(source["trend_permission_active"])
    active["actual_held_asset"] = source["actual_held_asset"].astype(str)
    active["authorized_tradable_asset"] = source["authorized_tradable_asset"].astype(str)
    active["held_asset"] = source["held_asset"].astype(str)
    active["current_asset"] = source["current_asset"].astype(str)
    active["effective_market_exposure"] = _to_float_series(source["effective_market_exposure"]).round(12)
    active["current_exposure"] = _to_float_series(source["current_exposure"]).round(12)
    active["exposure"] = _to_float_series(source["exposure"]).round(12)
    active["regime"] = source["regime"].astype(str)
    active["market_state"] = source["market_state"].astype(str)
    active["execution_state"] = source["execution_state"].astype(str)
    active["execution_target_asset"] = source["execution_target_asset"].astype(str)
    active["execution_target_exposure"] = _to_float_series(source["execution_target_exposure"]).round(12)
    active["trend_state"] = source["trend_state"].astype(str)
    active["trend_score"] = _to_float_series(source["trend_score"]).round(12)
    active["buy_threshold"] = _to_float_series(source["buy_threshold"]).round(12)
    model_candidate_return_gross = _to_float_series(source["model_candidate_return_gross"]).round(12)
    model_candidate_return_net = _to_float_series(source["model_candidate_return_net"]).round(12)
    authorized_return_gross = _to_float_series(source["authorized_return_gross"]).round(12)
    authorized_return_net = _to_float_series(source["authorized_return_net"]).round(12)
    active["model_candidate_equity"] = ((1.0 + model_candidate_return_net).cumprod()).round(12)
    active["authorized_equity"] = ((1.0 + authorized_return_net).cumprod()).round(12)
    active["btc_close"] = _to_float_series(source["btc_close"]).round(12)
    active["fees_daily"] = _to_float_series(source["fees_daily"]).round(12)
    active["funding_daily"] = _to_float_series(source["funding_daily"]).round(12)
    active["borrow_cost_daily"] = _to_float_series(source["borrow_cost_daily"]).round(12)
    active["slippage_cost_daily"] = _to_float_series(source["slippage_cost_daily"]).round(12)
    active["turnover"] = _to_float_series(source["turnover"]).round(12)
    active["cash_day"] = _to_bool_series(source["cash_day"])
    active["btc_day"] = _to_bool_series(source["btc_day"])
    active["in_market"] = _to_bool_series(source["in_market"])
    active["is_rebalance_day"] = _to_bool_series(source["is_rebalance_day"])
    active["asset_transition_day"] = _to_bool_series(source["asset_transition_day"])
    active["trend_block_day"] = _to_bool_series(source["trend_block_day"])
    active["stress_block_day"] = _to_bool_series(source["stress_block_day"])
    active["trend_gate_pass"] = _to_bool_series(source["trend_gate_pass"])
    active["leverage_active"] = _to_bool_series(source["leverage_active"])
    active["leverage_state_reason"] = source["leverage_state_reason"].astype(str)
    active["trend_activation_threshold"] = _to_float_series(source["trend_activation_threshold"]).round(12)
    active["reason_code"] = source["reason_code"].astype(str)
    active["early_risk_active"] = _to_bool_series(
        source.get("early_risk_active", pd.Series(False, index=source.index))
    )
    active["cooldown_blocked_entry"] = _to_bool_series(
        source.get("cooldown_blocked_entry", pd.Series(False, index=source.index))
    )
    active["etf_flow_feature_available"] = _to_bool_series(
        source.get("etf_flow_feature_available", pd.Series(False, index=source.index))
    )
    active["etf_flow_evidence_window"] = _to_bool_series(
        source.get("etf_flow_evidence_window", pd.Series(False, index=source.index))
    )
    active["etf_flow_rule_active"] = _to_bool_series(
        source.get("etf_flow_rule_active", pd.Series(False, index=source.index))
    )
    active["etf_flow_causal_date_available"] = (
        source.get("etf_flow_causal_date_available", pd.Series("", index=source.index))
        .fillna("")
        .astype(str)
    )
    active["source_validated"] = _to_bool_series(source["source_validated"])

    active["fees_cumulative"] = active["fees_daily"].cumsum().round(12)
    active["funding_cumulative"] = active["funding_daily"].cumsum().round(12)
    active["borrow_cost_cumulative"] = active["borrow_cost_daily"].cumsum().round(12)
    active["slippage_cost_cumulative"] = active["slippage_cost_daily"].cumsum().round(12)

    active["model_candidate_return_net"] = model_candidate_return_net
    active["model_candidate_return_gross"] = model_candidate_return_gross
    active["authorized_return_net"] = authorized_return_net
    active["authorized_return_gross"] = authorized_return_gross
    active["return_gross"] = active["authorized_return_gross"]
    active["return_net"] = active["authorized_return_net"]
    active["equity"] = active["authorized_equity"]
    active["drawdown_pct"] = (
        ((active["equity"] / active["equity"].cummax()) - 1.0) * 100.0
    ).round(12)

    active["btc_return"] = active["btc_close"].pct_change().fillna(0.0).round(12)
    active["btc_baseline_equity"] = (1.0 + active["btc_return"]).cumprod().round(12)
    active["btc_baseline_index"] = (active["btc_baseline_equity"] * 100.0).round(12)

    active["rolling_return_7d"] = _rolling_compound_return(active["return_net"], 7).round(12)
    active["rolling_return_30d"] = _rolling_compound_return(active["return_net"], 30).round(12)
    active["rolling_return_90d"] = _rolling_compound_return(active["return_net"], 90).round(12)
    active["rolling_vol_30d"] = (
        _to_float_series(active["return_net"]).rolling(window=30, min_periods=30).std(ddof=0) * (365.25 ** 0.5)
    ).round(12)
    active["rolling_sharpe_90d"] = _rolling_sharpe(active["return_net"], 90).round(12)
    return active.loc[:, ACTIVE_TIMESERIES_COLUMNS]


def build_promoted_reason_text(row: pd.Series) -> str:
    reason_code = str(row.get("reason_code") or "").strip()
    candidate_asset = str(row.get("candidate_asset") or "CASH").strip().upper() or "CASH"
    actual_asset = str(row.get("actual_held_asset", row.get("held_asset")) or "CASH").strip().upper() or "CASH"
    exposure = float(row.get("effective_market_exposure", row.get("exposure", 0.0)) or 0.0)

    if reason_code == "early_risk_etf_flow_impulse":
        return (
            f"The active Production Core takes {actual_asset} at {exposure:.2f}x because the ETF-flow "
            "EARLY_RISK permission is active."
        )
    if reason_code == "early_risk_cooldown_block":
        return (
            "ETF-flow EARLY_RISK permission is active, but the active Production Core stays in CASH "
            "because the 15-day cooldown still blocks a new entry."
        )
    if reason_code == "early_risk_permission_vetoed":
        return (
            f"{candidate_asset} is the current candidate, but the ETF-flow EARLY_RISK entry veto remains "
            "active, so the active Production Core stays in CASH."
        )
    if reason_code == "baseline_full_risk_pass_through":
        return (
            f"The active Production Core passes through the baseline FULL_RISK row unchanged, so authorized "
            f"exposure remains {actual_asset} at {exposure:.2f}x."
        )
    if actual_asset in CASH_EQUIVALENT_ASSETS:
        return (
            "The active Production Core remains in CASH because neither the baseline FULL_RISK state nor "
            "the ETF-flow EARLY_RISK entry conditions authorize market exposure."
        )
    if bool(row.get("is_rebalance_day")) and actual_asset in CASH_EQUIVALENT_ASSETS:
        return "The active Production Core rebalanced into CASH on the latest closed day."
    if bool(row.get("is_rebalance_day")):
        return f"The active Production Core rebalanced into {actual_asset} on the latest closed day."
    return f"The active Production Core holds {actual_asset} with authorized exposure at {exposure:.2f}x."


def build_promoted_wait_condition(current_row: pd.Series) -> dict[str, Any]:
    candidate_asset = str(current_row.get("candidate_asset") or "CASH").strip().upper() or "CASH"
    actual_asset = str(current_row.get("actual_held_asset", current_row.get("held_asset")) or "CASH").strip().upper() or "CASH"
    effective_market_exposure = float(current_row.get("effective_market_exposure", 0.0) or 0.0)
    model_candidate_exposure = float(current_row.get("model_candidate_exposure", 0.0) or 0.0)
    execution_target_asset = str(current_row.get("execution_target_asset") or "CASH").strip().upper() or "CASH"
    execution_target_exposure = float(current_row.get("execution_target_exposure", 0.0) or 0.0)
    reason_code = str(current_row.get("reason_code") or "").strip()

    if reason_code == "early_risk_cooldown_block":
        return {
            "code": "cooldown_clearance_pending_for_candidate_entry",
            "text": (
                "ETF-flow EARLY_RISK permission is active, but the active Production Core stays in CASH "
                "because the 15-day cooldown still blocks a new entry."
            ),
            "current_values": {
                "candidate_asset": candidate_asset,
                "actual_held_asset": actual_asset,
                "effective_market_exposure": effective_market_exposure,
                "model_candidate_exposure": model_candidate_exposure,
                "execution_target_asset": execution_target_asset,
                "execution_target_exposure": execution_target_exposure,
            },
            "target_condition": {
                "cooldown_active": False,
                "execution_target_asset": candidate_asset,
                "execution_target_exposure": model_candidate_exposure,
            },
        }
    if reason_code == "early_risk_permission_vetoed":
        return {
            "code": "etf_flow_permission_veto_active",
            "text": (
                f"{candidate_asset} is the current candidate, but the ETF-flow EARLY_RISK entry veto remains "
                "active, so the active Production Core stays in CASH."
            ),
            "current_values": {
                "candidate_asset": candidate_asset,
                "actual_held_asset": actual_asset,
                "effective_market_exposure": effective_market_exposure,
                "model_candidate_exposure": model_candidate_exposure,
            },
            "target_condition": {
                "permission_on": True,
                "execution_target_asset": candidate_asset,
                "execution_target_exposure": model_candidate_exposure,
            },
        }
    if actual_asset in CASH_EQUIVALENT_ASSETS and candidate_asset not in CASH_EQUIVALENT_ASSETS:
        return {
            "code": "candidate_entry_not_authorized",
            "text": build_promoted_reason_text(current_row),
            "current_values": {
                "candidate_asset": candidate_asset,
                "actual_held_asset": actual_asset,
                "effective_market_exposure": effective_market_exposure,
                "model_candidate_exposure": model_candidate_exposure,
            },
            "target_condition": {
                "execution_target_asset": candidate_asset,
                "execution_target_exposure": model_candidate_exposure,
            },
        }
    return {
        "code": "already_in_target_state",
        "text": f"The active Production Core is already in its current authorized state for {actual_asset}.",
        "current_values": {
            "candidate_asset": candidate_asset,
            "actual_held_asset": actual_asset,
            "effective_market_exposure": effective_market_exposure,
        },
        "target_condition": {
            "next_rebalance_date": None,
        },
    }


def build_promoted_snapshot_metrics(timeseries: pd.DataFrame) -> dict[str, Any]:
    dates = pd.to_datetime(timeseries["date"], errors="coerce")
    return_net = _to_float_series(timeseries["return_net"])
    sharpe = _annualized_sharpe_from_daily_returns(return_net)
    sortino = _annualized_sortino_from_daily_returns(return_net)
    if sharpe is None or sortino is None:
        raise ValueError("Unable to compute promoted Production Core Sharpe/Sortino from current_strategy_timeseries.csv")
    return {
        "total_return_pct_net": round(_compute_total_return_pct(return_net), 4),
        "cagr_pct_net": round(_compute_cagr_pct(return_net, dates), 4),
        "max_drawdown_pct_net": round(_compute_max_drawdown_pct(return_net), 4),
        "since2023_cagr_pct_net": round(_compute_cagr_since(return_net, dates, "2023-01-01"), 4),
        "since2025_cagr_pct_net": round(_compute_cagr_since(return_net, dates, "2025-01-01"), 4),
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


def build_promoted_decision_context(timeseries: pd.DataFrame) -> dict[str, Any]:
    current_row = timeseries.iloc[-1]
    dates = pd.to_datetime(timeseries["date"], errors="coerce")
    latest_rebalance_rows = timeseries.loc[_to_bool_series(timeseries["is_rebalance_day"])]
    latest_rebalance_date = None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["date"])
    risk_on_entry_mask = (~_to_bool_series(timeseries["cash_day"])) & _to_bool_series(timeseries["cash_day"]).shift(
        1,
        fill_value=True,
    )
    return {
        "current_reason_code": str(current_row["reason_code"]),
        "current_reason_text": build_promoted_reason_text(current_row),
        "current_regime_duration_days": int(_consecutive_tail_length(timeseries["regime"])),
        "days_since_last_trade": _days_since_last_true(_to_bool_series(timeseries["is_rebalance_day"]), dates),
        "days_since_last_risk_on": _days_since_last_true(risk_on_entry_mask, dates),
        "days_since_last_equity_high": _days_since_last_true(
            _to_float_series(timeseries["equity"]).eq(_to_float_series(timeseries["equity"]).cummax()),
            dates,
        ),
        "current_drawdown_pct": round(float(current_row["drawdown_pct"]), 6),
        "current_cash_streak_days": int(
            _consecutive_tail_length(_to_bool_series(timeseries["cash_day"])) if bool(current_row["cash_day"]) else 0
        ),
        "latest_rebalance_date": latest_rebalance_date,
        "latest_rebalance_reason": (
            None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["reason_code"])
        ),
    }


def build_promoted_source_inputs(candidate_inputs: dict[str, Any]) -> dict[str, Any]:
    snapshot = candidate_inputs["snapshot"]
    source_inputs = snapshot.get("source_inputs", {})
    lineage = source_inputs.get("lineage") if isinstance(source_inputs, dict) else None
    if not isinstance(lineage, dict):
        lineage = {
            "dev_only_source_lineage": True,
            "non_authoritative_research_input": True,
            "official_truth": False,
            "live_truth": False,
            "app_truth": False,
            "execution_truth": False,
        }
    return {
        "promotion_source": "staged_strategy_candidate_bundle",
        "strategy_id": PRODUCTION_STRATEGY_ID,
        "strategy_version": PROMOTED_CANDIDATE_ID,
        "validated_closed_day": candidate_inputs["closed_day"],
        "candidate_id": PROMOTED_CANDIDATE_ID,
        "base_strategy_version": str(snapshot.get("base_strategy_version") or "").strip(),
        "candidate_quality_status": str(candidate_inputs["quality"].get("status") or "").strip(),
        "candidate_bundle_path": _path_for_manifest(candidate_inputs["bundle_dir"], root=ROOT),
        "lineage": lineage,
        "baseline_reference": {
            "baseline_strategy_version": str(snapshot.get("base_strategy_version") or "").strip(),
            "baseline_closed_day": str(source_inputs.get("baseline_closed_day") or "").strip(),
            "baseline_source_path": str(snapshot.get("compare_universe", {}).get("baseline_source_path") or "").strip(),
        },
        "files": {
            "candidate_snapshot": {
                **_source_file_metadata(candidate_inputs["paths"]["snapshot"]),
                "closed_day": candidate_inputs["closed_day"],
                "candidate_id": str(snapshot.get("candidate_id") or "").strip(),
                "status": str(snapshot.get("status") or "").strip(),
            },
            "candidate_timeseries": _source_file_metadata(
                candidate_inputs["paths"]["timeseries"],
                last_date=candidate_inputs["timeseries_last_day"],
                row_count=len(candidate_inputs["timeseries"]),
            ),
            "candidate_diagnostics": {
                **_source_file_metadata(candidate_inputs["paths"]["diagnostics"]),
                "closed_day": candidate_inputs["closed_day"],
            },
            "candidate_quality": {
                **_source_file_metadata(candidate_inputs["paths"]["quality"]),
                "status": str(candidate_inputs["quality"].get("status") or "").strip(),
            },
            "candidate_manifest": {
                **_source_file_metadata(candidate_inputs["paths"]["manifest"]),
                "validation_status": str(candidate_inputs["manifest"].get("validation_status") or "").strip(),
            },
            "candidate_compare_json": _source_file_metadata(candidate_inputs["paths"]["compare_json"]),
            "candidate_compare_csv": _source_file_metadata(
                candidate_inputs["paths"]["compare_csv"],
                row_count=len(candidate_inputs["compare_csv"]),
            ),
        },
    }


def build_promoted_snapshot(
    *,
    generated_at_utc: str,
    build_command: str,
    git_commit: str | None,
    candidate_inputs: dict[str, Any],
    active_timeseries: pd.DataFrame,
    previous_snapshot: dict[str, Any],
    backup_path: str,
) -> dict[str, Any]:
    current_row = active_timeseries.iloc[-1]
    wait_condition = build_promoted_wait_condition(current_row)
    metrics = build_promoted_snapshot_metrics(active_timeseries)
    return {
        "artifact_type": "current_strategy_snapshot",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "strategy_id": PRODUCTION_STRATEGY_ID,
        "strategy_version": PROMOTED_CANDIDATE_ID,
        "closed_day": candidate_inputs["closed_day"],
        "strategy_status": "ready",
        "candidate_asset": str(current_row["candidate_asset"]),
        "selected_asset": str(current_row["selected_asset"]),
        "actual_held_asset": str(current_row["actual_held_asset"]),
        "authorized_tradable_asset": str(current_row["authorized_tradable_asset"]),
        "market_state": str(current_row["market_state"]),
        "current_asset": str(current_row["held_asset"]),
        "current_exposure": round(float(current_row["exposure"]), 6),
        "effective_market_exposure": round(float(current_row["effective_market_exposure"]), 6),
        "model_candidate_exposure": round(float(current_row["model_candidate_exposure"]), 6),
        "trend_permission_active": bool(current_row["trend_permission_active"]),
        "current_regime": str(current_row["regime"]),
        "execution_state": str(current_row["execution_state"]),
        "trend_state": str(current_row["trend_state"]),
        "trend_score": round(float(current_row["trend_score"]), 6),
        "next_rebalance_date": str(previous_snapshot.get("next_rebalance_date") or "").strip() or None,
        "metrics": metrics,
        "decision_context": build_promoted_decision_context(active_timeseries),
        "execution_intent": {
            "target_asset": str(current_row["execution_target_asset"]),
            "target_exposure": round(float(current_row["execution_target_exposure"]), 6),
            "signal_id": (
                f"{PRODUCTION_STRATEGY_ID}::{PROMOTED_CANDIDATE_ID}::{candidate_inputs['closed_day']}::"
                f"target_{str(current_row['execution_target_asset'])}::candidate_{str(current_row['candidate_asset'])}"
            ),
            "stale_signal": False,
            "allow_live_order_candidate": bool(
                bool(current_row["trend_permission_active"])
                and float(current_row["execution_target_exposure"]) > 0.0
            ),
        },
        "source_inputs": build_promoted_source_inputs(candidate_inputs),
        "validation": {
            "status": "pending",
            "errors": [],
            "warnings": [],
        },
        "provenance": {
            "promotion_type": "promoted_from_staged_candidate",
            "promoted_from_staged_candidate": {
                "candidate_id": PROMOTED_CANDIDATE_ID,
                "base_strategy_version": str(candidate_inputs["snapshot"].get("base_strategy_version") or "").strip(),
                "candidate_closed_day": candidate_inputs["closed_day"],
                "candidate_bundle_path": _path_for_manifest(candidate_inputs["bundle_dir"], root=ROOT),
                "candidate_snapshot_path": _path_for_manifest(candidate_inputs["paths"]["snapshot"], root=ROOT),
                "candidate_timeseries_path": _path_for_manifest(candidate_inputs["paths"]["timeseries"], root=ROOT),
                "candidate_diagnostics_path": _path_for_manifest(candidate_inputs["paths"]["diagnostics"], root=ROOT),
                "candidate_quality_path": _path_for_manifest(candidate_inputs["paths"]["quality"], root=ROOT),
                "candidate_manifest_path": _path_for_manifest(candidate_inputs["paths"]["manifest"], root=ROOT),
                "candidate_compare_json_path": _path_for_manifest(candidate_inputs["paths"]["compare_json"], root=ROOT),
                "candidate_compare_csv_path": _path_for_manifest(candidate_inputs["paths"]["compare_csv"], root=ROOT),
                "candidate_quality_status": str(candidate_inputs["quality"].get("status") or "").strip(),
                "candidate_validation_status": str(candidate_inputs["manifest"].get("validation_status") or "").strip(),
                "previous_active_strategy_version": str(previous_snapshot.get("strategy_version") or "").strip(),
                "previous_active_closed_day": str(previous_snapshot.get("closed_day") or "").strip(),
                "previous_active_next_rebalance_date": str(previous_snapshot.get("next_rebalance_date") or "").strip() or None,
                "backup_path": backup_path,
                "promotion_script": "scripts/production/promote_staged_strategy_candidate.py",
                "promotion_git_commit": git_commit,
                "promotion_command": build_command,
                "execution_refresh_required": True,
                "transitional_status": "ACTIVE_PRODUCTION_CORE_CUTOVER_READY_FOR_AUTOMATION_REFRESH",
            },
            "wait_condition": wait_condition,
        },
    }


def _build_promoted_pain_points(
    timeseries: pd.DataFrame,
    metrics: dict[str, Any],
    current_row: pd.Series,
    wait_condition: dict[str, Any],
) -> list[dict[str, Any]]:
    pain_points: list[dict[str, Any]] = []
    total_cost_pct = (
        float(metrics["trading_fees_total_pct"])
        + float(metrics["funding_total_pct"])
        + float(metrics["borrow_cost_total_pct"])
        + float(metrics["slippage_cost_total_pct"])
    )
    if float(metrics["cash_days_pct"]) >= 40.0:
        pain_points.append(
            {
                "code": "cash_drag_elevated",
                "severity": "medium",
                "text": f"Cash participation remains elevated at {float(metrics['cash_days_pct']):.4f}% of promoted history.",
                "metric_value": float(metrics["cash_days_pct"]),
                "metric_unit": "pct",
            }
        )
    if total_cost_pct >= 5.0:
        pain_points.append(
            {
                "code": "modeled_cost_drag_visible",
                "severity": "medium",
                "text": f"Modeled lifetime cost drag totals {total_cost_pct:.4f}% across the promoted overlap window.",
                "metric_value": total_cost_pct,
                "metric_unit": "pct",
            }
        )
    if wait_condition["code"] == "cooldown_clearance_pending_for_candidate_entry":
        pain_points.append(
            {
                "code": "cooldown_entry_block_active",
                "severity": "medium",
                "text": "ETF-flow permission is active, but the cooldown still blocks the next authorized entry.",
                "metric_value": None,
                "metric_unit": None,
            }
        )
    if wait_condition["code"] != "already_in_target_state":
        pain_points.append(
            {
                "code": "active_wait_condition",
                "severity": "low",
                "text": wait_condition["text"],
                "metric_value": None,
                "metric_unit": None,
            }
        )
    if not pain_points:
        pain_points.append(
            {
                "code": "no_material_pain_point_flagged",
                "severity": "low",
                "text": "No dominant promoted Production Core pain point was flagged by the current rule set.",
                "metric_value": None,
                "metric_unit": None,
            }
        )
    return pain_points


def build_promoted_diagnostics(
    *,
    generated_at_utc: str,
    candidate_inputs: dict[str, Any],
    active_timeseries: pd.DataFrame,
    validation: dict[str, Any],
) -> dict[str, Any]:
    current_row = active_timeseries.iloc[-1]
    metrics = build_promoted_snapshot_metrics(active_timeseries)
    wait_condition = build_promoted_wait_condition(current_row)
    pain_points = _build_promoted_pain_points(active_timeseries, metrics, current_row, wait_condition)
    dates = pd.to_datetime(active_timeseries["date"], errors="coerce")
    recent_regime_rows = active_timeseries.loc[
        active_timeseries["regime"] != active_timeseries["regime"].shift(1, fill_value=active_timeseries["regime"].iloc[0])
    ].tail(5)
    recent_rebalance_rows = active_timeseries.loc[_to_bool_series(active_timeseries["is_rebalance_day"])].tail(5)
    trailing_30 = active_timeseries.tail(30)
    trailing_90 = active_timeseries.tail(90)
    cash_streak_days = int(_consecutive_tail_length(_to_bool_series(active_timeseries["cash_day"]))) if bool(current_row["cash_day"]) else 0
    lifetime_cost_pct = (
        float(_to_float_series(active_timeseries["fees_daily"]).sum() * 100.0)
        + float(_to_float_series(active_timeseries["funding_daily"]).sum() * 100.0)
        + float(_to_float_series(active_timeseries["borrow_cost_daily"]).sum() * 100.0)
        + float(_to_float_series(active_timeseries["slippage_cost_daily"]).sum() * 100.0)
    )
    return {
        "artifact_type": "current_strategy_diagnostics",
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "strategy_id": PRODUCTION_STRATEGY_ID,
        "strategy_version": PROMOTED_CANDIDATE_ID,
        "closed_day": candidate_inputs["closed_day"],
        "latest_state_explanation": build_promoted_reason_text(current_row),
        "current_flatline_explanation": (
            f"Authorized capital should stay flat during the current CASH streak of {cash_streak_days} days "
            "because no market exposure is currently allowed."
            if cash_streak_days > 0
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
            "current_effective_exposure": round(float(current_row["effective_market_exposure"]), 6),
            "trailing_30d_fees_pct": round(float(_to_float_series(trailing_30["fees_daily"]).sum() * 100.0), 6),
            "trailing_30d_funding_pct": round(float(_to_float_series(trailing_30["funding_daily"]).sum() * 100.0), 6),
            "trailing_30d_borrow_pct": round(float(_to_float_series(trailing_30["borrow_cost_daily"]).sum() * 100.0), 6),
            "trailing_30d_slippage_pct": round(float(_to_float_series(trailing_30["slippage_cost_daily"]).sum() * 100.0), 6),
        },
        "current_fee_drag_summary": {
            "lifetime_trading_fees_total_pct": round(float(_to_float_series(active_timeseries["fees_daily"]).sum() * 100.0), 6),
            "lifetime_funding_total_pct": round(float(_to_float_series(active_timeseries["funding_daily"]).sum() * 100.0), 6),
            "lifetime_borrow_cost_total_pct": round(float(_to_float_series(active_timeseries["borrow_cost_daily"]).sum() * 100.0), 6),
            "lifetime_slippage_cost_total_pct": round(float(_to_float_series(active_timeseries["slippage_cost_daily"]).sum() * 100.0), 6),
            "lifetime_total_cost_pct": round(lifetime_cost_pct, 6),
            "trailing_90d_turnover": round(float(_to_float_series(trailing_90["turnover"]).sum()), 6),
        },
        "current_data_health_summary": {
            "status": "passed",
            "closed_day": candidate_inputs["closed_day"],
            "summary_latest_available_date": candidate_inputs["closed_day"],
            "paper_last_day": candidate_inputs["closed_day"],
            "trend_status_day": candidate_inputs["closed_day"],
            "trend_history_last_day": candidate_inputs["closed_day"],
            "freshness_closed_day": candidate_inputs["closed_day"],
            "freshness_status": "passed",
            "freshness_errors": [],
            "warnings": [],
            "staged_candidate_quality_status": str(candidate_inputs["quality"].get("status") or "").strip(),
        },
        "strategy_improvement_signals": {
            "churn_pressure": {
                "status": "elevated" if float(_to_float_series(trailing_90["turnover"]).sum()) >= 8.0 else "contained",
                "trade_count": int(metrics["trade_count"]),
                "switch_count": int(metrics["switch_count"]),
                "trailing_90d_turnover": round(float(_to_float_series(trailing_90["turnover"]).sum()), 6),
            },
            "fee_sensitivity": {
                "status": "elevated" if lifetime_cost_pct >= 5.0 else "contained",
                "lifetime_total_cost_pct": round(lifetime_cost_pct, 6),
                "effective_trading_fee_bps": 4.5,
            },
            "cash_drag": {
                "status": "elevated" if float(metrics["cash_days_pct"]) >= 40.0 else "contained",
                "cash_days_pct": round(float(metrics["cash_days_pct"]), 6),
                "current_cash_streak_days": cash_streak_days,
            },
            "flatline_duration": {
                "status": "active" if cash_streak_days > 0 else "inactive",
                "current_cash_streak_days": cash_streak_days,
            },
            "current_research_questions": [
                "Can the 15-day ETF-flow cooldown be shortened without increasing false starts?",
                "How much of the promoted edge survives after modeled fees and slippage?",
                "How often does ETF-flow permission fire while the baseline model still stays in CASH?",
            ],
        },
        "validation": {
            "status": validation["status"],
            "errors": list(validation["errors"]),
            "warnings": list(validation["warnings"]),
        },
        "current_trade_state": {
            "is_cash": bool(current_row["cash_day"]),
            "is_waiting": wait_condition["code"] != "already_in_target_state",
            "state_code": str(current_row["market_state"]),
            "candidate_asset": str(current_row["candidate_asset"]),
            "selected_asset": str(current_row["selected_asset"]),
            "actual_held_asset": str(current_row["actual_held_asset"]),
            "authorized_tradable_asset": str(current_row["authorized_tradable_asset"]),
            "effective_market_exposure": round(float(current_row["effective_market_exposure"]), 6),
            "model_candidate_exposure": round(float(current_row["model_candidate_exposure"]), 6),
            "trend_permission_active": bool(current_row["trend_permission_active"]),
            "waiting_reason_code": str(current_row["reason_code"]),
            "waiting_reason_text": build_promoted_reason_text(current_row),
            "waiting_condition_code": wait_condition["code"],
            "waiting_condition_text": wait_condition["text"],
            "waiting_condition_values": wait_condition["current_values"],
            "target_condition": wait_condition["target_condition"],
            "pain_points": pain_points,
        },
        "current_pain_points": pain_points,
        "current_wait_condition": wait_condition,
        "promotion_summary": {
            "candidate_window_counts": candidate_inputs["diagnostics"].get("window_counts", {}),
            "candidate_blocker_rows": candidate_inputs["diagnostics"].get("blocker_rows", {}),
            "candidate_compare_summary": candidate_inputs["diagnostics"].get("compare_summary", {}),
            "candidate_quality_status": str(candidate_inputs["quality"].get("status") or "").strip(),
            "candidate_manifest_validation_status": str(candidate_inputs["manifest"].get("validation_status") or "").strip(),
        },
    }


def build_promoted_manifest(
    *,
    generated_at_utc: str,
    build_command: str,
    git_commit: str | None,
    candidate_inputs: dict[str, Any],
    validation: dict[str, Any],
    backup_path: str,
    backup_files: list[str],
    snapshot_path: Path,
    timeseries_path: Path,
    diagnostics_path: Path,
    quality_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    return {
        "artifact_type": "current_strategy_snapshot_manifest",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "strategy_id": PRODUCTION_STRATEGY_ID,
        "strategy_version": PROMOTED_CANDIDATE_ID,
        "adapter_name": PROMOTION_ADAPTER_NAME,
        "build_command": build_command,
        "git_commit": git_commit,
        "source_inputs": build_promoted_source_inputs(candidate_inputs),
        "output_paths": {
            "snapshot": _path_for_manifest(snapshot_path, root=ROOT),
            "timeseries": _path_for_manifest(timeseries_path, root=ROOT),
            "diagnostics": _path_for_manifest(diagnostics_path, root=ROOT),
            "quality": _path_for_manifest(quality_path, root=ROOT),
            "manifest": _path_for_manifest(manifest_path, root=ROOT),
        },
        "promotion": {
            "mode": "promoted_from_staged_candidate",
            "candidate_id": PROMOTED_CANDIDATE_ID,
            "candidate_closed_day": candidate_inputs["closed_day"],
            "candidate_bundle_path": _path_for_manifest(candidate_inputs["bundle_dir"], root=ROOT),
            "candidate_quality_status": str(candidate_inputs["quality"].get("status") or "").strip(),
            "candidate_manifest_validation_status": str(candidate_inputs["manifest"].get("validation_status") or "").strip(),
            "backup_path": backup_path,
            "backup_files": list(backup_files),
            "replaced_output_files": [
                "outputs/production/current_strategy_snapshot.json",
                "outputs/production/current_strategy_timeseries.csv",
                "outputs/production/current_strategy_diagnostics.json",
                "outputs/production/current_strategy_snapshot.quality.json",
                "outputs/production/current_strategy_snapshot.manifest.json",
            ],
            "execution_refresh_required": True,
            "transitional_status": "ACTIVE_PRODUCTION_CORE_CUTOVER_READY_FOR_AUTOMATION_REFRESH",
        },
        "validation_status": validation["status"],
    }


def validate_promoted_candidate_production_payloads(
    *,
    snapshot: dict[str, Any],
    timeseries: pd.DataFrame,
    diagnostics: dict[str, Any],
    candidate_inputs: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    _check_required_keys(snapshot, REQUIRED_SNAPSHOT_KEYS, context="snapshot", errors=errors)
    _check_required_keys(diagnostics, REQUIRED_DIAGNOSTICS_KEYS, context="diagnostics", errors=errors)
    missing_columns = [column for column in ACTIVE_TIMESERIES_COLUMNS if column not in timeseries.columns]
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

    _compare_text(snapshot.get("artifact_type"), "current_strategy_snapshot", context="snapshot.artifact_type", errors=errors)
    _compare_text(diagnostics.get("artifact_type"), "current_strategy_diagnostics", context="diagnostics.artifact_type", errors=errors)
    _compare_text(snapshot.get("strategy_id"), PRODUCTION_STRATEGY_ID, context="snapshot.strategy_id", errors=errors)
    _compare_text(snapshot.get("strategy_version"), PROMOTED_CANDIDATE_ID, context="snapshot.strategy_version", errors=errors)
    _compare_text(diagnostics.get("strategy_id"), PRODUCTION_STRATEGY_ID, context="diagnostics.strategy_id", errors=errors)
    _compare_text(diagnostics.get("strategy_version"), PROMOTED_CANDIDATE_ID, context="diagnostics.strategy_version", errors=errors)

    closed_day = candidate_inputs["closed_day"]
    _compare_text(snapshot.get("closed_day"), closed_day, context="snapshot.closed_day", errors=errors)
    _compare_text(diagnostics.get("closed_day"), closed_day, context="diagnostics.closed_day", errors=errors)
    last_day = _normalize_iso_day_text(timeseries["date"].iloc[-1], context="timeseries.last_row.date")
    _compare_text(last_day, closed_day, context="timeseries.last_row.date", errors=errors)
    checks["source_day_alignment"] = (
        candidate_inputs["timeseries_last_day"] == closed_day
        and str(candidate_inputs["diagnostics"].get("closed_day") or "").strip() == closed_day
        and last_day == closed_day
    )
    if not checks["source_day_alignment"]:
        errors.append("promoted candidate closed-day alignment failed across the staged bundle and active outputs")

    checks["strategy_status_ready"] = str(snapshot.get("strategy_status") or "").strip() == "ready"
    if not checks["strategy_status_ready"]:
        errors.append("snapshot.strategy_status must be 'ready'")

    last_row = timeseries.iloc[-1]
    _compare_text(snapshot.get("candidate_asset"), str(last_row["candidate_asset"]), context="snapshot.candidate_asset", errors=errors)
    _compare_text(snapshot.get("selected_asset"), str(last_row["selected_asset"]), context="snapshot.selected_asset", errors=errors)
    _compare_text(snapshot.get("actual_held_asset"), str(last_row["actual_held_asset"]), context="snapshot.actual_held_asset", errors=errors)
    _compare_text(
        snapshot.get("authorized_tradable_asset"),
        str(last_row["authorized_tradable_asset"]),
        context="snapshot.authorized_tradable_asset",
        errors=errors,
    )
    _compare_text(snapshot.get("market_state"), str(last_row["market_state"]), context="snapshot.market_state", errors=errors)
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
    _compare_text(snapshot.get("execution_state"), str(last_row["execution_state"]), context="snapshot.execution_state", errors=errors)
    _compare_text(snapshot.get("trend_state"), str(last_row["trend_state"]), context="snapshot.trend_state", errors=errors)
    _compare_float(snapshot.get("trend_score"), float(last_row["trend_score"]), context="snapshot.trend_score", errors=errors)

    decision_context = snapshot.get("decision_context")
    if not isinstance(decision_context, dict):
        errors.append("snapshot.decision_context must be an object")
    else:
        _compare_text(
            decision_context.get("current_reason_code"),
            str(last_row["reason_code"]),
            context="snapshot.decision_context.current_reason_code",
            errors=errors,
        )
        _compare_text(
            decision_context.get("current_reason_text"),
            build_promoted_reason_text(last_row),
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
            errors.append("snapshot.execution_intent.stale_signal must be false for a validated promotion")

    metrics = snapshot.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("snapshot.metrics must be an object")
    else:
        expected_metrics = build_promoted_snapshot_metrics(timeseries)
        for field_name, expected_value in expected_metrics.items():
            _compare_float(
                metrics.get(field_name),
                float(expected_value),
                context=f"snapshot.metrics.{field_name}",
                errors=errors,
                tolerance=1e-4,
            )
        checks["summary_parity"] = True

    trend_permission_active = bool(snapshot.get("trend_permission_active"))
    current_asset = str(snapshot.get("current_asset") or "").strip().upper()
    effective_market_exposure = float(snapshot.get("effective_market_exposure") or 0.0)
    current_exposure = float(snapshot.get("current_exposure") or 0.0)
    model_candidate_exposure = float(snapshot.get("model_candidate_exposure") or 0.0)
    execution_target_asset = str((execution_intent or {}).get("target_asset") or "").strip().upper()
    execution_target_exposure = float((execution_intent or {}).get("target_exposure") or 0.0)
    allow_live_order_candidate = bool((execution_intent or {}).get("allow_live_order_candidate"))

    checks["candidate_asset_separated_from_actual_exposure"] = (
        not trend_permission_active
        and not _is_cash_like_asset(str(snapshot.get("candidate_asset") or "").strip().upper())
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
    if not trend_permission_active and allow_live_order_candidate:
        errors.append("trend_permission_active=false but allow_live_order_candidate is true")
    if trend_permission_active and execution_target_exposure <= SUMMARY_TOLERANCE:
        errors.append("trend_permission_active=true but execution target exposure is zero")
    if trend_permission_active and _is_cash_like_asset(execution_target_asset):
        errors.append("trend_permission_active=true but execution target asset is CASH")
    if model_candidate_exposure < effective_market_exposure - SUMMARY_TOLERANCE:
        errors.append("model_candidate_exposure must be greater than or equal to effective_market_exposure")

    primary_return_gross = _to_float_series(timeseries["return_gross"])
    primary_return_net = _to_float_series(timeseries["return_net"])
    primary_equity = _to_float_series(timeseries["equity"])
    authorized_return_gross = _to_float_series(timeseries["authorized_return_gross"])
    authorized_return_net = _to_float_series(timeseries["authorized_return_net"])
    authorized_equity = _to_float_series(timeseries["authorized_equity"])
    btc_close = _to_float_series(timeseries["btc_close"])
    btc_return = _to_float_series(timeseries["btc_return"])
    btc_baseline_equity = _to_float_series(timeseries["btc_baseline_equity"])
    btc_baseline_index = _to_float_series(timeseries["btc_baseline_index"])
    model_candidate_return_net = _to_float_series(timeseries["model_candidate_return_net"])
    model_candidate_equity = _to_float_series(timeseries["model_candidate_equity"])
    effective_exposure_series = _to_float_series(timeseries["effective_market_exposure"])
    transition_mask = _to_bool_series(timeseries["asset_transition_day"])
    daily_costs = (
        _to_float_series(timeseries["fees_daily"])
        + _to_float_series(timeseries["funding_daily"])
        + _to_float_series(timeseries["borrow_cost_daily"])
        + _to_float_series(timeseries["slippage_cost_daily"])
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

    out_of_market_non_transition_cost = out_of_market_mask & (~transition_mask) & (daily_costs.abs() > SUMMARY_TOLERANCE)
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
    authorized_equity_curve_mismatch = (reconstructed_authorized_equity - authorized_equity).abs() > SUMMARY_TOLERANCE
    if authorized_equity_curve_mismatch.any():
        errors.append(
            "authorized_equity must equal the cumulative authorized_return_net curve "
            f"(examples: {_summarize_bad_dates(authorized_equity_curve_mismatch, row_dates)})"
        )

    if (btc_close <= 0).any():
        errors.append(
            "btc_close must stay strictly positive "
            f"(examples: {_summarize_bad_dates(btc_close <= 0, row_dates)})"
        )

    reconstructed_btc_return = btc_close.pct_change().fillna(0.0)
    btc_return_mismatch = (reconstructed_btc_return - btc_return).abs() > SUMMARY_TOLERANCE
    if btc_return_mismatch.any():
        errors.append(
            "btc_return must match close-to-close BTC benchmark moves "
            f"(examples: {_summarize_bad_dates(btc_return_mismatch, row_dates)})"
        )

    reconstructed_btc_baseline_equity = (1.0 + btc_return).cumprod()
    btc_equity_mismatch = (reconstructed_btc_baseline_equity - btc_baseline_equity).abs() > SUMMARY_TOLERANCE
    if btc_equity_mismatch.any():
        errors.append(
            "btc_baseline_equity must equal the cumulative btc_return curve "
            f"(examples: {_summarize_bad_dates(btc_equity_mismatch, row_dates)})"
        )

    btc_index_mismatch = ((btc_baseline_equity * 100.0) - btc_baseline_index).abs() > SUMMARY_TOLERANCE
    if btc_index_mismatch.any():
        errors.append(
            "btc_baseline_index must equal btc_baseline_equity * 100 "
            f"(examples: {_summarize_bad_dates(btc_index_mismatch, row_dates)})"
        )

    checks["primary_series_use_authorized_equity_semantics"] = not (
        primary_gross_mismatch.any() or primary_net_mismatch.any() or primary_equity_mismatch.any()
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
        (btc_close <= 0).any()
        or btc_return_mismatch.any()
        or btc_equity_mismatch.any()
        or btc_index_mismatch.any()
    )

    expected_source_inputs = build_promoted_source_inputs(candidate_inputs)
    source_inputs = snapshot.get("source_inputs")
    if not isinstance(source_inputs, dict):
        errors.append("snapshot.source_inputs must be an object")
    else:
        for top_level_key in (
            "promotion_source",
            "strategy_id",
            "strategy_version",
            "validated_closed_day",
            "candidate_id",
            "base_strategy_version",
            "candidate_quality_status",
            "candidate_bundle_path",
        ):
            _compare_text(
                source_inputs.get(top_level_key),
                str(expected_source_inputs[top_level_key]),
                context=f"snapshot.source_inputs.{top_level_key}",
                errors=errors,
            )
        if source_inputs.get("lineage") != expected_source_inputs["lineage"]:
            errors.append("snapshot.source_inputs.lineage mismatch")
        if source_inputs.get("baseline_reference") != expected_source_inputs["baseline_reference"]:
            errors.append("snapshot.source_inputs.baseline_reference mismatch")
        current_files = source_inputs.get("files")
        expected_files = expected_source_inputs["files"]
        if not isinstance(current_files, dict):
            errors.append("snapshot.source_inputs.files must be an object")
        else:
            for key, expected_meta in expected_files.items():
                actual_meta = current_files.get(key)
                if not isinstance(actual_meta, dict):
                    errors.append(f"snapshot.source_inputs.files.{key} must be an object")
                    continue
                for meta_key in ("path", "sha256"):
                    _compare_text(
                        actual_meta.get(meta_key),
                        str(expected_meta[meta_key]),
                        context=f"snapshot.source_inputs.files.{key}.{meta_key}",
                        errors=errors,
                    )
                for meta_key in ("last_date", "closed_day", "status", "validation_status", "candidate_id"):
                    if meta_key in expected_meta:
                        _compare_text(
                            actual_meta.get(meta_key),
                            str(expected_meta[meta_key]),
                            context=f"snapshot.source_inputs.files.{key}.{meta_key}",
                            errors=errors,
                        )
                for meta_key in ("row_count", "size_bytes"):
                    if meta_key in expected_meta:
                        _compare_float(
                            actual_meta.get(meta_key),
                            float(expected_meta[meta_key]),
                            context=f"snapshot.source_inputs.files.{key}.{meta_key}",
                            errors=errors,
                            tolerance=0.0,
                        )

    provenance = snapshot.get("provenance")
    promoted_from = provenance.get("promoted_from_staged_candidate") if isinstance(provenance, dict) else None
    checks["promoted_from_staged_candidate_provenance_present"] = isinstance(promoted_from, dict)
    if not isinstance(promoted_from, dict):
        errors.append("snapshot.provenance.promoted_from_staged_candidate must be an object")
    else:
        _compare_text(
            promoted_from.get("candidate_id"),
            PROMOTED_CANDIDATE_ID,
            context="snapshot.provenance.promoted_from_staged_candidate.candidate_id",
            errors=errors,
        )
        _compare_text(
            promoted_from.get("candidate_closed_day"),
            closed_day,
            context="snapshot.provenance.promoted_from_staged_candidate.candidate_closed_day",
            errors=errors,
        )
        _compare_text(
            promoted_from.get("candidate_bundle_path"),
            _path_for_manifest(candidate_inputs["bundle_dir"], root=ROOT),
            context="snapshot.provenance.promoted_from_staged_candidate.candidate_bundle_path",
            errors=errors,
        )
        _compare_text(
            promoted_from.get("candidate_quality_status"),
            str(candidate_inputs["quality"].get("status") or "").strip(),
            context="snapshot.provenance.promoted_from_staged_candidate.candidate_quality_status",
            errors=errors,
        )
        _compare_text(
            promoted_from.get("candidate_validation_status"),
            str(candidate_inputs["manifest"].get("validation_status") or "").strip(),
            context="snapshot.provenance.promoted_from_staged_candidate.candidate_validation_status",
            errors=errors,
        )

    expected_wait_condition = build_promoted_wait_condition(last_row)
    if not isinstance(provenance, dict) or provenance.get("wait_condition") != expected_wait_condition:
        errors.append("snapshot.provenance.wait_condition mismatch")

    trade_state = diagnostics.get("current_trade_state")
    if not isinstance(trade_state, dict):
        errors.append("diagnostics.current_trade_state must be an object")
    else:
        _compare_text(
            trade_state.get("candidate_asset"),
            str(last_row["candidate_asset"]),
            context="diagnostics.current_trade_state.candidate_asset",
            errors=errors,
        )
        _compare_text(
            trade_state.get("actual_held_asset"),
            str(last_row["actual_held_asset"]),
            context="diagnostics.current_trade_state.actual_held_asset",
            errors=errors,
        )
        _compare_float(
            trade_state.get("effective_market_exposure"),
            float(last_row["effective_market_exposure"]),
            context="diagnostics.current_trade_state.effective_market_exposure",
            errors=errors,
        )
        _compare_float(
            trade_state.get("model_candidate_exposure"),
            float(last_row["model_candidate_exposure"]),
            context="diagnostics.current_trade_state.model_candidate_exposure",
            errors=errors,
        )
        _compare_text(
            trade_state.get("waiting_reason_code"),
            str(last_row["reason_code"]),
            context="diagnostics.current_trade_state.waiting_reason_code",
            errors=errors,
        )
        _compare_text(
            trade_state.get("waiting_reason_text"),
            build_promoted_reason_text(last_row),
            context="diagnostics.current_trade_state.waiting_reason_text",
            errors=errors,
        )
        if trade_state.get("pain_points") != diagnostics.get("current_pain_points"):
            errors.append("diagnostics.current_trade_state.pain_points must match diagnostics.current_pain_points")

    if diagnostics.get("current_wait_condition") != expected_wait_condition:
        errors.append("diagnostics.current_wait_condition mismatch")

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
        _compare_text(
            current_data_health_summary.get("staged_candidate_quality_status"),
            str(candidate_inputs["quality"].get("status") or "").strip(),
            context="diagnostics.current_data_health_summary.staged_candidate_quality_status",
            errors=errors,
        )

    checks["validation_status_passed"] = (
        str(snapshot.get("validation", {}).get("status") or "").strip() == "passed"
        and str(diagnostics.get("validation", {}).get("status") or "").strip() == "passed"
    )
    if not checks["validation_status_passed"]:
        errors.append("snapshot.validation.status and diagnostics.validation.status must both be 'passed'")

    status = "passed" if not errors else "failed"
    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }
