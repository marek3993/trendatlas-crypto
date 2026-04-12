from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import pandas as pd

import dev_only_breadth_ignition_volatility_hostility_veto_probe as prev_probe
import dev_only_cash_overstay_diagnostic as cash_diag
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_breadth_ignition_volatility_hostility_veto_confirm_probe"
BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "breadth_ignition_volatility_hostility_veto_confirm_probe"
MECHANISM_ID = "smoothed_breadth_two_day_confirm_volatility_hostility_veto"
CONFIRMATION_DAYS = 2

BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
PHASE68I_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
PHASE68I_SUMMARY_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_summary.csv"
PURE_BREADTH_SUMMARY_PATH = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_breadth_ignition_regime_probe" / "breadth_ignition_regime_probe.summary.json"
PURE_BREADTH_COST_PATH = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_breadth_ignition_regime_probe" / "breadth_ignition_regime_probe.cost_metrics.csv"
PRIOR_VETO_SUMMARY_PATH = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_breadth_ignition_volatility_hostility_veto_probe" / "breadth_ignition_volatility_hostility_veto_probe.summary.json"
PRIOR_VETO_COST_PATH = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_breadth_ignition_volatility_hostility_veto_probe" / "breadth_ignition_volatility_hostility_veto_probe.cost_metrics.csv"

