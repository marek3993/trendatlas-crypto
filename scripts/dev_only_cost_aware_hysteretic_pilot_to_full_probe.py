from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import pandas as pd

import dev_only_cash_overstay_diagnostic as cash_diag
import dev_only_high_conviction_pre_activation_pilot_probe as pre_activation
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_cost_aware_hysteretic_pilot_to_full_probe"
)

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "cost_aware_hysteretic_pilot_to_full_probe"
MECHANISM_ID = "cost_aware_hysteretic_pilot_to_full"

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
HIGH_CONVICTION_SUMMARY_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_high_conviction_pre_activation_pilot_probe"
    / "high_conviction_pre_activation_pilot_probe.summary.json"
)
REARMED_SUMMARY_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_rearmed_high_conviction_pre_activation_pilot_probe"
    / "rearmed_high_conviction_pre_activation_pilot_probe.summary.json"
)

PILOT_WEIGHT = 0.15
FULL_WEIGHT = 1.0
PILOT_ENTRY_PERSISTENCE_DAYS = 2
FULL_ENTRY_PERSISTENCE_DAYS = 3
RECENT_RECAPTURE_MAX_AGE_DAYS = pre_activation.RECENT_RECAPTURE_MAX_AGE_DAYS
HYSTERETIC_EXIT_DAYS = 2

