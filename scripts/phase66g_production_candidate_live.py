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

PHASE66G_DIR = OUTPUTS / "phase66g_production_candidate_live"


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_winner_config(min_history_days: int) -> core.GovernanceConfig:
    return core.GovernanceConfig(
        profile_name="phase66g_production_soft_filters",
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
    )


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


def load_phase66f_reference(summary_path: Path) -> dict | None:
    if not summary_path.exists():
        return None
    df = pd.read_csv(summary_path)
    df.columns = [str(c).strip() for c in df.columns]
    match = df[df["model"].astype(str) == "phase66f_probation_soft_filters"]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def compute_next_rebalance_date(decisions_df: pd.DataFrame, rebalance_days: int) -> str:
    if decisions_df.empty or "decision_date" not in decisions_df.columns:
        return ""
    last_decision = pd.to_datetime(decisions_df["decision_date"], errors="coerce").dropna()
    if last_decision.empty:
        return ""
    next_dt = last_decision.iloc[-1] + pd.Timedelta(days=rebalance_days)
    return next_dt.strftime("%Y-%m-%d")


def _find_column_case_insensitive(df: pd.DataFrame, required_name: str) -> str:
    lower_map = {str(col).lower(): col for col in df.columns}
    key = required_name.lower()
    if key not in lower_map:
        raise KeyError(
            f"Trend barometer source column '{required_name}' sa nenašiel v baseline DataFrame. "
            f"Dostupné stĺpce: {list(df.columns)}"
        )
    return lower_map[key]


def _trend_state_label(score: float) -> str:
    if pd.isna(score):
        return "nezname"
    if score <= -0.50:
        return "negativny"
    if score < 0.0:
        return "pod_buy_hranicou"
    if score < 0.50:
        return "nad_buy_hranicou"
    return "pozitivny"


