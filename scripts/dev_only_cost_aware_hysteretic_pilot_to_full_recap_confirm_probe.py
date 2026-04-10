from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import pandas as pd

import dev_only_cash_overstay_diagnostic as cash_diag
import dev_only_cost_aware_hysteretic_pilot_to_full_probe as base_probe
import dev_only_high_conviction_pre_activation_pilot_probe as pre_activation
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_cost_aware_hysteretic_pilot_to_full_recap_confirm_probe"
)

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe"
MECHANISM_ID = "cost_aware_hysteretic_pilot_to_full_recap_confirm"
PREVIOUS_PROBE_ID = "dev_only_cost_aware_hysteretic_pilot_to_full_probe"

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
PREVIOUS_COST_AWARE_SUMMARY_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_cost_aware_hysteretic_pilot_to_full_probe"
    / "cost_aware_hysteretic_pilot_to_full_probe.summary.json"
)
PREVIOUS_COST_AWARE_COST_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_cost_aware_hysteretic_pilot_to_full_probe"
    / "cost_aware_hysteretic_pilot_to_full_probe.cost_metrics.csv"
)

PILOT_WEIGHT = base_probe.PILOT_WEIGHT
FULL_WEIGHT = base_probe.FULL_WEIGHT
PILOT_ENTRY_PERSISTENCE_DAYS = base_probe.PILOT_ENTRY_PERSISTENCE_DAYS
FULL_ENTRY_PERSISTENCE_DAYS = base_probe.FULL_ENTRY_PERSISTENCE_DAYS
RECAPTURE_HOLD_DAYS = 2
HYSTERETIC_EXIT_DAYS = base_probe.HYSTERETIC_EXIT_DAYS

JSON_LOCKS = {
    "analysis_mode": "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}
WHY_SAME_FAMILY_NOT_DUPLICATE = (
    "This probe keeps the same cost-aware hysteretic CASH -> PILOT -> FULL family, but replaces recapture recency with "
    "recapture-and-hold confirmation to test whether broader earlier-activation evidence appears without adding churn."
)
STOP_RULE = (
    "if no new valid earlier-activation evidence appears or generalization requires higher churn / switches / DD or this "
    "remains a one-window-only family"
)
PAUSE_RULE = "if family remains strong but still too narrow for stronger progression language"

WINDOW_COMPARE_COLUMNS = base_probe.WINDOW_COMPARE_COLUMNS
STATE_TIME_COLUMNS = base_probe.STATE_TIME_COLUMNS
COMPARE_COLUMNS = base_probe.COMPARE_COLUMNS
COST_COLUMNS = base_probe.COST_COLUMNS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dev-only cost-aware hysteretic Pilot-to-Full recap-confirm probe"
    )
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
        "summary_json": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.summary.json",
        "window_compare_csv": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.state_time.csv",
        "compare_csv": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.compare.csv",
        "cost_metrics_csv": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.cost_metrics.csv",
        "manifest_json": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.manifest.json",
        "quality_json": OUTPUT_ROOT / "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.quality.json",
    }


