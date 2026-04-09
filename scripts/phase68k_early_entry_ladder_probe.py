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
PROBE_MODEL = "phase68k_early_entry_ladder_probe"

BASELINE_PAPER_PATH = OUTPUTS / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
CORE_PAPER_PATH = OUTPUTS / "phase66g_production_candidate_live" / "phase66g_production_soft_filters_paper.csv"
TREND_HISTORY_PATH = OUTPUTS / "phase66g_production_candidate_live" / "phase66g_trend_barometer_history.csv"

PHASE68K_DIR = OUTPUTS / PROBE_MODEL
PAPERS_DIR = PHASE68K_DIR / "papers"
SUMMARY_PATH = PHASE68K_DIR / "phase68k_early_entry_summary.csv"
COMPARE_PATH = PHASE68K_DIR / "phase68k_early_entry_compare.csv"
MANIFEST_PATH = PHASE68K_DIR / "phase68k_early_entry_manifest.json"
BASELINE_OUTPUT_PAPER_PATH = PAPERS_DIR / f"{BASELINE_MODEL}_paper.csv"
PROBE_OUTPUT_PAPER_PATH = PAPERS_DIR / f"{PROBE_MODEL}_paper.csv"


@dataclass(frozen=True)
class OverlayConfig:
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
class EarlyEntryConfig:
    early_entry_weight: float = 0.35
    leader_stable_days: int = 2
    trend_improve_days: int = 2
    near_threshold_floor: float = -0.35
    full_threshold: float = 0.0
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

    required = ["strategy_return", "equity"]
    for column in required:
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


def build_candidate_context(core_df: pd.DataFrame, asset_daily: pd.DataFrame, cfg: OverlayConfig) -> pd.DataFrame:
    out = core_df[["strategy_return", "equity", "executed_regime", "executed_position"]].copy()
    aligned_asset = asset_daily.reindex(out.index)
    aligned_asset["candidate_close"] = aligned_asset["candidate_close"].ffill()
    out["candidate_close"] = aligned_asset["candidate_close"]
    out["candidate_return"] = out["candidate_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

    out["core_score"] = rolling_compound_return(out["strategy_return"], cfg.score_lb)
    out["cand_score"] = out["candidate_close"].pct_change(cfg.score_lb)
    out["cand_recent_rel"] = (
        out["candidate_close"].pct_change(cfg.rel_recent_lb) - out["equity"].pct_change(cfg.rel_recent_lb)
    )

    out["cand_fast_ma"] = out["candidate_close"].rolling(cfg.fast_ma, min_periods=cfg.fast_ma).mean()
    out["cand_slow_ma"] = out["candidate_close"].rolling(cfg.slow_ma, min_periods=cfg.slow_ma).mean()
    out["cand_risk_ma"] = out["candidate_close"].rolling(cfg.risk_ma, min_periods=cfg.risk_ma).mean()
    out["cand_vol"] = out["candidate_return"].rolling(cfg.vol_lb, min_periods=cfg.vol_lb).std(ddof=0)

    out["cand_trend_ok"] = (
        (out["candidate_close"] > out["cand_fast_ma"])
        & (out["cand_fast_ma"] > out["cand_slow_ma"])
        & (out["cand_score"] >= cfg.min_score)
    )
    out["candidate_risk_off"] = (
        (out["candidate_close"] < (out["cand_risk_ma"] * (1.0 + cfg.risk_buffer)))
        | (out["cand_vol"] > cfg.vol_cap)
    )
    out["cand_beats_core"] = out["cand_score"] >= (out["core_score"] + cfg.edge_vs_core)
    out["cand_recent_rel_ok"] = out["cand_recent_rel"] >= cfg.rel_recent_min_edge

    out["candidate_signal_raw"] = (
        out["executed_regime"].eq("BASE")
        & out["cand_trend_ok"].fillna(False)
        & (~out["candidate_risk_off"].fillna(True))
        & out["cand_beats_core"].fillna(False)
        & out["cand_recent_rel_ok"].fillna(False)
        & out["candidate_close"].notna()
    )

    raw_signal = out["candidate_signal_raw"].fillna(False).astype(bool).to_numpy()
    if cfg.cooldown_days > 0:
        locked = np.zeros(len(raw_signal), dtype=bool)
        hold = 0
        for idx, flag in enumerate(raw_signal):
            if flag:
                hold = cfg.cooldown_days
            elif hold > 0:
                hold -= 1
            locked[idx] = flag or hold > 0
        out["candidate_signal"] = locked
    else:
        out["candidate_signal"] = raw_signal

    out["candidate_execute"] = pd.Series(out["candidate_signal"], index=out.index).shift(1, fill_value=False)
    return out


def build_trend_improving_flag(trend_score: pd.Series, persistence_days: int) -> pd.Series:
    if persistence_days <= 0:
        return pd.Series(True, index=trend_score.index)
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
    equity = (1.0 + pd.to_numeric(df["strategy_return"], errors="coerce").fillna(0.0)).cumprod()
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


def enrich_metrics(
    df: pd.DataFrame,
    model_name: str,
    *,
    early_entry_days: int,
    avg_lead_days_vs_full_entry: float,
    false_start_count: int,
    captured_pre_breakout_return_pct: float,
) -> dict:
    metrics = calc_metrics(df, model_name)
    metrics["since2023_cagr_pct"] = window_cagr_pct(df, "2023-01-01")
    metrics["since2025_cagr_pct"] = window_cagr_pct(df, "2025-01-01")
    metrics["early_entry_days"] = int(early_entry_days)
    metrics["avg_lead_days_vs_full_entry"] = float(avg_lead_days_vs_full_entry)
    metrics["false_start_count"] = int(false_start_count)
    metrics["captured_pre_breakout_return_pct"] = float(captured_pre_breakout_return_pct)
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase68K dev-only early-entry ladder probe")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--core-paper", type=str, default=str(CORE_PAPER_PATH))
    parser.add_argument("--trend-history", type=str, default=str(TREND_HISTORY_PATH))
    parser.add_argument("--early-entry-weight", type=float, default=0.35)
    parser.add_argument("--leader-stable-days", type=int, default=2)
    parser.add_argument("--trend-improve-days", type=int, default=2)
    parser.add_argument("--near-threshold-floor", type=float, default=-0.35)
    parser.add_argument("--full-threshold", type=float, default=0.0)
    parser.add_argument("--success-resolution-days", type=int, default=2)
    return parser.parse_args()


