from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class TrendState(Enum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


@dataclass
class BlockSnapshot:
    score: float
    confidence: float
    strength: float
    persistence: float
    exit_risk: float


@dataclass
class SignalSnapshot:
    st_state: TrendState
    lt_state: TrendState
    st: BlockSnapshot
    lt: BlockSnapshot
    mr_score: float
    regime: str
    confidence: float
    directional_bias: float
    timing_score: float


def _clip(s: pd.Series) -> pd.Series:
    return s.fillna(0.0).clip(-100.0, 100.0)


def _block_confidence(score_df: pd.DataFrame, cols: list[str]) -> pd.Series:
    row_mean = score_df[cols].mean(axis=1)
    mad = score_df[cols].sub(row_mean, axis=0).abs().mean(axis=1)
    conf = 100.0 * (1.0 - (mad / 80.0))
    return conf.clip(0.0, 100.0)


def _state_from_score(score: float, bullish: float = 35.0, bearish: float = -35.0) -> TrendState:
    if score >= bullish:
        return TrendState.BULLISH
    if score <= bearish:
        return TrendState.BEARISH
    return TrendState.NEUTRAL


def compute_score_frame(features: pd.DataFrame) -> pd.DataFrame:
    s = pd.DataFrame(index=features.index)

    s["st_tsmom20"] = _clip(features["tsmom20"] * 100.0)
    s["st_ols_t20"] = _clip(features["ols_t20"] * 10.0)
    s["st_er20"] = _clip((features["er20"] - 0.5) * 200.0)
    s["st_donchian20"] = _clip((features["donchian20"] - 0.5) * 200.0)
    s["st_price_vs_sma200"] = _clip(features["price_vs_sma200"] * 300.0)

    s["lt_tsmom126"] = _clip(features["tsmom126"] * 100.0)
    s["lt_ols_t90"] = _clip(features["ols_t90"] * 10.0)
    s["lt_sma200_slope"] = _clip(features["sma200_slope"] * 500.0)
    s["lt_price_vs_sma200"] = _clip(features["price_vs_sma200"] * 300.0)
    s["global_liquidity_lag8"] = _clip(features["global_liquidity_lag8"])
    s["global_liquidity_lag10"] = _clip(features["global_liquidity_lag10"])
    s["global_liquidity_lag12"] = _clip(features["global_liquidity_lag12"])
    s["global_liquidity"] = (
        s["global_liquidity_lag8"]
        + s["global_liquidity_lag10"]
        + s["global_liquidity_lag12"]
    ) / 3.0

    s["mr_z_close_20"] = _clip(-features["z_close_20"] * 25.0)
    s["mr_boll_b"] = _clip((0.5 - features["boll_b"]) * 200.0)
    s["mr_rsi2"] = _clip((50.0 - features["rsi2"]) * 2.0)
    s["mr_residual_sma20"] = _clip(-features["residual_sma20"] * 300.0)

    return s


def latest_signal(features: pd.DataFrame) -> SignalSnapshot:
    s = compute_score_frame(features)

    st_cols = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
    lt_cols = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
    mr_cols = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]

    st_score = float(s[st_cols].iloc[-1].mean())
    lt_score = float(s[lt_cols].iloc[-1].mean())
    mr_score = float(s[mr_cols].iloc[-1].mean())

    st_conf = float(_block_confidence(s, st_cols).iloc[-1])
    lt_conf = float(_block_confidence(s, lt_cols).iloc[-1])

    yz = float(features["yz_vol_20"].iloc[-1]) if "yz_vol_20" in features.columns else 0.0
    atr_pct = float(features["atr_pct"].iloc[-1]) if "atr_pct" in features.columns else 0.0

    if yz > 0.9:
        regime = "chaos"
    elif atr_pct > 80:
        regime = "transition"
    elif abs(st_score) < 20 and abs(lt_score) < 20:
        regime = "range"
    else:
        regime = "transition"

    st_state = _state_from_score(st_score)
    lt_state = _state_from_score(lt_score)

    confidence = min(st_conf, lt_conf)
    directional_bias = 0.45 * lt_score + 0.35 * st_score + 0.20 * mr_score
    timing_score = directional_bias

    st_block = BlockSnapshot(
        score=st_score,
        confidence=st_conf,
        strength=abs(st_score),
        persistence=max(st_score, 0.0),
        exit_risk=50.0 - (st_score / 2.0),
    )
    lt_block = BlockSnapshot(
        score=lt_score,
        confidence=lt_conf,
        strength=abs(lt_score),
        persistence=max(lt_score, 0.0),
        exit_risk=50.0 - (lt_score / 2.0),
    )

    return SignalSnapshot(
        st_state=st_state,
        lt_state=lt_state,
        st=st_block,
        lt=lt_block,
        mr_score=mr_score,
        regime=regime,
        confidence=confidence,
        directional_bias=directional_bias,
        timing_score=timing_score,
    )
def signal_from_row(features: pd.DataFrame, idx) -> SignalSnapshot:
    s = compute_score_frame(features)

    st_cols = ["st_tsmom20", "st_ols_t20", "st_er20", "st_donchian20", "st_price_vs_sma200"]
    lt_cols = ["lt_tsmom126", "lt_ols_t90", "lt_sma200_slope", "lt_price_vs_sma200", "global_liquidity"]
    mr_cols = ["mr_z_close_20", "mr_boll_b", "mr_rsi2", "mr_residual_sma20"]

    st_score = float(s.loc[idx, st_cols].mean())
    lt_score = float(s.loc[idx, lt_cols].mean())
    mr_score = float(s.loc[idx, mr_cols].mean())

    st_conf = float(_block_confidence(s, st_cols).loc[idx])
    lt_conf = float(_block_confidence(s, lt_cols).loc[idx])

    yz = float(features.loc[idx, "yz_vol_20"]) if "yz_vol_20" in features.columns else 0.0
    atr_pct = float(features.loc[idx, "atr_pct"]) if "atr_pct" in features.columns else 0.0

    if yz > 0.9:
        regime = "chaos"
    elif atr_pct > 80:
        regime = "transition"
    elif abs(st_score) < 20 and abs(lt_score) < 20:
        regime = "range"
    else:
        regime = "transition"

    st_state = _state_from_score(st_score)
    lt_state = _state_from_score(lt_score)

    confidence = min(st_conf, lt_conf)
    directional_bias = 0.45 * lt_score + 0.35 * st_score + 0.20 * mr_score
    timing_score = directional_bias

    st_block = BlockSnapshot(
        score=st_score,
        confidence=st_conf,
        strength=abs(st_score),
        persistence=max(st_score, 0.0),
        exit_risk=50.0 - (st_score / 2.0),
    )
    lt_block = BlockSnapshot(
        score=lt_score,
        confidence=lt_conf,
        strength=abs(lt_score),
        persistence=max(lt_score, 0.0),
        exit_risk=50.0 - (lt_score / 2.0),
    )

    return SignalSnapshot(
        st_state=st_state,
        lt_state=lt_state,
        st=st_block,
        lt=lt_block,
        mr_score=mr_score,
        regime=regime,
        confidence=confidence,
        directional_bias=directional_bias,
        timing_score=timing_score,
    )