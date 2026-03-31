from dataclasses import dataclass
from enum import Enum


class TrendState(str, Enum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


@dataclass(slots=True)
class BlockSnapshot:
    score: float
    confidence: float
    strength: float
    persistence: float
    exit_risk: float


@dataclass(slots=True)
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


@dataclass(slots=True)
class RankedAsset:
    symbol: str
    rank: float
    directional_bias: float
    confidence: float
    mr_score: float
    liquidity_score: float
    reason: str


@dataclass(slots=True)
class LeverageRecommendation:
    allowed: bool
    recommended: float
    max_safe: float
    quality_score: float
    reason: str
