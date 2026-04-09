from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from freshness_lineage import build_producer_lineage


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
OHLCV_DIR = ROOT / "data" / "ohlcv"
DATA_DIR = ROOT / "data"

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "phase68l_early_entry_soft_gate_probe"

BASELINE_PAPER_PATH = OUTPUTS / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
CORE_PAPER_PATH = OUTPUTS / "phase66g_production_candidate_live" / "phase66g_production_soft_filters_paper.csv"
TREND_HISTORY_PATH = OUTPUTS / "phase66g_production_candidate_live" / "phase66g_trend_barometer_history.csv"

PHASE68L_DIR = OUTPUTS / PROBE_MODEL
PAPERS_DIR = PHASE68L_DIR / "papers"
SUMMARY_PATH = PHASE68L_DIR / "phase68l_early_entry_soft_gate_summary.csv"
COMPARE_PATH = PHASE68L_DIR / "phase68l_early_entry_soft_gate_compare.csv"
BLOCKER_COUNTS_PATH = PHASE68L_DIR / "phase68l_early_entry_soft_gate_blocker_counts.csv"
STATE_TIME_PATH = PHASE68L_DIR / "phase68l_early_entry_soft_gate_state_time.csv"
MANIFEST_PATH = PHASE68L_DIR / "phase68l_early_entry_soft_gate_manifest.json"
BASELINE_OUTPUT_PAPER_PATH = PAPERS_DIR / f"{BASELINE_MODEL}_paper.csv"
PROBE_OUTPUT_PAPER_PATH = PAPERS_DIR / f"{PROBE_MODEL}_paper.csv"


@dataclass(frozen=True)
class StrictFullConfig:
    score_lb: int = 30
    fast_ma: int = 20
    slow_ma: int = 100
    min_score: float = 0.12
    edge_vs_core: float = 0.03
    risk_ma: int = 150
    risk_buffer: float = -0.03
    vol_lb: int = 30
    vol_cap: float = 0.045
    rel_recent_lb: int = 30
    rel_recent_min_edge: float = 0.0
    cooldown_days: int = 3


@dataclass(frozen=True)
class EarlyRiskConfig:
    early_entry_weight: float = 0.35
    leader_stable_days: int = 2
    trend_improve_days: int = 2
    near_threshold_floor: float = -0.60
    full_threshold: float = 0.0
    early_zone_ceiling: float = 0.15
    early_score_min: float = 0.06
    early_edge_vs_core: float = -0.01
    early_recent_rel_min: float = -0.02
    early_risk_buffer: float = -0.08
    early_vol_cap: float = 0.065
    success_resolution_days: int = 2


def log(message: str) -> None:
    print(message, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(col).strip() for col in out.columns]
    return out


def normalize_asset_label(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NAN", "NONE", "NULL", "NA", "CORE", "BASELINE", "CASH", "BTC"}:
        return ""
    if text == "HYPERLIQUID":
        text = "HYPE"
    if text.endswith("USDT"):
        text = text[:-4]
    return text


def rolling_compound_return(ret: pd.Series, lookback: int) -> pd.Series:
    return (1.0 + ret).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1.0


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if years <= 0:
        return 0.0
    if total_return <= -1.0:
        return -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def max_drawdown_from_equity(equity: pd.Series) -> float:
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min()) if len(drawdown) else 0.0


def calmar_ratio(cagr_pct: float, max_drawdown_pct: float) -> float:
    if pd.isna(max_drawdown_pct) or max_drawdown_pct == 0:
        return 0.0
    return float(cagr_pct / abs(max_drawdown_pct))


