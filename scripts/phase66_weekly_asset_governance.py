from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DATA_DIR = ROOT / "data" / "ohlcv"

CURRENT_WINNER_KEY = "phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3"
CURRENT_WINNER_PAPER = (
    OUTPUTS
    / "phase63_btc_participation_overlay"
    / f"{CURRENT_WINNER_KEY}_paper.csv"
)

PHASE66_DIR = OUTPUTS / "phase66_weekly_asset_governance"

STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "EURC", "PYUSD"}
BAD_NAME_PARTS = {"UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S"}


@dataclass
class OverlayConfig:
    candidate_fast_ma: int = 20
    candidate_slow_ma: int = 100
    candidate_ret_lb: int = 30
    candidate_ret_min: float = 0.12
    candidate_risk_ma: int = 150
    candidate_risk_buffer: float = -0.03
    candidate_vol_lb: int = 30
    candidate_vol_cap: float = 0.045
    weak_base_lb: int = 30
    weak_base_threshold: float = 0.02
    cooldown_days: int = 3


@dataclass
class GovernanceConfig:
    trailing_train_days: int = 365
    recent_days: int = 90
    rebalance_every_days: int = 7
    min_history_days: int = 180
    min_triggers_in_train: int = 3
    min_total_delta_pct: float = 0.0
    min_recent_delta_pct: float = 0.0
    max_allowed_dd_worsen_pct: float = 5.0


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported file type: {path}")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def to_naive_datetime(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce", utc=False)
    try:
        dt = dt.dt.tz_localize(None)
    except Exception:
        pass
    return dt


def parseable_datetime_ratio(series: pd.Series) -> float:
    s = series.astype(str).str.strip()
    s = s.replace({"": np.nan, "nan": np.nan, "NaT": np.nan, "None": np.nan})
    s = s.dropna()
    if s.empty:
        return 0.0
    sample = s.head(200)
    dt = pd.to_datetime(sample, errors="coerce", utc=False)
    return float(dt.notna().mean()) if len(sample) else 0.0


def detect_date_column(df: pd.DataFrame) -> str:
    preferred = [
        "date", "datetime", "timestamp", "time", "dt", "ts",
        "open_time", "open time", "close_time", "close time",
        "index", "Unnamed: 0",
    ]
    for col in preferred:
        if col in df.columns:
            return col

    best_col = None
    best_ratio = 0.0
    for col in df.columns:
        ratio = parseable_datetime_ratio(df[col])
        if ratio > best_ratio:
            best_ratio = ratio
            best_col = col

    if best_col is not None and best_ratio >= 0.50:
        return best_col

    raise ValueError("Nenašiel som dátumový stĺpec.")


def detect_close_column(df: pd.DataFrame) -> str:
    for col in ["close", "Close", "adj_close", "price", "last"]:
        if col in df.columns:
            return col
    for col in df.columns:
        if str(col).lower() == "close":
            return col
    raise ValueError("Nenašiel som close stĺpec.")


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


def standardize_date_index(df: pd.DataFrame) -> pd.DataFrame:
    out = normalize_columns(df)
    date_col = detect_date_column(out)
    out[date_col] = to_naive_datetime(out[date_col])
    out = out.dropna(subset=[date_col]).sort_values(date_col).drop_duplicates(subset=[date_col], keep="last")
    out = out.set_index(date_col)
    return out


def rolling_compound_return(ret: pd.Series, lb: int) -> pd.Series:
    return (1.0 + ret).rolling(lb, min_periods=lb).apply(np.prod, raw=True) - 1.0


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


