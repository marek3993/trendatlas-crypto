from __future__ import annotations

import numpy as np
import pandas as pd

from market_regime_v1.features import compute_feature_frame
from market_regime_v1.leverage import recommend_leverage
from market_regime_v1.paper import run_paper_strategy
from market_regime_v1.scoring import latest_signal


def make_dummy_ohlcv(n: int = 800) -> pd.DataFrame:
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    rng = np.random.default_rng(7)
    drift = np.concatenate([
        np.full(250, 0.0008),
        np.full(150, -0.0004),
        np.full(200, 0.0012),
        np.full(n - 600, 0.0001),
    ])
    noise = rng.normal(0.0, 0.02, size=n)
    close = 100 * np.exp(np.cumsum(drift + noise))
    open_ = close * (1 + rng.normal(0.0, 0.003, size=n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.01, size=n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.01, size=n))
    volume = rng.integers(1_000_000, 10_000_000, size=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def make_dummy_macro(n: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2021-01-03", periods=n, freq="W")
    rng = np.random.default_rng(11)
    return pd.DataFrame(
        {
            "g7_m2_yoy": rng.normal(6.0, 2.0, size=n),
            "bis_gli_yoy": rng.normal(5.0, 1.5, size=n),
            "cb_balance_sheet_yoy": rng.normal(4.0, 2.5, size=n),
        },
        index=idx,
    )


def main() -> None:
    ohlcv = make_dummy_ohlcv()
    macro = make_dummy_macro()
    features = compute_feature_frame(ohlcv, macro_df=macro)
    signal = latest_signal(features)
    paper = run_paper_strategy(ohlcv, macro_df=macro)
    annualized_vol = float(features["yz_vol_20"].iloc[-1])
    liq_penalty = min(float(features["amihud20"].iloc[-1]) * 1e8, 1.0)
    dd = abs(float(features["drawdown252"].iloc[-1]))
    rolling_sharpe = float(paper["strategy_ret"].tail(90).mean() / (paper["strategy_ret"].tail(90).std() + 1e-9) * np.sqrt(252))
    neg = paper["strategy_ret"].tail(90)
    downside = neg[neg < 0].std() if (neg < 0).any() else 0.0
    rolling_sortino = float(paper["strategy_ret"].tail(90).mean() / (downside + 1e-9) * np.sqrt(252))
    lev = recommend_leverage(signal, annualized_vol, liq_penalty, dd, rolling_sharpe, rolling_sortino)

    print("=== SIGNAL ===")
    print(signal)
    print("\n=== LEVERAGE ===")
    print(lev)
    print("\n=== PAPER ===")
    print(paper.tail())


if __name__ == "__main__":
    main()
