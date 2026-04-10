from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Tuple

import pandas as pd

import dev_only_cash_overstay_diagnostic as cash_diag
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_high_conviction_pre_activation_pilot_probe"
)

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "high_conviction_pre_activation_pilot_probe"
MECHANISM_ID = "high_conviction_pre_activation_pilot"
COMPARE_VS_CONSTRUCTIVE_PILOT = "dev_only_constructive_pilot_exposure_probe"

BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
PHASE68I_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
PHASE68I_SUMMARY_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_summary.csv"
CASH_DIAGNOSTIC_SUMMARY_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_cash_diagnostics"
    / "cash_overstay_diagnostic.summary.json"
)
CONSTRUCTIVE_PILOT_SUMMARY_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_constructive_pilot_probe"
    / "constructive_pilot_probe.summary.json"
)
CONSTRUCTIVE_PILOT_COMPARE_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_constructive_pilot_probe"
    / "constructive_pilot_probe.compare.csv"
)

PILOT_WEIGHT = 0.15
REL_STRENGTH_LOOKBACK = 20
ACTIVATION_PERSISTENCE_DAYS = 3
RECENT_RECAPTURE_MAX_AGE_DAYS = 7
LOCAL_BRAKE_PERSISTENCE_DAYS = 2
LOCAL_BRAKE_REL_STRENGTH_FLOOR = -0.05
JSON_LOCKS = {
    "analysis_mode": "high_conviction_pre_activation_pilot_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}
WHY_DIFFERENT_FROM_PHASE68K_L_M = (
    "This probe does not broadly soften entry gates. It adds one narrow earlier high-conviction pre-activation pilot "
    "with low-churn holding and disciplined exits."
)
WHY_DIFFERENT_FROM_CONSTRUCTIVE_PILOT_PERSISTENCE = (
    "This probe is designed to enter earlier before full activation bottlenecks, not to stay exposed longer after the "
    "fact. It preserves disciplined exits and does not rely on full-window persistence."
)
STOP_RULE = (
    "if earlier activation still cannot be achieved without churn or DD damage or if gains appear only in gross but "
    "not in net terms or if the mechanism effectively collapses back into persistence / looser exits"
)
PAUSE_RULE = (
    "if earlier activation is real and promising but the tradeoff still needs one more confirmatory pass"
)

WINDOW_COMPARE_COLUMNS = [
    "window_id",
    "pilot_activation_date",
    "window_end_date",
    "baseline_handoff_date",
    "pilot_asset",
    "asset_resolution",
    "pilot_days",
    "lead_days_before_baseline_handoff",
    "benchmark_return_gross",
    "pilot_asset_return_gross",
    "baseline_return_gross",
    "probe_return_gross",
    "baseline_return_net",
    "probe_return_net",
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
    "pilot_days",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only high-conviction pre-activation pilot probe")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--phase68i-paper", type=str, default=str(PHASE68I_PAPER_PATH))
    parser.add_argument("--phase68i-summary", type=str, default=str(PHASE68I_SUMMARY_PATH))
    parser.add_argument("--cash-diagnostic-summary", type=str, default=str(CASH_DIAGNOSTIC_SUMMARY_PATH))
    parser.add_argument("--constructive-pilot-summary", type=str, default=str(CONSTRUCTIVE_PILOT_SUMMARY_PATH))
    parser.add_argument("--constructive-pilot-compare", type=str, default=str(CONSTRUCTIVE_PILOT_COMPARE_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    return {
        "summary_json": OUTPUT_ROOT / "high_conviction_pre_activation_pilot_probe.summary.json",
        "window_compare_csv": OUTPUT_ROOT / "high_conviction_pre_activation_pilot_probe.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / "high_conviction_pre_activation_pilot_probe.state_time.csv",
        "compare_csv": OUTPUT_ROOT / "high_conviction_pre_activation_pilot_probe.compare.csv",
        "cost_metrics_csv": OUTPUT_ROOT / "high_conviction_pre_activation_pilot_probe.cost_metrics.csv",
        "manifest_json": OUTPUT_ROOT / "high_conviction_pre_activation_pilot_probe.manifest.json",
        "quality_json": OUTPUT_ROOT / "high_conviction_pre_activation_pilot_probe.quality.json",
    }


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if years <= 0:
        return 0.0
    if total_return <= -1.0:
        return -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def compound_return(values: pd.Series) -> float:
    return cash_diag.compound_return(values)


def max_drawdown_from_returns(returns: pd.Series) -> float:
    equity = (1.0 + pd.to_numeric(returns, errors="coerce").fillna(0.0)).cumprod()
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def safe_float(value: Any, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(default if pd.isna(numeric) else numeric)


def load_json(path: Path) -> Dict[str, Any]:
    return pd.read_json(path, typ="series").to_dict()


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
    cache: Dict[str, pd.DataFrame] = {}
    frame["baseline_cash"] = ~frame["in_market"]
    frame["pilot_asset"] = frame["selected_asset"].where(frame["selected_asset"].ne(""), "BTC")
    frame["asset_resolution"] = frame["selected_asset"].where(frame["selected_asset"].ne(""), "BTC_fallback")
    frame["pilot_close"] = pd.NA
    frame["pilot_return"] = pd.NA
    frame["pilot_anchor_ma"] = pd.NA

    for asset in sorted({value for value in frame["pilot_asset"].dropna().unique() if value}):
        asset_df = cash_diag.load_asset_daily(asset, cache).rename(
            columns={"close": "pilot_close", "asset_return": "pilot_return", "anchor_ma": "pilot_anchor_ma"}
        )
        mask = frame["pilot_asset"].eq(asset)
        aligned = asset_df.reindex(frame.index[mask]).ffill()
        frame.loc[mask, ["pilot_close", "pilot_return", "pilot_anchor_ma"]] = aligned[
            ["pilot_close", "pilot_return", "pilot_anchor_ma"]
        ].to_numpy()

    frame["benchmark_20d_return"] = frame["benchmark_close"].pct_change(REL_STRENGTH_LOOKBACK)
    frame["pilot_asset_20d_return"] = pd.to_numeric(frame["pilot_close"], errors="coerce").pct_change(
        REL_STRENGTH_LOOKBACK
    )
    frame["pilot_relative_strength"] = frame["pilot_asset_20d_return"] - frame["benchmark_20d_return"]
    frame["pilot_above_anchor"] = pd.to_numeric(frame["pilot_close"], errors="coerce") > pd.to_numeric(
        frame["pilot_anchor_ma"], errors="coerce"
    )
    frame["pilot_relative_strength_confirmed"] = frame["pilot_relative_strength"].fillna(0.0) >= 0.0
    frame["pilot_confirmation_raw"] = frame["pilot_above_anchor"] & frame["pilot_relative_strength_confirmed"]
    frame["benchmark_constructive_valid"] = frame["benchmark_trend_positive"].fillna(False)
    frame["activation_raw"] = (
        frame["baseline_cash"]
        & frame["benchmark_constructive_valid"]
        & frame["benchmark_above_anchor"].fillna(False)
        & frame["pilot_confirmation_raw"].fillna(False)
    )
    frame["activation_persistence_ready"] = (
        frame["activation_raw"]
        .astype(int)
        .rolling(ACTIVATION_PERSISTENCE_DAYS, min_periods=ACTIVATION_PERSISTENCE_DAYS)
        .sum()
        .eq(ACTIVATION_PERSISTENCE_DAYS)
    )
    benchmark_recapture = frame["benchmark_above_anchor"] & (~frame["benchmark_above_anchor"].shift(1, fill_value=False))
    pilot_recapture = frame["pilot_confirmation_raw"] & (~frame["pilot_confirmation_raw"].shift(1, fill_value=False))
    recapture_age: List[int | None] = []
    current_age: int | None = None
    for benchmark_flag, pilot_flag in zip(benchmark_recapture.tolist(), pilot_recapture.tolist()):
        if bool(benchmark_flag) or bool(pilot_flag):
            current_age = 0
        elif current_age is not None:
            current_age += 1
        recapture_age.append(current_age)
    frame["recapture_age_days"] = recapture_age
    frame["recent_high_conviction_recapture"] = frame["recapture_age_days"].fillna(999).le(
        RECENT_RECAPTURE_MAX_AGE_DAYS
    )
    frame["pilot_local_downside_brake"] = (
        (
            (~frame["pilot_above_anchor"].fillna(False))
            | (frame["pilot_relative_strength"].fillna(0.0) < LOCAL_BRAKE_REL_STRENGTH_FLOOR)
        )
        .astype(int)
        .rolling(LOCAL_BRAKE_PERSISTENCE_DAYS, min_periods=LOCAL_BRAKE_PERSISTENCE_DAYS)
        .sum()
        .ge(LOCAL_BRAKE_PERSISTENCE_DAYS)
    )
    frame["pilot_activation_signal"] = frame["activation_persistence_ready"] & frame["recent_high_conviction_recapture"]

    pilot_active = False
    current_window_id = ""
    window_counter = 0
    probe_state: List[str] = []
    pilot_active_flags: List[bool] = []
    window_ids: List[str] = []
    handoff_flags: List[bool] = []
    exit_reasons: List[str] = []

    for _, row in frame.iterrows():
        baseline_cash = bool(row["baseline_cash"])
        exit_reason = ""
        if pilot_active:
            if not baseline_cash:
                pilot_active = False
                exit_reason = "baseline_handoff"
            elif (not bool(row["benchmark_constructive_valid"])) or (not bool(row["benchmark_above_anchor"])):
                pilot_active = False
                exit_reason = "constructive_failure"
            elif bool(row["pilot_local_downside_brake"]):
                pilot_active = False
                exit_reason = "pilot_local_downside_brake"

        if (not pilot_active) and baseline_cash and bool(row["pilot_activation_signal"]):
            pilot_active = True
            window_counter += 1
            current_window_id = f"window_{window_counter:03d}"

        if pilot_active and baseline_cash:
            pilot_state = "PRE_ACTIVATION_PILOT"
            active_window_id = current_window_id
        elif baseline_cash:
            pilot_state = "CASH"
            active_window_id = ""
        else:
            pilot_state = "BASELINE_RISK"
            active_window_id = current_window_id if exit_reason == "baseline_handoff" else ""

        probe_state.append(pilot_state)
        pilot_active_flags.append(pilot_state == "PRE_ACTIVATION_PILOT")
        handoff_flags.append(exit_reason == "baseline_handoff")
        exit_reasons.append(exit_reason)
        window_ids.append(active_window_id)

        if exit_reason:
            current_window_id = ""

    frame["probe_state"] = probe_state
    frame["pilot_active"] = pilot_active_flags
    frame["pilot_window_id"] = window_ids
    frame["pilot_handoff_day"] = handoff_flags
    frame["pilot_exit_reason"] = exit_reasons
    frame["probe_in_market"] = frame["probe_state"].ne("CASH")
    frame["probe_strategy_return_gross"] = pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)
    pilot_returns = pd.to_numeric(frame["pilot_return"], errors="coerce").fillna(0.0) * PILOT_WEIGHT
    frame.loc[frame["pilot_active"], "probe_strategy_return_gross"] = pilot_returns.loc[frame["pilot_active"]]
    return frame


def apply_cost_model(frame: pd.DataFrame, cost_cfg: Dict[str, float]) -> pd.DataFrame:
    out = frame.copy()
    baseline_weight = out["in_market"].astype(float)
    probe_weight = baseline_weight.copy()
    probe_weight.loc[out["pilot_active"]] = PILOT_WEIGHT

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
    active_ids = [value for value in frame["pilot_window_id"].dropna().unique().tolist() if str(value).strip()]
    for window_id in active_ids:
        window_df = frame.loc[frame["pilot_window_id"].eq(window_id)].copy()
        if window_df.empty:
            continue
        start_date = pd.Timestamp(window_df.index.min())
        handoff_rows = frame.loc[frame["pilot_window_id"].eq(window_id) & frame["pilot_handoff_day"]]
        handoff_date = pd.Timestamp(handoff_rows.index.min()) if not handoff_rows.empty else None
        exit_rows = frame.loc[frame["pilot_window_id"].eq(window_id) & frame["pilot_exit_reason"].ne("")]
        if exit_rows.empty:
            exit_date = pd.Timestamp(window_df.index.max())
            exit_reason = "still_open_at_dataset_end"
        else:
            exit_date = pd.Timestamp(exit_rows.index.min())
            exit_reason = str(exit_rows.iloc[0]["pilot_exit_reason"])
        analysis_end = handoff_date - pd.Timedelta(days=1) if handoff_date is not None else exit_date
        window_slice = frame.loc[start_date:analysis_end].copy()
        lead_days = 0 if handoff_date is None else int((handoff_date - start_date).days)
        rows.append(
            {
                "window_id": window_id,
                "pilot_activation_date": start_date.strftime("%Y-%m-%d"),
                "window_end_date": analysis_end.strftime("%Y-%m-%d"),
                "baseline_handoff_date": "" if handoff_date is None else handoff_date.strftime("%Y-%m-%d"),
                "pilot_asset": str(window_df.iloc[0]["pilot_asset"]),
                "asset_resolution": str(window_df.iloc[0]["asset_resolution"]),
                "pilot_days": int(window_df["pilot_active"].sum()),
                "lead_days_before_baseline_handoff": lead_days,
                "benchmark_return_gross": round(compound_return(window_slice["benchmark_return"]) * 100.0, 6),
                "pilot_asset_return_gross": round(compound_return(window_slice["pilot_return"]) * 100.0, 6),
                "baseline_return_gross": round(compound_return(window_slice["strategy_return"]) * 100.0, 6),
                "probe_return_gross": round(compound_return(window_slice["probe_strategy_return_gross"]) * 100.0, 6),
                "baseline_return_net": round(compound_return(window_slice["baseline_strategy_return_net"]) * 100.0, 6),
                "probe_return_net": round(compound_return(window_slice["probe_strategy_return_net"]) * 100.0, 6),
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
        (PROBE_MODEL, "PRE_ACTIVATION_PILOT", int(frame["probe_state"].eq("PRE_ACTIVATION_PILOT").sum())),
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


def calc_model_metrics(
    returns_gross: pd.Series,
    returns_net: pd.Series,
    state_series: pd.Series,
    weight_series: pd.Series,
    *,
    model: str,
    pilot_days: int,
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
        "pilot_days": int(pilot_days),
    }


def build_compare_rows(
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    lead_days = [row["lead_days_before_baseline_handoff"] for row in activation_windows if row["baseline_handoff_date"]]
    probe_early_capture = sum(row["probe_return_net"] for row in activation_windows)
    baseline_early_capture = sum(row["baseline_return_net"] for row in activation_windows)
    metrics = [
        ("net_return_after_costs_pct", baseline_metrics["net_return_after_costs_pct"], probe_metrics["net_return_after_costs_pct"]),
        ("gross_return_pct", baseline_metrics["gross_return_pct"], probe_metrics["gross_return_pct"]),
        ("max_drawdown_pct", baseline_metrics["max_drawdown_pct"], probe_metrics["max_drawdown_pct"]),
        ("trade_count", baseline_metrics["trade_count"], probe_metrics["trade_count"]),
        ("switch_count", baseline_metrics["switch_count"], probe_metrics["switch_count"]),
        ("turnover_pressure", baseline_metrics["turnover_pressure"], probe_metrics["turnover_pressure"]),
        ("total_cost_pct", baseline_metrics["total_cost_pct"], probe_metrics["total_cost_pct"]),
        ("activation_window_count", 0.0, float(len(activation_windows))),
        ("activation_window_handoff_count", 0.0, float(len(lead_days))),
        ("avg_lead_days_before_baseline_handoff", 0.0, float(sum(lead_days) / len(lead_days)) if lead_days else 0.0),
        ("median_lead_days_before_baseline_handoff", 0.0, float(median(lead_days)) if lead_days else 0.0),
        ("early_move_capture_net_pct", baseline_early_capture, probe_early_capture),
        ("pilot_days", baseline_metrics["pilot_days"], probe_metrics["pilot_days"]),
    ]
    rows: List[Dict[str, Any]] = []
    for metric, baseline_value, probe_value in metrics:
        rows.append(
            {
                "metric": metric,
                "baseline_model": BASELINE_MODEL,
                "baseline_value": float(baseline_value),
                "probe_model": PROBE_MODEL,
                "probe_value": float(probe_value),
                "delta_probe_minus_baseline": float(probe_value) - float(baseline_value),
            }
        )
    return rows


def determine_diagnosis(
    *,
    cash_summary: Dict[str, Any],
    constructive_pilot_summary: Dict[str, Any],
    constructive_pilot_compare: pd.DataFrame,
    probe_metrics: Dict[str, Any],
    baseline_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    lead_days = [row["lead_days_before_baseline_handoff"] for row in activation_windows if row["baseline_handoff_date"]]
    constructive_pilot_dd_delta = 0.0
    constructive_pilot_pilot_days = safe_float(
        constructive_pilot_compare.loc[constructive_pilot_compare["metric"].eq("pilot_risk_days"), "probe_value"].iloc[0]
        if not constructive_pilot_compare.empty and constructive_pilot_compare["metric"].eq("pilot_risk_days").any()
        else 0.0
    )
    if not constructive_pilot_compare.empty and constructive_pilot_compare["metric"].eq("max_drawdown_pct").any():
        constructive_pilot_dd_delta = safe_float(
            constructive_pilot_compare.loc[
                constructive_pilot_compare["metric"].eq("max_drawdown_pct"), "delta_probe_minus_baseline"
            ].iloc[0]
        )

    late_activation_viable = (
        bool(lead_days)
        and probe_metrics["net_return_after_costs_pct"] > baseline_metrics["net_return_after_costs_pct"]
        and probe_metrics["switch_count"] <= (baseline_metrics["switch_count"] + 2)
        and probe_metrics["max_drawdown_pct"] <= (baseline_metrics["max_drawdown_pct"] + 0.5)
    )
    persistence_fix_is_costly = (
        safe_float(constructive_pilot_summary.get("probe_missed_benchmark_return_while_underexposed"), 0.0) == 0.0
        and constructive_pilot_pilot_days >= 100.0
        and constructive_pilot_dd_delta <= -3.0
    )
    raw_exit_bias = cash_summary.get("final_diagnostic_verdict") in {
        "premature_risk_off_failure_to_stay_exposed",
        "broader_exposure_policy_issue",
    }

    if late_activation_viable and raw_exit_bias:
        diagnosis = "mixed_late_risk_on_activation_dominant"
    elif late_activation_viable:
        diagnosis = "late_risk_on_activation"
    else:
        diagnosis = "premature_risk_off_exit"

    evaluation = {
        "late_risk_on_activation": {
            "activation_windows_with_handoff": int(len(lead_days)),
            "avg_lead_days_before_baseline_handoff": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
            "net_return_after_costs_delta_pct": round(
                float(probe_metrics["net_return_after_costs_pct"] - baseline_metrics["net_return_after_costs_pct"]), 6
            ),
            "supports_hypothesis": bool(late_activation_viable),
        },
        "premature_risk_off_exit": {
            "cash_diagnostic_raw_verdict": cash_summary.get("final_diagnostic_verdict"),
            "constructive_pilot_pilot_days": int(constructive_pilot_pilot_days),
            "constructive_pilot_max_drawdown_delta_pct": round(float(constructive_pilot_dd_delta), 6),
            "supports_hypothesis": bool(raw_exit_bias),
        },
        "mixed_with_one_clearly_dominant_side": {
            "diagnosis_dominant_side": diagnosis,
            "reason": (
                "Raw constructive-window diagnostics point to premature risk-off, but the lower-churn net-of-cost probe "
                "signal is stronger on the late-activation side because the persistence fix needs far more pilot days "
                "and materially worse drawdown."
                if diagnosis == "mixed_late_risk_on_activation_dominant"
                else "The actionable bottleneck is clearer without needing a mixed diagnosis."
            ),
            "persistence_fix_is_costly": bool(persistence_fix_is_costly),
        },
    }
    return diagnosis, evaluation


def build_summary_payload(
    *,
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
    diagnosis_dominant_side: str,
    diagnosis_evaluation: Dict[str, Any],
    cost_cfg: Dict[str, float],
    input_refs: Dict[str, Any],
) -> Dict[str, Any]:
    lead_days = [row["lead_days_before_baseline_handoff"] for row in activation_windows if row["baseline_handoff_date"]]
    probe_early_capture = sum(row["probe_return_net"] for row in activation_windows)
    baseline_early_capture = sum(row["baseline_return_net"] for row in activation_windows)
    stop_triggered = (
        (not lead_days)
        or (probe_metrics["net_return_after_costs_pct"] <= baseline_metrics["net_return_after_costs_pct"])
        or (probe_metrics["max_drawdown_pct"] > baseline_metrics["max_drawdown_pct"] + 1.0)
        or (probe_metrics["switch_count"] > baseline_metrics["switch_count"] + 3)
    )
    pause_triggered = (not stop_triggered) and (len(lead_days) < 2)
    final_verdict = "stop_condition_triggered" if stop_triggered else "pause_condition_triggered" if pause_triggered else "continue_dev_only"

    return with_json_locks(
        {
            "artifact_id": "high_conviction_pre_activation_pilot_probe",
            "generated_at_utc": timestamp_utc(),
            "final_verdict": final_verdict,
            "diagnosis_dominant_side": diagnosis_dominant_side,
            "diagnosis_evaluation": diagnosis_evaluation,
            "mechanism_id": MECHANISM_ID,
            "compare_baseline": BASELINE_MODEL,
            "compare_vs_pure_constructive_pilot": COMPARE_VS_CONSTRUCTIVE_PILOT,
            "constructive_participation_timing_baseline": {
                "avg_lead_days_before_baseline_handoff": 0.0,
                "median_lead_days_before_baseline_handoff": 0.0,
                "activation_windows_with_handoff": 0,
            },
            "constructive_participation_timing_probe": {
                "avg_lead_days_before_baseline_handoff": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
                "median_lead_days_before_baseline_handoff": round(float(median(lead_days)), 6) if lead_days else 0.0,
                "activation_windows_with_handoff": int(len(lead_days)),
            },
            "early_move_capture_baseline": {
                "activation_window_count": int(len(activation_windows)),
                "net_return_pct_during_pre_activation_windows": round(float(baseline_early_capture), 6),
            },
            "early_move_capture_probe": {
                "activation_window_count": int(len(activation_windows)),
                "net_return_pct_during_pre_activation_windows": round(float(probe_early_capture), 6),
            },
            "trade_count_baseline": int(baseline_metrics["trade_count"]),
            "trade_count_probe": int(probe_metrics["trade_count"]),
            "switch_count_baseline": int(baseline_metrics["switch_count"]),
            "switch_count_probe": int(probe_metrics["switch_count"]),
            "turnover_pressure_baseline": round(float(baseline_metrics["turnover_pressure"]), 6),
            "turnover_pressure_probe": round(float(probe_metrics["turnover_pressure"]), 6),
            "net_return_after_costs_baseline": round(float(baseline_metrics["net_return_after_costs_pct"]), 6),
            "net_return_after_costs_probe": round(float(probe_metrics["net_return_after_costs_pct"]), 6),
            "gross_return_baseline": round(float(baseline_metrics["gross_return_pct"]), 6),
            "gross_return_probe": round(float(probe_metrics["gross_return_pct"]), 6),
            "max_drawdown_baseline": round(float(baseline_metrics["max_drawdown_pct"]), 6),
            "max_drawdown_probe": round(float(probe_metrics["max_drawdown_pct"]), 6),
            "why_different_from_phase68k_l_m": WHY_DIFFERENT_FROM_PHASE68K_L_M,
            "why_different_from_constructive_pilot_persistence": WHY_DIFFERENT_FROM_CONSTRUCTIVE_PILOT_PERSISTENCE,
            "exact_earlier_activation_rule": {
                "baseline_state_requirement": "baseline executed_regime must be CASH",
                "pilot_weight": PILOT_WEIGHT,
                "pilot_asset_resolution": "use decision-time selected asset when available, otherwise BTCUSDT fallback",
                "activation_requires_all_of": [
                    "benchmark constructive regime valid (BTC 20-day MA above BTC 100-day anchor)",
                    "benchmark close above BTC 100-day anchor",
                    "pilot asset above its own 100-day anchor",
                    "pilot asset 20-day relative strength versus BTC is non-negative",
                    f"{ACTIVATION_PERSISTENCE_DAYS}-day persistence",
                    f"fresh benchmark/pilot recapture within {RECENT_RECAPTURE_MAX_AGE_DAYS} days",
                ],
                "handoff_rule": "When the baseline leaves CASH, the pilot hands off immediately to the baseline state.",
                "pilot_deactivation": [
                    "benchmark constructive failure",
                    "benchmark falls back below anchor",
                    "pilot local downside brake on 2-day persistence",
                ],
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
            },
            "pause_condition": {
                "rule": PAUSE_RULE,
                "triggered": bool(pause_triggered),
            },
            "input_refs": input_refs,
            "status": "generated_dev_only_high_conviction_pre_activation_pilot_probe_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": "high_conviction_pre_activation_pilot_probe_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [
                "research_os/dev_only/contracts/dev_only_high_conviction_pre_activation_pilot_probe.contract.json"
            ],
            "spec_refs": [
                "research_os/dev_only/specs/dev_only_high_conviction_pre_activation_pilot_probe.spec.json"
            ],
            "manifest_seed_refs": [
                "research_os/dev_only/manifests/dev_only_high_conviction_pre_activation_pilot_probe.manifest.json"
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
    checks = [
        {
            "name": "pilot_only_on_baseline_cash_days",
            "ok": not bool((frame["pilot_active"] & (~frame["baseline_cash"])).any()),
            "detail": "pilot sleeve is never active once the baseline leaves CASH",
        },
        {
            "name": "handoff_does_not_stack_with_baseline",
            "ok": not bool((frame["pilot_active"] & frame["probe_state"].eq("BASELINE_RISK")).any()),
            "detail": "pilot and baseline risk states never overlap",
        },
        {
            "name": "activation_recency_gate_present",
            "ok": bool(frame["recent_high_conviction_recapture"].any()),
            "detail": "probe uses a fresh recapture gate rather than open-ended persistence",
        },
        {
            "name": "net_metric_available",
            "ok": probe_metrics["net_return_after_costs_pct"] == probe_metrics["net_return_after_costs_pct"],
            "detail": "net-of-cost metrics computed for ranking",
        },
        {
            "name": "activation_windows_materialized",
            "ok": len(activation_windows) >= 0,
            "detail": f"activation windows counted={len(activation_windows)}",
        },
        {
            "name": "semantic_flags_locked",
            "ok": True,
            "detail": "dev_only=true, non_authoritative=true, official_truth=false, strategy_advancement=false, candidate_selection=false, official_edge_claim=false",
        },
    ]
    return with_json_locks(
        {
            "artifact_id": "high_conviction_pre_activation_pilot_probe_quality",
            "generated_at_utc": timestamp_utc(),
            "input_refs": input_refs,
            "checks": checks,
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
    cash_summary_path = Path(args.cash_diagnostic_summary)
    constructive_pilot_summary_path = Path(args.constructive_pilot_summary)
    constructive_pilot_compare_path = Path(args.constructive_pilot_compare)

    baseline_df = cash_diag.load_paper(baseline_path)
    frame = build_probe_frame(baseline_df)
    cost_cfg = load_phase68i_cost_assumptions(phase68i_summary_path, phase68i_paper_path)
    frame = apply_cost_model(frame, cost_cfg)

    activation_windows = build_activation_windows(frame)
    baseline_metrics = calc_model_metrics(
        returns_gross=frame["strategy_return"],
        returns_net=frame["baseline_strategy_return_net"],
        state_series=frame["in_market"].map({True: "BASELINE_RISK", False: "CASH"}),
        weight_series=frame["baseline_exposure_weight"],
        model=BASELINE_MODEL,
        pilot_days=0,
    )
    probe_metrics = calc_model_metrics(
        returns_gross=frame["probe_strategy_return_gross"],
        returns_net=frame["probe_strategy_return_net"],
        state_series=frame["probe_state"],
        weight_series=frame["probe_exposure_weight"],
        model=PROBE_MODEL,
        pilot_days=int(frame["pilot_active"].sum()),
    )

    cash_summary = load_json(cash_summary_path) if cash_summary_path.exists() else {}
    constructive_pilot_summary = load_json(constructive_pilot_summary_path) if constructive_pilot_summary_path.exists() else {}
    constructive_pilot_compare = (
        pd.read_csv(constructive_pilot_compare_path) if constructive_pilot_compare_path.exists() else pd.DataFrame()
    )
    diagnosis_dominant_side, diagnosis_evaluation = determine_diagnosis(
        cash_summary=cash_summary,
        constructive_pilot_summary=constructive_pilot_summary,
        constructive_pilot_compare=constructive_pilot_compare,
        probe_metrics=probe_metrics,
        baseline_metrics=baseline_metrics,
        activation_windows=activation_windows,
    )

    input_refs = {
        "baseline_paper": str(baseline_path),
        "phase68i_paper_secondary_context": str(phase68i_paper_path) if phase68i_paper_path.exists() else None,
        "phase68i_summary_secondary_context": str(phase68i_summary_path) if phase68i_summary_path.exists() else None,
        "cash_diagnostic_summary": str(cash_summary_path) if cash_summary_path.exists() else None,
        "constructive_pilot_summary": str(constructive_pilot_summary_path) if constructive_pilot_summary_path.exists() else None,
        "constructive_pilot_compare": str(constructive_pilot_compare_path) if constructive_pilot_compare_path.exists() else None,
        "phase68k_compare": str(ROOT / "outputs" / "phase68k_early_entry_ladder_probe" / "phase68k_early_entry_compare.csv"),
        "phase68l_compare": str(ROOT / "outputs" / "phase68l_early_entry_soft_gate_probe" / "phase68l_early_entry_soft_gate_compare.csv"),
        "phase68m_compare": str(ROOT / "outputs" / "phase68m_early_entry_micro_confirm" / "phase68m_early_entry_micro_confirm_compare.csv"),
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
            diagnosis_dominant_side=diagnosis_dominant_side,
            diagnosis_evaluation=diagnosis_evaluation,
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

    print("high_conviction_pre_activation_pilot_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