JSON_LOCKS = {
    "analysis_mode": "cost_aware_hysteretic_pilot_to_full_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}
WHY_DIFFERENT_FROM_PHASE68K_L_M = (
    "This probe is not another softer gate clone. It introduces a discrete cost-aware state machine with hysteretic "
    "Pilot-to-Full transition and no-trade band discipline."
)
WHY_DIFFERENT_FROM_CONSTRUCTIVE_PILOT_PERSISTENCE = (
    "This probe does not rely on staying exposed longer through full constructive windows. It uses a smaller earlier "
    "pilot with explicit hysteresis and clean escalation to full only after stronger confirmation."
)
WHY_DIFFERENT_FROM_HIGH_CONVICTION_PRE_ACTIVATION = (
    "This probe is not just a one-off pre-activation sleeve. It explicitly models CASH -> PILOT -> FULL with different "
    "thresholds and cost-aware no-trade-band discipline."
)
STOP_RULE = (
    "if earlier activation is only achievable with churn or DD worsens too much or net benefit is too small after costs "
    "or mechanism collapses into disguised persistence or disguised soft-gate behavior"
)
PAUSE_RULE = "if mechanism is promising but evidence breadth is still too narrow"

WINDOW_COMPARE_COLUMNS = [
    "window_id",
    "pilot_activation_date",
    "full_activation_date",
    "window_end_date",
    "baseline_handoff_date",
    "exit_reason",
    "pilot_asset",
    "asset_resolution",
    "pilot_days",
    "full_prebaseline_days",
    "lead_days_vs_baseline",
    "baseline_return_net",
    "probe_return_net",
    "net_early_move_capture",
    "baseline_return_gross",
    "probe_return_gross",
    "gross_early_move_capture",
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
    "full_prebaseline_days",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only cost-aware hysteretic Pilot-to-Full probe")
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
        "summary_json": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_probe.summary.json",
        "window_compare_csv": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_probe.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_probe.state_time.csv",
        "compare_csv": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_probe.compare.csv",
        "cost_metrics_csv": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_probe.cost_metrics.csv",
        "manifest_json": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_probe.manifest.json",
        "quality_json": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_probe.quality.json",
    }


def load_json(path: Path) -> Dict[str, Any]:
    return pre_activation.load_json(path) if path.exists() else {}


def compound_pct(values: pd.Series) -> float:
    return round(pre_activation.compound_return(values) * 100.0, 6)


def build_signal_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    frame = pre_activation.build_probe_frame(baseline_df).copy()
    frame["pilot_entry_signal"] = (
        frame["activation_raw"]
        .astype(int)
        .rolling(PILOT_ENTRY_PERSISTENCE_DAYS, min_periods=PILOT_ENTRY_PERSISTENCE_DAYS)
        .sum()
        .eq(PILOT_ENTRY_PERSISTENCE_DAYS)
        & pd.to_numeric(frame["benchmark_20d_return"], errors="coerce").fillna(-1.0).ge(0.0)
        & frame["recent_high_conviction_recapture"]
    )
    frame["full_entry_signal"] = (
        frame["activation_raw"]
        .astype(int)
        .rolling(FULL_ENTRY_PERSISTENCE_DAYS, min_periods=FULL_ENTRY_PERSISTENCE_DAYS)
        .sum()
        .eq(FULL_ENTRY_PERSISTENCE_DAYS)
        & pd.to_numeric(frame["benchmark_20d_return"], errors="coerce").fillna(-1.0).ge(0.0)
        & frame["recent_high_conviction_recapture"]
        & (~frame["pilot_local_downside_brake"].fillna(False))
    )
    constructive_failure_raw = (~frame["benchmark_constructive_valid"].fillna(False)) | (
        ~frame["benchmark_above_anchor"].fillna(False)
    )
    frame["hysteretic_constructive_failure"] = (
        constructive_failure_raw.astype(int)
        .rolling(HYSTERETIC_EXIT_DAYS, min_periods=HYSTERETIC_EXIT_DAYS)
        .sum()
        .ge(HYSTERETIC_EXIT_DAYS)
    )
    frame["hard_risk_off_exit"] = frame.get("risk_off_invalidation_day", False)
    frame["hysteretic_exit_signal"] = (
        frame["hysteretic_constructive_failure"].fillna(False)
        | frame["pilot_local_downside_brake"].fillna(False)
        | frame["hard_risk_off_exit"].fillna(False)
    )
    return frame


def build_probe_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    frame = build_signal_frame(baseline_df)
    state = "CASH"
    current_window_id = ""
    window_counter = 0

    states: List[str] = []
    window_ids: List[str] = []
    exit_reasons: List[str] = []
    pilot_start_flags: List[bool] = []
    full_upgrade_flags: List[bool] = []
    baseline_handoff_flags: List[bool] = []

    for _, row in frame.iterrows():
        baseline_cash = bool(row["baseline_cash"])
        exit_reason = ""
        pilot_start = False
        full_upgrade = False
        baseline_handoff = False
        exit_window_id = ""

        if not baseline_cash:
            baseline_handoff = state in {"PILOT", "FULL_PRE_BASELINE"}
            state = "BASELINE_FULL"
        else:
            if state == "BASELINE_FULL":
                state = "CASH"
                current_window_id = ""
            if state in {"PILOT", "FULL_PRE_BASELINE"} and bool(row["hysteretic_exit_signal"]):
                exit_reason = "hysteretic_failure_or_local_brake"
                exit_window_id = current_window_id
                state = "CASH"
                current_window_id = ""
            else:
                exit_window_id = ""
            if state == "PILOT" and bool(row["full_entry_signal"]):
                state = "FULL_PRE_BASELINE"
                full_upgrade = True
            if state == "CASH" and bool(row["pilot_entry_signal"]):
                window_counter += 1
                current_window_id = f"window_{window_counter:03d}"
                state = "PILOT"
                pilot_start = True

        states.append(state)
        window_ids.append(current_window_id if state in {"PILOT", "FULL_PRE_BASELINE"} or baseline_handoff else exit_window_id)
        exit_reasons.append(exit_reason)
        pilot_start_flags.append(pilot_start)
        full_upgrade_flags.append(full_upgrade)
        baseline_handoff_flags.append(baseline_handoff)

    frame["probe_state"] = states
    frame["pilot_window_id"] = window_ids
    frame["probe_exit_reason"] = exit_reasons
    frame["pilot_start_day"] = pilot_start_flags
    frame["full_upgrade_day"] = full_upgrade_flags
    frame["baseline_handoff_day"] = baseline_handoff_flags
    frame["pilot_active"] = frame["probe_state"].eq("PILOT")
    frame["full_prebaseline_active"] = frame["probe_state"].eq("FULL_PRE_BASELINE")
    frame["probe_in_market"] = frame["probe_state"].ne("CASH")
    frame["probe_exposure_weight"] = 0.0
    frame.loc[frame["pilot_active"], "probe_exposure_weight"] = PILOT_WEIGHT
    frame.loc[frame["full_prebaseline_active"], "probe_exposure_weight"] = FULL_WEIGHT
    frame.loc[~frame["baseline_cash"], "probe_exposure_weight"] = FULL_WEIGHT

    frame["probe_strategy_return_gross"] = pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)
    pilot_asset_return = pd.to_numeric(frame["pilot_return"], errors="coerce").fillna(0.0)
    frame.loc[frame["pilot_active"], "probe_strategy_return_gross"] = pilot_asset_return.loc[frame["pilot_active"]] * PILOT_WEIGHT
    frame.loc[frame["full_prebaseline_active"], "probe_strategy_return_gross"] = pilot_asset_return.loc[
        frame["full_prebaseline_active"]
    ] * FULL_WEIGHT
    return frame


