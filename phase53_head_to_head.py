from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"

PHASE46_EQUITY_PATH = OUTPUTS / "phase46_final_compare_pruned_equity_curves.csv"
PHASE49_EQUITY_PATH = OUTPUTS / "phase49_final_compare" / "phase49_final_compare_equity_curves.csv"

OUT_DIR = OUTPUTS / "phase53_head_to_head"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PHASE42_KEY = "phase42_full12"
PHASE49_KEY = "phase49_bnb_hybrid_strict"

WINDOWS = {
    "since_2021": pd.Timestamp("2021-01-01"),
    "since_2023": pd.Timestamp("2023-01-01"),
    "since_2025": pd.Timestamp("2025-01-01"),
}

TRADING_DAYS_PER_YEAR = 365.25

MODEL_LABELS = {
    PHASE42_KEY: "Predosly lider",
    PHASE49_KEY: "Hlavna strategia",
}

PHASE42_FILE_HINTS = [
    "phase42_full12",
    "full12",
    "phase42",
    "phase41_full12",
]
PHASE49_PAPER_PATH = OUTPUTS / "phase49_final_compare" / "phase49_bnb_hybrid_strict_paper.csv"


def load_equity_phase46() -> pd.DataFrame:
    df = pd.read_csv(PHASE46_EQUITY_PATH)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    return df.dropna(subset=["ts"]).sort_values("ts").copy()


def load_equity_phase49() -> pd.DataFrame:
    df = pd.read_csv(PHASE49_EQUITY_PATH)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    return df.dropna(subset=["ts"]).sort_values("ts").copy()


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

    if "gross_exposure" not in df.columns:
        df["gross_exposure"] = np.where(df["selected"] != "CASH", 1.0, 0.0)

    if "strategy_ret" not in df.columns:
        if "equity" in df.columns:
            df["strategy_ret"] = pd.to_numeric(df["equity"], errors="coerce").pct_change().fillna(0.0)
        else:
            raise ValueError(f"{path} nema strategy_ret ani equity")

    if "turnover" not in df.columns:
        prev = df["selected"].shift(1).fillna("CASH")
        curr = df["selected"]
        df["turnover"] = np.where(prev != curr, 1.0, 0.0)

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


def build_window_rebased(merged: pd.DataFrame, start_date: pd.Timestamp) -> pd.DataFrame:
    df = merged.loc[merged["ts"] >= start_date].copy()
    if df.empty:
        return df

    for col in [PHASE42_KEY, PHASE49_KEY]:
        first_val = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(first_val):
            df[f"{col}_rebased"] = pd.to_numeric(df[col], errors="coerce") / first_val.iloc[0]
        else:
            df[f"{col}_rebased"] = np.nan

    return df


