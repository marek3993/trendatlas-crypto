from __future__ import annotations

import pandas as pd

from .indicators import (
    amihud_illiquidity,
    atr_percentile,
    bollinger_b,
    donchian_position,
    efficiency_ratio,
    log_returns,
    residual_vs_sma,
    rolling_drawdown,
    rolling_ols_tstat,
    rolling_zscore,
    rsi,
    sma,
    sma_slope,
    tsmom,
    variance_ratio,
    yang_zhang_vol,
)
from .macro import build_global_liquidity_feature_set
from .utils import annualize_vol


def compute_feature_frame(ohlcv: pd.DataFrame, macro_df: pd.DataFrame | None = None) -> pd.DataFrame:
    df = ohlcv.copy().sort_index()
    out = pd.DataFrame(index=df.index)

    out["ret_1d"] = log_returns(df["close"])
    out["yz_vol_20"] = annualize_vol(yang_zhang_vol(df[["open", "high", "low", "close"]], 20))
    out["tsmom20"] = tsmom(df["close"], 20)
    out["tsmom126"] = tsmom(df["close"], 126)
    out["ols_t20"] = rolling_ols_tstat(df["close"], 20)
    out["ols_t90"] = rolling_ols_tstat(df["close"], 90)
    out["er20"] = efficiency_ratio(df["close"], 20)
    out["donchian20"] = donchian_position(df["high"], df["low"], df["close"], 20)
    out["atr_pct"] = atr_percentile(df["high"], df["low"], df["close"], 14, 252)
    out["amihud20"] = amihud_illiquidity(df["close"], df["volume"], 20)
    out["sma200"] = sma(df["close"], 200)
    out["price_vs_sma200"] = (df["close"] / out["sma200"]) - 1.0
    out["sma200_slope"] = sma_slope(df["close"], 200, 20)
    out["drawdown252"] = rolling_drawdown(df["close"], 252)
    out["z_close_20"] = rolling_zscore(df["close"], 20)
    out["boll_b"] = bollinger_b(df["close"], 20, 2.0)
    out["rsi2"] = rsi(df["close"], 2)
    out["residual_sma20"] = residual_vs_sma(df["close"], 20)
    out["vr5_126"] = variance_ratio(df["close"], 5, 126)

    if macro_df is not None:
        liq = build_global_liquidity_feature_set(macro_df)
        liq = liq.reindex(out.index).ffill()
        for col in liq.columns:
            out[col] = liq[col]
    else:
        out["global_liquidity_lag8"] = 0.0
        out["global_liquidity_lag10"] = 0.0
        out["global_liquidity_lag12"] = 0.0
        out["global_liquidity"] = 0.0

    return out
