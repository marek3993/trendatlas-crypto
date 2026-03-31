from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

ALWAYS_DAILY_PATH = OUTPUTS_DIR / "phase18_always_daily.csv"

OUT_DETAIL_CSV = OUTPUTS_DIR / "phase29_missed_leader_detail.csv"
OUT_WINDOWS_CSV = OUTPUTS_DIR / "phase29_missed_leader_windows.csv"
OUT_SUMMARY_JSON = OUTPUTS_DIR / "phase29_missed_leader_summary.json"


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
        "selected",
        "gross_exposure",
        "strategy_ret",
        "selected_ret_next",
        "best_available_next",
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

    out["selected"] = clean_sel(out["selected"])

    num_cols = [
        "gross_exposure",
        "strategy_ret",
        "selected_ret_next",
        "best_available_next",
        "turnover",
        "cost",
    ]
    for c in num_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)

    out["in_market"] = (out["selected"] != "CASH") & (out["gross_exposure"] > 0.0)

    # sme v trhu, ale držaný coin zaostáva za najlepším dostupným coinom
    out["leader_gap_ret"] = out["best_available_next"] - out["selected_ret_next"]
    out["missed_leader_bar"] = out["in_market"] & (out["leader_gap_ret"] > 0.0)

    # len fakt bolestivé bary
    out["pain_bar"] = out["in_market"] & (out["leader_gap_ret"] > 0.02)

    return out


def build_windows(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["grp"] = (work["missed_leader_bar"] != work["missed_leader_bar"].shift(1)).cumsum()

    rows: List[dict] = []
    for _, g in work.groupby("grp"):
        if not bool(g["missed_leader_bar"].iloc[0]):
            continue

        start_ts = g["ts"].iloc[0]
        end_ts = g["ts"].iloc[-1]
        selected_mode = g["selected"].mode().iloc[0] if len(g["selected"].mode()) else g["selected"].iloc[0]

        rows.append(
            {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "selected_mode": selected_mode,
                "bars": int(len(g)),
                "days": int((g["date"].iloc[-1] - g["date"].iloc[0]).days) + 1,
                "avg_exposure": float(g["gross_exposure"].mean()),
                "sum_selected_ret_next": float(g["selected_ret_next"].sum()),
                "sum_best_available_next": float(g["best_available_next"].sum()),
                "sum_leader_gap_ret": float(g["leader_gap_ret"].sum()),
                "compound_selected_ret_next": float((1.0 + g["selected_ret_next"]).prod() - 1.0),
                "compound_best_available_next": float((1.0 + g["best_available_next"]).prod() - 1.0),
                "compound_gap_approx": float(
                    ((1.0 + g["best_available_next"]).prod() - 1.0)
                    - ((1.0 + g["selected_ret_next"]).prod() - 1.0)
                ),
                "positive_gap_bars": int((g["leader_gap_ret"] > 0).sum()),
                "pain_bars_gt_2pct_gap": int((g["leader_gap_ret"] > 0.02).sum()),
                "turnover_sum": float(g["turnover"].sum()),
                "cost_sum": float(g["cost"].sum()),
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(
            ["compound_gap_approx", "sum_leader_gap_ret"],
            ascending=[False, False],
        ).reset_index(drop=True)

    return out


def main() -> None:
    df = load_stream(ALWAYS_DAILY_PATH)

    detail_cols = [
        "ts",
        "date",
        "selected",
        "gross_exposure",
        "strategy_ret",
        "selected_ret_next",
        "best_available_next",
        "leader_gap_ret",
        "in_market",
        "missed_leader_bar",
        "pain_bar",
        "turnover",
        "cost",
    ]
    detail = df[detail_cols].copy()
    detail.to_csv(OUT_DETAIL_CSV, index=False)

    windows = build_windows(df)
    windows.to_csv(OUT_WINDOWS_CSV, index=False)

    in_mkt = df["in_market"]
    missed = df["missed_leader_bar"]
    pain = df["pain_bar"]

    summary: Dict[str, object] = {
        "total_bars": int(len(df)),
        "in_market_bars": int(in_mkt.sum()),
        "in_market_bar_pct": float(in_mkt.mean() * 100.0),
        "missed_leader_bars": int(missed.sum()),
        "missed_leader_bar_pct": float(missed.mean() * 100.0),
        "missed_leader_bar_pct_of_in_market": float((missed.sum() / max(int(in_mkt.sum()), 1)) * 100.0),
        "pain_bars_gt_2pct_gap": int(pain.sum()),
        "pain_bar_pct_of_in_market": float((pain.sum() / max(int(in_mkt.sum()), 1)) * 100.0),
        "sum_selected_ret_next_in_market": float(df.loc[in_mkt, "selected_ret_next"].sum()),
        "sum_best_available_next_in_market": float(df.loc[in_mkt, "best_available_next"].sum()),
        "sum_leader_gap_ret_in_market": float(df.loc[in_mkt, "leader_gap_ret"].clip(lower=0.0).sum()),
        "compound_selected_ret_next_in_market": float((1.0 + df.loc[in_mkt, "selected_ret_next"]).prod() - 1.0),
        "compound_best_available_next_in_market": float((1.0 + df.loc[in_mkt, "best_available_next"]).prod() - 1.0),
        "top_20_windows": windows.head(20).to_dict(orient="records"),
    }

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n=== PHASE 29 MISSED LEADER AUDIT ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "top_20_windows"}, indent=2))
    print("\n=== TOP 20 MISSED LEADER WINDOWS ===")
    if windows.empty:
        print("No missed-leader windows found.")
    else:
        print(windows.head(20).to_string(index=False))

    print(f"\nSaved detail CSV:   {OUT_DETAIL_CSV}")
    print(f"Saved windows CSV:  {OUT_WINDOWS_CSV}")
    print(f"Saved summary JSON: {OUT_SUMMARY_JSON}")


if __name__ == "__main__":
    main()