from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.approved_strategy_net_export_helper import (
    CASH_EQUIVALENT_ASSETS,
    NetCostExportConfig,
    build_net_cost_export_frame,
    summarize_net_cost_export,
)


ROOT = Path(__file__).resolve().parents[3]

PRODUCTION_STRATEGY_ID = "current_strategy"
SOURCE_STRATEGY_VERSION = "phase68g_66g_1p25x_candidate"
ADAPTER_NAME = "phase68g_66g_1p25x_candidate_adapter"
SNAPSHOT_SCHEMA_VERSION = 4
DIAGNOSTICS_SCHEMA_VERSION = 4
QUALITY_SCHEMA_VERSION = 4
MANIFEST_SCHEMA_VERSION = 4
SUMMARY_TOLERANCE = 1e-6


def _read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _read_csv_rows_required(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required CSV file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        rows = list(reader)
    if not header:
        raise ValueError(f"CSV header is missing in {path}")
    if not rows:
        raise ValueError(f"CSV has no rows in {path}")
    return header, rows


def _read_single_csv_row_required(path: Path) -> dict[str, str]:
    _header, rows = _read_csv_rows_required(path)
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one row in {path}, found {len(rows)}")
    return rows[0]


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


def _to_float(value: Any, *, context: str) -> float:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    try:
        numeric = float(text)
    except ValueError as exc:
        raise ValueError(f"{context} must be numeric (actual={value})") from exc
    if not np.isfinite(numeric):
        raise ValueError(f"{context} must be finite (actual={value})")
    return numeric


def _to_int(value: Any, *, context: str) -> int:
    return int(round(_to_float(value, context=context)))


def _to_bool_series(series: pd.Series) -> pd.Series:
    normalized = series.fillna("").astype(str).str.strip().str.lower()
    return normalized.isin({"1", "true", "yes", "y"})


def _to_float_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify_regime(held_asset: str) -> str:
    normalized = str(held_asset or "").strip().upper()
    if normalized in CASH_EQUIVALENT_ASSETS:
        return "CASH"
    if normalized == "BTC":
        return "BTC"
    if normalized == "BASE":
        return "BASE"
    return "ALT"


def _normalize_asset_code(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized or normalized in {"NONE", "OUT_OF_MARKET"}:
        return "CASH"
    if normalized in CASH_EQUIVALENT_ASSETS:
        return "CASH"
    return normalized


def _resolve_trend_permission_active(
    *,
    trend_gate_pass: bool,
    stress_block_day: bool,
) -> bool:
    if stress_block_day:
        return False
    return bool(trend_gate_pass)


def _build_reason_code(row: pd.Series) -> str:
    candidate_asset = _normalize_asset_code(row.get("candidate_asset"))
    actual_asset = _normalize_asset_code(row.get("actual_held_asset", row.get("held_asset")))
    regime = str(row["regime"]).strip().upper()
    trend_permission_active = bool(row.get("trend_permission_active", False))
    if bool(row["cash_day"]) and bool(row["stress_block_day"]):
        return "cash_stress_block"
    if not trend_permission_active and candidate_asset not in CASH_EQUIVALENT_ASSETS:
        return "candidate_wait_trend_confirmation"
    if bool(row["is_rebalance_day"]):
        return f"rebalance_to_{actual_asset.lower()}" if actual_asset else "rebalance"
    state_reason = str(row["leverage_state_reason"] or "").strip().lower()
    if state_reason == "switch_day":
        return "switch_day_hold"
    if state_reason == "entry_buffer_day":
        return "entry_buffer_hold"
    if bool(row["leverage_active"]):
        return "leveraged_hold"
    if regime == "BTC":
        return "hold_btc"
    if regime == "BASE":
        return "hold_base"
    if regime == "ALT":
        return "hold_alt"
    return "hold_cash"


def build_reason_text(row: pd.Series) -> str:
    candidate_asset = _normalize_asset_code(row.get("candidate_asset"))
    held_asset = _normalize_asset_code(row.get("actual_held_asset", row.get("held_asset"))) or "CASH"
    trend_score = float(row["trend_score"])
    buy_threshold = float(row["buy_threshold"])
    activation_threshold = float(row["trend_activation_threshold"])
    exposure = float(row.get("effective_market_exposure", row.get("exposure", 0.0)))
    trend_permission_active = bool(row.get("trend_permission_active", False))
    trigger_threshold = activation_threshold if activation_threshold > 0.0 else buy_threshold
    if bool(row["cash_day"]) and bool(row["stress_block_day"]) and candidate_asset not in CASH_EQUIVALENT_ASSETS:
        return (
            f"{candidate_asset} is only the current candidate. The strategy remains in CASH because "
            "the stress block is active, and authorized capital stays flat until market exposure is allowed."
        )
    if bool(row["cash_day"]) and bool(row["stress_block_day"]):
        return (
            "The strategy remains in CASH because the stress block is active, and authorized capital "
            "stays flat until market exposure is allowed."
        )
    if not trend_permission_active and candidate_asset not in CASH_EQUIVALENT_ASSETS:
        return (
            f"{candidate_asset} is only the current candidate. The strategy remains in CASH because "
            f"trend has not confirmed entry ({trend_score:.4f} vs {trigger_threshold:.4f}), and "
            "authorized capital stays flat while no exposure is allowed."
        )
    if bool(row["is_rebalance_day"]) and held_asset == "CASH":
        return "The strategy rebalanced into CASH on the latest closed day."
    if bool(row["is_rebalance_day"]):
        return f"The strategy rebalanced into {held_asset} on the latest closed day."
    if held_asset in CASH_EQUIVALENT_ASSETS:
        return (
            "The strategy remains in CASH with no authorized market exposure, so authorized capital "
            "stays flat until a new entry is approved."
        )
    if bool(row["leverage_active"]):
        return f"The strategy holds {held_asset} with authorized leverage at {exposure:.2f}x."
    return f"The strategy holds {held_asset} with authorized market exposure at {exposure:.2f}x."


def _rolling_compound_return(series: pd.Series, window: int) -> pd.Series:
    return (
        (1.0 + series)
        .rolling(window=window, min_periods=window)
        .apply(np.prod, raw=True)
        - 1.0
    )


def _rolling_sharpe(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std(ddof=0)
    sharpe = (mean / std.replace(0.0, np.nan)) * np.sqrt(365.25)
    return sharpe.replace([np.inf, -np.inf], np.nan)


def _to_float_value(value: Any, *, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return default
    return float(numeric)


def _normalize_materialized_timeseries(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized = normalized.dropna(subset=["date"]).sort_values("date")
    normalized = normalized.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    if normalized.empty:
        raise ValueError("phase68g baseline timeseries has no usable rows after date normalization")
    return normalized


def _build_dependency_materialization_carry_forward_row(
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
            "Unable to materialize stale phase68g baseline rows without a prior BTC close "
            f"(paper_last_day={last_day_text})"
        )
    if held_asset not in CASH_EQUIVALENT_ASSETS and held_asset != "BTC":
        raise ValueError(
            "phase68g baseline paper is stale relative to the canonical closed day, and the "
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


def _materialize_strategy_timeseries_to_closed_day(
    *,
    timeseries: pd.DataFrame,
    summary_row: dict[str, Any],
    benchmark_df: pd.DataFrame,
    target_closed_day: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    materialized = _normalize_materialized_timeseries(timeseries)
    source_last_day = pd.Timestamp(materialized["date"].iloc[-1]).strftime("%Y-%m-%d")
    target_day = pd.Timestamp(target_closed_day)
    if pd.Timestamp(source_last_day) > target_day:
        raise ValueError(
            "phase68g baseline timeseries last_row.date cannot be ahead of the canonical closed day "
            f"(timeseries={source_last_day} closed_day={target_closed_day})"
        )
    if source_last_day == target_closed_day:
        materialized["date"] = materialized["date"].dt.strftime("%Y-%m-%d")
        return materialized, {
            "paper_source_last_day": source_last_day,
            "raw_source_last_day": source_last_day,
            "materialized_closed_day": target_closed_day,
            "carry_forward_rows_added": 0,
        }

    benchmark = benchmark_df.copy()
    benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce")
    benchmark["btc_close"] = pd.to_numeric(benchmark["btc_close"], errors="coerce")
    benchmark = benchmark.dropna(subset=["date", "btc_close"]).sort_values("date")
    benchmark = benchmark.drop_duplicates(subset=["date"], keep="last").set_index("date")
    carry_forward_days = benchmark.index[
        (benchmark.index > pd.Timestamp(source_last_day)) & (benchmark.index <= target_day)
    ]
    if carry_forward_days.empty or carry_forward_days[-1] != target_day:
        raise ValueError(
            "benchmark_ohlcv is missing one or more rows needed to materialize the canonical closed day "
            f"(timeseries={source_last_day} closed_day={target_closed_day})"
        )

    annual_borrow_cost_pct = _to_float_value(summary_row.get("annual_borrow_cost_pct"))
    added_rows = 0
    for carry_day in carry_forward_days.tolist():
        next_row = _build_dependency_materialization_carry_forward_row(
            last_row=materialized.iloc[-1],
            target_day=pd.Timestamp(carry_day),
            benchmark_close=float(benchmark.loc[carry_day, "btc_close"]),
            annual_borrow_cost_pct=annual_borrow_cost_pct,
        )
        materialized = pd.concat([materialized, pd.DataFrame([next_row])], ignore_index=True)
        added_rows += 1

    materialized["date"] = pd.to_datetime(materialized["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return materialized, {
        "paper_source_last_day": source_last_day,
        "raw_source_last_day": source_last_day,
        "materialized_closed_day": pd.Timestamp(materialized["date"].iloc[-1]).strftime("%Y-%m-%d"),
        "carry_forward_rows_added": added_rows,
    }


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
    downside_variance = sum((value - downside_mean) ** 2 for value in downside) / (
        len(downside) - 1
    )
    if downside_variance <= 0:
        return None
    downside_std = downside_variance**0.5
    if downside_std == 0:
        return None
    return (mean_ret / downside_std) * (365**0.5)


def _prepare_btc_benchmark_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if "date" not in frame.columns:
        raise KeyError("benchmark_ohlcv is missing required date column")
    if "close" not in frame.columns:
        raise KeyError("benchmark_ohlcv is missing required close column")
    prepared = pd.DataFrame()
    prepared["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    prepared["btc_close"] = pd.to_numeric(frame["close"], errors="coerce")
    prepared = (
        prepared.dropna(subset=["date", "btc_close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if prepared.empty:
        raise ValueError("benchmark_ohlcv has no usable date/close rows")
    if (prepared["btc_close"] <= 0).any():
        raise ValueError("benchmark_ohlcv.close must stay strictly positive")
    return prepared


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


@dataclass(frozen=True)
class Phase68g66g1p25xCandidateAdapter:
    strategy_id: str = PRODUCTION_STRATEGY_ID
    strategy_version: str = SOURCE_STRATEGY_VERSION
    adapter_name: str = ADAPTER_NAME

    def resolve_source_paths(self, *, root: Path | None = None) -> dict[str, Path]:
        repo_root = (root or ROOT).resolve()
        return {
            "strategy_summary": repo_root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv",
            "strategy_paper": repo_root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase68g_66g_1p25x_candidate_paper.csv",
            "trend_status": repo_root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase66g_live_status.csv",
            "trend_history": repo_root
            / "outputs"
            / "execution"
            / "app_exports"
            / "phase66g_trend_barometer_history.csv",
            "freshness_report": repo_root
            / "outputs"
            / "execution"
            / "freshness"
            / "app_freshness_report.json",
            "benchmark_ohlcv": repo_root / "data" / "ohlcv" / "BTCUSDT_1d.csv",
        }

    def load_inputs(
        self,
        *,
        root: Path | None = None,
        materialize_to_canonical_closed_day: bool = False,
    ) -> dict[str, Any]:
        repo_root = (root or ROOT).resolve()
        source_paths = self.resolve_source_paths(root=repo_root)

        summary_row = _read_single_csv_row_required(source_paths["strategy_summary"])
        paper_df = _read_dataframe_required(source_paths["strategy_paper"])
        trend_status_row = _read_single_csv_row_required(source_paths["trend_status"])
        trend_history_df = _read_dataframe_required(source_paths["trend_history"])
        freshness_payload = _read_json_required(source_paths["freshness_report"])
        benchmark_df = _prepare_btc_benchmark_frame(
            _read_dataframe_required(source_paths["benchmark_ohlcv"])
        )

        closed_day = _normalize_iso_day_text(
            summary_row.get("latest_available_date"),
            context="strategy_summary.latest_available_date",
        )
        paper_last_day = _normalize_iso_day_text(
            paper_df["date"].iloc[-1],
            context="strategy_paper.last_row.date",
        )
        trend_status_day = _normalize_iso_day_text(
            trend_status_row.get("latest_available_date"),
            context="trend_status.latest_available_date",
        )
        trend_history_last_day = _normalize_iso_day_text(
            trend_history_df["trend_calc_date"].iloc[-1]
            if "trend_calc_date" in trend_history_df.columns
            else trend_history_df["date"].iloc[-1],
            context="trend_history.last_row.day",
        )
        freshness_closed_day = _normalize_iso_day_text(
            freshness_payload.get("latest_closed_utc_date"),
            context="freshness_report.latest_closed_utc_date",
        )
        benchmark_last_day = _normalize_iso_day_text(
            benchmark_df["date"].iloc[-1].strftime("%Y-%m-%d"),
            context="benchmark_ohlcv.last_row.date",
        )
        freshness_status = str(freshness_payload.get("status") or "").strip().lower()
        freshness_errors = freshness_payload.get("errors")
        if freshness_status not in {"ok", "success", "current"}:
            raise ValueError(
                f"freshness_report.status must be green for production build (actual={freshness_status or 'missing'})"
            )
        if isinstance(freshness_errors, list) and freshness_errors:
            raise ValueError("freshness_report.errors must be empty for production build")

        config = NetCostExportConfig(
            annual_borrow_cost=_to_float(
                summary_row.get("annual_borrow_cost_pct"),
                context="strategy_summary.annual_borrow_cost_pct",
            )
            / 100.0,
            tradable_transition_slippage_bps=_to_float(
                summary_row.get("tradable_transition_slippage_bps"),
                context="strategy_summary.tradable_transition_slippage_bps",
            ),
            fee_side_mode=str(summary_row.get("fee_side_mode") or "").strip() or "taker",
            taker_fee_bps=_to_float(summary_row.get("taker_fee_bps"), context="strategy_summary.taker_fee_bps"),
            maker_fee_bps=_to_float(summary_row.get("maker_fee_bps"), context="strategy_summary.maker_fee_bps"),
            staking_discount_pct=_to_float(
                summary_row.get("staking_discount_pct"),
                context="strategy_summary.staking_discount_pct",
            ),
            referral_discount_pct=_to_float(
                summary_row.get("referral_discount_pct"),
                context="strategy_summary.referral_discount_pct",
            ),
        )

        inputs = {
            "repo_root": repo_root,
            "source_paths": source_paths,
            "summary_row": summary_row,
            "paper_df": paper_df,
            "trend_status_row": trend_status_row,
            "trend_history_df": trend_history_df,
            "freshness_payload": freshness_payload,
            "benchmark_df": benchmark_df,
            "closed_day": closed_day,
            "paper_last_day": paper_last_day,
            "trend_status_day": trend_status_day,
            "trend_history_last_day": trend_history_last_day,
            "freshness_closed_day": freshness_closed_day,
            "benchmark_last_day": benchmark_last_day,
            "config": config,
        }

        if not materialize_to_canonical_closed_day:
            if benchmark_last_day != closed_day:
                raise ValueError(
                    "benchmark_ohlcv last date must match the production closed day "
                    f"(actual={benchmark_last_day} expected={closed_day})"
                )
            return inputs

        if paper_last_day != closed_day:
            raise ValueError(
                "strategy_paper last_row.date must match strategy_summary.latest_available_date "
                f"(paper={paper_last_day} summary={closed_day})"
            )
        if trend_history_last_day != trend_status_day:
            raise ValueError(
                "trend_history last day must match trend_status latest_available_date "
                f"(trend_history={trend_history_last_day} trend_status={trend_status_day})"
            )
        if freshness_closed_day != trend_status_day:
            raise ValueError(
                "freshness_report latest_closed_utc_date must match trend_status latest_available_date "
                f"(freshness={freshness_closed_day} trend_status={trend_status_day})"
            )

        canonical_closed_day = freshness_closed_day
        if pd.Timestamp(canonical_closed_day) < pd.Timestamp(closed_day):
            raise ValueError(
                "Canonical closed day cannot be behind the validated phase68g source day "
                f"(canonical={canonical_closed_day} source={closed_day})"
            )
        if pd.Timestamp(canonical_closed_day) > pd.Timestamp(benchmark_last_day):
            raise ValueError(
                "benchmark_ohlcv must cover the canonical closed day for dependency materialization "
                f"(btc_last_day={benchmark_last_day} canonical_closed_day={canonical_closed_day})"
            )
        if pd.Timestamp(canonical_closed_day) > pd.Timestamp(closed_day):
            next_rebalance_text = str(trend_status_row.get("next_rebalance_date") or "").strip()
            if not next_rebalance_text:
                raise ValueError(
                    "Cannot materialize stale phase68g baseline without next_rebalance_date on the trend status row"
                )
            next_rebalance_day = _normalize_iso_day_text(
                next_rebalance_text,
                context="trend_status.next_rebalance_date",
            )
            if pd.Timestamp(canonical_closed_day) >= pd.Timestamp(next_rebalance_day):
                raise ValueError(
                    "phase68g baseline dependency materialization would cross a rebalance boundary "
                    f"(source_day={closed_day} target_day={canonical_closed_day} "
                    f"next_rebalance_date={next_rebalance_day})"
                )
            source_timeseries = self.build_timeseries(inputs)
            materialized_timeseries, paper_materialization = _materialize_strategy_timeseries_to_closed_day(
                timeseries=source_timeseries,
                summary_row=summary_row,
                benchmark_df=benchmark_df,
                target_closed_day=canonical_closed_day,
            )
            inputs = dict(inputs)
            inputs["source_closed_day"] = closed_day
            inputs["closed_day"] = canonical_closed_day
            inputs["materialized_timeseries"] = materialized_timeseries
            inputs["paper_materialization"] = {
                "summary_latest_available_date": closed_day,
                "summary_source_last_day": closed_day,
                "trend_source_last_day": trend_status_day,
                "freshness_source_closed_day": freshness_closed_day,
                "next_rebalance_date": next_rebalance_day,
                **paper_materialization,
            }
        else:
            inputs = dict(inputs)
            inputs["source_closed_day"] = closed_day

        return inputs

    def build_timeseries(self, inputs: dict[str, Any]) -> pd.DataFrame:
        materialized_timeseries = inputs.get("materialized_timeseries")
        if isinstance(materialized_timeseries, pd.DataFrame):
            return materialized_timeseries.copy()
        paper_df = inputs["paper_df"].copy()
        benchmark_df = inputs["benchmark_df"].copy()
        model_export_df = build_net_cost_export_frame(
            paper_df,
            date_col="date",
            gross_return_col="realistic_ret_gross",
            held_asset_col="portfolio_held_asset",
            leverage_col="effective_leverage",
            daily_borrow_cost_col="daily_borrow_cost",
            tradable_slippage_cost_col="tradable_slippage_cost",
            config=inputs["config"],
        )

        candidate_asset = model_export_df["held_asset"].astype(str).map(_normalize_asset_code)
        trend_block_day = _to_bool_series(paper_df["trend_block_day"])
        stress_block_day = _to_bool_series(paper_df["stress_block_day"])
        trend_gate_pass = _to_bool_series(paper_df["trend_gate_pass"])
        trend_permission_active = pd.Series(
            [
                _resolve_trend_permission_active(
                    trend_gate_pass=bool(gate_pass),
                    stress_block_day=bool(stress_block),
                )
                for gate_pass, stress_block in zip(
                    trend_gate_pass.tolist(),
                    stress_block_day.tolist(),
                )
            ],
            index=paper_df.index,
        )
        model_candidate_exposure = np.where(
            candidate_asset.isin(CASH_EQUIVALENT_ASSETS),
            0.0,
            model_export_df["effective_leverage"],
        )
        actual_held_asset = np.where(trend_permission_active, candidate_asset, "CASH")
        effective_market_exposure = np.where(
            trend_permission_active,
            model_candidate_exposure,
            0.0,
        )
        authorized_input_df = pd.DataFrame(
            {
                "date": model_export_df["date"],
                "authorized_return_gross": np.where(
                    effective_market_exposure > 0.0,
                    model_export_df["gross_return"],
                    0.0,
                ),
                "authorized_held_asset": actual_held_asset,
                "authorized_effective_leverage": effective_market_exposure,
            }
        )
        authorized_export_df = build_net_cost_export_frame(
            authorized_input_df,
            date_col="date",
            gross_return_col="authorized_return_gross",
            held_asset_col="authorized_held_asset",
            leverage_col="authorized_effective_leverage",
            config=inputs["config"],
        )
        benchmark_aligned = pd.DataFrame({"date": model_export_df["date"]}).merge(
            benchmark_df,
            on="date",
            how="left",
        )
        if benchmark_aligned["btc_close"].isna().any():
            missing_dates = (
                benchmark_aligned.loc[benchmark_aligned["btc_close"].isna(), "date"]
                .dt.strftime("%Y-%m-%d")
                .head(5)
                .tolist()
            )
            raise ValueError(
                "benchmark_ohlcv is missing rows required for Production Core timeseries "
                f"(examples: {', '.join(missing_dates)})"
            )
        btc_return = benchmark_aligned["btc_close"].pct_change().fillna(0.0)
        btc_baseline_equity = (1.0 + btc_return).cumprod()
        btc_baseline_index = btc_baseline_equity * 100.0

        timeseries = pd.DataFrame()
        timeseries["date"] = model_export_df["date"].dt.strftime("%Y-%m-%d")
        timeseries["strategy_id"] = self.strategy_id
        timeseries["strategy_version"] = self.strategy_version
        timeseries["candidate_asset"] = candidate_asset
        timeseries["selected_asset"] = candidate_asset
        timeseries["model_candidate_exposure"] = model_candidate_exposure
        timeseries["trend_permission_active"] = trend_permission_active
        timeseries["actual_held_asset"] = actual_held_asset
        timeseries["authorized_tradable_asset"] = actual_held_asset
        timeseries["held_asset"] = actual_held_asset
        timeseries["current_asset"] = actual_held_asset
        timeseries["effective_market_exposure"] = effective_market_exposure
        timeseries["current_exposure"] = effective_market_exposure
        timeseries["exposure"] = effective_market_exposure
        timeseries["regime"] = timeseries["held_asset"].map(_classify_regime)
        timeseries["market_state"] = np.where(
            timeseries["effective_market_exposure"] > 0.0,
            "IN_MARKET",
            "OUT_OF_MARKET",
        )
        timeseries["execution_state"] = np.where(
            timeseries["effective_market_exposure"] > 0.0,
            timeseries["held_asset"],
            "OUT_OF_MARKET",
        )
        timeseries["execution_target_asset"] = np.where(
            timeseries["effective_market_exposure"] > 0.0,
            timeseries["held_asset"],
            "CASH",
        )
        timeseries["execution_target_exposure"] = timeseries["effective_market_exposure"]
        timeseries["trend_state"] = paper_df["trend_state_label"].fillna("").astype(str)
        timeseries["trend_score"] = _to_float_series(paper_df["trend_score"])
        timeseries["buy_threshold"] = _to_float_series(paper_df["buy_threshold"])
        timeseries["model_candidate_return_gross"] = model_export_df["gross_return"]
        timeseries["model_candidate_return_net"] = model_export_df["net_return"]
        timeseries["model_candidate_equity"] = model_export_df["equity_curve_net"]
        timeseries["authorized_return_gross"] = authorized_export_df["gross_return"]
        timeseries["authorized_return_net"] = authorized_export_df["net_return"]
        timeseries["authorized_equity"] = authorized_export_df["equity_curve_net"]
        timeseries["btc_close"] = benchmark_aligned["btc_close"]
        timeseries["btc_return"] = btc_return
        timeseries["btc_baseline_equity"] = btc_baseline_equity
        timeseries["btc_baseline_index"] = btc_baseline_index
        timeseries["return_gross"] = timeseries["authorized_return_gross"]
        timeseries["return_net"] = timeseries["authorized_return_net"]
        timeseries["equity"] = timeseries["authorized_equity"]
        drawdown = (timeseries["authorized_equity"] / timeseries["authorized_equity"].cummax()) - 1.0
        timeseries["drawdown_pct"] = drawdown * 100.0
        timeseries["fees_daily"] = authorized_export_df["trading_fees_daily"]
        timeseries["fees_cumulative"] = authorized_export_df["trading_fees_daily"].cumsum()
        timeseries["funding_daily"] = authorized_export_df["funding_daily"]
        timeseries["funding_cumulative"] = authorized_export_df["funding_daily"].cumsum()
        timeseries["borrow_cost_daily"] = authorized_export_df["daily_borrow_cost"]
        timeseries["borrow_cost_cumulative"] = authorized_export_df["daily_borrow_cost"].cumsum()
        timeseries["slippage_cost_daily"] = authorized_export_df["tradable_slippage_cost"]
        timeseries["slippage_cost_cumulative"] = authorized_export_df["tradable_slippage_cost"].cumsum()
        timeseries["turnover"] = authorized_export_df["trading_turnover_notional"]
        timeseries["cash_day"] = timeseries["effective_market_exposure"] <= 0.0
        timeseries["btc_day"] = (timeseries["held_asset"] == "BTC") & (
            timeseries["effective_market_exposure"] > 0.0
        )
        timeseries["in_market"] = timeseries["effective_market_exposure"] > 0.0
        timeseries["is_rebalance_day"] = authorized_export_df["asset_transition_day"].astype(bool)
        timeseries["asset_transition_day"] = authorized_export_df["asset_transition_day"].astype(bool)
        timeseries["trend_block_day"] = trend_block_day
        timeseries["stress_block_day"] = stress_block_day
        timeseries["trend_gate_pass"] = trend_gate_pass
        timeseries["leverage_active"] = _to_bool_series(paper_df["leverage_active"])
        timeseries["leverage_state_reason"] = paper_df["leverage_state_reason"].fillna("").astype(str)
        timeseries["trend_activation_threshold"] = _to_float_series(
            paper_df["trend_activation_threshold"]
        )
        timeseries["reason_code"] = timeseries.apply(_build_reason_code, axis=1)
        timeseries["rolling_return_7d"] = _rolling_compound_return(timeseries["return_net"], 7)
        timeseries["rolling_return_30d"] = _rolling_compound_return(timeseries["return_net"], 30)
        timeseries["rolling_return_90d"] = _rolling_compound_return(timeseries["return_net"], 90)
        timeseries["rolling_vol_30d"] = (
            timeseries["return_net"].rolling(window=30, min_periods=30).std(ddof=0) * np.sqrt(365.25)
        )
        timeseries["rolling_sharpe_90d"] = _rolling_sharpe(timeseries["return_net"], 90)
        timeseries["source_validated"] = True
        return timeseries

    def summarize_source_metrics(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "strategy_summary": _source_file_metadata(
                inputs["source_paths"]["strategy_summary"],
                last_date=inputs["closed_day"],
                row_count=1,
            ),
            "strategy_paper": _source_file_metadata(
                inputs["source_paths"]["strategy_paper"],
                last_date=inputs["paper_last_day"],
                row_count=len(inputs["paper_df"]),
            ),
            "trend_status": _source_file_metadata(
                inputs["source_paths"]["trend_status"],
                last_date=inputs["trend_status_day"],
                row_count=1,
            ),
            "trend_history": _source_file_metadata(
                inputs["source_paths"]["trend_history"],
                last_date=inputs["trend_history_last_day"],
                row_count=len(inputs["trend_history_df"]),
            ),
            "freshness_report": {
                **_source_file_metadata(
                    inputs["source_paths"]["freshness_report"],
                    last_date=inputs["freshness_closed_day"],
                ),
                "status": str(inputs["freshness_payload"].get("status") or "").strip().lower(),
            },
            "benchmark_ohlcv": _source_file_metadata(
                inputs["source_paths"]["benchmark_ohlcv"],
                last_date=inputs["benchmark_last_day"],
                row_count=len(inputs["benchmark_df"]),
            ),
        }

    def build_source_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter_name": self.adapter_name,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "validated_closed_day": inputs["closed_day"],
            "files": self.summarize_source_metrics(inputs),
        }

    def derive_summary_from_timeseries(
        self,
        inputs: dict[str, Any],
        timeseries: pd.DataFrame,
    ) -> dict[str, Any]:
        authorized_switch_count = int(timeseries["asset_transition_day"].astype(bool).sum())
        export_df = pd.DataFrame(
            {
                "date": pd.to_datetime(timeseries["date"], errors="coerce"),
                "gross_return": timeseries["authorized_return_gross"],
                "net_return": timeseries["authorized_return_net"],
                "held_asset": timeseries["held_asset"],
                "trading_fees_daily": timeseries["fees_daily"],
                "funding_daily": timeseries["funding_daily"],
                "daily_borrow_cost": timeseries["borrow_cost_daily"],
                "tradable_slippage_cost": timeseries["slippage_cost_daily"],
                "asset_transition_day": timeseries["asset_transition_day"],
                "annual_borrow_cost_pct": float(inputs["summary_row"]["annual_borrow_cost_pct"]),
                "tradable_transition_slippage_bps": float(
                    inputs["summary_row"]["tradable_transition_slippage_bps"]
                ),
                "fee_side_mode": inputs["summary_row"]["fee_side_mode"],
                "taker_fee_bps": float(inputs["summary_row"]["taker_fee_bps"]),
                "maker_fee_bps": float(inputs["summary_row"]["maker_fee_bps"]),
                "staking_discount_pct": float(inputs["summary_row"]["staking_discount_pct"]),
                "referral_discount_pct": float(inputs["summary_row"]["referral_discount_pct"]),
                "effective_trading_fee_bps": float(inputs["summary_row"]["effective_trading_fee_bps"]),
            }
        )
        return summarize_net_cost_export(
            export_df,
            model=self.strategy_version,
            switch_count=authorized_switch_count,
            trade_count=authorized_switch_count,
        )

    def source_summary_metrics(self, inputs: dict[str, Any]) -> dict[str, Any]:
        summary = inputs["summary_row"]
        return {
            "total_return_pct_net": _to_float(summary["total_return_pct_net"], context="summary.total_return_pct_net"),
            "cagr_pct_net": _to_float(summary["cagr_pct_net"], context="summary.cagr_pct_net"),
            "max_drawdown_pct_net": _to_float(
                summary["max_drawdown_pct_net"], context="summary.max_drawdown_pct_net"
            ),
            "since2023_cagr_pct_net": _to_float(
                summary["since2023_cagr_pct_net"],
                context="summary.since2023_cagr_pct_net",
            ),
            "since2025_cagr_pct_net": _to_float(
                summary["since2025_cagr_pct_net"],
                context="summary.since2025_cagr_pct_net",
            ),
            "trading_fees_total_pct": _to_float(
                summary["trading_fees_total_pct"], context="summary.trading_fees_total_pct"
            ),
            "funding_total_pct": _to_float(summary["funding_total_pct"], context="summary.funding_total_pct"),
            "borrow_cost_total_pct": _to_float(
                summary["borrow_cost_total_pct"], context="summary.borrow_cost_total_pct"
            ),
            "slippage_cost_total_pct": _to_float(
                summary["tradable_slippage_cost_total_pct"],
                context="summary.tradable_slippage_cost_total_pct",
            ),
            "cash_days_pct": _to_float(summary["cash_days_pct"], context="summary.cash_days_pct"),
            "btc_days_pct": _to_float(summary["btc_days_pct"], context="summary.btc_days_pct"),
            "switch_count": _to_int(summary["switch_count"], context="summary.switch_count"),
            "trade_count": _to_int(summary["trade_count"], context="summary.trade_count"),
        }

    def build_snapshot_metrics(self, inputs: dict[str, Any], timeseries: pd.DataFrame) -> dict[str, Any]:
        derived_summary = self.derive_summary_from_timeseries(inputs, timeseries)
        sharpe = _annualized_sharpe_from_daily_returns(timeseries["authorized_return_net"])
        sortino = _annualized_sortino_from_daily_returns(timeseries["authorized_return_net"])
        if sharpe is None or not np.isfinite(sharpe):
            raise ValueError("Unable to compute authorized Sharpe ratio from Production Core timeseries")
        if sortino is None or not np.isfinite(sortino):
            raise ValueError(
                "Unable to compute authorized Sortino ratio from Production Core timeseries"
            )
        return {
            "total_return_pct_net": round(float(derived_summary["total_return_pct_net"]), 4),
            "cagr_pct_net": round(float(derived_summary["cagr_pct_net"]), 4),
            "max_drawdown_pct_net": round(float(derived_summary["max_drawdown_pct_net"]), 4),
            "since2023_cagr_pct_net": round(float(derived_summary["since2023_cagr_pct_net"]), 4),
            "since2025_cagr_pct_net": round(float(derived_summary["since2025_cagr_pct_net"]), 4),
            "sharpe": round(float(sharpe), 4),
            "sortino": round(float(sortino), 4),
            "trading_fees_total_pct": round(float(derived_summary["trading_fees_total_pct"]), 6),
            "funding_total_pct": round(float(derived_summary["funding_total_pct"]), 6),
            "borrow_cost_total_pct": round(float(derived_summary["borrow_cost_total_pct"]), 6),
            "slippage_cost_total_pct": round(
                float(derived_summary["tradable_slippage_cost_total_pct"]),
                6,
            ),
            "cash_days_pct": round(float(derived_summary["cash_days_pct"]), 6),
            "btc_days_pct": round(float(derived_summary["btc_days_pct"]), 6),
            "switch_count": int(derived_summary["switch_count"]),
            "trade_count": int(derived_summary["trade_count"]),
        }

    def build_decision_context(self, timeseries: pd.DataFrame) -> dict[str, Any]:
        current_row = timeseries.iloc[-1]
        dates = pd.to_datetime(timeseries["date"], errors="coerce")
        latest_rebalance_rows = timeseries.loc[timeseries["is_rebalance_day"]]
        latest_rebalance_date = (
            None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["date"])
        )
        current_regime_duration_days = _consecutive_tail_length(timeseries["regime"])
        current_cash_streak_days = (
            _consecutive_tail_length(timeseries["cash_day"]) if bool(current_row["cash_day"]) else 0
        )
        risk_on_entry_mask = (~timeseries["cash_day"]) & timeseries["cash_day"].shift(1, fill_value=True)
        return {
            "current_reason_code": str(current_row["reason_code"]),
            "current_reason_text": build_reason_text(current_row),
            "current_regime_duration_days": int(current_regime_duration_days),
            "days_since_last_trade": _days_since_last_true(timeseries["is_rebalance_day"], dates),
            "days_since_last_risk_on": _days_since_last_true(risk_on_entry_mask, dates),
            "days_since_last_equity_high": _days_since_last_true(
                timeseries["equity"] == timeseries["equity"].cummax(),
                dates,
            ),
            "current_drawdown_pct": round(float(current_row["drawdown_pct"]), 6),
            "current_cash_streak_days": int(current_cash_streak_days),
            "latest_rebalance_date": latest_rebalance_date,
            "latest_rebalance_reason": (
                None if latest_rebalance_rows.empty else str(latest_rebalance_rows.iloc[-1]["reason_code"])
            ),
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
        recent_regime_rows = timeseries.loc[
            timeseries["regime"] != timeseries["regime"].shift(1, fill_value=timeseries["regime"].iloc[0])
        ].tail(5)
        recent_rebalance_rows = timeseries.loc[timeseries["is_rebalance_day"]].tail(5)
        trailing_30 = timeseries.tail(30)
        trailing_90 = timeseries.tail(90)
        lifetime_cost_pct = (
            float(timeseries["fees_daily"].sum())
            + float(timeseries["funding_daily"].sum())
            + float(timeseries["borrow_cost_daily"].sum())
            + float(timeseries["slippage_cost_daily"].sum())
        ) * 100.0
        churn_status = "elevated" if float(trailing_90["turnover"].sum()) >= 8.0 else "contained"
        fee_status = "elevated" if lifetime_cost_pct >= 20.0 else "contained"
        cash_days_pct = float(self.build_snapshot_metrics(inputs, timeseries)["cash_days_pct"])
        cash_status = "elevated" if cash_days_pct >= 40.0 else "contained"
        flatline_days = (
            self.build_decision_context(timeseries)["current_cash_streak_days"]
            if bool(current_row["cash_day"])
            else 0
        )
        diagnostics = {
            "artifact_type": "current_strategy_diagnostics",
            "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
            "generated_at_utc": generated_at_utc,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "closed_day": inputs["closed_day"],
            "latest_state_explanation": build_reason_text(current_row),
            "current_flatline_explanation": (
                f"Authorized capital should stay flat during the current CASH streak of {flatline_days} days "
                "because no market exposure is currently allowed."
                if flatline_days > 0
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
                "summary_latest_available_date": inputs["closed_day"],
                "paper_last_day": inputs["paper_last_day"],
                "trend_status_day": inputs["trend_status_day"],
                "trend_history_last_day": inputs["trend_history_last_day"],
                "freshness_closed_day": inputs["freshness_closed_day"],
                "freshness_status": str(inputs["freshness_payload"].get("status") or "").strip().lower(),
                "freshness_errors": inputs["freshness_payload"].get("errors", []),
                "warnings": validation["warnings"],
            },
            "strategy_improvement_signals": {
                "churn_pressure": {
                    "status": churn_status,
                    "trade_count": int(self.build_snapshot_metrics(inputs, timeseries)["trade_count"]),
                    "switch_count": int(self.build_snapshot_metrics(inputs, timeseries)["switch_count"]),
                    "trailing_90d_turnover": round(float(trailing_90["turnover"].sum()), 6),
                },
                "fee_sensitivity": {
                    "status": fee_status,
                    "lifetime_total_cost_pct": round(lifetime_cost_pct, 6),
                    "effective_trading_fee_bps": _to_float(
                        inputs["summary_row"]["effective_trading_fee_bps"],
                        context="summary.effective_trading_fee_bps",
                    ),
                },
                "cash_drag": {
                    "status": cash_status,
                    "cash_days_pct": round(cash_days_pct, 6),
                    "current_cash_streak_days": int(
                        self.build_decision_context(timeseries)["current_cash_streak_days"]
                    ),
                },
                "flatline_duration": {
                    "status": "active" if flatline_days > 0 else "inactive",
                    "current_cash_streak_days": int(flatline_days),
                },
                "current_research_questions": [
                    "Can churn be reduced without losing the current net-return profile?",
                    "Is the current trend confirmation gate too conservative when BTC stays the candidate but market entry remains blocked?",
                    "How much of lifetime cost drag comes from transition frequency versus borrow carry?",
                ],
            },
            "validation": {
                "status": validation["status"],
                "errors": list(validation["errors"]),
                "warnings": list(validation["warnings"]),
            },
        }
        return diagnostics

    def compare_summary_metrics(
        self,
        *,
        inputs: dict[str, Any],
        timeseries: pd.DataFrame,
    ) -> list[str]:
        del inputs, timeseries
        return []