def load_paper(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing paper: {path}")

    raw = pd.read_csv(path)
    raw = normalize_columns(raw)
    if "date" not in raw.columns:
        raise ValueError(f"{path.name}: missing date column")

    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")

    for column in ["strategy_return", "equity"]:
        if column not in raw.columns:
            raise ValueError(f"{path.name}: missing {column}")

    regime_col = "executed_regime" if "executed_regime" in raw.columns else "final_regime"
    if regime_col not in raw.columns:
        raise ValueError(f"{path.name}: missing executed_regime/final_regime")

    if "executed_position" in raw.columns:
        position_col = "executed_position"
    elif "final_position" in raw.columns:
        position_col = "final_position"
    else:
        raise ValueError(f"{path.name}: missing executed position column")

    out = raw.set_index("date").copy()
    out["strategy_return"] = pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)
    out["equity"] = pd.to_numeric(out["equity"], errors="coerce").ffill().bfill()
    out["executed_regime"] = out[regime_col].astype(str).fillna("").str.upper().str.strip()
    out["executed_position"] = out[position_col].astype(str).fillna("").str.upper().str.strip()
    for column in ["chosen_asset", "weekly_authorized_asset"]:
        if column in out.columns:
            out[column] = out[column].fillna("").astype(str).str.upper().str.strip()
        else:
            out[column] = ""
    return out


def load_trend_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing trend history: {path}")

    raw = pd.read_csv(path)
    raw = normalize_columns(raw)
    if "date" not in raw.columns:
        raise ValueError(f"{path.name}: missing date column")

    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")

    out = raw.set_index("date").copy()
    for column in ["trend_score", "prev_trend_score", "buy_threshold"]:
        if column not in out.columns:
            out[column] = np.nan
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out[["trend_score", "prev_trend_score", "buy_threshold"]]


def resolve_asset_daily_path(asset: str) -> Path:
    direct_path = OHLCV_DIR / f"{asset}USDT_1d.csv"
    if direct_path.exists():
        return direct_path

    exact_candidates = sorted(
        [
            path
            for path in DATA_DIR.rglob("*.csv")
            if path.name.upper().startswith(f"{asset.upper()}USDT") and "1D" in path.name.upper()
        ]
    )
    if exact_candidates:
        return exact_candidates[0]

    loose_candidates = sorted(
        [
            path
            for path in DATA_DIR.rglob("*.csv")
            if asset.upper() in path.name.upper() and "USDT" in path.name.upper() and "1D" in path.name.upper()
        ]
    )
    if loose_candidates:
        return loose_candidates[0]

    return direct_path


def load_asset_daily(asset: str) -> pd.DataFrame:
    path = resolve_asset_daily_path(asset)
    if not path.exists():
        raise FileNotFoundError(f"Missing OHLCV input for {asset}: {path}")

    raw = pd.read_csv(path)
    raw = normalize_columns(raw)
    if "date" not in raw.columns or "close" not in raw.columns:
        raise ValueError(f"{path.name}: missing date/close")

    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
    raw = raw.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return raw.set_index("date")[["close"]].rename(columns={"close": "candidate_close"})


