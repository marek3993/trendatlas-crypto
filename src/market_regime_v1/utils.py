from __future__ import annotations

import math
import numpy as np
import pandas as pd


def robust_zscore(series: pd.Series, window: int = 252, eps: float = 1e-9) -> pd.Series:
    med = series.rolling(window).median()
    mad = (series - med).abs().rolling(window).median()
    return (series - med) / (1.4826 * mad + eps)


def squash_score(z: pd.Series | float, k: float = 1.5) -> pd.Series | float:
    if isinstance(z, pd.Series):
        return 100.0 * np.tanh(z / k)
    return 100.0 * math.tanh(z / k)


def pct_rank(series: pd.Series, window: int = 252) -> pd.Series:
    return series.rolling(window).rank(pct=True)


def annualize_vol(daily_vol: pd.Series, periods_per_year: int = 252) -> pd.Series:
    return daily_vol * np.sqrt(periods_per_year)


def safe_div(a: pd.Series, b: pd.Series, fill: float = 0.0) -> pd.Series:
    out = a / b.replace(0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan).fillna(fill)
