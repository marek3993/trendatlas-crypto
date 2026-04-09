from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

import phase68l_early_entry_soft_gate_probe as phase68l
from freshness_lineage import build_producer_lineage


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

BASELINE_MODEL = "phase67j_no_neo_main"
PHASE68L_MODEL = "phase68l_early_entry_soft_gate_probe"
PHASE68M_PHASE = "phase68m_early_entry_micro_confirm"

BASELINE_PAPER_PATH = OUTPUTS / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
CORE_PAPER_PATH = OUTPUTS / "phase66g_production_candidate_live" / "phase66g_production_soft_filters_paper.csv"
TREND_HISTORY_PATH = OUTPUTS / "phase66g_production_candidate_live" / "phase66g_trend_barometer_history.csv"

PHASE68M_DIR = OUTPUTS / PHASE68M_PHASE
PAPERS_DIR = PHASE68M_DIR / "papers"
SUMMARY_PATH = PHASE68M_DIR / "phase68m_early_entry_micro_confirm_summary.csv"
COMPARE_PATH = PHASE68M_DIR / "phase68m_early_entry_micro_confirm_compare.csv"
BLOCKER_COUNTS_PATH = PHASE68M_DIR / "phase68m_early_entry_micro_confirm_blocker_counts.csv"
STATE_TIME_PATH = PHASE68M_DIR / "phase68m_early_entry_micro_confirm_state_time.csv"
MANIFEST_PATH = PHASE68M_DIR / "phase68m_early_entry_micro_confirm_manifest.json"
BASELINE_OUTPUT_PAPER_PATH = PAPERS_DIR / f"{BASELINE_MODEL}_paper.csv"


@dataclass(frozen=True)
class VariantSpec:
    model: str
    note: str
    overrides: dict[str, float]


VARIANTS: list[VariantSpec] = [
    VariantSpec(
        model="phase68m_early_zone_plus",
        note="Small expansion of the EARLY_RISK upper trend zone only.",
        overrides={
            "early_zone_ceiling": 0.20,
        },
    ),
    VariantSpec(
        model="phase68m_zone_score_plus",
        note="Zone plus a slightly easier early score and relative edge requirement.",
        overrides={
            "early_zone_ceiling": 0.20,
            "early_score_min": 0.05,
            "early_edge_vs_core": -0.02,
            "early_recent_rel_min": -0.03,
        },
    ),
    VariantSpec(
        model="phase68m_zone_score_risk_plus",
        note="Zone/score relaxation plus a small early-only risk-off relaxation.",
        overrides={
            "early_zone_ceiling": 0.20,
            "early_score_min": 0.05,
            "early_edge_vs_core": -0.02,
            "early_recent_rel_min": -0.03,
            "early_risk_buffer": -0.10,
            "early_vol_cap": 0.070,
        },
    ),
]


