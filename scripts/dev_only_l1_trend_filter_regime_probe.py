from __future__ import annotations

import argparse
import math
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

import dev_only_cash_overstay_diagnostic as cash_diag
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_l1_trend_filter_regime_probe"
)

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "l1_trend_filter_regime_probe"
MECHANISM_ID = "one_sided_btc_l1_trend_filter_regime"

BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
PHASE68I_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
PHASE68I_SUMMARY_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_summary.csv"

ROLLING_WINDOW_DAYS = 126
LAMBDA_MULTIPLIER = 2.0
ADMM_RHO = 1.0
ADMM_MAX_ITER = 80
ADMM_TOL = 1e-5
SLOPE_ENTRY_THRESHOLD = 0.0

JSON_LOCKS = {
    "analysis_mode": "l1_trend_filter_regime_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}

LAMBDA_RULE = (
    "For each causal 126-day BTC window, compute sigma as 1.4826 * MAD of daily BTC log returns in that window; "
    "set lambda = 2.0 * sigma * sqrt(2 * log(125)) for the 125-slope fused-L1 problem. "
    "This robust universal-threshold style rule is a single low-switch heuristic, not a sweep."
)
ONE_SIDED_METHOD = (
    "Each day t uses only BTC closes from the trailing 126 daily observations ending on t. The script denoises the "
    "125 log-return slopes in that window with a first-difference L1 penalty, then uses only the final filtered slope "
    "for day t."
)
STATE_RULE = (
    "Baseline risk days remain unchanged. On baseline CASH days only, the probe enters full BTC risk when the causal "
    "L1-filtered endpoint slope is greater than 0 and the existing hard BTC risk-off invalidation is false; otherwise "
    "it remains CASH. There is no pilot state, no Pilot-to-Full ladder, and no persistence exposure logic."
)
STOP_RULE = (
    "stop if earlier activation is not present in more than one valid handoff window, or if net benefit disappears, "
    "or if trade days / switches / turnover rise materially, or if net drawdown deteriorates by more than 1 pct point"
)

WINDOW_COMPARE_COLUMNS = [
    "window_id",
    "l1_activation_date",
    "window_end_date",
    "baseline_handoff_date",
    "activation_kind",
    "lead_days_vs_baseline",
    "l1_risk_days",
    "entry_l1_endpoint_slope",
    "entry_lambda",
    "entry_slope_change_count",
    "btc_return_gross",
    "baseline_return_gross",
    "probe_return_gross",
    "baseline_return_net",
    "probe_return_net",
    "net_early_move_capture",
    "gross_early_move_capture",
    "exit_reason",
]
STATE_TIME_COLUMNS = ["model", "state", "days", "share_of_total_days"]
COMPARE_COLUMNS = ["metric", "baseline_model", "baseline_value", "probe_model", "probe_value", "delta_probe_minus_baseline"]
COST_COLUMNS = [
    "model",
    "gross_return_pct",
    "net_return_after_costs_pct",
    "net_cagr_pct",
    "max_drawdown_pct",
    "trade_count",
    "switch_count",
    "turnover_pressure",
    "total_cost_pct",
    "l1_risk_days",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only one-sided BTC L1 trend-filter regime probe")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--phase68i-paper", type=str, default=str(PHASE68I_PAPER_PATH))
    parser.add_argument("--phase68i-summary", type=str, default=str(PHASE68I_SUMMARY_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    return {
        "summary_json": OUTPUT_ROOT / "l1_trend_filter_regime_probe.summary.json",
        "window_compare_csv": OUTPUT_ROOT / "l1_trend_filter_regime_probe.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / "l1_trend_filter_regime_probe.state_time.csv",
        "compare_csv": OUTPUT_ROOT / "l1_trend_filter_regime_probe.compare.csv",
        "cost_metrics_csv": OUTPUT_ROOT / "l1_trend_filter_regime_probe.cost_metrics.csv",
        "manifest_json": OUTPUT_ROOT / "l1_trend_filter_regime_probe.manifest.json",
        "quality_json": OUTPUT_ROOT / "l1_trend_filter_regime_probe.quality.json",
    }


def safe_float(value: Any, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(default if pd.isna(numeric) else numeric)


def compound_return(values: pd.Series) -> float:
    return cash_diag.compound_return(values)


def compound_pct(values: pd.Series) -> float:
    return round(compound_return(values) * 100.0, 6)


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if total_return <= -1.0:
        return -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def max_drawdown_from_returns(returns: pd.Series) -> float:
    equity = (1.0 + pd.to_numeric(returns, errors="coerce").fillna(0.0)).cumprod()
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def load_phase68i_cost_assumptions(summary_path: Path, paper_path: Path) -> Dict[str, float]:
    fee_bps = 4.5
    slippage_bps = 10.0
    if summary_path.exists():
        summary_df = pd.read_csv(summary_path)
        if not summary_df.empty and "effective_trading_fee_bps" in summary_df.columns:
            fee_bps = safe_float(summary_df.iloc[0]["effective_trading_fee_bps"], fee_bps)
    if paper_path.exists():
        paper_df = pd.read_csv(paper_path)
        if not paper_df.empty and "tradable_transition_slippage_bps" in paper_df.columns:
            candidate = pd.to_numeric(paper_df["tradable_transition_slippage_bps"], errors="coerce").dropna()
            if not candidate.empty:
                slippage_bps = float(candidate.iloc[0])
    return {
        "trading_fee_bps": round(fee_bps, 6),
        "slippage_bps": round(slippage_bps, 6),
        "turnover_cost_per_unit": round((fee_bps + slippage_bps) / 10000.0, 8),
    }


def make_tridiagonal_solver(n: int, rho: float) -> Callable[[np.ndarray], np.ndarray]:
    lower = np.full(n - 1, -rho, dtype=float)
    upper = np.full(n - 1, -rho, dtype=float)
    diag = np.full(n, 1.0 + 2.0 * rho, dtype=float)
    diag[0] = 1.0 + rho
    diag[-1] = 1.0 + rho

    cp = np.zeros(n - 1, dtype=float)
    denom = np.zeros(n, dtype=float)
    denom[0] = diag[0]
    cp[0] = upper[0] / denom[0]
    for idx in range(1, n - 1):
        denom[idx] = diag[idx] - lower[idx - 1] * cp[idx - 1]
        cp[idx] = upper[idx] / denom[idx]
    denom[-1] = diag[-1] - lower[-1] * cp[-1]

    def solve(rhs: np.ndarray) -> np.ndarray:
        dp = np.zeros(n, dtype=float)
        dp[0] = rhs[0] / denom[0]
        for idx in range(1, n):
            dp[idx] = (rhs[idx] - lower[idx - 1] * dp[idx - 1]) / denom[idx]
        out = np.zeros(n, dtype=float)
        out[-1] = dp[-1]
        for idx in range(n - 2, -1, -1):
            out[idx] = dp[idx] - cp[idx] * out[idx + 1]
        return out

    return solve


def diff_transpose(values: np.ndarray) -> np.ndarray:
    out = np.zeros(len(values) + 1, dtype=float)
    out[0] = -values[0]
    out[1:-1] = values[:-1] - values[1:]
    out[-1] = values[-1]
    return out


def shrink(values: np.ndarray, threshold: float) -> np.ndarray:
    return np.sign(values) * np.maximum(np.abs(values) - threshold, 0.0)


def robust_sigma(values: np.ndarray) -> float:
    median_value = float(np.median(values))
    mad = float(np.median(np.abs(values - median_value)))
    return 1.4826 * mad


def l1_lambda_for_window(log_returns: np.ndarray) -> float:
    sigma = robust_sigma(log_returns)
    slope_count = max(int(log_returns.size), 2)
    return float(LAMBDA_MULTIPLIER * sigma * math.sqrt(2.0 * math.log(slope_count)))


def tv_denoise_slopes(
    raw_slopes: np.ndarray,
    lambda_value: float,
    solver: Callable[[np.ndarray], np.ndarray],
) -> Tuple[np.ndarray, int, float, int]:
    x = raw_slopes.astype(float).copy()
    z = np.diff(x)
    u = np.zeros_like(z)
    residual = 0.0
    for iteration in range(1, ADMM_MAX_ITER + 1):
        rhs = raw_slopes + ADMM_RHO * diff_transpose(z - u)
        x = solver(rhs)
        dx = np.diff(x)
        z_old = z.copy()
        z = shrink(dx + u, lambda_value / ADMM_RHO)
        u = u + dx - z
        primal = float(np.max(np.abs(dx - z))) if len(z) else 0.0
        dual = float(np.max(np.abs(ADMM_RHO * diff_transpose(z - z_old)))) if len(z) else 0.0
        residual = max(primal, dual)
        if residual <= ADMM_TOL:
            break
    slope_change_count = int((np.abs(np.diff(x)) > 1e-8).sum())
    return x, iteration, residual, slope_change_count


def add_one_sided_l1_filter_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    log_close = np.log(pd.to_numeric(out["benchmark_close"], errors="coerce").astype(float).to_numpy())
    solver = make_tridiagonal_solver(ROLLING_WINDOW_DAYS - 1, ADMM_RHO)

    endpoint_slopes: List[float | None] = []
    endpoint_filtered_logs: List[float | None] = []
    lambda_values: List[float | None] = []
    slope_changes: List[int | None] = []
    iterations: List[int | None] = []
    residuals: List[float | None] = []
    window_start_dates: List[str] = []
    window_end_dates: List[str] = []

    for idx in range(len(out)):
        if idx < ROLLING_WINDOW_DAYS - 1:
            endpoint_slopes.append(None)
            endpoint_filtered_logs.append(None)
            lambda_values.append(None)
            slope_changes.append(None)
            iterations.append(None)
            residuals.append(None)
            window_start_dates.append("")
            window_end_dates.append("")
            continue

        start_idx = idx - ROLLING_WINDOW_DAYS + 1
        window_log = log_close[start_idx : idx + 1]
        raw_slopes = np.diff(window_log)
        lambda_value = l1_lambda_for_window(raw_slopes)
        filtered_slopes, iteration_count, residual, slope_change_count = tv_denoise_slopes(
            raw_slopes=raw_slopes,
            lambda_value=lambda_value,
            solver=solver,
        )

        endpoint_slopes.append(float(filtered_slopes[-1]))
        endpoint_filtered_logs.append(float(window_log[0] + filtered_slopes.cumsum()[-1]))
        lambda_values.append(lambda_value)
        slope_changes.append(slope_change_count)
        iterations.append(iteration_count)
        residuals.append(residual)
        window_start_dates.append(pd.Timestamp(out.index[start_idx]).strftime("%Y-%m-%d"))
        window_end_dates.append(pd.Timestamp(out.index[idx]).strftime("%Y-%m-%d"))

    out["l1_endpoint_slope"] = endpoint_slopes
    out["l1_endpoint_filtered_log_price"] = endpoint_filtered_logs
    out["l1_lambda"] = lambda_values
    out["l1_slope_change_count"] = slope_changes
    out["l1_admm_iterations"] = iterations
    out["l1_admm_residual"] = residuals
    out["l1_window_start_date"] = window_start_dates
    out["l1_window_end_date"] = window_end_dates
    out["l1_slope_positive"] = pd.to_numeric(out["l1_endpoint_slope"], errors="coerce").fillna(0.0) > SLOPE_ENTRY_THRESHOLD
    return out


def build_probe_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    frame = cash_diag.build_analysis_frame(baseline_df).copy()
    frame = add_one_sided_l1_filter_columns(frame)
    frame["baseline_cash"] = ~frame["in_market"]
    frame["l1_hard_risk_off_block"] = frame["risk_off_invalidation_day"].fillna(False).astype(bool)
    frame["l1_risk_on_permission_raw"] = frame["l1_slope_positive"]
    frame["l1_risk_on_permission"] = (
        frame["baseline_cash"] & frame["l1_risk_on_permission_raw"] & (~frame["l1_hard_risk_off_block"])
    )

    l1_active = False
    current_window_id = ""
    window_counter = 0

    probe_states: List[str] = []
    probe_window_ids: List[str] = []
    handoff_flags: List[bool] = []
    exit_reasons: List[str] = []
    l1_active_flags: List[bool] = []

    for _, row in frame.iterrows():
        baseline_cash = bool(row["baseline_cash"])
        permission = bool(row["l1_risk_on_permission"])
        exit_reason = ""
        row_window_id = ""

        if l1_active and not baseline_cash:
            state = "BASELINE_RISK"
            row_window_id = current_window_id
            exit_reason = "baseline_handoff"
            l1_active = False
        elif l1_active and not permission:
            state = "CASH"
            row_window_id = current_window_id
            exit_reason = "hard_risk_off" if bool(row["l1_hard_risk_off_block"]) else "l1_slope_nonpositive"
            l1_active = False
        elif (not l1_active) and baseline_cash and permission:
            window_counter += 1
            current_window_id = f"window_{window_counter:03d}"
            state = "L1_BTC_RISK"
            row_window_id = current_window_id
            l1_active = True
        elif l1_active:
            state = "L1_BTC_RISK"
            row_window_id = current_window_id
        elif baseline_cash:
            state = "CASH"
        else:
            state = "BASELINE_RISK"

        probe_states.append(state)
        probe_window_ids.append(row_window_id)
        handoff_flags.append(exit_reason == "baseline_handoff")
        exit_reasons.append(exit_reason)
        l1_active_flags.append(state == "L1_BTC_RISK")

        if exit_reason:
            current_window_id = ""

    frame["probe_state"] = probe_states
    frame["l1_window_id"] = probe_window_ids
    frame["baseline_handoff_day"] = handoff_flags
    frame["probe_exit_reason"] = exit_reasons
    frame["l1_active"] = l1_active_flags
    frame["probe_in_market"] = frame["probe_state"].ne("CASH")
    frame["probe_strategy_return_gross"] = pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)
    frame.loc[frame["l1_active"], "probe_strategy_return_gross"] = pd.to_numeric(
        frame.loc[frame["l1_active"], "benchmark_return"], errors="coerce"
    ).fillna(0.0)
    return frame


def apply_cost_model(frame: pd.DataFrame, cost_cfg: Dict[str, float]) -> pd.DataFrame:
    out = frame.copy()
    baseline_weight = out["in_market"].astype(float)
    probe_weight = out["probe_in_market"].astype(float)
    out["baseline_exposure_weight"] = baseline_weight
    out["probe_exposure_weight"] = probe_weight
    out["baseline_turnover"] = baseline_weight.diff().abs().fillna(abs(float(baseline_weight.iloc[0])))
    out["probe_turnover"] = probe_weight.diff().abs().fillna(abs(float(probe_weight.iloc[0])))
    turnover_cost = float(cost_cfg["turnover_cost_per_unit"])
    out["baseline_cost"] = out["baseline_turnover"] * turnover_cost
    out["probe_cost"] = out["probe_turnover"] * turnover_cost
    out["baseline_strategy_return_net"] = pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0) - out[
        "baseline_cost"
    ]
    out["probe_strategy_return_net"] = out["probe_strategy_return_gross"] - out["probe_cost"]
    return out


def build_activation_windows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    active_ids = [value for value in frame["l1_window_id"].dropna().unique().tolist() if str(value).strip()]
    for window_id in active_ids:
        window_df = frame.loc[frame["l1_window_id"].eq(window_id)].copy()
        active_df = window_df.loc[window_df["l1_active"]]
        if active_df.empty:
            continue
        start_date = pd.Timestamp(active_df.index.min())
        handoff_rows = window_df.loc[window_df["baseline_handoff_day"]]
        exit_rows = window_df.loc[window_df["probe_exit_reason"].ne("")]
        handoff_date = pd.Timestamp(handoff_rows.index.min()) if not handoff_rows.empty else None
        if handoff_date is not None:
            end_date = handoff_date - pd.Timedelta(days=1)
            exit_reason = "baseline_handoff"
        elif not exit_rows.empty:
            end_date = pd.Timestamp(exit_rows.index.min()) - pd.Timedelta(days=1)
            exit_reason = str(exit_rows.iloc[0]["probe_exit_reason"])
        else:
            end_date = pd.Timestamp(active_df.index.max())
            exit_reason = "still_open_at_dataset_end"

        if end_date < start_date:
            end_date = start_date
        window_slice = frame.loc[start_date:end_date].copy()
        entry = frame.loc[start_date]
        baseline_return_net = compound_pct(window_slice["baseline_strategy_return_net"])
        probe_return_net = compound_pct(window_slice["probe_strategy_return_net"])
        baseline_return_gross = compound_pct(window_slice["strategy_return"])
        probe_return_gross = compound_pct(window_slice["probe_strategy_return_gross"])
        btc_return_gross = compound_pct(window_slice["benchmark_return"])

        rows.append(
            {
                "window_id": window_id,
                "l1_activation_date": start_date.strftime("%Y-%m-%d"),
                "window_end_date": end_date.strftime("%Y-%m-%d"),
                "baseline_handoff_date": "" if handoff_date is None else handoff_date.strftime("%Y-%m-%d"),
                "activation_kind": "one_sided_l1_btc_slope",
                "lead_days_vs_baseline": 0 if handoff_date is None else int((handoff_date - start_date).days),
                "l1_risk_days": int(window_slice["l1_active"].sum()),
                "entry_l1_endpoint_slope": round(safe_float(entry["l1_endpoint_slope"]), 8),
                "entry_lambda": round(safe_float(entry["l1_lambda"]), 8),
                "entry_slope_change_count": int(safe_float(entry["l1_slope_change_count"], 0.0)),
                "btc_return_gross": btc_return_gross,
                "baseline_return_gross": baseline_return_gross,
                "probe_return_gross": probe_return_gross,
                "baseline_return_net": baseline_return_net,
                "probe_return_net": probe_return_net,
                "net_early_move_capture": round(probe_return_net - baseline_return_net, 6),
                "gross_early_move_capture": round(probe_return_gross - baseline_return_gross, 6),
                "exit_reason": exit_reason,
            }
        )
    return rows


def build_state_time_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    total_days = int(len(frame))
    specs = [
        (BASELINE_MODEL, "BASELINE_RISK", int(frame["in_market"].sum())),
        (BASELINE_MODEL, "CASH", int((~frame["in_market"]).sum())),
        (PROBE_MODEL, "BASELINE_RISK", int(frame["probe_state"].eq("BASELINE_RISK").sum())),
        (PROBE_MODEL, "L1_BTC_RISK", int(frame["probe_state"].eq("L1_BTC_RISK").sum())),
        (PROBE_MODEL, "CASH", int(frame["probe_state"].eq("CASH").sum())),
    ]
    return [
        {
            "model": model,
            "state": state,
            "days": days,
            "share_of_total_days": round(days / total_days, 6) if total_days else 0.0,
        }
        for model, state, days in specs
    ]


def count_trade_days(weight_series: pd.Series) -> int:
    return int(weight_series.diff().abs().fillna(abs(float(weight_series.iloc[0]))).gt(0.0).sum())


def count_switches(state_series: pd.Series) -> int:
    series = state_series.astype(str)
    if series.empty:
        return 0
    return int(series.ne(series.shift(1)).sum() - 1)


def calc_metrics(
    returns_gross: pd.Series,
    returns_net: pd.Series,
    state_series: pd.Series,
    weight_series: pd.Series,
    *,
    model: str,
    l1_risk_days: int,
) -> Dict[str, Any]:
    gross_total_return = compound_return(returns_gross)
    net_total_return = compound_return(returns_net)
    net_cagr = annualize_return(net_total_return, len(returns_net))
    max_dd = max_drawdown_from_returns(returns_net)
    total_cost_pct = round(
        (
            pd.to_numeric(returns_gross, errors="coerce").fillna(0.0)
            - pd.to_numeric(returns_net, errors="coerce").fillna(0.0)
        ).sum()
        * 100.0,
        6,
    )
    turnover_pressure = round(weight_series.diff().abs().fillna(abs(float(weight_series.iloc[0]))).sum(), 6)
    return {
        "model": model,
        "gross_return_pct": round(gross_total_return * 100.0, 6),
        "net_return_after_costs_pct": round(net_total_return * 100.0, 6),
        "net_cagr_pct": round(net_cagr * 100.0, 6),
        "max_drawdown_pct": round(max_dd * 100.0, 6),
        "trade_count": int(count_trade_days(weight_series)),
        "switch_count": int(count_switches(state_series)),
        "turnover_pressure": turnover_pressure,
        "total_cost_pct": total_cost_pct,
        "l1_risk_days": int(l1_risk_days),
    }


def valid_handoff_windows(activation_windows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in activation_windows if str(row["baseline_handoff_date"]).strip()]


def build_compare_rows(
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    valid_windows = valid_handoff_windows(activation_windows)
    lead_days = [int(row["lead_days_vs_baseline"]) for row in valid_windows]
    net_capture = sum(float(row["net_early_move_capture"]) for row in activation_windows)
    gross_capture = sum(float(row["gross_early_move_capture"]) for row in activation_windows)
    metrics = [
        ("number_of_earlier_activation_windows", 0.0, float(len(valid_windows))),
        ("avg_lead_days_vs_baseline", 0.0, float(sum(lead_days) / len(lead_days)) if lead_days else 0.0),
        ("median_lead_days_vs_baseline", 0.0, float(median(lead_days)) if lead_days else 0.0),
        ("max_lead_days_vs_baseline", 0.0, float(max(lead_days)) if lead_days else 0.0),
        ("net_early_move_capture_pct", 0.0, net_capture),
        ("gross_early_move_capture_pct", 0.0, gross_capture),
        ("trade_count", baseline_metrics["trade_count"], probe_metrics["trade_count"]),
        ("switch_count", baseline_metrics["switch_count"], probe_metrics["switch_count"]),
        ("turnover_pressure", baseline_metrics["turnover_pressure"], probe_metrics["turnover_pressure"]),
        ("net_max_drawdown_pct", baseline_metrics["max_drawdown_pct"], probe_metrics["max_drawdown_pct"]),
        ("net_total_return_pct", baseline_metrics["net_return_after_costs_pct"], probe_metrics["net_return_after_costs_pct"]),
        ("net_cagr_pct", baseline_metrics["net_cagr_pct"], probe_metrics["net_cagr_pct"]),
        ("gross_total_return_pct", baseline_metrics["gross_return_pct"], probe_metrics["gross_return_pct"]),
        ("l1_risk_days", baseline_metrics["l1_risk_days"], probe_metrics["l1_risk_days"]),
    ]
    return [
        {
            "metric": metric,
            "baseline_model": BASELINE_MODEL,
            "baseline_value": float(baseline_value),
            "probe_model": PROBE_MODEL,
            "probe_value": float(probe_value),
            "delta_probe_minus_baseline": float(probe_value) - float(baseline_value),
        }
        for metric, baseline_value, probe_value in metrics
    ]


def build_summary_payload(
    *,
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
    cost_cfg: Dict[str, float],
    input_refs: Dict[str, Any],
) -> Dict[str, Any]:
    valid_windows = valid_handoff_windows(activation_windows)
    lead_days = [int(row["lead_days_vs_baseline"]) for row in valid_windows]
    net_capture = round(sum(float(row["net_early_move_capture"]) for row in activation_windows), 6)
    gross_capture = round(sum(float(row["gross_early_move_capture"]) for row in activation_windows), 6)
    trade_delta = int(probe_metrics["trade_count"] - baseline_metrics["trade_count"])
    switch_delta = int(probe_metrics["switch_count"] - baseline_metrics["switch_count"])
    turnover_delta = round(float(probe_metrics["turnover_pressure"] - baseline_metrics["turnover_pressure"]), 6)
    dd_delta = round(float(probe_metrics["max_drawdown_pct"] - baseline_metrics["max_drawdown_pct"]), 6)
    net_delta = round(float(probe_metrics["net_return_after_costs_pct"] - baseline_metrics["net_return_after_costs_pct"]), 6)
    cagr_delta = round(float(probe_metrics["net_cagr_pct"] - baseline_metrics["net_cagr_pct"]), 6)
    gross_delta = round(float(probe_metrics["gross_return_pct"] - baseline_metrics["gross_return_pct"]), 6)

    earlier_activation_ok = len(valid_windows) > 1
    churn_ok = trade_delta <= 3 and switch_delta <= 3 and turnover_delta <= 3.0
    dd_ok = dd_delta >= -1.0
    net_ok = net_delta > 0.0 and net_capture > 0.0
    stop_triggered = (not earlier_activation_ok) or (not churn_ok) or (not dd_ok) or (not net_ok)
    final_verdict = "stop_condition_triggered" if stop_triggered else "continue_dev_only"

    return with_json_locks(
        {
            "artifact_id": "l1_trend_filter_regime_probe",
            "generated_at_utc": timestamp_utc(),
            "final_verdict": final_verdict,
            "mechanism_id": MECHANISM_ID,
            "compare_baseline": BASELINE_MODEL,
            "number_of_earlier_activation_windows": int(len(valid_windows)),
            "lead_days_vs_baseline": {
                "all_valid_handoff_windows": lead_days,
                "avg": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
                "median": round(float(median(lead_days)), 6) if lead_days else 0.0,
                "max": int(max(lead_days)) if lead_days else 0,
            },
            "net_early_move_capture_pct": net_capture,
            "trade_days_delta": trade_delta,
            "switch_count_delta": switch_delta,
            "turnover_pressure_delta": turnover_delta,
            "net_max_drawdown_delta_pct": dd_delta,
            "net_total_return_delta_pct": net_delta,
            "net_cagr_delta_pct": cagr_delta,
            "gross_metrics_context": {
                "gross_early_move_capture_pct": gross_capture,
                "gross_total_return_baseline_pct": round(float(baseline_metrics["gross_return_pct"]), 6),
                "gross_total_return_probe_pct": round(float(probe_metrics["gross_return_pct"]), 6),
                "gross_total_return_delta_pct": gross_delta,
            },
            "baseline_metrics": baseline_metrics,
            "probe_metrics": probe_metrics,
            "exact_state_regime_rule": STATE_RULE,
            "exact_one_sided_implementation_method": ONE_SIDED_METHOD,
            "exact_rolling_window_used": {
                "rolling_window_days": ROLLING_WINDOW_DAYS,
                "price_input": "BTCUSDT daily close",
                "transform": "log price, daily log-return slopes",
            },
            "exact_lambda_rule_used": LAMBDA_RULE,
            "hysteresis": {
                "used": False,
                "entry_slope_threshold": SLOPE_ENTRY_THRESHOLD,
            },
            "cost_model": {
                "source_context": "phase68i dynamic ladder export fee/slippage fields used only as secondary cost assumptions",
                "trading_fee_bps": cost_cfg["trading_fee_bps"],
                "slippage_bps": cost_cfg["slippage_bps"],
                "turnover_cost_per_unit": cost_cfg["turnover_cost_per_unit"],
            },
            "stop_condition": {
                "rule": STOP_RULE,
                "triggered": bool(stop_triggered),
                "components": {
                    "earlier_activation_ok": bool(earlier_activation_ok),
                    "churn_ok": bool(churn_ok),
                    "drawdown_ok": bool(dd_ok),
                    "net_ok": bool(net_ok),
                },
            },
            "input_refs": input_refs,
            "status": "generated_dev_only_l1_trend_filter_regime_probe_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": "l1_trend_filter_regime_probe_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [
                "research_os/dev_only/contracts/dev_only_l1_trend_filter_regime_probe.contract.json"
            ],
            "spec_refs": [
                "research_os/dev_only/specs/dev_only_l1_trend_filter_regime_probe.spec.json"
            ],
            "manifest_seed_refs": [
                "research_os/dev_only/manifests/dev_only_l1_trend_filter_regime_probe.manifest.json"
            ],
            "status": "implementation_pack_ready",
        }
    )


def build_quality_payload(
    frame: pd.DataFrame,
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
    input_refs: Dict[str, Any],
) -> Dict[str, Any]:
    l1_rows = frame.loc[frame["l1_window_end_date"].astype(str).ne("")]
    causal_end_ok = bool(
        (l1_rows["l1_window_end_date"].astype(str) == l1_rows.index.strftime("%Y-%m-%d")).all()
    ) if not l1_rows.empty else False
    checks = [
        {
            "name": "one_sided_window_end_equals_current_day",
            "ok": causal_end_ok,
            "detail": "every computed L1 signal window ends on the same date receiving the signal",
        },
        {
            "name": "full_window_required_before_signal",
            "ok": not bool(frame.iloc[: ROLLING_WINDOW_DAYS - 1]["l1_risk_on_permission_raw"].any()),
            "detail": f"first {ROLLING_WINDOW_DAYS - 1} rows have no L1 risk-on permission",
        },
        {
            "name": "l1_risk_only_on_baseline_cash_days",
            "ok": not bool((frame["l1_active"] & (~frame["baseline_cash"])).any()),
            "detail": "L1 BTC risk never overlaps with baseline risk-on exposure",
        },
        {
            "name": "baseline_risk_days_unchanged",
            "ok": bool(
                (
                    frame.loc[frame["in_market"], "probe_strategy_return_gross"]
                    == pd.to_numeric(frame.loc[frame["in_market"], "strategy_return"], errors="coerce").fillna(0.0)
                ).all()
            ),
            "detail": "baseline in-market daily returns pass through unchanged",
        },
        {
            "name": "no_pilot_or_ladder_states",
            "ok": not bool(frame["probe_state"].astype(str).str.contains("PILOT|FULL_PRE_BASELINE", regex=True).any()),
            "detail": "probe states are CASH, L1_BTC_RISK, and BASELINE_RISK only",
        },
        {
            "name": "single_lambda_rule_recorded",
            "ok": bool(LAMBDA_RULE),
            "detail": LAMBDA_RULE,
        },
        {
            "name": "semantic_flags_locked",
            "ok": True,
            "detail": "dev_only=true, non_authoritative=true, official_truth=false, strategy_advancement=false, candidate_selection=false, official_edge_claim=false",
        },
    ]
    return with_json_locks(
        {
            "artifact_id": "l1_trend_filter_regime_probe_quality",
            "generated_at_utc": timestamp_utc(),
            "input_refs": input_refs,
            "checks": checks,
            "activation_window_count": int(len(activation_windows)),
            "baseline_metrics": baseline_metrics,
            "probe_metrics": probe_metrics,
            "status": "passed" if all(check["ok"] for check in checks) else "failed",
        }
    )


def main() -> None:
    args = parse_args()
    baseline_path = Path(args.baseline_paper)
    phase68i_paper_path = Path(args.phase68i_paper)
    phase68i_summary_path = Path(args.phase68i_summary)

    baseline_df = cash_diag.load_paper(baseline_path)
    frame = build_probe_frame(baseline_df)
    cost_cfg = load_phase68i_cost_assumptions(phase68i_summary_path, phase68i_paper_path)
    frame = apply_cost_model(frame, cost_cfg)

    activation_windows = build_activation_windows(frame)
    baseline_metrics = calc_metrics(
        returns_gross=frame["strategy_return"],
        returns_net=frame["baseline_strategy_return_net"],
        state_series=frame["in_market"].map({True: "BASELINE_RISK", False: "CASH"}),
        weight_series=frame["baseline_exposure_weight"],
        model=BASELINE_MODEL,
        l1_risk_days=0,
    )
    probe_metrics = calc_metrics(
        returns_gross=frame["probe_strategy_return_gross"],
        returns_net=frame["probe_strategy_return_net"],
        state_series=frame["probe_state"],
        weight_series=frame["probe_exposure_weight"],
        model=PROBE_MODEL,
        l1_risk_days=int(frame["l1_active"].sum()),
    )

    input_refs = {
        "baseline_paper": str(baseline_path),
        "btc_ohlcv": str(cash_diag.resolve_asset_daily_path("BTC")),
        "phase68i_paper_secondary_context": str(phase68i_paper_path) if phase68i_paper_path.exists() else None,
        "phase68i_summary_secondary_context": str(phase68i_summary_path) if phase68i_summary_path.exists() else None,
    }
    paths = output_paths()

    save_csv(paths["window_compare_csv"], activation_windows, WINDOW_COMPARE_COLUMNS)
    save_csv(paths["state_time_csv"], build_state_time_rows(frame), STATE_TIME_COLUMNS)
    save_csv(paths["compare_csv"], build_compare_rows(baseline_metrics, probe_metrics, activation_windows), COMPARE_COLUMNS)
    save_csv(paths["cost_metrics_csv"], [baseline_metrics, probe_metrics], COST_COLUMNS)
    save_json(
        paths["summary_json"],
        build_summary_payload(
            baseline_metrics=baseline_metrics,
            probe_metrics=probe_metrics,
            activation_windows=activation_windows,
            cost_cfg=cost_cfg,
            input_refs=input_refs,
        ),
    )
    save_json(paths["manifest_json"], build_manifest_payload(paths, input_refs))
    save_json(
        paths["quality_json"],
        build_quality_payload(
            frame=frame,
            baseline_metrics=baseline_metrics,
            probe_metrics=probe_metrics,
            activation_windows=activation_windows,
            input_refs=input_refs,
        ),
    )

    print("l1_trend_filter_regime_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
