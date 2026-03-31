from __future__ import annotations

import math

from .config import RiskConfig
from .types import LeverageRecommendation, SignalSnapshot


def recommend_leverage(
    signal: SignalSnapshot,
    annualized_vol: float,
    liquidity_penalty_pct: float,
    rolling_drawdown: float,
    rolling_sharpe: float | None,
    rolling_sortino: float | None,
    cfg: RiskConfig | None = None,
) -> LeverageRecommendation:
    cfg = cfg or RiskConfig()

    if signal.confidence < 40 or signal.regime in {"chaos", "range"}:
        return LeverageRecommendation(False, 1.0, 1.0, 0.0, "slabá dôvera alebo chop režim")

    vol = max(annualized_vol, 1e-6)
    base = cfg.target_vol_annual / vol
    quality = (
        0.35 * min(abs(signal.directional_bias), 100.0)
        + 0.25 * signal.confidence
        + 0.20 * min((signal.st.persistence + signal.lt.persistence) / 2.0, 100.0)
        + 0.20 * (100.0 - min(abs(signal.mr_score), 100.0))
    ) / 100.0

    sr_bonus = 1.0
    if rolling_sharpe is not None:
        sr_bonus *= 1.0 + max(min(rolling_sharpe, 2.0), -1.0) * 0.08
    if rolling_sortino is not None:
        sr_bonus *= 1.0 + max(min(rolling_sortino, 3.0), -1.0) * 0.05

    dd_penalty = max(0.25, 1.0 - 1.5 * max(rolling_drawdown, 0.0))
    liq_penalty = max(0.30, 1.0 - liquidity_penalty_pct)
    q_multiplier = min(max(0.70 + 0.60 * quality, 0.70), 1.30)

    lev = base * q_multiplier * dd_penalty * liq_penalty * sr_bonus
    lev = min(max(lev, cfg.min_leverage), cfg.max_leverage)

    return LeverageRecommendation(
        allowed=True,
        recommended=round(float(lev), 2),
        max_safe=cfg.max_leverage,
        quality_score=round(float(quality * 100.0), 1),
        reason=(
            f"base={base:.2f}, kvalita={quality*100:.1f}, dd_penalty={dd_penalty:.2f}, "
            f"liq_penalty={liq_penalty:.2f}, sr_bonus={sr_bonus:.2f}"
        ),
    )
