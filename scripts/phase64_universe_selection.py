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

PHASE64_DIR = OUTPUTS / "phase64_universe_selection"

CURRENT_WINNER_KEY = "phase63_btcpref_f20_s100_r30_m12_rm150_rb-03_v30_045_wb30_wt+02_cd3"
CURRENT_WINNER_PAPER = (
    OUTPUTS
    / "phase63_btc_participation_overlay"
    / f"{CURRENT_WINNER_KEY}_paper.csv"
)

FORCE_INCLUDE_ASSETS = {"XRP", "SUI", "HYPE", "HYPERLIQUID"}

STABLES = {
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "EURC", "PYUSD",
}
BAD_NAME_PARTS = {
    "UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S",
}


@dataclass
class ScanConfig:
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
    min_history_days: int = 180
    min_non_na_close_ratio: float = 0.90
    max_gap_days: int = 45
    top_n_save: int = 20


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
    preferred = ["close", "Close", "adj_close", "price", "last"]
    for col in preferred:
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


def load_baseline_paper(path: Path, cfg: ScanConfig) -> pd.DataFrame:
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


def extract_asset_from_path(path: Path) -> str:
    parts = re.split(r"[^A-Z0-9]+", path.stem.upper())
    parts = [p for p in parts if p]
    candidates = []
    for part in parts:
        for quote in ["USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USD"]:
            if part.endswith(quote) and len(part) > len(quote):
                candidates.append(part[: -len(quote)])
    if candidates:
        return candidates[0]
    for part in parts:
        if part not in {"1D", "1H", "4H", "5M", "15M", "30M", "DAILY", "OHLCV", "DATA"} and len(part) >= 2:
            return part
    return ""


def normalize_asset_name(asset: str) -> str:
    asset = asset.upper().strip()
    if asset == "HYPERLIQUID":
        return "HYPE"
    return asset


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


def load_candidate_daily_prices(path: Path) -> tuple[pd.DataFrame, dict]:
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
    daily = x.groupby("day", as_index=True)["close"].last().to_frame("candidate_close").sort_index()

    quality = {
        "raw_rows": int(len(raw)),
        "daily_rows": int(len(daily)),
        "non_na_close_ratio": float(daily["candidate_close"].notna().mean()) if len(daily) else 0.0,
        "start_date": daily.index.min().date().isoformat() if len(daily) else "",
        "end_date": daily.index.max().date().isoformat() if len(daily) else "",
        "history_days": int((daily.index.max() - daily.index.min()).days + 1) if len(daily) else 0,
        "max_gap_days": 0,
        "median_gap_days": 0.0,
    }

    if len(daily) >= 2:
        gaps = pd.Series(daily.index).diff().dt.days.dropna()
        if not gaps.empty:
            quality["max_gap_days"] = int(gaps.max())
            quality["median_gap_days"] = float(gaps.median())

    return daily, quality


def candidate_quality_ok(q: dict, cfg: ScanConfig, asset: str) -> tuple[bool, str]:
    if q["daily_rows"] < cfg.min_history_days and asset not in FORCE_INCLUDE_ASSETS:
        return False, f"daily_rows<{cfg.min_history_days}"
    if q["non_na_close_ratio"] < cfg.min_non_na_close_ratio:
        return False, "too_many_missing_closes"
    if q["max_gap_days"] > cfg.max_gap_days and asset not in FORCE_INCLUDE_ASSETS:
        return False, f"max_gap_days>{cfg.max_gap_days}"
    return True, ""


def align_candidate_to_baseline(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
) -> pd.DataFrame:
    x = baseline.copy()
    c = candidate.copy().reindex(x.index)
    c["candidate_close"] = c["candidate_close"].ffill()
    x["candidate_close"] = c["candidate_close"]
    x["candidate_return"] = x["candidate_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return x


def build_candidate_signal(df: pd.DataFrame, cfg: ScanConfig, asset: str) -> pd.DataFrame:
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
        & (~x["executed_position"].eq(asset))
    )

    if cfg.cooldown_days > 0:
        raw = x["candidate_signal_raw"].fillna(False).astype(bool).values
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
        x["candidate_signal"] = x["candidate_signal_raw"].fillna(False)

    x["candidate_execute"] = x["candidate_signal"].shift(1).fillna(False)
    return x


