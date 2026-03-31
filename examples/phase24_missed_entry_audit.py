from __future__ import annotations

import json
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

ALWAYS_DAILY_PATH = OUTPUTS_DIR / "phase18_always_daily.csv"

OUT_DETAIL_CSV = OUTPUTS_DIR / "phase24_missed_entry_detail.csv"
OUT_WINDOWS_CSV = OUTPUTS_DIR / "phase24_missed_entry_windows.csv"
OUT_SUMMARY_JSON = OUTPUTS_DIR / "phase24_missed_entry_summary.json"


def find_date_col(df: pd.DataFrame) -> str:
    candidates = [
        "date", "Date", "datetime", "Datetime", "timestamp", "Timestamp",
        "time", "Time", "open_time", "Open time", "ts",
    ]
    for col in candidates:
        if col in df.columns:
            return col

    unnamed = [c for c in df.columns if str(c).lower().startswith("unnamed")]
    if unnamed:
        return unnamed[0]

    first_col = df.columns[0]
    sample = pd.to_datetime(df[first_col], errors="coerce")
    if sample.notna().sum() >= max(3, int(len(df) * 0.5)):
        return first_col

    raise ValueError(f"No datetime column found. Columns: {list(df.columns)}")


def clean_sel(s: pd.Series) -> pd.Series:
    out = s.astype(str).str.strip()
    out = out.replace(
        {
            "": "CASH",
            "nan": "CASH",
            "NaN": "CASH",
            "None": "CASH",
            "none": "CASH",
            "NULL": "CASH",
            "null": "CASH",
        }
    )
    return out.fillna("CASH")


def load_stream(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df = pd.read_csv(path)
    ts_col = find_date_col(df)

    required = [
        "daily_selected",
        "selected",
        "gross_exposure",
        "strategy_ret",
        "selected_ret_next",
        "turnover",
        "cost",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    out = df.copy()
    out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")
    out = out.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)
    out = out.rename(columns={ts_col: "ts"})
    out["date"] = out["ts"].dt.normalize()

    out["daily_selected"] = clean_sel(out["daily_selected"])
    out["selected"] = clean_sel(out["selected"])

    num_cols = ["gross_exposure", "strategy_ret", "selected_ret_next", "turnover", "cost"]
    for c in num_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)

    out["candidate_active"] = out["daily_selected"] != "CASH"
    out["actually_in_trade"] = (out["selected"] != "CASH") & (out["gross_exposure"] > 0)
    out["missed_entry_bar"] = out["candidate_active"] & (~out["actually_in_trade"])

    # len keď máme daily_selected coin a reálne sme ešte nenaskočili
    out["missed_bar_coin_ret"] = np.where(out["missed_entry_bar"], out["selected_ret_next"], 0.0)

    # zmysluplné missed bars: coin šiel hore a my sme neboli v pozícii
    out["missed_positive_bar"] = out["missed_entry_bar"] & (out["selected_ret_next"] > 0)

    return out


def build_windows(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["grp"] = (work["missed_entry_bar"] != work["missed_entry_bar"].shift(1)).cumsum()

    rows: List[dict] = []
    for _, g in work.groupby("grp"):
        if not bool(g["missed_entry_bar"].iloc[0]):
            continue

        start_ts = g["ts"].iloc[0]
        end_ts = g["ts"].iloc[-1]
        coin = g["daily_selected"].mode().iloc[0] if len(g["daily_selected"].mode()) else g["daily_selected"].iloc[0]

        bars = int(len(g))
        days = int((g["date"].iloc[-1] - g["date"].iloc[0]).days) + 1

        gross_missed_sum = float(g["missed_bar_coin_ret"].sum())
        gross_missed_compound = float((1.0 + g["missed_bar_coin_ret"]).prod() - 1.0)

        pos_bars = int((g["selected_ret_next"] > 0).sum())
        neg_bars = int((g["selected_ret_next"] < 0).sum())
        flat_bars = int((g["selected_ret_next"] == 0).sum())

        rows.append(
            {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "coin": coin,
                "bars": bars,
                "days": days,
                "avg_exposure_during_window": float(g["gross_exposure"].mean()),
                "sum_selected_ret_next": gross_missed_sum,
                "compound_selected_ret_next": gross_missed_compound,
                "positive_bars": pos_bars,
                "negative_bars": neg_bars,
                "flat_bars": flat_bars,
                "turnover_sum": float(g["turnover"].sum()),
                "cost_sum": float(g["cost"].sum()),
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["compound_selected_ret_next", "sum_selected_ret_next"], ascending=[False, False]).reset_index(drop=True)
    return out


def main() -> None:
    df = load_stream(ALWAYS_DAILY_PATH)

    detail_cols = [
        "ts",
        "date",
        "daily_selected",
        "selected",
        "gross_exposure",
        "strategy_ret",
        "selected_ret_next",
        "turnover",
        "cost",
        "candidate_active",
        "actually_in_trade",
        "missed_entry_bar",
        "missed_positive_bar",
        "missed_bar_coin_ret",
    ]
    detail = df[detail_cols].copy()
    detail.to_csv(OUT_DETAIL_CSV, index=False)

    windows = build_windows(df)
    windows.to_csv(OUT_WINDOWS_CSV, index=False)

    summary = {
        "total_bars": int(len(df)),
        "missed_entry_bars": int(df["missed_entry_bar"].sum()),
        "missed_entry_bar_pct": float(df["missed_entry_bar"].mean() * 100.0),
        "missed_positive_bars": int(df["missed_positive_bar"].sum()),
        "missed_positive_bar_pct": float(df["missed_positive_bar"].mean() * 100.0),
        "sum_selected_ret_next_on_missed_bars": float(df.loc[df["missed_entry_bar"], "selected_ret_next"].sum()),
        "compound_selected_ret_next_on_missed_bars": float((1.0 + df.loc[df["missed_entry_bar"], "selected_ret_next"]).prod() - 1.0),
        "top_20_windows": windows.head(20).to_dict(orient="records"),
    }

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n=== PHASE 24 MISSED ENTRY AUDIT ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "top_20_windows"}, indent=2))
    print("\n=== TOP 20 MISSED WINDOWS ===")
    if windows.empty:
        print("No missed-entry windows found.")
    else:
        print(windows.head(20).to_string(index=False))

    print(f"\nSaved detail CSV:   {OUT_DETAIL_CSV}")
    print(f"Saved windows CSV:  {OUT_WINDOWS_CSV}")
    print(f"Saved summary JSON: {OUT_SUMMARY_JSON}")


if __name__ == "__main__":
    main()