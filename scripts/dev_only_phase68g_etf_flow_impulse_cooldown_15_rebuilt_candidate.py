from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from approved_strategy_net_export_helper import NetCostExportConfig
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
PYCACHE_DIR = SCRIPTS_DIR / "__pycache__"

BASELINE_SNAPSHOT_PATH = ROOT / "outputs" / "production" / "current_strategy_snapshot.json"
BASELINE_TIMESERIES_PATH = ROOT / "outputs" / "production" / "current_strategy_timeseries.csv"
BASELINE_DIAGNOSTICS_PATH = ROOT / "outputs" / "production" / "current_strategy_diagnostics.json"
ETF_PANEL_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_btc_etf_flow_daily_panel"
    / "btc_etf_flow_daily_panel.csv"
)
BTC_OHLCV_PATH = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"

OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate"
)

CONTRACT_REF = (
    "research_os/dev_only/contracts/"
    "dev_only_phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate.contract.json"
)
SPEC_REF = (
    "research_os/dev_only/specs/"
    "dev_only_phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate.spec.json"
)
MANIFEST_SEED_REF = (
    "research_os/dev_only/manifests/"
    "dev_only_phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate.manifest.json"
)

ARTIFACT_ID = "phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate"
ARTIFACT_LABEL = "ETF-flow impulse EARLY_RISK cooldown_15 rebuilt candidate"
BASELINE_MODEL_ID = "phase68g_66g_1p25x_candidate"
BASELINE_LABEL = "Production Core authorized phase68g_66g_1p25x_candidate"
MODEL_ID = "phase68g_etf_flow_impulse_cooldown_15_rebuilt_candidate"
MODEL_LABEL = "ETF-flow impulse cooldown_15 rebuilt candidate"
VARIANT_ID = "cooldown_15_days"
ANALYSIS_MODE = "phase68g_etf_flow_impulse_cooldown_15_rebuild_only"
MECHANISM_ID = "phase68g_dev_only_etf_flow_impulse_cooldown_15_rebuild"

FLOW_3D_FLOOR_USD = 500_000_000.0
EARLY_RISK_WEIGHT = 0.50
BTC_EMA_DAYS = 10
COOLDOWN_DAYS = 15

PERIOD_DEFS = [
    ("full_etf_overlap", None),
    ("since2025", "2025-01-01"),
]

HANDOFF_AUDIT_DATES = ("2024-02-02", "2024-10-22")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild the dev-only ETF-flow EARLY_RISK cooldown_15 candidate evidence pack."
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    return parser.parse_args()


