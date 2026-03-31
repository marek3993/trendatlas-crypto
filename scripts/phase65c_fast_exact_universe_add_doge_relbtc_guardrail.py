from __future__ import annotations

import argparse
import json
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
BTC_FILE_DEFAULT = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"

PHASE65C_FAST_DIR = OUTPUTS / "phase65c_fast_exact_universe_add_doge_relbtc_guardrail"


@dataclass
class VariantConfig:
    name: str
    score_lb: int
    doge_fast_ma: int
    doge_slow_ma: int
    doge_min_score: float
    doge_edge_vs_base: float
    rel_btc_lb: int
    rel_btc_min_edge: float
    doge_risk_ma: int
    doge_risk_buffer: float
    doge_vol_lb: int
    doge_vol_cap: float
    cooldown_days: int = 0


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
        out["doge_days_pct"] = float((r == "DOGE").mean() * 100.0)
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


def load_baseline_paper(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing baseline paper: {path}")

    raw = safe_read_table(path)
    raw = standardize_date_index(raw)

    required_numeric = ["strategy_return", "base_return", "btc_return", "equity"]
    for col in required_numeric:
        if col not in raw.columns:
            raise ValueError(f"Baseline paper missing column: {col}")

    regime_col = "executed_regime" if "executed_regime" in raw.columns else "final_regime"
    if regime_col not in raw.columns:
        raise ValueError("Baseline paper missing executed_regime/final_regime")

    pos_col = detect_position_column(raw)
    if pos_col is None:
        raise ValueError("Baseline paper missing executed position column")

    out = pd.DataFrame(index=raw.index.copy())
    out["strategy_return"] = pd.to_numeric(raw["strategy_return"], errors="coerce").fillna(0.0)
    out["base_return"] = pd.to_numeric(raw["base_return"], errors="coerce").fillna(0.0)
    out["btc_return"] = pd.to_numeric(raw["btc_return"], errors="coerce").fillna(0.0)
    out["equity"] = pd.to_numeric(raw["equity"], errors="coerce").ffill().bfill()
    out["executed_regime"] = raw[regime_col].astype(str).fillna("NA").str.upper()
    out["executed_position"] = raw[pos_col].astype(str).fillna("NA").str.upper().str.strip()
    return out


def normalize_asset_name(asset: str) -> str:
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


def discover_asset_file(asset: str) -> Path:
    asset = normalize_asset_name(asset)
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Missing data dir: {DATA_DIR}")

    files = list(DATA_DIR.rglob("*.csv")) + list(DATA_DIR.rglob("*.parquet")) + list(DATA_DIR.rglob("*.pq"))
    candidates: list[tuple[int, int, Path]] = []

    for path in files:
        path_asset = extract_asset_from_path(path)
        if path_asset != asset:
            continue
        score = 0
        full = str(path).upper()
        if "USDT" in full:
            score += 30
        if "1D" in full or "DAILY" in full:
            score += 20
        if "OHLCV" in full:
            score += 5
        candidates.append((score, -len(full), path))

    if not candidates:
        raise FileNotFoundError(f"Nenašiel som input file pre asset {asset} v {DATA_DIR}")

    candidates.sort(reverse=True)
    return candidates[0][2]


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


def align_inputs(
    baseline: pd.DataFrame,
    doge_df: pd.DataFrame,
    btc_df: pd.DataFrame,
) -> pd.DataFrame:
    x = baseline.copy()

    d = doge_df.copy().reindex(x.index)
    d["doge_close"] = d["doge_close"].ffill()
    x["doge_close"] = d["doge_close"]
    x["doge_return"] = x["doge_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

    b = btc_df.copy().reindex(x.index)
    b["btc_close_ext"] = b["btc_close_ext"].ffill()
    x["btc_close_ext"] = b["btc_close_ext"]
    x["btc_return_ext"] = x["btc_close_ext"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

    return x


def build_fast_variants() -> list[VariantConfig]:
    variants = [
        VariantConfig("phase65c_fast_a", 30, 20, 100, 0.16, 0.06, 30, 0.03, 150, -0.03, 20, 0.045, 3),
        VariantConfig("phase65c_fast_b", 30, 20, 100, 0.16, 0.06, 45, 0.03, 150, -0.03, 20, 0.045, 3),
        VariantConfig("phase65c_fast_c", 30, 20, 100, 0.16, 0.06, 45, 0.06, 150, -0.03, 20, 0.045, 3),
        VariantConfig("phase65c_fast_d", 45, 30, 150, 0.20, 0.06, 45, 0.06, 200, 0.00, 20, 0.035, 3),
        VariantConfig("phase65c_fast_e", 45, 30, 150, 0.20, 0.09, 45, 0.06, 200, 0.00, 20, 0.035, 5),
        VariantConfig("phase65c_fast_f", 30, 20, 100, 0.16, 0.09, 60, 0.06, 150, -0.03, 20, 0.045, 3),
        VariantConfig("phase65c_fast_g", 30, 20, 100, 0.12, 0.06, 60, 0.10, 150, -0.03, 20, 0.045, 3),
        VariantConfig("phase65c_fast_h", 45, 30, 150, 0.16, 0.06, 60, 0.10, 200, 0.00, 20, 0.035, 5),
        VariantConfig("phase65c_fast_i", 20, 20, 100, 0.16, 0.03, 30, 0.06, 150, -0.03, 30, 0.045, 3),
        VariantConfig("phase65c_fast_j", 30, 30, 150, 0.16, 0.06, 30, 0.10, 200, 0.00, 20, 0.035, 5),
        VariantConfig("phase65c_fast_k", 45, 20, 100, 0.20, 0.09, 60, 0.10, 200, 0.00, 20, 0.035, 5),
        VariantConfig("phase65c_fast_l", 30, 20, 100, 0.16, 0.06, 45, 0.10, 150, -0.03, 20, 0.035, 3),
    ]
    return variants


def compute_signal_columns(df: pd.DataFrame, cfg: VariantConfig) -> pd.DataFrame:
    x = df.copy()

    x["base_proxy_score"] = rolling_compound_return(x["base_return"], cfg.score_lb)
    x["doge_score"] = x["doge_close"].pct_change(cfg.score_lb)
    x["btc_score_for_rel"] = x["btc_close_ext"].pct_change(cfg.rel_btc_lb)
    x["doge_rel_btc_score"] = x["doge_close"].pct_change(cfg.rel_btc_lb) - x["btc_score_for_rel"]

    x["doge_fast_ma"] = x["doge_close"].rolling(cfg.doge_fast_ma, min_periods=cfg.doge_fast_ma).mean()
    x["doge_slow_ma"] = x["doge_close"].rolling(cfg.doge_slow_ma, min_periods=cfg.doge_slow_ma).mean()
    x["doge_risk_ma"] = x["doge_close"].rolling(cfg.doge_risk_ma, min_periods=cfg.doge_risk_ma).mean()
    x["doge_vol"] = x["doge_return"].rolling(cfg.doge_vol_lb, min_periods=cfg.doge_vol_lb).std(ddof=0)

    x["doge_trend_ok"] = (
        (x["doge_close"] > x["doge_fast_ma"])
        & (x["doge_fast_ma"] > x["doge_slow_ma"])
        & (x["doge_score"] >= cfg.doge_min_score)
    )

    x["doge_risk_off"] = (
        (x["doge_close"] < (x["doge_risk_ma"] * (1.0 + cfg.doge_risk_buffer)))
        | (x["doge_vol"] > cfg.doge_vol_cap)
    )

    x["doge_beats_base"] = x["doge_score"] >= (x["base_proxy_score"] + cfg.doge_edge_vs_base)
    x["doge_rel_btc_ok"] = x["doge_rel_btc_score"] >= cfg.rel_btc_min_edge

    x["doge_signal_raw"] = (
        x["executed_regime"].eq("BASE")
        & x["doge_trend_ok"].fillna(False)
        & (~x["doge_risk_off"].fillna(True))
        & x["doge_beats_base"].fillna(False)
        & x["doge_rel_btc_ok"].fillna(False)
        & x["doge_close"].notna()
        & (~x["executed_position"].eq("DOGE"))
    )

    raw = x["doge_signal_raw"].fillna(False).astype(bool).values
    if cfg.cooldown_days > 0:
        locked = np.zeros(len(raw), dtype=bool)
        hold = 0
        for i, flag in enumerate(raw):
            if flag:
                hold = cfg.cooldown_days
            elif hold > 0:
                hold -= 1
            locked[i] = flag or hold > 0
        x["doge_signal"] = locked
    else:
        x["doge_signal"] = raw

    x["doge_execute"] = pd.Series(x["doge_signal"], index=x.index).shift(1, fill_value=False)
    return x


def simulate_variant(
    baseline: pd.DataFrame,
    doge_daily: pd.DataFrame,
    btc_daily: pd.DataFrame,
    cfg: VariantConfig,
) -> pd.DataFrame:
    x = align_inputs(baseline, doge_daily, btc_daily)
    x = compute_signal_columns(x, cfg)

    out = x.copy()
    out["executed_regime"] = np.where(out["doge_execute"], "DOGE", out["executed_regime"])
    out["executed_position"] = np.where(out["doge_execute"], "DOGE", out["executed_position"])
    out["strategy_return"] = np.where(out["doge_execute"], out["doge_return"], out["strategy_return"])
    out["equity"] = (1.0 + pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)).cumprod()
    return out


def add_deltas(target: dict, base: dict) -> dict:
    out = target.copy()
    for metric in [
        "cagr_pct",
        "max_drawdown_pct",
        "since2021_cagr_pct",
        "since2023_cagr_pct",
        "since2025_cagr_pct",
    ]:
        out[f"delta_vs_phase63_{metric}"] = (
            pd.to_numeric(out.get(metric), errors="coerce")
            - pd.to_numeric(base.get(metric), errors="coerce")
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE65C FAST exact DOGE challenger with relBTC gate + 2025 guardrail")
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    parser.add_argument("--doge-file", type=str, default="")
    parser.add_argument("--btc-file", type=str, default=str(BTC_FILE_DEFAULT))
    parser.add_argument("--top-n-save", type=int, default=8)
    parser.add_argument("--min-since2025-delta", type=float, default=-5.0)
    args = parser.parse_args()

    ensure_dir(PHASE65C_FAST_DIR)

    log("[PHASE65C_FAST] Start")
    log(f"[PHASE65C_FAST] Baseline paper: {args.baseline_paper}")
    log(f"[PHASE65C_FAST] Min since2025 delta: {args.min_since2025_delta:.2f} p.b.")

    baseline = load_baseline_paper(Path(args.baseline_paper))

    doge_file = Path(args.doge_file) if args.doge_file else discover_asset_file("DOGE")
    btc_file = Path(args.btc_file)
    log(f"[PHASE65C_FAST] DOGE file: {doge_file}")
    log(f"[PHASE65C_FAST] BTC file: {btc_file}")

    doge_daily, doge_quality = load_asset_daily_prices(doge_file, "doge_close")
    btc_daily, btc_quality = load_asset_daily_prices(btc_file, "btc_close_ext")

    variants = build_fast_variants()
    log(f"[PHASE65C_FAST] Variants: {len(variants)}")

    base_row = calc_metrics(baseline, CURRENT_WINNER_KEY)
    base_row.update(window_metrics(baseline, "2021-01-01"))
    base_row.update(window_metrics(baseline, "2023-01-01"))
    base_row.update(window_metrics(baseline, "2025-01-01"))
    base_row["asset"] = ""
    base_row["doge_days_pct"] = 0.0
    base_row["signal_days_pct"] = 0.0
    base_row["trigger_days"] = 0
    base_row["passes_2025_guardrail"] = True
    base_row["source"] = "current_phase63_winner"

    rows = [base_row]
    papers_for_top = {CURRENT_WINNER_KEY: baseline.copy()}

    for cfg in variants:
        try:
            sim = simulate_variant(baseline, doge_daily, btc_daily, cfg)
            row = calc_metrics(sim, cfg.name)
            row.update(window_metrics(sim, "2021-01-01"))
            row.update(window_metrics(sim, "2023-01-01"))
            row.update(window_metrics(sim, "2025-01-01"))
            row = add_deltas(row, base_row)

            row["asset"] = "DOGE"
            row["score_lb"] = cfg.score_lb
            row["doge_fast_ma"] = cfg.doge_fast_ma
            row["doge_slow_ma"] = cfg.doge_slow_ma
            row["doge_min_score"] = cfg.doge_min_score
            row["doge_edge_vs_base"] = cfg.doge_edge_vs_base
            row["rel_btc_lb"] = cfg.rel_btc_lb
            row["rel_btc_min_edge"] = cfg.rel_btc_min_edge
            row["doge_risk_ma"] = cfg.doge_risk_ma
            row["doge_risk_buffer"] = cfg.doge_risk_buffer
            row["doge_vol_lb"] = cfg.doge_vol_lb
            row["doge_vol_cap"] = cfg.doge_vol_cap
            row["cooldown_days"] = cfg.cooldown_days
            row["signal_days_pct"] = float(sim["doge_signal"].mean() * 100.0)
            row["doge_days_pct"] = float(sim["doge_execute"].mean() * 100.0)
            row["trigger_days"] = int(sim["doge_signal_raw"].sum())
            row["doge_data_start"] = doge_quality["start_date"]
            row["doge_data_end"] = doge_quality["end_date"]
            row["btc_data_start"] = btc_quality["start_date"]
            row["btc_data_end"] = btc_quality["end_date"]
            row["passes_2025_guardrail"] = (
                pd.to_numeric(row.get("delta_vs_phase63_since2025_cagr_pct"), errors="coerce") >= args.min_since2025_delta
            )
            row["source"] = "phase65c_fast_exact_doge_relbtc_guardrail"

            rows.append(row)
            papers_for_top[cfg.name] = sim
            log(f"[PHASE65C_FAST] done {cfg.name}")
        except Exception as e:
            log(f"[WARN] {cfg.name} failed: {e}")

    summary = pd.DataFrame(rows)

    sort_cols = [
        "delta_vs_phase63_since2023_cagr_pct",
        "delta_vs_phase63_cagr_pct",
        "delta_vs_phase63_max_drawdown_pct",
        "delta_vs_phase63_since2025_cagr_pct",
    ]
    for col in sort_cols:
        if col not in summary.columns:
            summary[col] = np.nan

    baseline_df = summary[summary["model"] == CURRENT_WINNER_KEY].copy()
    cand_df = summary[summary["model"] != CURRENT_WINNER_KEY].copy()

    pass_df = cand_df[cand_df["passes_2025_guardrail"] == True].copy()
    fail_df = cand_df[cand_df["passes_2025_guardrail"] != True].copy()

    pass_df = pass_df.sort_values(by=sort_cols, ascending=[False, False, False, False], na_position="last").reset_index(drop=True)
    fail_df = fail_df.sort_values(
        by=[
            "delta_vs_phase63_since2025_cagr_pct",
            "delta_vs_phase63_since2023_cagr_pct",
            "delta_vs_phase63_cagr_pct",
            "delta_vs_phase63_max_drawdown_pct",
        ],
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    final_summary = pd.concat([baseline_df, pass_df, fail_df], ignore_index=True)
    compare_df = pd.concat([baseline_df, pass_df.head(20)], ignore_index=True)

    summary_path = PHASE65C_FAST_DIR / "phase65c_fast_exact_universe_add_doge_relbtc_guardrail_summary.csv"
    compare_path = PHASE65C_FAST_DIR / "phase65c_fast_exact_universe_add_doge_relbtc_guardrail_compare.csv"
    rejected_path = PHASE65C_FAST_DIR / "phase65c_fast_exact_universe_add_doge_relbtc_guardrail_rejected.csv"
    manifest_path = PHASE65C_FAST_DIR / "phase65c_fast_manifest.json"

    final_summary.to_csv(summary_path, index=False)
    compare_df.to_csv(compare_path, index=False)
    fail_df.to_csv(rejected_path, index=False)

    top_models = [CURRENT_WINNER_KEY] + pass_df["model"].head(max(args.top_n_save, 1)).astype(str).tolist()
    for model in top_models:
        paper = papers_for_top.get(model)
        if paper is None:
            continue
        out_path = PHASE65C_FAST_DIR / f"{model}_paper.csv"
        paper.reset_index().rename(columns={paper.index.name or "index": "date"}).to_csv(out_path, index=False)

    manifest = {
        "phase": "phase65c_fast_exact_universe_add_doge_relbtc_guardrail",
        "baseline_model": CURRENT_WINNER_KEY,
        "baseline_paper": str(args.baseline_paper),
        "doge_file": str(doge_file),
        "btc_file": str(btc_file),
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "rejected_file": str(rejected_path),
        "top_saved_models": top_models,
        "variant_count_total": int(len(variants)),
        "guardrail": {
            "metric": "delta_vs_phase63_since2025_cagr_pct",
            "min_allowed": float(args.min_since2025_delta),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    best = pass_df.iloc[0].to_dict() if not pass_df.empty else None

    log("")
    log("=== PHASE65C_FAST TOP RESULT ===")
    if best is None:
        log("No variants passed the 2025 guardrail.")
    else:
        log(f"model: {best.get('model')}")
        log(f"cagr_pct: {best.get('cagr_pct'):.2f}")
        log(f"max_drawdown_pct: {best.get('max_drawdown_pct'):.2f}")
        log(f"since2023_cagr_pct: {best.get('since2023_cagr_pct'):.2f}")
        log(f"since2025_cagr_pct: {best.get('since2025_cagr_pct'):.2f}")
        log(f"delta_vs_phase63_cagr_pct: {best.get('delta_vs_phase63_cagr_pct'):.2f}")
        log(f"delta_vs_phase63_since2023_cagr_pct: {best.get('delta_vs_phase63_since2023_cagr_pct'):.2f}")
        log(f"delta_vs_phase63_since2025_cagr_pct: {best.get('delta_vs_phase63_since2025_cagr_pct'):.2f}")
        log(f"delta_vs_phase63_max_drawdown_pct: {best.get('delta_vs_phase63_max_drawdown_pct'):.2f}")
        log(f"doge_days_pct: {best.get('doge_days_pct'):.2f}")
        log(f"signal_days_pct: {best.get('signal_days_pct'):.2f}")
        log(f"trigger_days: {int(best.get('trigger_days'))}")
        log("")

    log(f"[PHASE65C_FAST] pass_variants: {len(pass_df)}")
    log(f"[PHASE65C_FAST] rejected_variants: {len(fail_df)}")
    log(f"[PHASE65C_FAST] Saved summary -> {summary_path}")
    log(f"[PHASE65C_FAST] Saved compare -> {compare_path}")
    log(f"[PHASE65C_FAST] Saved rejected -> {rejected_path}")
    log(f"[PHASE65C_FAST] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()