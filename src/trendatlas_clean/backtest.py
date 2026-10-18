"""Explicit daily close-fill proxy accounting; no inference of real account PnL."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .core import ANN, price_returns
from .data import Panel


@dataclass(frozen=True)
class Costs:
    perp_fee_bps: float = 0.7 * 1.5 + 0.3 * 4.5
    spot_fee_bps: float = 0.7 * 4.0 + 0.3 * 7.0
    slippage_bps: float = 5.0
    cash_yield_pa: float = 0.04

    def __post_init__(self) -> None:
        values = (self.perp_fee_bps, self.spot_fee_bps, self.slippage_bps, self.cash_yield_pa)
        if not all(math.isfinite(x) and x >= 0 for x in values):
            raise ValueError("Costs must be finite and non-negative")


def replay(panel: Panel, decisions: pd.DataFrame, costs: Costs = Costs()) -> pd.DataFrame:
    close = panel.close
    if not decisions.index.equals(close.index) or not decisions.columns.equals(close.columns):
        raise ValueError("Decision and price axes must match")
    values = decisions.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or (decisions.sum(axis=1) > 1 + 1e-12).any():
        raise ValueError("Invalid long-only 1x decision weights")
    # This is the only PnL timing shift. D decision remains on D in signal.json.
    held = decisions.shift(1).fillna(0.0)
    prior = held.shift(1).fillna(0.0)
    ret = price_returns(close)
    missing_return = (held.gt(0) & ret.isna()).any(axis=1)
    gross = (held * ret.fillna(0)).sum(axis=1).mask(missing_return)
    fees = pd.Series({c: costs.spot_fee_bps if c in {"BTC", "ETH"} else costs.perp_fee_bps for c in close})
    perp_held = held.copy()
    for c in {"BTC", "ETH"} & set(perp_held.columns):
        perp_held[c] = 0
    funding = (perp_held * panel.funding).sum(axis=1)
    cash_weight = 1 - held.sum(axis=1)
    # Explicit simple daily accrual; this is a research assumption, not cash custody income.
    cash_interest = cash_weight * costs.cash_yield_pa / ANN
    # Fixed daily weights require rebalancing even without a symbol switch.
    # Use yesterday's price/funding/cash move to obtain today's pre-trade notionals.
    holding_growth = 1 + gross - funding + cash_interest
    previous_growth = holding_growth.shift(1).fillna(1.0)
    drifted = prior.mul(1 + ret.shift(1).fillna(0)).div(previous_growth, axis=0)
    combined_rate = fees / 10000 + costs.slippage_bps / 10000
    # Solve post_cost_NAV = pre_cost_NAV - trading_cost, so a 1x target is
    # relative to NAV after costs, not a tiny accidental levered position.
    nav_fraction = pd.Series(1.0, index=held.index)
    for _ in range(20):
        traded = (held.mul(nav_fraction, axis=0) - drifted).abs()
        updated = 1 - traded.mul(combined_rate).sum(axis=1)
        if (updated - nav_fraction).abs().max() < 1e-14:
            nav_fraction = updated
            break
        nav_fraction = updated
    traded = (held.mul(nav_fraction, axis=0) - drifted).abs()
    fee_debit = traded.mul(fees / 10000).sum(axis=1)
    slippage = traded.sum(axis=1) * costs.slippage_bps / 10000
    net = nav_fraction * holding_growth - 1
    invalid_nav = net.le(-1) | ~np.isfinite(net)
    equity = (1 + net).cumprod(skipna=False)
    unpriced_execution = (traded.gt(1e-12) & close.shift(1).isna()).any(axis=1)
    proxy_funding = (perp_held.gt(0) & panel.funding_source.ne("OBSERVED")).any(axis=1)
    return pd.DataFrame({
        "gross_return": gross, "fees": fee_debit, "slippage": slippage,
        "funding_debit": funding, "cash_interest": cash_interest, "net_return": net,
        "equity": equity, "gross_exposure": held.sum(axis=1), "cash_weight": cash_weight,
        "turnover_notional": traded.sum(axis=1), "unpriced_execution_proxy": unpriced_execution,
        "post_cost_nav_fraction": nav_fraction,
        "funding_proxy_used": proxy_funding, "invalid_return_or_nav": invalid_nav,
    }, index=close.index)


def metrics(ledger: pd.DataFrame) -> dict:
    if ledger.empty or ledger["invalid_return_or_nav"].any():
        return {"status": "INVALID_RETURN_OR_NAV", "cagr_pct": None, "max_drawdown_pct": None, "sharpe": None}
    r = ledger["net_return"].astype(float)
    growth = float((1 + r).prod())
    days = (ledger.index[-1] - ledger.index[0]).days + 1
    eq = (1 + r).cumprod()
    peak = eq.cummax().clip(lower=1.0)
    sigma = float(r.std(ddof=1))
    return {"status": "DAILY_SPOT_PRICE_COST_PROXY", "start_day": str(ledger.index[0].date()),
            "end_day": str(ledger.index[-1].date()), "calendar_days": days,
            "cagr_pct": float((growth ** (ANN / days) - 1) * 100),
            "total_return_pct": float((growth - 1) * 100),
            "max_drawdown_pct": float((eq / peak - 1).min() * 100),
            "sharpe": float(r.mean() / sigma * math.sqrt(ANN)) if sigma > 0 else None,
            "turnover_notional": float(ledger["turnover_notional"].sum()),
            "unpriced_execution_proxy_days": int(ledger["unpriced_execution_proxy"].sum()),
            "funding_proxy_days": int(ledger["funding_proxy_used"].sum()),
            "cash_yield_is_model_assumption": True, "daily_close_fill_is_model_assumption": True,
            "real_account_pnl": False, "live_execution_certified": False}