def simulate_add_one(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    cfg: ScanConfig,
    asset: str,
) -> pd.DataFrame:
    merged = align_candidate_to_baseline(baseline, candidate)
    merged = build_candidate_signal(merged, cfg, asset)

    out = merged.copy()
    out["executed_regime"] = np.where(out["candidate_execute"], "CANDIDATE", out["executed_regime"])
    out["executed_position"] = np.where(out["candidate_execute"], asset, out["executed_position"])
    out["strategy_return"] = np.where(out["candidate_execute"], out["candidate_return"], out["strategy_return"])
    out["equity"] = (1.0 + pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)).cumprod()
    return out


def build_baseline_row(baseline: pd.DataFrame) -> dict:
    row = calc_metrics(baseline, CURRENT_WINNER_KEY)
    row.update(window_metrics(baseline, "2021-01-01"))
    row.update(window_metrics(baseline, "2023-01-01"))
    row.update(window_metrics(baseline, "2025-01-01"))
    row["candidate_asset"] = ""
    row["candidate_file"] = str(CURRENT_WINNER_PAPER)
    row["already_in_baseline"] = True
    row["selected_days_in_baseline_pct"] = np.nan
    row["trigger_days"] = 0
    row["signal_days_pct"] = 0.0
    row["candidate_days_pct"] = 0.0
    row["source"] = "current_phase63_winner"
    return row


def make_candidate_row(
    sim: pd.DataFrame,
    asset: str,
    path: Path,
    q: dict,
    baseline_row: dict,
    baseline_assets: set[str],
    baseline_selected_pct: float,
) -> dict:
    row = calc_metrics(sim, f"add_{asset}")
    row.update(window_metrics(sim, "2021-01-01"))
    row.update(window_metrics(sim, "2023-01-01"))
    row.update(window_metrics(sim, "2025-01-01"))

    row["candidate_asset"] = asset
    row["candidate_file"] = str(path)
    row["already_in_baseline"] = asset in baseline_assets
    row["selected_days_in_baseline_pct"] = baseline_selected_pct
    row["trigger_days"] = int(sim["candidate_signal_raw"].fillna(False).sum()) if "candidate_signal_raw" in sim.columns else 0
    row["signal_days_pct"] = float(sim["candidate_signal"].fillna(False).mean() * 100.0) if "candidate_signal" in sim.columns else 0.0
    row["candidate_days_pct"] = float(sim["candidate_execute"].fillna(False).mean() * 100.0) if "candidate_execute" in sim.columns else 0.0

    row["history_days"] = q["history_days"]
    row["daily_rows"] = q["daily_rows"]
    row["data_start"] = q["start_date"]
    row["data_end"] = q["end_date"]
    row["non_na_close_ratio"] = q["non_na_close_ratio"] * 100.0
    row["max_gap_days"] = q["max_gap_days"]
    row["median_gap_days"] = q["median_gap_days"]
    row["raw_rows"] = q["raw_rows"]

    row["delta_vs_phase63_cagr_pct"] = row["cagr_pct"] - baseline_row["cagr_pct"]
    row["delta_vs_phase63_max_drawdown_pct"] = row["max_drawdown_pct"] - baseline_row["max_drawdown_pct"]
    row["delta_vs_phase63_since2021_cagr_pct"] = row["since2021_cagr_pct"] - baseline_row["since2021_cagr_pct"]
    row["delta_vs_phase63_since2023_cagr_pct"] = row["since2023_cagr_pct"] - baseline_row["since2023_cagr_pct"]
    row["delta_vs_phase63_since2025_cagr_pct"] = row["since2025_cagr_pct"] - baseline_row["since2025_cagr_pct"]
    row["source"] = "phase64_add_one_prescan"
    return row


