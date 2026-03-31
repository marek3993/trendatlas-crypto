from __future__ import annotations

import argparse
import copy
import json
from dataclasses import asdict, dataclass
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
PHASE66J_DIR = OUTPUTS / "phase66j_core_reaction_sweep"


@dataclass(frozen=True)
class ReactionVariant:
    model: str
    candidate_fast_ma_delta: int
    candidate_slow_ma_delta: int
    candidate_ret_lb_delta: int
    candidate_risk_ma_delta: int


VARIANTS: list[ReactionVariant] = [
    ReactionVariant(
        model="phase66j_core_reaction_A",
        candidate_fast_ma_delta=-2,
        candidate_slow_ma_delta=0,
        candidate_ret_lb_delta=-5,
        candidate_risk_ma_delta=-5,
    ),
    ReactionVariant(
        model="phase66j_core_reaction_B",
        candidate_fast_ma_delta=-2,
        candidate_slow_ma_delta=-5,
        candidate_ret_lb_delta=-5,
        candidate_risk_ma_delta=-5,
    ),
    ReactionVariant(
        model="phase66j_core_reaction_C",
        candidate_fast_ma_delta=-4,
        candidate_slow_ma_delta=-5,
        candidate_ret_lb_delta=-10,
        candidate_risk_ma_delta=-5,
    ),
    ReactionVariant(
        model="phase66j_core_reaction_D",
        candidate_fast_ma_delta=-2,
        candidate_slow_ma_delta=0,
        candidate_ret_lb_delta=-10,
        candidate_risk_ma_delta=-10,
    ),
    ReactionVariant(
        model="phase66j_core_reaction_E",
        candidate_fast_ma_delta=0,
        candidate_slow_ma_delta=-5,
        candidate_ret_lb_delta=-10,
        candidate_risk_ma_delta=-10,
    ),
    ReactionVariant(
        model="phase66j_core_reaction_F",
        candidate_fast_ma_delta=-4,
        candidate_slow_ma_delta=-10,
        candidate_ret_lb_delta=-10,
        candidate_risk_ma_delta=-10,
    ),
]