def build_candidate_context(core_df: pd.DataFrame, asset_daily: pd.DataFrame, strict_cfg: StrictFullConfig, early_cfg: EarlyRiskConfig) -> pd.DataFrame:
    out = core_df[["strategy_return", "equity", "executed_regime", "executed_position"]].copy()
    aligned_asset = asset_daily.reindex(out.index)
    aligned_asset["candidate_close"] = aligned_asset["candidate_close"].ffill()
    out["candidate_close"] = aligned_asset["candidate_close"]
    out["candidate_return"] = out["candidate_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

    out["core_score"] = rolling_compound_return(out["strategy_return"], strict_cfg.score_lb)
    out["cand_score"] = out["candidate_close"].pct_change(strict_cfg.score_lb)
    out["cand_recent_rel"] = (
        out["candidate_close"].pct_change(strict_cfg.rel_recent_lb) - out["equity"].pct_change(strict_cfg.rel_recent_lb)
    )

    out["cand_fast_ma"] = out["candidate_close"].rolling(strict_cfg.fast_ma, min_periods=strict_cfg.fast_ma).mean()
    out["cand_slow_ma"] = out["candidate_close"].rolling(strict_cfg.slow_ma, min_periods=strict_cfg.slow_ma).mean()
    out["cand_risk_ma"] = out["candidate_close"].rolling(strict_cfg.risk_ma, min_periods=strict_cfg.risk_ma).mean()
    out["cand_vol"] = out["candidate_return"].rolling(strict_cfg.vol_lb, min_periods=strict_cfg.vol_lb).std(ddof=0)

    out["strict_trend_ok"] = (
        (out["candidate_close"] > out["cand_fast_ma"])
        & (out["cand_fast_ma"] > out["cand_slow_ma"])
        & (out["cand_score"] >= strict_cfg.min_score)
    )
    out["strict_risk_off"] = (
        (out["candidate_close"] < (out["cand_risk_ma"] * (1.0 + strict_cfg.risk_buffer)))
        | (out["cand_vol"] > strict_cfg.vol_cap)
    )
    out["strict_edge_ok"] = out["cand_score"] >= (out["core_score"] + strict_cfg.edge_vs_core)
    out["strict_recent_rel_ok"] = out["cand_recent_rel"] >= strict_cfg.rel_recent_min_edge
    out["strict_signal_raw"] = (
        out["executed_regime"].eq("BASE")
        & out["strict_trend_ok"].fillna(False)
        & (~out["strict_risk_off"].fillna(True))
        & out["strict_edge_ok"].fillna(False)
        & out["strict_recent_rel_ok"].fillna(False)
        & out["candidate_close"].notna()
    )

    out["early_trend_ok"] = (
        (out["candidate_close"] > out["cand_fast_ma"])
        & (out["cand_fast_ma"] > out["cand_slow_ma"])
        & (out["cand_score"] >= early_cfg.early_score_min)
    )
    out["early_risk_off"] = (
        (out["candidate_close"] < (out["cand_risk_ma"] * (1.0 + early_cfg.early_risk_buffer)))
        | (out["cand_vol"] > early_cfg.early_vol_cap)
    )
    out["early_edge_ok"] = out["cand_score"] >= (out["core_score"] + early_cfg.early_edge_vs_core)
    out["early_recent_rel_ok"] = out["cand_recent_rel"] >= early_cfg.early_recent_rel_min
    out["early_signal_soft"] = (
        out["executed_regime"].isin(["BASE", "BTC"])
        & out["early_trend_ok"].fillna(False)
        & (~out["early_risk_off"].fillna(True))
        & out["early_edge_ok"].fillna(False)
        & out["early_recent_rel_ok"].fillna(False)
        & out["candidate_close"].notna()
    )

    return out


def build_trend_improving_flag(trend_score: pd.Series, persistence_days: int) -> pd.Series:
    improving = trend_score.diff() > 0.0
    return improving.rolling(persistence_days, min_periods=persistence_days).sum().eq(persistence_days).fillna(False)


def build_leader_stable_flag(leader_series: pd.Series, stable_days: int) -> pd.Series:
    normalized = leader_series.fillna("").astype(str)
    result = []
    for idx in range(len(normalized)):
        current = normalize_asset_label(normalized.iloc[idx])
        if not current:
            result.append(False)
            continue
        start = idx - stable_days + 1
        if start < 0:
            result.append(False)
            continue
        window = normalized.iloc[start : idx + 1].map(normalize_asset_label)
        result.append(bool((window == current).all()))
    return pd.Series(result, index=leader_series.index)


def calc_metrics(df: pd.DataFrame, model_name: str) -> dict:
    returns = pd.to_numeric(df["strategy_return"], errors="coerce").fillna(0.0)
    equity = (1.0 + returns).cumprod()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) > 1 else 0.0
    cagr = annualize_return(total_return, len(df))
    max_dd = max_drawdown_from_equity(equity)
    return {
        "model": model_name,
        "cagr_pct": cagr * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
        "calmar": calmar_ratio(cagr * 100.0, max_dd * 100.0),
    }


def window_cagr_pct(df: pd.DataFrame, start_date: str) -> float:
    sub = df[df.index >= pd.Timestamp(start_date)].copy()
    if sub.empty:
        return float("nan")
    return calc_metrics(sub, f"since{start_date[:4]}")["cagr_pct"]


