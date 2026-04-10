from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import pandas as pd

import dev_only_cash_overstay_diagnostic as cash_diag
import dev_only_high_conviction_pre_activation_pilot_probe as prev_probe
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_rearmed_high_conviction_pre_activation_pilot_probe"
)

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "rearmed_high_conviction_pre_activation_pilot_probe"
MECHANISM_ID = "rearmed_high_conviction_pre_activation_pilot"
COMPARE_VS_CONSTRUCTIVE_PILOT = "dev_only_constructive_pilot_exposure_probe"
COMPARE_VS_PREVIOUS = "dev_only_high_conviction_pre_activation_pilot_probe"

BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
PHASE68I_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
PHASE68I_SUMMARY_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_summary.csv"
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
PREVIOUS_PROBE_SUMMARY_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_high_conviction_pre_activation_pilot_probe"
    / "high_conviction_pre_activation_pilot_probe.summary.json"
)
PREVIOUS_PROBE_COST_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_high_conviction_pre_activation_pilot_probe"
    / "high_conviction_pre_activation_pilot_probe.cost_metrics.csv"
)
PREVIOUS_PROBE_COMPARE_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_high_conviction_pre_activation_pilot_probe"
    / "high_conviction_pre_activation_pilot_probe.compare.csv"
)

PILOT_WEIGHT = prev_probe.PILOT_WEIGHT
REARM_MIN_DAYS_OUT = 5
MAX_REARMS_PER_REGIME = 1

