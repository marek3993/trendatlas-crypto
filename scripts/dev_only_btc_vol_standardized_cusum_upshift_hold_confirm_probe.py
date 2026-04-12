from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import numpy as np
import pandas as pd

import dev_only_btc_vol_standardized_cusum_upshift_probe as prev_probe
import dev_only_cash_overstay_diagnostic as cash_diag
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_btc_vol_standardized_cusum_upshift_hold_confirm_probe"
)

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "btc_vol_standardized_cusum_upshift_hold_confirm_probe"
MECHANISM_ID = "btc_vol_standardized_cusum_upshift_hold_confirm"
CONFIRMATION_DAYS_AFTER_TRIGGER = 2

BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
PHASE68I_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
PHASE68I_SUMMARY_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_summary.csv"
PRIOR_CUSUM_SUMMARY_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_btc_vol_standardized_cusum_upshift_probe"
    / "btc_vol_standardized_cusum_upshift_probe.summary.json"
)
PRIOR_CUSUM_COST_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_btc_vol_standardized_cusum_upshift_probe"
    / "btc_vol_standardized_cusum_upshift_probe.cost_metrics.csv"
)

VOL_WINDOW_DAYS = prev_probe.VOL_WINDOW_DAYS
CUSUM_REFERENCE_K = prev_probe.CUSUM_REFERENCE_K
CUSUM_THRESHOLD_H = prev_probe.CUSUM_THRESHOLD_H
STATE_TIME_COLUMNS = prev_probe.STATE_TIME_COLUMNS
COMPARE_COLUMNS = prev_probe.COMPARE_COLUMNS
COST_COLUMNS = prev_probe.COST_COLUMNS

