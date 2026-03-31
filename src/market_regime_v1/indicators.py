from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import safe_div


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close).diff()


def tsmom(close: pd.Series, lookback: int) -> pd.Series:
    return close.pct_change(lookback)


def rolling_ols_tstat(close: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    x_centered = x - x.mean()
    x_var = (x_centered ** 2).sum()

    def _t(y: np.ndarray) -> float:
        if np.isnan(y).any():
            return np.nan
        y_centered = y - y.mean()
        beta = float((x_centered * y_centered).sum() / x_var)
        resid = y - (y.mean() + beta * x_centered)
        dof = max(window - 2, 1)
        sigma2 = float((resid ** 2).sum() / dof)
        se = np.sqrt(sigma2 / x_var)
        if se == 0:
            return 0.0
        return beta / se

    return np.log(close).rolling(window).apply(_t, raw=True)


def efficiency_ratio(close: pd.Series, window: int = 20) -> pd.Series:
    direction = (close - close.shift(window)).abs()
    volatility = close.diff().abs().rolling(window).sum()
    return safe_div(direction, volatility)


def donchian_position(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20) -> pd.Series:
    lo = low.rolling(window).min()
    hi = high.rolling(window).max()
    return safe_div(close - lo, hi - lo, fill=0.5)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    return true_range(high, low, close).rolling(window).mean()


def atr_percentile(high: pd.Series, low: pd.Series, close: pd.Series, atr_window: int = 14, rank_window: int = 252) -> pd.Series:
    atr_v = atr(high, low, close, atr_window)
    return atr_v.rolling(rank_window).rank(pct=True)


def amihud_illiquidity(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    ret = close.pct_change().abs()
    dollar_volume = close * volume
    daily = safe_div(ret, dollar_volume)
    return daily.rolling(window).mean()


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).mean()


def sma_slope(close: pd.Series, window: int = 200, slope_lookback: int = 20) -> pd.Series:
    ma = sma(close, window)
    return ma.pct_change(slope_lookback)


def rolling_drawdown(close: pd.Series, window: int = 252) -> pd.Series:
    roll_max = close.rolling(window).max()
    return close / roll_max - 1.0


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = safe_div(avg_gain, avg_loss, fill=np.nan)
    return 100 - (100 / (1 + rs))


def bollinger_b(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.Series:
    ma = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    ub = ma + n_std * sd
    lb = ma - n_std * sd
    return safe_div(close - lb, ub - lb, fill=0.5)


def rolling_zscore(close: pd.Series, window: int = 20) -> pd.Series:
    mean = close.rolling(window).mean()
    std = close.rolling(window).std(ddof=0)
    return safe_div(close - mean, std, fill=0.0)


def residual_vs_sma(close: pd.Series, window: int = 20) -> pd.Series:
    ma = close.rolling(window).mean()
    std = close.rolling(window).std(ddof=0)
    return safe_div(close - ma, std, fill=0.0)


def variance_ratio(close: pd.Series, q: int = 5, window: int = 126) -> pd.Series:
    r1 = np.log(close).diff()
    rq = np.log(close / close.shift(q))
    var1 = r1.rolling(window).var(ddof=1)
    varq = rq.rolling(window).var(ddof=1)
    return safe_div(varq, q * var1, fill=1.0)


def yang_zhang_vol(ohlc: pd.DataFrame, window: int = 20) -> pd.Series:
    o = np.log(ohlc["open"])
    h = np.log(ohlc["high"])
    l = np.log(ohlc["low"])
    c = np.log(ohlc["close"])
    prev_c = c.shift(1)
    oc = o - prev_c
    co = c - o
    rs = (h - c) * (h - o) + (l - c) * (l - o)
    vo = oc.rolling(window).var(ddof=1)
    vc = co.rolling(window).var(ddof=1)
    vrs = rs.rolling(window).mean()
    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    yz_var = vo + k * vc + (1 - k) * vrs
    return np.sqrt(yz_var.clip(lower=0.0))
