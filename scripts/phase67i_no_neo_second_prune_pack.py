from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

import phase66e_probation_governance as core


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

CORE_MODEL_KEY = "phase66g_production_soft_filters"
CORE_PAPER = (
    OUTPUTS
    / "phase66g_production_candidate_live"
    / f"{CORE_MODEL_KEY}_paper.csv"
)

PHASE63_MODEL_KEY = core.CURRENT_WINNER_KEY
PHASE63_PAPER = core.CURRENT_WINNER_PAPER

PHASE67B_SHORTLIST = (
    OUTPUTS
    / "phase67b_top100_forensic_prune_and_rerun"
    / "phase67b_asset_shortlist.csv"
)

PHASE67I_DIR = OUTPUTS / "phase67i_no_neo_second_prune_pack"


@dataclass
class ChallengerOverlayConfig:
    score_lb: int
    fast_ma: int
    slow_ma: int
    min_score: float
    edge_vs_core: float
    risk_ma: int
    risk_buffer: float
    vol_lb: int
    vol_cap: float
    rel_recent_lb: int
    rel_recent_min_edge: float
    cooldown_days: int


@dataclass
class WeeklyGovernanceConfig:
    profile_name: str
    trailing_train_days: int
    recent_days: int
    rebalance_every_days: int
    min_triggers_in_train: int
    min_total_delta_pct: float
    min_recent_delta_pct: float
    max_allowed_dd_worsen_pct: float
    switch_score_margin: float
    min_hold_periods: int
    probation_lookback_days: int
    probation_min_delta_pct: float
    probation_ban_periods: int

    promotion_margin_pct: float
    persistence_weeks: int
    reentry_cooldown_days: int
    downside_lookback_days: int
    downside_max_worsen_pct: float
    bnb_shield_margin_pct: float


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def detect_position_column(df: pd.DataFrame) -> str | None:
    preferred = [
        "executed_position",
        "final_position",
        "signal_position",
        "position",
        "selected_symbol",
        "symbol",
        "asset",
    ]
    for col in preferred:
        if col in df.columns:
            return col
    for col in df.columns:
        lc = str(col).lower()
        if "position" in lc or "symbol" in lc or "asset" in lc:
            return col
    return None


