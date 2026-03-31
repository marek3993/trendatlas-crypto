from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from .features import compute_feature_frame
from .scoring import latest_signal
from .types import RankedAsset


def rank_assets(asset_data: Mapping[str, pd.DataFrame], macro_df: pd.DataFrame | None = None) -> list[RankedAsset]:
    ranked: list[RankedAsset] = []
    for symbol, df in asset_data.items():
        features = compute_feature_frame(df, macro_df=macro_df)
        sig = latest_signal(features)
        latest = features.iloc[-1]
        liquidity_score = float((1.0 - min(max(latest.get("amihud20", 0.0) * 1e8, 0.0), 1.0)) * 100.0)
        rank = (
            0.45 * abs(sig.directional_bias)
            + 0.20 * ((sig.st.persistence + sig.lt.persistence) / 2.0)
            + 0.15 * liquidity_score
            + 0.10 * sig.confidence
            - 0.10 * abs(sig.mr_score)
        )
        if sig.directional_bias > 20:
            side = "long"
        elif sig.directional_bias < -20:
            side = "short"
        else:
            side = "avoid"
        ranked.append(
            RankedAsset(
                symbol=symbol,
                rank=float(rank),
                directional_bias=sig.directional_bias,
                confidence=sig.confidence,
                mr_score=sig.mr_score,
                liquidity_score=liquidity_score,
                reason=f"{side}; regime={sig.regime}; ST={sig.st_state.value}; LT={sig.lt_state.value}",
            )
        )
    return sorted(ranked, key=lambda x: x.rank, reverse=True)
