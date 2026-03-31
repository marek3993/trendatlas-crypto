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

PHASE64D_DIR = OUTPUTS / "phase64d_combo_assets"


@dataclass
class ComboConfig:
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


def load_baseline_paper(path: Path, cfg: ComboConfig) -> pd.DataFrame:
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
    asset = asset.upper().strip()
    if asset == "HYPERLIQUID":
        return "HYPE"
    return asset


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
        "start_date": daily.index.min().date().isoformat() if len(daily) else "",
        "end_date": daily.index.max().date().isoformat() if len(daily) else "",
        "history_days": int((daily.index.max() - daily.index.min()).days + 1) if len(daily) else 0,
        "non_na_close_ratio": float(daily["candidate_close"].notna().mean()) * 100.0 if len(daily) else 0.0,
        "max_gap_days": 0,
    }

    if len(daily) >= 2:
        gaps = pd.Series(daily.index).diff().dt.days.dropna()
        quality["max_gap_days"] = int(gaps.max()) if not gaps.empty else 0

    return daily, quality


def align_candidate_to_baseline(
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    asset: str,
) -> pd.DataFrame:
    x = baseline.copy()
    c = candidate.copy().reindex(x.index)
    c["candidate_close"] = c["candidate_close"].ffill()
    x[f"{asset}_close"] = c["candidate_close"]
    x[f"{asset}_return"] = x[f"{asset}_close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return x


def apply_one_asset_signal(df: pd.DataFrame, cfg: ComboConfig, asset: str) -> pd.DataFrame:
    x = df.copy()

    close_col = f"{asset}_close"
    ret_col = f"{asset}_return"

    x[f"{asset}_fast_ma"] = x[close_col].rolling(cfg.candidate_fast_ma, min_periods=cfg.candidate_fast_ma).mean()
    x[f"{asset}_slow_ma"] = x[close_col].rolling(cfg.candidate_slow_ma, min_periods=cfg.candidate_slow_ma).mean()
    x[f"{asset}_risk_ma"] = x[close_col].rolling(cfg.candidate_risk_ma, min_periods=cfg.candidate_risk_ma).mean()
    x[f"{asset}_ret_lb"] = x[close_col].pct_change(cfg.candidate_ret_lb)
    x[f"{asset}_vol"] = x[ret_col].rolling(cfg.candidate_vol_lb, min_periods=cfg.candidate_vol_lb).std(ddof=0)

    x[f"{asset}_trend_ok"] = (
        (x[close_col] > x[f"{asset}_fast_ma"])
        & (x[f"{asset}_fast_ma"] > x[f"{asset}_slow_ma"])
        & (x[f"{asset}_ret_lb"] >= cfg.candidate_ret_min)
    )

    x[f"{asset}_risk_off"] = (
        (x[close_col] < (x[f"{asset}_risk_ma"] * (1.0 + cfg.candidate_risk_buffer)))
        | (x[f"{asset}_vol"] > cfg.candidate_vol_cap)
    )

    x[f"{asset}_signal_raw"] = (
        x["executed_regime"].eq("BASE")
        & x["baseline_is_weak"].fillna(False)
        & x[f"{asset}_trend_ok"].fillna(False)
        & (~x[f"{asset}_risk_off"].fillna(True))
        & x[close_col].notna()
        & (~x["executed_position"].eq(asset))
    )

    if cfg.cooldown_days > 0:
        raw = x[f"{asset}_signal_raw"].fillna(False).astype(bool).values
        locked = np.zeros(len(raw), dtype=bool)
        hold = 0
        for i, flag in enumerate(raw):
            if flag:
                hold = cfg.cooldown_days
            elif hold > 0:
                hold -= 1
            locked[i] = flag or hold > 0
        x[f"{asset}_signal"] = locked
    else:
        x[f"{asset}_signal"] = x[f"{asset}_signal_raw"].fillna(False)

    return x


def simulate_combo(
    baseline: pd.DataFrame,
    asset_map: dict[str, pd.DataFrame],
    cfg: ComboConfig,
) -> pd.DataFrame:
    x = baseline.copy()

    for asset, candidate_df in asset_map.items():
        x = align_candidate_to_baseline(x, candidate_df, asset)
        x = apply_one_asset_signal(x, cfg, asset)

    score_cols = []
    signal_cols = []
    ret_cols = []
    for asset in asset_map.keys():
        score_col = f"{asset}_score"
        signal_col = f"{asset}_signal"
        ret_lb_col = f"{asset}_ret_lb"
        close_col = f"{asset}_close"
        ret_col = f"{asset}_return"

        x[score_col] = np.where(
            x[signal_col].fillna(False),
            pd.to_numeric(x[ret_lb_col], errors="coerce").fillna(-999.0),
            -999.0,
        )
        score_cols.append(score_col)
        signal_cols.append(signal_col)
        ret_cols.append(ret_col)

    score_df = x[score_cols].copy()
    best_asset_series = score_df.idxmax(axis=1)
    best_score = score_df.max(axis=1)

    asset_lookup = {f"{asset}_score": asset for asset in asset_map.keys()}
    x["combo_signal_asset"] = best_asset_series.map(asset_lookup)
    x["combo_signal_asset"] = np.where(best_score > -999.0, x["combo_signal_asset"], "")

    x["combo_execute_asset"] = pd.Series(x["combo_signal_asset"], index=x.index).shift(1).fillna("")
    x["combo_execute"] = x["combo_execute_asset"].astype(str).str.len() > 0

    x["combo_candidate_return"] = 0.0
    for asset in asset_map.keys():
        x["combo_candidate_return"] = np.where(
            x["combo_execute_asset"] == asset,
            x[f"{asset}_return"].fillna(0.0),
            x["combo_candidate_return"],
        )

    out = x.copy()
    out["executed_regime"] = np.where(out["combo_execute"], "CANDIDATE", out["executed_regime"])
    out["executed_position"] = np.where(out["combo_execute"], out["combo_execute_asset"], out["executed_position"])
    out["strategy_return"] = np.where(out["combo_execute"], out["combo_candidate_return"], out["strategy_return"])
    out["equity"] = (1.0 + pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0)).cumprod()

    return out