def build_trend_barometer_history(baseline: pd.DataFrame, overlay_cfg: object) -> pd.DataFrame:
    base_strength_col = _find_column_case_insensitive(baseline, "base_strength_lb")

    threshold_raw = float(getattr(overlay_cfg, "weak_base_threshold"))
    trend_band = float(
        max(
            float(getattr(overlay_cfg, "candidate_ret_min")),
            float(getattr(overlay_cfg, "candidate_risk_buffer")),
            1e-6,
        )
    )

    out = pd.DataFrame(index=baseline.index.copy())
    out.index.name = baseline.index.name or "date"
    out["trend_input_raw"] = pd.to_numeric(baseline[base_strength_col], errors="coerce")
    out["trend_threshold_raw"] = threshold_raw
    out["trend_band"] = trend_band
    out["trend_score_raw"] = (out["trend_input_raw"] - out["trend_threshold_raw"]) / out["trend_band"]
    out["trend_score"] = out["trend_score_raw"].clip(-1.0, 1.0)
    out["buy_threshold"] = 0.0
    out["prev_trend_score"] = out["trend_score"].shift(1)
    out["crossed_up_today"] = (
        (out["prev_trend_score"] < 0.0) & (out["trend_score"] >= 0.0)
    ).fillna(False)
    out["crossed_down_today"] = (
        (out["prev_trend_score"] >= 0.0) & (out["trend_score"] < 0.0)
    ).fillna(False)
    out["trend_state_label"] = out["trend_score"].apply(_trend_state_label)
    out["trend_calc_date"] = pd.to_datetime(out.index).strftime("%Y-%m-%d")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE66G production candidate + live weekly selector")
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    parser.add_argument("--drop-file", type=str, default=str(PHASE66B_DROP_CANDIDATES))
    parser.add_argument(
        "--phase66f-summary",
        type=str,
        default=str(OUTPUTS / "phase66f_probation_robustness" / "phase66f_probation_robustness_summary.csv"),
    )
    parser.add_argument("--min-history-days", type=int, default=180)
    args = parser.parse_args()

    ensure_dir(PHASE66G_DIR)

    overlay_cfg = core.OverlayConfig()
    gov_cfg = build_winner_config(args.min_history_days)
    remove_assets = core.load_remove_assets(Path(args.drop_file))
    phase66f_ref = load_phase66f_reference(Path(args.phase66f_summary))

    log("[PHASE66G] Start")
    log(f"[PHASE66G] Baseline paper: {args.baseline_paper}")
    log(f"[PHASE66G] Remove assets: {remove_assets}")

    baseline = core.load_baseline_paper(Path(args.baseline_paper), overlay_cfg)
    trend_history = build_trend_barometer_history(baseline, overlay_cfg)
    best_files = core.discover_best_file_per_asset()

    allowed_assets = [asset for asset in sorted(best_files.keys()) if asset not in remove_assets]
    asset_strategies: dict[str, pd.DataFrame] = {}
    asset_quality_rows = []
    failed_assets = []

    for asset in allowed_assets:
        try:
            file_path = best_files[asset]
            daily, q = core.load_asset_daily_prices(file_path, "candidate_close")
            if q["history_days"] < gov_cfg.min_history_days:
                continue
            strat = core.build_asset_strategy(baseline, daily, overlay_cfg, asset)
            asset_strategies[asset] = strat
            asset_quality_rows.append({"asset": asset, "file": str(file_path), **q})
        except Exception as e:
            failed_assets.append({"asset": asset, "reason": str(e)})

    log(f"[PHASE66G] Candidate assets loaded: {len(asset_strategies)}")

    governance, decisions_df, leaderboard_df = core.simulate_governance_strategy_probation(
        baseline=baseline,
        asset_strategies=asset_strategies,
        gov_cfg=gov_cfg,
    )

    phase63_row = core.calc_metrics(baseline, CURRENT_WINNER_KEY)
    phase63_row.update(core.window_metrics(baseline, "2021-01-01"))
    phase63_row.update(core.window_metrics(baseline, "2023-01-01"))
    phase63_row.update(core.window_metrics(baseline, "2025-01-01"))
    phase63_row["mode"] = "baseline"

    prod_row = core.calc_metrics(governance, gov_cfg.profile_name)
    prod_row.update(core.window_metrics(governance, "2021-01-01"))
    prod_row.update(core.window_metrics(governance, "2023-01-01"))
    prod_row.update(core.window_metrics(governance, "2025-01-01"))
    prod_row["mode"] = gov_cfg.profile_name
    prod_row = add_delta_cols(prod_row, phase63_row, "phase63")
    if phase66f_ref is not None:
        prod_row = add_delta_cols(prod_row, phase66f_ref, "phase66f_soft_filters")

    selected_nonempty = governance["chosen_asset"].astype(str)
    prod_row["unique_selected_assets"] = int(selected_nonempty[selected_nonempty != ""].nunique())
    prod_row["selected_days_pct"] = float((selected_nonempty != "").mean() * 100.0)
    prod_row["decision_count"] = int(len(decisions_df))
    prod_row["selection_count"] = int(decisions_df["selected"].sum()) if not decisions_df.empty else 0
    prod_row["switch_count"] = int(
        (decisions_df["selected_asset"].astype(str) != decisions_df["selected_asset"].astype(str).shift(1)).sum() - 1
    ) if not decisions_df.empty else 0

    if not leaderboard_df.empty and "suspended" in leaderboard_df.columns:
        susp = leaderboard_df.groupby("asset", as_index=False)["suspended"].sum()
        prod_row["asset_suspensions_total"] = int(pd.to_numeric(susp["suspended"], errors="coerce").sum())
    else:
        prod_row["asset_suspensions_total"] = 0

    summary = pd.DataFrame([phase63_row, prod_row])

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

    latest_available_date = governance.index.max().strftime("%Y-%m-%d") if len(governance) else ""
    current_asset = str(governance["weekly_authorized_asset"].astype(str).iloc[-1]) if len(governance) else ""
    current_asset = current_asset if current_asset else "BASELINE"
    next_rebalance_date = compute_next_rebalance_date(decisions_df, gov_cfg.rebalance_every_days)

    latest_decision_date = ""
    latest_period_start = ""
    latest_period_end = ""
    latest_keep_reason = ""
    if not decisions_df.empty:
        latest_decision = decisions_df.iloc[-1]
        latest_decision_date = str(latest_decision.get("decision_date", ""))
        latest_period_start = str(latest_decision.get("period_start", ""))
        latest_period_end = str(latest_decision.get("period_end", ""))
        latest_keep_reason = str(latest_decision.get("keep_reason", ""))

    latest_leaderboard = pd.DataFrame()
    if not leaderboard_df.empty and latest_decision_date:
        latest_leaderboard = (
            leaderboard_df[leaderboard_df["decision_date"].astype(str) == latest_decision_date]
            .copy()
            .sort_values(
                by=["passed_filters", "score", "recent_total_delta_pct", "train_total_delta_pct"],
                ascending=[False, False, False, False],
                na_position="last",
            )
            .reset_index(drop=True)
        )

    latest_top10 = latest_leaderboard.head(10).copy() if not latest_leaderboard.empty else pd.DataFrame()

    suspended_assets = pd.DataFrame()
    if not latest_leaderboard.empty and "suspended" in latest_leaderboard.columns:
        suspended_assets = latest_leaderboard[latest_leaderboard["suspended"] == True].copy()
        suspended_assets = suspended_assets.sort_values(
            by=["suspended_until_rebalance_idx", "asset"],
            ascending=[False, True],
            na_position="last",
        ).reset_index(drop=True)

    latest_trend_row = trend_history.iloc[-1].to_dict() if not trend_history.empty else {}
    live_status = pd.DataFrame(
        [
            {
                "model": gov_cfg.profile_name,
                "latest_available_date": latest_available_date,
                "current_asset": current_asset,
                "latest_decision_date": latest_decision_date,
                "latest_period_start": latest_period_start,
                "latest_period_end": latest_period_end,
                "next_rebalance_date": next_rebalance_date,
                "latest_keep_reason": latest_keep_reason,
                "candidate_assets_loaded": len(asset_strategies),
                "failed_assets_count": len(failed_assets),
                "suspended_assets_now": int(len(suspended_assets)),
                "trend_score": float(latest_trend_row.get("trend_score", np.nan)),
                "trend_state_label": str(latest_trend_row.get("trend_state_label", "")),
                "buy_threshold": float(latest_trend_row.get("buy_threshold", 0.0)),
                "prev_trend_score": float(latest_trend_row.get("prev_trend_score", np.nan)),
                "crossed_up_today": bool(latest_trend_row.get("crossed_up_today", False)),
                "crossed_down_today": bool(latest_trend_row.get("crossed_down_today", False)),
                "trend_input_raw": float(latest_trend_row.get("trend_input_raw", np.nan)),
                "trend_threshold_raw": float(latest_trend_row.get("trend_threshold_raw", np.nan)),
                "trend_band": float(latest_trend_row.get("trend_band", np.nan)),
                "trend_score_raw": float(latest_trend_row.get("trend_score_raw", np.nan)),
                "trend_calc_date": str(latest_trend_row.get("trend_calc_date", "")),
            }
        ]
    )

    summary_path = PHASE66G_DIR / "phase66g_production_candidate_summary.csv"
    compare_path = PHASE66G_DIR / "phase66g_production_candidate_compare.csv"
    live_status_path = PHASE66G_DIR / "phase66g_live_status.csv"
    trend_history_path = PHASE66G_DIR / "phase66g_trend_barometer_history.csv"
    decisions_path = PHASE66G_DIR / "phase66g_production_candidate_decisions.csv"
    leaderboard_path = PHASE66G_DIR / "phase66g_production_candidate_leaderboard.csv"
    latest_top10_path = PHASE66G_DIR / "phase66g_latest_decision_top10.csv"
    suspended_now_path = PHASE66G_DIR / "phase66g_suspended_assets_now.csv"
    asset_quality_path = PHASE66G_DIR / "phase66g_production_candidate_asset_quality.csv"
    asset_usage_path = PHASE66G_DIR / "phase66g_production_candidate_asset_usage.csv"
    failed_assets_path = PHASE66G_DIR / "phase66g_production_candidate_failed_assets.csv"
    baseline_paper_path = PHASE66G_DIR / f"{CURRENT_WINNER_KEY}_paper.csv"
    production_paper_path = PHASE66G_DIR / f"{gov_cfg.profile_name}_paper.csv"
    manifest_path = PHASE66G_DIR / "phase66g_manifest.json"

    summary.to_csv(summary_path, index=False)
    summary.to_csv(compare_path, index=False)
    live_status.to_csv(live_status_path, index=False)
    trend_history.reset_index().rename(columns={trend_history.index.name or "index": "date"}).to_csv(trend_history_path, index=False)
    decisions_df.to_csv(decisions_path, index=False)
    leaderboard_df.to_csv(leaderboard_path, index=False)
    latest_top10.to_csv(latest_top10_path, index=False)
    suspended_assets.to_csv(suspended_now_path, index=False)
    pd.DataFrame(asset_quality_rows).to_csv(asset_quality_path, index=False)
    asset_usage.to_csv(asset_usage_path, index=False)
    pd.DataFrame(failed_assets).to_csv(failed_assets_path, index=False)

    baseline.reset_index().rename(columns={baseline.index.name or "index": "date"}).to_csv(baseline_paper_path, index=False)
    governance.reset_index().rename(columns={governance.index.name or "index": "date"}).to_csv(production_paper_path, index=False)

    manifest = {
        "phase": "phase66g_production_candidate_live",
        "baseline_model": CURRENT_WINNER_KEY,
        "baseline_paper": str(args.baseline_paper),
        "phase66f_summary": str(args.phase66f_summary),
        "drop_file": str(args.drop_file),
        "removed_assets": remove_assets,
        "candidate_assets_loaded": int(len(asset_strategies)),
        "candidate_assets_failed": int(len(failed_assets)),
        "winner_profile": asdict(gov_cfg),
        "current_asset": current_asset,
        "latest_available_date": latest_available_date,
        "latest_decision_date": latest_decision_date,
        "next_rebalance_date": next_rebalance_date,
        "trend_barometer_definition": {
            "trend_score": "clip((base_strength_lb - weak_base_threshold) / max(candidate_ret_min, candidate_risk_buffer, 1e-6), -1, 1)",
            "buy_threshold": 0.0,
            "zero_meaning": "core buy threshold crossed, not guaranteed execution",
            "state_labels": {
                "negativny": "trend_score <= -0.50",
                "pod_buy_hranicou": "-0.50 < trend_score < 0.0",
                "nad_buy_hranicou": "0.0 <= trend_score < 0.50",
                "pozitivny": "trend_score >= 0.50",
            },
            "source_column": "base_strength_lb",
            "threshold_source": "OverlayConfig.weak_base_threshold",
            "band_source": "max(OverlayConfig.candidate_ret_min, OverlayConfig.candidate_risk_buffer)",
        },
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "live_status_file": str(live_status_path),
        "trend_history_file": str(trend_history_path),
        "decisions_file": str(decisions_path),
        "leaderboard_file": str(leaderboard_path),
        "latest_top10_file": str(latest_top10_path),
        "suspended_now_file": str(suspended_now_path),
        "asset_quality_file": str(asset_quality_path),
        "asset_usage_file": str(asset_usage_path),
        "failed_assets_file": str(failed_assets_path),
        "baseline_paper_saved": str(baseline_paper_path),
        "production_paper_saved": str(production_paper_path),
        "notes": [
            "Produkčný kandidát z víťazného Phase66F soft_filters profilu.",
            "Rovnou exportuje aj live weekly selector stav.",
            "Current asset je based na poslednom dostupnom daily bare, nie na intraday live cene.",
            "Trend barometer je source-of-truth metric zo stratégie, nie app-side heuristika.",
            "Trend score 0.0 znamená core buy threshold, nie automatický buy execution.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE66G TOP RESULT ===")
    log(f"model: {gov_cfg.profile_name}")
    log(f"cagr_pct: {prod_row['cagr_pct']:.2f}")
    log(f"max_drawdown_pct: {prod_row['max_drawdown_pct']:.2f}")
    log(f"since2023_cagr_pct: {prod_row['since2023_cagr_pct']:.2f}")
    log(f"since2025_cagr_pct: {prod_row['since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_cagr_pct: {prod_row['delta_vs_phase63_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_since2023_cagr_pct: {prod_row['delta_vs_phase63_since2023_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_since2025_cagr_pct: {prod_row['delta_vs_phase63_since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_max_drawdown_pct: {prod_row['delta_vs_phase63_max_drawdown_pct']:.2f}")
    if phase66f_ref is not None:
        log(f"delta_vs_phase66f_soft_filters_cagr_pct: {prod_row['delta_vs_phase66f_soft_filters_cagr_pct']:.2f}")
        log(f"delta_vs_phase66f_soft_filters_since2023_cagr_pct: {prod_row['delta_vs_phase66f_soft_filters_since2023_cagr_pct']:.2f}")
        log(f"delta_vs_phase66f_soft_filters_since2025_cagr_pct: {prod_row['delta_vs_phase66f_soft_filters_since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase66f_soft_filters_max_drawdown_pct: {prod_row['delta_vs_phase66f_soft_filters_max_drawdown_pct']:.2f}")
    log(f"selection_count: {int(prod_row['selection_count'])}")
    log(f"switch_count: {int(prod_row['switch_count'])}")
    log(f"asset_suspensions_total: {int(prod_row['asset_suspensions_total'])}")
    log("")
    log("=== PHASE66G LIVE STATUS ===")
    log(f"latest_available_date: {latest_available_date}")
    log(f"current_asset: {current_asset}")
    log(f"latest_decision_date: {latest_decision_date}")
    log(f"next_rebalance_date: {next_rebalance_date}")
    log(f"suspended_assets_now: {len(suspended_assets)}")
    log(f"trend_score: {float(latest_trend_row.get('trend_score', np.nan)):.4f}")
    log(f"trend_state_label: {str(latest_trend_row.get('trend_state_label', ''))}")
    log(f"buy_threshold: {float(latest_trend_row.get('buy_threshold', 0.0)):.4f}")
    log(f"prev_trend_score: {float(latest_trend_row.get('prev_trend_score', np.nan)):.4f}")
    log(f"crossed_up_today: {bool(latest_trend_row.get('crossed_up_today', False))}")
    log(f"crossed_down_today: {bool(latest_trend_row.get('crossed_down_today', False))}")
    log("")

    log(f"[PHASE66G] Saved summary -> {summary_path}")
    log(f"[PHASE66G] Saved compare -> {compare_path}")
    log(f"[PHASE66G] Saved live status -> {live_status_path}")
    log(f"[PHASE66G] Saved trend history -> {trend_history_path}")
    log(f"[PHASE66G] Saved decisions -> {decisions_path}")
    log(f"[PHASE66G] Saved leaderboard -> {leaderboard_path}")
    log(f"[PHASE66G] Saved latest top10 -> {latest_top10_path}")
    log(f"[PHASE66G] Saved suspended now -> {suspended_now_path}")
    log(f"[PHASE66G] Saved asset quality -> {asset_quality_path}")
    log(f"[PHASE66G] Saved asset usage -> {asset_usage_path}")
    log(f"[PHASE66G] Saved failed assets -> {failed_assets_path}")
    log(f"[PHASE66G] Saved baseline paper -> {baseline_paper_path}")
    log(f"[PHASE66G] Saved production paper -> {production_paper_path}")
    log(f"[PHASE66G] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()