def build_probe_frame(
    baseline_df: pd.DataFrame,
    core_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    overlay_cfg: OverlayConfig,
    early_cfg: EarlyEntryConfig,
) -> pd.DataFrame:
    frame = baseline_df.copy()
    frame = frame.join(trend_df, how="left")

    frame["selected_asset"] = frame["weekly_authorized_asset"].map(normalize_asset_label)
    fallback_asset = frame["chosen_asset"].map(normalize_asset_label)
    frame["selected_asset"] = np.where(frame["selected_asset"] == "", fallback_asset, frame["selected_asset"])
    frame["selected_asset"] = pd.Series(frame["selected_asset"], index=frame.index).fillna("").astype(str)

    asset_contexts: dict[str, pd.DataFrame] = {}
    for asset in sorted({asset for asset in frame["selected_asset"].unique() if asset}):
        try:
            asset_contexts[asset] = build_candidate_context(core_df, load_asset_daily(asset), overlay_cfg)
        except FileNotFoundError as exc:
            log(f"[PHASE68K] Skipping {asset}: {exc}")

    trend_improving = build_trend_improving_flag(frame["trend_score"], early_cfg.trend_improve_days)
    leader_stable = build_leader_stable_flag(frame["selected_asset"], early_cfg.leader_stable_days)

    frame["baseline_strategy_return"] = frame["strategy_return"].astype(float)
    frame["baseline_executed_regime"] = frame["executed_regime"].astype(str)
    frame["baseline_executed_position"] = frame["executed_position"].astype(str)
    frame["leader_stable"] = leader_stable.astype(bool)
    frame["trend_improving"] = trend_improving.astype(bool)
    frame["candidate_asset_return"] = 0.0
    frame["candidate_risk_off"] = True
    frame["candidate_signal_raw"] = False
    frame["candidate_execute_raw"] = False

    for date_value, row in frame.iterrows():
        asset = row["selected_asset"]
        if not asset:
            continue
        asset_context = asset_contexts.get(asset)
        if asset_context is None or date_value not in asset_context.index:
            continue
        context_row = asset_context.loc[date_value]
        frame.at[date_value, "candidate_asset_return"] = float(context_row.get("candidate_return", 0.0))
        frame.at[date_value, "candidate_risk_off"] = bool(context_row.get("candidate_risk_off", True))
        frame.at[date_value, "candidate_signal_raw"] = bool(context_row.get("candidate_signal_raw", False))
        frame.at[date_value, "candidate_execute_raw"] = bool(context_row.get("candidate_execute", False))

    frame["full_risk_active"] = frame["baseline_executed_regime"].eq("CANDIDATE")
    frame["near_full_threshold"] = (
        frame["trend_score"].notna()
        & frame["trend_score"].lt(early_cfg.full_threshold)
        & frame["trend_score"].ge(early_cfg.near_threshold_floor)
    )
    frame["risk_off_blocked"] = frame["candidate_risk_off"].astype(bool)
    frame["early_setup_ready"] = (
        frame["selected_asset"].ne("")
        & (~frame["full_risk_active"])
        & frame["leader_stable"]
        & frame["trend_improving"]
        & frame["near_full_threshold"]
        & (~frame["risk_off_blocked"])
        & (~frame["candidate_signal_raw"].astype(bool))
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
    frame["equity"] = (1.0 + frame["strategy_return"].astype(float)).cumprod()
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


def build_compare_rows(summary_df: pd.DataFrame) -> pd.DataFrame:
    metric_columns = [
        "cagr_pct",
        "max_drawdown_pct",
        "since2023_cagr_pct",
        "since2025_cagr_pct",
        "calmar",
        "early_entry_days",
        "avg_lead_days_vs_full_entry",
        "false_start_count",
        "captured_pre_breakout_return_pct",
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
    args = parse_args()
    overlay_cfg = OverlayConfig()
    early_cfg = EarlyEntryConfig(
        early_entry_weight=float(args.early_entry_weight),
        leader_stable_days=int(args.leader_stable_days),
        trend_improve_days=int(args.trend_improve_days),
        near_threshold_floor=float(args.near_threshold_floor),
        full_threshold=float(args.full_threshold),
        success_resolution_days=int(args.success_resolution_days),
    )

    ensure_dir(PHASE68K_DIR)
    ensure_dir(PAPERS_DIR)

    baseline_df = load_paper(Path(args.baseline_paper))
    core_df = load_paper(Path(args.core_paper))
    trend_df = load_trend_history(Path(args.trend_history))

    log("[PHASE68K] Building probe frame")
    probe_df = build_probe_frame(baseline_df, core_df, trend_df, overlay_cfg, early_cfg)

    early_entry_days = int(probe_df["ladder_state"].eq("EARLY_RISK").sum())
    avg_lead_days, false_start_count, captured_pre_breakout_return_pct = analyze_early_sequences(
        probe_df,
        early_cfg.success_resolution_days,
    )

    baseline_metrics = enrich_metrics(
        baseline_df,
        BASELINE_MODEL,
        early_entry_days=0,
        avg_lead_days_vs_full_entry=0.0,
        false_start_count=0,
        captured_pre_breakout_return_pct=0.0,
    )
    probe_metrics = enrich_metrics(
        probe_df,
        PROBE_MODEL,
        early_entry_days=early_entry_days,
        avg_lead_days_vs_full_entry=avg_lead_days,
        false_start_count=false_start_count,
        captured_pre_breakout_return_pct=captured_pre_breakout_return_pct,
    )

    summary_df = pd.DataFrame([baseline_metrics, probe_metrics])
    compare_df = build_compare_rows(summary_df)

    baseline_df.reset_index().rename(columns={"index": "date"}).to_csv(BASELINE_OUTPUT_PAPER_PATH, index=False)
    probe_df.reset_index().rename(columns={"index": "date"}).to_csv(PROBE_OUTPUT_PAPER_PATH, index=False)
    summary_df.to_csv(SUMMARY_PATH, index=False)
    compare_df.to_csv(COMPARE_PATH, index=False)

    manifest = {
        "phase": PROBE_MODEL,
        "experiment_scope": "narrow_dev_only_core_probe",
        "official_compare_baseline": BASELINE_MODEL,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "changes_shortlist": False,
        "changes_governance": False,
        "changes_leverage": False,
        "changes_app_live_truth": False,
        "mechanism": {
            "states": ["CASH", "EARLY_RISK", "FULL_RISK"],
            "description": (
                "EARLY_RISK blends the selected leader return into the official phase67j baseline return at a partial "
                "weight until the existing full-risk candidate state is reached."
            ),
        },
        "parameters": {
            "overlay_config_reference": asdict(overlay_cfg),
            "early_entry_config": asdict(early_cfg),
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
            "manifest_file": str(MANIFEST_PATH.resolve()),
            "papers_dir": str(PAPERS_DIR.resolve()),
            "baseline_paper_copy": str(BASELINE_OUTPUT_PAPER_PATH.resolve()),
            "probe_paper": str(PROBE_OUTPUT_PAPER_PATH.resolve()),
        },
        "metric_notes": {
            "avg_lead_days_vs_full_entry": "Average calendar-day lead between EARLY_RISK start and the next resolved FULL_RISK start.",
            "false_start_count": "Count of EARLY_RISK sequences that reverted without resolving into FULL_RISK inside the configured resolution window.",
            "captured_pre_breakout_return_pct": (
                "Compounded incremental return captured by the probe versus the official baseline over successful "
                "pre-full-entry windows."
            ),
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

    best_delta_row = compare_df[compare_df["metric"] == "cagr_pct"].iloc[0]
    log("[PHASE68K] Completed")
    log(
        "[PHASE68K] "
        f"baseline_cagr={baseline_metrics['cagr_pct']:.2f} "
        f"probe_cagr={probe_metrics['cagr_pct']:.2f} "
        f"delta={best_delta_row['delta_probe_minus_baseline']:.2f}"
    )
    log(f"[PHASE68K] Saved summary -> {SUMMARY_PATH}")
    log(f"[PHASE68K] Saved compare -> {COMPARE_PATH}")
    log(f"[PHASE68K] Saved manifest -> {MANIFEST_PATH}")
    log(f"[PHASE68K] Saved papers -> {PAPERS_DIR}")


if __name__ == "__main__":
    main()
