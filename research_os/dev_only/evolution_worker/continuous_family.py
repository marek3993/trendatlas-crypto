"""Frozen long/cash family math: close-D evidence, next-open fills only."""
from __future__ import annotations

import hashlib
import statistics

from research_os.dev_only.evolution.backtest import canonical, metrics, read_bars

FAMILIES = frozenset({"trend_momentum", "trend_low_turnover", "mean_reversion_entry",
                      "trend_momentum_protected", "regime_ensemble"})


def validate_genes(family, genes, domains):
    if family not in FAMILIES or set(genes) != set(domains):
        raise ValueError("Unknown family or gene layout")
    if any(not isinstance(values, list) or not values or genes[key] not in values
           for key, values in domains.items()):
        raise ValueError("Gene outside the frozen domain")
    if genes.get("exposure_cap", 1) > 0.75 or genes.get("exposure_cap", 0) <= 0:
        raise ValueError("Exposure cap exceeds research limit")
    if "fast_window" in genes and "slow_window" in genes and genes["fast_window"] >= genes["slow_window"]:
        raise ValueError("Fast window must precede slow window")


def candidate_id(family, genes, domains):
    validate_genes(family, genes, domains)
    return hashlib.sha256(canonical({"family": family, "genes": genes}).encode()).hexdigest()


def decision(history, family, genes):
    """Read only completed closes; no caller may expose the next day's open."""
    if len(history) < 200:
        raise ValueError("Insufficient closed-day warmup")
    close = history[-1]
    slow = statistics.fmean(history[-genes.get("slow_window", genes.get("regime_window", 200)):])
    mean = statistics.fmean(history[-genes.get("mean_window", 20):])
    short = history[-genes.get("mean_window", 20):]
    deviation = statistics.pstdev(short)
    oversold = deviation > 0 and close <= mean - genes.get("entry_z", 1.5) * deviation
    momentum_window = genes.get("momentum_window", 20)
    momentum = close / history[-1 - momentum_window] - 1
    fast = statistics.fmean(history[-genes.get("fast_window", 20):])
    trend = fast > slow and momentum > genes.get("entry_threshold", 0)
    if family == "trend_momentum":
        return {"enter": trend, "exit": not trend, "reason": "trend_momentum"}
    if family == "trend_low_turnover":
        allowed = close >= slow and momentum > genes["entry_threshold"]
        return {"enter": allowed, "exit": close < slow or momentum < 0,
                "reason": "low_turnover_trend"}
    if family == "mean_reversion_entry":
        allowed = close >= slow * (1 - genes["downtrend_floor"])
        return {"enter": oversold and allowed, "exit": close >= mean,
                "reason": "mean_reversion"}
    if family == "trend_momentum_protected":
        overbought = deviation > 0 and close > mean + genes["overbought_z_veto"] * deviation
        return {"enter": trend and not overbought, "exit": not trend,
                "reason": "protected_trend"}
    if family == "regime_ensemble":
        regime = close >= slow * (1 - genes["regime_floor"])
        return {"enter": regime and (trend or oversold),
                "exit": not regime or (not trend and close >= mean),
                "reason": "regime_ensemble"}
    raise ValueError("Unknown family")


def backtest(bars, family, genes, domains, start, end, *, benchmark=None, cost_bps=15, step_guard=None):
    validate_genes(family, genes, domains)
    if benchmark not in (None, "cash", "btc") or cost_bps != 15:
        raise ValueError("Unknown benchmark or changed costs")
    # Hide future bars even if the caller passed the full input.
    visible = [bar for bar in bars if bar.day <= end]
    active = [bar for bar in visible if bar.day >= start]
    history = [bar.close for bar in visible if bar.day < start]
    if len(active) < 2 or active[0].day != start or active[-1].day != end or len(history) < 200:
        raise ValueError("Incomplete chronological fold or warmup")
    previous_day = next(bar.day for bar in reversed(visible) if bar.day < start)
    cash, units, held_closes, cooldown_until = 1.0, 0.0, 0, -1
    rate = cost_bps / 10000
    curve, trades = [], []

    def trade(bar, side, notional, before, reason):
        trades.append({"signal_day": previous_day, "day": bar.day, "fill": "open",
                       "side": side, "reason": reason, "price": bar.open,
                       "notional": notional, "cost": notional * rate,
                       "turnover_fraction": notional / before})

    for index, bar in enumerate(active):
        if step_guard is not None:
            step_guard()
        before = cash + units * bar.open
        boundary = index == len(active) - 1
        signal = decision(history, family, genes) if benchmark is None else None
        if units:
            min_hold = genes.get("min_hold", 0)
            max_hold = genes.get("max_hold")
            should_exit = boundary or (benchmark is None and (
                (signal["exit"] and held_closes >= min_hold) or
                (max_hold is not None and held_closes >= max_hold)))
            if should_exit:
                notional = units * bar.open
                trade(bar, "sell", notional, before, "fold_boundary" if boundary else "signal_or_max_hold")
                cash += notional * (1 - rate)
                units, held_closes = 0.0, 0
                cooldown_until = index + genes.get("cooldown", 0)
            elif benchmark is None:
                cap = genes["exposure_cap"]
                excess = units * bar.open - cap * before
                if excess > 1e-12:
                    notional = excess / (1 - cap * rate)
                    trade(bar, "sell", notional, before, "exposure_cap")
                    cash += notional * (1 - rate)
                    units -= notional / bar.open
        elif not boundary and benchmark != "cash":
            allowed = benchmark == "btc" or (index > cooldown_until and signal["enter"])
            if allowed:
                cap = 1.0 if benchmark == "btc" else genes["exposure_cap"]
                notional = cap * before / (1 + cap * rate)
                trade(bar, "buy", notional, before, "benchmark" if benchmark else signal["reason"])
                units += notional / bar.open
                cash -= notional * (1 + rate)
                held_closes = 0
        opening_equity = cash + units * bar.open
        weight = units * bar.open / opening_equity
        if benchmark is None and weight > genes["exposure_cap"] + 1e-10:
            raise ArithmeticError("Opening exposure cap exceeded")
        if cash < -1e-12 or units < -1e-12:
            raise ArithmeticError("Borrowing or shorting forbidden")
        equity = cash + units * bar.close
        curve.append({"day": bar.day, "equity": equity, "weight": weight})
        held_closes += bool(units)
        history.append(bar.close)
        previous_day = bar.day
    result = metrics(curve, trades)
    turnover = sum(item["turnover_fraction"] for item in trades)
    annualized = turnover * 365.25 / len(active)
    result.update(annualized_turnover=annualized, turnover_disqualified=annualized > 24,
                  max_opening_exposure=max(item["weight"] for item in curve),
                  entries=sum(item["side"] == "buy" for item in trades),
                  data_role="seen_development_retrospective")
    return {"metrics": result, "curve": curve, "trades": trades}