def count_state_transitions(state_series: pd.Series) -> dict[str, int]:
    states = state_series.astype(str).tolist()
    risk_state_transition_count = 0
    cash_to_early = 0
    early_to_full = 0
    early_to_cash = 0
    for prev_state, next_state in zip(states[:-1], states[1:]):
        if prev_state != next_state:
            risk_state_transition_count += 1
        if prev_state == "CASH" and next_state == "EARLY_RISK":
            cash_to_early += 1
        if prev_state == "EARLY_RISK" and next_state == "FULL_RISK":
            early_to_full += 1
        if prev_state == "EARLY_RISK" and next_state == "CASH":
            early_to_cash += 1
    return {
        "risk_state_transition_count": int(risk_state_transition_count),
        "cash_to_early_transition_count": int(cash_to_early),
        "early_to_full_transition_count": int(early_to_full),
        "early_to_cash_transition_count": int(early_to_cash),
    }


def build_probe_frame(
    baseline_df: pd.DataFrame,
    core_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    strict_cfg: StrictFullConfig,
    early_cfg: EarlyRiskConfig,
) -> pd.DataFrame:
    frame = baseline_df.copy()
    frame = frame.join(trend_df, how="left")

    frame["selected_asset"] = frame["weekly_authorized_asset"].map(normalize_asset_label)
    fallback_asset = frame["chosen_asset"].map(normalize_asset_label)
    frame["selected_asset"] = np.where(frame["selected_asset"] == "", fallback_asset, frame["selected_asset"])
    frame["selected_asset"] = pd.Series(frame["selected_asset"], index=frame.index).fillna("").astype(str)

    frame["baseline_strategy_return"] = pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)
    frame["baseline_executed_regime"] = frame["executed_regime"].astype(str)
    frame["baseline_executed_position"] = frame["executed_position"].astype(str)

    asset_contexts: dict[str, pd.DataFrame] = {}
    for asset in sorted({asset for asset in frame["selected_asset"].unique() if asset}):
        asset_contexts[asset] = build_candidate_context(core_df, load_asset_daily(asset), strict_cfg, early_cfg)

    frame["leader_stable"] = build_leader_stable_flag(frame["selected_asset"], early_cfg.leader_stable_days).astype(bool)
    frame["trend_improving"] = build_trend_improving_flag(frame["trend_score"], early_cfg.trend_improve_days).astype(bool)

    for column in ["candidate_asset_return", "cand_score", "core_score", "cand_recent_rel", "cand_vol"]:
        frame[column] = 0.0
    for column in [
        "strict_signal_raw",
        "strict_risk_off",
        "strict_trend_ok",
        "strict_edge_ok",
        "strict_recent_rel_ok",
        "early_signal_soft",
        "early_risk_off",
        "early_trend_ok",
        "early_edge_ok",
        "early_recent_rel_ok",
    ]:
        frame[column] = False

    for date_value, row in frame.iterrows():
        asset = row["selected_asset"]
        if not asset:
            continue
        asset_context = asset_contexts.get(asset)
        if asset_context is None or date_value not in asset_context.index:
            continue
        context_row = asset_context.loc[date_value]
        frame.at[date_value, "candidate_asset_return"] = float(context_row.get("candidate_return", 0.0))
        frame.at[date_value, "cand_score"] = float(pd.to_numeric(context_row.get("cand_score", 0.0), errors="coerce"))
        frame.at[date_value, "core_score"] = float(pd.to_numeric(context_row.get("core_score", 0.0), errors="coerce"))
        frame.at[date_value, "cand_recent_rel"] = float(pd.to_numeric(context_row.get("cand_recent_rel", 0.0), errors="coerce"))
        frame.at[date_value, "cand_vol"] = float(pd.to_numeric(context_row.get("cand_vol", 0.0), errors="coerce"))
        for column in [
            "strict_signal_raw",
            "strict_risk_off",
            "strict_trend_ok",
            "strict_edge_ok",
            "strict_recent_rel_ok",
            "early_signal_soft",
            "early_risk_off",
            "early_trend_ok",
            "early_edge_ok",
            "early_recent_rel_ok",
        ]:
            frame.at[date_value, column] = bool(context_row.get(column, False))

    frame["full_risk_active"] = frame["baseline_executed_regime"].eq("CANDIDATE")
    frame["early_zone_ready"] = (
        frame["trend_score"].notna()
        & frame["trend_score"].lt(early_cfg.early_zone_ceiling)
        & frame["trend_score"].ge(early_cfg.near_threshold_floor)
    )
    frame["soft_or_strict_early_signal_ready"] = frame["strict_signal_raw"] | frame["early_signal_soft"]
    frame["early_setup_ready"] = (
        frame["selected_asset"].ne("")
        & frame["leader_stable"]
        & frame["trend_improving"]
        & frame["early_zone_ready"]
        & frame["soft_or_strict_early_signal_ready"]
    )

    frame["ladder_state"] = np.where(
        frame["full_risk_active"],
        "FULL_RISK",
        np.where(frame["early_setup_ready"], "EARLY_RISK", "CASH"),
    )
    frame["early_entry_weight"] = np.where(
        frame["ladder_state"].eq("EARLY_RISK"),
        early_cfg.early_entry_weight,
        np.where(frame["ladder_state"].eq("FULL_RISK"), 1.0, 0.0),
    )
    frame["strategy_return"] = np.where(
        frame["ladder_state"].eq("EARLY_RISK"),
        (
            (1.0 - early_cfg.early_entry_weight) * frame["baseline_strategy_return"]
            + early_cfg.early_entry_weight * frame["candidate_asset_return"]
        ),
        frame["baseline_strategy_return"],
    )
    frame["equity"] = (1.0 + pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)).cumprod()
    frame["incremental_vs_baseline"] = frame["strategy_return"] - frame["baseline_strategy_return"]
    return frame