def window_summary(merged: pd.DataFrame, window_name: str, start_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = build_window_rebased(merged, start_date)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    rows = []
    for key in [PHASE42_KEY, PHASE49_KEY]:
        m = compute_metrics_from_index(df["ts"], df[f"{key}_rebased"])
        rows.append(
            {
                "window": window_name,
                "start_date": str(start_date.date()),
                "model": key,
                "label": MODEL_LABELS[key],
                **m,
            }
        )

    sum_df = pd.DataFrame(rows)

    detail = df[["ts", f"{PHASE42_KEY}_rebased", f"{PHASE49_KEY}_rebased"]].copy()
    detail[f"{PHASE42_KEY}_ret"] = detail[f"{PHASE42_KEY}_rebased"].pct_change().fillna(0.0)
    detail[f"{PHASE49_KEY}_ret"] = detail[f"{PHASE49_KEY}_rebased"].pct_change().fillna(0.0)

    detail["main_above_prev"] = detail[f"{PHASE49_KEY}_rebased"] > detail[f"{PHASE42_KEY}_rebased"]
    detail["main_rolling_90d"] = rolling_return(detail[f"{PHASE49_KEY}_ret"], 90) * 100.0
    detail["prev_rolling_90d"] = rolling_return(detail[f"{PHASE42_KEY}_ret"], 90) * 100.0
    detail["main_rolling_180d"] = rolling_return(detail[f"{PHASE49_KEY}_ret"], 180) * 100.0
    detail["prev_rolling_180d"] = rolling_return(detail[f"{PHASE42_KEY}_ret"], 180) * 100.0

    quick = pd.DataFrame(
        [
            {
                "window": window_name,
                "start_date": str(start_date.date()),
                "main_above_prev_pct_of_days": round(float(detail["main_above_prev"].mean() * 100.0), 2),
                "main_vs_prev_rolling_90d_win_pct": round(float((detail["main_rolling_90d"] > detail["prev_rolling_90d"]).dropna().mean() * 100.0), 2),
                "main_vs_prev_rolling_180d_win_pct": round(float((detail["main_rolling_180d"] > detail["prev_rolling_180d"]).dropna().mean() * 100.0), 2),
            }
        ]
    )

    return sum_df, quick


def selection_stats_for_window(df: pd.DataFrame, label: str, start_date: pd.Timestamp, window_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    recent = df.loc[df["ts"] >= start_date].copy()

    cash_days_pct = float((pd.to_numeric(recent["gross_exposure"], errors="coerce").fillna(0.0) <= 0.0).mean() * 100.0)
    trade_count = int((pd.to_numeric(recent["turnover"], errors="coerce").fillna(0.0) > 0).sum())

    summary = pd.DataFrame(
        [
            {
                "window": window_name,
                "label": label,
                "cash_days_pct": round(cash_days_pct, 2),
                "trade_count": trade_count,
                "days": len(recent),
            }
        ]
    )

    held = recent.loc[recent["selected"].ne("CASH")].copy()
    if held.empty:
        top = pd.DataFrame(columns=["window", "label", "selected", "days_held", "share_of_in_market_days_pct"])
    else:
        top = (
            held.groupby("selected")
            .size()
            .reset_index(name="days_held")
            .sort_values(["days_held", "selected"], ascending=[False, True])
        )
        total_held_days = max(int(top["days_held"].sum()), 1)
        top["share_of_in_market_days_pct"] = (top["days_held"] / total_held_days * 100.0).round(2)
        top.insert(0, "label", label)
        top.insert(0, "window", window_name)

    return summary, top


def compare_daily_behavior(main_df: pd.DataFrame, prev_df: pd.DataFrame, start_date: pd.Timestamp, window_name: str) -> pd.DataFrame:
    a = main_df[["ts", "selected", "gross_exposure", "strategy_ret"]].copy()
    a = a.rename(
        columns={
            "selected": "main_selected",
            "gross_exposure": "main_gross_exposure",
            "strategy_ret": "main_strategy_ret",
        }
    )

    b = prev_df[["ts", "selected", "gross_exposure", "strategy_ret"]].copy()
    b = b.rename(
        columns={
            "selected": "prev_selected",
            "gross_exposure": "prev_gross_exposure",
            "strategy_ret": "prev_strategy_ret",
        }
    )

    merged = a.merge(b, on="ts", how="inner")
    merged = merged.loc[merged["ts"] >= start_date].copy()

    merged["window"] = window_name
    merged["ret_diff_main_minus_prev"] = merged["main_strategy_ret"] - merged["prev_strategy_ret"]
    merged["same_selection"] = merged["main_selected"] == merged["prev_selected"]
    merged["main_in_market"] = pd.to_numeric(merged["main_gross_exposure"], errors="coerce").fillna(0.0) > 0
    merged["prev_in_market"] = pd.to_numeric(merged["prev_gross_exposure"], errors="coerce").fillna(0.0) > 0
    merged["main_cash_prev_in"] = (~merged["main_in_market"]) & merged["prev_in_market"]
    merged["prev_cash_main_in"] = (~merged["prev_in_market"]) & merged["main_in_market"]

    return merged


def main() -> None:
    if not PHASE46_EQUITY_PATH.exists():
        raise FileNotFoundError(f"Missing file: {PHASE46_EQUITY_PATH}")
    if not PHASE49_EQUITY_PATH.exists():
        raise FileNotFoundError(f"Missing file: {PHASE49_EQUITY_PATH}")

    eq46 = load_equity_phase46()
    eq49 = load_equity_phase49()

    merged = eq46[["ts", PHASE42_KEY]].copy()
    merged["ts"] = pd.to_datetime(merged["ts"]).dt.normalize()

    main_eq = eq49[["ts", PHASE49_KEY]].copy()
    main_eq["ts"] = pd.to_datetime(main_eq["ts"]).dt.normalize()

    merged = merged.merge(main_eq, on="ts", how="inner").sort_values("ts").copy()

    summary_frames = []
    quick_frames = []

    for window_name, start_date in WINDOWS.items():
        s, q = window_summary(merged, window_name, start_date)
        if not s.empty:
            summary_frames.append(s)
        if not q.empty:
            quick_frames.append(q)

    summary_df = pd.concat(summary_frames, ignore_index=True)
    quick_df = pd.concat(quick_frames, ignore_index=True)

    summary_path = OUT_DIR / "phase53_head_to_head_summary.csv"
    quick_path = OUT_DIR / "phase53_head_to_head_quick_read.csv"
    summary_df.to_csv(summary_path, index=False)
    quick_df.to_csv(quick_path, index=False)

    phase42_path = find_phase42_daily_paper()
    phase49_path = PHASE49_PAPER_PATH if PHASE49_PAPER_PATH.exists() else None

    print("\n=== PHASE53 HEAD TO HEAD ===\n")
    print("Phase42 daily paper:", phase42_path if phase42_path else "NENAJDENY")
    print("Phase49 daily paper:", phase49_path if phase49_path else "NENAJDENY")

    print("\n--- SUMMARY ---\n")
    print(summary_df.to_string(index=False))

    print("\n--- QUICK READ ---\n")
    print(quick_df.to_string(index=False))

    if phase42_path is None or phase49_path is None:
        print("\nDennu coin attribution cast som nevedel spravit, lebo chyba daily paper pre jeden z modelov.")
        print(f"\nSaved summary: {summary_path}")
        print(f"Saved quick read: {quick_path}")
        return

    prev_df = prepare_daily_paper(phase42_path)
    main_df = prepare_daily_paper(phase49_path)

    selection_summary_frames = []
    top_holdings_frames = []
    behavior_frames = []

    for window_name, start_date in WINDOWS.items():
        prev_sum, prev_top = selection_stats_for_window(prev_df, MODEL_LABELS[PHASE42_KEY], start_date, window_name)
        main_sum, main_top = selection_stats_for_window(main_df, MODEL_LABELS[PHASE49_KEY], start_date, window_name)

        selection_summary_frames.extend([prev_sum, main_sum])
        top_holdings_frames.extend([prev_top.head(10), main_top.head(10)])

        behavior = compare_daily_behavior(main_df, prev_df, start_date, window_name)
        behavior_frames.append(behavior)

        same_selection_pct = float(behavior["same_selection"].mean() * 100.0) if len(behavior) else 0.0
        main_cash_prev_in_days = int(behavior["main_cash_prev_in"].sum()) if len(behavior) else 0
        prev_cash_main_in_days = int(behavior["prev_cash_main_in"].sum()) if len(behavior) else 0

        print(f"\n--- {window_name.upper()} DAILY BEHAVIOR QUICK READ ---\n")
        print(f"Rovnaky vyber coinu: {same_selection_pct:.2f}%")
        print(f"Dni, ked hlavna bola v cashi a predosly lider v trhu: {main_cash_prev_in_days}")
        print(f"Dni, ked predosly lider bol v cashi a hlavna v trhu: {prev_cash_main_in_days}")

    selection_summary_df = pd.concat(selection_summary_frames, ignore_index=True)
    top_holdings_df = pd.concat(top_holdings_frames, ignore_index=True)
    behavior_df = pd.concat(behavior_frames, ignore_index=True)

    selection_summary_path = OUT_DIR / "phase53_head_to_head_selection_summary.csv"
    top_holdings_path = OUT_DIR / "phase53_head_to_head_top_holdings.csv"
    behavior_path = OUT_DIR / "phase53_head_to_head_daily_behavior.csv"

    selection_summary_df.to_csv(selection_summary_path, index=False)
    top_holdings_df.to_csv(top_holdings_path, index=False)
    behavior_df.to_csv(behavior_path, index=False)

    worst_days = (
        behavior_df[["window", "ts", "main_selected", "prev_selected", "ret_diff_main_minus_prev"]]
        .sort_values(["window", "ret_diff_main_minus_prev"])
        .groupby("window", group_keys=False)
        .head(20)
        .copy()
    )
    best_days = (
        behavior_df[["window", "ts", "main_selected", "prev_selected", "ret_diff_main_minus_prev"]]
        .sort_values(["window", "ret_diff_main_minus_prev"], ascending=[True, False])
        .groupby("window", group_keys=False)
        .head(20)
        .copy()
    )

    worst_path = OUT_DIR / "phase53_head_to_head_worst_days.csv"
    best_path = OUT_DIR / "phase53_head_to_head_best_days.csv"
    worst_days.to_csv(worst_path, index=False)
    best_days.to_csv(best_path, index=False)

    print("\n--- SELECTION SUMMARY ---\n")
    print(selection_summary_df.to_string(index=False))

    print("\n--- TOP HOLDINGS ---\n")
    print(top_holdings_df.to_string(index=False))

    print(f"\nSaved summary: {summary_path}")
    print(f"Saved quick read: {quick_path}")
    print(f"Saved selection summary: {selection_summary_path}")
    print(f"Saved top holdings: {top_holdings_path}")
    print(f"Saved daily behavior: {behavior_path}")
    print(f"Saved worst days: {worst_path}")
    print(f"Saved best days: {best_path}")


if __name__ == "__main__":
    main()