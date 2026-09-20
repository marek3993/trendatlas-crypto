"""Daily long/cash simulation using prior closes and next-open fills."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import math
import statistics


DOMAINS = {
    "fast": (5, 10, 15, 20, 30, 40),
    "slow": (60, 90, 120, 150, 200),
    "momentum": (10, 20, 40, 60, 90),
    "threshold": (0.0, 0.02, 0.05, 0.10),
    "vol_target": (0.20, 0.35, 0.50, 0.75),
    "cap": (0.5, 0.75, 1.0),
}
WARMUP = 200


@dataclass(frozen=True)
class Bar:
    day: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def candidate_id(genes):
    validate_genes(genes)
    return hashlib.sha256(canonical(genes).encode()).hexdigest()[:20]


def validate_genes(genes):
    if set(genes) != set(DOMAINS):
        raise ValueError("Unknown or missing genes")
    if any(genes[k] not in values for k, values in DOMAINS.items()):
        raise ValueError("Gene outside the frozen domain")
    if genes["fast"] >= genes["slow"]:
        raise ValueError("Fast window must precede slow window")


def read_bars(raw: bytes, *, today=None):
    today = today or datetime.now(timezone.utc).date()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = ("date", "open", "high", "low", "close", "volume")
    if not set(required).issubset(reader.fieldnames or []):
        raise ValueError("Daily OHLCV columns required")
    bars = []
    previous = None
    for row in reader:
        day = date.fromisoformat(row["date"])
        if day.isoformat() != row["date"] or day >= today:
            raise ValueError("Only canonical closed UTC dates are allowed")
        if previous is not None and day != previous + timedelta(days=1):
            raise ValueError("Duplicate, unordered or missing daily bar")
        values = [float(row[k]) for k in required[1:]]
        o, h, low, c, volume = values
        if not all(math.isfinite(x) for x in values):
            raise ValueError("Non-finite OHLCV value")
        if min(o, h, low, c) <= 0 or volume < 0 or not low <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Invalid OHLCV range")
        bars.append(Bar(day.isoformat(), *values))
        previous = day
    if not bars:
        raise ValueError("Empty input")
    return bars


def target_weight(history, genes):
    """history contains only closes strictly before today's execution open."""
    if len(history) < WARMUP:
        raise ValueError("Insufficient warmup")
    fast = statistics.fmean(history[-genes["fast"]:])
    slow = statistics.fmean(history[-genes["slow"]:])
    momentum = history[-1] / history[-1 - genes["momentum"]] - 1
    if fast <= slow or momentum <= genes["threshold"]:
        return 0.0
    trailing = history[-31:]
    returns = [b / a - 1 for a, b in zip(trailing, trailing[1:])]
    vol = statistics.pstdev(returns) * math.sqrt(365.25)
    return min(genes["cap"], genes["vol_target"] / max(vol, 1e-12))


def metrics(curve, trades):
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    returns = []
    for row in curve:
        returns.append(row["equity"] / equity - 1)
        equity = row["equity"]
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    deviation = statistics.pstdev(returns)
    cagr = equity ** (365.25 / len(curve)) - 1
    return {
        "days": len(curve), "total_return": equity - 1, "cagr": cagr,
        "max_drawdown": drawdown,
        "sharpe": statistics.fmean(returns) / deviation * math.sqrt(365.25) if deviation else 0.0,
        "trade_count": len(trades), "cost_paid": sum(t["cost"] for t in trades),
        "turnover": sum(t["notional"] for t in trades),
        "exposed_days": sum(row["weight"] > 0 for row in curve),
        "fitness": cagr - 2 * abs(drawdown),
    }


def backtest(bars, genes, start, end, cost_bps, *, benchmark=False):
    """Fresh cash at each split. Fixed proportional fees + slippage in bps."""
    validate_genes(genes)
    if not math.isfinite(cost_bps) or not 0 <= cost_bps < 1000:
        raise ValueError("Invalid transaction costs")
    if start > end:
        raise ValueError("Invalid period")
    # Remove all later bars before computing features, including final holdout.
    visible = [bar for bar in bars if bar.day <= end]
    active = [bar for bar in visible if bar.day >= start]
    if not active or active[0].day != start or active[-1].day != end:
        raise ValueError("Input does not cover the complete period")
    history = [bar.close for bar in visible if bar.day < start]
    if len(history) < WARMUP:
        raise ValueError("Insufficient warmup before split")
    cash, units = 1.0, 0.0
    rate = cost_bps / 10000
    curve, trades = [], []
    for index, bar in enumerate(active):
        before = cash + units * bar.open
        old_weight = units * bar.open / before
        weight = 1.0 if benchmark else target_weight(history, genes)
        # Exact proportional-cost solution for target weight after costs.
        difference = weight - old_weight
        fee_fraction = rate * abs(difference) / (1 + rate * weight if difference >= 0 else 1 - rate * weight)
        cost = before * fee_fraction
        new_units = (before - cost) * weight / bar.open
        delta = new_units - units
        if abs(delta) > 1e-15:
            trades.append({"day": bar.day, "fill": "open", "side": "buy" if delta > 0 else "sell",
                           "price": bar.open, "units": abs(delta), "notional": abs(delta) * bar.open, "cost": cost})
        units = new_units
        cash = (before - cost) * (1 - weight)
        equity = cash + units * bar.close
        if index == len(active) - 1 and units:
            liquidation = units * bar.close
            closing_cost = liquidation * rate
            trades.append({"day": bar.day, "fill": "close", "side": "sell", "price": bar.close,
                           "units": units, "notional": liquidation, "cost": closing_cost})
            equity -= closing_cost
            cash, units = equity, 0.0
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("Invalid simulated equity")
        curve.append({"day": bar.day, "equity": equity, "weight": weight})
        history.append(bar.close)
    return {"metrics": metrics(curve, trades), "curve": curve, "trades": trades}


def cash_backtest(bars, start, end):
    """Zero-risk cash reference for judging whether trading added value."""
    active = [bar for bar in bars if start <= bar.day <= end]
    if not active or active[0].day != start or active[-1].day != end:
        raise ValueError("Input does not cover the complete period")
    curve = [{"day": bar.day, "equity": 1.0, "weight": 0.0} for bar in active]
    return {"metrics": metrics(curve, []), "curve": curve, "trades": []}
