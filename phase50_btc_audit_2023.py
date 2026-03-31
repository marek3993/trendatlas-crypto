from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
DATA_DIR = ROOT / "data" / "ohlcv"

PHASE49_SUMMARY_PATH = OUTPUTS / "phase49_final_compare" / "phase49_final_compare_summary.csv"
PHASE49_EQUITY_PATH = OUTPUTS / "phase49_final_compare" / "phase49_final_compare_equity_curves.csv"
BTC_FILE = DATA_DIR / "BTCUSDT_1d.csv"

OUT_DIR = OUTPUTS / "phase50_btc_audit_2023"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = pd.Timestamp("2023-01-01")
TRADING_DAYS_PER_YEAR = 365.25
MAIN_KEY = "phase49_bnb_hybrid_strict"


def load_phase49_equity() -> pd.DataFrame:
    df = pd.read_csv(PHASE49_EQUITY_PATH)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts").copy()
    return df


def load_btc() -> pd.DataFrame:
    df = pd.read_csv(BTC_FILE)

    rename_map = {
        "Date": "date",
        "Timestamp": "timestamp",
        "Datetime": "datetime",
        "Time": "time",
        "Close": "close",
        "Open time": "open_time",
        "Open Time": "open_time",
    }
    df = df.rename(columns=rename_map)

    date_col = next((c for c in ["date", "timestamp", "datetime", "time", "open_time"] if c in df.columns), None)
    if date_col is None:
        raise ValueError("BTC file nema datumovy stlpec")
    if "close" not in df.columns:
        raise ValueError("BTC file nema close stlpec")

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=[date_col, "close"]).copy()
    df = df[[date_col, "close"]].rename(columns={date_col: "ts"}).sort_values("ts")
    df["ts"] = pd.to_datetime(df["ts"]).dt.normalize()
    df = df.drop_duplicates(subset=["ts"]).reset_index(drop=True)
    return df


def compute_metrics_from_index(ts: pd.Series, idx: pd.Series) -> dict:
    df = pd.DataFrame({"ts": pd.to_datetime(ts), "idx": pd.to_numeric(idx, errors="coerce")})
    df = df.dropna().sort_values("ts").copy()
    if len(df) < 2:
        return {
            "total_return_pct": np.nan,
            "cagr_pct": np.nan,
            "max_drawdown_pct": np.nan,
            "worst_day_pct": np.nan,
            "worst_30d_pct": np.nan,
            "days": 0,
        }

    df["ret"] = df["idx"].pct_change().fillna(0.0)

    total_return = float(df["idx"].iloc[-1] / df["idx"].iloc[0] - 1.0)
    span_days = max((df["ts"].iloc[-1] - df["ts"].iloc[0]).days, 1)
    years = span_days / TRADING_DAYS_PER_YEAR
    cagr = float((df["idx"].iloc[-1] / df["idx"].iloc[0]) ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = df["idx"] / df["idx"].cummax() - 1.0
    max_dd = float(dd.min())

    worst_day = float(df["ret"].min())

    if len(df) >= 30:
        worst_30d = float(((1.0 + df["ret"]).rolling(30).apply(np.prod, raw=True) - 1.0).min())
    else:
        worst_30d = np.nan

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "worst_day_pct": round(worst_day * 100.0, 2),
        "worst_30d_pct": round(worst_30d * 100.0, 2) if pd.notna(worst_30d) else np.nan,
        "days": int(len(df)),
    }


def rolling_return(series: pd.Series, window: int) -> pd.Series:
    return (1.0 + series).rolling(window).apply(np.prod, raw=True) - 1.0