def build_row(df: pd.DataFrame, model_name: str) -> dict:
    row = calc_metrics(df, model_name)
    row.update(window_metrics(df, "2021-01-01"))
    row.update(window_metrics(df, "2023-01-01"))
    row.update(window_metrics(df, "2025-01-01"))
    return row


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


def parse_combo_string(combo_string: str) -> list[list[str]]:
    combos = []
    for chunk in combo_string.split("|"):
        assets = [normalize_asset_name(x) for x in re.split(r"[,\s;]+", chunk.strip()) if x.strip()]
        deduped = []
        for asset in assets:
            if asset not in deduped:
                deduped.append(asset)
        if deduped:
            combos.append(deduped)
    return combos


def combo_name(assets: list[str]) -> str:
    return "add_" + "_".join(assets)


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE64D exact combo rerun for multiple asset sets")
    parser.add_argument(
        "--combos",
        type=str,
        default="DOGE|DOGE,XRP|DOGE,SUI|DOGE,HYPE|DOGE,XRP,SUI|DOGE,XRP,HYPE|DOGE,SUI,HYPE",
    )
    parser.add_argument("--baseline-paper", type=str, default=str(CURRENT_WINNER_PAPER))
    args = parser.parse_args()

    cfg = ComboConfig()
    ensure_dir(PHASE64D_DIR)

    combos = parse_combo_string(args.combos)
    if not combos:
        raise ValueError("Žiadne combos na test.")

    log("[PHASE64D] Start")
    log(f"[PHASE64D] Combos: {combos}")
    log(f"[PHASE64D] Baseline paper: {args.baseline_paper}")

    baseline = load_baseline_paper(Path(args.baseline_paper), cfg)
    baseline_row = build_row(baseline, CURRENT_WINNER_KEY)
    baseline_row["combo_assets"] = ""
    baseline_row["combo_size"] = 0
    baseline_row["candidate_days_pct"] = 0.0
    baseline_row["signal_days_pct"] = 0.0
    baseline_row["trigger_days"] = 0

    rows = [baseline_row]
    diagnostics = []
    saved_papers = {CURRENT_WINNER_KEY: baseline.copy()}

    asset_file_cache: dict[str, Path] = {}
    asset_daily_cache: dict[str, pd.DataFrame] = {}

    for assets in combos:
        combo_key = combo_name(assets)
        try:
            asset_map: dict[str, pd.DataFrame] = {}
            combo_quality = []

            for asset in assets:
                if asset not in asset_file_cache:
                    asset_file_cache[asset] = discover_asset_file(asset)
                if asset not in asset_daily_cache:
                    daily, quality = load_candidate_daily_prices(asset_file_cache[asset])
                    asset_daily_cache[asset] = daily
                    diagnostics.append({
                        "combo": combo_key,
                        "asset": asset,
                        "status": "loaded",
                        "asset_file": str(asset_file_cache[asset]),
                        **quality,
                    })
                asset_map[asset] = asset_daily_cache[asset]
                combo_quality.append(asset_file_cache[asset].name)

            sim = simulate_combo(baseline, asset_map, cfg)
            row = build_row(sim, combo_key)
            row = add_deltas(row, baseline_row)
            row["combo_assets"] = ",".join(assets)
            row["combo_size"] = len(assets)
            row["candidate_days_pct"] = float(sim["combo_execute"].fillna(False).mean() * 100.0)
            row["signal_days_pct"] = float(sim["combo_signal_asset"].astype(str).str.len().gt(0).mean() * 100.0)
            row["trigger_days"] = int(sim["combo_signal_asset"].astype(str).str.len().gt(0).sum())
            rows.append(row)
            saved_papers[combo_key] = sim

            diagnostics.append({
                "combo": combo_key,
                "asset": ",".join(assets),
                "status": "processed_combo",
                "asset_file": " | ".join(combo_quality),
            })
            log(f"[PHASE64D] done {combo_key}")
        except Exception as e:
            diagnostics.append({
                "combo": combo_key,
                "asset": ",".join(assets),
                "status": "failed_combo",
                "reason": str(e),
            })
            log(f"[WARN] {combo_key} failed: {e}")

    summary = pd.DataFrame(rows)
    diagnostics_df = pd.DataFrame(diagnostics)

    if len(summary) > 1:
        base_df = summary[summary["model"] == CURRENT_WINNER_KEY].copy()
        cand_df = summary[summary["model"] != CURRENT_WINNER_KEY].copy()
        cand_df = cand_df.sort_values(
            by=[
                "delta_vs_phase63_since2023_cagr_pct",
                "delta_vs_phase63_cagr_pct",
                "delta_vs_phase63_since2025_cagr_pct",
                "delta_vs_phase63_max_drawdown_pct",
            ],
            ascending=[False, False, False, False],
            na_position="last",
        ).reset_index(drop=True)
        summary = pd.concat([base_df, cand_df], ignore_index=True)

    summary_path = PHASE64D_DIR / "phase64d_combo_assets_summary.csv"
    compare_path = PHASE64D_DIR / "phase64d_combo_assets_compare.csv"
    diagnostics_path = PHASE64D_DIR / "phase64d_combo_assets_diagnostics.csv"
    manifest_path = PHASE64D_DIR / "phase64d_combo_assets_manifest.json"

    summary.to_csv(summary_path, index=False)
    summary.to_csv(compare_path, index=False)
    diagnostics_df.to_csv(diagnostics_path, index=False)

    for model, paper in saved_papers.items():
        out_path = PHASE64D_DIR / f"{model}_paper.csv"
        paper.reset_index().rename(columns={paper.index.name or "index": "date"}).to_csv(out_path, index=False)

    manifest = {
        "phase": "phase64d_combo_assets",
        "baseline_model": CURRENT_WINNER_KEY,
        "baseline_paper": str(args.baseline_paper),
        "combos": combos,
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "diagnostics_file": str(diagnostics_path),
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
        },
        "selection_rule": "Ak je aktívnych viac kandidátov, berie sa ten s najvyšším candidate_ret_lb score.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    best = summary[summary["model"] != CURRENT_WINNER_KEY].head(1)
    log("")
    log("=== PHASE64D TOP RESULT ===")
    if best.empty:
        log("No valid combos processed.")
    else:
        row = best.iloc[0]
        log(f"model: {row['model']}")
        log(f"combo_assets: {row['combo_assets']}")
        log(f"cagr_pct: {row['cagr_pct']:.2f}")
        log(f"max_drawdown_pct: {row['max_drawdown_pct']:.2f}")
        log(f"since2023_cagr_pct: {row['since2023_cagr_pct']:.2f}")
        log(f"since2025_cagr_pct: {row['since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_cagr_pct: {row['delta_vs_phase63_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_since2023_cagr_pct: {row['delta_vs_phase63_since2023_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_since2025_cagr_pct: {row['delta_vs_phase63_since2025_cagr_pct']:.2f}")
        log(f"delta_vs_phase63_max_drawdown_pct: {row['delta_vs_phase63_max_drawdown_pct']:.2f}")
        log(f"candidate_days_pct: {row['candidate_days_pct']:.2f}")
        log(f"signal_days_pct: {row['signal_days_pct']:.2f}")
        log(f"trigger_days: {int(row['trigger_days'])}")

    log("")
    log(f"[PHASE64D] Saved summary -> {summary_path}")
    log(f"[PHASE64D] Saved compare -> {compare_path}")
    log(f"[PHASE64D] Saved diagnostics -> {diagnostics_path}")
    log(f"[PHASE64D] Saved manifest -> {manifest_path}")


if __name__ == "__main__":
    main()