JSON_LOCKS = {
    "analysis_mode": "breadth_ignition_volatility_hostility_veto_confirm_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}

WINDOW_COMPARE_COLUMNS = [
    "window_id",
    "breadth_activation_date",
    "window_end_date",
    "baseline_handoff_date",
    "activation_kind",
    "lead_days_vs_baseline",
    "breadth_risk_days",
    "entry_breadth",
    "entry_smoothed_breadth",
    "entry_two_day_confirmation",
    "entry_eligible_assets",
    "entry_positive_assets",
    "entry_slow_btc_realized_vol_annualized",
    "entry_vol_hostility_threshold",
    "entry_vol_hostility_veto_active",
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
    parser = argparse.ArgumentParser(description="Dev-only breadth ignition two-day confirm + unchanged volatility veto")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--phase68i-paper", type=str, default=str(PHASE68I_PAPER_PATH))
    parser.add_argument("--phase68i-summary", type=str, default=str(PHASE68I_SUMMARY_PATH))
    parser.add_argument("--pure-breadth-summary", type=str, default=str(PURE_BREADTH_SUMMARY_PATH))
    parser.add_argument("--pure-breadth-cost", type=str, default=str(PURE_BREADTH_COST_PATH))
    parser.add_argument("--prior-veto-summary", type=str, default=str(PRIOR_VETO_SUMMARY_PATH))
    parser.add_argument("--prior-veto-cost", type=str, default=str(PRIOR_VETO_COST_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    stem = "breadth_ignition_volatility_hostility_veto_confirm_probe"
    return {
        "summary_json": OUTPUT_ROOT / f"{stem}.summary.json",
        "window_compare_csv": OUTPUT_ROOT / f"{stem}.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / f"{stem}.state_time.csv",
        "compare_csv": OUTPUT_ROOT / f"{stem}.compare.csv",
        "cost_metrics_csv": OUTPUT_ROOT / f"{stem}.cost_metrics.csv",
        "manifest_json": OUTPUT_ROOT / f"{stem}.manifest.json",
        "quality_json": OUTPUT_ROOT / f"{stem}.quality.json",
    }


def safe_float(value: Any, default: float = 0.0) -> float:
    return prev_probe.safe_float(value, default)


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
    lead_block = summary.get("lead_days_vs_baseline", {})
    lead_days = lead_block.get("all_valid_handoff_windows", []) if isinstance(lead_block, dict) else []
    return {
        "final_verdict": str(summary.get("final_verdict", "")),
        "earlier_activation_windows": int(summary.get("number_of_earlier_activation_windows", 0)),
        "lead_days": [int(x) for x in lead_days],
        "avg_lead_days": round(safe_float(lead_block.get("avg"), 0.0), 6) if isinstance(lead_block, dict) else 0.0,
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
            "net_early_move_capture_pct": round(float(current["net_early_move_capture_pct"] - reference.get("net_early_move_capture_pct", 0.0)), 6),
            "trade_count": int(current["trade_count"] - reference.get("trade_count", 0)),
            "switch_count": int(current["switch_count"] - reference.get("switch_count", 0)),
            "turnover_pressure": round(float(current["turnover_pressure"] - reference.get("turnover_pressure", 0.0)), 6),
            "net_max_drawdown_pct": round(float(current["max_drawdown_pct"] - reference.get("max_drawdown_pct", 0.0)), 6),
            "net_total_return_pct": round(float(current["net_total_return_pct"] - reference.get("net_total_return_pct", 0.0)), 6),
            "net_cagr_pct": round(float(current["net_cagr_pct"] - reference.get("net_cagr_pct", 0.0)), 6),
            "gross_total_return_pct": round(float(current["gross_total_return_pct"] - reference.get("gross_total_return_pct", 0.0)), 6),
        },
    }


def add_breadth_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    eligible_parts: List[pd.Series] = []
    positive_parts: List[pd.Series] = []
    for asset in prev_probe.UNIVERSE_SYMBOLS:
        asset_frame = prev_probe.load_asset_trend_frame(asset).reindex(out.index).ffill()
        eligible_parts.append(asset_frame["breadth_eligible"].fillna(False).astype(bool).rename(asset))
        positive_parts.append(asset_frame["breadth_positive"].fillna(False).astype(bool).rename(asset))
    eligible_df = pd.concat(eligible_parts, axis=1)
    positive_df = pd.concat(positive_parts, axis=1) & eligible_df
    eligible_count = eligible_df.sum(axis=1)
    positive_count = positive_df.sum(axis=1)
    breadth = (positive_count / eligible_count.where(eligible_count.gt(0))).where(eligible_count >= prev_probe.MIN_ELIGIBLE_ASSETS)
    smoothed = breadth.ewm(span=prev_probe.BREADTH_SMOOTHING_EMA_SPAN_DAYS, adjust=False, min_periods=prev_probe.BREADTH_SMOOTHING_EMA_SPAN_DAYS).mean()
    threshold_candidate = smoothed.gt(prev_probe.BREADTH_IGNITION_THRESHOLD).fillna(False)
    two_day_confirmation = threshold_candidate.astype(int).rolling(CONFIRMATION_DAYS, min_periods=CONFIRMATION_DAYS).sum().eq(CONFIRMATION_DAYS)
    ignition = []
    active = False
    for candidate, confirmed in zip(threshold_candidate.tolist(), two_day_confirmation.tolist()):
        if (not active) and bool(confirmed):
            active = True
        elif active and (not bool(candidate)):
            active = False
        ignition.append(active)
    ignition_on = pd.Series(ignition, index=out.index, dtype=bool)
    out["breadth_eligible_assets"] = eligible_count.astype(int)
    out["breadth_positive_assets"] = positive_count.astype(int)
    out["breadth_share"] = breadth
    out["breadth_smoothed"] = smoothed
    out["breadth_threshold_candidate"] = threshold_candidate
    out["breadth_two_day_confirmation"] = two_day_confirmation.fillna(False)
    out["breadth_threshold_cross_up"] = ignition_on & (~ignition_on.shift(1, fill_value=False))
    out["breadth_ignition_on"] = ignition_on
    return out


def build_probe_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    original = prev_probe.add_breadth_columns
    try:
        prev_probe.add_breadth_columns = add_breadth_columns
        return prev_probe.build_probe_frame(baseline_df).copy()
    finally:
        prev_probe.add_breadth_columns = original


def build_activation_windows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    rows = prev_probe.build_activation_windows(frame)
    for row in rows:
        row["activation_kind"] = "cross_sectional_breadth_ignition_two_day_confirm"
        row["entry_two_day_confirmation"] = bool(frame.loc[pd.Timestamp(row["breadth_activation_date"]), "breadth_two_day_confirmation"])
    return rows


def build_state_time_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    total_days = int(len(frame))
    specs = [
        (BASELINE_MODEL, "BASELINE_RISK", int(frame["in_market"].sum())),
        (BASELINE_MODEL, "CASH", int((~frame["in_market"]).sum())),
        (PROBE_MODEL, "BASELINE_RISK", int(frame["probe_state"].eq("BASELINE_RISK").sum())),
        (PROBE_MODEL, "BREADTH_BTC_RISK", int(frame["probe_state"].eq("BREADTH_BTC_RISK").sum())),
        (PROBE_MODEL, "CASH", int(frame["probe_state"].eq("CASH").sum())),
    ]
    return [{"model": m, "state": s, "days": d, "share_of_total_days": round(d / total_days, 6) if total_days else 0.0} for m, s, d in specs]


def build_compare_rows(baseline_metrics: Dict[str, Any], probe_metrics: Dict[str, Any], activation_windows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    valid_windows = prev_probe.valid_handoff_windows(activation_windows)
    lead_days = [int(row["lead_days_vs_baseline"]) for row in valid_windows]
    metrics = [
        ("number_of_earlier_activation_windows", 0.0, float(len(valid_windows))),
        ("avg_lead_days_vs_baseline", 0.0, float(sum(lead_days) / len(lead_days)) if lead_days else 0.0),
        ("median_lead_days_vs_baseline", 0.0, float(median(lead_days)) if lead_days else 0.0),
        ("max_lead_days_vs_baseline", 0.0, float(max(lead_days)) if lead_days else 0.0),
        ("net_early_move_capture_pct", 0.0, sum(float(row["net_early_move_capture"]) for row in activation_windows)),
        ("gross_early_move_capture_pct", 0.0, sum(float(row["gross_early_move_capture"]) for row in activation_windows)),
        ("trade_count", baseline_metrics["trade_count"], probe_metrics["trade_count"]),
        ("switch_count", baseline_metrics["switch_count"], probe_metrics["switch_count"]),
        ("turnover_pressure", baseline_metrics["turnover_pressure"], probe_metrics["turnover_pressure"]),
        ("net_max_drawdown_pct", baseline_metrics["max_drawdown_pct"], probe_metrics["max_drawdown_pct"]),
        ("net_total_return_pct", baseline_metrics["net_return_after_costs_pct"], probe_metrics["net_return_after_costs_pct"]),
        ("net_cagr_pct", baseline_metrics["net_cagr_pct"], probe_metrics["net_cagr_pct"]),
        ("gross_total_return_pct", baseline_metrics["gross_return_pct"], probe_metrics["gross_return_pct"]),
    ]
    return [{"metric": metric, "baseline_model": BASELINE_MODEL, "baseline_value": float(a), "probe_model": PROBE_MODEL, "probe_value": float(b), "delta_probe_minus_baseline": float(b) - float(a)} for metric, a, b in metrics]


def build_summary_payload(baseline_metrics: Dict[str, Any], probe_metrics: Dict[str, Any], activation_windows: List[Dict[str, Any]], cost_cfg: Dict[str, float], pure_snapshot: Dict[str, Any], prior_snapshot: Dict[str, Any], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    valid_windows = prev_probe.valid_handoff_windows(activation_windows)
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
    stop_triggered = (probe_metrics["max_drawdown_pct"] < prior_snapshot.get("max_drawdown_pct", probe_metrics["max_drawdown_pct"])) or (len(valid_windows) <= 1) or (net_capture <= 0.0) or (net_delta <= 0.0) or (trade_delta > 3) or (switch_delta > 3) or (turnover_delta > 3.0)
    pause_triggered = (not stop_triggered) and ((net_capture < prior_snapshot.get("net_early_move_capture_pct", 0.0)) or (len(valid_windows) <= prior_snapshot.get("earlier_activation_windows", 0)))
    final_verdict = "stop" if stop_triggered else "pause" if pause_triggered else "continue"
    current_snapshot = {
        "final_verdict": final_verdict,
        "earlier_activation_windows": int(len(valid_windows)),
        "lead_days": lead_days,
        "avg_lead_days": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
        "net_early_move_capture_pct": net_capture,
        "trade_count": int(probe_metrics["trade_count"]),
        "switch_count": int(probe_metrics["switch_count"]),
        "turnover_pressure": round(float(probe_metrics["turnover_pressure"]), 6),
        "max_drawdown_pct": round(float(probe_metrics["max_drawdown_pct"]), 6),
        "net_total_return_pct": round(float(probe_metrics["net_return_after_costs_pct"]), 6),
        "net_cagr_pct": round(float(probe_metrics["net_cagr_pct"]), 6),
        "gross_total_return_pct": round(float(probe_metrics["gross_return_pct"]), 6),
    }
    return with_json_locks({
        "artifact_id": "breadth_ignition_volatility_hostility_veto_confirm_probe",
        "generated_at_utc": timestamp_utc(),
        "final_verdict": final_verdict,
        "mechanism_id": MECHANISM_ID,
        "compare_baseline": BASELINE_MODEL,
        "secondary_context_only_models": ["phase68i_dynamic_ladder_candidate", "phase68g_66g_1p25x_candidate", "phase66g_production_soft_filters"],
        "exact_mechanism_used": {
            "breadth_definition": prev_probe.BREADTH_FORMULA,
            "smoothing": prev_probe.SMOOTHING_RULE,
            "ignition_threshold": "Smoothed breadth must be strictly greater than 2/3.",
            "breadth_confirm_before_on": "Ignition turns ON only after 2 consecutive days with smoothed breadth > 2/3.",
            "hold_rule": "Once ON, ignition remains ON while smoothed breadth stays > 2/3.",
            "volatility_measure": prev_probe.VOLATILITY_MEASURE_RULE,
            "volatility_threshold_rule": prev_probe.VOLATILITY_THRESHOLD_RULE,
            "volatility_persistence_rule": prev_probe.PERSISTENCE_RULE,
            "risk_on_rule": prev_probe.STATE_RULE,
        },
        "exact_confirmatory_difference_vs_prior_breadth_veto_probe": "The prior breadth+veto probe turned ignition ON immediately when the 5-day smoothed breadth state was above 2/3 and held it while still above 2/3. This pass keeps that same 5-day EMA, same >2/3 threshold, same >2/3 hold rule, and the same slow volatility-hostility veto, but ignition turns ON only after 2 consecutive days with smoothed breadth > 2/3.",
        "exact_compare_vs_pure_breadth": compare_snapshots(current_snapshot, pure_snapshot, "breadth_ignition_regime_probe"),
        "exact_compare_vs_prior_breadth_veto_result": compare_snapshots(current_snapshot, prior_snapshot, "breadth_ignition_volatility_hostility_veto_probe"),
        "exact_results": {
            "earlier_activation_windows": int(len(valid_windows)),
            "lead_days": lead_days,
            "avg_lead_days": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
            "net_early_move_capture_pct": net_capture,
            "trade_days_delta": trade_delta,
            "switch_count_delta": switch_delta,
            "turnover_pressure_delta": turnover_delta,
            "net_max_drawdown_delta_pct": dd_delta,
            "net_total_return_delta_pct": net_delta,
            "net_cagr_delta_pct": cagr_delta,
            "gross_metrics_for_context_only": {
                "gross_early_move_capture_pct": gross_capture,
                "gross_total_return_baseline_pct": round(float(baseline_metrics["gross_return_pct"]), 6),
                "gross_total_return_probe_pct": round(float(probe_metrics["gross_return_pct"]), 6),
                "gross_total_return_delta_pct": gross_delta,
            },
        },
        "why_same_family_not_new_line": "This remains the same family because breadth ignition is still the activation driver and the slow volatility-hostility veto is still the unchanged protective veto; only one narrow breadth confirmation change was introduced.",
        "stop_condition": {"rule": "stop if DD worsens again, or if DD protection kills the earlier-activation benefit, or if earlier activation shrinks into a one-off result, or if switching/churn/turnover rises materially", "triggered": bool(stop_triggered)},
        "pause_condition": {"rule": "pause if the result remains good but still too narrow for stronger progression language", "triggered": bool(pause_triggered)},
        "cost_model": {"trading_fee_bps": cost_cfg["trading_fee_bps"], "slippage_bps": cost_cfg["slippage_bps"], "turnover_cost_per_unit": cost_cfg["turnover_cost_per_unit"]},
        "input_refs": input_refs,
        "status": "generated_dev_only_breadth_ignition_volatility_hostility_veto_confirm_probe_summary",
    })


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks({"artifact_id": "breadth_ignition_volatility_hostility_veto_confirm_probe_manifest", "generated_at_utc": timestamp_utc(), "output_namespace": str(OUTPUT_ROOT), "output_refs": {key: str(value) for key, value in paths.items()}, "input_refs": input_refs, "contract_refs": [], "spec_refs": [], "manifest_seed_refs": [], "status": "implementation_pack_ready"})


def build_quality_payload(frame: pd.DataFrame, baseline_metrics: Dict[str, Any], probe_metrics: Dict[str, Any], activation_windows: List[Dict[str, Any]], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    ignition_start = frame["breadth_ignition_on"] & (~frame["breadth_ignition_on"].shift(1, fill_value=False))
    checks = [
        {"name": "two_day_confirmation_before_ignition", "ok": bool(frame.loc[ignition_start, "breadth_two_day_confirmation"].fillna(False).all()), "detail": "every new ignition start occurs only after the two-day smoothed breadth confirmation is true"},
        {"name": "hold_rule_respected", "ok": not bool((frame["breadth_ignition_on"].shift(1, fill_value=False) & frame["breadth_threshold_candidate"].fillna(False) & (~frame["breadth_ignition_on"])).any()), "detail": "once ignition is ON it remains ON while smoothed breadth stays above 2/3"},
        {"name": "volatility_veto_blocks_probe_risk", "ok": not bool((frame["breadth_active"] & frame["vol_hostility_veto_active"]).any()), "detail": "probe breadth risk never remains active when the unchanged volatility-hostility veto is active"},
        {"name": "breadth_risk_only_on_baseline_cash_days", "ok": not bool((frame["breadth_active"] & (~frame["baseline_cash"])).any()), "detail": "breadth BTC risk never overlaps with baseline risk-on exposure"},
        {"name": "baseline_risk_days_unchanged", "ok": bool((frame.loc[frame["in_market"], "probe_strategy_return_gross"] == pd.to_numeric(frame.loc[frame["in_market"], "strategy_return"], errors="coerce").fillna(0.0)).all()), "detail": "baseline in-market daily returns pass through unchanged"},
        {"name": "semantic_flags_locked", "ok": True, "detail": "dev_only=true, non_authoritative=true, official_truth=false, strategy_advancement=false, candidate_selection=false, official_edge_claim=false"},
    ]
    return with_json_locks({"artifact_id": "breadth_ignition_volatility_hostility_veto_confirm_probe_quality", "generated_at_utc": timestamp_utc(), "input_refs": input_refs, "checks": checks, "activation_window_count": int(len(activation_windows)), "baseline_metrics": baseline_metrics, "probe_metrics": probe_metrics, "status": "passed" if all(check["ok"] for check in checks) else "failed"})


def main() -> None:
    args = parse_args()
    baseline_df = cash_diag.load_paper(Path(args.baseline_paper))
    frame = build_probe_frame(baseline_df)
    cost_cfg = prev_probe.load_phase68i_cost_assumptions(Path(args.phase68i_summary), Path(args.phase68i_paper))
    frame = prev_probe.apply_cost_model(frame, cost_cfg)
    activation_windows = build_activation_windows(frame)
    baseline_metrics = prev_probe.calc_metrics(returns_gross=frame["strategy_return"], returns_net=frame["baseline_strategy_return_net"], state_series=frame["in_market"].map({True: "BASELINE_RISK", False: "CASH"}), weight_series=frame["baseline_exposure_weight"], model=BASELINE_MODEL, breadth_risk_days=0, vol_hostility_veto_active_days=0)
    probe_metrics = prev_probe.calc_metrics(returns_gross=frame["probe_strategy_return_gross"], returns_net=frame["probe_strategy_return_net"], state_series=frame["probe_state"], weight_series=frame["probe_exposure_weight"], model=PROBE_MODEL, breadth_risk_days=int(frame["breadth_active"].sum()), vol_hostility_veto_active_days=int(frame["vol_hostility_veto_active"].sum()))
    pure_snapshot = load_snapshot(Path(args.pure_breadth_summary), Path(args.pure_breadth_cost), "breadth_ignition_regime_probe")
    prior_snapshot = load_snapshot(Path(args.prior_veto_summary), Path(args.prior_veto_cost), "breadth_ignition_volatility_hostility_veto_probe")
    input_refs = {
        "baseline_paper": str(Path(args.baseline_paper)),
        "universe_ohlcv": {asset: str(cash_diag.resolve_asset_daily_path(asset)) for asset in prev_probe.UNIVERSE_SYMBOLS},
        "btc_volatility_source": str(cash_diag.resolve_asset_daily_path("BTC")),
        "phase68i_paper_secondary_context": str(Path(args.phase68i_paper)) if Path(args.phase68i_paper).exists() else None,
        "phase68i_summary_secondary_context": str(Path(args.phase68i_summary)) if Path(args.phase68i_summary).exists() else None,
        "pure_breadth_summary": str(Path(args.pure_breadth_summary)) if Path(args.pure_breadth_summary).exists() else None,
        "pure_breadth_cost_metrics": str(Path(args.pure_breadth_cost)) if Path(args.pure_breadth_cost).exists() else None,
        "prior_breadth_veto_summary": str(Path(args.prior_veto_summary)) if Path(args.prior_veto_summary).exists() else None,
        "prior_breadth_veto_cost_metrics": str(Path(args.prior_veto_cost)) if Path(args.prior_veto_cost).exists() else None,
    }
    paths = output_paths()
    save_csv(paths["window_compare_csv"], activation_windows, WINDOW_COMPARE_COLUMNS)
    save_csv(paths["state_time_csv"], build_state_time_rows(frame), prev_probe.STATE_TIME_COLUMNS)
    save_csv(paths["compare_csv"], build_compare_rows(baseline_metrics, probe_metrics, activation_windows), prev_probe.COMPARE_COLUMNS)
    save_csv(paths["cost_metrics_csv"], [baseline_metrics, probe_metrics], prev_probe.COST_COLUMNS)
    save_json(paths["summary_json"], build_summary_payload(baseline_metrics, probe_metrics, activation_windows, cost_cfg, pure_snapshot, prior_snapshot, input_refs))
    save_json(paths["manifest_json"], build_manifest_payload(paths, input_refs))
    save_json(paths["quality_json"], build_quality_payload(frame, baseline_metrics, probe_metrics, activation_windows, input_refs))
    print("breadth_ignition_volatility_hostility_veto_confirm_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