def log(message: str) -> None:
    print(message, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_early_cfg(base_cfg: phase68l.EarlyRiskConfig, overrides: dict[str, float]) -> phase68l.EarlyRiskConfig:
    payload = asdict(base_cfg)
    payload.update(overrides)
    return phase68l.EarlyRiskConfig(**payload)


def build_compare_rows(summary_df: pd.DataFrame) -> pd.DataFrame:
    metric_columns = [
        "cagr_pct",
        "max_drawdown_pct",
        "since2023_cagr_pct",
        "since2025_cagr_pct",
        "calmar",
        "early_setup_ready_days",
        "early_entry_days",
        "avg_lead_days_vs_full_entry",
        "false_start_count",
        "captured_pre_breakout_return_pct",
        "cash_days",
        "early_risk_days",
        "full_risk_days",
        "risk_state_transition_count",
        "cash_to_early_transition_count",
        "early_to_full_transition_count",
        "early_to_cash_transition_count",
    ]
    baseline_row = summary_df[summary_df["model"] == BASELINE_MODEL].iloc[0]
    rows: list[dict[str, float | str]] = []
    for _, probe_row in summary_df[summary_df["model"] != BASELINE_MODEL].iterrows():
        for metric in metric_columns:
            baseline_value = float(pd.to_numeric(baseline_row.get(metric), errors="coerce"))
            probe_value = float(pd.to_numeric(probe_row.get(metric), errors="coerce"))
            rows.append(
                {
                    "metric": metric,
                    "baseline_model": BASELINE_MODEL,
                    "baseline_value": baseline_value,
                    "probe_model": str(probe_row["model"]),
                    "probe_value": probe_value,
                    "delta_probe_minus_baseline": probe_value - baseline_value,
                }
            )
    return pd.DataFrame(rows)


def evaluate_variant(
    variant: VariantSpec,
    baseline_df: pd.DataFrame,
    core_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    strict_cfg: phase68l.StrictFullConfig,
    base_early_cfg: phase68l.EarlyRiskConfig,
) -> tuple[pd.DataFrame, dict, pd.DataFrame, pd.DataFrame]:
    early_cfg = build_early_cfg(base_early_cfg, variant.overrides)
    probe_df = phase68l.build_probe_frame(baseline_df, core_df, trend_df, strict_cfg, early_cfg)

    early_setup_ready_days = int(probe_df["early_setup_ready"].sum())
    early_entry_days = int(probe_df["ladder_state"].eq("EARLY_RISK").sum())
    avg_lead_days, false_start_count, captured_pre_breakout_return_pct = phase68l.analyze_early_sequences(
        probe_df,
        early_cfg.success_resolution_days,
    )
    metrics = phase68l.enrich_metrics(
        probe_df,
        variant.model,
        early_setup_ready_days=early_setup_ready_days,
        early_entry_days=early_entry_days,
        avg_lead_days_vs_full_entry=avg_lead_days,
        false_start_count=false_start_count,
        captured_pre_breakout_return_pct=captured_pre_breakout_return_pct,
    )
    metrics["variant_note"] = variant.note
    metrics["phase68l_reference_early_entry_days"] = 1
    blocker_counts = phase68l.build_blocker_counts(probe_df, early_cfg).copy()
    blocker_counts.insert(0, "model", variant.model)
    state_time = phase68l.build_state_time_summary(probe_df).copy()
    state_time.insert(0, "model", variant.model)
    return probe_df, metrics, blocker_counts, state_time


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase68M dev-only early-entry micro confirm")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--core-paper", type=str, default=str(CORE_PAPER_PATH))
    parser.add_argument("--trend-history", type=str, default=str(TREND_HISTORY_PATH))
    args = parser.parse_args()

    ensure_dir(PHASE68M_DIR)
    ensure_dir(PAPERS_DIR)

    strict_cfg = phase68l.StrictFullConfig()
    base_early_cfg = phase68l.EarlyRiskConfig()

    baseline_df = phase68l.load_paper(Path(args.baseline_paper))
    core_df = phase68l.load_paper(Path(args.core_paper))
    trend_df = phase68l.load_trend_history(Path(args.trend_history))

    baseline_diag = baseline_df.copy()
    baseline_diag["baseline_executed_regime"] = baseline_diag["executed_regime"].astype(str)
    baseline_diag["ladder_state"] = baseline_diag["baseline_executed_regime"].eq("CANDIDATE").map(
        {True: "FULL_RISK", False: "CASH"}
    )
    baseline_metrics = phase68l.enrich_metrics(
        baseline_diag,
        BASELINE_MODEL,
        early_setup_ready_days=0,
        early_entry_days=0,
        avg_lead_days_vs_full_entry=0.0,
        false_start_count=0,
        captured_pre_breakout_return_pct=0.0,
    )
    baseline_metrics["variant_note"] = "Official baseline reference row."
    baseline_metrics["phase68l_reference_early_entry_days"] = 1

    summary_rows = [baseline_metrics]
    blocker_frames: list[pd.DataFrame] = []
    state_time_frames: list[pd.DataFrame] = []

    baseline_df.reset_index().rename(columns={"index": "date"}).to_csv(BASELINE_OUTPUT_PAPER_PATH, index=False)

    log("[PHASE68M] Running micro confirm variants")
    for variant in VARIANTS:
        probe_df, metrics, blocker_counts, state_time = evaluate_variant(
            variant,
            baseline_df,
            core_df,
            trend_df,
            strict_cfg,
            base_early_cfg,
        )
        summary_rows.append(metrics)
        blocker_frames.append(blocker_counts)
        state_time_frames.append(state_time)
        paper_path = PAPERS_DIR / f"{variant.model}_paper.csv"
        probe_df.reset_index().rename(columns={"index": "date"}).to_csv(paper_path, index=False)
        log(
            "[PHASE68M] "
            f"{variant.model} early_setup_ready_days={metrics['early_setup_ready_days']} "
            f"early_entry_days={metrics['early_entry_days']} "
            f"cagr={metrics['cagr_pct']:.4f} "
            f"max_dd={metrics['max_drawdown_pct']:.4f}"
        )

    summary_df = pd.DataFrame(summary_rows)
    compare_df = build_compare_rows(summary_df)
    blocker_counts_df = pd.concat(blocker_frames, ignore_index=True) if blocker_frames else pd.DataFrame()
    state_time_df = pd.concat(state_time_frames, ignore_index=True) if state_time_frames else pd.DataFrame()

    summary_df.to_csv(SUMMARY_PATH, index=False)
    compare_df.to_csv(COMPARE_PATH, index=False)
    blocker_counts_df.to_csv(BLOCKER_COUNTS_PATH, index=False)
    state_time_df.to_csv(STATE_TIME_PATH, index=False)

    manifest = {
        "phase": PHASE68M_PHASE,
        "experiment_scope": "final_narrow_dev_only_early_entry_micro_confirm",
        "official_compare_baseline": BASELINE_MODEL,
        "phase68l_reference_model": PHASE68L_MODEL,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "changes_shortlist": False,
        "changes_governance": False,
        "changes_leverage": False,
        "changes_app_live_truth": False,
        "changes_execution_logic": False,
        "full_risk_behavior": "preserved_strict_baseline_behavior",
        "micro_pass_design": {
            "variant_count": len(VARIANTS),
            "variant_selection_style": "hand_picked_micro_pass_not_broad_sweep",
            "strict_full_reference": asdict(strict_cfg),
            "phase68l_early_reference": asdict(base_early_cfg),
            "variants": [
                {
                    "model": variant.model,
                    "note": variant.note,
                    "overrides": variant.overrides,
                }
                for variant in VARIANTS
            ],
        },
        "inputs": {
            "baseline_paper": str(Path(args.baseline_paper).resolve()),
            "core_paper": str(Path(args.core_paper).resolve()),
            "trend_history": str(Path(args.trend_history).resolve()),
        },
        "outputs": {
            "summary_file": str(SUMMARY_PATH.resolve()),
            "compare_file": str(COMPARE_PATH.resolve()),
            "blocker_counts_file": str(BLOCKER_COUNTS_PATH.resolve()),
            "state_time_file": str(STATE_TIME_PATH.resolve()),
            "manifest_file": str(MANIFEST_PATH.resolve()),
            "papers_dir": str(PAPERS_DIR.resolve()),
            "baseline_paper_copy": str(BASELINE_OUTPUT_PAPER_PATH.resolve()),
        },
        "freshness_lineage": build_producer_lineage(
            producer_script=__file__,
            source_file=Path(args.baseline_paper).resolve(),
            raw_file=Path(args.trend_history).resolve(),
            output_file=SUMMARY_PATH.resolve(),
            date_semantics="execution_date",
        ),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log(f"[PHASE68M] Saved summary -> {SUMMARY_PATH}")
    log(f"[PHASE68M] Saved compare -> {COMPARE_PATH}")
    log(f"[PHASE68M] Saved blocker counts -> {BLOCKER_COUNTS_PATH}")
    log(f"[PHASE68M] Saved state time -> {STATE_TIME_PATH}")
    log(f"[PHASE68M] Saved manifest -> {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
