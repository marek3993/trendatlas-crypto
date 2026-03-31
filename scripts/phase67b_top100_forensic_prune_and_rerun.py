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

PHASE66G_SUMMARY = (
    OUTPUTS
    / "phase66g_production_candidate_live"
    / "phase66g_production_candidate_summary.csv"
)

PHASE67_SUMMARY = (
    OUTPUTS
    / "phase67_top100_build_and_governance"
    / "phase67_top100_production_summary.csv"
)

PHASE67_ASSET_QUALITY = (
    OUTPUTS
    / "phase67_top100_build_and_governance"
    / "phase67_top100_asset_quality.csv"
)

PHASE67B_DIR = OUTPUTS / "phase67b_top100_forensic_prune_and_rerun"


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_production_config(min_history_days: int) -> core.GovernanceConfig:
    return core.GovernanceConfig(
        profile_name="phase67b_top100_pruned_soft_filters",
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


def load_reference(summary_path: Path, model_name: str) -> dict | None:
    if not summary_path.exists():
        return None
    df = pd.read_csv(summary_path)
    df.columns = [str(c).strip() for c in df.columns]
    match = df[df["model"].astype(str) == model_name]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def add_delta_cols(row: dict, ref: dict | None, prefix: str) -> dict:
    out = row.copy()
    if ref is None:
        for metric in [
            "cagr_pct",
            "max_drawdown_pct",
            "since2021_cagr_pct",
            "since2023_cagr_pct",
            "since2025_cagr_pct",
        ]:
            out[f"delta_vs_{prefix}_{metric}"] = np.nan
        return out

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


def load_local_daily_for_core(path: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]
    if "date" not in df.columns or "close" not in df.columns:
        raise ValueError(f"{path.name}: missing date/close")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = (
        df.dropna(subset=["date", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )

    daily = df[["date", "close"]].rename(columns={"date": "ts"}).copy()
    daily["day"] = pd.to_datetime(daily["ts"]).dt.normalize()
    daily = daily.groupby("day", as_index=True)["close"].last().to_frame("candidate_close").sort_index()

    q = {
        "history_days": int((daily.index.max() - daily.index.min()).days + 1) if len(daily) else 0,
        "start_date": daily.index.min().date().isoformat() if len(daily) else "",
        "end_date": daily.index.max().date().isoformat() if len(daily) else "",
        "daily_rows": int(len(daily)),
        "max_gap_days": 0,
        "non_na_close_ratio": float(daily["candidate_close"].notna().mean()) * 100.0 if len(daily) else 0.0,
    }
    if len(daily) >= 2:
        gaps = pd.Series(daily.index).diff().dt.days.dropna()
        q["max_gap_days"] = int(gaps.max()) if not gaps.empty else 0
    return daily, q


def compute_asset_row(
    asset: str,
    strategy: pd.DataFrame,
    phase63_row: dict,
    phase66g_ref: dict | None,
) -> dict:
    row = core.calc_metrics(strategy, f"asset_{asset}")
    row.update(core.window_metrics(strategy, "2021-01-01"))
    row.update(core.window_metrics(strategy, "2023-01-01"))
    row.update(core.window_metrics(strategy, "2025-01-01"))
    row["asset"] = asset

    if "candidate_execute" in strategy.columns:
        row["candidate_days_pct"] = float(pd.to_numeric(strategy["candidate_execute"], errors="coerce").fillna(0.0).mean() * 100.0)
        row["trigger_days"] = int(pd.to_numeric(strategy["candidate_execute"], errors="coerce").fillna(0.0).sum())
    else:
        row["candidate_days_pct"] = np.nan
        row["trigger_days"] = np.nan

    row = add_delta_cols(row, phase63_row, "phase63")
    row = add_delta_cols(row, phase66g_ref, "phase66g")

    s2023 = pd.to_numeric(row.get("delta_vs_phase66g_since2023_cagr_pct"), errors="coerce")
    s2025 = pd.to_numeric(row.get("delta_vs_phase66g_since2025_cagr_pct"), errors="coerce")
    full = pd.to_numeric(row.get("delta_vs_phase66g_cagr_pct"), errors="coerce")
    dd = pd.to_numeric(row.get("delta_vs_phase66g_max_drawdown_pct"), errors="coerce")

    if pd.isna(s2023):
        s2023 = pd.to_numeric(row.get("delta_vs_phase63_since2023_cagr_pct"), errors="coerce")
    if pd.isna(s2025):
        s2025 = pd.to_numeric(row.get("delta_vs_phase63_since2025_cagr_pct"), errors="coerce")
    if pd.isna(full):
        full = pd.to_numeric(row.get("delta_vs_phase63_cagr_pct"), errors="coerce")
    if pd.isna(dd):
        dd = pd.to_numeric(row.get("delta_vs_phase63_max_drawdown_pct"), errors="coerce")

    score = (
        (0.0 if pd.isna(s2023) else s2023 * 2.0)
        + (0.0 if pd.isna(s2025) else s2025 * 1.25)
        + (0.0 if pd.isna(full) else full * 1.0)
        + (0.0 if pd.isna(dd) else dd * 0.6)
    )
    row["forensic_score"] = score

    row["keep_candidate"] = bool(
        (not pd.isna(pd.to_numeric(row.get("delta_vs_phase63_since2023_cagr_pct"), errors="coerce")))
        and (pd.to_numeric(row.get("delta_vs_phase63_since2023_cagr_pct"), errors="coerce") > 0.0)
        and (pd.to_numeric(row.get("delta_vs_phase63_since2025_cagr_pct"), errors="coerce") >= 0.0)
        and (pd.to_numeric(row.get("delta_vs_phase63_max_drawdown_pct"), errors="coerce") >= -8.0)
    )

    return row


def compute_next_rebalance_date(decisions_df: pd.DataFrame, rebalance_days: int) -> str:
    if decisions_df.empty or "decision_date" not in decisions_df.columns:
        return ""
    last_decision = pd.to_datetime(decisions_df["decision_date"], errors="coerce").dropna()
    if last_decision.empty:
        return ""
    return (last_decision.iloc[-1] + pd.Timedelta(days=rebalance_days)).strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE67B prune top100 first, then rerun governance")
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    parser.add_argument("--asset-quality-file", type=str, default=str(PHASE67_ASSET_QUALITY))
    parser.add_argument("--phase66g-summary", type=str, default=str(PHASE66G_SUMMARY))
    parser.add_argument("--phase67-summary", type=str, default=str(PHASE67_SUMMARY))
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--min-history-days", type=int, default=180)
    args = parser.parse_args()

    ensure_dir(PHASE67B_DIR)

    overlay_cfg = core.OverlayConfig()
    gov_cfg = build_production_config(args.min_history_days)

    phase66g_ref = load_reference(Path(args.phase66g_summary), "phase66g_production_soft_filters")
    phase67_ref = load_reference(Path(args.phase67_summary), "phase67_top100_production_soft_filters")

    log("[PHASE67B] Start")
    log(f"[PHASE67B] Baseline paper: {args.baseline_paper}")
    log(f"[PHASE67B] Asset quality file: {args.asset_quality_file}")

    baseline = core.load_baseline_paper(Path(args.baseline_paper), overlay_cfg)
    phase63_row = core.calc_metrics(baseline, CURRENT_WINNER_KEY)
    phase63_row.update(core.window_metrics(baseline, "2021-01-01"))
    phase63_row.update(core.window_metrics(baseline, "2023-01-01"))
    phase63_row.update(core.window_metrics(baseline, "2025-01-01"))
    phase63_row["mode"] = "baseline"

    aq = pd.read_csv(args.asset_quality_file)
    aq.columns = [str(c).strip() for c in aq.columns]
    if "asset" not in aq.columns or "file" not in aq.columns:
        raise ValueError("phase67 asset quality file must contain asset and file columns")

    asset_rows = []
    asset_strategies: dict[str, pd.DataFrame] = {}
    failed_assets = []

    for _, r in aq.iterrows():
        asset = str(r["asset"]).strip().upper()
        file_path = Path(str(r["file"]))
        try:
            daily, q = load_local_daily_for_core(file_path)
            if q["history_days"] < gov_cfg.min_history_days:
                continue

            strat = core.build_asset_strategy(baseline, daily, overlay_cfg, asset)
            asset_strategies[asset] = strat

            row = compute_asset_row(asset, strat, phase63_row, phase66g_ref)
            row["file"] = str(file_path)
            row["history_days"] = q["history_days"]
            row["start_date"] = q["start_date"]
            row["end_date"] = q["end_date"]
            row["cg_rank"] = r.get("cg_rank", np.nan)
            row["name"] = r.get("name", "")
            asset_rows.append(row)
        except Exception as e:
            failed_assets.append({"asset": asset, "file": str(file_path), "reason": str(e)})

    asset_forensic = pd.DataFrame(asset_rows)
    if asset_forensic.empty:
        raise RuntimeError("No asset forensic rows produced.")

    asset_forensic = asset_forensic.sort_values(
        by=[
            "keep_candidate",
            "forensic_score",
            "delta_vs_phase63_since2023_cagr_pct",
            "delta_vs_phase63_since2025_cagr_pct",
            "delta_vs_phase63_cagr_pct",
        ],
        ascending=[False, False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    kept = asset_forensic[asset_forensic["keep_candidate"] == True].copy()
    if kept.empty:
        shortlist = asset_forensic.head(args.top_n).copy()
    else:
        shortlist = kept.head(args.top_n).copy()

    shortlist_assets = shortlist["asset"].astype(str).tolist()
    pruned_strategies = {a: asset_strategies[a] for a in shortlist_assets if a in asset_strategies}

    log(f"[PHASE67B] Asset forensic rows: {len(asset_forensic)}")
    log(f"[PHASE67B] Shortlist assets: {shortlist_assets}")

    governance, decisions_df, leaderboard_df = core.simulate_governance_strategy_probation(
        baseline=baseline,
        asset_strategies=pruned_strategies,
        gov_cfg=gov_cfg,
    )

    prod_row = core.calc_metrics(governance, gov_cfg.profile_name)
    prod_row.update(core.window_metrics(governance, "2021-01-01"))
    prod_row.update(core.window_metrics(governance, "2023-01-01"))
    prod_row.update(core.window_metrics(governance, "2025-01-01"))
    prod_row["mode"] = gov_cfg.profile_name
    prod_row = add_delta_cols(prod_row, phase63_row, "phase63")
    prod_row = add_delta_cols(prod_row, phase66g_ref, "phase66g")
    prod_row = add_delta_cols(prod_row, phase67_ref, "phase67broad")

    selected_nonempty = governance["chosen_asset"].astype(str)
    prod_row["unique_selected_assets"] = int(selected_nonempty[selected_nonempty != ""].nunique())
    prod_row["selected_days_pct"] = float((selected_nonempty != "").mean() * 100.0)
    prod_row["decision_count"] = int(len(decisions_df))
    prod_row["selection_count"] = int(decisions_df["selected"].sum()) if not decisions_df.empty else 0
    prod_row["switch_count"] = int((decisions_df["selected_asset"].astype(str) != decisions_df["selected_asset"].astype(str).shift(1)).sum() - 1) if not decisions_df.empty else 0
    prod_row["shortlist_size"] = len(shortlist_assets)

    if not leaderboard_df.empty and "suspended" in leaderboard_df.columns:
        susp = leaderboard_df.groupby("asset", as_index=False)["suspended"].sum()
        prod_row["asset_suspensions_total"] = int(pd.to_numeric(susp["suspended"], errors="coerce").sum())
    else:
        prod_row["asset_suspensions_total"] = 0

    summary_rows = [phase63_row]
    if phase66g_ref is not None:
        summary_rows.append({"model": "phase66g_production_soft_filters_ref", **phase66g_ref})
    if phase67_ref is not None:
        summary_rows.append({"model": "phase67_top100_production_soft_filters_ref", **phase67_ref})
    summary_rows.append(prod_row)
    summary = pd.DataFrame(summary_rows)

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
                "shortlist_size": len(shortlist_assets),
                "current_shortlist_assets": ",".join(shortlist_assets),
                "failed_assets_count": len(failed_assets),
            }
        ]
    )

    forensic_path = PHASE67B_DIR / "phase67b_asset_forensic.csv"
    shortlist_path = PHASE67B_DIR / "phase67b_asset_shortlist.csv"
    summary_path = PHASE67B_DIR / "phase67b_pruned_production_summary.csv"
    compare_path = PHASE67B_DIR / "phase67b_pruned_production_compare.csv"
    live_status_path = PHASE67B_DIR / "phase67b_live_status.csv"
    decisions_path = PHASE67B_DIR / "phase67b_pruned_production_decisions.csv"
    leaderboard_path = PHASE67B_DIR / "phase67b_pruned_production_leaderboard.csv"
    latest_top10_path = PHASE67B_DIR / "phase67b_latest_decision_top10.csv"
    asset_usage_path = PHASE67B_DIR / "phase67b_pruned_asset_usage.csv"
    failed_assets_path = PHASE67B_DIR / "phase67b_failed_assets.csv"
    baseline_paper_path = PHASE67B_DIR / f"{CURRENT_WINNER_KEY}_paper.csv"
    production_paper_path = PHASE67B_DIR / f"{gov_cfg.profile_name}_paper.csv"
    manifest_path = PHASE67B_DIR / "phase67b_manifest.json"

    asset_forensic.to_csv(forensic_path, index=False)
    shortlist.to_csv(shortlist_path, index=False)
    summary.to_csv(summary_path, index=False)
    summary.to_csv(compare_path, index=False)
    live_status.to_csv(live_status_path, index=False)
    decisions_df.to_csv(decisions_path, index=False)
    leaderboard_df.to_csv(leaderboard_path, index=False)
    latest_top10.to_csv(latest_top10_path, index=False)
    asset_usage.to_csv(asset_usage_path, index=False)
    pd.DataFrame(failed_assets).to_csv(failed_assets_path, index=False)

    baseline.reset_index().rename(columns={baseline.index.name or "index": "date"}).to_csv(baseline_paper_path, index=False)
    governance.reset_index().rename(columns={governance.index.name or "index": "date"}).to_csv(production_paper_path, index=False)

    manifest = {
        "phase": "phase67b_top100_forensic_prune_and_rerun",
        "baseline_model": CURRENT_WINNER_KEY,
        "baseline_paper": str(args.baseline_paper),
        "phase66g_summary": str(args.phase66g_summary),
        "phase67_summary": str(args.phase67_summary),
        "asset_quality_file": str(args.asset_quality_file),
        "winner_profile": asdict(gov_cfg),
        "top_n": int(args.top_n),
        "shortlist_assets": shortlist_assets,
        "shortlist_size": len(shortlist_assets),
        "current_asset": current_asset,
        "latest_available_date": latest_available_date,
        "latest_decision_date": latest_decision_date,
        "next_rebalance_date": next_rebalance_date,
        "forensic_file": str(forensic_path),
        "shortlist_file": str(shortlist_path),
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "live_status_file": str(live_status_path),
        "decisions_file": str(decisions_path),
        "leaderboard_file": str(leaderboard_path),
        "latest_top10_file": str(latest_top10_path),
        "asset_usage_file": str(asset_usage_path),
        "failed_assets_file": str(failed_assets_path),
        "baseline_paper_saved": str(baseline_paper_path),
        "production_paper_saved": str(production_paper_path),
        "notes": [
            "2 kroky naraz: forensic prune top100 + rerun produkčného governance profilu.",
            "Shortlist sa tvorí z assetov, ktoré zlepšujú since2023, nekazia since2025 a príliš neškodia DD.",
            "Current asset je based na poslednom dostupnom daily bare.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE67B TOP RESULT ===")
    log(f"model: {gov_cfg.profile_name}")
    log(f"cagr_pct: {prod_row['cagr_pct']:.2f}")
    log(f"max_drawdown_pct: {prod_row['max_drawdown_pct']:.2f}")
    log(f"since2023_cagr_pct: {prod_row['since2023_cagr_pct']:.2f}")
    log(f"since2025_cagr_pct: {prod_row['since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase66g_cagr_pct: {prod_row['delta_vs_phase66g_cagr_pct']:.2f}")
    log(f"delta_vs_phase66g_since2023_cagr_pct: {prod_row['delta_vs_phase66g_since2023_cagr_pct']:.2f}")
    log(f"delta_vs_phase66g_since2025_cagr_pct: {prod_row['delta_vs_phase66g_since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase66g_max_drawdown_pct: {prod_row['delta_vs_phase66g_max_drawdown_pct']:.2f}")
    log(f"delta_vs_phase67broad_cagr_pct: {prod_row['delta_vs_phase67broad_cagr_pct']:.2f}")
    log(f"delta_vs_phase67broad_since2023_cagr_pct: {prod_row['delta_vs_phase67broad_since2023_cagr_pct']:.2f}")
    log(f"delta_vs_phase67broad_since2025_cagr_pct: {prod_row['delta_vs_phase67broad_since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase67broad_max_drawdown_pct: {prod_row['delta_vs_phase67broad_max_drawdown_pct']:.2f}")
    log(f"shortlist_size: {len(shortlist_assets)}")
    log(f"selection_count: {int(prod_row['selection_count'])}")
    log(f"switch_count: {int(prod_row['switch_count'])}")
    log("")

    log("=== PHASE67B SHORTLIST ===")
    for asset in shortlist_assets[:12]:
        log(asset)
    log("")

    log("=== PHASE67B LIVE STATUS ===")
    log(f"latest_available_date: {latest_available_date}")
    log(f"current_asset: {current_asset}")
    log(f"latest_decision_date: {latest_decision_date}")
    log(f"next_rebalance_date: {next_rebalance_date}")
    log("")

    log(f"[PHASE67B] Saved forensic -> {forensic_path}")
    log(f"[PHASE67B] Saved shortlist -> {shortlist_path}")
    log(f"[PHASE67B] Saved summary -> {summary_path}")
    log(f"[PHASE67B] Saved compare -> {compare_path}")
    log(f"[PHASE67B] Saved live status -> {live_status_path}")
    log(f"[PHASE67B] Saved decisions -> {decisions_path}")
    log(f"[PHASE67B] Saved leaderboard -> {leaderboard_path}")
    log(f"[PHASE67B] Saved latest top10 -> {latest_top10_path}")
    log(f"[PHASE67B] Saved asset usage -> {asset_usage_path}")
    log(f"[PHASE67B] Saved failed assets -> {failed_assets_path}")
    log(f"[PHASE67B] Saved baseline paper -> {baseline_paper_path}")
    log(f"[PHASE67B] Saved production paper -> {production_paper_path}")
    log(f"[PHASE67B] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()