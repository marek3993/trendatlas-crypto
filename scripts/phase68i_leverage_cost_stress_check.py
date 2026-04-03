from __future__ import annotations

import argparse
import json
print("[PHASE68I] file loaded", flush=True)
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

import phase68h_dynamic_leverage_ladder_candidate as core68h


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

PHASE66G_DIR = OUTPUTS / "phase66g_production_candidate_live"
DEFAULT_GOVERNANCE_PAPER = PHASE66G_DIR / "phase66g_production_soft_filters_paper.csv"
DEFAULT_TREND = PHASE66G_DIR / "phase66g_trend_barometer_history.csv"
DEFAULT_DECISIONS = PHASE66G_DIR / "phase66g_production_candidate_decisions.csv"

PHASE68I_DIR = OUTPUTS / "phase68i_leverage_cost_stress_check"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    annual_borrow_cost: float
    tradable_transition_slippage_bps: float


@dataclass(frozen=True)
class Variant:
    model: str
    mode: str
    target_leverage: float


SCENARIOS: list[Scenario] = [
    Scenario("bc12_sl10", 0.12, 10.0),
    Scenario("bc12_sl20", 0.12, 20.0),
    Scenario("bc12_sl30", 0.12, 30.0),
    Scenario("bc18_sl10", 0.18, 10.0),
    Scenario("bc18_sl20", 0.18, 20.0),
    Scenario("bc18_sl30", 0.18, 30.0),
    Scenario("bc24_sl10", 0.24, 10.0),
    Scenario("bc24_sl20", 0.24, 20.0),
    Scenario("bc24_sl30", 0.24, 30.0),
]

VARIANTS: list[Variant] = [
    Variant("phase68i_66g_1p00x_baseline", "static", 1.00),
    Variant("phase68i_66g_1p25x_static", "static", 1.25),
    Variant("phase68i_66g_1p50x_static", "static", 1.50),
    Variant("phase68i_dynamic_ladder_candidate", "dynamic", 0.0),
]

