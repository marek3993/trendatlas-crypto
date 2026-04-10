from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

import dev_only_cash_overstay_diagnostic as cash_diag
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_constructive_pilot_probe"

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "constructive_regime_pilot_exposure_persistence_probe"
MECHANISM_ID = "constructive_regime_pilot_exposure_persistence"

BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
PHASE68I_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"

PILOT_WEIGHT = 0.25
JSON_LOCKS = {
    "analysis_mode": "constructive_pilot_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}
WHY_DIFFERENT = "phase68k/phase68l/phase68m primarily tested earlier or softer entry permission. This probe instead tests exposure persistence inside already-confirmed constructive windows by replacing binary cash fallback with a deterministic pilot exposure state."
STOP_CONDITION = "if constructive-window participation does not improve materially or if missed benchmark return while underexposed does not shrink materially or if gains come only from one isolated window or if probe implicitly becomes broad entry softening"
PAUSE_CONDITION = "if results are mixed across windows or if improvement depends on one narrow episode or if persistence logic causes obvious drift away from mechanism-first scope"

WINDOW_COMPARE_COLUMNS = [
    "window_id",
    "window_start",
    "window_end",
    "window_length_days",
    "benchmark_return_during_window",
    "baseline_return_during_window",
    "probe_return_during_window",
    "baseline_time_in_market_share",
    "probe_time_in_market_share",
    "baseline_cash_share",
    "probe_cash_share",
    "baseline_underexposed_days_count",
    "probe_underexposed_days_count",
    "baseline_missed_benchmark_return_while_underexposed",
    "probe_missed_benchmark_return_while_underexposed",
    "baseline_gap_label",
    "probe_gap_label",
    "pilot_days_in_window",
]

COMPARE_COLUMNS = [
    "metric",
    "baseline_model",
    "baseline_value",
    "probe_model",
    "probe_value",
    "delta_probe_minus_baseline",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Constructive pilot exposure persistence probe")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--phase68i-paper", type=str, default=str(PHASE68I_PAPER_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    return {
        "summary_json": OUTPUT_ROOT / "constructive_pilot_probe.summary.json",
        "window_compare_csv": OUTPUT_ROOT / "constructive_pilot_probe.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / "constructive_pilot_probe.state_time.csv",
        "compare_csv": OUTPUT_ROOT / "constructive_pilot_probe.compare.csv",
        "manifest_json": OUTPUT_ROOT / "constructive_pilot_probe.manifest.json",
        "quality_json": OUTPUT_ROOT / "constructive_pilot_probe.quality.json",
    }


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if years <= 0 or total_return <= -1.0:
        return 0.0 if years <= 0 else -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def max_drawdown_from_returns(returns: pd.Series) -> float:
    equity = (1.0 + pd.to_numeric(returns, errors="coerce").fillna(0.0)).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min()) if len(drawdown) else 0.0


def calmar_ratio(cagr_pct: float, max_drawdown_pct: float) -> float:
    if max_drawdown_pct == 0:
        return 0.0
    return float(cagr_pct / abs(max_drawdown_pct))


def calc_metrics(returns: pd.Series, model_name: str) -> Dict[str, Any]:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    equity = (1.0 + clean).cumprod()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) > 1 else 0.0
    cagr = annualize_return(total_return, len(clean))
    max_dd = max_drawdown_from_returns(clean)
    return {
        "model": model_name,
        "cagr_pct": round(cagr * 100.0, 6),
        "max_drawdown_pct": round(max_dd * 100.0, 6),
        "calmar": round(calmar_ratio(cagr * 100.0, max_dd * 100.0), 6),
    }


def mark_constructive_windows(frame: pd.DataFrame, windows: List[tuple[pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    out = frame.copy()
    out["constructive_window_active"] = False
    out["constructive_window_id"] = ""
    for idx, (start_date, end_date) in enumerate(windows, start=1):
        mask = (out.index >= start_date) & (out.index <= end_date)
        out.loc[mask, "constructive_window_active"] = True
        out.loc[mask, "constructive_window_id"] = f"window_{idx:03d}"
    return out


def build_probe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["pilot_active"] = out["constructive_window_active"] & (~out["in_market"])
    out["probe_state"] = "CASH"
    out.loc[out["in_market"], "probe_state"] = "FULL_RISK"
    out.loc[out["pilot_active"], "probe_state"] = "PILOT_RISK"
    out["probe_in_market"] = out["probe_state"].ne("CASH")
    out["pilot_return"] = pd.to_numeric(out["benchmark_return"], errors="coerce").fillna(0.0) * PILOT_WEIGHT
    out["probe_strategy_return"] = pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)
    out.loc[out["pilot_active"], "probe_strategy_return"] = out.loc[out["pilot_active"], "pilot_return"]
    return out


def classify_probe_gap(window_df: pd.DataFrame) -> Dict[str, Any]:
    temp = window_df.copy()
    temp["in_market"] = temp["probe_in_market"]
    temp["strategy_return"] = temp["probe_strategy_return"]
    return cash_diag.classify_exposure_gap(temp)


def build_window_compare(frame: pd.DataFrame, windows: List[tuple[pd.Timestamp, pd.Timestamp]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, (start_date, end_date) in enumerate(windows, start=1):
        window_id = f"window_{idx:03d}"
        window_df = frame.loc[start_date:end_date].copy()
        baseline_gap = cash_diag.classify_exposure_gap(window_df)
        probe_gap = classify_probe_gap(window_df)
        rows.append(
            {
                "window_id": window_id,
                "window_start": start_date.strftime("%Y-%m-%d"),
                "window_end": end_date.strftime("%Y-%m-%d"),
                "window_length_days": int(len(window_df)),
                "benchmark_return_during_window": round(cash_diag.compound_return(window_df["benchmark_return"]), 6),
                "baseline_return_during_window": round(cash_diag.compound_return(window_df["strategy_return"]), 6),
                "probe_return_during_window": round(cash_diag.compound_return(window_df["probe_strategy_return"]), 6),
                "baseline_time_in_market_share": round(float(window_df["in_market"].mean()), 6),
                "probe_time_in_market_share": round(float(window_df["probe_in_market"].mean()), 6),
                "baseline_cash_share": round(float((~window_df["in_market"]).mean()), 6),
                "probe_cash_share": round(float((~window_df["probe_in_market"]).mean()), 6),
                "baseline_underexposed_days_count": int(baseline_gap["underexposed_days_count"]),
                "probe_underexposed_days_count": int(probe_gap["underexposed_days_count"]),
                "baseline_missed_benchmark_return_while_underexposed": float(baseline_gap["missed_benchmark_return_while_cash"]),
                "probe_missed_benchmark_return_while_underexposed": float(probe_gap["missed_benchmark_return_while_cash"]),
                "baseline_gap_label": str(baseline_gap["exposure_gap_label"]),
                "probe_gap_label": str(probe_gap["exposure_gap_label"]),
                "pilot_days_in_window": int(window_df["pilot_active"].sum()),
            }
        )
    return rows


def build_state_time_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    total_days = int(len(frame))
    constructive_days = int(frame["constructive_window_active"].sum())
    specs = [
        (BASELINE_MODEL, "FULL_RISK", int(frame["in_market"].sum()), int((frame["in_market"] & frame["constructive_window_active"]).sum())),
        (BASELINE_MODEL, "CASH", int((~frame["in_market"]).sum()), int(((~frame["in_market"]) & frame["constructive_window_active"]).sum())),
        (PROBE_MODEL, "FULL_RISK", int(frame["probe_state"].eq("FULL_RISK").sum()), int(((frame["probe_state"].eq("FULL_RISK")) & frame["constructive_window_active"]).sum())),
        (PROBE_MODEL, "PILOT_RISK", int(frame["probe_state"].eq("PILOT_RISK").sum()), int(((frame["probe_state"].eq("PILOT_RISK")) & frame["constructive_window_active"]).sum())),
        (PROBE_MODEL, "CASH", int(frame["probe_state"].eq("CASH").sum()), int(((frame["probe_state"].eq("CASH")) & frame["constructive_window_active"]).sum())),
    ]
    for model, state, days, constructive_state_days in specs:
        rows.append(
            {
                "model": model,
                "state": state,
                "days": days,
                "share_of_total_days": round(days / total_days, 6) if total_days else 0.0,
                "constructive_window_days": constructive_state_days,
                "share_of_constructive_window_days": round(constructive_state_days / constructive_days, 6) if constructive_days else 0.0,
            }
        )
    return rows


def build_compare_rows(summary_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    metric_pairs = [
        ("cagr_pct", summary_metrics["baseline_metrics"]["cagr_pct"], summary_metrics["probe_metrics"]["cagr_pct"]),
        ("max_drawdown_pct", summary_metrics["baseline_metrics"]["max_drawdown_pct"], summary_metrics["probe_metrics"]["max_drawdown_pct"]),
        ("calmar", summary_metrics["baseline_metrics"]["calmar"], summary_metrics["probe_metrics"]["calmar"]),
        ("constructive_windows_count", summary_metrics["constructive_windows_count"], summary_metrics["constructive_windows_count"]),
        ("material_gap_windows", summary_metrics["baseline_material_gap_windows"], summary_metrics["probe_material_gap_windows"]),
        ("time_in_market_share_in_constructive_windows", summary_metrics["baseline_time_in_market_share_in_constructive_windows"], summary_metrics["probe_time_in_market_share_in_constructive_windows"]),
        ("cash_share_in_constructive_windows", summary_metrics["baseline_cash_share_in_constructive_windows"], summary_metrics["probe_cash_share_in_constructive_windows"]),
        ("missed_benchmark_return_while_underexposed", summary_metrics["baseline_missed_benchmark_return_while_underexposed"], summary_metrics["probe_missed_benchmark_return_while_underexposed"]),
        ("pilot_risk_days", 0.0, summary_metrics["pilot_risk_days"]),
    ]
    rows: List[Dict[str, Any]] = []
    for metric, baseline_value, probe_value in metric_pairs:
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


def build_summary_metrics(frame: pd.DataFrame, window_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    constructive_mask = frame["constructive_window_active"]
    constructive_days = int(constructive_mask.sum())
    baseline_time_share = float(frame.loc[constructive_mask, "in_market"].mean()) if constructive_days else 0.0
    probe_time_share = float(frame.loc[constructive_mask, "probe_in_market"].mean()) if constructive_days else 0.0
    baseline_cash_share = float((~frame.loc[constructive_mask, "in_market"]).mean()) if constructive_days else 0.0
    probe_cash_share = float((~frame.loc[constructive_mask, "probe_in_market"]).mean()) if constructive_days else 0.0
    baseline_missed = sum(float(row["baseline_missed_benchmark_return_while_underexposed"]) for row in window_rows)
    probe_missed = sum(float(row["probe_missed_benchmark_return_while_underexposed"]) for row in window_rows)
    baseline_material = sum(row["baseline_gap_label"] != "no_material_gap" for row in window_rows)
    probe_material = sum(row["probe_gap_label"] != "no_material_gap" for row in window_rows)
    baseline_metrics = calc_metrics(frame["strategy_return"], BASELINE_MODEL)
    probe_metrics = calc_metrics(frame["probe_strategy_return"], PROBE_MODEL)

    participation_improvements = [
        max(0.0, float(row["probe_time_in_market_share"]) - float(row["baseline_time_in_market_share"]))
        for row in window_rows
    ]
    missed_reductions = [
        max(0.0, float(row["baseline_missed_benchmark_return_while_underexposed"]) - float(row["probe_missed_benchmark_return_while_underexposed"]))
        for row in window_rows
    ]
    total_window_signal = sum(participation_improvements) + sum(missed_reductions)
    top_window_signal = max(
        [participation_improvements[idx] + missed_reductions[idx] for idx in range(len(window_rows))],
        default=0.0,
    )
    isolated_window_flag = total_window_signal > 0 and (top_window_signal / total_window_signal) > 0.70
    improved_windows = sum(
        (participation_improvements[idx] > 0.01) or (missed_reductions[idx] > 0.01) for idx in range(len(window_rows))
    )
    worsened_windows = sum(
        (float(row["probe_return_during_window"]) < float(row["baseline_return_during_window"]) - 0.01) for row in window_rows
    )
    mixed_windows_flag = improved_windows > 0 and worsened_windows > 0
    broad_entry_softening_flag = bool((frame["pilot_active"] & (~frame["constructive_window_active"])).any())

    participation_delta = probe_time_share - baseline_time_share
    missed_delta = baseline_missed - probe_missed
    material_participation_improvement = participation_delta >= 0.05
    material_missed_shrink = missed_delta >= 0.05
    risk_drift_flag = probe_metrics["max_drawdown_pct"] < (baseline_metrics["max_drawdown_pct"] - 1.0)

    if (not material_participation_improvement) or (not material_missed_shrink) or isolated_window_flag or broad_entry_softening_flag:
        final_verdict = "stop_not_confirmed"
    elif mixed_windows_flag or risk_drift_flag:
        final_verdict = "mixed_pause_recommended"
    else:
        final_verdict = "meaningful_non_authoritative_signal"

    return {
        "constructive_windows_count": int(len(window_rows)),
        "baseline_material_gap_windows": int(baseline_material),
        "probe_material_gap_windows": int(probe_material),
        "baseline_time_in_market_share_in_constructive_windows": round(baseline_time_share, 6),
        "probe_time_in_market_share_in_constructive_windows": round(probe_time_share, 6),
        "baseline_cash_share_in_constructive_windows": round(baseline_cash_share, 6),
        "probe_cash_share_in_constructive_windows": round(probe_cash_share, 6),
        "baseline_missed_benchmark_return_while_underexposed": round(baseline_missed, 6),
        "probe_missed_benchmark_return_while_underexposed": round(probe_missed, 6),
        "pilot_risk_days": int(frame["probe_state"].eq("PILOT_RISK").sum()),
        "baseline_metrics": baseline_metrics,
        "probe_metrics": probe_metrics,
        "final_verdict": final_verdict,
        "stop_triggered": (not material_participation_improvement) or (not material_missed_shrink) or isolated_window_flag or broad_entry_softening_flag,
        "pause_triggered": mixed_windows_flag or isolated_window_flag or risk_drift_flag,
        "improved_windows": int(improved_windows),
        "worsened_windows": int(worsened_windows),
        "isolated_window_flag": bool(isolated_window_flag),
        "broad_entry_softening_flag": bool(broad_entry_softening_flag),
        "risk_drift_flag": bool(risk_drift_flag),
    }


def build_summary_payload(summary_metrics: Dict[str, Any], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": "constructive_pilot_probe",
            "generated_at_utc": timestamp_utc(),
            "final_verdict": summary_metrics["final_verdict"],
            "mechanism_id": MECHANISM_ID,
            "compare_baseline": BASELINE_MODEL,
            "constructive_windows_count": summary_metrics["constructive_windows_count"],
            "baseline_material_gap_windows": summary_metrics["baseline_material_gap_windows"],
            "probe_material_gap_windows": summary_metrics["probe_material_gap_windows"],
            "baseline_time_in_market_share_in_constructive_windows": summary_metrics["baseline_time_in_market_share_in_constructive_windows"],
            "probe_time_in_market_share_in_constructive_windows": summary_metrics["probe_time_in_market_share_in_constructive_windows"],
            "baseline_cash_share_in_constructive_windows": summary_metrics["baseline_cash_share_in_constructive_windows"],
            "probe_cash_share_in_constructive_windows": summary_metrics["probe_cash_share_in_constructive_windows"],
            "baseline_missed_benchmark_return_while_underexposed": summary_metrics["baseline_missed_benchmark_return_while_underexposed"],
            "probe_missed_benchmark_return_while_underexposed": summary_metrics["probe_missed_benchmark_return_while_underexposed"],
            "why_meaningfully_different_from_phase68k_l_m": WHY_DIFFERENT,
            "pilot_exposure_rule": {
                "constructive_regime_rule_reused_from": "scripts/dev_only_cash_overstay_diagnostic.py",
                "pilot_asset": "BTCUSDT",
                "pilot_weight": PILOT_WEIGHT,
                "activation_rule": "When phase67j baseline is in CASH inside an already-confirmed constructive window, replace full CASH with a small BTC pilot state.",
                "persistence_rule": "Pilot stays active on baseline CASH days until the same explicit constructive invalidation rule ends the window.",
                "full_risk_rule": "Baseline full-risk behavior remains unchanged and is not loosened.",
            },
            "stop_condition": {
                "rule": STOP_CONDITION,
                "triggered": summary_metrics["stop_triggered"],
            },
            "pause_condition": {
                "rule": PAUSE_CONDITION,
                "triggered": summary_metrics["pause_triggered"],
            },
            "input_refs": input_refs,
            "descriptive_only": True,
            "status": "generated_dev_only_constructive_pilot_probe_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": "constructive_pilot_probe_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [
                "research_os/dev_only/contracts/dev_only_constructive_pilot_exposure_probe.contract.json"
            ],
            "spec_refs": [
                "research_os/dev_only/specs/dev_only_constructive_pilot_exposure_probe.spec.json"
            ],
            "manifest_seed_refs": [
                "research_os/dev_only/manifests/dev_only_constructive_pilot_exposure_probe.manifest.json"
            ],
            "status": "implementation_pack_ready",
        }
    )


def build_quality_payload(frame: pd.DataFrame, summary_metrics: Dict[str, Any], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    checks = [
        {
            "name": "pilot_only_inside_constructive_windows",
            "ok": not bool((frame["pilot_active"] & (~frame["constructive_window_active"])).any()),
            "detail": "pilot state appears only inside confirmed constructive windows",
        },
        {
            "name": "full_risk_days_unchanged_vs_baseline",
            "ok": bool((frame["probe_state"].eq("FULL_RISK") == frame["in_market"]).all()),
            "detail": "probe FULL_RISK state matches baseline in-market days exactly",
        },
        {
            "name": "compare_baseline_locked",
            "ok": True,
            "detail": f"compare_baseline={BASELINE_MODEL}",
        },
        {
            "name": "no_broad_entry_softening_flag",
            "ok": not summary_metrics["broad_entry_softening_flag"],
            "detail": "pilot activation remains persistence-only rather than a broad earlier entry rule",
        },
    ]
    return with_json_locks(
        {
            "artifact_id": "constructive_pilot_probe_quality",
            "generated_at_utc": timestamp_utc(),
            "input_refs": input_refs,
            "checks": checks,
            "status": "passed" if all(check["ok"] for check in checks) else "failed",
        }
    )


def main() -> None:
    args = parse_args()
    baseline_path = Path(args.baseline_paper)
    phase68i_path = Path(args.phase68i_paper)
    baseline_df = cash_diag.load_paper(baseline_path)
    frame = cash_diag.build_analysis_frame(baseline_df)
    windows = cash_diag.build_constructive_windows(frame)
    frame = mark_constructive_windows(frame, windows)
    frame = build_probe_frame(frame)

    window_rows = build_window_compare(frame, windows)
    summary_metrics = build_summary_metrics(frame, window_rows)
    input_refs = {
        "baseline_paper": str(baseline_path),
        "phase68i_paper_secondary_context": str(phase68i_path) if phase68i_path.exists() else None,
        "cash_diagnostic_summary": str(ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_cash_diagnostics" / "cash_overstay_diagnostic.summary.json"),
        "phase68k_compare": str(ROOT / "outputs" / "phase68k_early_entry_ladder_probe" / "phase68k_early_entry_compare.csv"),
        "phase68l_compare": str(ROOT / "outputs" / "phase68l_early_entry_soft_gate_probe" / "phase68l_early_entry_soft_gate_compare.csv"),
        "phase68m_compare": str(ROOT / "outputs" / "phase68m_early_entry_micro_confirm" / "phase68m_early_entry_micro_confirm_compare.csv"),
    }
    paths = output_paths()

    save_csv(paths["window_compare_csv"], window_rows, WINDOW_COMPARE_COLUMNS)
    save_csv(paths["state_time_csv"], build_state_time_rows(frame), ["model", "state", "days", "share_of_total_days", "constructive_window_days", "share_of_constructive_window_days"])
    save_csv(paths["compare_csv"], build_compare_rows(summary_metrics), COMPARE_COLUMNS)
    save_json(paths["summary_json"], build_summary_payload(summary_metrics, input_refs))
    save_json(paths["manifest_json"], build_manifest_payload(paths, input_refs))
    save_json(paths["quality_json"], build_quality_payload(frame, summary_metrics, input_refs))

    print("constructive_pilot_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
