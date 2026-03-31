from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
OUT_DIR = OUTPUTS / "phase61_final_compare"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TRADING_DAYS_PER_YEAR = 365.25

MODEL_FILES = {
    "phase61_phase42_core": {
        "label": "Phase42 core",
        "path": OUTPUTS / "phase60_selective_restore_robustness" / "phase60_phase42_core_paper.csv",
    },
    "phase61_phase49_strict": {
        "label": "Phase49 strict",
        "path": OUTPUTS / "phase49_final_compare" / "phase49_bnb_hybrid_strict_paper.csv",
    },
    "phase61_restore_trx_only_base": {
        "label": "Restore BNB vs TRX",
        "path": OUTPUTS / "phase60_selective_restore_robustness" / "phase60_restore_trx_only_base_paper.csv",
    },
    "phase61_restore_trx_sol_base": {
        "label": "Restore BNB vs TRX/SOL",
        "path": OUTPUTS / "phase60_selective_restore_robustness" / "phase60_restore_trx_sol_base_paper.csv",
    },
}

WINDOWS = {
    "since2021": pd.Timestamp("2021-01-01"),
    "since2023": pd.Timestamp("2023-01-01"),
    "since2025": pd.Timestamp("2025-01-01"),
}


def load_paper(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    df = pd.read_csv(path)

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
        raise ValueError(f"{path} nema casovy stlpec")

    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=[ts_col]).copy().sort_values(ts_col)
    df = df.rename(columns={ts_col: "ts"})
    df["ts"] = pd.to_datetime(df["ts"]).dt.normalize()

    for col in ["strategy_ret", "gross_exposure", "turnover", "equity"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "strategy_ret" not in df.columns:
        if "equity" in df.columns:
            df["strategy_ret"] = pd.to_numeric(df["equity"], errors="coerce").pct_change().fillna(0.0)
        else:
            raise ValueError(f"{path} nema strategy_ret ani equity")

    if "gross_exposure" not in df.columns:
        if "selected" in df.columns:
            df["gross_exposure"] = np.where(df["selected"].fillna("CASH").astype(str) != "CASH", 1.0, 0.0)
        else:
            df["gross_exposure"] = 0.0

    if "turnover" not in df.columns:
        if "selected" in df.columns:
            prev = df["selected"].shift(1).fillna("CASH").astype(str)
            curr = df["selected"].fillna("CASH").astype(str)
            df["turnover"] = np.where(prev != curr, 1.0, 0.0)
        else:
            df["turnover"] = 0.0

    if "equity" not in df.columns:
        df["equity"] = (1.0 + df["strategy_ret"].fillna(0.0)).cumprod()

    return df.reset_index(drop=True)


def compute_summary(model_df: pd.DataFrame) -> dict:
    rets = pd.to_numeric(model_df["strategy_ret"], errors="coerce").fillna(0.0)
    equity = (1.0 + rets).cumprod()

    total_return = float(equity.iloc[-1] - 1.0)
    span_days = max((pd.to_datetime(model_df["ts"]).max() - pd.to_datetime(model_df["ts"]).min()).days, 1)
    years = span_days / TRADING_DAYS_PER_YEAR
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    dd = equity / equity.cummax() - 1.0
    max_dd = float(dd.min())

    vol = float(rets.std(ddof=0))
    sharpe = float((rets.mean() / (vol + 1e-12)) * np.sqrt(TRADING_DAYS_PER_YEAR))
    downside = rets[rets < 0].std(ddof=0)
    downside = 0.0 if pd.isna(downside) else float(downside)
    sortino = float((rets.mean() / (downside + 1e-12)) * np.sqrt(TRADING_DAYS_PER_YEAR))

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": int((pd.to_numeric(model_df["turnover"], errors="coerce").fillna(0.0) > 0).sum()),
        "cash_days_pct": round(float((pd.to_numeric(model_df["gross_exposure"], errors="coerce").fillna(0.0) <= 0.0).mean() * 100.0), 2),
    }


def compute_window_summary(model_df: pd.DataFrame, start_dt: pd.Timestamp, prefix: str) -> dict:
    sub = model_df.loc[pd.to_datetime(model_df["ts"]) >= start_dt].copy()
    if sub.empty:
        return {
            f"{prefix}_total_return_pct": np.nan,
            f"{prefix}_cagr_pct": np.nan,
            f"{prefix}_max_drawdown_pct": np.nan,
            f"{prefix}_trade_count": np.nan,
            f"{prefix}_cash_days_pct": np.nan,
        }

    s = compute_summary(sub)
    return {
        f"{prefix}_total_return_pct": s["total_return_pct"],
        f"{prefix}_cagr_pct": s["cagr_pct"],
        f"{prefix}_max_drawdown_pct": s["max_drawdown_pct"],
        f"{prefix}_trade_count": s["trade_count"],
        f"{prefix}_cash_days_pct": s["cash_days_pct"],
    }


def build_equity_curves(loaded: dict[str, pd.DataFrame]) -> pd.DataFrame:
    all_dates = sorted(set().union(*[set(pd.to_datetime(df["ts"])) for df in loaded.values()]))
    eq = pd.DataFrame({"ts": all_dates})

    for model_key, df in loaded.items():
        temp = df[["ts", "equity"]].copy()
        temp["ts"] = pd.to_datetime(temp["ts"])
        eq = eq.merge(temp.rename(columns={"equity": model_key}), on="ts", how="left")

    eq = eq.sort_values("ts")
    value_cols = [c for c in eq.columns if c != "ts"]
    eq[value_cols] = eq[value_cols].ffill()

    for c in value_cols:
        first_valid = pd.to_numeric(eq[c], errors="coerce").dropna()
        if len(first_valid):
            eq[f"{c}_rebased"] = eq[c] / first_valid.iloc[0]

    return eq


def main() -> None:
    loaded: dict[str, pd.DataFrame] = {}

    for model_key, meta in MODEL_FILES.items():
        print(f"Loading {model_key}...", flush=True)
        loaded[model_key] = load_paper(meta["path"])

    rows = []
    for model_key, df in loaded.items():
        row = {
            "model": model_key,
            "label": MODEL_FILES[model_key]["label"],
            **compute_summary(df),
        }
        for prefix, start_dt in WINDOWS.items():
            row.update(compute_window_summary(df, start_dt, prefix))
        rows.append(row)

    summary_df = pd.DataFrame(rows).sort_values(
        ["since2025_cagr_pct", "since2023_cagr_pct", "cagr_pct"],
        ascending=[False, False, False],
    )
    summary_path = OUT_DIR / "phase61_final_compare_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    equity_curves = build_equity_curves(loaded)
    equity_path = OUT_DIR / "phase61_final_compare_equity_curves.csv"
    equity_curves.to_csv(equity_path, index=False)

    print("\n=== PHASE61 FINAL COMPARE ===\n")
    print(summary_df.to_string(index=False))
    print(f"\nSaved summary: {summary_path}")
    print(f"Saved equity curves: {equity_path}")


if __name__ == "__main__":
    main()