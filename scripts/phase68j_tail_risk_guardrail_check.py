from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import phase68h_dynamic_leverage_ladder_candidate as core68h


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

PHASE66G_DIR = OUTPUTS / "phase66g_production_candidate_live"
DEFAULT_GOVERNANCE_PAPER = PHASE66G_DIR / "phase66g_production_soft_filters_paper.csv"
DEFAULT_TREND = PHASE66G_DIR / "phase66g_trend_barometer_history.csv"
DEFAULT_DECISIONS = PHASE66G_DIR / "phase66g_production_candidate_decisions.csv"

PHASE68J_DIR = OUTPUTS / "phase68j_tail_risk_guardrail_check"

OFFICIAL_COMPARE_BASELINE = "phase68j_ref_dynamic_ladder"


@dataclass(frozen=True)
class ParentVariant:
    model: str
    mode: str
    target_leverage: float


@dataclass(frozen=True)
class GuardrailSpec:
    guardrail_id: str
    description: str


PARENT_VARIANTS: list[ParentVariant] = [
    ParentVariant("phase68j_ref_1p50x_static", "static", 1.50),
    ParentVariant("phase68j_ref_dynamic_ladder", "dynamic", 0.0),
    ParentVariant("phase68j_ref_1p25x_static", "static", 1.25),
]