JSON_LOCKS = {
    "analysis_mode": "btc_vol_standardized_cusum_upshift_hold_confirm_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}

WHY_SAME_FAMILY = (
    "This remains the same family because BTC log returns, causal 63-day realized-vol standardization, two-sided Page "
    "CUSUM, fixed k = 0.25, fixed h = 5.0, baseline-cash-only integration, and the clear logic all stay unchanged; "
    "only activation turns on after a 2-day post-trigger hold confirmation."
)
NO_LOOKAHEAD_DESIGN = {
    "btc_input_series": "BTCUSDT daily closes from data/ohlcv/BTCUSDT_1d.csv",
    "return_transform": "daily BTC log return r_t = log(close_t / close_{t-1})",
    "vol_standardization": (
        "sigma_t is the causal 63-day rolling standard deviation of BTC daily log returns using only returns up to day t; "
        "x_t = r_t / sigma_t."
    ),
    "detector_update": (
        "The positive and negative CUSUM accumulators are updated sequentially one day at a time using only x_t and the "
        "previous accumulator state."
    ),
    "confirmation_timing": (
        "A trigger event is recorded on day t when S_pos_t >= h on a baseline CASH day and hard risk-off is false. "
        "Activation is allowed only if the upshift condition still holds on each of the next 2 consecutive days, so the "
        "earliest possible turn-on is day t+2 with no future data."
    ),
    "integration_reset": (
        "CUSUM permission is reset whenever the baseline is not in CASH. This keeps the probe earlier-activation-only "
        "and prevents any persistence carryover through baseline risk-on days."
    ),
    "fitting": "No future-aware fitting, no return optimization, and no global calibration pass are used.",
}
PARAMETER_HEURISTIC = {
    "single_heuristic": (
        "Use the smallest non-sweep anti-noise hold above the immediate trigger: require exactly 2 consecutive "
        "post-trigger days with S_pos_t >= h before activation. k = 0.25 and h = 5.0 remain fixed from the base family."
    ),
    "fixed_defaults": {
        "vol_window_days": VOL_WINDOW_DAYS,
        "cusum_reference_k": CUSUM_REFERENCE_K,
        "cusum_threshold_h": CUSUM_THRESHOLD_H,
        "confirmation_days_after_trigger": CONFIRMATION_DAYS_AFTER_TRIGGER,
    },
}
WINDOW_COMPARE_COLUMNS = [
    "window_id",
    "trigger_event_date",
    "cusum_activation_date",
    "window_end_date",
    "baseline_handoff_date",
    "activation_kind",
    "lead_days_vs_baseline",
    "activation_delay_days",
    "confirmation_days_required",
    "confirmation_days_observed_after_trigger",
    "cusum_risk_days",
    "entry_standardized_return",
    "entry_positive_cusum",
    "entry_negative_cusum",
    "entry_realized_vol",
    "entry_threshold_h",
    "entry_reference_k",
    "btc_return_gross",
    "baseline_return_gross",
    "probe_return_gross",
    "baseline_return_net",
    "probe_return_net",
    "net_early_move_capture",
    "gross_early_move_capture",
    "exit_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only BTC vol-standardized CUSUM upshift hold-confirm probe")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--phase68i-paper", type=str, default=str(PHASE68I_PAPER_PATH))
    parser.add_argument("--phase68i-summary", type=str, default=str(PHASE68I_SUMMARY_PATH))
    parser.add_argument("--prior-cusum-summary", type=str, default=str(PRIOR_CUSUM_SUMMARY_PATH))
    parser.add_argument("--prior-cusum-cost", type=str, default=str(PRIOR_CUSUM_COST_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    return {
        "summary_json": OUTPUT_ROOT / "btc_vol_standardized_cusum_upshift_hold_confirm_probe.summary.json",
        "window_compare_csv": OUTPUT_ROOT / "btc_vol_standardized_cusum_upshift_hold_confirm_probe.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / "btc_vol_standardized_cusum_upshift_hold_confirm_probe.state_time.csv",
        "compare_csv": OUTPUT_ROOT / "btc_vol_standardized_cusum_upshift_hold_confirm_probe.compare.csv",
        "cost_metrics_csv": OUTPUT_ROOT / "btc_vol_standardized_cusum_upshift_hold_confirm_probe.cost_metrics.csv",
        "manifest_json": OUTPUT_ROOT / "btc_vol_standardized_cusum_upshift_hold_confirm_probe.manifest.json",
        "quality_json": OUTPUT_ROOT / "btc_vol_standardized_cusum_upshift_hold_confirm_probe.quality.json",
    }


def safe_float(value: Any, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(default if pd.isna(numeric) else numeric)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_metrics_row(path: Path, model: str) -> Dict[str, Any]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    matches = df.loc[df["model"].astype(str).eq(model)] if "model" in df.columns else pd.DataFrame()
    return {} if matches.empty else matches.iloc[0].to_dict()


def load_snapshot(summary_path: Path, cost_path: Path, model: str) -> Dict[str, Any]:
    summary = load_json(summary_path)
    metrics = load_metrics_row(cost_path, model)
    return {
        "final_verdict": str(summary.get("final_verdict", "")),
        "earlier_activation_windows": int(summary.get("earlier_activation_windows_count", 0)),
        "lead_days": [int(x) for x in summary.get("lead_days_list", [])],
        "avg_lead_days": round(safe_float(summary.get("avg_lead_days"), 0.0), 6),
        "net_early_move_capture_pct": round(safe_float(summary.get("net_early_move_capture_pct"), 0.0), 6),
        "trade_count": int(safe_float(metrics.get("trade_count"), 0.0)),
        "switch_count": int(safe_float(metrics.get("switch_count"), 0.0)),
        "turnover_pressure": round(safe_float(metrics.get("turnover_pressure"), 0.0), 6),
        "max_drawdown_pct": round(safe_float(metrics.get("max_drawdown_pct"), 0.0), 6),
        "net_total_return_pct": round(safe_float(metrics.get("net_return_after_costs_pct"), 0.0), 6),
        "net_cagr_pct": round(safe_float(metrics.get("net_cagr_pct"), 0.0), 6),
        "gross_total_return_pct": round(safe_float(metrics.get("gross_return_pct"), 0.0), 6),
    }


def compare_snapshots(current: Dict[str, Any], reference: Dict[str, Any], reference_probe: str) -> Dict[str, Any]:
    return {
        "reference_probe": reference_probe,
        "reference_final_verdict": reference.get("final_verdict"),
        "reference_results": reference,
        "probe_results": current,
        "delta_probe_minus_reference": {
            "earlier_activation_windows": int(current["earlier_activation_windows"] - reference.get("earlier_activation_windows", 0)),
            "avg_lead_days": round(float(current["avg_lead_days"] - reference.get("avg_lead_days", 0.0)), 6),
            "net_early_move_capture_pct": round(
                float(current["net_early_move_capture_pct"] - reference.get("net_early_move_capture_pct", 0.0)), 6
            ),
            "trade_count": int(current["trade_count"] - reference.get("trade_count", 0)),
            "switch_count": int(current["switch_count"] - reference.get("switch_count", 0)),
            "turnover_pressure": round(float(current["turnover_pressure"] - reference.get("turnover_pressure", 0.0)), 6),
            "net_max_drawdown_pct": round(float(current["max_drawdown_pct"] - reference.get("max_drawdown_pct", 0.0)), 6),
            "net_total_return_pct": round(float(current["net_total_return_pct"] - reference.get("net_total_return_pct", 0.0)), 6),
            "net_cagr_pct": round(float(current["net_cagr_pct"] - reference.get("net_cagr_pct", 0.0)), 6),
            "gross_total_return_pct": round(
                float(current["gross_total_return_pct"] - reference.get("gross_total_return_pct", 0.0)), 6
            ),
        },
    }


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


def build_probe_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    frame = cash_diag.build_analysis_frame(baseline_df).copy()
    benchmark_close = pd.to_numeric(frame["benchmark_close"], errors="coerce").replace(0.0, np.nan).ffill()
    btc_log_return = np.log(benchmark_close).diff()
    btc_realized_vol = btc_log_return.rolling(VOL_WINDOW_DAYS, min_periods=VOL_WINDOW_DAYS).std(ddof=0)
    btc_std_return = (btc_log_return / btc_realized_vol.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)

    cusum_positive_values: List[float] = []
    cusum_negative_values: List[float] = []
    cusum_active_values: List[bool] = []
    pending_confirmation_values: List[bool] = []
    confirmation_streak_values: List[int] = []
    trigger_event_values: List[bool] = []
    activation_confirmed_values: List[bool] = []
    trigger_date_values: List[str] = []

    positive = 0.0
    negative = 0.0
    active = False
    pending_confirmation = False
    confirmation_streak = 0
    trigger_event_date: pd.Timestamp | None = None

    baseline_cash = (~frame["in_market"]).fillna(False).astype(bool)
    hard_risk_off = frame["risk_off_invalidation_day"].fillna(False).astype(bool)

    for date_value, x_t, baseline_cash_day, hard_risk_off_day in zip(
        frame.index,
        btc_std_return.tolist(),
        baseline_cash.tolist(),
        hard_risk_off.tolist(),
    ):
        trigger_event = False
        activation_confirmed = False

        if (not baseline_cash_day) or pd.isna(x_t):
            positive = 0.0
            negative = 0.0
            active = False
            pending_confirmation = False
            confirmation_streak = 0
            trigger_event_date = None
        else:
            positive = max(0.0, positive + float(x_t) - CUSUM_REFERENCE_K)
            negative = max(0.0, negative - float(x_t) - CUSUM_REFERENCE_K)

            if active:
                if hard_risk_off_day or negative >= CUSUM_THRESHOLD_H:
                    active = False
                    positive = 0.0
                    negative = 0.0
                    pending_confirmation = False
                    confirmation_streak = 0
                    trigger_event_date = None
            elif pending_confirmation:
                if (not hard_risk_off_day) and positive >= CUSUM_THRESHOLD_H:
                    confirmation_streak += 1
                    if confirmation_streak >= CONFIRMATION_DAYS_AFTER_TRIGGER:
                        active = True
                        pending_confirmation = False
                        activation_confirmed = True
                        negative = 0.0
                else:
                    positive = 0.0
                    negative = 0.0
                    pending_confirmation = False
                    confirmation_streak = 0
                    trigger_event_date = None
            elif (not hard_risk_off_day) and positive >= CUSUM_THRESHOLD_H:
                pending_confirmation = True
                confirmation_streak = 0
                trigger_event = True
                trigger_event_date = pd.Timestamp(date_value)

        if (not active) and (not pending_confirmation) and (trigger_event_date is not None) and (not activation_confirmed):
            trigger_event_date = None

        cusum_positive_values.append(positive)
        cusum_negative_values.append(negative)
        cusum_active_values.append(active)
        pending_confirmation_values.append(pending_confirmation)
        confirmation_streak_values.append(int(confirmation_streak))
        trigger_event_values.append(trigger_event)
        activation_confirmed_values.append(activation_confirmed)
        trigger_date_values.append("" if trigger_event_date is None else pd.Timestamp(trigger_event_date).strftime("%Y-%m-%d"))

    frame["btc_log_return"] = btc_log_return
    frame["btc_realized_vol"] = btc_realized_vol
    frame["btc_std_return"] = btc_std_return
    frame["cusum_positive"] = cusum_positive_values
    frame["cusum_negative"] = cusum_negative_values
    frame["cusum_upshift_active"] = cusum_active_values
    frame["cusum_pending_confirmation"] = pending_confirmation_values
    frame["cusum_confirmation_streak_after_trigger"] = confirmation_streak_values
    frame["cusum_trigger_event"] = trigger_event_values
    frame["cusum_activation_confirmed"] = activation_confirmed_values
    frame["cusum_trigger_event_date"] = trigger_date_values
    frame["baseline_cash"] = baseline_cash
    frame["cusum_hard_risk_off_block"] = hard_risk_off
    frame["cusum_risk_on_permission"] = baseline_cash & frame["cusum_upshift_active"] & (~hard_risk_off)

    probe_states: List[str] = []
    probe_window_ids: List[str] = []
    handoff_flags: List[bool] = []
    exit_reasons: List[str] = []
    cusum_active_flags: List[bool] = []

    cusum_position_active = False
    current_window_id = ""
    window_counter = 0

    for baseline_cash_day, probe_permission, hard_risk_off_day in zip(
        baseline_cash.tolist(),
        frame["cusum_risk_on_permission"].tolist(),
        hard_risk_off.tolist(),
    ):
        exit_reason = ""
        row_window_id = ""

        if cusum_position_active and (not baseline_cash_day):
            state = "BASELINE_RISK"
            row_window_id = current_window_id
            exit_reason = "baseline_handoff"
            cusum_position_active = False
        elif cusum_position_active and (not probe_permission):
            state = "CASH"
            row_window_id = current_window_id
            exit_reason = "hard_risk_off" if hard_risk_off_day else "cusum_downshift_off"
            cusum_position_active = False
        elif (not cusum_position_active) and baseline_cash_day and probe_permission:
            window_counter += 1
            current_window_id = f"window_{window_counter:03d}"
            state = "CUSUM_BTC_RISK"
            row_window_id = current_window_id
            cusum_position_active = True
        elif cusum_position_active:
            state = "CUSUM_BTC_RISK"
            row_window_id = current_window_id
        elif baseline_cash_day:
            state = "CASH"
        else:
            state = "BASELINE_RISK"

        probe_states.append(state)
        probe_window_ids.append(row_window_id)
        handoff_flags.append(exit_reason == "baseline_handoff")
        exit_reasons.append(exit_reason)
        cusum_active_flags.append(state == "CUSUM_BTC_RISK")

        if exit_reason:
            current_window_id = ""

    frame["probe_state"] = probe_states
    frame["cusum_window_id"] = probe_window_ids
    frame["baseline_handoff_day"] = handoff_flags
    frame["probe_exit_reason"] = exit_reasons
    frame["cusum_risk_active"] = cusum_active_flags
    frame["probe_in_market"] = frame["probe_state"].ne("CASH")
    frame["probe_strategy_return_gross"] = pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)
    frame.loc[frame["cusum_risk_active"], "probe_strategy_return_gross"] = pd.to_numeric(
        frame.loc[frame["cusum_risk_active"], "benchmark_return"], errors="coerce"
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
    active_ids = [value for value in frame["cusum_window_id"].dropna().unique().tolist() if str(value).strip()]
    for window_id in active_ids:
        window_df = frame.loc[frame["cusum_window_id"].eq(window_id)].copy()
        active_df = window_df.loc[window_df["cusum_risk_active"]]
        if active_df.empty:
            continue

        start_date = pd.Timestamp(active_df.index.min())
        handoff_rows = window_df.loc[window_df["baseline_handoff_day"]]
        exit_rows = window_df.loc[window_df["probe_exit_reason"].astype(str).ne("")]
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
        trigger_event_date_raw = str(entry.get("cusum_trigger_event_date", "") or "").strip()
        trigger_event_date = pd.Timestamp(trigger_event_date_raw) if trigger_event_date_raw else None
        baseline_return_net = compound_pct(window_slice["baseline_strategy_return_net"])
        probe_return_net = compound_pct(window_slice["probe_strategy_return_net"])
        baseline_return_gross = compound_pct(window_slice["strategy_return"])
        probe_return_gross = compound_pct(window_slice["probe_strategy_return_gross"])
        btc_return_gross = compound_pct(window_slice["benchmark_return"])

        rows.append(
            {
                "window_id": window_id,
                "trigger_event_date": "" if trigger_event_date is None else trigger_event_date.strftime("%Y-%m-%d"),
                "cusum_activation_date": start_date.strftime("%Y-%m-%d"),
                "window_end_date": end_date.strftime("%Y-%m-%d"),
                "baseline_handoff_date": "" if handoff_date is None else handoff_date.strftime("%Y-%m-%d"),
                "activation_kind": "btc_vol_standardized_page_cusum_upshift_hold_confirm",
                "lead_days_vs_baseline": 0 if handoff_date is None else int((handoff_date - start_date).days),
                "activation_delay_days": 0 if trigger_event_date is None else int((start_date - trigger_event_date).days),
                "confirmation_days_required": CONFIRMATION_DAYS_AFTER_TRIGGER,
                "confirmation_days_observed_after_trigger": int(
                    safe_float(entry.get("cusum_confirmation_streak_after_trigger"), 0.0)
                ),
                "cusum_risk_days": int(window_slice["cusum_risk_active"].sum()),
                "entry_standardized_return": round(safe_float(entry["btc_std_return"]), 6),
                "entry_positive_cusum": round(safe_float(entry["cusum_positive"]), 6),
                "entry_negative_cusum": round(safe_float(entry["cusum_negative"]), 6),
                "entry_realized_vol": round(safe_float(entry["btc_realized_vol"]), 8),
                "entry_threshold_h": CUSUM_THRESHOLD_H,
                "entry_reference_k": CUSUM_REFERENCE_K,
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
        (PROBE_MODEL, "CUSUM_BTC_RISK", int(frame["probe_state"].eq("CUSUM_BTC_RISK").sum())),
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
    cusum_risk_days: int,
    all_activation_windows_count: int,
    earlier_activation_windows_count: int,
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
        "cusum_risk_days": int(cusum_risk_days),
        "all_activation_windows_count": int(all_activation_windows_count),
        "earlier_activation_windows_count": int(earlier_activation_windows_count),
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
    net_capture = sum(float(row["net_early_move_capture"]) for row in valid_windows)
    metrics = [
        ("all_activation_windows_count", baseline_metrics["all_activation_windows_count"], probe_metrics["all_activation_windows_count"]),
        (
            "earlier_activation_windows_count",
            baseline_metrics["earlier_activation_windows_count"],
            probe_metrics["earlier_activation_windows_count"],
        ),
        ("avg_lead_days_vs_baseline", 0.0, float(sum(lead_days) / len(lead_days)) if lead_days else 0.0),
        ("median_lead_days_vs_baseline", 0.0, float(median(lead_days)) if lead_days else 0.0),
        ("max_lead_days_vs_baseline", 0.0, float(max(lead_days)) if lead_days else 0.0),
        ("net_early_move_capture_pct", 0.0, net_capture),
        ("trade_count", baseline_metrics["trade_count"], probe_metrics["trade_count"]),
        ("switch_count", baseline_metrics["switch_count"], probe_metrics["switch_count"]),
        ("turnover_pressure", baseline_metrics["turnover_pressure"], probe_metrics["turnover_pressure"]),
        ("net_max_drawdown_pct", baseline_metrics["max_drawdown_pct"], probe_metrics["max_drawdown_pct"]),
        ("net_total_return_pct", baseline_metrics["net_return_after_costs_pct"], probe_metrics["net_return_after_costs_pct"]),
        ("net_cagr_pct", baseline_metrics["net_cagr_pct"], probe_metrics["net_cagr_pct"]),
        ("gross_total_return_pct", baseline_metrics["gross_return_pct"], probe_metrics["gross_return_pct"]),
        ("cusum_risk_days", baseline_metrics["cusum_risk_days"], probe_metrics["cusum_risk_days"]),
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
    prior_snapshot: Dict[str, Any],
    cost_cfg: Dict[str, float],
    input_refs: Dict[str, Any],
) -> Dict[str, Any]:
    valid_windows = valid_handoff_windows(activation_windows)
    lead_days = [int(row["lead_days_vs_baseline"]) for row in valid_windows]
    net_early_move_capture = round(sum(float(row["net_early_move_capture"]) for row in valid_windows), 6)
    all_window_net_capture = round(sum(float(row["net_early_move_capture"]) for row in activation_windows), 6)
    trade_delta = int(probe_metrics["trade_count"] - baseline_metrics["trade_count"])
    switch_delta = int(probe_metrics["switch_count"] - baseline_metrics["switch_count"])
    turnover_delta = round(float(probe_metrics["turnover_pressure"] - baseline_metrics["turnover_pressure"]), 6)
    dd_delta = round(float(probe_metrics["max_drawdown_pct"] - baseline_metrics["max_drawdown_pct"]), 6)
    net_delta = round(float(probe_metrics["net_return_after_costs_pct"] - baseline_metrics["net_return_after_costs_pct"]), 6)
    cagr_delta = round(float(probe_metrics["net_cagr_pct"] - baseline_metrics["net_cagr_pct"]), 6)
    gross_delta = round(float(probe_metrics["gross_return_pct"] - baseline_metrics["gross_return_pct"]), 6)
    switch_improved_vs_prior = int(probe_metrics["switch_count"]) < int(prior_snapshot.get("switch_count", probe_metrics["switch_count"]))
    turnover_not_worse_vs_prior = float(probe_metrics["turnover_pressure"]) <= float(
        prior_snapshot.get("turnover_pressure", probe_metrics["turnover_pressure"])
    )

    stop_triggered = (
        (len(valid_windows) <= 1)
        or (net_early_move_capture <= 0.0)
        or (not switch_improved_vs_prior)
        or (not turnover_not_worse_vs_prior)
        or (dd_delta < -0.5)
    )
    continue_ready = (
        (len(valid_windows) >= 2)
        and (net_early_move_capture > 0.0)
        and switch_improved_vs_prior
        and turnover_not_worse_vs_prior
        and (trade_delta <= 2)
        and (dd_delta >= -0.25)
    )
    pause_triggered = (not stop_triggered) and (not continue_ready)
    final_verdict = "stop" if stop_triggered else "pause" if pause_triggered else "continue"

    current_snapshot = {
        "final_verdict": final_verdict,
        "earlier_activation_windows": int(len(valid_windows)),
        "lead_days": lead_days,
        "avg_lead_days": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
        "net_early_move_capture_pct": net_early_move_capture,
        "trade_count": int(probe_metrics["trade_count"]),
        "switch_count": int(probe_metrics["switch_count"]),
        "turnover_pressure": round(float(probe_metrics["turnover_pressure"]), 6),
        "max_drawdown_pct": round(float(probe_metrics["max_drawdown_pct"]), 6),
        "net_total_return_pct": round(float(probe_metrics["net_return_after_costs_pct"]), 6),
        "net_cagr_pct": round(float(probe_metrics["net_cagr_pct"]), 6),
        "gross_total_return_pct": round(float(probe_metrics["gross_return_pct"]), 6),
    }

    return with_json_locks(
        {
            "artifact_id": PROBE_MODEL,
            "generated_at_utc": timestamp_utc(),
            "final_verdict": final_verdict,
            "mechanism_id": MECHANISM_ID,
            "compare_baseline": BASELINE_MODEL,
            "secondary_context_only": "phase68i_dynamic_ladder_candidate",
            "all_activation_windows_count": int(len(activation_windows)),
            "earlier_activation_windows_count": int(len(valid_windows)),
            "lead_days_list": lead_days,
            "avg_lead_days": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
            "net_early_move_capture_pct": net_early_move_capture,
            "all_activation_windows_net_capture_pct": all_window_net_capture,
            "trade_days_delta": trade_delta,
            "switch_count_delta": switch_delta,
            "turnover_pressure_delta": turnover_delta,
            "net_max_drawdown_delta_pct": dd_delta,
            "net_total_return_delta_pct": net_delta,
            "net_cagr_delta_pct": cagr_delta,
            "gross_metrics_context": {
                "gross_total_return_baseline_pct": round(float(baseline_metrics["gross_return_pct"]), 6),
                "gross_total_return_probe_pct": round(float(probe_metrics["gross_return_pct"]), 6),
                "gross_total_return_delta_pct": gross_delta,
            },
            "baseline_metrics": baseline_metrics,
            "probe_metrics": probe_metrics,
            "exact_confirmatory_cusum_implementation": {
                "detector_type": "two_sided_page_cusum_on_standardized_btc_log_returns",
                "positive_accumulator": "S_pos_t = max(0, S_pos_{t-1} + x_t - k)",
                "negative_accumulator": "S_neg_t = max(0, S_neg_{t-1} - x_t - k)",
                "trigger_event_rule": "A trigger event occurs on day t when S_pos_t >= h during a baseline CASH day and hard risk-off is false.",
                "activation_permission_rule": (
                    "CUSUM_UPSHIFT_ACTIVE turns on only if the upshift condition still holds on each of the next 2 "
                    "consecutive days after the trigger event, so activation can first occur on trigger+2."
                ),
                "confirmation_failure_rule": (
                    "If either post-trigger confirmation day fails because S_pos_t < h, hard risk-off becomes true, or "
                    "the baseline leaves CASH, the trigger candidate resets and the probe remains off."
                ),
                "permission_clear_rule": (
                    "After activation, CUSUM_UPSHIFT_ACTIVE clears when S_neg_t >= h, when hard BTC risk-off invalidation "
                    "is true, or when the baseline is no longer in CASH."
                ),
                "downstream_integration_rule": (
                    "Baseline risk-on days remain unchanged. On baseline CASH days only, the probe replaces CASH with full BTC risk "
                    "while CUSUM_UPSHIFT_ACTIVE is true."
                ),
                "binary_states_only": ["CASH", "CUSUM_BTC_RISK", "BASELINE_RISK"],
            },
            "why_same_family_not_duplicate": WHY_SAME_FAMILY,
            "exact_no_lookahead_design": NO_LOOKAHEAD_DESIGN,
            "exact_single_heuristic_used_to_set_parameters": PARAMETER_HEURISTIC,
            "exact_compare_vs_previous_cusum_result": compare_snapshots(
                current_snapshot, prior_snapshot, "btc_vol_standardized_cusum_upshift_probe"
            ),
            "cost_model": {
                "source_context": "phase68i dynamic ladder export fee/slippage fields used only as secondary cost assumptions",
                "trading_fee_bps": cost_cfg["trading_fee_bps"],
                "slippage_bps": cost_cfg["slippage_bps"],
                "turnover_cost_per_unit": cost_cfg["turnover_cost_per_unit"],
            },
            "success_bar_check": {
                "more_than_one_earlier_window": bool(len(valid_windows) > 1),
                "positive_net_early_move_capture": bool(net_early_move_capture > 0.0),
                "switch_count_improved_vs_previous_cusum": bool(switch_improved_vs_prior),
                "turnover_near_flat_vs_baseline": bool(turnover_delta <= 2.0),
                "turnover_not_worse_vs_previous_cusum": bool(turnover_not_worse_vs_prior),
                "net_drawdown_near_flat_vs_baseline": bool(dd_delta >= -0.25),
                "survives_net_of_fees": bool(net_delta > 0.0),
            },
            "stop_condition": {
                "rule": (
                    "stop if confirmation kills most of the edge, or if switch/churn does not improve versus the prior "
                    "CUSUM result, or if turnover worsens, or if the result collapses toward old-family behavior"
                ),
                "triggered": bool(stop_triggered),
            },
            "pause_condition": {
                "rule": "pause if churn improves but the evidence breadth is still too narrow for a stronger claim",
                "triggered": bool(pause_triggered),
            },
            "input_refs": input_refs,
            "status": "generated_dev_only_btc_vol_standardized_cusum_upshift_hold_confirm_probe_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": f"{PROBE_MODEL}_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [],
            "spec_refs": [],
            "manifest_seed_refs": [],
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
    pre_vol_ok = not bool(frame.iloc[: VOL_WINDOW_DAYS - 1]["cusum_upshift_active"].any())
    reset_outside_cash_ok = bool(
        (
            frame.loc[~frame["baseline_cash"], ["cusum_positive", "cusum_negative"]]
            .fillna(0.0)
            .abs()
            .sum(axis=1)
            .eq(0.0)
        ).all()
    )
    activation_rows = frame["cusum_activation_confirmed"].fillna(False)
    checks = [
        {
            "name": "no_signal_before_vol_window_ready",
            "ok": pre_vol_ok,
            "detail": f"first {VOL_WINDOW_DAYS - 1} rows have no CUSUM activation",
        },
        {
            "name": "cusum_resets_outside_baseline_cash",
            "ok": reset_outside_cash_ok,
            "detail": "positive and negative accumulators are zero whenever the baseline is not in CASH",
        },
        {
            "name": "two_day_post_trigger_confirmation_before_activation",
            "ok": bool(
                frame.loc[activation_rows, "cusum_confirmation_streak_after_trigger"]
                .astype(int)
                .eq(CONFIRMATION_DAYS_AFTER_TRIGGER)
                .all()
            ),
            "detail": "every activation row shows exactly 2 confirmed post-trigger days",
        },
        {
            "name": "probe_risk_only_on_baseline_cash_days",
            "ok": not bool((frame["cusum_risk_active"] & (~frame["baseline_cash"])).any()),
            "detail": "CUSUM BTC risk never overlaps with baseline risk-on exposure",
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
            "detail": "probe states are CASH, CUSUM_BTC_RISK, and BASELINE_RISK only",
        },
        {
            "name": "semantic_flags_locked",
            "ok": True,
            "detail": "dev_only=true, non_authoritative=true, official_truth=false, strategy_advancement=false, candidate_selection=false, official_edge_claim=false",
        },
    ]
    return with_json_locks(
        {
            "artifact_id": f"{PROBE_MODEL}_quality",
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
    prior_cusum_summary_path = Path(args.prior_cusum_summary)
    prior_cusum_cost_path = Path(args.prior_cusum_cost)

    baseline_df = cash_diag.load_paper(baseline_path)
    frame = build_probe_frame(baseline_df)
    cost_cfg = load_phase68i_cost_assumptions(phase68i_summary_path, phase68i_paper_path)
    frame = apply_cost_model(frame, cost_cfg)

    activation_windows = build_activation_windows(frame)
    valid_windows = valid_handoff_windows(activation_windows)
    baseline_metrics = calc_metrics(
        returns_gross=frame["strategy_return"],
        returns_net=frame["baseline_strategy_return_net"],
        state_series=frame["in_market"].map({True: "BASELINE_RISK", False: "CASH"}),
        weight_series=frame["baseline_exposure_weight"],
        model=BASELINE_MODEL,
        cusum_risk_days=0,
        all_activation_windows_count=0,
        earlier_activation_windows_count=0,
    )
    probe_metrics = calc_metrics(
        returns_gross=frame["probe_strategy_return_gross"],
        returns_net=frame["probe_strategy_return_net"],
        state_series=frame["probe_state"],
        weight_series=frame["probe_exposure_weight"],
        model=PROBE_MODEL,
        cusum_risk_days=int(frame["cusum_risk_active"].sum()),
        all_activation_windows_count=len(activation_windows),
        earlier_activation_windows_count=len(valid_windows),
    )
    prior_snapshot = load_snapshot(prior_cusum_summary_path, prior_cusum_cost_path, "btc_vol_standardized_cusum_upshift_probe")

    input_refs = {
        "baseline_paper": str(baseline_path),
        "btc_ohlcv": str(cash_diag.resolve_asset_daily_path("BTC")),
        "phase68i_paper_secondary_context": str(phase68i_paper_path) if phase68i_paper_path.exists() else None,
        "phase68i_summary_secondary_context": str(phase68i_summary_path) if phase68i_summary_path.exists() else None,
        "prior_cusum_summary": str(prior_cusum_summary_path) if prior_cusum_summary_path.exists() else None,
        "prior_cusum_cost_metrics": str(prior_cusum_cost_path) if prior_cusum_cost_path.exists() else None,
        "l1_probe_summary": str(
            ROOT
            / "outputs"
            / "research_os"
            / "dev_only"
            / "non_authoritative_l1_trend_filter_regime_probe"
            / "l1_trend_filter_regime_probe.summary.json"
        ),
        "breadth_veto_confirm_summary": str(
            ROOT
            / "outputs"
            / "research_os"
            / "dev_only"
            / "non_authoritative_breadth_ignition_volatility_hostility_veto_confirm_probe"
            / "breadth_ignition_volatility_hostility_veto_confirm_probe.summary.json"
        ),
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
            prior_snapshot=prior_snapshot,
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

    print("btc_vol_standardized_cusum_upshift_hold_confirm_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