JSON_LOCKS = {
    "analysis_mode": "rearmed_high_conviction_pre_activation_pilot_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}
WHY_IN_FAMILY_NOT_DUPLICATE = (
    "This confirmatory pass keeps the same earlier high-conviction pre-activation stack and adds only one "
    "deterministic second-chance re-arm after a clean reset. It is not persistence, not broad gate softening, and "
    "not an exit-loosening pass."
)
STOP_RULE = (
    "if confirmatory pass fails to reproduce meaningful earlier activation or if benefit survives only by adding churn / "
    "switching / DD cost or if previous success appears isolated and non-generalizable"
)
PAUSE_RULE = "if result remains promising but still too narrow for stronger language"

WINDOW_COMPARE_COLUMNS = [
    "window_id",
    "constructive_regime_id",
    "activation_kind",
    "pilot_activation_date",
    "window_end_date",
    "exit_date",
    "baseline_handoff_date",
    "pilot_asset",
    "asset_resolution",
    "days_out_of_pilot_before_activation",
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
    parser = argparse.ArgumentParser(description="Dev-only rearmed high-conviction pre-activation pilot probe")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--phase68i-paper", type=str, default=str(PHASE68I_PAPER_PATH))
    parser.add_argument("--phase68i-summary", type=str, default=str(PHASE68I_SUMMARY_PATH))
    parser.add_argument("--constructive-pilot-summary", type=str, default=str(CONSTRUCTIVE_PILOT_SUMMARY_PATH))
    parser.add_argument("--constructive-pilot-compare", type=str, default=str(CONSTRUCTIVE_PILOT_COMPARE_PATH))
    parser.add_argument("--previous-probe-summary", type=str, default=str(PREVIOUS_PROBE_SUMMARY_PATH))
    parser.add_argument("--previous-probe-cost", type=str, default=str(PREVIOUS_PROBE_COST_PATH))
    parser.add_argument("--previous-probe-compare", type=str, default=str(PREVIOUS_PROBE_COMPARE_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    return {
        "summary_json": OUTPUT_ROOT / "rearmed_high_conviction_pre_activation_pilot_probe.summary.json",
        "window_compare_csv": OUTPUT_ROOT / "rearmed_high_conviction_pre_activation_pilot_probe.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / "rearmed_high_conviction_pre_activation_pilot_probe.state_time.csv",
        "compare_csv": OUTPUT_ROOT / "rearmed_high_conviction_pre_activation_pilot_probe.compare.csv",
        "cost_metrics_csv": OUTPUT_ROOT / "rearmed_high_conviction_pre_activation_pilot_probe.cost_metrics.csv",
        "manifest_json": OUTPUT_ROOT / "rearmed_high_conviction_pre_activation_pilot_probe.manifest.json",
        "quality_json": OUTPUT_ROOT / "rearmed_high_conviction_pre_activation_pilot_probe.quality.json",
    }


def load_json(path: Path) -> Dict[str, Any]:
    return prev_probe.load_json(path) if path.exists() else {}


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def safe_float(value: Any, default: float = 0.0) -> float:
    return prev_probe.safe_float(value, default)


def safe_int(value: Any, default: int = 0) -> int:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return int(default if pd.isna(numeric) else int(numeric))


def load_metrics_row(path: Path, model: str) -> Dict[str, Any]:
    df = load_csv(path)
    if df.empty or "model" not in df.columns:
        return {}
    matches = df.loc[df["model"].astype(str).eq(model)]
    if matches.empty:
        return {}
    return matches.iloc[0].to_dict()


def tag_constructive_regimes(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["constructive_regime_id"] = ""
    for idx, (start_date, end_date) in enumerate(cash_diag.build_constructive_windows(out), start=1):
        out.loc[start_date:end_date, "constructive_regime_id"] = f"constructive_regime_{idx:03d}"
    return out


def build_probe_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    frame = tag_constructive_regimes(prev_probe.build_probe_frame(baseline_df).copy())

    regime_tracker: Dict[str, Dict[str, Any]] = {}
    pilot_active = False
    current_window_id = ""
    current_activation_kind = ""
    current_activation_regime_id = ""
    window_counter = 0

    probe_state: List[str] = []
    pilot_active_flags: List[bool] = []
    pilot_window_ids: List[str] = []
    handoff_flags: List[bool] = []
    exit_reasons: List[str] = []
    activation_kinds: List[str] = []
    rearmed_flags: List[bool] = []
    activation_gap_days: List[float | None] = []
    rearm_reset_ready_flags: List[bool] = []

    def regime_meta(regime_id: str) -> Dict[str, Any]:
        return regime_tracker.setdefault(
            regime_id,
            {
                "initial_activation_used": False,
                "rearm_used": False,
                "activation_count": 0,
                "last_exit_date": None,
                "rearm_candidate_open": False,
                "reset_observed_after_exit": False,
            },
        )

    def open_rearm_candidate(meta: Dict[str, Any], date_value: pd.Timestamp) -> None:
        meta["last_exit_date"] = pd.Timestamp(date_value)
        meta["rearm_candidate_open"] = not bool(meta["rearm_used"])
        meta["reset_observed_after_exit"] = False

    for date_value, row in frame.iterrows():
        regime_id = str(row.get("constructive_regime_id", "") or "")
        if regime_id:
            meta = regime_meta(regime_id)
            if (not pilot_active) and meta["rearm_candidate_open"] and meta["last_exit_date"] is not None:
                if pd.Timestamp(date_value) > pd.Timestamp(meta["last_exit_date"]) and (not bool(row["activation_raw"])):
                    meta["reset_observed_after_exit"] = True

        baseline_cash = bool(row["baseline_cash"])
        exit_reason = ""
        row_window_id = current_window_id
        row_activation_kind = current_activation_kind
        row_gap_days: float | None = None

        if pilot_active:
            active_meta = regime_tracker.get(current_activation_regime_id)
            if not baseline_cash:
                pilot_active = False
                exit_reason = "baseline_handoff"
                if active_meta is not None:
                    active_meta["rearm_candidate_open"] = False
            elif not regime_id:
                pilot_active = False
                exit_reason = "constructive_failure"
                if active_meta is not None:
                    open_rearm_candidate(active_meta, pd.Timestamp(date_value))
            elif (not bool(row["benchmark_constructive_valid"])) or (not bool(row["benchmark_above_anchor"])):
                pilot_active = False
                exit_reason = "constructive_failure"
                if active_meta is not None:
                    open_rearm_candidate(active_meta, pd.Timestamp(date_value))
            elif bool(row["pilot_local_downside_brake"]):
                pilot_active = False
                exit_reason = "pilot_local_downside_brake"
                if active_meta is not None:
                    open_rearm_candidate(active_meta, pd.Timestamp(date_value))

        rearm_reset_ready = False
        if (not pilot_active) and baseline_cash and regime_id:
            meta = regime_meta(regime_id)
            days_out = None
            if meta["last_exit_date"] is not None:
                days_out = int((pd.Timestamp(date_value) - pd.Timestamp(meta["last_exit_date"])).days)
            rearm_reset_ready = (
                bool(meta["initial_activation_used"])
                and bool(meta["rearm_candidate_open"])
                and (not bool(meta["rearm_used"]))
                and bool(meta["reset_observed_after_exit"])
                and (days_out is not None)
                and (days_out >= REARM_MIN_DAYS_OUT)
            )
            can_activate_initial = (not bool(meta["initial_activation_used"])) and bool(row["pilot_activation_signal"])
            can_activate_rearm = bool(row["pilot_activation_signal"]) and rearm_reset_ready
            if can_activate_initial or can_activate_rearm:
                pilot_active = True
                window_counter += 1
                current_window_id = f"window_{window_counter:03d}"
                current_activation_kind = "REARM" if can_activate_rearm else "INITIAL"
                current_activation_regime_id = regime_id
                row_window_id = current_window_id
                row_activation_kind = current_activation_kind
                row_gap_days = float(days_out) if can_activate_rearm and days_out is not None else 0.0
                meta["initial_activation_used"] = True
                meta["activation_count"] = safe_int(meta.get("activation_count"), 0) + 1
                if can_activate_rearm:
                    meta["rearm_used"] = True
                    meta["rearm_candidate_open"] = False
                    meta["reset_observed_after_exit"] = False

        if pilot_active and baseline_cash:
            state = "PRE_ACTIVATION_PILOT"
            row_window_id = current_window_id
            row_activation_kind = current_activation_kind
        elif baseline_cash:
            state = "CASH"
        else:
            state = "BASELINE_RISK"

        if exit_reason:
            row_window_id = current_window_id
            row_activation_kind = current_activation_kind

        probe_state.append(state)
        pilot_active_flags.append(state == "PRE_ACTIVATION_PILOT")
        pilot_window_ids.append(row_window_id)
        handoff_flags.append(exit_reason == "baseline_handoff")
        exit_reasons.append(exit_reason)
        activation_kinds.append(row_activation_kind)
        rearmed_flags.append(bool(row_window_id) and row_activation_kind == "REARM")
        activation_gap_days.append(row_gap_days)
        rearm_reset_ready_flags.append(bool(rearm_reset_ready))

        if exit_reason:
            current_window_id = ""
            current_activation_kind = ""
            current_activation_regime_id = ""

    frame["probe_state"] = probe_state
    frame["pilot_active"] = pilot_active_flags
    frame["pilot_window_id"] = pilot_window_ids
    frame["pilot_handoff_day"] = handoff_flags
    frame["pilot_exit_reason"] = exit_reasons
    frame["pilot_activation_kind"] = activation_kinds
    frame["rearmed_activation"] = rearmed_flags
    frame["days_out_of_pilot_before_activation"] = activation_gap_days
    frame["rearm_reset_ready"] = rearm_reset_ready_flags
    frame["probe_in_market"] = frame["probe_state"].ne("CASH")
    frame["probe_strategy_return_gross"] = pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)
    pilot_returns = pd.to_numeric(frame["pilot_return"], errors="coerce").fillna(0.0) * PILOT_WEIGHT
    frame.loc[frame["pilot_active"], "probe_strategy_return_gross"] = pilot_returns.loc[frame["pilot_active"]]
    return frame


def build_activation_windows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    active_ids = [value for value in frame["pilot_window_id"].dropna().unique().tolist() if str(value).strip()]
    for window_id in active_ids:
        window_df = frame.loc[frame["pilot_window_id"].eq(window_id)].copy()
        pilot_df = window_df.loc[window_df["pilot_active"]].copy()
        if pilot_df.empty:
            continue
        start_date = pd.Timestamp(pilot_df.index.min())
        last_pilot_date = pd.Timestamp(pilot_df.index.max())
        exit_rows = window_df.loc[window_df["pilot_exit_reason"].ne("")]
        exit_date = pd.Timestamp(exit_rows.index.min()) if not exit_rows.empty else last_pilot_date
        handoff_rows = window_df.loc[window_df["pilot_handoff_day"]]
        handoff_date = pd.Timestamp(handoff_rows.index.min()) if not handoff_rows.empty else None
        analysis_end = handoff_date - pd.Timedelta(days=1) if handoff_date is not None else last_pilot_date
        analysis_slice = frame.loc[start_date:analysis_end].copy()
        exit_reason = str(exit_rows.iloc[0]["pilot_exit_reason"]) if not exit_rows.empty else "still_open_at_dataset_end"
        lead_days = 0 if handoff_date is None else int((handoff_date - start_date).days)
        gap_series = pd.to_numeric(pilot_df["days_out_of_pilot_before_activation"], errors="coerce").dropna()
        rows.append(
            {
                "window_id": window_id,
                "constructive_regime_id": str(pilot_df.iloc[0]["constructive_regime_id"]),
                "activation_kind": str(pilot_df.iloc[0]["pilot_activation_kind"]),
                "pilot_activation_date": start_date.strftime("%Y-%m-%d"),
                "window_end_date": analysis_end.strftime("%Y-%m-%d"),
                "exit_date": exit_date.strftime("%Y-%m-%d"),
                "baseline_handoff_date": "" if handoff_date is None else handoff_date.strftime("%Y-%m-%d"),
                "pilot_asset": str(pilot_df.iloc[0]["pilot_asset"]),
                "asset_resolution": str(pilot_df.iloc[0]["asset_resolution"]),
                "days_out_of_pilot_before_activation": round(float(gap_series.iloc[0]), 6) if not gap_series.empty else 0.0,
                "pilot_days": int(pilot_df["pilot_active"].sum()),
                "lead_days_before_baseline_handoff": lead_days,
                "benchmark_return_gross": round(prev_probe.compound_return(analysis_slice["benchmark_return"]) * 100.0, 6),
                "pilot_asset_return_gross": round(prev_probe.compound_return(analysis_slice["pilot_return"]) * 100.0, 6),
                "baseline_return_gross": round(prev_probe.compound_return(analysis_slice["strategy_return"]) * 100.0, 6),
                "probe_return_gross": round(prev_probe.compound_return(analysis_slice["probe_strategy_return_gross"]) * 100.0, 6),
                "baseline_return_net": round(prev_probe.compound_return(analysis_slice["baseline_strategy_return_net"]) * 100.0, 6),
                "probe_return_net": round(prev_probe.compound_return(analysis_slice["probe_strategy_return_net"]) * 100.0, 6),
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


def build_compare_rows(
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    lead_days = [row["lead_days_before_baseline_handoff"] for row in activation_windows if row["baseline_handoff_date"]]
    probe_early_capture = sum(row["probe_return_net"] for row in activation_windows)
    baseline_early_capture = sum(row["baseline_return_net"] for row in activation_windows)
    rearm_count = sum(1 for row in activation_windows if row["activation_kind"] == "REARM")
    metrics = [
        ("net_return_after_costs_pct", baseline_metrics["net_return_after_costs_pct"], probe_metrics["net_return_after_costs_pct"]),
        ("gross_return_pct", baseline_metrics["gross_return_pct"], probe_metrics["gross_return_pct"]),
        ("max_drawdown_pct", baseline_metrics["max_drawdown_pct"], probe_metrics["max_drawdown_pct"]),
        ("trade_count", baseline_metrics["trade_count"], probe_metrics["trade_count"]),
        ("switch_count", baseline_metrics["switch_count"], probe_metrics["switch_count"]),
        ("turnover_pressure", baseline_metrics["turnover_pressure"], probe_metrics["turnover_pressure"]),
        ("total_cost_pct", baseline_metrics["total_cost_pct"], probe_metrics["total_cost_pct"]),
        ("activation_window_count", 0.0, float(len(activation_windows))),
        ("rearm_activation_count", 0.0, float(rearm_count)),
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


def compute_summary_metrics(
    activation_windows: List[Dict[str, Any]],
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    lead_days = [row["lead_days_before_baseline_handoff"] for row in activation_windows if row["baseline_handoff_date"]]
    total_net_capture = sum(row["probe_return_net"] for row in activation_windows)
    baseline_net_capture = sum(row["baseline_return_net"] for row in activation_windows)
    rearm_windows = [row for row in activation_windows if row["activation_kind"] == "REARM"]
    rearm_net_capture = sum(row["probe_return_net"] - row["baseline_return_net"] for row in rearm_windows)
    return {
        "earlier_activation_windows_count": int(len(activation_windows)),
        "rearm_activation_windows_count": int(len(rearm_windows)),
        "lead_days": lead_days,
        "net_early_move_capture_probe": round(float(total_net_capture), 6),
        "net_early_move_capture_baseline": round(float(baseline_net_capture), 6),
        "net_early_move_capture_delta": round(float(total_net_capture - baseline_net_capture), 6),
        "rearm_net_early_move_capture_delta": round(float(rearm_net_capture), 6),
        "trade_count_delta_vs_baseline": int(probe_metrics["trade_count"] - baseline_metrics["trade_count"]),
        "switch_count_delta_vs_baseline": int(probe_metrics["switch_count"] - baseline_metrics["switch_count"]),
    }


def determine_diagnosis_update(
    summary_metrics: Dict[str, Any],
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    previous_summary: Dict[str, Any],
) -> str:
    rearm_count = safe_int(summary_metrics.get("rearm_activation_windows_count"), 0)
    net_capture_delta = safe_float(summary_metrics.get("net_early_move_capture_delta"), 0.0)
    dd_ok = probe_metrics["max_drawdown_pct"] <= (baseline_metrics["max_drawdown_pct"] + 0.5)
    churn_ok = probe_metrics["switch_count"] <= (baseline_metrics["switch_count"] + 2)
    previous_windows = safe_int(
        previous_summary.get("constructive_participation_timing_probe", {}).get("activation_windows_with_handoff", 0), 0
    )
    if rearm_count > 0 and net_capture_delta > 0.0 and dd_ok and churn_ok:
        return "late_risk_on_activation_support_strengthened_but_still_narrow"
    if rearm_count > 0 and churn_ok and dd_ok:
        return "late_risk_on_activation_still_supported_but_rearm_capture_is_weak"
    if previous_windows >= 1:
        return "previous_late_risk_on_signal_not_generalized_by_clean_rearm"
    return "confirmatory_rearm_failed_no_generalization"


def build_summary_payload(
    *,
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
    diagnosis_update: str,
    constructive_pilot_summary: Dict[str, Any],
    previous_summary: Dict[str, Any],
    previous_metrics: Dict[str, Any],
    cost_cfg: Dict[str, float],
    input_refs: Dict[str, Any],
) -> Dict[str, Any]:
    summary_metrics = compute_summary_metrics(activation_windows, baseline_metrics, probe_metrics)
    lead_days = summary_metrics["lead_days"]
    rearm_count = safe_int(summary_metrics["rearm_activation_windows_count"], 0)
    net_capture_delta = safe_float(summary_metrics["net_early_move_capture_delta"], 0.0)
    previous_capture = safe_float(
        previous_summary.get("early_move_capture_probe", {}).get("net_return_pct_during_pre_activation_windows", 0.0),
        0.0,
    )
    dd_ok = probe_metrics["max_drawdown_pct"] <= (baseline_metrics["max_drawdown_pct"] + 0.5)
    churn_ok = probe_metrics["switch_count"] <= (baseline_metrics["switch_count"] + 2) and probe_metrics[
        "turnover_pressure"
    ] <= (baseline_metrics["turnover_pressure"] + 1.0)
    net_ok = probe_metrics["net_return_after_costs_pct"] > baseline_metrics["net_return_after_costs_pct"]
    late_risk_on_supported = rearm_count > 0 and net_capture_delta > 0.0 and churn_ok and dd_ok

    stop_triggered = (rearm_count == 0) or (not net_ok) or (not churn_ok) or (not dd_ok) or (net_capture_delta <= 0.0)
    pause_triggered = (not stop_triggered) and ((rearm_count < 2) or (net_capture_delta <= previous_capture))
    final_verdict = "stop_condition_triggered" if stop_triggered else "pause_condition_triggered" if pause_triggered else "continue_dev_only"

    return with_json_locks(
        {
            "artifact_id": "rearmed_high_conviction_pre_activation_pilot_probe",
            "generated_at_utc": timestamp_utc(),
            "final_verdict": final_verdict,
            "diagnosis_update": diagnosis_update,
            "mechanism_id": MECHANISM_ID,
            "compare_baseline": BASELINE_MODEL,
            "compare_vs_pure_constructive_pilot": COMPARE_VS_CONSTRUCTIVE_PILOT,
            "compare_vs_previous_pre_activation_probe": COMPARE_VS_PREVIOUS,
            "earlier_activation_windows_count": summary_metrics["earlier_activation_windows_count"],
            "lead_time_vs_baseline": {
                "activation_windows_with_handoff": int(len(lead_days)),
                "avg_lead_days": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
                "median_lead_days": round(float(median(lead_days)), 6) if lead_days else 0.0,
                "max_lead_days": int(max(lead_days)) if lead_days else 0,
            },
            "net_early_move_capture": {
                "baseline_total_pct": summary_metrics["net_early_move_capture_baseline"],
                "probe_total_pct": summary_metrics["net_early_move_capture_probe"],
                "delta_probe_minus_baseline_pct": summary_metrics["net_early_move_capture_delta"],
                "rearm_only_delta_probe_minus_baseline_pct": summary_metrics["rearm_net_early_move_capture_delta"],
            },
            "trade_count": {
                "baseline": int(baseline_metrics["trade_count"]),
                "previous_probe": safe_int(previous_metrics.get("trade_count"), 0),
                "probe": int(probe_metrics["trade_count"]),
                "delta_probe_minus_baseline": int(probe_metrics["trade_count"] - baseline_metrics["trade_count"]),
            },
            "switch_count": {
                "baseline": int(baseline_metrics["switch_count"]),
                "previous_probe": safe_int(previous_metrics.get("switch_count"), 0),
                "probe": int(probe_metrics["switch_count"]),
                "delta_probe_minus_baseline": int(probe_metrics["switch_count"] - baseline_metrics["switch_count"]),
            },
            "turnover_pressure": {
                "baseline": round(float(baseline_metrics["turnover_pressure"]), 6),
                "previous_probe": round(safe_float(previous_metrics.get("turnover_pressure"), 0.0), 6),
                "probe": round(float(probe_metrics["turnover_pressure"]), 6),
                "delta_probe_minus_baseline": round(
                    float(probe_metrics["turnover_pressure"] - baseline_metrics["turnover_pressure"]), 6
                ),
            },
            "max_drawdown": {
                "baseline_pct": round(float(baseline_metrics["max_drawdown_pct"]), 6),
                "previous_probe_pct": round(safe_float(previous_metrics.get("max_drawdown_pct"), 0.0), 6),
                "probe_pct": round(float(probe_metrics["max_drawdown_pct"]), 6),
                "delta_probe_minus_baseline_pct": round(
                    float(probe_metrics["max_drawdown_pct"] - baseline_metrics["max_drawdown_pct"]), 6
                ),
            },
            "gross_metrics_context": {
                "baseline_gross_return_pct": round(float(baseline_metrics["gross_return_pct"]), 6),
                "previous_probe_gross_return_pct": round(safe_float(previous_metrics.get("gross_return_pct"), 0.0), 6),
                "probe_gross_return_pct": round(float(probe_metrics["gross_return_pct"]), 6),
                "probe_minus_baseline_gross_return_pct": round(
                    float(probe_metrics["gross_return_pct"] - baseline_metrics["gross_return_pct"]), 6
                ),
            },
            "why_in_family_not_duplicate": WHY_IN_FAMILY_NOT_DUPLICATE,
            "exact_confirmatory_rule_implemented": {
                "base_stack_reused_unchanged": {
                    "baseline_state_requirement": "baseline executed_regime must be CASH",
                    "pilot_weight": PILOT_WEIGHT,
                    "pilot_asset_resolution": "use decision-time selected asset when available, otherwise BTCUSDT fallback",
                    "activation_requires_all_of": [
                        "BTC 20DMA > BTC 100DMA anchor",
                        "BTC close > BTC 100DMA anchor",
                        "pilot asset > own 100DMA anchor",
                        "pilot asset 20-day relative strength versus BTC >= 0",
                        "3-day persistence",
                        "fresh benchmark/pilot recapture within 7 days",
                    ],
                    "handoff_rule": "first day baseline leaves CASH",
                    "deactivation_rule": [
                        "constructive failure",
                        "2-day local downside brake",
                    ],
                },
                "confirmatory_addition_only": {
                    "allow_at_most_one_rearm_per_constructive_regime": True,
                    "rearm_requires_days_out_of_pilot_at_least": REARM_MIN_DAYS_OUT,
                    "rearm_requires_full_base_stack_reset_then_rehold": True,
                    "rearm_uses_same_weight_and_same_exit_discipline": True,
                    "no_multiple_rearms": True,
                },
            },
            "evaluation_answers": {
                "does_earlier_activation_happen_again_in_a_valid_way": {
                    "answer": bool(rearm_count > 0 and summary_metrics["rearm_net_early_move_capture_delta"] > 0.0),
                    "detail": {
                        "rearm_activation_windows_count": rearm_count,
                        "rearm_net_early_move_capture_delta_pct": summary_metrics["rearm_net_early_move_capture_delta"],
                    },
                },
                "does_net_early_move_capture_remain_positive": {
                    "answer": bool(net_capture_delta > 0.0),
                    "detail": summary_metrics["net_early_move_capture_delta"],
                },
                "does_low_churn_remain_intact": {
                    "answer": bool(churn_ok),
                    "detail": {
                        "trade_count_delta_vs_baseline": summary_metrics["trade_count_delta_vs_baseline"],
                        "switch_count_delta_vs_baseline": summary_metrics["switch_count_delta_vs_baseline"],
                        "turnover_pressure_baseline": round(float(baseline_metrics["turnover_pressure"]), 6),
                        "turnover_pressure_probe": round(float(probe_metrics["turnover_pressure"]), 6),
                    },
                },
                "does_dd_remain_disciplined": {
                    "answer": bool(dd_ok),
                    "detail": {
                        "baseline_max_drawdown_pct": round(float(baseline_metrics["max_drawdown_pct"]), 6),
                        "probe_max_drawdown_pct": round(float(probe_metrics["max_drawdown_pct"]), 6),
                    },
                },
                "does_result_still_support_late_risk_on_dominance_rather_than_persistence_logic": {
                    "answer": bool(late_risk_on_supported),
                    "detail": {
                        "constructive_pilot_probe_final_verdict": constructive_pilot_summary.get("final_verdict"),
                        "constructive_pilot_probe_missed_benchmark_while_underexposed": constructive_pilot_summary.get(
                            "probe_missed_benchmark_return_while_underexposed"
                        ),
                        "previous_probe_capture_pct": previous_capture,
                        "confirmatory_rearm_count": rearm_count,
                    },
                },
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
            "status": "generated_dev_only_rearmed_high_conviction_pre_activation_pilot_probe_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": "rearmed_high_conviction_pre_activation_pilot_probe_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [
                "research_os/dev_only/contracts/dev_only_rearmed_high_conviction_pre_activation_pilot_probe.contract.json"
            ],
            "spec_refs": [
                "research_os/dev_only/specs/dev_only_rearmed_high_conviction_pre_activation_pilot_probe.spec.json"
            ],
            "manifest_seed_refs": [
                "research_os/dev_only/manifests/dev_only_rearmed_high_conviction_pre_activation_pilot_probe.manifest.json"
            ],
            "status": "implementation_pack_ready",
        }
    )


def build_quality_payload(
    frame: pd.DataFrame,
    activation_windows: List[Dict[str, Any]],
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    input_refs: Dict[str, Any],
) -> Dict[str, Any]:
    per_regime_rearm_counts = (
        pd.DataFrame(activation_windows)
        .groupby("constructive_regime_id")["activation_kind"]
        .apply(lambda series: int(series.eq("REARM").sum()))
        if activation_windows
        else pd.Series(dtype="int64")
    )
    rearm_gap_ok = True
    if activation_windows:
        rearm_rows = pd.DataFrame(activation_windows)
        rearm_rows = rearm_rows.loc[rearm_rows["activation_kind"].eq("REARM")]
        if not rearm_rows.empty:
            rearm_gap_ok = bool(
                pd.to_numeric(rearm_rows["days_out_of_pilot_before_activation"], errors="coerce").ge(REARM_MIN_DAYS_OUT).all()
            )
    checks = [
        {
            "name": "pilot_only_on_baseline_cash_days",
            "ok": not bool((frame["pilot_active"] & (~frame["baseline_cash"])).any()),
            "detail": "pilot sleeve is never active once the baseline leaves CASH",
        },
        {
            "name": "no_more_than_one_rearm_per_constructive_regime",
            "ok": bool(per_regime_rearm_counts.le(MAX_REARMS_PER_REGIME).all()) if not per_regime_rearm_counts.empty else True,
            "detail": f"per_regime_rearm_counts={per_regime_rearm_counts.to_dict()}",
        },
        {
            "name": "rearm_gap_respected",
            "ok": bool(rearm_gap_ok),
            "detail": f"rearm requires at least {REARM_MIN_DAYS_OUT} calendar days out of pilot state",
        },
        {
            "name": "rearm_requires_reset_path",
            "ok": not bool(
                (
                    frame["rearmed_activation"]
                    & pd.to_numeric(frame["days_out_of_pilot_before_activation"], errors="coerce").lt(REARM_MIN_DAYS_OUT)
                ).any()
            ),
            "detail": "no rearmed activation occurs before the minimum reset gap",
        },
        {
            "name": "net_metric_available",
            "ok": probe_metrics["net_return_after_costs_pct"] == probe_metrics["net_return_after_costs_pct"],
            "detail": "net-of-cost metrics computed for ranking",
        },
        {
            "name": "semantic_flags_locked",
            "ok": True,
            "detail": "dev_only=true, non_authoritative=true, official_truth=false, strategy_advancement=false, candidate_selection=false, official_edge_claim=false",
        },
    ]
    return with_json_locks(
        {
            "artifact_id": "rearmed_high_conviction_pre_activation_pilot_probe_quality",
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
    constructive_pilot_summary_path = Path(args.constructive_pilot_summary)
    constructive_pilot_compare_path = Path(args.constructive_pilot_compare)
    previous_probe_summary_path = Path(args.previous_probe_summary)
    previous_probe_cost_path = Path(args.previous_probe_cost)
    previous_probe_compare_path = Path(args.previous_probe_compare)

    baseline_df = cash_diag.load_paper(baseline_path)
    frame = build_probe_frame(baseline_df)
    cost_cfg = prev_probe.load_phase68i_cost_assumptions(phase68i_summary_path, phase68i_paper_path)
    frame = prev_probe.apply_cost_model(frame, cost_cfg)
    activation_windows = build_activation_windows(frame)

    baseline_metrics = prev_probe.calc_model_metrics(
        returns_gross=frame["strategy_return"],
        returns_net=frame["baseline_strategy_return_net"],
        state_series=frame["in_market"].map({True: "BASELINE_RISK", False: "CASH"}),
        weight_series=frame["baseline_exposure_weight"],
        model=BASELINE_MODEL,
        pilot_days=0,
    )
    probe_metrics = prev_probe.calc_model_metrics(
        returns_gross=frame["probe_strategy_return_gross"],
        returns_net=frame["probe_strategy_return_net"],
        state_series=frame["probe_state"],
        weight_series=frame["probe_exposure_weight"],
        model=PROBE_MODEL,
        pilot_days=int(frame["pilot_active"].sum()),
    )

    constructive_pilot_summary = load_json(constructive_pilot_summary_path)
    previous_summary = load_json(previous_probe_summary_path)
    previous_metrics = load_metrics_row(previous_probe_cost_path, "high_conviction_pre_activation_pilot_probe")
    diagnosis_update = determine_diagnosis_update(
        compute_summary_metrics(activation_windows, baseline_metrics, probe_metrics),
        baseline_metrics,
        probe_metrics,
        previous_summary,
    )

    input_refs = {
        "baseline_paper": str(baseline_path),
        "phase68i_paper_secondary_context": str(phase68i_paper_path) if phase68i_paper_path.exists() else None,
        "phase68i_summary_secondary_context": str(phase68i_summary_path) if phase68i_summary_path.exists() else None,
        "constructive_pilot_summary": str(constructive_pilot_summary_path) if constructive_pilot_summary_path.exists() else None,
        "constructive_pilot_compare": str(constructive_pilot_compare_path) if constructive_pilot_compare_path.exists() else None,
        "previous_pre_activation_probe_summary": str(previous_probe_summary_path) if previous_probe_summary_path.exists() else None,
        "previous_pre_activation_probe_cost_metrics": str(previous_probe_cost_path) if previous_probe_cost_path.exists() else None,
        "previous_pre_activation_probe_compare": str(previous_probe_compare_path) if previous_probe_compare_path.exists() else None,
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
            diagnosis_update=diagnosis_update,
            constructive_pilot_summary=constructive_pilot_summary,
            previous_summary=previous_summary,
            previous_metrics=previous_metrics,
            cost_cfg=cost_cfg,
            input_refs=input_refs,
        ),
    )
    save_json(paths["manifest_json"], build_manifest_payload(paths, input_refs))
    save_json(
        paths["quality_json"],
        build_quality_payload(
            frame=frame,
            activation_windows=activation_windows,
            baseline_metrics=baseline_metrics,
            probe_metrics=probe_metrics,
            input_refs=input_refs,
        ),
    )

    print("rearmed_high_conviction_pre_activation_pilot_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