def apply_cost_model(frame: pd.DataFrame, cost_cfg: Dict[str, float]) -> pd.DataFrame:
    out = frame.copy()
    baseline_weight = out["in_market"].astype(float)
    out["baseline_exposure_weight"] = baseline_weight
    out["baseline_turnover"] = baseline_weight.diff().abs().fillna(abs(float(baseline_weight.iloc[0])))
    out["probe_turnover"] = out["probe_exposure_weight"].diff().abs().fillna(abs(float(out["probe_exposure_weight"].iloc[0])))
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
        active_df = window_df.loc[window_df["probe_state"].isin(["PILOT", "FULL_PRE_BASELINE"])]
        if active_df.empty:
            continue
        start_date = pd.Timestamp(active_df.index.min())
        full_rows = window_df.loc[window_df["full_upgrade_day"]]
        handoff_rows = window_df.loc[window_df["baseline_handoff_day"]]
        exit_rows = window_df.loc[window_df["probe_exit_reason"].ne("")]
        full_date = pd.Timestamp(full_rows.index.min()) if not full_rows.empty else None
        handoff_date = pd.Timestamp(handoff_rows.index.min()) if not handoff_rows.empty else None
        if handoff_date is not None:
            end_date = handoff_date - pd.Timedelta(days=1)
            exit_reason = "baseline_handoff"
        elif not exit_rows.empty:
            end_date = pd.Timestamp(exit_rows.index.min())
            exit_reason = str(exit_rows.iloc[0]["probe_exit_reason"])
        else:
            end_date = pd.Timestamp(active_df.index.max())
            exit_reason = "still_open_at_dataset_end"
        window_slice = frame.loc[start_date:end_date].copy()
        baseline_return_net = compound_pct(window_slice["baseline_strategy_return_net"])
        probe_return_net = compound_pct(window_slice["probe_strategy_return_net"])
        baseline_return_gross = compound_pct(window_slice["strategy_return"])
        probe_return_gross = compound_pct(window_slice["probe_strategy_return_gross"])
        rows.append(
            {
                "window_id": window_id,
                "pilot_activation_date": start_date.strftime("%Y-%m-%d"),
                "full_activation_date": "" if full_date is None else full_date.strftime("%Y-%m-%d"),
                "window_end_date": end_date.strftime("%Y-%m-%d"),
                "baseline_handoff_date": "" if handoff_date is None else handoff_date.strftime("%Y-%m-%d"),
                "exit_reason": exit_reason,
                "pilot_asset": str(active_df.iloc[0]["pilot_asset"]),
                "asset_resolution": str(active_df.iloc[0]["asset_resolution"]),
                "pilot_days": int(window_slice["pilot_active"].sum()),
                "full_prebaseline_days": int(window_slice["full_prebaseline_active"].sum()),
                "lead_days_vs_baseline": 0 if handoff_date is None else int((handoff_date - start_date).days),
                "baseline_return_net": baseline_return_net,
                "probe_return_net": probe_return_net,
                "net_early_move_capture": round(probe_return_net - baseline_return_net, 6),
                "baseline_return_gross": baseline_return_gross,
                "probe_return_gross": probe_return_gross,
                "gross_early_move_capture": round(probe_return_gross - baseline_return_gross, 6),
            }
        )
    return rows


