from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

import phase66e_probation_governance as core


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

CURRENT_WINNER_KEY = core.CURRENT_WINNER_KEY
CURRENT_WINNER_PAPER = core.CURRENT_WINNER_PAPER
PHASE66B_DROP_CANDIDATES = core.PHASE66B_DROP_CANDIDATES

PHASE66E_SUMMARY = (
    OUTPUTS
    / "phase66e_probation_governance"
    / "phase66e_probation_governance_summary.csv"
)

PHASE66F_DIR = OUTPUTS / "phase66f_probation_robustness"


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_profiles(min_history_days: int) -> list[core.GovernanceConfig]:
    return [
        core.GovernanceConfig(
            profile_name="phase66f_probation_ref_strict",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_recent45",
            trailing_train_days=365,
            recent_days=45,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_recent75",
            trailing_train_days=365,
            recent_days=75,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_soft_ban4",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=4,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_hard_ban8",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=8,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_soft_thresh_neg05",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=-0.5,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_hard_thresh_pos05",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=0.5,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_lb30",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=30,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_lb60",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=60,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_hold2_margin2",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=2.0,
            min_hold_periods=2,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_hold4_margin4",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=5,
            min_total_delta_pct=1.0,
            min_recent_delta_pct=0.5,
            max_allowed_dd_worsen_pct=2.5,
            switch_score_margin=4.0,
            min_hold_periods=4,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_soft_filters",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=4,
            min_total_delta_pct=0.5,
            min_recent_delta_pct=0.25,
            max_allowed_dd_worsen_pct=3.0,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
        core.GovernanceConfig(
            profile_name="phase66f_probation_hard_filters",
            trailing_train_days=365,
            recent_days=60,
            rebalance_every_days=7,
            min_history_days=min_history_days,
            min_triggers_in_train=6,
            min_total_delta_pct=1.5,
            min_recent_delta_pct=0.75,
            max_allowed_dd_worsen_pct=2.0,
            switch_score_margin=3.0,
            min_hold_periods=3,
            probation_lookback_days=45,
            probation_min_delta_pct=0.0,
            probation_ban_periods=6,
        ),
    ]


def load_phase66e_strict_reference(summary_path: Path) -> dict | None:
    if not summary_path.exists():
        return None
    df = pd.read_csv(summary_path)
    df.columns = [str(c).strip() for c in df.columns]
    match = df[df["model"].astype(str) == "phase66e_probation_strict"]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def add_delta_cols(row: dict, ref: dict, prefix: str) -> dict:
    out = row.copy()
    for metric in [
        "cagr_pct",
        "max_drawdown_pct",
        "since2021_cagr_pct",
        "since2023_cagr_pct",
        "since2025_cagr_pct",
    ]:
        out[f"delta_vs_{prefix}_{metric}"] = (
            pd.to_numeric(out.get(metric), errors="coerce")
            - pd.to_numeric(ref.get(metric), errors="coerce")
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE66F probation robustness around strict winner")
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    parser.add_argument("--drop-file", type=str, default=str(PHASE66B_DROP_CANDIDATES))
    parser.add_argument("--phase66e-summary", type=str, default=str(PHASE66E_SUMMARY))
    parser.add_argument("--min-history-days", type=int, default=180)
    args = parser.parse_args()

    ensure_dir(PHASE66F_DIR)

    overlay_cfg = core.OverlayConfig()
    remove_assets = core.load_remove_assets(Path(args.drop_file))
    profiles = build_profiles(args.min_history_days)
    strict_ref = load_phase66e_strict_reference(Path(args.phase66e_summary))

    log("[PHASE66F] Start")
    log(f"[PHASE66F] Baseline paper: {args.baseline_paper}")
    log(f"[PHASE66F] Remove assets: {remove_assets}")
    log(f"[PHASE66F] Profiles: {len(profiles)}")

    baseline = core.load_baseline_paper(Path(args.baseline_paper), overlay_cfg)
    best_files = core.discover_best_file_per_asset()

    allowed_assets = [asset for asset in sorted(best_files.keys()) if asset not in remove_assets]
    asset_strategies: dict[str, pd.DataFrame] = {}
    asset_quality_rows = []
    failed_assets = []

    min_history_days = max(p.min_history_days for p in profiles)

    for asset in allowed_assets:
        try:
            file_path = best_files[asset]
            daily, q = core.load_asset_daily_prices(file_path, "candidate_close")
            if q["history_days"] < min_history_days:
                continue
            strat = core.build_asset_strategy(baseline, daily, overlay_cfg, asset)
            asset_strategies[asset] = strat
            asset_quality_rows.append({"asset": asset, "file": str(file_path), **q})
        except Exception as e:
            failed_assets.append({"asset": asset, "reason": str(e)})

    log(f"[PHASE66F] Candidate assets loaded: {len(asset_strategies)}")

    phase63_row = core.calc_metrics(baseline, CURRENT_WINNER_KEY)
    phase63_row.update(core.window_metrics(baseline, "2021-01-01"))
    phase63_row.update(core.window_metrics(baseline, "2023-01-01"))
    phase63_row.update(core.window_metrics(baseline, "2025-01-01"))
    phase63_row["mode"] = "baseline"

    summary_rows = [phase63_row]
    decisions_all = []
    leaderboards_all = []
    usage_rows = []
    governance_papers = {CURRENT_WINNER_KEY: baseline.copy()}

    if strict_ref is not None:
        strict_ref_row = {
            "model": "phase66e_probation_strict_ref",
            "mode": "phase66e_probation_strict_ref",
            **strict_ref,
        }
        summary_rows.append(strict_ref_row)

    for gov_cfg in profiles:
        governance, decisions_df, leaderboard_df = core.simulate_governance_strategy_probation(
            baseline=baseline,
            asset_strategies=asset_strategies,
            gov_cfg=gov_cfg,
        )

        row = core.calc_metrics(governance, gov_cfg.profile_name)
        row.update(core.window_metrics(governance, "2021-01-01"))
        row.update(core.window_metrics(governance, "2023-01-01"))
        row.update(core.window_metrics(governance, "2025-01-01"))
        row["mode"] = gov_cfg.profile_name

        row = add_delta_cols(row, phase63_row, "phase63")
        if strict_ref is not None:
            row = add_delta_cols(row, strict_ref, "phase66e_strict")

        selected_nonempty = governance["chosen_asset"].astype(str)
        row["unique_selected_assets"] = int(selected_nonempty[selected_nonempty != ""].nunique())
        row["selected_days_pct"] = float((selected_nonempty != "").mean() * 100.0)
        row["decision_count"] = int(len(decisions_df))
        row["selection_count"] = int(decisions_df["selected"].sum()) if not decisions_df.empty else 0
        row["switch_count"] = int((decisions_df["selected_asset"].astype(str) != decisions_df["selected_asset"].astype(str).shift(1)).sum() - 1) if not decisions_df.empty else 0

        if not leaderboard_df.empty and "suspended" in leaderboard_df.columns:
            susp = leaderboard_df.groupby("asset", as_index=False)["suspended"].sum()
            row["asset_suspensions_total"] = int(pd.to_numeric(susp["suspended"], errors="coerce").sum())
        else:
            row["asset_suspensions_total"] = 0

        summary_rows.append(row)
        governance_papers[gov_cfg.profile_name] = governance.copy()

        if not decisions_df.empty:
            decisions_all.append(decisions_df)
        if not leaderboard_df.empty:
            leaderboards_all.append(leaderboard_df)

        asset_usage = (
            governance["chosen_asset"]
            .astype(str)
            .replace("", np.nan)
            .dropna()
            .value_counts()
            .rename_axis("asset")
            .reset_index(name="selected_days")
        )
        if not asset_usage.empty:
            asset_usage["selected_days_pct"] = asset_usage["selected_days"] / len(governance) * 100.0
            asset_usage["profile"] = gov_cfg.profile_name
            usage_rows.append(asset_usage)

        log(f"[PHASE66F] done {gov_cfg.profile_name}")

    summary = pd.DataFrame(summary_rows)

    compare = summary.copy()
    ref_models = [CURRENT_WINNER_KEY, "phase66e_probation_strict_ref"]
    cand_df = summary[~summary["model"].astype(str).isin(ref_models)].copy()

    if strict_ref is not None:
        sort_cols = [
            "delta_vs_phase66e_strict_since2023_cagr_pct",
            "delta_vs_phase66e_strict_cagr_pct",
            "delta_vs_phase66e_strict_max_drawdown_pct",
            "delta_vs_phase66e_strict_since2025_cagr_pct",
        ]
    else:
        sort_cols = [
            "delta_vs_phase63_since2023_cagr_pct",
            "delta_vs_phase63_cagr_pct",
            "delta_vs_phase63_max_drawdown_pct",
            "delta_vs_phase63_since2025_cagr_pct",
        ]

    for col in sort_cols:
        if col not in cand_df.columns:
            cand_df[col] = np.nan

    cand_df = cand_df.sort_values(
        by=sort_cols,
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    base_parts = [summary[summary["model"].astype(str) == CURRENT_WINNER_KEY].copy()]
    if strict_ref is not None:
        base_parts.append(summary[summary["model"].astype(str) == "phase66e_probation_strict_ref"].copy())
    compare = pd.concat(base_parts + [cand_df], ignore_index=True)

    decisions_out = pd.concat(decisions_all, ignore_index=True) if decisions_all else pd.DataFrame()
    leaderboard_out = pd.concat(leaderboards_all, ignore_index=True) if leaderboards_all else pd.DataFrame()
    usage_out = pd.concat(usage_rows, ignore_index=True) if usage_rows else pd.DataFrame()

    summary_path = PHASE66F_DIR / "phase66f_probation_robustness_summary.csv"
    compare_path = PHASE66F_DIR / "phase66f_probation_robustness_compare.csv"
    decisions_path = PHASE66F_DIR / "phase66f_probation_robustness_decisions.csv"
    leaderboard_path = PHASE66F_DIR / "phase66f_probation_robustness_leaderboard.csv"
    asset_quality_path = PHASE66F_DIR / "phase66f_probation_robustness_asset_quality.csv"
    asset_usage_path = PHASE66F_DIR / "phase66f_probation_robustness_asset_usage.csv"
    failed_assets_path = PHASE66F_DIR / "phase66f_probation_robustness_failed_assets.csv"
    manifest_path = PHASE66F_DIR / "phase66f_manifest.json"

    summary.to_csv(summary_path, index=False)
    compare.to_csv(compare_path, index=False)
    decisions_out.to_csv(decisions_path, index=False)
    leaderboard_out.to_csv(leaderboard_path, index=False)
    pd.DataFrame(asset_quality_rows).to_csv(asset_quality_path, index=False)
    usage_out.to_csv(asset_usage_path, index=False)
    pd.DataFrame(failed_assets).to_csv(failed_assets_path, index=False)

    top_models = [CURRENT_WINNER_KEY]
    if strict_ref is not None:
        top_models.append("phase66e_probation_strict_ref")
    top_models += cand_df["model"].head(6).astype(str).tolist()

    for model in top_models:
        if model == "phase66e_probation_strict_ref":
            continue
        paper = governance_papers.get(model)
        if paper is None:
            continue
        out_path = PHASE66F_DIR / f"{model}_paper.csv"
        paper.reset_index().rename(columns={paper.index.name or "index": "date"}).to_csv(out_path, index=False)

    manifest = {
        "phase": "phase66f_probation_robustness",
        "baseline_model": CURRENT_WINNER_KEY,
        "baseline_paper": str(args.baseline_paper),
        "phase66e_summary": str(args.phase66e_summary),
        "drop_file": str(args.drop_file),
        "removed_assets": remove_assets,
        "candidate_assets_loaded": int(len(asset_strategies)),
        "candidate_assets_failed": int(len(failed_assets)),
        "profiles": [asdict(p) for p in profiles],
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "decisions_file": str(decisions_path),
        "leaderboard_file": str(leaderboard_path),
        "asset_quality_file": str(asset_quality_path),
        "asset_usage_file": str(asset_usage_path),
        "failed_assets_file": str(failed_assets_path),
        "notes": [
            "Robustness test okolo Phase66E strict.",
            "2 kroky naraz: neighborhood sweep + direct compare vs Phase66E strict aj vs Phase63.",
            "Cieľ: overiť, či winner stojí na úzkom sete parametrov alebo je stabilný.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    best = cand_df.head(1)

    log("")
    log("=== PHASE66F TOP RESULT ===")
    if best.empty:
        log("No robustness profile processed.")
    else:
        row = best.iloc[0]
        log(f"model: {row['model']}")
        log(f"cagr_pct: {row['cagr_pct']:.2f}")
        log(f"max_drawdown_pct: {row['max_drawdown_pct']:.2f}")
        log(f"since2023_cagr_pct: {row['since2023_cagr_pct']:.2f}")
        log(f"since2025_cagr_pct: {row['since2025_cagr_pct']:.2f}")
        if strict_ref is not None:
            log(f"delta_vs_phase66e_strict_cagr_pct: {row['delta_vs_phase66e_strict_cagr_pct']:.2f}")
            log(f"delta_vs_phase66e_strict_since2023_cagr_pct: {row['delta_vs_phase66e_strict_since2023_cagr_pct']:.2f}")
            log(f"delta_vs_phase66e_strict_since2025_cagr_pct: {row['delta_vs_phase66e_strict_since2025_cagr_pct']:.2f}")
            log(f"delta_vs_phase66e_strict_max_drawdown_pct: {row['delta_vs_phase66e_strict_max_drawdown_pct']:.2f}")
        log(f"delta_vs_phase63_cagr_pct: {row['delta_vs_phase63_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_since2023_cagr_pct: {row['delta_vs_phase63_since2023_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_since2025_cagr_pct: {row['delta_vs_phase63_since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_max_drawdown_pct: {row['delta_vs_phase63_max_drawdown_pct']:.2f}")
        log(f"selection_count: {int(row['selection_count'])}")
        log(f"switch_count: {int(row['switch_count'])}")
        log(f"asset_suspensions_total: {int(row['asset_suspensions_total'])}")
        log("")

    log(f"[PHASE66F] Saved summary -> {summary_path}")
    log(f"[PHASE66F] Saved compare -> {compare_path}")
    log(f"[PHASE66F] Saved decisions -> {decisions_path}")
    log(f"[PHASE66F] Saved leaderboard -> {leaderboard_path}")
    log(f"[PHASE66F] Saved asset quality -> {asset_quality_path}")
    log(f"[PHASE66F] Saved asset usage -> {asset_usage_path}")
    log(f"[PHASE66F] Saved failed assets -> {failed_assets_path}")
    log(f"[PHASE66F] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()