def main() -> None:
    if not PHASE49_EQUITY_PATH.exists():
        raise FileNotFoundError(f"Missing file: {PHASE49_EQUITY_PATH}")
    if not BTC_FILE.exists():
        raise FileNotFoundError(f"Missing file: {BTC_FILE}")

    eq = load_phase49_equity()
    btc = load_btc()

    if MAIN_KEY not in eq.columns:
        raise ValueError(f"Missing model column in phase49 equity: {MAIN_KEY}")

    df = eq[["ts", MAIN_KEY]].copy()
    df["ts"] = pd.to_datetime(df["ts"]).dt.normalize()
    df = df.merge(btc, on="ts", how="left")
    df["close"] = df["close"].ffill()
    df = df.loc[df["ts"] >= START_DATE].copy()

    if df.empty:
        raise ValueError(f"No data from {START_DATE.date()}")

    df["strategy_idx"] = pd.to_numeric(df[MAIN_KEY], errors="coerce")
    df["btc_idx"] = df["close"] / df["close"].iloc[0]

    strategy_metrics = compute_metrics_from_index(df["ts"], df["strategy_idx"])
    btc_metrics = compute_metrics_from_index(df["ts"], df["btc_idx"])

    metrics_df = pd.DataFrame(
        [
            {"asset": "Main strategy", **strategy_metrics},
            {"asset": "BTC Buy & Hold", **btc_metrics},
        ]
    )
    metrics_path = OUT_DIR / "phase50_btc_audit_2023_summary.csv"
    metrics_df.to_csv(metrics_path, index=False)

    out = df[["ts", "strategy_idx", "btc_idx"]].copy()
    out["strategy_ret"] = out["strategy_idx"].pct_change().fillna(0.0)
    out["btc_ret"] = out["btc_idx"].pct_change().fillna(0.0)

    out["strategy_above_btc"] = out["strategy_idx"] > out["btc_idx"]
    out["rolling_90d_strategy"] = rolling_return(out["strategy_ret"], 90) * 100.0
    out["rolling_90d_btc"] = rolling_return(out["btc_ret"], 90) * 100.0
    out["rolling_90d_diff"] = out["rolling_90d_strategy"] - out["rolling_90d_btc"]

    out["rolling_180d_strategy"] = rolling_return(out["strategy_ret"], 180) * 100.0
    out["rolling_180d_btc"] = rolling_return(out["btc_ret"], 180) * 100.0
    out["rolling_180d_diff"] = out["rolling_180d_strategy"] - out["rolling_180d_btc"]

    detail_path = OUT_DIR / "phase50_btc_audit_2023_detail.csv"
    out.to_csv(detail_path, index=False)

    monthly = out.copy()
    monthly["month"] = pd.to_datetime(monthly["ts"]).dt.strftime("%Y-%m")
    monthly_cmp = monthly.groupby("month").agg(
        strategy_month_end=("strategy_idx", "last"),
        btc_month_end=("btc_idx", "last"),
    ).reset_index()

    monthly_cmp["strategy_month_ret_pct"] = pd.Series(monthly_cmp["strategy_month_end"]).pct_change().fillna(0.0) * 100.0
    monthly_cmp["btc_month_ret_pct"] = pd.Series(monthly_cmp["btc_month_end"]).pct_change().fillna(0.0) * 100.0
    monthly_cmp["diff_pct"] = monthly_cmp["strategy_month_ret_pct"] - monthly_cmp["btc_month_ret_pct"]

    monthly_path = OUT_DIR / "phase50_btc_audit_2023_monthly.csv"
    monthly_cmp.to_csv(monthly_path, index=False)

    above_pct = float(out["strategy_above_btc"].mean() * 100.0)
    rolling90_win_pct = float((out["rolling_90d_diff"] > 0).dropna().mean() * 100.0) if out["rolling_90d_diff"].notna().any() else np.nan
    rolling180_win_pct = float((out["rolling_180d_diff"] > 0).dropna().mean() * 100.0) if out["rolling_180d_diff"].notna().any() else np.nan

    quick = pd.DataFrame(
        [
            {
                "start_date": str(START_DATE.date()),
                "strategy_above_btc_pct_of_days": round(above_pct, 2),
                "strategy_beats_btc_rolling_90d_pct": round(rolling90_win_pct, 2) if pd.notna(rolling90_win_pct) else np.nan,
                "strategy_beats_btc_rolling_180d_pct": round(rolling180_win_pct, 2) if pd.notna(rolling180_win_pct) else np.nan,
                "strategy_total_return_pct": strategy_metrics["total_return_pct"],
                "btc_total_return_pct": btc_metrics["total_return_pct"],
                "strategy_cagr_pct": strategy_metrics["cagr_pct"],
                "btc_cagr_pct": btc_metrics["cagr_pct"],
                "strategy_max_dd_pct": strategy_metrics["max_drawdown_pct"],
                "btc_max_dd_pct": btc_metrics["max_drawdown_pct"],
            }
        ]
    )
    quick_path = OUT_DIR / "phase50_btc_audit_2023_quick_read.csv"
    quick.to_csv(quick_path, index=False)

    print("\n=== PHASE50 BTC AUDIT FROM 2023-01-01 ===\n")
    print(metrics_df.to_string(index=False))
    print("\n--- QUICK READ ---\n")
    print(quick.to_string(index=False))
    print(f"\nSaved summary: {metrics_path}")
    print(f"Saved detail: {detail_path}")
    print(f"Saved monthly: {monthly_path}")
    print(f"Saved quick read: {quick_path}")


if __name__ == "__main__":
    main()