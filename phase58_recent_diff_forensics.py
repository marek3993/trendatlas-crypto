from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"

PHASE46_EQUITY_PATH = OUTPUTS / "phase46_final_compare_pruned_equity_curves.csv"
PHASE49_PAPER_PATH = OUTPUTS / "phase49_final_compare" / "phase49_bnb_hybrid_strict_paper.csv"

OUT_DIR = OUTPUTS / "phase58_recent_diff_forensics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PHASE42_FILE_HINTS = [
    "phase42_full12",
    "full12",
    "phase42",
    "phase41_full12",
]

WINDOWS = {
    "since_2023": pd.Timestamp("2023-01-01"),
    "since_2025": pd.Timestamp("2025-01-01"),
}


def normalize_ts_col(df: pd.DataFrame) -> pd.DataFrame:
    ts_col = None
    for c in ["ts", "timestamp", "date", "datetime"]:
        if c in df.columns:
            ts_col = c
            break

    if ts_col is None:
        unnamed = [c for c in df.columns if str(c).lower().startswith("unnamed")]
        if unnamed:
            ts_col = unnamed[0]

    if ts_col is None:
        raise ValueError("Subor nema casovy stlpec")

    out = df.copy()
    out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")
    out = out.dropna(subset=[ts_col]).copy()
    out = out.rename(columns={ts_col: "ts"})
    out["ts"] = pd.to_datetime(out["ts"]).dt.normalize()
    return out.sort_values("ts")


def try_load_csv(path: Path) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(path)
        df = normalize_ts_col(df)
        return df
    except Exception:
        return None


def looks_like_daily_paper(df: pd.DataFrame) -> bool:
    cols = set(df.columns)
    return len({"selected", "gross_exposure", "strategy_ret"}.intersection(cols)) >= 2


def score_phase42_candidate(path: Path) -> int:
    name = path.name.lower()
    score = 0

    for hint in PHASE42_FILE_HINTS:
        if hint.lower() in name:
            score += 10

    if "paper" in name:
        score += 6
    if "daily" in name:
        score += 4
    if "summary" in name:
        score -= 6
    if "equity" in name:
        score -= 4
    if "compare" in name:
        score -= 2

    return score


def find_phase42_daily_paper() -> Optional[Path]:
    candidates = []
    for path in OUTPUTS.rglob("*.csv"):
        score = score_phase42_candidate(path)
        if score <= 0:
            continue
        df = try_load_csv(path)
        if df is None:
            continue
        if looks_like_daily_paper(df):
            candidates.append((score, path))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x[0], str(x[1])))
    return candidates[0][1]