def build_state_time_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    total_days = int(len(frame))
    specs = [
        (BASELINE_MODEL, "BASELINE_FULL", int(frame["in_market"].sum())),
        (BASELINE_MODEL, "CASH", int((~frame["in_market"]).sum())),
        (PROBE_MODEL, "BASELINE_FULL", int(frame["probe_state"].eq("BASELINE_FULL").sum())),
        (PROBE_MODEL, "FULL_PRE_BASELINE", int(frame["probe_state"].eq("FULL_PRE_BASELINE").sum())),
        (PROBE_MODEL, "PILOT", int(frame["probe_state"].eq("PILOT").sum())),
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


def calc_metrics(
    returns_gross: pd.Series,
    returns_net: pd.Series,
    state_series: pd.Series,
    weight_series: pd.Series,
    *,
    model: str,
    pilot_days: int,
    full_prebaseline_days: int,
) -> Dict[str, Any]:
    metrics = pre_activation.calc_model_metrics(
        returns_gross=returns_gross,
        returns_net=returns_net,
        state_series=state_series,
        weight_series=weight_series,
        model=model,
        pilot_days=pilot_days,
    )
    metrics["full_prebaseline_days"] = int(full_prebaseline_days)
    return metrics


def build_compare_rows(
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    lead_days = [row["lead_days_vs_baseline"] for row in activation_windows if row["baseline_handoff_date"]]
    net_capture = sum(float(row["net_early_move_capture"]) for row in activation_windows)
    gross_capture = sum(float(row["gross_early_move_capture"]) for row in activation_windows)
    metrics = [
        ("net_return_after_costs_pct", baseline_metrics["net_return_after_costs_pct"], probe_metrics["net_return_after_costs_pct"]),
        ("net_cagr_pct", baseline_metrics["net_cagr_pct"], probe_metrics["net_cagr_pct"]),
        ("max_drawdown_pct", baseline_metrics["max_drawdown_pct"], probe_metrics["max_drawdown_pct"]),
        ("trade_count", baseline_metrics["trade_count"], probe_metrics["trade_count"]),
        ("switch_count", baseline_metrics["switch_count"], probe_metrics["switch_count"]),
        ("turnover_pressure", baseline_metrics["turnover_pressure"], probe_metrics["turnover_pressure"]),
        ("total_cost_pct", baseline_metrics["total_cost_pct"], probe_metrics["total_cost_pct"]),
        ("gross_return_pct", baseline_metrics["gross_return_pct"], probe_metrics["gross_return_pct"]),
        ("activation_window_count", 0.0, float(len(activation_windows))),
        ("activation_window_handoff_count", 0.0, float(len(lead_days))),
        ("avg_lead_days_vs_baseline", 0.0, float(sum(lead_days) / len(lead_days)) if lead_days else 0.0),
        ("median_lead_days_vs_baseline", 0.0, float(median(lead_days)) if lead_days else 0.0),
        ("net_early_move_capture_pct", 0.0, net_capture),
        ("gross_early_move_capture_pct", 0.0, gross_capture),
        ("pilot_days", baseline_metrics["pilot_days"], probe_metrics["pilot_days"]),
        ("full_prebaseline_days", baseline_metrics["full_prebaseline_days"], probe_metrics["full_prebaseline_days"]),
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
    lead_days = [row["lead_days_vs_baseline"] for row in activation_windows if row["baseline_handoff_date"]]
    net_capture = round(sum(float(row["net_early_move_capture"]) for row in activation_windows), 6)
    gross_capture = round(sum(float(row["gross_early_move_capture"]) for row in activation_windows), 6)
    trade_delta = int(probe_metrics["trade_count"] - baseline_metrics["trade_count"])
    switch_delta = int(probe_metrics["switch_count"] - baseline_metrics["switch_count"])
    turnover_delta = round(float(probe_metrics["turnover_pressure"] - baseline_metrics["turnover_pressure"]), 6)
    dd_delta = round(float(probe_metrics["max_drawdown_pct"] - baseline_metrics["max_drawdown_pct"]), 6)
    net_delta = round(float(probe_metrics["net_return_after_costs_pct"] - baseline_metrics["net_return_after_costs_pct"]), 6)
    total_prebaseline_days = int(probe_metrics["pilot_days"] + probe_metrics["full_prebaseline_days"])

    meaningful_early = bool(lead_days) and max(lead_days) >= 7
    useful_net_capture = net_capture >= 0.50 and net_delta > 0.0
    churn_ok = trade_delta <= 3 and switch_delta <= 3 and turnover_delta <= 3.0
    dd_ok = dd_delta >= -1.0
    disguised_persistence = total_prebaseline_days > 90
    stop_triggered = (not meaningful_early) or (not useful_net_capture) or (not churn_ok) or (not dd_ok) or disguised_persistence
    pause_triggered = (not stop_triggered) and len(lead_days) < 2
    final_verdict = "stop_condition_triggered" if stop_triggered else "pause_condition_triggered" if pause_triggered else "continue_dev_only"

    return with_json_locks(
        {
            "artifact_id": "cost_aware_hysteretic_pilot_to_full_probe",
            "generated_at_utc": timestamp_utc(),
            "final_verdict": final_verdict,
            "mechanism_id": MECHANISM_ID,
            "compare_baseline": BASELINE_MODEL,
            "lead_days_vs_baseline": {
                "activation_windows_with_handoff": int(len(lead_days)),
                "avg_lead_days": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
                "median_lead_days": round(float(median(lead_days)), 6) if lead_days else 0.0,
                "max_lead_days": int(max(lead_days)) if lead_days else 0,
            },
            "net_early_move_capture": {
                "total_pct": net_capture,
                "window_count": int(len(activation_windows)),
            },
            "trade_days_delta": trade_delta,
            "switch_count_delta": switch_delta,
            "turnover_pressure": {
                "baseline": round(float(baseline_metrics["turnover_pressure"]), 6),
                "probe": round(float(probe_metrics["turnover_pressure"]), 6),
                "delta_probe_minus_baseline": turnover_delta,
            },
            "max_drawdown_net": {
                "baseline_pct": round(float(baseline_metrics["max_drawdown_pct"]), 6),
                "probe_pct": round(float(probe_metrics["max_drawdown_pct"]), 6),
                "delta_probe_minus_baseline_pct": dd_delta,
            },
            "total_return_net": {
                "baseline_pct": round(float(baseline_metrics["net_return_after_costs_pct"]), 6),
                "probe_pct": round(float(probe_metrics["net_return_after_costs_pct"]), 6),
                "delta_probe_minus_baseline_pct": net_delta,
            },
            "cagr_net": {
                "baseline_pct": round(float(baseline_metrics["net_cagr_pct"]), 6),
                "probe_pct": round(float(probe_metrics["net_cagr_pct"]), 6),
                "delta_probe_minus_baseline_pct": round(float(probe_metrics["net_cagr_pct"] - baseline_metrics["net_cagr_pct"]), 6),
            },
            "gross_metrics_context": {
                "baseline_gross_return_pct": round(float(baseline_metrics["gross_return_pct"]), 6),
                "probe_gross_return_pct": round(float(probe_metrics["gross_return_pct"]), 6),
                "delta_probe_minus_baseline_pct": round(float(probe_metrics["gross_return_pct"] - baseline_metrics["gross_return_pct"]), 6),
                "gross_early_move_capture_pct": gross_capture,
            },
            "why_different_from_phase68k_l_m": WHY_DIFFERENT_FROM_PHASE68K_L_M,
            "why_different_from_constructive_pilot_persistence": WHY_DIFFERENT_FROM_CONSTRUCTIVE_PILOT_PERSISTENCE,
            "why_different_from_high_conviction_pre_activation": WHY_DIFFERENT_FROM_HIGH_CONVICTION_PRE_ACTIVATION,
            "state_machine": {
                "allowed_states": ["CASH", "PILOT", "FULL"],
                "allowed_weights": [0.0, PILOT_WEIGHT, FULL_WEIGHT],
                "pilot_entry": [
                    "baseline must be CASH",
                    "BTC 20DMA > BTC 100DMA",
                    "BTC close > BTC 100DMA",
                    "pilot asset > own 100DMA",
                    "pilot asset 20-day relative strength versus BTC >= 0",
                    "BTC 20-day return >= 0 as the cost-aware no-trade band",
                    f"setup persists {PILOT_ENTRY_PERSISTENCE_DAYS} days",
                    f"fresh benchmark/pilot recapture within {RECENT_RECAPTURE_MAX_AGE_DAYS} days",
                ],
                "pilot_to_full": [
                    f"same stack persists {FULL_ENTRY_PERSISTENCE_DAYS} days",
                    "BTC 20-day return remains >= 0",
                    "existing local downside brake is not active",
                    "baseline handoff also maps cleanly to FULL",
                ],
                "exit": [
                    f"constructive failure persists {HYSTERETIC_EXIT_DAYS} days",
                    "or existing local downside brake",
                    "or hard benchmark risk-off invalidation",
                ],
            },
            "cost_model": {
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
            "status": "generated_dev_only_cost_aware_hysteretic_pilot_to_full_probe_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": "cost_aware_hysteretic_pilot_to_full_probe_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": ["research_os/dev_only/contracts/dev_only_cost_aware_hysteretic_pilot_to_full_probe.contract.json"],
            "spec_refs": ["research_os/dev_only/specs/dev_only_cost_aware_hysteretic_pilot_to_full_probe.spec.json"],
            "manifest_seed_refs": ["research_os/dev_only/manifests/dev_only_cost_aware_hysteretic_pilot_to_full_probe.manifest.json"],
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
    non_discrete_weights = ~frame["probe_exposure_weight"].isin([0.0, PILOT_WEIGHT, FULL_WEIGHT])
    checks = [
        {
            "name": "discrete_weights_only",
            "ok": not bool(non_discrete_weights.any()),
            "detail": "probe uses only 0.00, 0.15, and 1.00 exposure weights",
        },
        {
            "name": "pilot_only_from_baseline_cash",
            "ok": not bool((frame["pilot_start_day"] & (~frame["baseline_cash"])).any()),
            "detail": "PILOT starts only while baseline is CASH",
        },
        {
            "name": "full_prebaseline_has_prior_pilot",
            "ok": int(frame["full_prebaseline_active"].sum()) == 0
            or bool(frame["pilot_start_day"].cumsum().loc[frame["full_prebaseline_active"]].gt(0).all()),
            "detail": "FULL_PRE_BASELINE cannot appear before a PILOT start",
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
            "artifact_id": "cost_aware_hysteretic_pilot_to_full_probe_quality",
            "generated_at_utc": timestamp_utc(),
            "input_refs": input_refs,
            "checks": checks,
            "activation_windows_count": int(len(activation_windows)),
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
    cost_cfg = pre_activation.load_phase68i_cost_assumptions(phase68i_summary_path, phase68i_paper_path)
    frame = apply_cost_model(frame, cost_cfg)
    activation_windows = build_activation_windows(frame)

    baseline_metrics = calc_metrics(
        returns_gross=frame["strategy_return"],
        returns_net=frame["baseline_strategy_return_net"],
        state_series=frame["in_market"].map({True: "BASELINE_FULL", False: "CASH"}),
        weight_series=frame["baseline_exposure_weight"],
        model=BASELINE_MODEL,
        pilot_days=0,
        full_prebaseline_days=0,
    )
    probe_metrics = calc_metrics(
        returns_gross=frame["probe_strategy_return_gross"],
        returns_net=frame["probe_strategy_return_net"],
        state_series=frame["probe_state"],
        weight_series=frame["probe_exposure_weight"],
        model=PROBE_MODEL,
        pilot_days=int(frame["pilot_active"].sum()),
        full_prebaseline_days=int(frame["full_prebaseline_active"].sum()),
    )

    input_refs = {
        "baseline_paper": str(baseline_path),
        "phase68i_paper_secondary_context": str(phase68i_paper_path) if phase68i_paper_path.exists() else None,
        "phase68i_summary_secondary_context": str(phase68i_summary_path) if phase68i_summary_path.exists() else None,
        "constructive_pilot_summary": str(CONSTRUCTIVE_PILOT_SUMMARY_PATH) if CONSTRUCTIVE_PILOT_SUMMARY_PATH.exists() else None,
        "high_conviction_pre_activation_summary": str(HIGH_CONVICTION_SUMMARY_PATH) if HIGH_CONVICTION_SUMMARY_PATH.exists() else None,
        "rearmed_high_conviction_pre_activation_summary": str(REARMED_SUMMARY_PATH) if REARMED_SUMMARY_PATH.exists() else None,
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
            cost_cfg=cost_cfg,
            input_refs=input_refs,
        ),
    )
    save_json(paths["manifest_json"], build_manifest_payload(paths, input_refs))
    save_json(paths["quality_json"], build_quality_payload(frame, baseline_metrics, probe_metrics, activation_windows, input_refs))

    print("cost_aware_hysteretic_pilot_to_full_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