def discover_candidate_files() -> list[Path]:
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Missing data dir: {DATA_DIR}")
    files: list[Path] = []
    files.extend(DATA_DIR.rglob("*.csv"))
    files.extend(DATA_DIR.rglob("*.parquet"))
    files.extend(DATA_DIR.rglob("*.pq"))
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE64 universe selection broad scan")
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    parser.add_argument("--min-history-days", type=int, default=180)
    parser.add_argument("--top-n-save", type=int, default=20)
    args = parser.parse_args()

    cfg = ScanConfig(
        min_history_days=args.min_history_days,
        top_n_save=args.top_n_save,
    )

    ensure_dir(PHASE64_DIR)

    log("[PHASE64] Start")
    log(f"[PHASE64] Baseline paper: {args.baseline_paper}")

    baseline = load_baseline_paper(Path(args.baseline_paper), cfg)
    baseline_row = build_baseline_row(baseline)

    baseline_assets = {
        x for x in baseline["executed_position"].astype(str).str.upper().unique().tolist()
        if x not in {"", "NAN", "NA", "CASH", "BTC"}
    }
    baseline_selected_share = (
        baseline["executed_position"].astype(str).str.upper().value_counts(normalize=True) * 100.0
    ).to_dict()

    rows: list[dict] = [baseline_row]
    diagnostics: list[dict] = []
    saved_papers: dict[str, pd.DataFrame] = {CURRENT_WINNER_KEY: baseline.copy()}

    files = discover_candidate_files()
    log(f"[PHASE64] Candidate files found: {len(files)}")

    processed = 0
    skipped = 0
    failed = 0

    for path in files:
        asset = normalize_asset_name(extract_asset_from_path(path))

        if is_bad_asset_name(asset):
            diagnostics.append({
                "file": str(path),
                "asset": asset,
                "status": "skipped",
                "reason": "bad_asset_name_or_excluded",
            })
            skipped += 1
            continue

        try:
            cand_df, q = load_candidate_daily_prices(path)
            ok, reason = candidate_quality_ok(q, cfg, asset)
            if not ok:
                diagnostics.append({
                    "file": str(path),
                    "asset": asset,
                    "status": "skipped",
                    "reason": reason,
                    **q,
                })
                skipped += 1
                continue

            sim = simulate_add_one(baseline, cand_df, cfg, asset)
            row = make_candidate_row(
                sim=sim,
                asset=asset,
                path=path,
                q=q,
                baseline_row=baseline_row,
                baseline_assets=baseline_assets,
                baseline_selected_pct=float(baseline_selected_share.get(asset, 0.0)),
            )
            rows.append(row)
            saved_papers[f"add_{asset}"] = sim
            diagnostics.append({
                "file": str(path),
                "asset": asset,
                "status": "processed",
                "reason": "",
                **q,
            })
            processed += 1

            if processed % 25 == 0:
                log(f"[PHASE64] processed {processed}")
        except Exception as e:
            diagnostics.append({
                "file": str(path),
                "asset": asset,
                "status": "failed",
                "reason": str(e),
            })
            failed += 1
            log(f"[WARN] {path.name} failed: {e}")

    summary = pd.DataFrame(rows)
    diagnostics_df = pd.DataFrame(diagnostics)

    sort_cols = [
        "delta_vs_phase63_since2023_cagr_pct",
        "delta_vs_phase63_cagr_pct",
        "delta_vs_phase63_since2025_cagr_pct",
        "delta_vs_phase63_max_drawdown_pct",
    ]
    for col in sort_cols:
        if col not in summary.columns:
            summary[col] = np.nan

    baseline_df = summary[summary["model"] == CURRENT_WINNER_KEY].copy()
    candidates_df = summary[summary["model"] != CURRENT_WINNER_KEY].copy()

    candidates_df = candidates_df.sort_values(
        by=sort_cols,
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    final_summary = pd.concat([baseline_df, candidates_df], ignore_index=True)
    top_compare = pd.concat([baseline_df, candidates_df.head(30)], ignore_index=True)

    summary_path = PHASE64_DIR / "phase64_universe_selection_summary.csv"
    compare_path = PHASE64_DIR / "phase64_universe_selection_top_compare.csv"
    diagnostics_path = PHASE64_DIR / "phase64_universe_selection_diagnostics.csv"
    manifest_path = PHASE64_DIR / "phase64_manifest.json"

    final_summary.to_csv(summary_path, index=False)
    top_compare.to_csv(compare_path, index=False)
    diagnostics_df.to_csv(diagnostics_path, index=False)

    top_models = [CURRENT_WINNER_KEY] + [x for x in candidates_df["model"].head(cfg.top_n_save).tolist()]
    for model in top_models:
        paper = saved_papers.get(model)
        if paper is None:
            continue
        out_path = PHASE64_DIR / f"{model}_paper.csv"
        tmp = paper.copy().reset_index().rename(columns={paper.index.name or "index": "date"})
        tmp.to_csv(out_path, index=False)

    manifest = {
        "phase": "phase64_universe_selection",
        "mode": "broad_add_one_prescan",
        "baseline_model": CURRENT_WINNER_KEY,
        "baseline_paper": str(args.baseline_paper),
        "data_dir": str(DATA_DIR),
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "diagnostics_file": str(diagnostics_path),
        "processed_candidates": int(processed),
        "skipped_candidates": int(skipped),
        "failed_candidates": int(failed),
        "top_saved_models": top_models,
        "config": {
            "candidate_fast_ma": cfg.candidate_fast_ma,
            "candidate_slow_ma": cfg.candidate_slow_ma,
            "candidate_ret_lb": cfg.candidate_ret_lb,
            "candidate_ret_min": cfg.candidate_ret_min,
            "candidate_risk_ma": cfg.candidate_risk_ma,
            "candidate_risk_buffer": cfg.candidate_risk_buffer,
            "candidate_vol_lb": cfg.candidate_vol_lb,
            "candidate_vol_cap": cfg.candidate_vol_cap,
            "weak_base_lb": cfg.weak_base_lb,
            "weak_base_threshold": cfg.weak_base_threshold,
            "cooldown_days": cfg.cooldown_days,
            "min_history_days": cfg.min_history_days,
            "min_non_na_close_ratio": cfg.min_non_na_close_ratio,
            "max_gap_days": cfg.max_gap_days,
        },
        "notes": [
            "Toto je broad add-one prescan proti current Phase63 winnerovi.",
            "Ak sú inputy intraday, skript ich agreguje na daily last close.",
            "Výstup je shortlist filter pre ďalší presný phase.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    best = candidates_df.iloc[0].to_dict() if not candidates_df.empty else None

    log("")
    log("=== PHASE64 TOP RESULT ===")
    if best is None:
        log("No valid candidates passed filters.")
    else:
        log(f"model: {best.get('model')}")
        log(f"candidate_asset: {best.get('candidate_asset')}")
        log(f"cagr_pct: {best.get('cagr_pct'):.2f}")
        log(f"max_drawdown_pct: {best.get('max_drawdown_pct'):.2f}")
        log(f"since2023_cagr_pct: {best.get('since2023_cagr_pct'):.2f}")
        log(f"since2025_cagr_pct: {best.get('since2025_cagr_pct'):.2f}")
        log(f"delta_vs_phase63_cagr_pct: {best.get('delta_vs_phase63_cagr_pct'):.2f}")
        log(f"delta_vs_phase63_since2023_cagr_pct: {best.get('delta_vs_phase63_since2023_cagr_pct'):.2f}")
        log(f"delta_vs_phase63_max_drawdown_pct: {best.get('delta_vs_phase63_max_drawdown_pct'):.2f}")
        log("")

    log(f"[PHASE64] processed_candidates: {processed}")
    log(f"[PHASE64] skipped_candidates: {skipped}")
    log(f"[PHASE64] failed_candidates: {failed}")
    log(f"[PHASE64] Saved summary -> {summary_path}")
    log(f"[PHASE64] Saved compare -> {compare_path}")
    log(f"[PHASE64] Saved diagnostics -> {diagnostics_path}")
    log(f"[PHASE64] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()