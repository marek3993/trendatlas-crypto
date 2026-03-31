from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.leverage import recommend_leverage
from market_regime_v1.paper import run_paper_strategy
from market_regime_v1.scoring import latest_signal, TrendState

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


def compute_backtest_summary(paper: pd.DataFrame) -> dict:
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
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "trade_count": trade_count,
        "exposure_pct": round(exposure * 100.0, 2),
    }


def classify_action(sig) -> str:
    if (
        sig.st_state == TrendState.BEARISH
        and sig.lt_state == TrendState.BEARISH
        and sig.confidence >= 40
        and sig.regime != "chaos"
    ):
        return "SHORT"

    if (
        sig.st_state == TrendState.BULLISH
        and sig.lt_state == TrendState.BULLISH
        and sig.confidence >= 40
        and sig.regime != "chaos"
    ):
        return "LONG"

    if sig.regime == "chaos":
        return "AVOID"

    return "WATCH"


def action_order(action: str) -> int:
    if action == "LONG":
        return 0
    if action == "SHORT":
        return 1
    if action == "WATCH":
        return 2
    return 3


def main() -> None:
    macro = load_macro_csv("data/macro/global_liquidity_weekly.csv")
    folder = Path("data/ohlcv")
    files = sorted(folder.glob("*_1d.csv"))

    rows = []
    for path in files:
        symbol = path.stem.replace("_1d", "")
        ohlcv = load_ohlcv_csv(path)
        features = compute_feature_frame(ohlcv, macro_df=macro)
        sig = latest_signal(features)
        paper = run_paper_strategy(ohlcv, macro_df=macro)
        bt = compute_backtest_summary(paper)

        action = classify_action(sig)

        live_score = (
            0.35 * abs(sig.lt.score)
            + 0.25 * abs(sig.st.score)
            + 0.20 * sig.confidence
            - 0.10 * abs(sig.mr_score)
            - 10.0 * (1 if sig.regime in ["chaos", "range"] else 0)
        )

        bt_score = (
            0.30 * bt["sharpe"] * 10.0
            + 0.20 * bt["sortino"] * 10.0
            + 0.20 * bt["total_return_pct"] / 2.0
            + 0.10 * bt["cagr_pct"] / 2.0
            - 0.25 * abs(bt["max_drawdown_pct"])
        )

        final_score = 0.65 * live_score + 0.35 * bt_score

        if action == "WATCH":
            final_score -= 15.0
        elif action == "AVOID":
            final_score -= 30.0

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
            sig,
            annualized_vol,
            liq_penalty,
            dd,
            rolling_sharpe,
            rolling_sortino,
        )

        rows.append(
            {
                "symbol": symbol,
                "action": action,
                "st_state": sig.st_state.value,
                "lt_state": sig.lt_state.value,
                "regime": sig.regime,
                "st_score": round(sig.st.score, 2),
                "lt_score": round(sig.lt.score, 2),
                "mr_score": round(sig.mr_score, 2),
                "confidence": round(sig.confidence, 2),
                "total_return_pct": bt["total_return_pct"],
                "cagr_pct": bt["cagr_pct"],
                "max_drawdown_pct": bt["max_drawdown_pct"],
                "sharpe": bt["sharpe"],
                "sortino": bt["sortino"],
                "trade_count": bt["trade_count"],
                "exposure_pct": bt["exposure_pct"],
                "live_score": round(live_score, 2),
                "bt_score": round(bt_score, 2),
                "final_score": round(final_score, 2),
                "lev_allowed": lev.allowed,
                "lev_recommended": lev.recommended,
                "lev_max_safe": lev.max_safe,
                "lev_quality": round(lev.quality_score, 2),
            }
        )

    out = pd.DataFrame(rows)
    out["_action_order"] = out["action"].map(action_order)
    out = out.sort_values(["_action_order", "final_score"], ascending=[True, False]).drop(columns=["_action_order"])

    Path("outputs").mkdir(exist_ok=True)
    out.to_csv("outputs/universe_latest.csv", index=False)

    print(out.to_string(index=False))
    print("\nUložené do: outputs\\universe_latest.csv")


if __name__ == "__main__":
    main()