def analyze_early_sequences(frame: pd.DataFrame, success_resolution_days: int) -> tuple[float, int, float]:
    early_mask = frame["ladder_state"].eq("EARLY_RISK")
    if not early_mask.any():
        return 0.0, 0, 0.0

    early_positions = np.flatnonzero(early_mask.to_numpy())
    groups = np.split(early_positions, np.where(np.diff(early_positions) != 1)[0] + 1)

    lead_days: list[float] = []
    false_start_count = 0
    successful_dates: list[pd.Timestamp] = []

    index_values = frame.index.to_list()
    selected_assets = frame["selected_asset"].tolist()
    ladder_states = frame["ladder_state"].tolist()

    for group in groups:
        start_idx = int(group[0])
        end_idx = int(group[-1])
        asset = selected_assets[start_idx]
        success_idx: int | None = None

        for probe_idx in range(end_idx + 1, min(len(frame), end_idx + 1 + success_resolution_days)):
            if normalize_asset_label(selected_assets[probe_idx]) != normalize_asset_label(asset):
                break
            if ladder_states[probe_idx] == "FULL_RISK":
                success_idx = probe_idx
                break
            if ladder_states[probe_idx] == "EARLY_RISK":
                break

        if success_idx is None:
            false_start_count += 1
            continue

        lead_days.append(float((index_values[success_idx] - index_values[start_idx]).days))
        successful_dates.extend(index_values[start_idx:success_idx])

    successful_dates = sorted(set(successful_dates))
    if successful_dates:
        baseline_growth = (1.0 + frame.loc[successful_dates, "baseline_strategy_return"].astype(float)).prod()
        probe_growth = (1.0 + frame.loc[successful_dates, "strategy_return"].astype(float)).prod()
        captured_pre_breakout_return_pct = (probe_growth / baseline_growth - 1.0) * 100.0 if baseline_growth else 0.0
    else:
        captured_pre_breakout_return_pct = 0.0

    avg_lead_days = float(np.mean(lead_days)) if lead_days else 0.0
    return avg_lead_days, false_start_count, float(captured_pre_breakout_return_pct)