DYNAMIC_PARAMS = {
    "trend_activation_threshold": 0.10,
    "dynamic_mid_threshold": 0.50,
    "dynamic_mid_leverage": 1.25,
    "dynamic_high_leverage": 1.50,
    "stress_lookback_days": 20,
    "stress_off_threshold": -0.08,
    "stress_on_threshold": -0.04,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def add_scenario_deltas(group_df: pd.DataFrame) -> pd.DataFrame:
    out = group_df.copy()
    base = out.loc[out["model"] == "phase68i_66g_1p00x_baseline"]
    if base.empty:
        raise ValueError(f"Scenario {out['scenario_id'].iloc[0]} nemá baseline row.")
    ref = base.iloc[0].to_dict()

    rows = []
    for _, row in out.iterrows():
        row_dict = row.to_dict()
        for metric in [
            "cagr_pct",
            "max_drawdown_pct",
            "calmar",
            "since2023_cagr_pct",
            "since2025_cagr_pct",
            "worst_day_pct",
            "borrow_cost_total_pct",
            "tradable_slippage_cost_total_pct",
        ]:
            row_dict[f"delta_vs_1p00x_{metric}"] = (
                pd.to_numeric(row_dict.get(metric), errors="coerce")
                - pd.to_numeric(ref.get(metric), errors="coerce")
            )
        rows.append(row_dict)
    return pd.DataFrame(rows)


def pick_scenario_raw_winner(group_df: pd.DataFrame) -> str:
    cand = group_df.loc[group_df["model"] != "phase68i_66g_1p00x_baseline"].copy()
    cand = cand.sort_values(
        by=["cagr_pct", "since2025_cagr_pct", "calmar", "max_drawdown_pct"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    return str(cand.iloc[0]["model"])


def pick_scenario_deployment_winner(group_df: pd.DataFrame) -> str:
    cand = group_df.loc[group_df["model"] != "phase68i_66g_1p00x_baseline"].copy()
    cand = cand.sort_values(
        by=["calmar", "since2025_cagr_pct", "max_drawdown_pct", "cagr_pct"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    return str(cand.iloc[0]["model"])


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE68I leverage cost/stress check")
    parser.add_argument("--governance-paper", type=str, default=str(DEFAULT_GOVERNANCE_PAPER))
    parser.add_argument("--baseline-paper", type=str, default="")
    parser.add_argument("--trend-history", type=str, default=str(DEFAULT_TREND))
    parser.add_argument("--decisions", type=str, default=str(DEFAULT_DECISIONS))
    args = parser.parse_args()

    core68h.ensure_dir(PHASE68I_DIR)
    papers_dir = PHASE68I_DIR / "papers"
    core68h.ensure_dir(papers_dir)

    governance_paper_path = Path(args.governance_paper)
    baseline_paper_path = Path(args.baseline_paper) if args.baseline_paper else core68h.find_baseline_paper_in_phase66g_dir()
    trend_path = Path(args.trend_history)
    decisions_path = Path(args.decisions)

    if not governance_paper_path.exists():
        raise FileNotFoundError(f"Governance paper sa nenašiel: {governance_paper_path}")
    if not baseline_paper_path.exists():
        raise FileNotFoundError(f"Baseline paper sa nenašiel: {baseline_paper_path}")
    if not trend_path.exists():
        raise FileNotFoundError(f"Trend history sa nenašiel: {trend_path}")
    if not decisions_path.exists():
        raise FileNotFoundError(f"Decisions file sa nenašiel: {decisions_path}")

    log("[PHASE68I] Start")
    log(f"[PHASE68I] Governance paper: {governance_paper_path}")
    log(f"[PHASE68I] Baseline paper: {baseline_paper_path}")
    log(f"[PHASE68I] Trend history: {trend_path}")
    log(f"[PHASE68I] Decisions: {decisions_path}")

    governance_df = core68h.load_governance_paper(governance_paper_path)
    baseline_df = core68h.load_baseline_paper(baseline_paper_path)
    portfolio_df = core68h.build_portfolio_exposure_frame(governance_df, baseline_df)
    trend_df = core68h.load_trend_history(trend_path)
    decisions_df = core68h.load_governance_decisions(decisions_path)

    tradable_transition_df, governance_switch_count, mapping_meta = core68h.build_governance_transition_calendar(
        decisions_df=decisions_df,
        paper_dates=portfolio_df["date"],
    )
    tradable_transition_count = int(len(tradable_transition_df))

    transition_calendar_path = PHASE68I_DIR / "phase68i_tradable_transition_calendar.csv"
    tradable_transition_df.to_csv(transition_calendar_path, index=False)

    summary_rows: list[dict] = []

    for scenario in SCENARIOS:
        scenario_dir = papers_dir / scenario.scenario_id
        core68h.ensure_dir(scenario_dir)

        log(
            f"[PHASE68I] scenario {scenario.scenario_id} | "
            f"borrow={scenario.annual_borrow_cost:.2%} slippage={scenario.tradable_transition_slippage_bps:.0f}bps"
        )

        for variant in VARIANTS:
            wrapped = core68h.build_validation_wrapper(
                portfolio_df=portfolio_df,
                trend_df=trend_df,
                tradable_transition_df=tradable_transition_df,
                variant=variant,
                annual_borrow_cost=float(scenario.annual_borrow_cost),
                tradable_transition_slippage_bps=float(scenario.tradable_transition_slippage_bps),
                trend_activation_threshold=float(DYNAMIC_PARAMS["trend_activation_threshold"]),
                stress_lookback_days=int(DYNAMIC_PARAMS["stress_lookback_days"]),
                stress_off_threshold=float(DYNAMIC_PARAMS["stress_off_threshold"]),
                stress_on_threshold=float(DYNAMIC_PARAMS["stress_on_threshold"]),
                dynamic_mid_threshold=float(DYNAMIC_PARAMS["dynamic_mid_threshold"]),
                dynamic_mid_leverage=float(DYNAMIC_PARAMS["dynamic_mid_leverage"]),
                dynamic_high_leverage=float(DYNAMIC_PARAMS["dynamic_high_leverage"]),
            )

            row = core68h.summarize_variant(
                model=variant.model,
                df=wrapped,
                annual_borrow_cost=float(scenario.annual_borrow_cost),
                governance_switch_count=int(governance_switch_count),
                tradable_transition_count=int(tradable_transition_count),
            )
            row["scenario_id"] = scenario.scenario_id
            row["scenario_borrow_cost_pct"] = float(scenario.annual_borrow_cost * 100.0)
            row["scenario_slippage_bps"] = float(scenario.tradable_transition_slippage_bps)
            summary_rows.append(row)

            wrapped.to_csv(scenario_dir / f"{variant.model}_paper.csv", index=False)

    summary_df = pd.DataFrame(summary_rows)

    compare_parts = []
    winner_rows = []

    for scenario_id, group in summary_df.groupby("scenario_id", sort=False):
        comp = add_scenario_deltas(group)
        raw_winner = pick_scenario_raw_winner(comp)
        deployment_winner = pick_scenario_deployment_winner(comp)

        comp["is_scenario_raw_winner"] = comp["model"].astype(str) == raw_winner
        comp["is_scenario_deployment_winner"] = comp["model"].astype(str) == deployment_winner
        compare_parts.append(comp)

        winner_rows.append(
            {
                "scenario_id": scenario_id,
                "borrow_cost_pct": float(group["scenario_borrow_cost_pct"].iloc[0]),
                "slippage_bps": float(group["scenario_slippage_bps"].iloc[0]),
                "raw_winner_model": raw_winner,
                "deployment_winner_model": deployment_winner,
            }
        )

    compare_df = pd.concat(compare_parts, ignore_index=True)
    winners_df = pd.DataFrame(winner_rows)

    compare_df = compare_df.sort_values(
        by=["scenario_borrow_cost_pct", "scenario_slippage_bps", "model"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    raw_counts = winners_df["raw_winner_model"].value_counts().to_dict()
    deploy_counts = winners_df["deployment_winner_model"].value_counts().to_dict()

    global_candidates = compare_df.loc[compare_df["model"] != "phase68i_66g_1p00x_baseline"].copy()

    global_raw_top = global_candidates.sort_values(
        by=["cagr_pct", "since2025_cagr_pct", "calmar", "max_drawdown_pct"],
        ascending=[False, False, False, False],
        na_position="last",
    ).iloc[0].to_dict()

    global_deploy_top = global_candidates.sort_values(
        by=["calmar", "since2025_cagr_pct", "max_drawdown_pct", "cagr_pct"],
        ascending=[False, False, False, False],
        na_position="last",
    ).iloc[0].to_dict()

    summary_path = PHASE68I_DIR / "phase68i_leverage_cost_stress_summary.csv"
    compare_path = PHASE68I_DIR / "phase68i_leverage_cost_stress_compare.csv"
    winners_path = PHASE68I_DIR / "phase68i_leverage_cost_stress_winners.csv"
    manifest_path = PHASE68I_DIR / "phase68i_leverage_cost_stress_manifest.json"

    summary_df.to_csv(summary_path, index=False)
    compare_df.to_csv(compare_path, index=False)
    winners_df.to_csv(winners_path, index=False)

    manifest = {
        "phase": "phase68i_leverage_cost_stress_check",
        "official_compare_baseline": "phase68i_66g_1p00x_baseline",
        "governance_paper": str(governance_paper_path),
        "baseline_paper": str(baseline_paper_path),
        "trend_history": str(trend_path),
        "decisions_file": str(decisions_path),
        "transition_mapping_meta": mapping_meta,
        "governance_switch_count": int(governance_switch_count),
        "tradable_transition_count": int(tradable_transition_count),
        "transition_calendar_file": str(transition_calendar_path),
        "dynamic_params": DYNAMIC_PARAMS,
        "scenarios": [asdict(s) for s in SCENARIOS],
        "variants": [asdict(v) for v in VARIANTS],
        "raw_winner_counts": raw_counts,
        "deployment_winner_counts": deploy_counts,
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "winners_file": str(winners_path),
        "papers_dir": str(papers_dir),
        "notes": [
            "Cost/stress check len pre 1.25x static, 1.50x static, dynamic ladder.",
            "Borrow cost stress: 12 / 18 / 24%.",
            "Tradable slippage stress: 10 / 20 / 30 bps.",
            "Exposure basis, slippage basis a mapping ostávajú rovnaké ako clean 68G/68H.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE68I GLOBAL RAW TOP ===")
    log(f"scenario_id: {global_raw_top['scenario_id']}")
    log(f"model: {global_raw_top['model']}")
    log(f"cagr_pct: {float(global_raw_top['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(global_raw_top['max_drawdown_pct']):.2f}")
    log(f"calmar: {float(global_raw_top['calmar']):.4f}")
    log(f"since2025_cagr_pct: {float(global_raw_top['since2025_cagr_pct']):.2f}")
    log(f"borrow_cost_pct: {float(global_raw_top['scenario_borrow_cost_pct']):.2f}")
    log(f"slippage_bps: {float(global_raw_top['scenario_slippage_bps']):.0f}")
    log("")

    log("=== PHASE68I GLOBAL DEPLOYMENT TOP ===")
    log(f"scenario_id: {global_deploy_top['scenario_id']}")
    log(f"model: {global_deploy_top['model']}")
    log(f"cagr_pct: {float(global_deploy_top['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(global_deploy_top['max_drawdown_pct']):.2f}")
    log(f"calmar: {float(global_deploy_top['calmar']):.4f}")
    log(f"since2025_cagr_pct: {float(global_deploy_top['since2025_cagr_pct']):.2f}")
    log(f"borrow_cost_pct: {float(global_deploy_top['scenario_borrow_cost_pct']):.2f}")
    log(f"slippage_bps: {float(global_deploy_top['scenario_slippage_bps']):.0f}")
    log("")

    log(f"[PHASE68I] raw winner counts: {raw_counts}")
    log(f"[PHASE68I] deployment winner counts: {deploy_counts}")
    log(f"[PHASE68I] Saved summary -> {summary_path}")
    log(f"[PHASE68I] Saved compare -> {compare_path}")
    log(f"[PHASE68I] Saved winners -> {winners_path}")
    log(f"[PHASE68I] Saved manifest -> {manifest_path}")
    log(f"[PHASE68I] Saved transition calendar -> {transition_calendar_path}")
    log(f"[PHASE68I] Saved papers -> {papers_dir}")


if __name__ == "__main__":
    main()