GUARDRAILS: list[GuardrailSpec] = [
    GuardrailSpec(
        "g1_adverse_cd2",
        "Ak parent realistic_ret <= -5.0%, ďalšie 2 dni force 1.00x",
    ),
    GuardrailSpec(
        "g2_dd5_cd3",
        "Ak parent rolling 5d DD <= -7.5%, ďalšie 3 dni force 1.00x",
    ),
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

BORROW_COST = 0.12
TRADABLE_SLIPPAGE_BPS = 10.0


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def apply_g1_adverse_cooldown(parent_df: pd.DataFrame) -> pd.DataFrame:
    out = parent_df.copy()
    out["guardrail_trigger_day"] = False
    out["guardrail_forced_1p00"] = False
    out["guardrail_reason"] = ""

    cooldown_days = 2
    trigger_threshold = -0.05
    cooldown_remaining = 0

    parent_ret = pd.to_numeric(out["parent_realistic_ret"], errors="coerce").fillna(0.0).to_numpy()

    for i in range(len(out)):
        if cooldown_remaining > 0:
            out.at[i, "guardrail_forced_1p00"] = True
            out.at[i, "guardrail_reason"] = "g1_adverse_cd2_active"
            cooldown_remaining -= 1

        if parent_ret[i] <= trigger_threshold:
            out.at[i, "guardrail_trigger_day"] = True
            if out.at[i, "guardrail_reason"] == "":
                out.at[i, "guardrail_reason"] = "g1_trigger"
            cooldown_remaining = max(cooldown_remaining, cooldown_days)

    return out


def apply_g2_dd5_brake(parent_df: pd.DataFrame) -> pd.DataFrame:
    out = parent_df.copy()
    out["guardrail_trigger_day"] = False
    out["guardrail_forced_1p00"] = False
    out["guardrail_reason"] = ""

    cooldown_days = 3
    dd_trigger = -0.075

    parent_eq = (1.0 + pd.to_numeric(out["parent_realistic_ret"], errors="coerce").fillna(0.0)).cumprod()
    rolling_peak_5 = parent_eq.rolling(5, min_periods=1).max()
    parent_dd_5 = (parent_eq / rolling_peak_5) - 1.0
    out["parent_dd_5"] = parent_dd_5

    cooldown_remaining = 0
    dd_values = parent_dd_5.to_numpy()

    for i in range(len(out)):
        if cooldown_remaining > 0:
            out.at[i, "guardrail_forced_1p00"] = True
            out.at[i, "guardrail_reason"] = "g2_dd5_cd3_active"
            cooldown_remaining -= 1

        if dd_values[i] <= dd_trigger:
            out.at[i, "guardrail_trigger_day"] = True
            if out.at[i, "guardrail_reason"] == "":
                out.at[i, "guardrail_reason"] = "g2_trigger"
            cooldown_remaining = max(cooldown_remaining, cooldown_days)

    return out


def build_parent_wrapped(
    portfolio_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    tradable_transition_df: pd.DataFrame,
    parent: ParentVariant,
) -> pd.DataFrame:
    variant = core68h.ValidationVariant(
        model=parent.model,
        mode=parent.mode,
        target_leverage=parent.target_leverage,
    )

    wrapped = core68h.build_validation_wrapper(
        portfolio_df=portfolio_df,
        trend_df=trend_df,
        tradable_transition_df=tradable_transition_df,
        variant=variant,
        annual_borrow_cost=float(BORROW_COST),
        tradable_transition_slippage_bps=float(TRADABLE_SLIPPAGE_BPS),
        trend_activation_threshold=float(DYNAMIC_PARAMS["trend_activation_threshold"]),
        stress_lookback_days=int(DYNAMIC_PARAMS["stress_lookback_days"]),
        stress_off_threshold=float(DYNAMIC_PARAMS["stress_off_threshold"]),
        stress_on_threshold=float(DYNAMIC_PARAMS["stress_on_threshold"]),
        dynamic_mid_threshold=float(DYNAMIC_PARAMS["dynamic_mid_threshold"]),
        dynamic_mid_leverage=float(DYNAMIC_PARAMS["dynamic_mid_leverage"]),
        dynamic_high_leverage=float(DYNAMIC_PARAMS["dynamic_high_leverage"]),
    )
    return wrapped


def apply_guardrail_to_parent(
    parent_df: pd.DataFrame,
    parent: ParentVariant,
    guardrail: GuardrailSpec,
) -> pd.DataFrame:
    work = parent_df.copy()

    work["parent_model"] = parent.model
    work["parent_effective_leverage"] = pd.to_numeric(work["effective_leverage"], errors="coerce").fillna(1.0)
    work["parent_realistic_ret"] = pd.to_numeric(work["realistic_ret"], errors="coerce").fillna(0.0)
    work["parent_leverage_state_reason"] = work["leverage_state_reason"].astype(str)

    if guardrail.guardrail_id == "g1_adverse_cd2":
        work = apply_g1_adverse_cooldown(work)
    elif guardrail.guardrail_id == "g2_dd5_cd3":
        work = apply_g2_dd5_brake(work)
    else:
        raise ValueError(f"Unsupported guardrail: {guardrail.guardrail_id}")

    work["effective_leverage"] = np.where(
        work["guardrail_forced_1p00"],
        1.00,
        work["parent_effective_leverage"],
    )

    borrowed_fraction = np.maximum(work["effective_leverage"] - 1.0, 0.0)
    daily_borrow_rate = float(BORROW_COST) / 365.25

    work["daily_borrow_cost"] = borrowed_fraction * daily_borrow_rate
    work["realistic_ret_gross"] = work["base_ret"] * work["effective_leverage"]
    work["realistic_ret"] = (
        work["realistic_ret_gross"]
        - work["daily_borrow_cost"]
        - work["tradable_slippage_cost"]
    )
    work["realistic_ret"] = pd.to_numeric(work["realistic_ret"], errors="coerce").clip(lower=-0.999999)
    work["equity_curve"] = (1.0 + work["realistic_ret"]).cumprod()
    work["leverage_active"] = work["effective_leverage"] > 1.0

    work["leverage_state_reason"] = np.where(
        work["guardrail_forced_1p00"],
        work["guardrail_reason"],
        work["parent_leverage_state_reason"],
    )

    work["guardrail_id"] = guardrail.guardrail_id
    work["guardrail_description"] = guardrail.description
    work["model"] = f"{parent.model}_{guardrail.guardrail_id}"

    return work


def compute_cagr_pct(ret_series: pd.Series, date_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return np.nan
    eq = (1.0 + ret_series.astype(float)).cumprod()
    start_dt = pd.to_datetime(date_series.iloc[0])
    end_dt = pd.to_datetime(date_series.iloc[-1])
    days = max((end_dt - start_dt).days, 1)
    years = days / 365.25
    if years <= 0:
        return np.nan
    return float(((eq.iloc[-1] ** (1.0 / years)) - 1.0) * 100.0)


def compute_max_drawdown_pct(ret_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return np.nan
    eq = (1.0 + ret_series.astype(float)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min() * 100.0)


def subset_since(df: pd.DataFrame, start_date: str) -> pd.DataFrame:
    return df.loc[df["date"] >= pd.Timestamp(start_date)].copy().reset_index(drop=True)


def summarize_row(
    model: str,
    df: pd.DataFrame,
    governance_switch_count: int,
    tradable_transition_count: int,
    parent_model: str | None = None,
    guardrail_id: str | None = None,
) -> dict:
    since2023 = subset_since(df, "2023-01-01")
    since2025 = subset_since(df, "2025-01-01")

    cagr_pct = compute_cagr_pct(df["realistic_ret"], df["date"])
    max_dd_pct = compute_max_drawdown_pct(df["realistic_ret"])
    calmar = np.nan
    if pd.notna(cagr_pct) and pd.notna(max_dd_pct) and abs(max_dd_pct) > 1e-9:
        calmar = cagr_pct / abs(max_dd_pct)

    return {
        "model": model,
        "parent_model": parent_model or model,
        "guardrail_id": guardrail_id or "none",
        "cagr_pct": round(cagr_pct, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "calmar": round(calmar, 4) if pd.notna(calmar) else np.nan,
        "since2023_cagr_pct": round(compute_cagr_pct(since2023["realistic_ret"], since2023["date"]), 2) if not since2023.empty else np.nan,
        "since2025_cagr_pct": round(compute_cagr_pct(since2025["realistic_ret"], since2025["date"]), 2) if not since2025.empty else np.nan,
        "worst_day_pct": round(float(pd.to_numeric(df["realistic_ret"], errors="coerce").min() * 100.0), 2) if not df.empty else np.nan,
        "borrow_cost_total_pct": round(float(pd.to_numeric(df["daily_borrow_cost"], errors="coerce").sum() * 100.0), 4),
        "tradable_slippage_cost_total_pct": round(float(pd.to_numeric(df["tradable_slippage_cost"], errors="coerce").sum() * 100.0), 4),
        "governance_switch_count": int(governance_switch_count),
        "tradable_transition_count": int(tradable_transition_count),
        "exposure_days": int(df["is_exposed"].sum()),
        "asset_transition_count": int(df["asset_transition_day"].sum()),
        "eligible_days": int(df["leverage_eligible"].sum()),
        "leverage_active_days": int(df["leverage_active"].sum()),
        "guardrail_trigger_days": int(df["guardrail_trigger_day"].sum()) if "guardrail_trigger_day" in df.columns else 0,
        "guardrail_forced_1p00_days": int(df["guardrail_forced_1p00"].sum()) if "guardrail_forced_1p00" in df.columns else 0,
        "held_asset_now": str(df["portfolio_held_asset"].iloc[-1]) if not df.empty else "",
        "latest_available_date": df["date"].max().strftime("%Y-%m-%d") if not df.empty else "",
    }


def add_compare_deltas(
    df: pd.DataFrame,
    parent_refs: dict[str, dict],
    official_ref: dict,
) -> pd.DataFrame:
    out_rows = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        parent_ref = parent_refs[str(row_dict["parent_model"])]
        for metric in [
            "cagr_pct",
            "max_drawdown_pct",
            "calmar",
            "since2023_cagr_pct",
            "since2025_cagr_pct",
            "worst_day_pct",
        ]:
            row_dict[f"delta_vs_parent_{metric}"] = (
                pd.to_numeric(row_dict.get(metric), errors="coerce")
                - pd.to_numeric(parent_ref.get(metric), errors="coerce")
            )
            row_dict[f"delta_vs_official_baseline_{metric}"] = (
                pd.to_numeric(row_dict.get(metric), errors="coerce")
                - pd.to_numeric(official_ref.get(metric), errors="coerce")
            )
        out_rows.append(row_dict)

    return pd.DataFrame(out_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE68J tail-risk guardrail check")
    parser.add_argument("--governance-paper", type=str, default=str(DEFAULT_GOVERNANCE_PAPER))
    parser.add_argument("--baseline-paper", type=str, default="")
    parser.add_argument("--trend-history", type=str, default=str(DEFAULT_TREND))
    parser.add_argument("--decisions", type=str, default=str(DEFAULT_DECISIONS))
    args = parser.parse_args()

    ensure_dir(PHASE68J_DIR)
    papers_dir = PHASE68J_DIR / "papers"
    ensure_dir(papers_dir)

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

    log("[PHASE68J] Start")
    log(f"[PHASE68J] Governance paper: {governance_paper_path}")
    log(f"[PHASE68J] Baseline paper: {baseline_paper_path}")
    log(f"[PHASE68J] Trend history: {trend_path}")
    log(f"[PHASE68J] Decisions: {decisions_path}")

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

    transition_calendar_path = PHASE68J_DIR / "phase68j_tradable_transition_calendar.csv"
    tradable_transition_df.to_csv(transition_calendar_path, index=False)

    summary_rows: list[dict] = []
    parent_refs: dict[str, dict] = {}

    for parent in PARENT_VARIANTS:
        log(f"[PHASE68J] parent {parent.model}")

        parent_wrapped = build_parent_wrapped(
            portfolio_df=portfolio_df,
            trend_df=trend_df,
            tradable_transition_df=tradable_transition_df,
            parent=parent,
        )
        parent_wrapped["guardrail_trigger_day"] = False
        parent_wrapped["guardrail_forced_1p00"] = False
        parent_wrapped["guardrail_reason"] = ""
        parent_wrapped["parent_model"] = parent.model
        parent_wrapped["parent_effective_leverage"] = parent_wrapped["effective_leverage"]
        parent_wrapped["parent_realistic_ret"] = parent_wrapped["realistic_ret"]
        parent_wrapped["model"] = parent.model

        parent_path = papers_dir / f"{parent.model}_paper.csv"
        parent_wrapped.to_csv(parent_path, index=False)

        parent_row = summarize_row(
            model=parent.model,
            df=parent_wrapped,
            governance_switch_count=governance_switch_count,
            tradable_transition_count=tradable_transition_count,
            parent_model=parent.model,
            guardrail_id="none",
        )
        summary_rows.append(parent_row)
        parent_refs[parent.model] = parent_row

        for guardrail in GUARDRAILS:
            guarded = apply_guardrail_to_parent(parent_wrapped, parent, guardrail)
            guarded_path = papers_dir / f"{guarded['model'].iloc[0]}_paper.csv"
            guarded.to_csv(guarded_path, index=False)

            summary_rows.append(
                summarize_row(
                    model=str(guarded["model"].iloc[0]),
                    df=guarded,
                    governance_switch_count=governance_switch_count,
                    tradable_transition_count=tradable_transition_count,
                    parent_model=parent.model,
                    guardrail_id=guardrail.guardrail_id,
                )
            )
            log(f"[PHASE68J] done {guarded['model'].iloc[0]}")

    summary_df = pd.DataFrame(summary_rows)

    official_ref_row = summary_df.loc[summary_df["model"] == OFFICIAL_COMPARE_BASELINE]
    if official_ref_row.empty:
        raise ValueError(f"Chýba official compare baseline row: {OFFICIAL_COMPARE_BASELINE}")
    official_ref = official_ref_row.iloc[0].to_dict()

    compare_df = add_compare_deltas(summary_df, parent_refs=parent_refs, official_ref=official_ref)

    guarded_only = compare_df.loc[compare_df["guardrail_id"] != "none"].copy()
    if guarded_only.empty:
        raise ValueError("Chýbajú guarded variants.")

    best_guarded_deploy = guarded_only.sort_values(
        by=["delta_vs_parent_calmar", "delta_vs_parent_max_drawdown_pct", "delta_vs_parent_since2025_cagr_pct", "calmar"],
        ascending=[False, False, False, False],
        na_position="last",
    ).iloc[0].to_dict()

    best_guarded_raw = guarded_only.sort_values(
        by=["cagr_pct", "since2025_cagr_pct", "calmar", "max_drawdown_pct"],
        ascending=[False, False, False, False],
        na_position="last",
    ).iloc[0].to_dict()

    summary_path = PHASE68J_DIR / "phase68j_tail_risk_guardrail_summary.csv"
    compare_path = PHASE68J_DIR / "phase68j_tail_risk_guardrail_compare.csv"
    manifest_path = PHASE68J_DIR / "phase68j_tail_risk_guardrail_manifest.json"

    summary_df.to_csv(summary_path, index=False)
    compare_df.to_csv(compare_path, index=False)

    manifest = {
        "phase": "phase68j_tail_risk_guardrail_check",
        "official_compare_baseline": OFFICIAL_COMPARE_BASELINE,
        "governance_paper": str(governance_paper_path),
        "baseline_paper": str(baseline_paper_path),
        "trend_history": str(trend_path),
        "decisions_file": str(decisions_path),
        "transition_mapping_meta": mapping_meta,
        "governance_switch_count": int(governance_switch_count),
        "tradable_transition_count": int(tradable_transition_count),
        "transition_calendar_file": str(transition_calendar_path),
        "dynamic_params": DYNAMIC_PARAMS,
        "borrow_cost": BORROW_COST,
        "tradable_transition_slippage_bps": TRADABLE_SLIPPAGE_BPS,
        "parent_variants": [asdict(v) for v in PARENT_VARIANTS],
        "guardrails": [asdict(g) for g in GUARDRAILS],
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "papers_dir": str(papers_dir),
        "notes": [
            "68J nemení leverage level ani signal logiku parent vetiev.",
            "Testuje len downward-only tail-risk override na effective_leverage.",
            "G1: po adverse dni <= -5% ďalšie 2 dni force 1.00x.",
            "G2: po parent rolling 5d DD <= -7.5% ďalšie 3 dni force 1.00x.",
            "Official compare baseline = dynamic ladder reference.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE68J BEST GUARDED RAW ===")
    log(f"model: {best_guarded_raw['model']}")
    log(f"parent_model: {best_guarded_raw['parent_model']}")
    log(f"guardrail_id: {best_guarded_raw['guardrail_id']}")
    log(f"cagr_pct: {float(best_guarded_raw['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(best_guarded_raw['max_drawdown_pct']):.2f}")
    log(f"calmar: {float(best_guarded_raw['calmar']):.4f}")
    log(f"since2025_cagr_pct: {float(best_guarded_raw['since2025_cagr_pct']):.2f}")
    log(f"delta_vs_parent_cagr_pct: {float(best_guarded_raw['delta_vs_parent_cagr_pct']):.2f}")
    log(f"delta_vs_parent_max_drawdown_pct: {float(best_guarded_raw['delta_vs_parent_max_drawdown_pct']):.2f}")
    log(f"delta_vs_parent_calmar: {float(best_guarded_raw['delta_vs_parent_calmar']):.4f}")
    log(f"guardrail_trigger_days: {int(pd.to_numeric(best_guarded_raw['guardrail_trigger_days'], errors='coerce'))}")
    log(f"guardrail_forced_1p00_days: {int(pd.to_numeric(best_guarded_raw['guardrail_forced_1p00_days'], errors='coerce'))}")
    log("")

    log("=== PHASE68J BEST GUARDED DEPLOYMENT ===")
    log(f"model: {best_guarded_deploy['model']}")
    log(f"parent_model: {best_guarded_deploy['parent_model']}")
    log(f"guardrail_id: {best_guarded_deploy['guardrail_id']}")
    log(f"cagr_pct: {float(best_guarded_deploy['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(best_guarded_deploy['max_drawdown_pct']):.2f}")
    log(f"calmar: {float(best_guarded_deploy['calmar']):.4f}")
    log(f"since2025_cagr_pct: {float(best_guarded_deploy['since2025_cagr_pct']):.2f}")
    log(f"delta_vs_parent_cagr_pct: {float(best_guarded_deploy['delta_vs_parent_cagr_pct']):.2f}")
    log(f"delta_vs_parent_max_drawdown_pct: {float(best_guarded_deploy['delta_vs_parent_max_drawdown_pct']):.2f}")
    log(f"delta_vs_parent_calmar: {float(best_guarded_deploy['delta_vs_parent_calmar']):.4f}")
    log(f"guardrail_trigger_days: {int(pd.to_numeric(best_guarded_deploy['guardrail_trigger_days'], errors='coerce'))}")
    log(f"guardrail_forced_1p00_days: {int(pd.to_numeric(best_guarded_deploy['guardrail_forced_1p00_days'], errors='coerce'))}")
    log("")

    log(f"[PHASE68J] Saved summary -> {summary_path}")
    log(f"[PHASE68J] Saved compare -> {compare_path}")
    log(f"[PHASE68J] Saved manifest -> {manifest_path}")
    log(f"[PHASE68J] Saved transition calendar -> {transition_calendar_path}")
    log(f"[PHASE68J] Saved papers -> {papers_dir}")


if __name__ == "__main__":
    main()