def load_baseline_paper(path: Path, cfg: OverlayConfig) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing baseline paper: {path}")

    raw = safe_read_table(path)
    raw = standardize_date_index(raw)

    required_numeric = ["strategy_return", "base_return", "btc_return", "equity"]
    for col in required_numeric:
        if col not in raw.columns:
            raise ValueError(f"Baseline paper missing column: {col}")

    executed_regime_col = "executed_regime" if "executed_regime" in raw.columns else "final_regime"
    if executed_regime_col not in raw.columns:
        raise ValueError("Baseline paper missing executed_regime/final_regime")

    pos_col = detect_position_column(raw)
    if pos_col is None:
        raise ValueError("Baseline paper missing executed position column")

    out = pd.DataFrame(index=raw.index.copy())
    out["strategy_return"] = pd.to_numeric(raw["strategy_return"], errors="coerce").fillna(0.0)
    out["base_return"] = pd.to_numeric(raw["base_return"], errors="coerce").fillna(0.0)
    out["btc_return"] = pd.to_numeric(raw["btc_return"], errors="coerce").fillna(0.0)
    out["equity"] = pd.to_numeric(raw["equity"], errors="coerce").ffill().bfill()
    out["executed_regime"] = raw[executed_regime_col].astype(str).fillna("NA").str.upper()
    out["executed_position"] = raw[pos_col].astype(str).fillna("NA").str.upper().str.strip()
    out["base_strength_lb"] = rolling_compound_return(out["base_return"], cfg.weak_base_lb)
    out["baseline_is_weak"] = out["base_strength_lb"] <= cfg.weak_base_threshold
    return out


def normalize_asset_name(asset: str) -> str:
    if asset == "HYPERLIQUID":
        return "HYPE"
    return asset.upper().strip()


def extract_asset_from_path(path: Path) -> str:
    parts = re.split(r"[^A-Z0-9]+", path.stem.upper())
    parts = [p for p in parts if p]
    for part in parts:
        for quote in ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USD"]:
            if part.endswith(quote) and len(part) > len(quote):
                return normalize_asset_name(part[: -len(quote)])
    for part in parts:
        if part not in {"1D", "1H", "4H", "5M", "15M", "30M", "DAILY", "OHLCV", "DATA"} and len(part) >= 2:
            return normalize_asset_name(part)
    return ""


def is_bad_asset_name(asset: str) -> bool:
    if not asset:
        return True
    if asset in STABLES:
        return True
    if asset == "BTC":
        return True
    if asset.startswith("1000"):
        return True
    for part in BAD_NAME_PARTS:
        if asset.endswith(part):
            return True
    return False


def discover_best_file_per_asset() -> dict[str, Path]:
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Missing data dir: {DATA_DIR}")

    files = list(DATA_DIR.rglob("*.csv")) + list(DATA_DIR.rglob("*.parquet")) + list(DATA_DIR.rglob("*.pq"))
    best: dict[str, tuple[int, int, Path]] = {}

    for path in files:
        asset = extract_asset_from_path(path)
        if is_bad_asset_name(asset):
            continue

        score = 0
        full = str(path).upper()
        if "USDT" in full:
            score += 30
        if "1D" in full or "DAILY" in full:
            score += 20
        if "OHLCV" in full:
            score += 5

        item = (score, -len(full), path)
        if asset not in best or item > best[asset]:
            best[asset] = item

    return {asset: tpl[2] for asset, tpl in best.items()}


def load_asset_daily_prices(path: Path, value_col_name: str) -> tuple[pd.DataFrame, dict]:
    raw = safe_read_table(path)
    raw = normalize_columns(raw)
    date_col = detect_date_column(raw)
    close_col = detect_close_column(raw)

    raw[date_col] = to_naive_datetime(raw[date_col])
    raw[close_col] = pd.to_numeric(raw[close_col], errors="coerce")
    raw = raw.dropna(subset=[date_col]).sort_values(date_col)

    x = raw[[date_col, close_col]].rename(columns={date_col: "ts", close_col: "close"}).copy()
    x["day"] = pd.to_datetime(x["ts"]).dt.normalize()
    x = x.dropna(subset=["day"])
    daily = x.groupby("day", as_index=True)["close"].last().to_frame(value_col_name).sort_index()

    quality = {
        "raw_rows": int(len(raw)),
        "daily_rows": int(len(daily)),
        "start_date": daily.index.min().date().isoformat() if len(daily) else "",
        "end_date": daily.index.max().date().isoformat() if len(daily) else "",
        "history_days": int((daily.index.max() - daily.index.min()).days + 1) if len(daily) else 0,
        "non_na_close_ratio": float(daily[value_col_name].notna().mean()) * 100.0 if len(daily) else 0.0,
        "max_gap_days": 0,
    }
    if len(daily) >= 2:
        gaps = pd.Series(daily.index).diff().dt.days.dropna()
        quality["max_gap_days"] = int(gaps.max()) if not gaps.empty else 0
    return daily, quality