def build_state_time_summary(frame: pd.DataFrame) -> pd.DataFrame:
    total_days = len(frame)
    rows = []
    for state in ["CASH", "EARLY_RISK", "FULL_RISK"]:
        days = int(frame["ladder_state"].eq(state).sum())
        rows.append(
            {
                "state": state,
                "days": days,
                "days_pct": (days / total_days) * 100.0 if total_days else 0.0,
            }
        )
    return pd.DataFrame(rows)


def build_blocker_counts(frame: pd.DataFrame, early_cfg: EarlyRiskConfig) -> pd.DataFrame:
    eligible_context = frame["selected_asset"].ne("") & (~frame["full_risk_active"])
    blocked_context = eligible_context & (~frame["early_setup_ready"])

    rows = [
        {"reason": "no_selected_asset", "days": int(frame["selected_asset"].eq("").sum()), "scope": "all_days"},
        {"reason": "full_risk_override", "days": int((frame["full_risk_active"] & frame["early_setup_ready"]).sum()), "scope": "all_days"},
        {"reason": "leader_not_stable", "days": int((blocked_context & (~frame["leader_stable"])).sum()), "scope": "eligible_non_full_days"},
        {"reason": "trend_not_improving", "days": int((blocked_context & (~frame["trend_improving"])).sum()), "scope": "eligible_non_full_days"},
        {
            "reason": "below_early_zone_floor",
            "days": int((blocked_context & (frame["trend_score"].isna() | (frame["trend_score"] < early_cfg.near_threshold_floor))).sum()),
            "scope": "eligible_non_full_days",
        },
        {"reason": "above_early_zone_ceiling", "days": int((blocked_context & frame["trend_score"].ge(early_cfg.early_zone_ceiling)).sum()), "scope": "eligible_non_full_days"},
        {"reason": "early_trend_not_ready", "days": int((blocked_context & (~frame["strict_signal_raw"]) & (~frame["early_trend_ok"])).sum()), "scope": "eligible_non_full_days"},
        {"reason": "early_edge_not_ready", "days": int((blocked_context & (~frame["strict_signal_raw"]) & (~frame["early_edge_ok"] | ~frame["early_recent_rel_ok"])).sum()), "scope": "eligible_non_full_days"},
        {"reason": "early_risk_off_block", "days": int((blocked_context & (~frame["strict_signal_raw"]) & frame["early_risk_off"]).sum()), "scope": "eligible_non_full_days"},
        {"reason": "no_soft_or_strict_early_signal", "days": int((blocked_context & (~frame["soft_or_strict_early_signal_ready"])).sum()), "scope": "eligible_non_full_days"},
    ]

    eligible_days = int(eligible_context.sum())
    out = pd.DataFrame(rows)
    out["days_pct_of_scope"] = np.where(
        out["scope"].eq("eligible_non_full_days"),
        np.where(eligible_days > 0, out["days"] / eligible_days * 100.0, 0.0),
        np.where(len(frame) > 0, out["days"] / len(frame) * 100.0, 0.0),
    )
    return out