def prepare_daily_paper(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = normalize_ts_col(df)

    if "selected" not in df.columns:
        df["selected"] = "UNKNOWN"
    df["selected"] = df["selected"].fillna("UNKNOWN").astype(str)

    for col in ["strategy_ret", "gross_exposure", "turnover", "equity"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "strategy_ret" not in df.columns:
        if "equity" in df.columns:
            df["strategy_ret"] = pd.to_numeric(df["equity"], errors="coerce").pct_change().fillna(0.0)
        else:
            raise ValueError(f"{path} nema strategy_ret ani equity")

    if "gross_exposure" not in df.columns:
        df["gross_exposure"] = np.where(df["selected"] != "CASH", 1.0, 0.0)

    if "turnover" not in df.columns:
        prev = df["selected"].shift(1).fillna("CASH")
        curr = df["selected"]
        df["turnover"] = np.where(prev != curr, 1.0, 0.0)

    return df


def build_behavior(main_df: pd.DataFrame, prev_df: pd.DataFrame, start_date: pd.Timestamp) -> pd.DataFrame:
    a = main_df[["ts", "selected", "strategy_ret", "gross_exposure", "turnover"]].copy()
    a = a.rename(
        columns={
            "selected": "main_selected",
            "strategy_ret": "main_strategy_ret",
            "gross_exposure": "main_gross_exposure",
            "turnover": "main_turnover",
        }
    )

    b = prev_df[["ts", "selected", "strategy_ret", "gross_exposure", "turnover"]].copy()
    b = b.rename(
        columns={
            "selected": "prev_selected",
            "strategy_ret": "prev_strategy_ret",
            "gross_exposure": "prev_gross_exposure",
            "turnover": "prev_turnover",
        }
    )

    merged = a.merge(b, on="ts", how="inner")
    merged = merged.loc[merged["ts"] >= start_date].copy()

    merged["ret_diff_main_minus_prev"] = merged["main_strategy_ret"] - merged["prev_strategy_ret"]
    merged["same_selection"] = merged["main_selected"] == merged["prev_selected"]
    merged["different_selection"] = ~merged["same_selection"]

    merged["main_in_market"] = pd.to_numeric(merged["main_gross_exposure"], errors="coerce").fillna(0.0) > 0
    merged["prev_in_market"] = pd.to_numeric(merged["prev_gross_exposure"], errors="coerce").fillna(0.0) > 0

    merged["main_cash_prev_in"] = (~merged["main_in_market"]) & merged["prev_in_market"]
    merged["prev_cash_main_in"] = (~merged["prev_in_market"]) & merged["main_in_market"]

    merged["pair"] = merged["prev_selected"] + " -> " + merged["main_selected"]
    merged["month"] = pd.to_datetime(merged["ts"]).dt.strftime("%Y-%m")

    return merged


def summarize_window(behavior: pd.DataFrame, window_name: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    diff_only = behavior.loc[behavior["different_selection"]].copy()

    summary = pd.DataFrame(
        [
            {
                "window": window_name,
                "days_total": int(len(behavior)),
                "days_different_selection": int(len(diff_only)),
                "different_selection_pct": round(float(len(diff_only) / max(len(behavior), 1) * 100.0), 2),
                "same_selection_pct": round(float(behavior["same_selection"].mean() * 100.0), 2),
                "main_cash_prev_in_days": int(behavior["main_cash_prev_in"].sum()),
                "prev_cash_main_in_days": int(behavior["prev_cash_main_in"].sum()),
                "sum_ret_diff_all_days_pct_points": round(float(behavior["ret_diff_main_minus_prev"].sum() * 100.0), 4),
                "sum_ret_diff_diff_days_pct_points": round(float(diff_only["ret_diff_main_minus_prev"].sum() * 100.0), 4),
                "avg_ret_diff_diff_days_pct_points": round(float(diff_only["ret_diff_main_minus_prev"].mean() * 100.0), 4) if len(diff_only) else np.nan,
                "negative_diff_days": int((diff_only["ret_diff_main_minus_prev"] < 0).sum()),
                "positive_diff_days": int((diff_only["ret_diff_main_minus_prev"] > 0).sum()),
            }
        ]
    )

    pair_table = (
        diff_only.groupby(["prev_selected", "main_selected", "pair"], dropna=False)
        .agg(
            days=("pair", "size"),
            sum_ret_diff_pct_points=("ret_diff_main_minus_prev", lambda x: round(float(x.sum() * 100.0), 4)),
            avg_ret_diff_pct_points=("ret_diff_main_minus_prev", lambda x: round(float(x.mean() * 100.0), 4)),
        )
        .reset_index()
        .sort_values(["sum_ret_diff_pct_points", "days"], ascending=[True, False])
    )

    monthly = (
        diff_only.groupby("month", dropna=False)
        .agg(
            diff_days=("month", "size"),
            sum_ret_diff_pct_points=("ret_diff_main_minus_prev", lambda x: round(float(x.sum() * 100.0), 4)),
            avg_ret_diff_pct_points=("ret_diff_main_minus_prev", lambda x: round(float(x.mean() * 100.0), 4)),
        )
        .reset_index()
        .sort_values("month")
    )

    worst_days = (
        diff_only[["ts", "prev_selected", "main_selected", "ret_diff_main_minus_prev"]]
        .sort_values("ret_diff_main_minus_prev")
        .head(30)
        .copy()
    )
    worst_days["ret_diff_main_minus_prev_pct"] = (worst_days["ret_diff_main_minus_prev"] * 100.0).round(4)

    best_days = (
        diff_only[["ts", "prev_selected", "main_selected", "ret_diff_main_minus_prev"]]
        .sort_values("ret_diff_main_minus_prev", ascending=False)
        .head(30)
        .copy()
    )
    best_days["ret_diff_main_minus_prev_pct"] = (best_days["ret_diff_main_minus_prev"] * 100.0).round(4)

    return summary, pair_table, monthly, worst_days, best_days


def main() -> None:
    if not PHASE49_PAPER_PATH.exists():
        raise FileNotFoundError(f"Missing file: {PHASE49_PAPER_PATH}")

    phase42_path = find_phase42_daily_paper()
    if phase42_path is None:
        raise FileNotFoundError("Nenasiel som daily paper pre phase42/full12")

    print("Phase42 daily paper:", phase42_path)
    print("Phase49 daily paper:", PHASE49_PAPER_PATH)

    prev_df = prepare_daily_paper(phase42_path)
    main_df = prepare_daily_paper(PHASE49_PAPER_PATH)

    all_summary = []
    all_pairs = []
    all_monthly = []
    all_worst = []
    all_best = []

    for window_name, start_date in WINDOWS.items():
        behavior = build_behavior(main_df, prev_df, start_date)
        summary, pair_table, monthly, worst_days, best_days = summarize_window(behavior, window_name)

        summary_path = OUT_DIR / f"{window_name}_summary.csv"
        pair_path = OUT_DIR / f"{window_name}_pair_table.csv"
        monthly_path = OUT_DIR / f"{window_name}_monthly_diff.csv"
        worst_path = OUT_DIR / f"{window_name}_worst_days.csv"
        best_path = OUT_DIR / f"{window_name}_best_days.csv"
        behavior_path = OUT_DIR / f"{window_name}_behavior.csv"

        summary.to_csv(summary_path, index=False)
        pair_table.to_csv(pair_path, index=False)
        monthly.to_csv(monthly_path, index=False)
        worst_days.to_csv(worst_path, index=False)
        best_days.to_csv(best_path, index=False)
        behavior.to_csv(behavior_path, index=False)

        all_summary.append(summary)
        all_pairs.append(pair_table.assign(window=window_name))
        all_monthly.append(monthly.assign(window=window_name))
        all_worst.append(worst_days.assign(window=window_name))
        all_best.append(best_days.assign(window=window_name))

        print(f"\n=== {window_name.upper()} ===\n")
        print(summary.to_string(index=False))

        print("\n--- TOP LOSS PAIRS FOR MAIN ---\n")
        print(pair_table.head(15).to_string(index=False))

        print("\n--- TOP MONTHS WHERE MAIN LOST ON DIFFERENT DAYS ---\n")
        print(monthly.sort_values("sum_ret_diff_pct_points").head(12).to_string(index=False))

    pd.concat(all_summary, ignore_index=True).to_csv(OUT_DIR / "phase58_all_summary.csv", index=False)
    pd.concat(all_pairs, ignore_index=True).to_csv(OUT_DIR / "phase58_all_pair_table.csv", index=False)
    pd.concat(all_monthly, ignore_index=True).to_csv(OUT_DIR / "phase58_all_monthly_diff.csv", index=False)
    pd.concat(all_worst, ignore_index=True).to_csv(OUT_DIR / "phase58_all_worst_days.csv", index=False)
    pd.concat(all_best, ignore_index=True).to_csv(OUT_DIR / "phase58_all_best_days.csv", index=False)

    print(f"\nSaved outputs to: {OUT_DIR}")


if __name__ == "__main__":
    main()