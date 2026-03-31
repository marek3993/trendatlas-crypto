from __future__ import annotations

import pandas as pd

from .utils import robust_zscore, squash_score


def _prepare_macro(macro_df: pd.DataFrame) -> pd.DataFrame:
    df = macro_df.copy().sort_index()

    cols = ["g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]
    for c in cols:
        if c not in df.columns:
            df[c] = 0.0

    df = df[cols].apply(pd.to_numeric, errors="coerce")
    df = df.ffill().dropna(how="all")
    return df


def build_global_liquidity_feature(
    macro_df: pd.DataFrame,
    lag_weeks: int = 10,
    window: int = 52,
    name: str | None = None,
) -> pd.Series:
    df = _prepare_macro(macro_df)
    blended = df[["g7_m2_yoy", "bis_gli_yoy", "cb_balance_sheet_yoy"]].mean(axis=1)
    lagged = blended.shift(lag_weeks)
    feat = squash_score(robust_zscore(lagged, window=window))
    feat.name = name or f"global_liquidity_lag{lag_weeks}"
    return feat


def build_global_liquidity_feature_set(macro_df: pd.DataFrame) -> pd.DataFrame:
    f8 = build_global_liquidity_feature(
        macro_df, lag_weeks=8, window=52, name="global_liquidity_lag8"
    )
    f10 = build_global_liquidity_feature(
        macro_df, lag_weeks=10, window=52, name="global_liquidity_lag10"
    )
    f12 = build_global_liquidity_feature(
        macro_df, lag_weeks=12, window=52, name="global_liquidity_lag12"
    )

    out = pd.concat([f8, f10, f12], axis=1)
    out["global_liquidity"] = out.mean(axis=1)
    return out