def build_recapture_hold_signal(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    benchmark_above = out["benchmark_above_anchor"].fillna(False).astype(bool)
    pilot_above = out["pilot_above_anchor"].fillna(False).astype(bool)
    out["benchmark_recapture_event"] = benchmark_above & (~benchmark_above.shift(1, fill_value=False))
    out["pilot_anchor_recapture_event"] = pilot_above & (~pilot_above.shift(1, fill_value=False))
    recapture_event = out["benchmark_recapture_event"] | out["pilot_anchor_recapture_event"]
    both_above = benchmark_above & pilot_above

    hold_days: List[int] = []
    confirmed_flags: List[bool] = []
    active_recaptured_segment = False
    current_hold_days = 0
    for event_flag, both_flag in zip(recapture_event.tolist(), both_above.tolist()):
        if not bool(both_flag):
            active_recaptured_segment = False
            current_hold_days = 0
        elif bool(event_flag):
            active_recaptured_segment = True
            current_hold_days = 1
        elif active_recaptured_segment:
            current_hold_days += 1
        else:
            current_hold_days = 0
        hold_days.append(current_hold_days)
        confirmed_flags.append(active_recaptured_segment and current_hold_days >= RECAPTURE_HOLD_DAYS)

    out["recapture_hold_days"] = hold_days
    out["recapture_confirmed_and_held"] = confirmed_flags
    return out


def build_signal_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    frame = pre_activation.build_probe_frame(baseline_df).copy()
    frame = build_recapture_hold_signal(frame)
    frame["pilot_entry_signal"] = (
        frame["activation_raw"]
        .astype(int)
        .rolling(PILOT_ENTRY_PERSISTENCE_DAYS, min_periods=PILOT_ENTRY_PERSISTENCE_DAYS)
        .sum()
        .eq(PILOT_ENTRY_PERSISTENCE_DAYS)
        & pd.to_numeric(frame["benchmark_20d_return"], errors="coerce").fillna(-1.0).ge(0.0)
        & frame["recapture_confirmed_and_held"]
    )
    frame["full_entry_signal"] = (
        frame["activation_raw"]
        .astype(int)
        .rolling(FULL_ENTRY_PERSISTENCE_DAYS, min_periods=FULL_ENTRY_PERSISTENCE_DAYS)
        .sum()
        .eq(FULL_ENTRY_PERSISTENCE_DAYS)
        & pd.to_numeric(frame["benchmark_20d_return"], errors="coerce").fillna(-1.0).ge(0.0)
        & frame["recapture_confirmed_and_held"]
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
    original_signal_builder = base_probe.build_signal_frame
    try:
        base_probe.build_signal_frame = build_signal_frame
        return base_probe.build_probe_frame(baseline_df)
    finally:
        base_probe.build_signal_frame = original_signal_builder


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
    meaningful_windows = [
        row
        for row in activation_windows
        if row["baseline_handoff_date"] and int(row["lead_days_vs_baseline"]) >= 7 and float(row["net_early_move_capture"]) > 0.0
    ]
    net_capture = round(sum(float(row["net_early_move_capture"]) for row in activation_windows), 6)
    gross_capture = round(sum(float(row["gross_early_move_capture"]) for row in activation_windows), 6)
    trade_delta = int(probe_metrics["trade_count"] - baseline_metrics["trade_count"])
    switch_delta = int(probe_metrics["switch_count"] - baseline_metrics["switch_count"])
    turnover_delta = round(float(probe_metrics["turnover_pressure"] - baseline_metrics["turnover_pressure"]), 6)
    dd_delta = round(float(probe_metrics["max_drawdown_pct"] - baseline_metrics["max_drawdown_pct"]), 6)
    net_delta = round(float(probe_metrics["net_return_after_costs_pct"] - baseline_metrics["net_return_after_costs_pct"]), 6)
    cagr_delta = round(float(probe_metrics["net_cagr_pct"] - baseline_metrics["net_cagr_pct"]), 6)
    total_prebaseline_days = int(probe_metrics["pilot_days"] + probe_metrics["full_prebaseline_days"])

    churn_ok = trade_delta <= 3 and switch_delta <= 3 and turnover_delta <= 3.0
    dd_ok = dd_delta >= -1.0
    useful_net_capture = net_capture > 0.0 and net_delta > 0.0
    not_persistence_like = total_prebaseline_days <= 90
    repeated_valid_evidence = len(meaningful_windows) >= 2
    stop_triggered = (not repeated_valid_evidence) or (not useful_net_capture) or (not churn_ok) or (not dd_ok) or (
        not not_persistence_like
    )
    pause_triggered = not stop_triggered
    final_verdict = "stop_condition_triggered" if stop_triggered else "pause_condition_triggered"

    return with_json_locks(
        {
            "artifact_id": "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe",
            "generated_at_utc": timestamp_utc(),
            "final_verdict": final_verdict,
            "mechanism_id": MECHANISM_ID,
            "compare_baseline": BASELINE_MODEL,
            "compare_vs_previous_cost_aware_hysteretic_pilot_to_full": PREVIOUS_PROBE_ID,
            "meaningful_earlier_activation_windows": {
                "count": int(len(meaningful_windows)),
                "window_ids": [str(row["window_id"]) for row in meaningful_windows],
            },
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
            "net_max_drawdown": {
                "baseline_pct": round(float(baseline_metrics["max_drawdown_pct"]), 6),
                "probe_pct": round(float(probe_metrics["max_drawdown_pct"]), 6),
                "delta_probe_minus_baseline_pct": dd_delta,
            },
            "net_total_return": {
                "baseline_pct": round(float(baseline_metrics["net_return_after_costs_pct"]), 6),
                "probe_pct": round(float(probe_metrics["net_return_after_costs_pct"]), 6),
                "delta_probe_minus_baseline_pct": net_delta,
            },
            "net_cagr": {
                "baseline_pct": round(float(baseline_metrics["net_cagr_pct"]), 6),
                "probe_pct": round(float(probe_metrics["net_cagr_pct"]), 6),
                "delta_probe_minus_baseline_pct": cagr_delta,
            },
            "gross_metrics_context": {
                "baseline_gross_return_pct": round(float(baseline_metrics["gross_return_pct"]), 6),
                "probe_gross_return_pct": round(float(probe_metrics["gross_return_pct"]), 6),
                "delta_probe_minus_baseline_pct": round(float(probe_metrics["gross_return_pct"] - baseline_metrics["gross_return_pct"]), 6),
                "gross_early_move_capture_pct": gross_capture,
            },
            "why_same_family_not_duplicate": WHY_SAME_FAMILY_NOT_DUPLICATE,
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
                    f"recapture event occurs and benchmark plus pilot asset remain above anchors for {RECAPTURE_HOLD_DAYS} consecutive days",
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
            "status": "generated_dev_only_cost_aware_hysteretic_pilot_to_full_recap_confirm_probe_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [
                "research_os/dev_only/contracts/dev_only_cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.contract.json"
            ],
            "spec_refs": [
                "research_os/dev_only/specs/dev_only_cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.spec.json"
            ],
            "manifest_seed_refs": [
                "research_os/dev_only/manifests/dev_only_cost_aware_hysteretic_pilot_to_full_recap_confirm_probe.manifest.json"
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
            "name": "recapture_and_hold_gate_present",
            "ok": bool(frame["recapture_confirmed_and_held"].any()),
            "detail": "PILOT entry is gated by recapture event plus two-day benchmark/pilot anchor hold",
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
            "artifact_id": "cost_aware_hysteretic_pilot_to_full_recap_confirm_probe_quality",
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
    frame = base_probe.apply_cost_model(frame, cost_cfg)
    activation_windows = base_probe.build_activation_windows(frame)

    baseline_metrics = base_probe.calc_metrics(
        returns_gross=frame["strategy_return"],
        returns_net=frame["baseline_strategy_return_net"],
        state_series=frame["in_market"].map({True: "BASELINE_FULL", False: "CASH"}),
        weight_series=frame["baseline_exposure_weight"],
        model=BASELINE_MODEL,
        pilot_days=0,
        full_prebaseline_days=0,
    )
    probe_metrics = base_probe.calc_metrics(
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
        "previous_cost_aware_hysteretic_summary": str(PREVIOUS_COST_AWARE_SUMMARY_PATH)
        if PREVIOUS_COST_AWARE_SUMMARY_PATH.exists()
        else None,
        "previous_cost_aware_hysteretic_cost_metrics": str(PREVIOUS_COST_AWARE_COST_PATH)
        if PREVIOUS_COST_AWARE_COST_PATH.exists()
        else None,
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

    print("cost_aware_hysteretic_pilot_to_full_recap_confirm_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