def enrich_metrics(
    df: pd.DataFrame,
    model_name: str,
    *,
    early_setup_ready_days: int,
    early_entry_days: int,
    avg_lead_days_vs_full_entry: float,
    false_start_count: int,
    captured_pre_breakout_return_pct: float,
) -> dict:
    metrics = calc_metrics(df, model_name)
    metrics["since2023_cagr_pct"] = window_cagr_pct(df, "2023-01-01")
    metrics["since2025_cagr_pct"] = window_cagr_pct(df, "2025-01-01")
    metrics["early_setup_ready_days"] = int(early_setup_ready_days)
    metrics["early_entry_days"] = int(early_entry_days)
    metrics["avg_lead_days_vs_full_entry"] = float(avg_lead_days_vs_full_entry)
    metrics["false_start_count"] = int(false_start_count)
    metrics["captured_pre_breakout_return_pct"] = float(captured_pre_breakout_return_pct)
    metrics["cash_days"] = int(df["ladder_state"].eq("CASH").sum()) if "ladder_state" in df.columns else int(len(df) - df["baseline_executed_regime"].eq("CANDIDATE").sum())
    metrics["early_risk_days"] = int(df["ladder_state"].eq("EARLY_RISK").sum()) if "ladder_state" in df.columns else 0
    metrics["full_risk_days"] = int(df["ladder_state"].eq("FULL_RISK").sum()) if "ladder_state" in df.columns else int(df["baseline_executed_regime"].eq("CANDIDATE").sum())
    total_days = len(df)
    metrics["cash_days_pct"] = (metrics["cash_days"] / total_days) * 100.0 if total_days else 0.0
    metrics["early_risk_days_pct"] = (metrics["early_risk_days"] / total_days) * 100.0 if total_days else 0.0
    metrics["full_risk_days_pct"] = (metrics["full_risk_days"] / total_days) * 100.0 if total_days else 0.0
    state_series = df["ladder_state"] if "ladder_state" in df.columns else pd.Series(
        np.where(df["baseline_executed_regime"].eq("CANDIDATE"), "FULL_RISK", "CASH"),
        index=df.index,
    )
    metrics.update(count_state_transitions(state_series))
    return metrics


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
    probe_row = summary_df[summary_df["model"] == PROBE_MODEL].iloc[0]

    rows = []
    for metric in metric_columns:
        baseline_value = float(pd.to_numeric(baseline_row.get(metric), errors="coerce"))
        probe_value = float(pd.to_numeric(probe_row.get(metric), errors="coerce"))
        rows.append(
            {
                "metric": metric,
                "baseline_model": BASELINE_MODEL,
                "baseline_value": baseline_value,
                "probe_model": PROBE_MODEL,
                "probe_value": probe_value,
                "delta_probe_minus_baseline": probe_value - baseline_value,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase68L dev-only softer EARLY_RISK follow-up probe")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--core-paper", type=str, default=str(CORE_PAPER_PATH))
    parser.add_argument("--trend-history", type=str, default=str(TREND_HISTORY_PATH))
    args = parser.parse_args()

    strict_cfg = StrictFullConfig()
    early_cfg = EarlyRiskConfig()

    ensure_dir(PHASE68L_DIR)
    ensure_dir(PAPERS_DIR)

    baseline_df = load_paper(Path(args.baseline_paper))
    core_df = load_paper(Path(args.core_paper))
    trend_df = load_trend_history(Path(args.trend_history))

    log("[PHASE68L] Building softer EARLY_RISK follow-up probe")
    probe_df = build_probe_frame(baseline_df, core_df, trend_df, strict_cfg, early_cfg)

    early_setup_ready_days = int(probe_df["early_setup_ready"].sum())
    early_entry_days = int(probe_df["ladder_state"].eq("EARLY_RISK").sum())
    avg_lead_days, false_start_count, captured_pre_breakout_return_pct = analyze_early_sequences(
        probe_df,
        early_cfg.success_resolution_days,
    )

    baseline_diag = baseline_df.copy()
    baseline_diag["baseline_executed_regime"] = baseline_diag["executed_regime"].astype(str)
    baseline_diag["ladder_state"] = np.where(baseline_diag["baseline_executed_regime"].eq("CANDIDATE"), "FULL_RISK", "CASH")

    baseline_metrics = enrich_metrics(
        baseline_diag,
        BASELINE_MODEL,
        early_setup_ready_days=0,
        early_entry_days=0,
        avg_lead_days_vs_full_entry=0.0,
        false_start_count=0,
        captured_pre_breakout_return_pct=0.0,
    )
    probe_metrics = enrich_metrics(
        probe_df,
        PROBE_MODEL,
        early_setup_ready_days=early_setup_ready_days,
        early_entry_days=early_entry_days,
        avg_lead_days_vs_full_entry=avg_lead_days,
        false_start_count=false_start_count,
        captured_pre_breakout_return_pct=captured_pre_breakout_return_pct,
    )

    summary_df = pd.DataFrame([baseline_metrics, probe_metrics])
    compare_df = build_compare_rows(summary_df)
    blocker_counts_df = build_blocker_counts(probe_df, early_cfg)
    state_time_df = build_state_time_summary(probe_df)

    baseline_df.reset_index().rename(columns={"index": "date"}).to_csv(BASELINE_OUTPUT_PAPER_PATH, index=False)
    probe_df.reset_index().rename(columns={"index": "date"}).to_csv(PROBE_OUTPUT_PAPER_PATH, index=False)
    summary_df.to_csv(SUMMARY_PATH, index=False)
    compare_df.to_csv(COMPARE_PATH, index=False)
    blocker_counts_df.to_csv(BLOCKER_COUNTS_PATH, index=False)
    state_time_df.to_csv(STATE_TIME_PATH, index=False)

    manifest = {
        "phase": PROBE_MODEL,
        "experiment_scope": "narrow_dev_only_core_follow_up_probe",
        "official_compare_baseline": BASELINE_MODEL,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "changes_shortlist": False,
        "changes_governance": False,
        "changes_leverage": False,
        "changes_app_live_truth": False,
        "changes_execution_logic": False,
        "full_risk_behavior": "preserved_strict_baseline_behavior",
        "early_risk_behavior": {
            "description": (
                "EARLY_RISK keeps the same selected leader but allows a softer pre-confirmation gate: wider near-threshold "
                "zone, softer risk-off filter, and softer relative edge, while FULL_RISK remains the current strict candidate execute state."
            ),
            "strict_full_config_reference": asdict(strict_cfg),
            "soft_early_config": asdict(early_cfg),
        },
        "inputs": {
            "baseline_paper": str(Path(args.baseline_paper).resolve()),
            "core_paper": str(Path(args.core_paper).resolve()),
            "trend_history": str(Path(args.trend_history).resolve()),
            "ohlcv_dir": str(OHLCV_DIR.resolve()),
        },
        "outputs": {
            "summary_file": str(SUMMARY_PATH.resolve()),
            "compare_file": str(COMPARE_PATH.resolve()),
            "blocker_counts_file": str(BLOCKER_COUNTS_PATH.resolve()),
            "state_time_file": str(STATE_TIME_PATH.resolve()),
            "manifest_file": str(MANIFEST_PATH.resolve()),
            "papers_dir": str(PAPERS_DIR.resolve()),
            "baseline_paper_copy": str(BASELINE_OUTPUT_PAPER_PATH.resolve()),
            "probe_paper": str(PROBE_OUTPUT_PAPER_PATH.resolve()),
        },
        "diagnostic_notes": {
            "early_setup_ready_days": "Days where the softer EARLY_RISK gate was ready before state override.",
            "early_entry_days": "Days actually spent in EARLY_RISK after FULL_RISK override.",
            "early_blocker_counts": "Non-exclusive blocker counts for eligible non-full days unless scope says all_days.",
            "state_time": "Time spent in CASH, EARLY_RISK, and FULL_RISK under the probe state machine.",
        },
        "freshness_lineage": build_producer_lineage(
            producer_script=__file__,
            source_file=Path(args.baseline_paper).resolve(),
            raw_file=Path(args.trend_history).resolve(),
            output_file=PROBE_OUTPUT_PAPER_PATH.resolve(),
            date_semantics="execution_date",
        ),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log(
        "[PHASE68L] "
        f"baseline_cagr={baseline_metrics['cagr_pct']:.2f} "
        f"probe_cagr={probe_metrics['cagr_pct']:.2f} "
        f"early_setup_ready_days={early_setup_ready_days} "
        f"early_entry_days={early_entry_days}"
    )
    log(f"[PHASE68L] Saved summary -> {SUMMARY_PATH}")
    log(f"[PHASE68L] Saved compare -> {COMPARE_PATH}")
    log(f"[PHASE68L] Saved blocker counts -> {BLOCKER_COUNTS_PATH}")
    log(f"[PHASE68L] Saved state time -> {STATE_TIME_PATH}")
    log(f"[PHASE68L] Saved manifest -> {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
