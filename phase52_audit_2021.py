from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
DATA_DIR = ROOT / "data" / "ohlcv"

PHASE46_EQUITY_PATH = OUTPUTS / "phase46_final_compare_pruned_equity_curves.csv"
PHASE49_EQUITY_PATH = OUTPUTS / "phase49_final_compare" / "phase49_final_compare_equity_curves.csv"
BTC_FILE = DATA_DIR / "BTCUSDT_1d.csv"

OUT_DIR = OUTPUTS / "phase52_audit_2021"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = pd.Timestamp("2021-01-01")
TRADING_DAYS_PER_YEAR = 365.25
MAIN_KEY = "phase49_bnb_hybrid_strict"


def load_phase46_equity() -> pd.DataFrame:
    df = pd.read_csv(PHASE46_EQUITY_PATH)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    return df.dropna(subset=["ts"]).sort_values("ts")


def load_phase49_equity() -> pd.DataFrame:
    df = pd.read_csv(PHASE49_EQUITY_PATH)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    return df.dropna(subset=["ts"]).sort_values("ts")


def load_btc() -> pd.DataFrame:
    df = pd.read_csv(BTC_FILE)
    df = df.rename(
        columns={
            "Date": "date",
            "Timestamp": "timestamp",
            "Datetime": "datetime",
            "Time": "time",
            "Close": "close",
            "Open time": "open_time",
            "Open Time": "open_time",
        }
    )

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
    return df.drop_duplicates(subset=["ts"]).reset_index(drop=True)


def compute_metrics(ts: pd.Series, idx: pd.Series) -> dict:
    df = pd.DataFrame({"ts": pd.to_datetime(ts), "idx": pd.to_numeric(idx, errors="coerce")})
    df = df.dropna().sort_values("ts").copy()

    if len(df) < 2:
        return {
            "total_return_pct": np.nan,
            "cagr_pct": np.nan,
            "max_drawdown_pct": np.nan,
            "worst_day_pct": np.nan,
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

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "worst_day_pct": round(worst_day * 100.0, 2),
        "days": int(len(df)),
    }


def rolling_return(series: pd.Series, window: int) -> pd.Series:
    return (1.0 + series).rolling(window).apply(np.prod, raw=True) - 1.0


def main() -> None:
    if not PHASE46_EQUITY_PATH.exists():
        raise FileNotFoundError(f"Missing file: {PHASE46_EQUITY_PATH}")
    if not PHASE49_EQUITY_PATH.exists():
        raise FileNotFoundError(f"Missing file: {PHASE49_EQUITY_PATH}")
    if not BTC_FILE.exists():
        raise FileNotFoundError(f"Missing file: {BTC_FILE}")

    eq46 = load_phase46_equity()
    eq49 = load_phase49_equity()
    btc = load_btc()

    merged = eq46[["ts", "old_baseline", "phase42_full12"]].copy()
    merged["ts"] = pd.to_datetime(merged["ts"]).dt.normalize()

    main = eq49[["ts", MAIN_KEY]].copy()
    main["ts"] = pd.to_datetime(main["ts"]).dt.normalize()

    merged = merged.merge(main, on="ts", how="inner")
    merged = merged.merge(btc, on="ts", how="left")
    merged["close"] = merged["close"].ffill()

    merged = merged.loc[merged["ts"] >= START_DATE].copy()
    if merged.empty:
        raise ValueError("Po 2021-01-01 nie su ziadne data")

    merged["btc_idx"] = merged["close"] / merged["close"].iloc[0]

    rows = []
    for label, col in [
        ("Starsia verzia", "old_baseline"),
        ("Predosly lider", "phase42_full12"),
        ("Hlavna strategia", MAIN_KEY),
        ("BTC Buy & Hold", "btc_idx"),
    ]:
        rows.append({"label": label, **compute_metrics(merged["ts"], merged[col])})

    summary = pd.DataFrame(rows).sort_values(["cagr_pct", "total_return_pct"], ascending=[False, False])
    summary_path = OUT_DIR / "phase52_audit_2021_summary.csv"
    summary.to_csv(summary_path, index=False)

    detail = merged[["ts", "old_baseline", "phase42_full12", MAIN_KEY, "btc_idx"]].copy()
    for col in ["old_baseline", "phase42_full12", MAIN_KEY, "btc_idx"]:
        detail[f"{col}_ret"] = detail[col].pct_change().fillna(0.0)
        detail[f"{col}_rolling_90d"] = rolling_return(detail[f"{col}_ret"], 90) * 100.0
        detail[f"{col}_rolling_180d"] = rolling_return(detail[f"{col}_ret"], 180) * 100.0

    detail["main_above_old"] = detail[MAIN_KEY] > detail["old_baseline"]
    detail["main_above_prev"] = detail[MAIN_KEY] > detail["phase42_full12"]
    detail_path = OUT_DIR / "phase52_audit_2021_detail.csv"
    detail.to_csv(detail_path, index=False)

    quick = pd.DataFrame(
        [
            {
                "start_date": str(START_DATE.date()),
                "main_above_old_pct_of_days": round(float(detail["main_above_old"].mean() * 100.0), 2),
                "main_above_prev_pct_of_days": round(float(detail["main_above_prev"].mean() * 100.0), 2),
                "main_vs_old_rolling_90d_win_pct": round(float((detail[f"{MAIN_KEY}_rolling_90d"] > detail["old_baseline_rolling_90d"]).dropna().mean() * 100.0), 2),
                "main_vs_old_rolling_180d_win_pct": round(float((detail[f"{MAIN_KEY}_rolling_180d"] > detail["old_baseline_rolling_180d"]).dropna().mean() * 100.0), 2),
            }
        ]
    )
    quick_path = OUT_DIR / "phase52_audit_2021_quick_read.csv"
    quick.to_csv(quick_path, index=False)

    print("\n=== PHASE52 AUDIT FROM 2021-01-01 ===\n")
    print(summary.to_string(index=False))
    print("\n--- QUICK READ ---\n")
    print(quick.to_string(index=False))
    print(f"\nSaved summary: {summary_path}")
    print(f"Saved detail: {detail_path}")
    print(f"Saved quick read: {quick_path}")


if __name__ == "__main__":
    main()