def align_candidate_to_baseline(baseline: pd.DataFrame, candidate: pd.DataFrame) -> pd.DataFrame:
    x = baseline.copy()
    c = candidate.copy().reindex(x.index)
    c["candidate_close"] = c["candidate_close"].ffill()
    x["candidate_close"] = c["candidate_close"]
    x["candidate_return"] = x["candidate_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return x


def compute_asset_signal(df: pd.DataFrame, cfg: OverlayConfig) -> pd.DataFrame:
    x = df.copy()

    x["cand_fast_ma"] = x["candidate_close"].rolling(cfg.candidate_fast_ma, min_periods=cfg.candidate_fast_ma).mean()
    x["cand_slow_ma"] = x["candidate_close"].rolling(cfg.candidate_slow_ma, min_periods=cfg.candidate_slow_ma).mean()
    x["cand_risk_ma"] = x["candidate_close"].rolling(cfg.candidate_risk_ma, min_periods=cfg.candidate_risk_ma).mean()
    x["cand_ret_lb"] = x["candidate_close"].pct_change(cfg.candidate_ret_lb)
    x["cand_vol"] = x["candidate_return"].rolling(cfg.candidate_vol_lb, min_periods=cfg.candidate_vol_lb).std(ddof=0)

    x["candidate_trend_ok"] = (
        (x["candidate_close"] > x["cand_fast_ma"])
        & (x["cand_fast_ma"] > x["cand_slow_ma"])
        & (x["cand_ret_lb"] >= cfg.candidate_ret_min)
    )
    x["candidate_risk_off"] = (
        (x["candidate_close"] < (x["cand_risk_ma"] * (1.0 + cfg.candidate_risk_buffer)))
        | (x["cand_vol"] > cfg.candidate_vol_cap)
    )

    x["candidate_signal_raw"] = (
        x["executed_regime"].eq("BASE")
        & x["baseline_is_weak"].fillna(False)
        & x["candidate_trend_ok"].fillna(False)
        & (~x["candidate_risk_off"].fillna(True))
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


def build_asset_strategy(baseline: pd.DataFrame, candidate: pd.DataFrame, cfg: OverlayConfig, asset: str) -> pd.DataFrame:
    x = align_candidate_to_baseline(baseline, candidate)
    x = compute_asset_signal(x, cfg)

    out = x.copy()
    out["executed_regime"] = np.where(out["candidate_execute"], "CANDIDATE", out["executed_regime"])
    out["executed_position"] = np.where(out["candidate_execute"], asset, out["executed_position"])
    out["strategy_return"] = np.where(out["candidate_execute"], out["candidate_return"], out["strategy_return"])
    out["equity"] = (1.0 + pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)).cumprod()
    return out


def slice_metrics_from_returns(returns: pd.Series) -> tuple[float, float]:
    x = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    eq = (1.0 + x).cumprod()
    total = float(eq.iloc[-1] / eq.iloc[0] - 1.0) if len(eq) > 1 else 0.0
    dd = max_drawdown_from_equity(eq)
    return total * 100.0, dd * 100.0


def build_rebalance_dates(index: pd.DatetimeIndex, train_days: int, step_days: int) -> list[pd.Timestamp]:
    dates = []
    if len(index) <= train_days:
        return dates
    start_pos = train_days
    pos = start_pos
    while pos < len(index) - 1:
        dates.append(index[pos])
        pos += step_days
    return dates


def choose_asset_for_date(
    decision_date: pd.Timestamp,
    next_date: pd.Timestamp,
    baseline: pd.DataFrame,
    asset_strategies: dict[str, pd.DataFrame],
    gov_cfg: GovernanceConfig,
) -> tuple[str, dict, pd.DataFrame]:
    idx = baseline.index
    decision_loc = idx.get_loc(decision_date)
    train_start_loc = max(0, decision_loc - gov_cfg.trailing_train_days + 1)
    recent_start_loc = max(0, decision_loc - gov_cfg.recent_days + 1)

    train_idx = idx[train_start_loc:decision_loc + 1]
    recent_idx = idx[recent_start_loc:decision_loc + 1]

    base_train_total, base_train_dd = slice_metrics_from_returns(baseline.loc[train_idx, "strategy_return"])
    base_recent_total, _ = slice_metrics_from_returns(baseline.loc[recent_idx, "strategy_return"])

    rows = []
    best_asset = ""
    best_score = -1e18

    for asset, df in asset_strategies.items():
        train_total, train_dd = slice_metrics_from_returns(df.loc[train_idx, "strategy_return"])
        recent_total, _ = slice_metrics_from_returns(df.loc[recent_idx, "strategy_return"])
        train_delta = train_total - base_train_total
        recent_delta = recent_total - base_recent_total
        dd_worsen = train_dd - base_train_dd
        triggers = int(df.loc[train_idx, "candidate_execute"].sum())

        passed = (
            triggers >= gov_cfg.min_triggers_in_train
            and train_delta >= gov_cfg.min_total_delta_pct
            and recent_delta >= gov_cfg.min_recent_delta_pct
            and dd_worsen <= gov_cfg.max_allowed_dd_worsen_pct
        )

        score = (recent_delta * 4.0) + (train_delta * 1.5) - max(0.0, dd_worsen) * 1.25 + triggers * 0.15

        row = {
            "decision_date": decision_date.strftime("%Y-%m-%d"),
            "next_date_exclusive": next_date.strftime("%Y-%m-%d"),
            "asset": asset,
            "train_total_delta_pct": train_delta,
            "recent_total_delta_pct": recent_delta,
            "train_dd_worsen_pct": dd_worsen,
            "train_triggers": triggers,
            "score": score,
            "passed_filters": passed,
        }
        rows.append(row)

        if passed and score > best_score:
            best_score = score
            best_asset = asset

    leaderboard = pd.DataFrame(rows).sort_values(
        by=["passed_filters", "score", "recent_total_delta_pct", "train_total_delta_pct"],
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    choice_meta = {}
    if best_asset:
        top = leaderboard[leaderboard["asset"] == best_asset].iloc[0].to_dict()
        choice_meta = top

    return best_asset, choice_meta, leaderboard


def simulate_governance_strategy(
    baseline: pd.DataFrame,
    asset_strategies: dict[str, pd.DataFrame],
    gov_cfg: GovernanceConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    idx = baseline.index
    rebalance_dates = build_rebalance_dates(idx, gov_cfg.trailing_train_days, gov_cfg.rebalance_every_days)

    governance = baseline.copy()
    governance["chosen_asset"] = ""
    governance["weekly_authorized_asset"] = ""
    governance["strategy_return"] = pd.to_numeric(governance["strategy_return"], errors="coerce").fillna(0.0)
    governance["executed_regime"] = governance["executed_regime"].astype(str)
    governance["executed_position"] = governance["executed_position"].astype(str)

    decision_rows = []
    leaderboard_rows = []

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

        selected_asset, meta, leaderboard = choose_asset_for_date(
            decision_date=decision_date,
            next_date=next_date,
            baseline=baseline,
            asset_strategies=asset_strategies,
            gov_cfg=gov_cfg,
        )

        if not leaderboard.empty:
            leaderboard["selected_asset"] = selected_asset
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
                "decision_date": decision_date.strftime("%Y-%m-%d"),
                "period_start": period_idx[0].strftime("%Y-%m-%d"),
                "period_end": period_idx[-1].strftime("%Y-%m-%d"),
                "selected_asset": selected_asset,
                "selected": bool(selected_asset),
                "selected_score": meta.get("score", np.nan),
                "selected_train_total_delta_pct": meta.get("train_total_delta_pct", np.nan),
                "selected_recent_total_delta_pct": meta.get("recent_total_delta_pct", np.nan),
                "selected_train_dd_worsen_pct": meta.get("train_dd_worsen_pct", np.nan),
                "selected_train_triggers": meta.get("train_triggers", np.nan),
            }
        )

    governance["equity"] = (1.0 + pd.to_numeric(governance["strategy_return"], errors="coerce").fillna(0.0)).cumprod()

    decisions_df = pd.DataFrame(decision_rows)
    leaderboard_df = pd.concat(leaderboard_rows, ignore_index=True) if leaderboard_rows else pd.DataFrame()

    return governance, decisions_df, leaderboard_df


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE66 weekly asset governance")
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    parser.add_argument("--manual-assets", type=str, default="DOGE,XRP,SUI,HYPE")
    parser.add_argument("--train-days", type=int, default=365)
    parser.add_argument("--recent-days", type=int, default=90)
    parser.add_argument("--rebalance-days", type=int, default=7)
    parser.add_argument("--min-history-days", type=int, default=180)
    parser.add_argument("--min-triggers", type=int, default=3)
    parser.add_argument("--min-train-delta", type=float, default=0.0)
    parser.add_argument("--min-recent-delta", type=float, default=0.0)
    parser.add_argument("--max-dd-worsen", type=float, default=5.0)
    args = parser.parse_args()

    ensure_dir(PHASE66_DIR)

    overlay_cfg = OverlayConfig()
    gov_cfg = GovernanceConfig(
        trailing_train_days=args.train_days,
        recent_days=args.recent_days,
        rebalance_every_days=args.rebalance_days,
        min_history_days=args.min_history_days,
        min_triggers_in_train=args.min_triggers,
        min_total_delta_pct=args.min_train_delta,
        min_recent_delta_pct=args.min_recent_delta,
        max_allowed_dd_worsen_pct=args.max_dd_worsen,
    )

    log("[PHASE66] Start")
    log(f"[PHASE66] Baseline paper: {args.baseline_paper}")

    baseline = load_baseline_paper(Path(args.baseline_paper), overlay_cfg)

    best_files = discover_best_file_per_asset()
    manual_assets = [normalize_asset_name(x) for x in re.split(r"[,\s;]+", args.manual_assets.strip()) if x.strip()]

    candidate_assets = sorted(best_files.keys())
    for asset in manual_assets:
        if asset not in candidate_assets and asset in best_files:
            candidate_assets.append(asset)

    asset_strategies: dict[str, pd.DataFrame] = {}
    asset_quality_rows = []
    failed_assets = []

    for asset in candidate_assets:
        try:
            file_path = best_files[asset]
            daily, q = load_asset_daily_prices(file_path, "candidate_close")
            if q["history_days"] < gov_cfg.min_history_days:
                continue
            strat = build_asset_strategy(baseline, daily, overlay_cfg, asset)
            asset_strategies[asset] = strat
            asset_quality_rows.append(
                {
                    "asset": asset,
                    "file": str(file_path),
                    **q,
                }
            )
        except Exception as e:
            failed_assets.append({"asset": asset, "reason": str(e)})

    log(f"[PHASE66] Candidate assets loaded: {len(asset_strategies)}")

    governance, decisions_df, leaderboard_df = simulate_governance_strategy(
        baseline=baseline,
        asset_strategies=asset_strategies,
        gov_cfg=gov_cfg,
    )

    base_row = calc_metrics(baseline, CURRENT_WINNER_KEY)
    base_row.update(window_metrics(baseline, "2021-01-01"))
    base_row.update(window_metrics(baseline, "2023-01-01"))
    base_row.update(window_metrics(baseline, "2025-01-01"))
    base_row["mode"] = "baseline"

    gov_row = calc_metrics(governance, "phase66_weekly_asset_governance")
    gov_row.update(window_metrics(governance, "2021-01-01"))
    gov_row.update(window_metrics(governance, "2023-01-01"))
    gov_row.update(window_metrics(governance, "2025-01-01"))
    gov_row["mode"] = "weekly_governance"
    for metric in [
        "cagr_pct",
        "max_drawdown_pct",
        "since2021_cagr_pct",
        "since2023_cagr_pct",
        "since2025_cagr_pct",
    ]:
        gov_row[f"delta_vs_phase63_{metric}"] = pd.to_numeric(gov_row.get(metric), errors="coerce") - pd.to_numeric(base_row.get(metric), errors="coerce")

    selected_nonempty = governance["chosen_asset"].astype(str)
    gov_row["unique_selected_assets"] = int(selected_nonempty[selected_nonempty != ""].nunique())
    gov_row["selected_days_pct"] = float((selected_nonempty != "").mean() * 100.0)
    gov_row["decision_count"] = int(len(decisions_df))
    gov_row["selection_count"] = int(decisions_df["selected"].sum()) if not decisions_df.empty else 0

    summary = pd.DataFrame([base_row, gov_row])

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

    summary_path = PHASE66_DIR / "phase66_weekly_asset_governance_summary.csv"
    compare_path = PHASE66_DIR / "phase66_weekly_asset_governance_compare.csv"
    decisions_path = PHASE66_DIR / "phase66_weekly_asset_governance_decisions.csv"
    leaderboard_path = PHASE66_DIR / "phase66_weekly_asset_governance_leaderboard.csv"
    asset_quality_path = PHASE66_DIR / "phase66_weekly_asset_governance_asset_quality.csv"
    asset_usage_path = PHASE66_DIR / "phase66_weekly_asset_governance_asset_usage.csv"
    failed_assets_path = PHASE66_DIR / "phase66_weekly_asset_governance_failed_assets.csv"
    baseline_paper_path = PHASE66_DIR / f"{CURRENT_WINNER_KEY}_paper.csv"
    governance_paper_path = PHASE66_DIR / "phase66_weekly_asset_governance_paper.csv"
    manifest_path = PHASE66_DIR / "phase66_manifest.json"

    summary.to_csv(summary_path, index=False)
    summary.to_csv(compare_path, index=False)
    decisions_df.to_csv(decisions_path, index=False)
    leaderboard_df.to_csv(leaderboard_path, index=False)
    pd.DataFrame(asset_quality_rows).to_csv(asset_quality_path, index=False)
    asset_usage.to_csv(asset_usage_path, index=False)
    pd.DataFrame(failed_assets).to_csv(failed_assets_path, index=False)

    baseline.reset_index().rename(columns={baseline.index.name or "index": "date"}).to_csv(baseline_paper_path, index=False)
    governance.reset_index().rename(columns={governance.index.name or "index": "date"}).to_csv(governance_paper_path, index=False)

    manifest = {
        "phase": "phase66_weekly_asset_governance",
        "baseline_model": CURRENT_WINNER_KEY,
        "baseline_paper": str(args.baseline_paper),
        "candidate_assets_loaded": int(len(asset_strategies)),
        "candidate_assets_failed": int(len(failed_assets)),
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "decisions_file": str(decisions_path),
        "leaderboard_file": str(leaderboard_path),
        "asset_quality_file": str(asset_quality_path),
        "asset_usage_file": str(asset_usage_path),
        "failed_assets_file": str(failed_assets_path),
        "baseline_paper_saved": str(baseline_paper_path),
        "governance_paper_saved": str(governance_paper_path),
        "overlay_config": vars(overlay_cfg),
        "governance_config": vars(gov_cfg),
        "notes": [
            "Future-safe weekly asset governance.",
            "Každý týždeň sa asset vyberá len z minulých dát.",
            "Ak nikto neprejde filtrom, ostáva baseline.",
            "Toto nie je hindsight vypínanie assetu podľa budúcnosti.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE66 TOP RESULT ===")
    log(f"model: {gov_row['model']}")
    log(f"cagr_pct: {gov_row['cagr_pct']:.2f}")
    log(f"max_drawdown_pct: {gov_row['max_drawdown_pct']:.2f}")
    log(f"since2023_cagr_pct: {gov_row['since2023_cagr_pct']:.2f}")
    log(f"since2025_cagr_pct: {gov_row['since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_cagr_pct: {gov_row['delta_vs_phase63_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_since2023_cagr_pct: {gov_row['delta_vs_phase63_since2023_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_since2025_cagr_pct: {gov_row['delta_vs_phase63_since2025_cagr_pct']:.2f}")
    log(f"delta_vs_phase63_max_drawdown_pct: {gov_row['delta_vs_phase63_max_drawdown_pct']:.2f}")
    log(f"candidate_assets_loaded: {len(asset_strategies)}")
    log(f"decision_count: {gov_row['decision_count']}")
    log(f"selection_count: {gov_row['selection_count']}")
    log(f"unique_selected_assets: {gov_row['unique_selected_assets']}")
    log("")

    if not asset_usage.empty:
        top = asset_usage.head(5)
        log("=== PHASE66 TOP USED ASSETS ===")
        for _, row in top.iterrows():
            log(f"{row['asset']}: {int(row['selected_days'])} days ({row['selected_days_pct']:.2f}%)")
        log("")

    log(f"[PHASE66] Saved summary -> {summary_path}")
    log(f"[PHASE66] Saved compare -> {compare_path}")
    log(f"[PHASE66] Saved decisions -> {decisions_path}")
    log(f"[PHASE66] Saved leaderboard -> {leaderboard_path}")
    log(f"[PHASE66] Saved asset quality -> {asset_quality_path}")
    log(f"[PHASE66] Saved asset usage -> {asset_usage_path}")
    log(f"[PHASE66] Saved failed assets -> {failed_assets_path}")
    log(f"[PHASE66] Saved baseline paper -> {baseline_paper_path}")
    log(f"[PHASE66] Saved governance paper -> {governance_paper_path}")
    log(f"[PHASE66] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()