from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from market_regime_v1.paper import StrategyParams, run_paper_strategy

DATE_CANDIDATES = ["timestamp", "date", "datetime", "time", "open_time"]
RENAME_MAP = {
    "Date": "date",
    "Timestamp": "timestamp",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Open time": "open_time",
}

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "ohlcv"
MACRO_PATH = ROOT / "data" / "macro" / "global_liquidity_weekly.csv"
OUTPUT_DIR = ROOT / "outputs"


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path)
    df = df.rename(columns=RENAME_MAP)

    date_col = next((c for c in DATE_CANDIDATES if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"{path} nemá dátumový stĺpec")

    df[date_col] = pd.to_datetime(df[date_col], utc=False, errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()

    req = ["open", "high", "low", "close", "volume"]
    df = df[req].apply(pd.to_numeric, errors="coerce").dropna()
    return df


def load_macro_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.set_index("date").sort_index()

    cols = ["g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]
    df = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    return df


def compute_summary(paper: pd.DataFrame) -> dict:
    if paper.empty:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "trade_count": 0,
            "exposure_pct": 0.0,
        }

    rets = paper["strategy_ret"].fillna(0.0)
    if len(rets) < 20:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "trade_count": int((paper["turnover"] > 0).sum()),
            "exposure_pct": float((paper["position"] != 0).mean()) * 100.0,
        }

    equity = (1.0 + rets).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)

    n_days = max(len(rets), 1)
    years = n_days / 252.0
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0

    rolling_peak = equity.cummax()
    drawdown = equity / rolling_peak - 1.0
    max_drawdown = float(drawdown.min())

    vol = float(rets.std())
    sharpe = float((rets.mean() / (vol + 1e-9)) * np.sqrt(252))

    downside = rets[rets < 0].std()
    if pd.isna(downside):
        downside = 0.0
    sortino = float((rets.mean() / (downside + 1e-9)) * np.sqrt(252))

    trade_count = int((paper["turnover"] > 0).sum())
    exposure = float((paper["position"] != 0).mean())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "trade_count": trade_count,
        "exposure_pct": round(exposure * 100.0, 2),
    }


def split_folds(paper: pd.DataFrame, n_folds: int = 3) -> list[pd.DataFrame]:
    if paper.empty or len(paper) < 180:
        return [paper]

    edges = np.linspace(0, len(paper), n_folds + 1, dtype=int)
    folds = []
    for i in range(n_folds):
        part = paper.iloc[edges[i]:edges[i + 1]].copy()
        if len(part) > 20:
            folds.append(part)
    return folds


def robust_score(fold_df: pd.DataFrame) -> float:
    if fold_df.empty:
        return -9999.0

    median_sharpe = float(fold_df["sharpe"].median())
    median_sortino = float(fold_df["sortino"].median())
    median_cagr = float(fold_df["cagr_pct"].median())
    median_return = float(fold_df["total_return_pct"].median())
    worst_dd = float(fold_df["max_drawdown_pct"].min())
    positive_ratio = float((fold_df["total_return_pct"] > 0).mean())
    median_trades = float(fold_df["trade_count"].median())

    score = (
        12.0 * median_sharpe
        + 8.0 * median_sortino
        + 0.30 * median_cagr
        + 0.10 * median_return
        - 0.35 * abs(worst_dd)
        + 12.0 * positive_ratio
        - max(0.0, 8.0 - median_trades) * 0.75
    )
    return round(score, 3)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    macro = load_macro_csv(MACRO_PATH)
    files = sorted(DATA_DIR.glob("*_1d.csv"))
    assets = {path.stem.replace("_1d", ""): load_ohlcv_csv(path) for path in files}

    modes = [
        ("long_only", StrategyParams(allow_long=True, allow_short=False)),
        ("short_only", StrategyParams(allow_long=False, allow_short=True)),
        ("long_short", StrategyParams(allow_long=True, allow_short=True)),
    ]

    rows = []

    for mode_name, params in modes:
        print(f"počítam {mode_name}...", flush=True)

        fold_rows = []
        asset_rows = []

        for symbol, ohlcv in assets.items():
            paper = run_paper_strategy(ohlcv, macro_df=macro, params=params)

            full = compute_summary(paper)
            full["symbol"] = symbol
            asset_rows.append(full)

            for fold_i, fold in enumerate(split_folds(paper, 3), start=1):
                s = compute_summary(fold)
                s["symbol"] = symbol
                s["fold"] = fold_i
                fold_rows.append(s)

        fold_df = pd.DataFrame(fold_rows)
        asset_df = pd.DataFrame(asset_rows)

        rows.append(
            {
                "mode": mode_name,
                "robust_score": robust_score(fold_df),
                "median_fold_sharpe": round(float(fold_df["sharpe"].median()), 3),
                "median_fold_sortino": round(float(fold_df["sortino"].median()), 3),
                "median_fold_cagr_pct": round(float(fold_df["cagr_pct"].median()), 2),
                "median_fold_return_pct": round(float(fold_df["total_return_pct"].median()), 2),
                "worst_fold_dd_pct": round(float(fold_df["max_drawdown_pct"].min()), 2),
                "positive_fold_ratio": round(float((fold_df["total_return_pct"] > 0).mean()), 3),
                "median_asset_sharpe": round(float(asset_df["sharpe"].median()), 3),
                "median_asset_return_pct": round(float(asset_df["total_return_pct"].median()), 2),
            }
        )

    out = pd.DataFrame(rows).sort_values("robust_score", ascending=False).reset_index(drop=True)
    out.to_csv(OUTPUT_DIR / "phase1_modes.csv", index=False)

    print("\nPHASE 1")
    print(out.to_string(index=False))
    print("\nuložené: outputs\\phase1_modes.csv")


if __name__ == "__main__":
    main()