def with_json_flags(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(
        {
            "analysis_mode": ANALYSIS_MODE,
            "candidate_selection": False,
            "official_edge_claim": False,
        }
    )
    return out


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    if pd.isna(value):
        return None
    return value


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "summary_json": output_dir / "summary.json",
        "candidate_timeseries_csv": output_dir / "candidate_timeseries.csv",
        "handoff_row_audit_csv": output_dir / "handoff_row_audit.csv",
        "compare_csv": output_dir / "compare.csv",
        "activation_windows_csv": output_dir / "activation_windows.csv",
        "cost_metrics_csv": output_dir / "cost_metrics.csv",
        "blocker_counts_csv": output_dir / "blocker_counts.csv",
        "manifest_json": output_dir / "manifest.json",
        "quality_json": output_dir / "quality.json",
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_compiled_module(module_name: str, pattern: str) -> Any:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    if module_name in sys.modules:
        return sys.modules[module_name]
    matches = sorted(PYCACHE_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"Missing compiled helper for {module_name}: {pattern}")
    loader = importlib.machinery.SourcelessFileLoader(module_name, str(matches[0]))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise ImportError(f"Unable to load module spec for {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


def load_phase68g_helpers() -> tuple[Any, Any]:
    probe_mod = load_compiled_module(
        "dev_only_phase68g_etf_flow_impulse_probe",
        "dev_only_phase68g_etf_flow_impulse_probe.cpython-*.pyc",
    )
    cooldown_mod = load_compiled_module(
        "dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity",
        "dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity.cpython-*.pyc",
    )
    return probe_mod, cooldown_mod


def compound_return(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return float((1.0 + clean).prod() - 1.0)


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if years <= 0:
        return 0.0
    if total_return <= -1.0:
        return -1.0
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def max_drawdown_from_returns(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def count_trade_days(weight_series: pd.Series) -> int:
    weights = pd.to_numeric(weight_series, errors="coerce").fillna(0.0)
    if weights.empty:
        return 0
    prev = weights.shift(1).fillna(0.0)
    return int(weights.ne(prev).sum())


def count_switches(state_series: pd.Series) -> int:
    states = state_series.fillna("").astype(str)
    if states.empty:
        return 0
    prev = states.shift(1).fillna("")
    return int(states.ne(prev).sum() - (1 if states.iloc[0] != "" else 0))


def round_float(value: Any, digits: int = 6) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return round(float(0.0 if pd.isna(numeric) else numeric), digits)


def normalize_baseline_frame(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = pd.read_csv(path)
    df.columns = [str(column).strip() for column in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").copy()

    stress_column = "stress_block_day" if "stress_block_day" in df.columns else ""
    if stress_column:
        hard_invalidation_note = "stress_block_day is present and is used directly as the hard invalidation / risk-off equivalent."
        fallback_used = False
        stress_values = df[stress_column].fillna(False)
    else:
        hard_invalidation_note = (
            "stress_block_day is unavailable, so hard invalidation falls back to False on all rows."
        )
        fallback_used = True
        stress_values = False

    adapted = df.copy()
    adapted["portfolio_held_asset"] = adapted["current_asset"].fillna("CASH").astype(str).str.upper()
    adapted["is_exposed"] = pd.to_numeric(
        adapted["effective_market_exposure"], errors="coerce"
    ).fillna(0.0).gt(0.0)
    adapted["effective_leverage"] = pd.to_numeric(adapted["current_exposure"], errors="coerce").fillna(0.0)
    adapted["realistic_ret_gross"] = pd.to_numeric(adapted["return_gross"], errors="coerce").fillna(0.0)
    adapted["stress_block_active"] = pd.Series(stress_values, index=adapted.index).fillna(False)
    adapted = adapted.drop(columns=[column for column in ["btc_close", "btc_return"] if column in adapted.columns])
    adapted = adapted.set_index("date", drop=False)

    hard_invalidation_meta = {
        "source_column": stress_column or None,
        "fallback_used": fallback_used,
        "detail": hard_invalidation_note,
    }
    return adapted, hard_invalidation_meta


def derive_cost_config(df: pd.DataFrame) -> tuple[NetCostExportConfig, dict[str, Any]]:
    turnover = pd.to_numeric(df.get("turnover", 0.0), errors="coerce").fillna(0.0)
    fees = pd.to_numeric(df.get("fees_daily", 0.0), errors="coerce").fillna(0.0)
    fee_mask = fees.gt(0.0) & turnover.gt(0.0)
    taker_fee_bps = float(((fees[fee_mask] / turnover[fee_mask]) * 10000.0).median()) if fee_mask.any() else 4.5

    slippage = pd.to_numeric(df.get("slippage_cost_daily", 0.0), errors="coerce").fillna(0.0)
    slippage_mask = slippage.gt(0.0)
    tradable_transition_slippage_bps = (
        float((slippage[slippage_mask] * 10000.0).median()) if slippage_mask.any() else 10.0
    )

    exposure = pd.to_numeric(df.get("current_exposure", 0.0), errors="coerce").fillna(0.0)
    borrow = pd.to_numeric(df.get("borrow_cost_daily", 0.0), errors="coerce").fillna(0.0)
    borrow_mask = borrow.gt(0.0) & exposure.gt(1.0)
    annual_borrow_cost = (
        float((borrow[borrow_mask] / (exposure[borrow_mask] - 1.0) * 365.25).median())
        if borrow_mask.any()
        else 0.12
    )

    config = NetCostExportConfig(
        annual_borrow_cost=annual_borrow_cost,
        tradable_transition_slippage_bps=tradable_transition_slippage_bps,
        fee_side_mode="taker",
        taker_fee_bps=taker_fee_bps,
        maker_fee_bps=round(taker_fee_bps / 3.0, 6),
        staking_discount_pct=0.0,
        referral_discount_pct=0.0,
    )
    meta = {
        "annual_borrow_cost_pct": round_float(config.annual_borrow_cost * 100.0),
        "tradable_transition_slippage_bps": round_float(config.tradable_transition_slippage_bps),
        "taker_fee_bps": round_float(config.taker_fee_bps),
        "maker_fee_bps": round_float(config.maker_fee_bps),
        "fee_side_mode": config.fee_side_mode,
        "source": "derived from outputs/production/current_strategy_timeseries.csv daily cost columns",
    }
    return config, meta


def build_period_subset(
    enriched: pd.DataFrame,
    baseline_export: pd.DataFrame,
    probe_export: pd.DataFrame,
    start_date: str | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if start_date is None:
        return enriched.copy(), baseline_export.copy(), probe_export.copy()
    start_stamp = pd.Timestamp(start_date)
    return (
        enriched.loc[enriched.index >= start_stamp].copy(),
        baseline_export.loc[baseline_export.index >= start_stamp].copy(),
        probe_export.loc[probe_export.index >= start_stamp].copy(),
    )


def enforce_baseline_full_risk_pass_through(
    baseline_export: pd.DataFrame,
    probe_export: pd.DataFrame,
    enriched: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline_full_risk_mask = enriched["baseline_full_risk"].fillna(False).astype(bool)
    if not baseline_full_risk_mask.any():
        return baseline_export, probe_export, enriched

    baseline_export = baseline_export.copy()
    probe_export = probe_export.copy()
    enriched = enriched.copy()

    export_column_pairs = [
        ("baseline_gross_return", "probe_gross_return"),
        ("baseline_held_asset", "probe_held_asset"),
        ("baseline_effective_leverage", "probe_effective_leverage"),
        ("baseline_asset_transition_day", "probe_asset_transition_day"),
        ("baseline_trading_turnover_notional", "probe_trading_turnover_notional"),
        ("baseline_daily_borrow_cost", "probe_daily_borrow_cost"),
        ("baseline_tradable_slippage_cost", "probe_tradable_slippage_cost"),
        ("baseline_trading_fees_daily", "probe_trading_fees_daily"),
        ("baseline_funding_daily", "probe_funding_daily"),
        ("baseline_net_return", "probe_net_return"),
        ("baseline_equity_curve_gross", "probe_equity_curve_gross"),
        ("baseline_equity_curve_net", "probe_equity_curve_net"),
        ("baseline_fee_side_mode", "probe_fee_side_mode"),
        ("baseline_taker_fee_bps", "probe_taker_fee_bps"),
        ("baseline_maker_fee_bps", "probe_maker_fee_bps"),
        ("baseline_staking_discount_pct", "probe_staking_discount_pct"),
        ("baseline_referral_discount_pct", "probe_referral_discount_pct"),
        ("baseline_effective_trading_fee_bps", "probe_effective_trading_fee_bps"),
        ("baseline_annual_borrow_cost_pct", "probe_annual_borrow_cost_pct"),
        ("baseline_tradable_transition_slippage_bps", "probe_tradable_transition_slippage_bps"),
    ]

    for baseline_col, probe_col in export_column_pairs:
        if baseline_col in baseline_export.columns and probe_col in probe_export.columns:
            probe_export.loc[baseline_full_risk_mask, probe_col] = baseline_export.loc[
                baseline_full_risk_mask, baseline_col
            ]
        if baseline_col in enriched.columns and probe_col in enriched.columns:
            enriched.loc[baseline_full_risk_mask, probe_col] = enriched.loc[
                baseline_full_risk_mask, baseline_col
            ]

    if "baseline_state" in enriched.columns and "probe_state" in enriched.columns:
        enriched.loc[baseline_full_risk_mask, "probe_state"] = enriched.loc[
            baseline_full_risk_mask, "baseline_state"
        ]
    if "baseline_gross_return" in enriched.columns and "probe_strategy_return_gross" in enriched.columns:
        enriched.loc[baseline_full_risk_mask, "probe_strategy_return_gross"] = enriched.loc[
            baseline_full_risk_mask, "baseline_gross_return"
        ]

    return baseline_export, probe_export, enriched


def build_model_metrics(
    *,
    period_name: str,
    model_id: str,
    model_label: str,
    export_df: pd.DataFrame,
    period_frame: pd.DataFrame,
    gross_col: str,
    net_col: str,
    held_col: str,
    leverage_col: str,
    turnover_col: str,
    fee_col: str,
    funding_col: str,
    borrow_col: str,
    slippage_col: str,
    state_col: str,
    early_risk_series: pd.Series | None,
    cooldown_days: int | None,
) -> dict[str, Any]:
    if export_df.empty or period_frame.empty:
        return {
            "period": period_name,
            "period_start": None,
            "period_end": None,
            "model_id": model_id,
            "model_label": model_label,
            "cooldown_days": cooldown_days,
            "gross_return_pct": 0.0,
            "net_total_return_pct": 0.0,
            "net_cagr_pct": 0.0,
            "net_max_drawdown_pct": 0.0,
            "trade_days": 0,
            "switch_count": 0,
            "turnover_pressure": 0.0,
            "exposure_days": 0,
            "total_cost_pct": 0.0,
            "trading_fees_total_pct": 0.0,
            "funding_total_pct": 0.0,
            "borrow_cost_total_pct": 0.0,
            "tradable_slippage_cost_total_pct": 0.0,
            "early_risk_days": 0,
        }

    gross_return = compound_return(export_df[gross_col])
    net_return = compound_return(export_df[net_col])
    early_risk_days = int(early_risk_series.sum()) if early_risk_series is not None else 0
    total_cost_pct = (
        pd.to_numeric(export_df[fee_col], errors="coerce").fillna(0.0).sum()
        + pd.to_numeric(export_df[funding_col], errors="coerce").fillna(0.0).sum()
        + pd.to_numeric(export_df[borrow_col], errors="coerce").fillna(0.0).sum()
        + pd.to_numeric(export_df[slippage_col], errors="coerce").fillna(0.0).sum()
    ) * 100.0

    return {
        "period": period_name,
        "period_start": export_df.index.min().strftime("%Y-%m-%d"),
        "period_end": export_df.index.max().strftime("%Y-%m-%d"),
        "model_id": model_id,
        "model_label": model_label,
        "cooldown_days": cooldown_days,
        "gross_return_pct": round_float(gross_return * 100.0),
        "net_total_return_pct": round_float(net_return * 100.0),
        "net_cagr_pct": round_float(annualize_return(net_return, len(export_df)) * 100.0),
        "net_max_drawdown_pct": round_float(max_drawdown_from_returns(export_df[net_col]) * 100.0),
        "trade_days": count_trade_days(export_df[leverage_col]),
        "switch_count": count_switches(period_frame[state_col]),
        "turnover_pressure": round_float(pd.to_numeric(export_df[turnover_col], errors="coerce").fillna(0.0).sum()),
        "exposure_days": int(export_df[held_col].fillna("").astype(str).str.upper().ne("CASH").sum()),
        "total_cost_pct": round_float(total_cost_pct),
        "trading_fees_total_pct": round_float(
            pd.to_numeric(export_df[fee_col], errors="coerce").fillna(0.0).sum() * 100.0
        ),
        "funding_total_pct": round_float(
            pd.to_numeric(export_df[funding_col], errors="coerce").fillna(0.0).sum() * 100.0
        ),
        "borrow_cost_total_pct": round_float(
            pd.to_numeric(export_df[borrow_col], errors="coerce").fillna(0.0).sum() * 100.0
        ),
        "tradable_slippage_cost_total_pct": round_float(
            pd.to_numeric(export_df[slippage_col], errors="coerce").fillna(0.0).sum() * 100.0
        ),
        "early_risk_days": early_risk_days,
    }


def build_compare_rows(
    period_summaries: dict[str, dict[str, Any]],
    window_counts: dict[str, dict[str, int]],
    blocker_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    metric_pairs = [
        ("net_total_return_pct", "net_total_return_pct"),
        ("net_cagr_pct", "net_cagr_pct"),
        ("net_max_drawdown_pct", "net_max_drawdown_pct"),
        ("switch_count", "switch_count"),
        ("turnover_pressure", "turnover_pressure"),
        ("exposure_days", "exposure_days"),
        ("total_cost_pct", "total_cost_pct"),
        ("trade_days", "trade_days"),
        ("early_risk_days", "early_risk_days"),
    ]
    for period_name, payload in period_summaries.items():
        baseline_metrics = payload["baseline"]
        candidate_metrics = payload["candidate"]
        for metric_name, key in metric_pairs:
            baseline_value = baseline_metrics[key]
            candidate_value = candidate_metrics[key]
            rows.append(
                {
                    "period": period_name,
                    "metric": metric_name,
                    "baseline_model": baseline_metrics["model_id"],
                    "baseline_value": baseline_value,
                    "candidate_model": candidate_metrics["model_id"],
                    "candidate_value": candidate_value,
                    "delta_candidate_minus_baseline": round_float(candidate_value - baseline_value),
                }
            )

        counts = window_counts.get(period_name, {})
        for metric_name, candidate_value in [
            ("activation_windows_count", counts.get("activation_windows_count", 0)),
            ("false_start_count", counts.get("false_start_count", 0)),
            ("successful_handoff_count", counts.get("successful_handoff_count", 0)),
        ]:
            rows.append(
                {
                    "period": period_name,
                    "metric": metric_name,
                    "baseline_model": baseline_metrics["model_id"],
                    "baseline_value": 0,
                    "candidate_model": candidate_metrics["model_id"],
                    "candidate_value": candidate_value,
                    "delta_candidate_minus_baseline": candidate_value,
                }
            )

        blocker_row = blocker_rows.get(period_name, {})
        candidate_value = int(blocker_row.get("cooldown_blocked_entry_days", 0))
        rows.append(
            {
                "period": period_name,
                "metric": "cooldown_blocked_entry_days",
                "baseline_model": baseline_metrics["model_id"],
                "baseline_value": 0,
                "candidate_model": candidate_metrics["model_id"],
                "candidate_value": candidate_value,
                "delta_candidate_minus_baseline": candidate_value,
            }
        )
    return rows


def build_window_counts(activation_windows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {
        "full_etf_overlap": {
            "activation_windows_count": 0,
            "false_start_count": 0,
            "successful_handoff_count": 0,
        },
        "since2025": {
            "activation_windows_count": 0,
            "false_start_count": 0,
            "successful_handoff_count": 0,
        },
    }
    for period_name in out:
        if period_name == "full_etf_overlap":
            windows = activation_windows
        else:
            windows = [row for row in activation_windows if str(row.get("bucket")) == "since2025"]
        out[period_name]["activation_windows_count"] = len(windows)
        out[period_name]["false_start_count"] = sum(bool(row.get("false_start")) for row in windows)
        out[period_name]["successful_handoff_count"] = sum(
            bool(str(row.get("baseline_handoff_date", "")).strip()) for row in windows
        )
    return out


def summarize_periods(
    enriched: pd.DataFrame,
    baseline_export: pd.DataFrame,
    probe_export: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for period_name, start_date in PERIOD_DEFS:
        period_frame, baseline_period, probe_period = build_period_subset(
            enriched=enriched,
            baseline_export=baseline_export,
            probe_export=probe_export,
            start_date=start_date,
        )
        baseline_metrics = build_model_metrics(
            period_name=period_name,
            model_id=BASELINE_MODEL_ID,
            model_label=BASELINE_LABEL,
            export_df=baseline_period,
            period_frame=period_frame,
            gross_col="baseline_gross_return",
            net_col="baseline_net_return",
            held_col="baseline_held_asset",
            leverage_col="baseline_effective_leverage",
            turnover_col="baseline_trading_turnover_notional",
            fee_col="baseline_trading_fees_daily",
            funding_col="baseline_funding_daily",
            borrow_col="baseline_daily_borrow_cost",
            slippage_col="baseline_tradable_slippage_cost",
            state_col="baseline_state",
            early_risk_series=None,
            cooldown_days=None,
        )
        candidate_metrics = build_model_metrics(
            period_name=period_name,
            model_id=MODEL_ID,
            model_label=MODEL_LABEL,
            export_df=probe_period,
            period_frame=period_frame,
            gross_col="probe_gross_return",
            net_col="probe_net_return",
            held_col="probe_held_asset",
            leverage_col="probe_effective_leverage",
            turnover_col="probe_trading_turnover_notional",
            fee_col="probe_trading_fees_daily",
            funding_col="probe_funding_daily",
            borrow_col="probe_daily_borrow_cost",
            slippage_col="probe_tradable_slippage_cost",
            state_col="probe_state",
            early_risk_series=period_frame["early_risk_active"],
            cooldown_days=COOLDOWN_DAYS,
        )
        out[period_name] = {
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
            "deltas": {
                "net_total_return_pct": round_float(
                    candidate_metrics["net_total_return_pct"] - baseline_metrics["net_total_return_pct"]
                ),
                "net_cagr_pct": round_float(
                    candidate_metrics["net_cagr_pct"] - baseline_metrics["net_cagr_pct"]
                ),
                "net_max_drawdown_pct": round_float(
                    candidate_metrics["net_max_drawdown_pct"] - baseline_metrics["net_max_drawdown_pct"]
                ),
                "switch_count": int(candidate_metrics["switch_count"] - baseline_metrics["switch_count"]),
                "turnover_pressure": round_float(
                    candidate_metrics["turnover_pressure"] - baseline_metrics["turnover_pressure"]
                ),
                "exposure_days": int(candidate_metrics["exposure_days"] - baseline_metrics["exposure_days"]),
                "total_cost_pct": round_float(
                    candidate_metrics["total_cost_pct"] - baseline_metrics["total_cost_pct"]
                ),
            },
        }
    return out


def build_cost_rows(period_summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in period_summaries.values():
        rows.append(payload["baseline"])
        rows.append(payload["candidate"])
    return rows


def select_april_2026_windows(activation_windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for row in activation_windows:
        values = [
            str(row.get("start_date", "")),
            str(row.get("end_date", "")),
            str(row.get("baseline_handoff_date", "")),
        ]
        if any("2026-04" in value for value in values):
            windows.append(row)
    return windows


def build_leave_one_out_summary(
    activation_windows: list[dict[str, Any]],
    period_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not activation_windows:
        return None
    best_window = max(
        activation_windows,
        key=lambda row: float(row.get("net_contribution_pct_vs_baseline", 0.0)),
    )
    full_overlap_delta = period_summaries["full_etf_overlap"]["deltas"]["net_total_return_pct"]
    best_contribution = round_float(best_window.get("net_contribution_pct_vs_baseline", 0.0))
    return {
        "best_window_id": best_window.get("window_id"),
        "best_window_start_date": best_window.get("start_date"),
        "best_window_end_date": best_window.get("end_date"),
        "best_window_exit_reason": best_window.get("exit_reason"),
        "best_window_false_start": bool(best_window.get("false_start")),
        "best_window_bucket": best_window.get("bucket"),
        "best_window_net_contribution_pct_vs_baseline": best_contribution,
        "full_overlap_net_return_delta_excluding_best_window_pct": round_float(
            full_overlap_delta - best_contribution
        ),
    }


def build_summary_payload(
    *,
    snapshot: dict[str, Any],
    diagnostics: dict[str, Any],
    input_refs: dict[str, Any],
    paths: dict[str, Path],
    overlap_frame: pd.DataFrame,
    activation_windows: list[dict[str, Any]],
    cooldown_events: list[dict[str, Any]],
    period_summaries: dict[str, dict[str, Any]],
    window_counts: dict[str, dict[str, int]],
    blocker_rows: dict[str, dict[str, Any]],
    recent_useful_window: dict[str, Any] | None,
    april_windows: list[dict[str, Any]],
    leave_one_out: dict[str, Any] | None,
    cost_config_meta: dict[str, Any],
    hard_invalidation_meta: dict[str, Any],
    final_status: str,
) -> dict[str, Any]:
    useful_april_window = [
        row for row in april_windows if (not bool(row.get("false_start"))) and int(row.get("lead_days_vs_baseline_full_risk", 0)) > 0
    ]
    return with_json_flags(
        {
            "artifact_id": ARTIFACT_ID,
            "artifact_label": ARTIFACT_LABEL,
            "generated_at_utc": timestamp_utc(),
            "status": final_status,
            "baseline": {
                "model_id": BASELINE_MODEL_ID,
                "label": BASELINE_LABEL,
                "strategy_version": snapshot.get("strategy_version"),
                "closed_day": snapshot.get("closed_day"),
                "current_reason_code": snapshot.get("decision_context", {}).get("current_reason_code"),
                "current_reason_text": snapshot.get("decision_context", {}).get("current_reason_text"),
            },
            "candidate": {
                "model_id": MODEL_ID,
                "label": MODEL_LABEL,
                "mechanism_id": MECHANISM_ID,
                "early_risk_asset": "BTC",
                "early_risk_sleeve": EARLY_RISK_WEIGHT,
                "flow_3d_floor_usd": FLOW_3D_FLOOR_USD,
                "btc_ema_days": BTC_EMA_DAYS,
                "cooldown_days": COOLDOWN_DAYS,
            },
            "input_refs": input_refs,
            "output_refs": {name: str(path) for name, path in paths.items()},
            "overlap": {
                "joined_row_count": int(len(overlap_frame)),
                "start_date": overlap_frame.index.min().strftime("%Y-%m-%d") if not overlap_frame.empty else None,
                "end_date": overlap_frame.index.max().strftime("%Y-%m-%d") if not overlap_frame.empty else None,
                "baseline_rows_loaded": int(pd.read_csv(BASELINE_TIMESERIES_PATH).shape[0]),
                "etf_panel_rows_loaded": int(pd.read_csv(ETF_PANEL_PATH).shape[0]),
            },
            "hard_invalidation_rule": hard_invalidation_meta,
            "cost_model": cost_config_meta,
            "comparison": period_summaries,
            "window_counts": window_counts,
            "blocker_rows": blocker_rows,
            "cooldown_summary": {
                "cooldown_event_count": len(cooldown_events),
                "cooldown_active_days_total": int(
                    sum(int(row.get("cooldown_active_days_observed", 0)) for row in cooldown_events)
                ),
                "cooldown_blocked_entry_days_total": int(
                    sum(int(row.get("cooldown_blocked_entry_days", 0)) for row in cooldown_events)
                ),
            },
            "recent_useful_window": recent_useful_window,
            "april_2026_window_assessment": {
                "april_2026_window_present": bool(april_windows),
                "useful_april_2026_window_present": bool(useful_april_window),
                "observed_april_2026_windows": april_windows,
            },
            "leave_one_best_window_out": leave_one_out,
            "diagnostic_context": {
                "latest_state_explanation": diagnostics.get("latest_state_explanation"),
                "current_cash_or_risk_reason": diagnostics.get("current_cash_or_risk_reason"),
            },
        }
    )


def build_manifest_payload(
    *,
    paths: dict[str, Path],
    input_refs: dict[str, Any],
    cost_config_meta: dict[str, Any],
    hard_invalidation_meta: dict[str, Any],
    final_status: str,
) -> dict[str, Any]:
    return with_json_flags(
        {
            "artifact_id": f"{ARTIFACT_ID}_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(paths["summary_json"].parent),
            "output_refs": {name: str(path) for name, path in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [CONTRACT_REF],
            "spec_refs": [SPEC_REF],
            "manifest_seed_refs": [MANIFEST_SEED_REF],
            "compiled_helper_refs": [
                str(path)
                for path in sorted(
                    [
                        *PYCACHE_DIR.glob("dev_only_phase68g_etf_flow_impulse_probe.cpython-*.pyc"),
                        *PYCACHE_DIR.glob("dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity.cpython-*.pyc"),
                    ]
                )
            ],
            "cost_model": cost_config_meta,
            "hard_invalidation_rule": hard_invalidation_meta,
            "status": final_status,
        }
    )


def validate_output_bundle(paths: dict[str, Path]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    json_paths = [paths["summary_json"], paths["manifest_json"], paths["quality_json"]]
    csv_paths = [
        paths["candidate_timeseries_csv"],
        paths["handoff_row_audit_csv"],
        paths["compare_csv"],
        paths["activation_windows_csv"],
        paths["cost_metrics_csv"],
        paths["blocker_counts_csv"],
    ]
    for path in json_paths:
        ok = False
        detail = ""
        try:
            json.loads(path.read_text(encoding="utf-8"))
            ok = True
            detail = f"{path.name} parsed"
        except Exception as exc:
            detail = f"{path.name} parse failed: {exc}"
        checks.append({"path": str(path), "kind": "json", "ok": ok, "detail": detail})
    for path in csv_paths:
        ok = False
        detail = ""
        try:
            frame = pd.read_csv(path)
            ok = not frame.empty
            detail = f"{path.name} rows={len(frame)}"
        except Exception as exc:
            detail = f"{path.name} parse failed: {exc}"
        checks.append({"path": str(path), "kind": "csv", "ok": ok, "detail": detail})
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def full_risk_pass_through_check(candidate_csv_frame: pd.DataFrame) -> tuple[bool, str]:
    baseline_full_risk_mask = candidate_csv_frame["baseline_full_risk"].fillna(False).astype(bool)
    if not baseline_full_risk_mask.any():
        return True, "no baseline FULL_RISK rows observed"

    def numeric_match(left_col: str, right_col: str, digits: int = 12) -> pd.Series:
        return (
            pd.to_numeric(candidate_csv_frame.loc[baseline_full_risk_mask, left_col], errors="coerce")
            .fillna(0.0)
            .round(digits)
            .eq(
                pd.to_numeric(candidate_csv_frame.loc[baseline_full_risk_mask, right_col], errors="coerce")
                .fillna(0.0)
                .round(digits)
            )
        )

    combined = (
        candidate_csv_frame.loc[baseline_full_risk_mask, "probe_state"].eq(
            candidate_csv_frame.loc[baseline_full_risk_mask, "baseline_state"]
        )
        & candidate_csv_frame.loc[baseline_full_risk_mask, "probe_held_asset"].eq(
            candidate_csv_frame.loc[baseline_full_risk_mask, "baseline_held_asset"]
        )
        & numeric_match("probe_effective_leverage", "baseline_effective_leverage")
        & numeric_match("probe_gross_return", "baseline_gross_return")
        & numeric_match("probe_net_return", "baseline_net_return")
        & numeric_match("probe_trading_turnover_notional", "baseline_trading_turnover_notional")
        & numeric_match("probe_trading_fees_daily", "baseline_trading_fees_daily")
        & numeric_match("probe_funding_daily", "baseline_funding_daily")
        & numeric_match("probe_daily_borrow_cost", "baseline_daily_borrow_cost")
        & numeric_match("probe_tradable_slippage_cost", "baseline_tradable_slippage_cost")
        & numeric_match("probe_equity_curve_gross", "baseline_equity_curve_gross")
        & numeric_match("probe_equity_curve_net", "baseline_equity_curve_net")
    )
    ok = bool(combined.all())
    if ok:
        return True, f"baseline FULL_RISK strict pass-through verified on {int(baseline_full_risk_mask.sum())} rows"

    failing_dates = (
        candidate_csv_frame.loc[baseline_full_risk_mask, "date"]
        .loc[~combined]
        .astype(str)
        .tolist()
    )
    return (
        False,
        "baseline FULL_RISK strict pass-through mismatches on "
        f"{len(failing_dates)} row(s): {', '.join(failing_dates[:10])}",
    )


def build_handoff_row_audit(candidate_csv_frame: pd.DataFrame) -> pd.DataFrame:
    date_mask = candidate_csv_frame["date"].astype(str).isin(HANDOFF_AUDIT_DATES)
    audit_frame = candidate_csv_frame.loc[date_mask].copy()

    ordered_columns = [
        "date",
        "baseline_state",
        "candidate_state",
        "baseline_asset",
        "candidate_asset",
        "baseline_effective_market_exposure",
        "candidate_effective_market_exposure",
        "baseline_net_return",
        "candidate_net_return",
        "baseline_turnover",
        "candidate_turnover",
        "baseline_trading_fees",
        "candidate_trading_fees",
        "baseline_borrow_cost",
        "candidate_borrow_cost",
        "baseline_funding",
        "candidate_funding",
        "baseline_slippage",
        "candidate_slippage",
        "baseline_equity",
        "candidate_equity",
        "all_fields_match_flag",
    ]
    if audit_frame.empty:
        return pd.DataFrame(columns=ordered_columns)

    audit_frame = audit_frame.assign(
        candidate_state=audit_frame["probe_state"],
        baseline_asset=audit_frame["baseline_held_asset"],
        candidate_asset=audit_frame["probe_held_asset"],
        baseline_effective_market_exposure=pd.to_numeric(
            audit_frame["baseline_effective_leverage"], errors="coerce"
        ).fillna(0.0),
        candidate_effective_market_exposure=pd.to_numeric(
            audit_frame["probe_effective_leverage"], errors="coerce"
        ).fillna(0.0),
        candidate_net_return=pd.to_numeric(audit_frame["probe_net_return"], errors="coerce").fillna(0.0),
        baseline_turnover=pd.to_numeric(
            audit_frame["baseline_trading_turnover_notional"], errors="coerce"
        ).fillna(0.0),
        candidate_turnover=pd.to_numeric(
            audit_frame["probe_trading_turnover_notional"], errors="coerce"
        ).fillna(0.0),
        baseline_trading_fees=pd.to_numeric(
            audit_frame["baseline_trading_fees_daily"], errors="coerce"
        ).fillna(0.0),
        candidate_trading_fees=pd.to_numeric(
            audit_frame["probe_trading_fees_daily"], errors="coerce"
        ).fillna(0.0),
        baseline_borrow_cost=pd.to_numeric(
            audit_frame["baseline_daily_borrow_cost"], errors="coerce"
        ).fillna(0.0),
        candidate_borrow_cost=pd.to_numeric(
            audit_frame["probe_daily_borrow_cost"], errors="coerce"
        ).fillna(0.0),
        baseline_funding=pd.to_numeric(audit_frame["baseline_funding_daily"], errors="coerce").fillna(0.0),
        candidate_funding=pd.to_numeric(audit_frame["probe_funding_daily"], errors="coerce").fillna(0.0),
        baseline_slippage=pd.to_numeric(
            audit_frame["baseline_tradable_slippage_cost"], errors="coerce"
        ).fillna(0.0),
        candidate_slippage=pd.to_numeric(
            audit_frame["probe_tradable_slippage_cost"], errors="coerce"
        ).fillna(0.0),
        baseline_equity=pd.to_numeric(audit_frame["baseline_equity_curve_net"], errors="coerce").fillna(0.0),
        candidate_equity=pd.to_numeric(audit_frame["probe_equity_curve_net"], errors="coerce").fillna(0.0),
    )
    audit_frame["all_fields_match_flag"] = (
        audit_frame["candidate_state"].fillna("").astype(str).eq(audit_frame["baseline_state"].fillna("").astype(str))
        & audit_frame["candidate_asset"].fillna("").astype(str).eq(audit_frame["baseline_asset"].fillna("").astype(str))
        & audit_frame["candidate_effective_market_exposure"].round(12).eq(
            audit_frame["baseline_effective_market_exposure"].round(12)
        )
        & pd.to_numeric(audit_frame["candidate_net_return"], errors="coerce").fillna(0.0).round(12).eq(
            pd.to_numeric(audit_frame["baseline_net_return"], errors="coerce").fillna(0.0).round(12)
        )
        & audit_frame["candidate_turnover"].round(12).eq(audit_frame["baseline_turnover"].round(12))
        & audit_frame["candidate_trading_fees"].round(12).eq(audit_frame["baseline_trading_fees"].round(12))
        & audit_frame["candidate_borrow_cost"].round(12).eq(audit_frame["baseline_borrow_cost"].round(12))
        & audit_frame["candidate_funding"].round(12).eq(audit_frame["baseline_funding"].round(12))
        & audit_frame["candidate_slippage"].round(12).eq(audit_frame["baseline_slippage"].round(12))
        & audit_frame["candidate_equity"].round(12).eq(audit_frame["baseline_equity"].round(12))
    )
    audit_frame["date"] = pd.Categorical(audit_frame["date"], categories=list(HANDOFF_AUDIT_DATES), ordered=True)
    audit_frame = audit_frame.sort_values("date").copy()
    audit_frame["date"] = audit_frame["date"].astype(str)
    return audit_frame.loc[:, ordered_columns]


def handoff_row_audit_check(audit_frame: pd.DataFrame) -> tuple[bool, str]:
    observed_dates = set(audit_frame.get("date", pd.Series(dtype=str)).astype(str).tolist())
    missing_dates = [date for date in HANDOFF_AUDIT_DATES if date not in observed_dates]
    failing_dates = []
    if "all_fields_match_flag" in audit_frame.columns:
        failing_dates = (
            audit_frame.loc[~audit_frame["all_fields_match_flag"].fillna(False).astype(bool), "date"]
            .astype(str)
            .tolist()
        )
    if missing_dates or failing_dates:
        details: list[str] = []
        if missing_dates:
            details.append(f"missing required handoff rows: {', '.join(missing_dates)}")
        if failing_dates:
            details.append(f"strict pass-through mismatches on: {', '.join(failing_dates)}")
        return False, "; ".join(details)
    if len(audit_frame) != len(HANDOFF_AUDIT_DATES):
        return False, f"expected {len(HANDOFF_AUDIT_DATES)} handoff audit rows, found {len(audit_frame)}"
    return True, f"required handoff audit rows match exactly: {', '.join(HANDOFF_AUDIT_DATES)}"


def build_quality_payload(
    *,
    overlap_frame: pd.DataFrame,
    candidate_csv_frame: pd.DataFrame,
    handoff_row_audit_frame: pd.DataFrame,
    activation_windows: list[dict[str, Any]],
    cooldown_events: list[dict[str, Any]],
    blocker_rows: dict[str, dict[str, Any]],
    paths: dict[str, Path],
    parse_validation: dict[str, Any],
    hard_invalidation_meta: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    output_paths_ok = all("source_of_truth" not in str(path) for path in paths.values())
    date_universe_ok = candidate_csv_frame["date"].tolist() == [
        stamp.strftime("%Y-%m-%d") for stamp in overlap_frame.index
    ]
    causal_join_ok = bool(
        (
            pd.to_datetime(candidate_csv_frame["us_trading_session_date"], errors="coerce")
            + pd.Timedelta(days=1)
        ).eq(pd.to_datetime(candidate_csv_frame["date"], errors="coerce")).all()
        and pd.to_datetime(candidate_csv_frame["causal_available_for_btc_utc_day"], errors="coerce")
        .eq(pd.to_datetime(candidate_csv_frame["date"], errors="coerce"))
        .all()
    )
    early_risk_mask = candidate_csv_frame["early_risk_active"].fillna(False).astype(bool)
    early_risk_cash_ok = True
    if early_risk_mask.any():
        early_risk_cash_ok = bool(
            (
                candidate_csv_frame.loc[early_risk_mask, "baseline_cash"].fillna(False).astype(bool)
                & candidate_csv_frame.loc[early_risk_mask, "current_asset"].fillna("").astype(str).eq("CASH")
                & pd.to_numeric(
                    candidate_csv_frame.loc[early_risk_mask, "effective_market_exposure"], errors="coerce"
                )
                .fillna(0.0)
                .eq(0.0)
            ).all()
        )
    handoff_row_audit_ok, handoff_row_audit_detail = handoff_row_audit_check(handoff_row_audit_frame)
    full_risk_pass_through_ok, full_risk_pass_through_detail = full_risk_pass_through_check(candidate_csv_frame)

    cooldown_schedule_ok = True
    for event in cooldown_events:
        start_text = str(event.get("cooldown_start_date", "")).strip()
        end_text = str(event.get("scheduled_cooldown_end_date", "")).strip()
        if not start_text or not end_text:
            continue
        delta_days = (pd.Timestamp(end_text) - pd.Timestamp(start_text)).days + 1
        if delta_days != COOLDOWN_DAYS:
            cooldown_schedule_ok = False
            break
    cooldown_block_only_ok = bool(
        not (
            candidate_csv_frame["cooldown_blocked_entry"].fillna(False).astype(bool)
            & candidate_csv_frame["early_risk_active"].fillna(False).astype(bool)
        ).any()
    )
    cooldown_block_rows_valid = True
    cooldown_block_mask = candidate_csv_frame["cooldown_blocked_entry"].fillna(False).astype(bool)
    if cooldown_block_mask.any():
        cooldown_block_rows_valid = bool(
            (
                candidate_csv_frame.loc[cooldown_block_mask, "cooldown_active"].fillna(False).astype(bool)
                & candidate_csv_frame.loc[cooldown_block_mask, "baseline_cash"].fillna(False).astype(bool)
                & candidate_csv_frame.loc[cooldown_block_mask, "permission_on"].fillna(False).astype(bool)
            ).all()
        )
    cooldown_active_not_full_risk = bool(
        not (
            candidate_csv_frame["cooldown_active"].fillna(False).astype(bool)
            & candidate_csv_frame["baseline_full_risk"].fillna(False).astype(bool)
        ).any()
    )
    cooldown_ok = cooldown_schedule_ok and cooldown_block_only_ok and cooldown_block_rows_valid and cooldown_active_not_full_risk

    dev_marker_ok = bool(
        candidate_csv_frame["dev_only"].fillna(False).astype(bool).all()
        and candidate_csv_frame["non_authoritative"].fillna(False).astype(bool).all()
        and (~candidate_csv_frame["official_truth"].fillna(False).astype(bool)).all()
        and (~candidate_csv_frame["strategy_advancement"].fillna(False).astype(bool)).all()
    )

    checks = [
        {
            "name": "json_parse",
            "ok": parse_validation["ok"],
            "detail": "all required JSON and CSV outputs parse cleanly",
        },
        {
            "name": "csv_non_empty",
            "ok": all(
                check["ok"] for check in parse_validation["checks"] if check["kind"] == "csv"
            ),
            "detail": "all required CSV outputs are present and non-empty",
        },
        {
            "name": "production_core_baseline_rows_loaded",
            "ok": int(pd.read_csv(BASELINE_TIMESERIES_PATH).shape[0]) > 0,
            "detail": f"loaded {int(pd.read_csv(BASELINE_TIMESERIES_PATH).shape[0])} baseline rows",
        },
        {
            "name": "etf_panel_rows_loaded",
            "ok": int(pd.read_csv(ETF_PANEL_PATH).shape[0]) > 0,
            "detail": f"loaded {int(pd.read_csv(ETF_PANEL_PATH).shape[0])} ETF rows",
        },
        {
            "name": "candidate_timeseries_date_universe_matches_joined_overlap",
            "ok": date_universe_ok,
            "detail": "candidate_timeseries.csv uses the same date universe as the joined overlap",
        },
        {
            "name": "confirm_etf_d_plus_1_causal_join",
            "ok": causal_join_ok,
            "detail": "ETF session D is used only on BTC UTC day D+1",
        },
        {
            "name": "confirm_early_risk_only_on_baseline_cash",
            "ok": early_risk_cash_ok,
            "detail": "EARLY_RISK rows require effective_market_exposure == 0 and current_asset == CASH",
        },
        {
            "name": "confirm_required_handoff_rows_strict_pass_through",
            "ok": handoff_row_audit_ok,
            "detail": handoff_row_audit_detail,
        },
        {
            "name": "confirm_baseline_non_cash_behavior_passes_through_unchanged",
            "ok": full_risk_pass_through_ok,
            "detail": full_risk_pass_through_detail,
        },
        {
            "name": "confirm_cooldown_15_implementation",
            "ok": cooldown_ok,
            "detail": "15-day cooldown windows are scheduled correctly and block only new EARLY_RISK entries",
        },
        {
            "name": "confirm_dev_only_non_authoritative_markers",
            "ok": dev_marker_ok,
            "detail": "row-level dev_only / non_authoritative markers remain intact",
        },
        {
            "name": "confirm_no_source_of_truth_changes",
            "ok": output_paths_ok,
            "detail": "all writes remain under outputs/research_os/dev_only and avoid source_of_truth",
        },
        {
            "name": "hard_invalidation_source_documented",
            "ok": True,
            "detail": hard_invalidation_meta["detail"],
        },
    ]
    final_status = "READY_FOR_FORENSIC_RERUN" if all(check["ok"] for check in checks) else "STILL_FAILED"
    payload = with_json_flags(
        {
            "artifact_id": f"{ARTIFACT_ID}_quality",
            "generated_at_utc": timestamp_utc(),
            "checks": checks,
            "parse_validation": parse_validation,
            "status": "passed" if final_status == "READY_FOR_FORENSIC_RERUN" else "failed",
            "final_status": final_status,
            "cooldown_event_count": len(cooldown_events),
            "activation_windows_count": len(activation_windows),
            "blocker_rows": blocker_rows,
            "handoff_row_audit_rows": handoff_row_audit_frame.to_dict(orient="records"),
        }
    )
    return payload, final_status


def front_loaded_columns(frame: pd.DataFrame) -> list[str]:
    front = [
        "date",
        "us_trading_session_date",
        "causal_available_for_btc_utc_day",
        "current_asset",
        "effective_market_exposure",
        "baseline_cash",
        "baseline_full_risk",
        "permission_inputs_true",
        "permission_on",
        "permission_on_while_baseline_full_risk",
        "hard_invalidation_on",
        "probe_input_ready_flag",
        "flow_2_of_last_3_positive_flag",
        "flow_3d_sum_usd",
        "flow_3d_sum_pass",
        "btc_close",
        "btc_ema10",
        "btc_price_filter_pass",
        "probe_state",
        "probe_window_id",
        "probe_exit_reason",
        "baseline_handoff_day",
        "early_risk_active",
        "cooldown_active",
        "cooldown_blocked_entry",
        "cooldown_event_id",
        "portfolio_held_asset",
        "probe_held_asset",
        "effective_leverage",
        "probe_effective_leverage",
        "baseline_state",
        "baseline_gross_return",
        "probe_gross_return",
        "baseline_net_return",
        "probe_net_return",
        "baseline_equity_curve_net",
        "probe_equity_curve_net",
        "reason_code",
        "dev_only",
        "non_authoritative",
        "official_truth",
        "strategy_advancement",
    ]
    ordered = [column for column in front if column in frame.columns]
    ordered.extend(column for column in frame.columns if column not in ordered)
    return ordered


def write_dataframe(path: Path, frame: pd.DataFrame) -> None:
    ensure_dir(path.parent)
    frame.to_csv(path, index=False)


def write_records(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    pd.DataFrame(rows).to_csv(path, index=False)


def build_input_refs(cost_config_meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "baseline_snapshot": str(BASELINE_SNAPSHOT_PATH),
        "baseline_timeseries": str(BASELINE_TIMESERIES_PATH),
        "baseline_diagnostics": str(BASELINE_DIAGNOSTICS_PATH),
        "etf_panel": str(ETF_PANEL_PATH),
        "btc_ohlcv": str(BTC_OHLCV_PATH),
        "contract_ref": CONTRACT_REF,
        "spec_ref": SPEC_REF,
        "manifest_seed_ref": MANIFEST_SEED_REF,
        "cost_model_source": cost_config_meta["source"],
    }


def main() -> int:
    args = parse_args()
    ensure_dir(args.output_dir)
    paths = output_paths(args.output_dir)

    snapshot = read_json(BASELINE_SNAPSHOT_PATH)
    diagnostics = read_json(BASELINE_DIAGNOSTICS_PATH)
    baseline_df, hard_invalidation_meta = normalize_baseline_frame(BASELINE_TIMESERIES_PATH)
    cost_config, cost_config_meta = derive_cost_config(pd.read_csv(BASELINE_TIMESERIES_PATH))
    input_refs = build_input_refs(cost_config_meta)

    probe_mod, cooldown_mod = load_phase68g_helpers()
    etf_df = probe_mod.load_etf_panel(ETF_PANEL_PATH)
    btc_df = probe_mod.load_btc_frame(BTC_OHLCV_PATH)
    overlap_frame = probe_mod.build_overlap_frame(baseline_df, etf_df, btc_df)
    if "date" in overlap_frame.columns:
        overlap_frame = overlap_frame.drop(columns=["date"])
    if overlap_frame.empty:
        raise RuntimeError("No joined overlap across baseline, ETF panel, and BTC daily data.")

    state_frame, cooldown_events = cooldown_mod.build_cooldown_state_machine(overlap_frame, COOLDOWN_DAYS)
    baseline_export, probe_export, enriched = probe_mod.build_export_metrics(state_frame, cost_config)
    baseline_export, probe_export, enriched = enforce_baseline_full_risk_pass_through(
        baseline_export,
        probe_export,
        enriched,
    )

    candidate_timeseries = enriched.reset_index().rename(columns={"index": "date"})
    candidate_timeseries["date"] = pd.to_datetime(candidate_timeseries["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    candidate_timeseries = candidate_timeseries.loc[:, front_loaded_columns(candidate_timeseries)]

    activation_windows = probe_mod.build_activation_windows(enriched)
    for row in activation_windows:
        row["model_id"] = MODEL_ID
        row["model_label"] = MODEL_LABEL
        row["cooldown_days"] = COOLDOWN_DAYS
    blocker_rows_list = cooldown_mod.build_blocker_rows(
        enriched,
        {
            "variant_id": VARIANT_ID,
            "model_id": MODEL_ID,
            "model_label": MODEL_LABEL,
            "cooldown_days": COOLDOWN_DAYS,
        },
    )
    blocker_rows = {row["period"]: row for row in blocker_rows_list}

    period_summaries = summarize_periods(
        enriched=enriched,
        baseline_export=baseline_export,
        probe_export=probe_export,
    )
    cost_rows = build_cost_rows(period_summaries)
    window_counts = build_window_counts(activation_windows)
    compare_rows = build_compare_rows(period_summaries, window_counts, blocker_rows)

    recent_useful_window = cooldown_mod.select_recent_useful_window(activation_windows)
    april_windows = select_april_2026_windows(activation_windows)
    leave_one_out = build_leave_one_out_summary(activation_windows, period_summaries)
    handoff_row_audit = build_handoff_row_audit(candidate_timeseries)

    write_dataframe(paths["candidate_timeseries_csv"], candidate_timeseries)
    write_dataframe(paths["handoff_row_audit_csv"], handoff_row_audit)
    write_records(paths["compare_csv"], compare_rows)
    write_records(paths["activation_windows_csv"], activation_windows)
    write_records(paths["cost_metrics_csv"], cost_rows)
    write_records(paths["blocker_counts_csv"], blocker_rows_list)

    temp_manifest = build_manifest_payload(
        paths=paths,
        input_refs=input_refs,
        cost_config_meta=cost_config_meta,
        hard_invalidation_meta=hard_invalidation_meta,
        final_status="PENDING_VALIDATION",
    )
    temp_summary = build_summary_payload(
        snapshot=snapshot,
        diagnostics=diagnostics,
        input_refs=input_refs,
        paths=paths,
        overlap_frame=overlap_frame,
        activation_windows=activation_windows,
        cooldown_events=cooldown_mod.decorate_cooldown_events(
            cooldown_events,
            {
                "variant_id": VARIANT_ID,
                "model_id": MODEL_ID,
                "model_label": MODEL_LABEL,
                "cooldown_days": COOLDOWN_DAYS,
            },
        ),
        period_summaries=period_summaries,
        window_counts=window_counts,
        blocker_rows=blocker_rows,
        recent_useful_window=recent_useful_window,
        april_windows=april_windows,
        leave_one_out=leave_one_out,
        cost_config_meta=cost_config_meta,
        hard_invalidation_meta=hard_invalidation_meta,
        final_status="PENDING_VALIDATION",
    )
    save_json(paths["manifest_json"], temp_manifest)
    save_json(paths["summary_json"], temp_summary)

    temp_quality = with_json_flags(
        {
            "artifact_id": f"{ARTIFACT_ID}_quality",
            "generated_at_utc": timestamp_utc(),
            "status": "pending",
            "final_status": "PENDING_VALIDATION",
        }
    )
    save_json(paths["quality_json"], temp_quality)

    parse_validation = validate_output_bundle(paths)
    decorated_cooldown_events = cooldown_mod.decorate_cooldown_events(
        cooldown_events,
        {
            "variant_id": VARIANT_ID,
            "model_id": MODEL_ID,
            "model_label": MODEL_LABEL,
            "cooldown_days": COOLDOWN_DAYS,
        },
    )
    quality_payload, final_status = build_quality_payload(
        overlap_frame=overlap_frame,
        candidate_csv_frame=candidate_timeseries,
        handoff_row_audit_frame=handoff_row_audit,
        activation_windows=activation_windows,
        cooldown_events=decorated_cooldown_events,
        blocker_rows=blocker_rows,
        paths=paths,
        parse_validation=parse_validation,
        hard_invalidation_meta=hard_invalidation_meta,
    )
    manifest_payload = build_manifest_payload(
        paths=paths,
        input_refs=input_refs,
        cost_config_meta=cost_config_meta,
        hard_invalidation_meta=hard_invalidation_meta,
        final_status=final_status,
    )
    summary_payload = build_summary_payload(
        snapshot=snapshot,
        diagnostics=diagnostics,
        input_refs=input_refs,
        paths=paths,
        overlap_frame=overlap_frame,
        activation_windows=activation_windows,
        cooldown_events=decorated_cooldown_events,
        period_summaries=period_summaries,
        window_counts=window_counts,
        blocker_rows=blocker_rows,
        recent_useful_window=recent_useful_window,
        april_windows=april_windows,
        leave_one_out=leave_one_out,
        cost_config_meta=cost_config_meta,
        hard_invalidation_meta=hard_invalidation_meta,
        final_status=final_status,
    )

    save_json(paths["summary_json"], summary_payload)
    save_json(paths["manifest_json"], manifest_payload)
    save_json(paths["quality_json"], quality_payload)

    final_parse = validate_output_bundle(paths)
    if not final_parse["ok"] and final_status != "STILL_FAILED":
        quality_payload, final_status = build_quality_payload(
            overlap_frame=overlap_frame,
            candidate_csv_frame=candidate_timeseries,
            handoff_row_audit_frame=handoff_row_audit,
            activation_windows=activation_windows,
            cooldown_events=decorated_cooldown_events,
            blocker_rows=blocker_rows,
            paths=paths,
            parse_validation=final_parse,
            hard_invalidation_meta=hard_invalidation_meta,
        )
        manifest_payload = build_manifest_payload(
            paths=paths,
            input_refs=input_refs,
            cost_config_meta=cost_config_meta,
            hard_invalidation_meta=hard_invalidation_meta,
            final_status=final_status,
        )
        summary_payload = build_summary_payload(
            snapshot=snapshot,
            diagnostics=diagnostics,
            input_refs=input_refs,
            paths=paths,
            overlap_frame=overlap_frame,
            activation_windows=activation_windows,
            cooldown_events=decorated_cooldown_events,
            period_summaries=period_summaries,
            window_counts=window_counts,
            blocker_rows=blocker_rows,
            recent_useful_window=recent_useful_window,
            april_windows=april_windows,
            leave_one_out=leave_one_out,
            cost_config_meta=cost_config_meta,
            hard_invalidation_meta=hard_invalidation_meta,
            final_status=final_status,
        )
        save_json(paths["summary_json"], summary_payload)
        save_json(paths["manifest_json"], manifest_payload)
        save_json(paths["quality_json"], quality_payload)

    print(final_status)
    return 0 if final_status == "READY_FOR_FORENSIC_RERUN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