SUCCESS_RULE = {
    "min_since2025_cagr_pct": 113.91,
    "max_cagr_drop_vs_66g_pct": -2.00,
    "max_dd_worsen_vs_66g_pct": -3.00,
    "max_switch_count_increase_pct": 25.0,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_winner_config(profile_name: str, min_history_days: int) -> core.GovernanceConfig:
    return core.GovernanceConfig(
        profile_name=profile_name,
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


def normalize_date_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    date_col = None
    for c in ["date", "Date", "datetime", "timestamp", "ts"]:
        if c in out.columns:
            date_col = c
            break
    if date_col is None:
        raise KeyError("Nenašiel sa date column v paper CSV.")
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=[date_col]).set_index(date_col).sort_index()
    out.index.name = "date"
    return out


def compute_next_rebalance_date(decisions_df: pd.DataFrame, rebalance_days: int) -> str:
    if decisions_df.empty or "decision_date" not in decisions_df.columns:
        return ""
    last_decision = pd.to_datetime(decisions_df["decision_date"], errors="coerce").dropna()
    if last_decision.empty:
        return ""
    next_dt = last_decision.iloc[-1] + pd.Timedelta(days=rebalance_days)
    return next_dt.strftime("%Y-%m-%d")


def safe_numeric(row: dict, key: str, default: float = np.nan) -> float:
    val = pd.to_numeric(row.get(key), errors="coerce")
    return float(val) if pd.notna(val) else float(default)


def clamp_int(value: int, minimum: int) -> int:
    return max(int(value), int(minimum))


def load_phase66g_reference(summary_path: Path, paper_path: Path) -> dict:
    if summary_path.exists():
        df = pd.read_csv(summary_path)
        df.columns = [str(c).strip() for c in df.columns]
        match = df[df["model"].astype(str) == "phase66g_production_soft_filters"]
        if not match.empty:
            row = match.iloc[0].to_dict()
            row["model"] = "phase66g_production_soft_filters"
            row["mode"] = "baseline_66g"
            row = add_delta_cols(row, row, "phase66g_core")
            return row

    if not paper_path.exists():
        raise FileNotFoundError(
            f"Nenašiel sa ani phase66g summary ani phase66g paper. "
            f"summary={summary_path} paper={paper_path}"
        )

    paper = normalize_date_index(pd.read_csv(paper_path))
    row = core.calc_metrics(paper, "phase66g_production_soft_filters")
    row.update(core.window_metrics(paper, "2021-01-01"))
    row.update(core.window_metrics(paper, "2023-01-01"))
    row.update(core.window_metrics(paper, "2025-01-01"))
    row["model"] = "phase66g_production_soft_filters"
    row["mode"] = "baseline_66g"

    chosen_col = "chosen_asset" if "chosen_asset" in paper.columns else "weekly_authorized_asset"
    chosen = paper[chosen_col].astype(str).replace("nan", "").fillna("")
    nonempty = chosen[chosen != ""]

    row["unique_selected_assets"] = int(nonempty.nunique())
    row["selected_days_pct"] = float((chosen != "").mean() * 100.0)
    row["decision_count"] = np.nan
    row["selection_count"] = int((chosen != "").sum())
    row["switch_count"] = int((chosen != chosen.shift(1)).sum() - 1)
    row["asset_suspensions_total"] = np.nan

    row = add_delta_cols(row, row, "phase66g_core")
    return row


def build_overlay_config(base_cfg: object, variant: ReactionVariant) -> object:
    cfg = copy.deepcopy(base_cfg)

    required_fields = [
        "candidate_fast_ma",
        "candidate_slow_ma",
        "candidate_ret_lb",
        "candidate_risk_ma",
        "candidate_risk_buffer",
        "candidate_ret_min",
        "weak_base_lb",
        "weak_base_threshold",
        "cooldown_days",
    ]
    for field in required_fields:
        if not hasattr(cfg, field):
            raise AttributeError(f"OverlayConfig nemá field '{field}'.")

    base_fast = int(getattr(base_cfg, "candidate_fast_ma"))
    base_slow = int(getattr(base_cfg, "candidate_slow_ma"))
    base_ret_lb = int(getattr(base_cfg, "candidate_ret_lb"))
    base_risk_ma = int(getattr(base_cfg, "candidate_risk_ma"))

    cfg.candidate_fast_ma = clamp_int(base_fast + variant.candidate_fast_ma_delta, 2)
    cfg.candidate_slow_ma = clamp_int(base_slow + variant.candidate_slow_ma_delta, cfg.candidate_fast_ma + 2)
    cfg.candidate_ret_lb = clamp_int(base_ret_lb + variant.candidate_ret_lb_delta, 5)
    cfg.candidate_risk_ma = clamp_int(base_risk_ma + variant.candidate_risk_ma_delta, 5)

    # 66J: permission a weak-base guardraily nechávame presne na baseline 66G
    cfg.candidate_risk_buffer = float(getattr(base_cfg, "candidate_risk_buffer"))
    cfg.candidate_ret_min = float(getattr(base_cfg, "candidate_ret_min"))
    cfg.weak_base_lb = int(getattr(base_cfg, "weak_base_lb"))
    cfg.weak_base_threshold = float(getattr(base_cfg, "weak_base_threshold"))
    cfg.cooldown_days = int(getattr(base_cfg, "cooldown_days"))

    return cfg


def load_asset_cache(
    best_files: dict[str, Path],
    remove_assets: set[str],
    min_history_days: int,
) -> tuple[dict[str, pd.DataFrame], list[dict], list[dict]]:
    allowed_assets = [asset for asset in sorted(best_files.keys()) if asset not in remove_assets]

    asset_daily_cache: dict[str, pd.DataFrame] = {}
    asset_quality_rows: list[dict] = []
    failed_assets: list[dict] = []

    for asset in allowed_assets:
        try:
            file_path = best_files[asset]
            daily, q = core.load_asset_daily_prices(file_path, "candidate_close")
            if q["history_days"] < min_history_days:
                continue
            asset_daily_cache[asset] = daily
            asset_quality_rows.append({"asset": asset, "file": str(file_path), **q})
        except Exception as e:
            failed_assets.append({"model": "asset_cache", "asset": asset, "reason": str(e)})

    return asset_daily_cache, asset_quality_rows, failed_assets


def run_variant(
    variant: ReactionVariant,
    baseline_paper_path: Path,
    base_overlay_cfg: object,
    asset_daily_cache: dict[str, pd.DataFrame],
    cached_quality_rows: list[dict],
    cache_failed_assets: list[dict],
    min_history_days: int,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, list[dict], list[dict], object]:
    overlay_cfg = build_overlay_config(base_overlay_cfg, variant)
    gov_cfg = build_winner_config(variant.model, min_history_days)

    baseline = core.load_baseline_paper(baseline_paper_path, overlay_cfg)

    asset_strategies: dict[str, pd.DataFrame] = {}
    asset_quality_rows: list[dict] = []
    failed_assets: list[dict] = list(cache_failed_assets)

    for q in cached_quality_rows:
        asset_quality_rows.append({"model": variant.model, **q})

    for asset, daily in asset_daily_cache.items():
        try:
            strat = core.build_asset_strategy(baseline, daily.copy(), overlay_cfg, asset)
            asset_strategies[asset] = strat
        except Exception as e:
            failed_assets.append({"model": variant.model, "asset": asset, "reason": str(e)})

    governance, decisions_df, leaderboard_df = core.simulate_governance_strategy_probation(
        baseline=baseline,
        asset_strategies=asset_strategies,
        gov_cfg=gov_cfg,
    )

    row = core.calc_metrics(governance, gov_cfg.profile_name)
    row.update(core.window_metrics(governance, "2021-01-01"))
    row.update(core.window_metrics(governance, "2023-01-01"))
    row.update(core.window_metrics(governance, "2025-01-01"))
    row["model"] = gov_cfg.profile_name
    row["mode"] = gov_cfg.profile_name

    chosen_nonempty = governance["chosen_asset"].astype(str)
    row["unique_selected_assets"] = int(chosen_nonempty[chosen_nonempty != ""].nunique())
    row["selected_days_pct"] = float((chosen_nonempty != "").mean() * 100.0)
    row["decision_count"] = int(len(decisions_df))
    row["selection_count"] = int(decisions_df["selected"].sum()) if not decisions_df.empty and "selected" in decisions_df.columns else 0
    row["switch_count"] = (
        int((decisions_df["selected_asset"].astype(str) != decisions_df["selected_asset"].astype(str).shift(1)).sum() - 1)
        if not decisions_df.empty and "selected_asset" in decisions_df.columns
        else 0
    )

    if not leaderboard_df.empty and "suspended" in leaderboard_df.columns:
        susp = leaderboard_df.groupby("asset", as_index=False)["suspended"].sum()
        row["asset_suspensions_total"] = int(pd.to_numeric(susp["suspended"], errors="coerce").sum())
    else:
        row["asset_suspensions_total"] = 0

    row["candidate_fast_ma"] = int(getattr(overlay_cfg, "candidate_fast_ma"))
    row["candidate_slow_ma"] = int(getattr(overlay_cfg, "candidate_slow_ma"))
    row["candidate_ret_lb"] = int(getattr(overlay_cfg, "candidate_ret_lb"))
    row["candidate_risk_ma"] = int(getattr(overlay_cfg, "candidate_risk_ma"))
    row["candidate_risk_buffer"] = float(getattr(overlay_cfg, "candidate_risk_buffer"))
    row["candidate_ret_min"] = float(getattr(overlay_cfg, "candidate_ret_min"))
    row["weak_base_lb"] = int(getattr(overlay_cfg, "weak_base_lb"))
    row["weak_base_threshold"] = float(getattr(overlay_cfg, "weak_base_threshold"))
    row["cooldown_days"] = int(getattr(overlay_cfg, "cooldown_days"))
    row["candidate_assets_loaded"] = int(len(asset_strategies))
    row["failed_assets_count"] = int(len(failed_assets))

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

    decisions_out = decisions_df.copy()
    if not decisions_out.empty:
        decisions_out.insert(0, "model", variant.model)

    leaderboard_out = leaderboard_df.copy()
    if not leaderboard_out.empty:
        leaderboard_out.insert(0, "model", variant.model)

    live_status_row = {
        "model": variant.model,
        "latest_available_date": latest_available_date,
        "current_asset": current_asset,
        "latest_decision_date": latest_decision_date,
        "latest_period_start": latest_period_start,
        "latest_period_end": latest_period_end,
        "next_rebalance_date": next_rebalance_date,
        "latest_keep_reason": latest_keep_reason,
        "candidate_assets_loaded": len(asset_strategies),
        "failed_assets_count": len(failed_assets),
        "suspended_assets_now": int(
            len(
                leaderboard_out[
                    (leaderboard_out["decision_date"].astype(str) == latest_decision_date)
                    & (leaderboard_out["suspended"] == True)
                ]
            )
        )
        if (
            not leaderboard_out.empty
            and "decision_date" in leaderboard_out.columns
            and "suspended" in leaderboard_out.columns
            and latest_decision_date
        )
        else 0,
    }

    return row, governance, decisions_out, leaderboard_out, live_status_row, asset_quality_rows, failed_assets, overlay_cfg


def build_pass_flag(row: pd.Series) -> bool:
    since2025 = pd.to_numeric(row.get("since2025_cagr_pct"), errors="coerce")
    delta_cagr = pd.to_numeric(row.get("delta_vs_phase66g_core_cagr_pct"), errors="coerce")
    delta_dd = pd.to_numeric(row.get("delta_vs_phase66g_core_max_drawdown_pct"), errors="coerce")
    switch_change = pd.to_numeric(row.get("switch_count_change_pct"), errors="coerce")

    if pd.isna(since2025) or pd.isna(delta_cagr) or pd.isna(delta_dd):
        return False
    if since2025 < SUCCESS_RULE["min_since2025_cagr_pct"]:
        return False
    if delta_cagr < SUCCESS_RULE["max_cagr_drop_vs_66g_pct"]:
        return False
    if delta_dd < SUCCESS_RULE["max_dd_worsen_vs_66g_pct"]:
        return False
    if pd.notna(switch_change) and switch_change > SUCCESS_RULE["max_switch_count_increase_pct"]:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE66J core reaction sweep over phase66e overlay config")
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    parser.add_argument("--drop-file", type=str, default=str(PHASE66B_DROP_CANDIDATES))
    parser.add_argument(
        "--phase66g-summary",
        type=str,
        default=str(PHASE66G_DIR / "phase66g_production_candidate_summary.csv"),
    )
    parser.add_argument(
        "--phase66g-paper",
        type=str,
        default=str(PHASE66G_DIR / "phase66g_production_soft_filters_paper.csv"),
    )
    parser.add_argument("--min-history-days", type=int, default=180)
    args = parser.parse_args()

    ensure_dir(PHASE66J_DIR)

    base_overlay_cfg = core.OverlayConfig()
    remove_assets = core.load_remove_assets(Path(args.drop_file))
    phase66g_ref = load_phase66g_reference(Path(args.phase66g_summary), Path(args.phase66g_paper))
    best_files = core.discover_best_file_per_asset()

    log("[PHASE66J] Start")
    log(f"[PHASE66J] Baseline paper: {args.baseline_paper}")
    log(f"[PHASE66J] Phase66G summary ref: {args.phase66g_summary}")
    log(f"[PHASE66J] Remove assets: {remove_assets}")
    log(
        "[PHASE66J] Fixed baseline permission/weak-base fields | "
        f"candidate_risk_buffer={getattr(base_overlay_cfg, 'candidate_risk_buffer')} "
        f"candidate_ret_min={getattr(base_overlay_cfg, 'candidate_ret_min')} "
        f"weak_base_lb={getattr(base_overlay_cfg, 'weak_base_lb')} "
        f"weak_base_threshold={getattr(base_overlay_cfg, 'weak_base_threshold')} "
        f"cooldown_days={getattr(base_overlay_cfg, 'cooldown_days')}"
    )

    asset_daily_cache, cache_quality_rows, cache_failed_assets = load_asset_cache(
        best_files=best_files,
        remove_assets=remove_assets,
        min_history_days=args.min_history_days,
    )
    log(f"[PHASE66J] Candidate assets cached: {len(asset_daily_cache)}")

    baseline_for_copy = core.load_baseline_paper(Path(args.baseline_paper), base_overlay_cfg)

    summary_rows: list[dict] = [phase66g_ref]
    decisions_all: list[pd.DataFrame] = []
    leaderboard_all: list[pd.DataFrame] = []
    live_status_rows: list[dict] = []
    asset_quality_all: list[dict] = []
    failed_assets_all: list[dict] = []
    governance_by_model: dict[str, pd.DataFrame] = {}

    for variant in VARIANTS:
        log(
            f"[PHASE66J] running {variant.model} | "
            f"fast_ma_delta={variant.candidate_fast_ma_delta:+d} "
            f"slow_ma_delta={variant.candidate_slow_ma_delta:+d} "
            f"ret_lb_delta={variant.candidate_ret_lb_delta:+d} "
            f"risk_ma_delta={variant.candidate_risk_ma_delta:+d}"
        )

        row, governance, decisions_df, leaderboard_df, live_status_row, asset_quality_rows, failed_assets, overlay_cfg = run_variant(
            variant=variant,
            baseline_paper_path=Path(args.baseline_paper),
            base_overlay_cfg=base_overlay_cfg,
            asset_daily_cache=asset_daily_cache,
            cached_quality_rows=cache_quality_rows,
            cache_failed_assets=cache_failed_assets,
            min_history_days=args.min_history_days,
        )

        row = add_delta_cols(row, phase66g_ref, "phase66g_core")
        summary_rows.append(row)
        governance_by_model[variant.model] = governance

        if not decisions_df.empty:
            decisions_all.append(decisions_df)
        if not leaderboard_df.empty:
            leaderboard_all.append(leaderboard_df)

        live_status_rows.append(live_status_row)
        asset_quality_all.extend(asset_quality_rows)
        failed_assets_all.extend(failed_assets)

        paper_path = PHASE66J_DIR / f"{variant.model}_paper.csv"
        governance.reset_index().rename(columns={governance.index.name or "index": "date"}).to_csv(paper_path, index=False)

        log(f"[PHASE66J] done {variant.model}")

    summary_df = pd.DataFrame(summary_rows)

    baseline_switch_count = safe_numeric(phase66g_ref, "switch_count")
    if pd.notna(baseline_switch_count) and baseline_switch_count != 0:
        summary_df["switch_count_change_pct"] = (
            (pd.to_numeric(summary_df["switch_count"], errors="coerce") - baseline_switch_count)
            / baseline_switch_count
            * 100.0
        )
    else:
        summary_df["switch_count_change_pct"] = np.nan

    summary_df["passes_success_rule"] = summary_df.apply(build_pass_flag, axis=1)

    compare_df = summary_df.copy()
    compare_df = compare_df.sort_values(
        by=[
            "passes_success_rule",
            "since2025_cagr_pct",
            "cagr_pct",
            "since2023_cagr_pct",
            "max_drawdown_pct",
        ],
        ascending=[False, False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    candidate_compare = compare_df[compare_df["model"].astype(str) != "phase66g_production_soft_filters"].copy()
    top_row = candidate_compare.iloc[0].to_dict() if not candidate_compare.empty else None
    top_model = str(top_row["model"]) if top_row is not None else ""

    decisions_combined = pd.concat(decisions_all, ignore_index=True) if decisions_all else pd.DataFrame()
    leaderboard_combined = pd.concat(leaderboard_all, ignore_index=True) if leaderboard_all else pd.DataFrame()
    live_status_df = pd.DataFrame(live_status_rows)

    latest_top10 = pd.DataFrame()
    suspended_assets_now = pd.DataFrame()

    if top_model and not leaderboard_combined.empty:
        top_live = live_status_df[live_status_df["model"].astype(str) == top_model]
        latest_decision_date = str(top_live["latest_decision_date"].iloc[0]) if not top_live.empty else ""
        board = leaderboard_combined[leaderboard_combined["model"].astype(str) == top_model].copy()

        if latest_decision_date and "decision_date" in board.columns:
            board = board[board["decision_date"].astype(str) == latest_decision_date].copy()

        if not board.empty:
            sort_cols = [c for c in ["passed_filters", "score", "recent_total_delta_pct", "train_total_delta_pct"] if c in board.columns]
            if sort_cols:
                board = board.sort_values(by=sort_cols, ascending=[False] * len(sort_cols), na_position="last").reset_index(drop=True)

        latest_top10 = board.head(10).copy() if not board.empty else pd.DataFrame()

        if not board.empty and "suspended" in board.columns:
            suspended_assets_now = board[board["suspended"] == True].copy()
            sort_cols = [c for c in ["suspended_until_rebalance_idx", "asset"] if c in suspended_assets_now.columns]
            if sort_cols:
                suspended_assets_now = suspended_assets_now.sort_values(
                    by=sort_cols,
                    ascending=[False if c == "suspended_until_rebalance_idx" else True for c in sort_cols],
                    na_position="last",
                ).reset_index(drop=True)

    asset_usage_rows: list[pd.DataFrame] = []
    for model, governance in governance_by_model.items():
        usage = (
            governance["chosen_asset"]
            .astype(str)
            .replace("", np.nan)
            .dropna()
            .value_counts()
            .rename_axis("asset")
            .reset_index(name="selected_days")
        )
        if not usage.empty:
            usage["selected_days_pct"] = usage["selected_days"] / len(governance) * 100.0
            usage["profile"] = model
            asset_usage_rows.append(usage)

    asset_usage_df = pd.concat(asset_usage_rows, ignore_index=True) if asset_usage_rows else pd.DataFrame()
    failed_assets_df = pd.DataFrame(failed_assets_all)
    asset_quality_df = pd.DataFrame(asset_quality_all)

    summary_path = PHASE66J_DIR / "phase66j_core_reaction_summary.csv"
    compare_path = PHASE66J_DIR / "phase66j_core_reaction_compare.csv"
    live_status_path = PHASE66J_DIR / "phase66j_live_status.csv"
    decisions_path = PHASE66J_DIR / "phase66j_core_reaction_decisions.csv"
    leaderboard_path = PHASE66J_DIR / "phase66j_core_reaction_leaderboard.csv"
    latest_top10_path = PHASE66J_DIR / "phase66j_latest_decision_top10.csv"
    suspended_now_path = PHASE66J_DIR / "phase66j_suspended_assets_now.csv"
    asset_quality_path = PHASE66J_DIR / "phase66j_core_reaction_asset_quality.csv"
    asset_usage_path = PHASE66J_DIR / "phase66j_core_reaction_asset_usage.csv"
    failed_assets_path = PHASE66J_DIR / "phase66j_core_reaction_failed_assets.csv"
    baseline_copy_path = PHASE66J_DIR / f"{CURRENT_WINNER_KEY}_paper.csv"
    manifest_path = PHASE66J_DIR / "phase66j_manifest.json"

    summary_df.to_csv(summary_path, index=False)
    compare_df.to_csv(compare_path, index=False)
    live_status_df.to_csv(live_status_path, index=False)
    decisions_combined.to_csv(decisions_path, index=False)
    leaderboard_combined.to_csv(leaderboard_path, index=False)
    latest_top10.to_csv(latest_top10_path, index=False)
    suspended_assets_now.to_csv(suspended_now_path, index=False)
    asset_quality_df.to_csv(asset_quality_path, index=False)
    asset_usage_df.to_csv(asset_usage_path, index=False)
    failed_assets_df.to_csv(failed_assets_path, index=False)
    baseline_for_copy.reset_index().rename(columns={baseline_for_copy.index.name or "index": "date"}).to_csv(baseline_copy_path, index=False)

    manifest = {
        "phase": "phase66j_core_reaction_sweep",
        "baseline_model": "phase66g_production_soft_filters",
        "baseline_input_paper": str(args.baseline_paper),
        "phase66g_summary_ref": str(args.phase66g_summary),
        "phase66g_paper_ref": str(args.phase66g_paper),
        "drop_file": str(args.drop_file),
        "removed_assets": sorted(list(remove_assets)),
        "candidate_assets_cached": int(len(asset_daily_cache)),
        "candidate_assets_cache_failed": int(len(cache_failed_assets)),
        "success_rule": SUCCESS_RULE,
        "fixed_overlay_fields_from_base": {
            "candidate_risk_buffer": float(getattr(base_overlay_cfg, "candidate_risk_buffer")),
            "candidate_ret_min": float(getattr(base_overlay_cfg, "candidate_ret_min")),
            "weak_base_lb": int(getattr(base_overlay_cfg, "weak_base_lb")),
            "weak_base_threshold": float(getattr(base_overlay_cfg, "weak_base_threshold")),
            "cooldown_days": int(getattr(base_overlay_cfg, "cooldown_days")),
        },
        "swept_overlay_fields": {
            "candidate_fast_ma_base": int(getattr(base_overlay_cfg, "candidate_fast_ma")),
            "candidate_slow_ma_base": int(getattr(base_overlay_cfg, "candidate_slow_ma")),
            "candidate_ret_lb_base": int(getattr(base_overlay_cfg, "candidate_ret_lb")),
            "candidate_risk_ma_base": int(getattr(base_overlay_cfg, "candidate_risk_ma")),
        },
        "variants": [asdict(v) for v in VARIANTS],
        "top_model": top_model,
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "live_status_file": str(live_status_path),
        "decisions_file": str(decisions_path),
        "leaderboard_file": str(leaderboard_path),
        "latest_top10_file": str(latest_top10_path),
        "suspended_now_file": str(suspended_now_path),
        "asset_quality_file": str(asset_quality_path),
        "asset_usage_file": str(asset_usage_path),
        "failed_assets_file": str(failed_assets_path),
        "baseline_paper_saved": str(baseline_copy_path),
        "notes": [
            "Phase66J nemení GovernanceConfig ani universe/drop logic.",
            "Phase66J nemení candidate_risk_buffer, candidate_ret_min, weak_base_lb, weak_base_threshold ani cooldown_days oproti baseline 66G.",
            "Sweepuje len candidate_fast_ma, candidate_slow_ma, candidate_ret_lb a candidate_risk_ma.",
            "Compare je robený len proti phase66g_production_soft_filters.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if top_row is not None:
        log("")
        log("=== PHASE66J TOP RESULT ===")
        log(f"model: {top_row['model']}")
        log(f"cagr_pct: {float(top_row['cagr_pct']):.2f}")
        log(f"max_drawdown_pct: {float(top_row['max_drawdown_pct']):.2f}")
        log(f"since2023_cagr_pct: {float(top_row['since2023_cagr_pct']):.2f}")
        log(f"since2025_cagr_pct: {float(top_row['since2025_cagr_pct']):.2f}")
        log(f"delta_vs_phase66g_core_cagr_pct: {float(top_row['delta_vs_phase66g_core_cagr_pct']):.2f}")
        log(f"delta_vs_phase66g_core_since2023_cagr_pct: {float(top_row['delta_vs_phase66g_core_since2023_cagr_pct']):.2f}")
        log(f"delta_vs_phase66g_core_since2025_cagr_pct: {float(top_row['delta_vs_phase66g_core_since2025_cagr_pct']):.2f}")
        log(f"delta_vs_phase66g_core_max_drawdown_pct: {float(top_row['delta_vs_phase66g_core_max_drawdown_pct']):.2f}")
        log(f"selection_count: {int(pd.to_numeric(top_row.get('selection_count'), errors='coerce'))}")
        log(f"switch_count: {int(pd.to_numeric(top_row.get('switch_count'), errors='coerce'))}")
        log(f"asset_suspensions_total: {int(pd.to_numeric(top_row.get('asset_suspensions_total'), errors='coerce'))}")
        log(f"candidate_fast_ma: {int(pd.to_numeric(top_row['candidate_fast_ma'], errors='coerce'))}")
        log(f"candidate_slow_ma: {int(pd.to_numeric(top_row['candidate_slow_ma'], errors='coerce'))}")
        log(f"candidate_ret_lb: {int(pd.to_numeric(top_row['candidate_ret_lb'], errors='coerce'))}")
        log(f"candidate_risk_ma: {int(pd.to_numeric(top_row['candidate_risk_ma'], errors='coerce'))}")
        log(f"passes_success_rule: {bool(top_row.get('passes_success_rule', False))}")
        log("")

        top_live = live_status_df[live_status_df["model"].astype(str) == top_model]
        if not top_live.empty:
            r = top_live.iloc[0]
            log("=== PHASE66J LIVE STATUS ===")
            log(f"latest_available_date: {r['latest_available_date']}")
            log(f"current_asset: {r['current_asset']}")
            log(f"latest_decision_date: {r['latest_decision_date']}")
            log(f"next_rebalance_date: {r['next_rebalance_date']}")
            log(f"suspended_assets_now: {int(pd.to_numeric(r['suspended_assets_now'], errors='coerce'))}")
            log("")

    log(f"[PHASE66J] Saved summary -> {summary_path}")
    log(f"[PHASE66J] Saved compare -> {compare_path}")
    log(f"[PHASE66J] Saved live status -> {live_status_path}")
    log(f"[PHASE66J] Saved decisions -> {decisions_path}")
    log(f"[PHASE66J] Saved leaderboard -> {leaderboard_path}")
    log(f"[PHASE66J] Saved latest top10 -> {latest_top10_path}")
    log(f"[PHASE66J] Saved suspended now -> {suspended_now_path}")
    log(f"[PHASE66J] Saved asset quality -> {asset_quality_path}")
    log(f"[PHASE66J] Saved asset usage -> {asset_usage_path}")
    log(f"[PHASE66J] Saved failed assets -> {failed_assets_path}")
    log(f"[PHASE66J] Saved baseline paper -> {baseline_copy_path}")
    log(f"[PHASE66J] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()