from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.leverage import recommend_leverage
from market_regime_v1.paper import run_paper_strategy
from market_regime_v1.scoring import latest_signal

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


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV nenájdené: {path}")

    df = pd.read_csv(path)
    df = df.rename(columns=RENAME_MAP)

    date_col = next((c for c in DATE_CANDIDATES if c in df.columns), None)
    if date_col is None:
        raise ValueError(
            "CSV musí obsahovať aspoň jeden dátumový stĺpec: "
            + ", ".join(DATE_CANDIDATES)
        )

    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"CSV nemá povinné stĺpce: {missing}")

    df[date_col] = pd.to_datetime(df[date_col], utc=False, errors="coerce")
    df = df.dropna(subset=[date_col]).copy()
    df = df.set_index(date_col).sort_index()
    df = df[required].apply(pd.to_numeric, errors="coerce")
    df = df.dropna().copy()
    return df


def load_macro_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Macro CSV nenájdené: {path}")

    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError("Macro CSV musí obsahovať stĺpec 'date'")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.set_index("date").sort_index()

    cols = ["g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Macro CSV nemá povinné stĺpce: {missing}")

    df = df[cols].apply(pd.to_numeric, errors="coerce")
    df = df.dropna().copy()
    return df


def compute_backtest_summary(paper: pd.DataFrame) -> dict:
    if paper.empty:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "trade_count": 0,
            "avg_turnover": 0.0,
            "exposure_pct": 0.0,
        }

    rets = paper["strategy_ret"].fillna(0.0)
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
    avg_turnover = float(paper["turnover"].mean())
    exposure = float((paper["position"] != 0).mean())

    return {
        "total_return_pct": round(total_return * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "trade_count": trade_count,
        "avg_turnover": round(avg_turnover, 4),
        "exposure_pct": round(exposure * 100.0, 2),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("Použitie: python examples\\run_from_csv.py data\\ohlcv\\BTCUSDT_1d.csv")
        raise SystemExit(1)

    csv_path = sys.argv[1]
    ohlcv = load_ohlcv_csv(csv_path)
    macro = load_macro_csv("data/macro/global_liquidity_weekly.csv")

    features = compute_feature_frame(ohlcv, macro_df=macro)
    signal = latest_signal(features)
    paper = run_paper_strategy(ohlcv, macro_df=macro)

    annualized_vol = float(features["yz_vol_20"].iloc[-1])
    liq_penalty = min(float(features["amihud20"].iloc[-1]) * 1e8, 1.0)
    dd = abs(float(features["drawdown252"].iloc[-1]))

    tail = paper["strategy_ret"].tail(90) if not paper.empty else pd.Series(dtype=float)
    if tail.empty:
        rolling_sharpe = 0.0
        rolling_sortino = 0.0
    else:
        rolling_sharpe = float(tail.mean() / (tail.std() + 1e-9) * np.sqrt(252))
        downside = tail[tail < 0].std() if (tail < 0).any() else 0.0
        rolling_sortino = float(tail.mean() / (downside + 1e-9) * np.sqrt(252))

    lev = recommend_leverage(
        signal,
        annualized_vol,
        liq_penalty,
        dd,
        rolling_sharpe,
        rolling_sortino,
    )

    summary = compute_backtest_summary(paper)

    print("=== CSV ===")
    print(csv_path)
    print(f"Rows: {len(ohlcv)} | From: {ohlcv.index.min()} | To: {ohlcv.index.max()}")

    print("\n=== SIGNAL ===")
    print(signal)

    print("\n=== LEVERAGE ===")
    print(lev)

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}: {v}")

    print("\n=== PAPER ===")
    print(paper.tail())


if __name__ == "__main__":
    main()
