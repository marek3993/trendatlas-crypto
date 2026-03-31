from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .features import compute_feature_frame
from .scoring import TrendState, signal_from_row


@dataclass(frozen=True)
class StrategyParams:
    enter_conf: float = 40.0
    hold_conf: float = 30.0
    long_mr_floor: float = -90.0
    short_mr_ceiling: float = 80.0
    exit_long_bias: float = 0.0
    exit_short_bias: float = 10.0
    allow_long: bool = True
    allow_short: bool = False
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    exit_on_chaos: bool = True

    min_lt_score_long: float = 0.0
    min_st_score_long: float = -100.0
    max_yz_vol_entry: float = 999.0
    max_atr_pct_entry: float = 100.0
    exit_on_transition: bool = False


def run_paper_strategy(
    ohlcv: pd.DataFrame,
    macro_df: pd.DataFrame | None = None,
    params: StrategyParams | None = None,
) -> pd.DataFrame:
    if params is None:
        params = StrategyParams()

    features = compute_feature_frame(ohlcv, macro_df=macro_df)
    rows: list[dict] = []

    position = 0
    prev_position = 0

    close_ret_next = ohlcv["close"].pct_change().shift(-1)
    trade_cost = (params.fee_bps + params.slippage_bps) / 10000.0

    for i in range(260, len(features)):
        idx = features.index[i]
        sig = signal_from_row(features, idx)

        yz_val = float(features.loc[idx, "yz_vol_20"]) if "yz_vol_20" in features.columns else 0.0
        atr_val = float(features.loc[idx, "atr_pct"]) if "atr_pct" in features.columns else 0.0

        enter_long = (
            params.allow_long
            and sig.st_state == TrendState.BULLISH
            and sig.lt_state == TrendState.BULLISH
            and sig.confidence >= params.enter_conf
            and sig.regime != "chaos"
            and sig.mr_score >= params.long_mr_floor
            and sig.lt.score >= params.min_lt_score_long
            and sig.st.score >= params.min_st_score_long
            and yz_val <= params.max_yz_vol_entry
            and atr_val <= params.max_atr_pct_entry
        )

        enter_short = (
            params.allow_short
            and sig.st_state == TrendState.BEARISH
            and sig.lt_state == TrendState.BEARISH
            and sig.confidence >= params.enter_conf
            and sig.regime != "chaos"
            and sig.mr_score <= params.short_mr_ceiling
        )

        hold_long = (
            sig.lt_state != TrendState.BEARISH
            and sig.confidence >= params.hold_conf
            and sig.directional_bias > params.exit_long_bias
            and (not params.exit_on_chaos or sig.regime != "chaos")
            and (not params.exit_on_transition or sig.regime != "transition")
        )

        hold_short = (
            sig.lt_state != TrendState.BULLISH
            and sig.confidence >= params.hold_conf
            and sig.directional_bias < params.exit_short_bias
            and (not params.exit_on_chaos or sig.regime != "chaos")
        )

        if position == 0:
            if enter_long:
                position = 1
            elif enter_short:
                position = -1
        elif position == 1:
            if not hold_long:
                position = 0
                if enter_short:
                    position = -1
        elif position == -1:
            if not hold_short:
                position = 0
                if enter_long:
                    position = 1

        ret_next = float(close_ret_next.iloc[i]) if pd.notna(close_ret_next.iloc[i]) else 0.0
        raw_strategy_ret = position * ret_next

        turnover = abs(position - prev_position)
        cost = turnover * trade_cost
        strategy_ret = raw_strategy_ret - cost

        rows.append(
            {
                "ts": idx,
                "position": position,
                "ret_next": ret_next,
                "strategy_ret": strategy_ret,
                "raw_strategy_ret": raw_strategy_ret,
                "turnover": turnover,
                "cost": cost,
                "directional_bias": sig.directional_bias,
                "confidence": sig.confidence,
                "regime": sig.regime,
                "mr_score": sig.mr_score,
            }
        )

        prev_position = position

    out = pd.DataFrame(rows)
    if out.empty or "ts" not in out.columns:
        return pd.DataFrame(
            columns=[
                "position",
                "ret_next",
                "strategy_ret",
                "raw_strategy_ret",
                "turnover",
                "cost",
                "directional_bias",
                "confidence",
                "regime",
                "mr_score",
                "equity",
            ]
        ).rename_axis("ts")

    out = out.set_index("ts")
    out["equity"] = (1.0 + out["strategy_ret"].fillna(0.0)).cumprod()
    return out