def load_strategy_paper(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing paper: {path}")

    raw = pd.read_csv(path)
    raw = normalize_columns(raw)

    if "date" not in raw.columns:
        raise ValueError(f"{path.name}: missing date column")

    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    raw = raw.set_index("date")

    required_numeric = ["strategy_return", "equity"]
    for col in required_numeric:
        if col not in raw.columns:
            raise ValueError(f"{path.name}: missing {col}")

    regime_col = "executed_regime" if "executed_regime" in raw.columns else "final_regime"
    if regime_col not in raw.columns:
        raise ValueError(f"{path.name}: missing executed_regime/final_regime")

    pos_col = detect_position_column(raw)
    if pos_col is None:
        raise ValueError(f"{path.name}: missing position column")

    out = pd.DataFrame(index=raw.index.copy())
    out["strategy_return"] = pd.to_numeric(raw["strategy_return"], errors="coerce").fillna(0.0)
    out["equity"] = pd.to_numeric(raw["equity"], errors="coerce").ffill().bfill()
    out["executed_regime"] = raw[regime_col].astype(str).fillna("NA").str.upper()
    out["executed_position"] = raw[pos_col].astype(str).fillna("NA").str.upper().str.strip()
    return out


def load_local_daily_for_core(path: Path) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(path)
    df = normalize_columns(df)
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


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if years <= 0:
        return 0.0
    if total_return <= -1:
        return -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def max_drawdown_from_equity(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def sharpe_ratio(daily_ret: pd.Series) -> float:
    x = pd.to_numeric(daily_ret, errors="coerce").dropna()
    if len(x) < 2:
        return 0.0
    vol = x.std(ddof=0)
    if vol == 0 or np.isnan(vol):
        return 0.0
    return float((x.mean() / vol) * np.sqrt(365.25))


def sortino_ratio(daily_ret: pd.Series) -> float:
    x = pd.to_numeric(daily_ret, errors="coerce").dropna()
    if len(x) < 2:
        return 0.0
    downside = x[x < 0]
    if len(downside) == 0:
        return 0.0
    dd = downside.std(ddof=0)
    if dd == 0 or np.isnan(dd):
        return 0.0
    return float((x.mean() / dd) * np.sqrt(365.25))


def calc_metrics(df: pd.DataFrame, model_name: str) -> dict:
    x = df.copy()
    x["strategy_return"] = pd.to_numeric(x["strategy_return"], errors="coerce").fillna(0.0)
    x["equity"] = (1.0 + x["strategy_return"]).cumprod()

    total_return = float(x["equity"].iloc[-1] / x["equity"].iloc[0] - 1.0) if len(x) > 1 else 0.0
    cagr = annualize_return(total_return, len(x))
    max_dd = max_drawdown_from_equity(x["equity"])
    sharpe = sharpe_ratio(x["strategy_return"])
    sortino = sortino_ratio(x["strategy_return"])

    out = {
        "model": model_name,
        "days": int(len(x)),
        "total_return_pct": total_return * 100.0,
        "cagr_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
        "sharpe": sharpe,
        "sortino": sortino,
    }
    if "executed_regime" in x.columns:
        r = x["executed_regime"].astype(str).fillna("NA")
        out["cash_days_pct"] = float((r == "CASH").mean() * 100.0)
        out["btc_days_pct"] = float((r == "BTC").mean() * 100.0)
        out["base_days_pct"] = float((r == "BASE").mean() * 100.0)
        out["candidate_days_pct"] = float((r == "CANDIDATE").mean() * 100.0)
    if "executed_position" in x.columns:
        p = x["executed_position"].astype(str).fillna("NA")
        out["trade_count"] = int((p != p.shift(1)).sum() - 1) if len(p) else 0
    return out


def window_metrics(df: pd.DataFrame, start_date: str) -> dict:
    sub = df[df.index >= pd.Timestamp(start_date)].copy()
    if sub.empty:
        return {
            f"since{start_date[:4]}_total_return_pct": np.nan,
            f"since{start_date[:4]}_cagr_pct": np.nan,
            f"since{start_date[:4]}_max_drawdown_pct": np.nan,
        }
    m = calc_metrics(sub, f"since{start_date[:4]}")
    return {
        f"since{start_date[:4]}_total_return_pct": m["total_return_pct"],
        f"since{start_date[:4]}_cagr_pct": m["cagr_pct"],
        f"since{start_date[:4]}_max_drawdown_pct": m["max_drawdown_pct"],
    }


def rolling_compound_return(ret: pd.Series, lb: int) -> pd.Series:
    return (1.0 + ret).rolling(lb, min_periods=lb).apply(np.prod, raw=True) - 1.0


def align_candidate_to_core(core_df: pd.DataFrame, candidate_daily: pd.DataFrame) -> pd.DataFrame:
    x = core_df.copy()
    c = candidate_daily.copy().reindex(x.index)
    c["candidate_close"] = c["candidate_close"].ffill()
    x["candidate_close"] = c["candidate_close"]
    x["candidate_return"] = x["candidate_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return x


def compute_candidate_signal(df: pd.DataFrame, cfg: ChallengerOverlayConfig) -> pd.DataFrame:
    x = df.copy()

    x["core_score"] = rolling_compound_return(x["strategy_return"], cfg.score_lb)
    x["cand_score"] = x["candidate_close"].pct_change(cfg.score_lb)
    x["cand_recent_rel"] = x["candidate_close"].pct_change(cfg.rel_recent_lb) - x["equity"].pct_change(cfg.rel_recent_lb)

    x["cand_fast_ma"] = x["candidate_close"].rolling(cfg.fast_ma, min_periods=cfg.fast_ma).mean()
    x["cand_slow_ma"] = x["candidate_close"].rolling(cfg.slow_ma, min_periods=cfg.slow_ma).mean()
    x["cand_risk_ma"] = x["candidate_close"].rolling(cfg.risk_ma, min_periods=cfg.risk_ma).mean()
    x["cand_vol"] = x["candidate_return"].rolling(cfg.vol_lb, min_periods=cfg.vol_lb).std(ddof=0)

    x["cand_trend_ok"] = (
        (x["candidate_close"] > x["cand_fast_ma"])
        & (x["cand_fast_ma"] > x["cand_slow_ma"])
        & (x["cand_score"] >= cfg.min_score)
    )

    x["cand_risk_off"] = (
        (x["candidate_close"] < (x["cand_risk_ma"] * (1.0 + cfg.risk_buffer)))
        | (x["cand_vol"] > cfg.vol_cap)
    )

    x["cand_beats_core"] = x["cand_score"] >= (x["core_score"] + cfg.edge_vs_core)
    x["cand_recent_rel_ok"] = x["cand_recent_rel"] >= cfg.rel_recent_min_edge

    x["candidate_signal_raw"] = (
        x["cand_trend_ok"].fillna(False)
        & (~x["cand_risk_off"].fillna(True))
        & x["cand_beats_core"].fillna(False)
        & x["cand_recent_rel_ok"].fillna(False)
        & x["candidate_close"].notna()
    )

    raw = x["candidate_signal_raw"].fillna(False).astype(bool).values
    if cfg.cooldown_days > 0:
        locked = np.zeros(len(raw), dtype=bool)
        hold = 0
        for i, flag in enumerate(raw):
            if flag:
                hold = cfg.cooldown_days
            elif hold > 0:
                hold -= 1
            locked[i] = flag or hold > 0
        x["candidate_signal"] = locked
    else:
        x["candidate_signal"] = raw

    x["candidate_execute"] = pd.Series(x["candidate_signal"], index=x.index).shift(1, fill_value=False)
    return x


def build_asset_overlay_strategy(
    core_df: pd.DataFrame,
    candidate_daily: pd.DataFrame,
    cfg: ChallengerOverlayConfig,
    asset: str,
) -> pd.DataFrame:
    x = align_candidate_to_core(core_df, candidate_daily)
    x = compute_candidate_signal(x, cfg)

    out = x.copy()
    out["executed_regime"] = np.where(out["candidate_execute"], "CANDIDATE", out["executed_regime"])
    out["executed_position"] = np.where(out["candidate_execute"], asset, out["executed_position"])
    out["strategy_return"] = np.where(out["candidate_execute"], out["candidate_return"], out["strategy_return"])
    out["equity"] = (1.0 + pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)).cumprod()
    return out


def slice_metrics_from_returns(returns: pd.Series) -> tuple[float, float]:
    x = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if len(x) == 0:
        return np.nan, np.nan
    eq = (1.0 + x).cumprod()
    total = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0
    dd = max_drawdown_from_equity(eq)
    return total * 100.0, dd * 100.0


def build_rebalance_dates(index: pd.DatetimeIndex, train_days: int, step_days: int) -> list[pd.Timestamp]:
    dates = []
    if len(index) <= train_days:
        return dates
    pos = train_days
    while pos < len(index) - 1:
        dates.append(index[pos])
        pos += step_days
    return dates


def periods_from_days(days: int, rebalance_every_days: int) -> int:
    if days <= 0:
        return 0
    return max(1, int(np.ceil(days / rebalance_every_days)))


def position_is_bnb(pos: object) -> bool:
    s = str(pos).upper()
    return "BNB" in s


def evaluate_asset_for_date(
    asset: str,
    decision_date: pd.Timestamp,
    core_df: pd.DataFrame,
    asset_strategies: dict[str, pd.DataFrame],
    gov_cfg: WeeklyGovernanceConfig,
) -> dict:
    idx = core_df.index
    decision_loc = idx.get_loc(decision_date)
    train_start_loc = max(0, decision_loc - gov_cfg.trailing_train_days + 1)
    recent_start_loc = max(0, decision_loc - gov_cfg.recent_days + 1)
    downside_start_loc = max(0, decision_loc - gov_cfg.downside_lookback_days + 1)

    train_idx = idx[train_start_loc:decision_loc + 1]
    recent_idx = idx[recent_start_loc:decision_loc + 1]
    downside_idx = idx[downside_start_loc:decision_loc + 1]

    df = asset_strategies[asset]

    core_train_total, core_train_dd = slice_metrics_from_returns(core_df.loc[train_idx, "strategy_return"])
    core_recent_total, _ = slice_metrics_from_returns(core_df.loc[recent_idx, "strategy_return"])
    _, core_downside_dd = slice_metrics_from_returns(core_df.loc[downside_idx, "strategy_return"])

    train_total, train_dd = slice_metrics_from_returns(df.loc[train_idx, "strategy_return"])
    recent_total, _ = slice_metrics_from_returns(df.loc[recent_idx, "strategy_return"])
    _, cand_downside_dd = slice_metrics_from_returns(df.loc[downside_idx, "strategy_return"])

    train_delta = train_total - core_train_total
    recent_delta = recent_total - core_recent_total
    dd_worsen = train_dd - core_train_dd
    downside_dd_worsen = cand_downside_dd - core_downside_dd
    triggers = int(pd.to_numeric(df.loc[train_idx, "candidate_execute"], errors="coerce").fillna(0.0).sum())

    passed = (
        triggers >= gov_cfg.min_triggers_in_train
        and train_delta >= gov_cfg.min_total_delta_pct
        and recent_delta >= gov_cfg.min_recent_delta_pct
        and recent_delta >= gov_cfg.promotion_margin_pct
        and dd_worsen <= gov_cfg.max_allowed_dd_worsen_pct
        and downside_dd_worsen <= gov_cfg.downside_max_worsen_pct
    )

    score = (
        (recent_delta * 4.0)
        + (train_delta * 1.5)
        - max(0.0, dd_worsen) * 1.25
        - max(0.0, downside_dd_worsen) * 1.50
        + triggers * 0.15
    )

    return {
        "asset": asset,
        "train_total_delta_pct": train_delta,
        "recent_total_delta_pct": recent_delta,
        "train_dd_worsen_pct": dd_worsen,
        "downside_dd_worsen_pct": downside_dd_worsen,
        "train_triggers": triggers,
        "score": score,
        "passed_filters": passed,
    }


def simulate_weekly_challenger_governance(
    core_df: pd.DataFrame,
    asset_strategies: dict[str, pd.DataFrame],
    gov_cfg: WeeklyGovernanceConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    idx = core_df.index
    rebalance_dates = build_rebalance_dates(idx, gov_cfg.trailing_train_days, gov_cfg.rebalance_every_days)

    governance = core_df.copy()
    governance["chosen_asset"] = ""
    governance["weekly_authorized_asset"] = ""
    governance["strategy_return"] = pd.to_numeric(governance["strategy_return"], errors="coerce").fillna(0.0)
    governance["executed_regime"] = governance["executed_regime"].astype(str)
    governance["executed_position"] = governance["executed_position"].astype(str)

    decision_rows = []
    leaderboard_rows = []

    incumbent_asset = ""
    incumbent_hold_periods = 0
    suspended_until: dict[str, int] = {}
    blocked_reentry_until: dict[str, int] = {}
    consecutive_passes: dict[str, int] = {}

    reentry_cooldown_periods = periods_from_days(gov_cfg.reentry_cooldown_days, gov_cfg.rebalance_every_days)
    assets = sorted(asset_strategies.keys())

    for i, decision_date in enumerate(rebalance_dates):
        start_loc = idx.get_loc(decision_date) + 1
        if start_loc >= len(idx):
            continue

        if i + 1 < len(rebalance_dates):
            next_date = rebalance_dates[i + 1]
            end_loc = idx.get_loc(next_date)
        else:
            next_date = idx[-1]
            end_loc = len(idx)

        core_asset_today = str(core_df.loc[decision_date, "executed_position"]).upper() if decision_date in core_df.index else ""
        core_is_bnb = position_is_bnb(core_asset_today)

        eval_rows = []
        for asset in assets:
            meta = evaluate_asset_for_date(asset, decision_date, core_df, asset_strategies, gov_cfg)

            decision_loc = idx.get_loc(decision_date)
            probation_start_loc = max(0, decision_loc - gov_cfg.probation_lookback_days + 1)
            probation_idx = idx[probation_start_loc:decision_loc + 1]

            asset_df = asset_strategies[asset]
            asset_prob_total, _ = slice_metrics_from_returns(asset_df.loc[probation_idx, "strategy_return"])
            core_prob_total, _ = slice_metrics_from_returns(core_df.loc[probation_idx, "strategy_return"])
            probation_delta = asset_prob_total - core_prob_total

            suspended = suspended_until.get(asset, -1) >= i
            if probation_delta < gov_cfg.probation_min_delta_pct and not suspended:
                suspended_until[asset] = i + gov_cfg.probation_ban_periods - 1
                suspended = True

            reentry_blocked = blocked_reentry_until.get(asset, -1) >= i and asset != incumbent_asset

            if bool(meta["passed_filters"]):
                consecutive_passes[asset] = consecutive_passes.get(asset, 0) + 1
            else:
                consecutive_passes[asset] = 0

            persistence_ok = consecutive_passes.get(asset, 0) >= gov_cfg.persistence_weeks
            required_recent_delta = gov_cfg.promotion_margin_pct + (gov_cfg.bnb_shield_margin_pct if core_is_bnb else 0.0)
            promotion_ok = float(meta["recent_total_delta_pct"]) >= required_recent_delta

            if suspended or reentry_blocked or (not persistence_ok) or (not promotion_ok):
                meta["passed_filters"] = False
                meta["score"] = -1e18

            meta["profile"] = gov_cfg.profile_name
            meta["decision_date"] = decision_date.strftime("%Y-%m-%d")
            meta["next_date_exclusive"] = next_date.strftime("%Y-%m-%d")
            meta["probation_delta_pct"] = probation_delta
            meta["suspended"] = suspended
            meta["reentry_blocked"] = reentry_blocked
            meta["persistence_passes"] = consecutive_passes.get(asset, 0)
            meta["persistence_ok"] = persistence_ok
            meta["core_asset_today"] = core_asset_today
            meta["core_is_bnb"] = core_is_bnb
            meta["required_recent_delta_pct"] = required_recent_delta
            meta["promotion_ok"] = promotion_ok
            meta["suspended_until_rebalance_idx"] = suspended_until.get(asset, -1)
            meta["reentry_blocked_until_rebalance_idx"] = blocked_reentry_until.get(asset, -1)

            eval_rows.append(meta)

        leaderboard = pd.DataFrame(eval_rows).sort_values(
            by=["passed_filters", "score", "recent_total_delta_pct", "train_total_delta_pct"],
            ascending=[False, False, False, False],
            na_position="last",
        ).reset_index(drop=True)

        best_asset = ""
        best_meta = {}
        passed_df = leaderboard[leaderboard["passed_filters"] == True]
        if not passed_df.empty:
            best_asset = str(passed_df.iloc[0]["asset"])
            best_meta = passed_df.iloc[0].to_dict()

        selected_asset = best_asset
        keep_reason = "best_passed"

        incumbent_meta = None
        if incumbent_asset and not leaderboard.empty:
            incumbent_rows = leaderboard[leaderboard["asset"] == incumbent_asset]
            if not incumbent_rows.empty:
                incumbent_meta = incumbent_rows.iloc[0].to_dict()

        if incumbent_asset and incumbent_meta is not None and bool(incumbent_meta.get("passed_filters", False)):
            incumbent_score = float(pd.to_numeric(incumbent_meta.get("score"), errors="coerce"))
            best_score = float(pd.to_numeric(best_meta.get("score"), errors="coerce")) if best_asset else -1e18

            if incumbent_hold_periods < gov_cfg.min_hold_periods:
                selected_asset = incumbent_asset
                keep_reason = "min_hold"
            elif not best_asset:
                selected_asset = incumbent_asset
                keep_reason = "incumbent_only_passed"
            elif best_asset != incumbent_asset and best_score < incumbent_score + gov_cfg.switch_score_margin:
                selected_asset = incumbent_asset
                keep_reason = "switch_margin_not_met"
            elif best_asset == incumbent_asset:
                selected_asset = incumbent_asset
                keep_reason = "incumbent_best"

        if incumbent_asset and selected_asset != incumbent_asset and reentry_cooldown_periods > 0:
            blocked_reentry_until[incumbent_asset] = i + reentry_cooldown_periods - 1

        leaderboard["incumbent_asset_before"] = incumbent_asset
        leaderboard["selected_asset"] = selected_asset
        leaderboard["keep_reason"] = keep_reason
        leaderboard_rows.append(leaderboard)

        period_idx = idx[start_loc:end_loc]
        if len(period_idx) == 0:
            continue

        governance.loc[period_idx, "weekly_authorized_asset"] = selected_asset

        if selected_asset:
            chosen_df = asset_strategies[selected_asset]
            governance.loc[period_idx, "strategy_return"] = chosen_df.loc[period_idx, "strategy_return"].values
            governance.loc[period_idx, "executed_regime"] = chosen_df.loc[period_idx, "executed_regime"].values
            governance.loc[period_idx, "executed_position"] = chosen_df.loc[period_idx, "executed_position"].values
            governance.loc[period_idx, "chosen_asset"] = selected_asset

        decision_rows.append(
            {
                "profile": gov_cfg.profile_name,
                "decision_date": decision_date.strftime("%Y-%m-%d"),
                "period_start": period_idx[0].strftime("%Y-%m-%d"),
                "period_end": period_idx[-1].strftime("%Y-%m-%d"),
                "incumbent_asset_before": incumbent_asset,
                "incumbent_hold_periods_before": incumbent_hold_periods,
                "core_asset_today": core_asset_today,
                "core_is_bnb": core_is_bnb,
                "selected_asset": selected_asset,
                "selected": bool(selected_asset),
                "keep_reason": keep_reason,
                "best_passed_asset": best_asset,
                "best_passed_score": pd.to_numeric(best_meta.get("score"), errors="coerce") if best_asset else np.nan,
                "required_recent_delta_pct": required_recent_delta,
            }
        )

        if selected_asset:
            if selected_asset == incumbent_asset:
                incumbent_hold_periods += 1
            else:
                incumbent_asset = selected_asset
                incumbent_hold_periods = 1
        else:
            incumbent_asset = ""
            incumbent_hold_periods = 0

    governance["equity"] = (1.0 + pd.to_numeric(governance["strategy_return"], errors="coerce").fillna(0.0)).cumprod()

    decisions_df = pd.DataFrame(decision_rows)
    leaderboard_df = pd.concat(leaderboard_rows, ignore_index=True) if leaderboard_rows else pd.DataFrame()

    return governance, decisions_df, leaderboard_df


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


def load_shortlist(shortlist_path: Path) -> list[dict]:
    if not shortlist_path.exists():
        raise FileNotFoundError(f"Missing shortlist: {shortlist_path}")
    df = pd.read_csv(shortlist_path)
    df = normalize_columns(df)
    if "asset" not in df.columns or "file" not in df.columns:
        raise ValueError("Shortlist file must contain asset and file columns")
    return df.to_dict("records")


def maybe_drop_assets(shortlist: list[dict], drops: list[str]) -> list[dict]:
    drop_set = {x.upper() for x in drops}
    return [row for row in shortlist if str(row["asset"]).upper() not in drop_set]


def build_profiles() -> list[tuple[ChallengerOverlayConfig, WeeklyGovernanceConfig, list[str]]]:
    common_overlay = dict(
        score_lb=30,
        fast_ma=20,
        slow_ma=100,
        min_score=0.12,
        edge_vs_core=0.03,
        risk_ma=150,
        risk_buffer=-0.03,
        vol_lb=30,
        vol_cap=0.045,
        rel_recent_lb=30,
        rel_recent_min_edge=0.00,
        cooldown_days=3,
    )

    common_governance = dict(
        trailing_train_days=365,
        recent_days=42,
        rebalance_every_days=7,
        min_triggers_in_train=3,
        min_total_delta_pct=0.0,
        min_recent_delta_pct=0.0,
        max_allowed_dd_worsen_pct=6.0,
        switch_score_margin=2.0,
        min_hold_periods=2,
        probation_lookback_days=45,
        probation_min_delta_pct=-0.5,
        probation_ban_periods=4,
        promotion_margin_pct=2.0,
        persistence_weeks=2,
        reentry_cooldown_days=7,
        downside_lookback_days=42,
        downside_max_worsen_pct=2.5,
        bnb_shield_margin_pct=1.0,
    )

    return [
        (
            ChallengerOverlayConfig(**common_overlay),
            WeeklyGovernanceConfig(
                profile_name="phase67i_keep_drop_neo_baseline",
                **common_governance,
            ),
            ["NEO"],
        ),
        (
            ChallengerOverlayConfig(**common_overlay),
            WeeklyGovernanceConfig(
                profile_name="phase67i_drop_neo_bch",
                **common_governance,
            ),
            ["NEO", "BCH"],
        ),
        (
            ChallengerOverlayConfig(**common_overlay),
            WeeklyGovernanceConfig(
                profile_name="phase67i_drop_neo_xtz",
                **common_governance,
            ),
            ["NEO", "XTZ"],
        ),
        (
            ChallengerOverlayConfig(**common_overlay),
            WeeklyGovernanceConfig(
                profile_name="phase67i_drop_neo_apt",
                **common_governance,
            ),
            ["NEO", "APT"],
        ),
        (
            ChallengerOverlayConfig(**common_overlay),
            WeeklyGovernanceConfig(
                profile_name="phase67i_drop_neo_bch_xtz",
                **common_governance,
            ),
            ["NEO", "BCH", "XTZ"],
        ),
        (
            ChallengerOverlayConfig(**common_overlay),
            WeeklyGovernanceConfig(
                profile_name="phase67i_drop_neo_xtz_apt",
                **common_governance,
            ),
            ["NEO", "XTZ", "APT"],
        ),
    ]


def compute_next_rebalance_date(decisions_df: pd.DataFrame, rebalance_days: int) -> str:
    if decisions_df.empty or "decision_date" not in decisions_df.columns:
        return ""
    last_decision = pd.to_datetime(decisions_df["decision_date"], errors="coerce").dropna()
    if last_decision.empty:
        return ""
    return (last_decision.iloc[-1] + pd.Timedelta(days=rebalance_days)).strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE67I no-NEO second prune pack over 66G core")
    parser.add_argument("--core-paper", type=str, default=str(CORE_PAPER))
    parser.add_argument("--phase63-paper", type=str, default=str(PHASE63_PAPER))
    parser.add_argument("--shortlist-file", type=str, default=str(PHASE67B_SHORTLIST))
    args = parser.parse_args()

    ensure_dir(PHASE67I_DIR)

    core_df = load_strategy_paper(Path(args.core_paper))
    phase63_df = load_strategy_paper(Path(args.phase63_paper))
    full_shortlist = load_shortlist(Path(args.shortlist_file))
    profiles = build_profiles()

    core_row = calc_metrics(core_df, CORE_MODEL_KEY)
    core_row.update(window_metrics(core_df, "2021-01-01"))
    core_row.update(window_metrics(core_df, "2023-01-01"))
    core_row.update(window_metrics(core_df, "2025-01-01"))

    phase63_row = calc_metrics(phase63_df, PHASE63_MODEL_KEY)
    phase63_row.update(window_metrics(phase63_df, "2021-01-01"))
    phase63_row.update(window_metrics(phase63_df, "2023-01-01"))
    phase63_row.update(window_metrics(phase63_df, "2025-01-01"))

    log("[PHASE67I] Start")
    log(f"[PHASE67I] Core paper: {args.core_paper}")
    log(f"[PHASE67I] Full shortlist assets: {[x['asset'] for x in full_shortlist]}")

    summary_rows = [phase63_row, core_row]
    compare_rows = []
    decisions_all = []
    leaderboards_all = []
    asset_quality_rows = []
    papers = {
        PHASE63_MODEL_KEY: phase63_df.copy(),
        CORE_MODEL_KEY: core_df.copy(),
    }

    for overlay_cfg, gov_cfg, drops in profiles:
        shortlist = maybe_drop_assets(full_shortlist, drops)
        asset_strategies: dict[str, pd.DataFrame] = {}
        failed_assets = []

        for item in shortlist:
            asset = str(item["asset"]).strip().upper()
            file_path = Path(str(item["file"]))
            try:
                daily, q = load_local_daily_for_core(file_path)
                strat = build_asset_overlay_strategy(core_df, daily, overlay_cfg, asset)
                asset_strategies[asset] = strat
                asset_quality_rows.append(
                    {
                        "profile": gov_cfg.profile_name,
                        "asset": asset,
                        "file": str(file_path),
                        "dropped_assets": ",".join(drops),
                        **q,
                    }
                )
            except Exception as e:
                failed_assets.append(
                    {
                        "profile": gov_cfg.profile_name,
                        "asset": asset,
                        "reason": str(e),
                        "dropped_assets": ",".join(drops),
                    }
                )

        governance, decisions_df, leaderboard_df = simulate_weekly_challenger_governance(
            core_df=core_df,
            asset_strategies=asset_strategies,
            gov_cfg=gov_cfg,
        )

        row = calc_metrics(governance, gov_cfg.profile_name)
        row.update(window_metrics(governance, "2021-01-01"))
        row.update(window_metrics(governance, "2023-01-01"))
        row.update(window_metrics(governance, "2025-01-01"))
        row = add_delta_cols(row, core_row, "phase66g_core")
        row = add_delta_cols(row, phase63_row, "phase63")
        row["shortlist_size"] = len(asset_strategies)
        row["selection_count"] = int(decisions_df["selected"].sum()) if not decisions_df.empty else 0
        row["switch_count"] = int((decisions_df["selected_asset"].astype(str) != decisions_df["selected_asset"].astype(str).shift(1)).sum() - 1) if not decisions_df.empty else 0
        row["unique_selected_assets"] = int(governance["chosen_asset"].astype(str).replace("", np.nan).dropna().nunique())
        row["promotion_margin_pct"] = gov_cfg.promotion_margin_pct
        row["persistence_weeks"] = gov_cfg.persistence_weeks
        row["reentry_cooldown_days"] = gov_cfg.reentry_cooldown_days
        row["downside_lookback_days"] = gov_cfg.downside_lookback_days
        row["downside_max_worsen_pct"] = gov_cfg.downside_max_worsen_pct
        row["bnb_shield_margin_pct"] = gov_cfg.bnb_shield_margin_pct
        row["min_hold_periods"] = gov_cfg.min_hold_periods
        row["dropped_assets"] = ",".join(drops)

        if not leaderboard_df.empty and "suspended" in leaderboard_df.columns:
            susp = leaderboard_df.groupby("asset", as_index=False)["suspended"].sum()
            row["asset_suspensions_total"] = int(pd.to_numeric(susp["suspended"], errors="coerce").sum())
        else:
            row["asset_suspensions_total"] = 0

        if not leaderboard_df.empty and "reentry_blocked" in leaderboard_df.columns:
            reblock = leaderboard_df.groupby("asset", as_index=False)["reentry_blocked"].sum()
            row["asset_reentry_blocks_total"] = int(pd.to_numeric(reblock["reentry_blocked"], errors="coerce").sum())
        else:
            row["asset_reentry_blocks_total"] = 0

        summary_rows.append(row)
        compare_rows.append(row)
        papers[gov_cfg.profile_name] = governance.copy()

        if not decisions_df.empty:
            d = decisions_df.copy()
            d["profile"] = gov_cfg.profile_name
            d["dropped_assets"] = ",".join(drops)
            decisions_all.append(d)
        if not leaderboard_df.empty:
            l = leaderboard_df.copy()
            l["profile"] = gov_cfg.profile_name
            l["dropped_assets"] = ",".join(drops)
            leaderboards_all.append(l)

        for x in failed_assets:
            asset_quality_rows.append(x)

        log(f"[PHASE67I] done {gov_cfg.profile_name} | drops={drops}")

    summary = pd.DataFrame(summary_rows)
    compare = pd.DataFrame(compare_rows)
    if not compare.empty:
        compare = compare.sort_values(
            by=[
                "delta_vs_phase66g_core_since2025_cagr_pct",
                "delta_vs_phase66g_core_max_drawdown_pct",
                "delta_vs_phase66g_core_since2023_cagr_pct",
                "delta_vs_phase66g_core_cagr_pct",
            ],
            ascending=[False, False, False, False],
            na_position="last",
        ).reset_index(drop=True)

    decisions_out = pd.concat(decisions_all, ignore_index=True) if decisions_all else pd.DataFrame()
    leaderboards_out = pd.concat(leaderboards_all, ignore_index=True) if leaderboards_all else pd.DataFrame()
    asset_quality_df = pd.DataFrame(asset_quality_rows)

    best = compare.head(1)
    best_model = str(best.iloc[0]["model"]) if not best.empty else ""
    best_gov_cfg = None
    for _, gov_cfg, _ in profiles:
        if gov_cfg.profile_name == best_model:
            best_gov_cfg = gov_cfg
            break

    live_status = pd.DataFrame()
    latest_top10 = pd.DataFrame()
    if best_model and best_model in papers:
        best_paper = papers[best_model]
        latest_available_date = best_paper.index.max().strftime("%Y-%m-%d") if len(best_paper) else ""
        current_asset = str(best_paper["weekly_authorized_asset"].astype(str).iloc[-1]) if len(best_paper) else ""
        current_asset = current_asset if current_asset else "CORE"
        best_decisions = decisions_out[decisions_out["profile"].astype(str) == best_model].copy() if not decisions_out.empty else pd.DataFrame()
        next_rebalance_date = compute_next_rebalance_date(best_decisions, best_gov_cfg.rebalance_every_days if best_gov_cfg else 7)

        live_status = pd.DataFrame(
            [
                {
                    "model": best_model,
                    "latest_available_date": latest_available_date,
                    "current_asset": current_asset,
                    "next_rebalance_date": next_rebalance_date,
                    "dropped_assets": str(best.iloc[0]["dropped_assets"]) if not best.empty else "",
                }
            ]
        )

        best_leaderboard = leaderboards_out[leaderboards_out["profile"].astype(str) == best_model].copy() if not leaderboards_out.empty else pd.DataFrame()
        if not best_leaderboard.empty:
            last_decision_date = str(best_leaderboard["decision_date"].astype(str).iloc[-1])
            latest_top10 = (
                best_leaderboard[best_leaderboard["decision_date"].astype(str) == last_decision_date]
                .sort_values(
                    by=["passed_filters", "score", "recent_total_delta_pct", "train_total_delta_pct"],
                    ascending=[False, False, False, False],
                    na_position="last",
                )
                .head(10)
                .reset_index(drop=True)
            )

    summary_path = PHASE67I_DIR / "phase67i_no_neo_second_prune_summary.csv"
    compare_path = PHASE67I_DIR / "phase67i_no_neo_second_prune_compare.csv"
    decisions_path = PHASE67I_DIR / "phase67i_no_neo_second_prune_decisions.csv"
    leaderboard_path = PHASE67I_DIR / "phase67i_no_neo_second_prune_leaderboard.csv"
    asset_quality_path = PHASE67I_DIR / "phase67i_no_neo_second_prune_asset_quality.csv"
    live_status_path = PHASE67I_DIR / "phase67i_live_status.csv"
    latest_top10_path = PHASE67I_DIR / "phase67i_latest_decision_top10.csv"
    manifest_path = PHASE67I_DIR / "phase67i_manifest.json"

    summary.to_csv(summary_path, index=False)
    compare.to_csv(compare_path, index=False)
    decisions_out.to_csv(decisions_path, index=False)
    leaderboards_out.to_csv(leaderboard_path, index=False)
    asset_quality_df.to_csv(asset_quality_path, index=False)
    live_status.to_csv(live_status_path, index=False)
    latest_top10.to_csv(latest_top10_path, index=False)

    for model, paper in papers.items():
        out_path = PHASE67I_DIR / f"{model}_paper.csv"
        paper.reset_index().rename(columns={paper.index.name or "index": "date"}).to_csv(out_path, index=False)

    manifest = {
        "phase": "phase67i_no_neo_second_prune_pack",
        "phase63_paper": str(args.phase63_paper),
        "core_paper": str(args.core_paper),
        "shortlist_file": str(args.shortlist_file),
        "profiles": [
            {
                "overlay": asdict(overlay_cfg),
                "governance": asdict(gov_cfg),
                "dropped_assets": drops,
            }
            for overlay_cfg, gov_cfg, drops in profiles
        ],
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "decisions_file": str(decisions_path),
        "leaderboard_file": str(leaderboard_path),
        "asset_quality_file": str(asset_quality_path),
        "live_status_file": str(live_status_path),
        "latest_top10_file": str(latest_top10_path),
        "best_model": best_model,
        "notes": [
            "67I ide z nového no-NEO baseline.",
            "Testuje ďalší prune BCH/XTZ/APT a 2-asset combos po odstránení NEO.",
            "Cieľ: zachovať since2025 a skúsiť nájsť ďalší clean drag bez zhoršenia DD/CAGR.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE67I TOP RESULT ===")
    if best.empty:
        log("No phase67i profile processed.")
    else:
        row = best.iloc[0]
        log(f"model: {row['model']}")
        log(f"dropped_assets: {row['dropped_assets']}")
        log(f"cagr_pct: {row['cagr_pct']:.2f}")
        log(f"max_drawdown_pct: {row['max_drawdown_pct']:.2f}")
        log(f"since2023_cagr_pct: {row['since2023_cagr_pct']:.2f}")
        log(f"since2025_cagr_pct: {row['since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_core_cagr_pct: {row['delta_vs_phase66g_core_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_core_since2023_cagr_pct: {row['delta_vs_phase66g_core_since2023_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_core_since2025_cagr_pct: {row['delta_vs_phase66g_core_since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase66g_core_max_drawdown_pct: {row['delta_vs_phase66g_core_max_drawdown_pct']:.2f}")
        log(f"delta_vs_phase63_cagr_pct: {row['delta_vs_phase63_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_since2023_cagr_pct: {row['delta_vs_phase63_since2023_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_since2025_cagr_pct: {row['delta_vs_phase63_since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_max_drawdown_pct: {row['delta_vs_phase63_max_drawdown_pct']:.2f}")
        log(f"selection_count: {int(row['selection_count'])}")
        log(f"switch_count: {int(row['switch_count'])}")
        log(f"unique_selected_assets: {int(row['unique_selected_assets'])}")
        log("")

    if not live_status.empty:
        ls = live_status.iloc[0]
        log("=== PHASE67I LIVE STATUS ===")
        log(f"latest_available_date: {ls['latest_available_date']}")
        log(f"current_asset: {ls['current_asset']}")
        log(f"next_rebalance_date: {ls['next_rebalance_date']}")
        log(f"dropped_assets: {ls['dropped_assets']}")
        log("")

    log(f"[PHASE67I] Saved summary -> {summary_path}")
    log(f"[PHASE67I] Saved compare -> {compare_path}")
    log(f"[PHASE67I] Saved decisions -> {decisions_path}")
    log(f"[PHASE67I] Saved leaderboard -> {leaderboard_path}")
    log(f"[PHASE67I] Saved asset quality -> {asset_quality_path}")
    log(f"[PHASE67I] Saved live status -> {live_status_path}")
    log(f"[PHASE67I] Saved latest top10 -> {latest_top10_path}")
    log(f"[PHASE67I] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()