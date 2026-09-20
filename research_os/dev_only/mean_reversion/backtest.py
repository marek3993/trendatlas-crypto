"""Close-only decisions, next-open fills, no additions while holding BTC."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics

from research_os.dev_only.evolution.backtest import Bar, canonical, metrics, read_bars

STUDY_PATH = Path(__file__).with_name("study.json")
DOMAINS = json.loads(STUDY_PATH.read_text(encoding="utf-8"))["domains"]


def validate_genes(genes):
    if set(genes) != set(DOMAINS) or any(genes[k] not in v for k, v in DOMAINS.items()):
        raise ValueError("Genes do not match the preregistered domains")


def candidate_id(genes):
    validate_genes(genes)
    return hashlib.sha256(canonical(genes).encode()).hexdigest()


def signal(history, genes):
    """history ends at close D; caller can execute only at open D+1."""
    if len(history) < 200:
        raise ValueError("All candidates require 200 completed warmup days")
    short = history[-genes["mean_window"]:]
    mean = statistics.fmean(short)
    sd = statistics.pstdev(short)
    regime = statistics.fmean(history[-genes["regime_window"]:])
    range_allowed = abs(mean / regime - 1) <= genes["range_band"]
    regime_allowed = history[-1] >= regime * (1 - genes["downtrend_floor"])
    oversold = sd > 0 and history[-1] <= mean - genes["entry_z"] * sd
    return {"mean": mean, "sd": sd, "regime_mean": regime,
            "range_allowed": range_allowed, "regime_allowed": regime_allowed,
            "oversold": oversold, "enter": oversold and range_allowed and regime_allowed}


def turnover_disqualified(annualized_turnover):
    return annualized_turnover > 24.0


def backtest(bars, genes, start, end, *, benchmark=None):
    validate_genes(genes)
    if benchmark not in (None, "cash", "btc"):
        raise ValueError("Unknown benchmark")
    visible = [b for b in bars if b.day <= end]
    active = [b for b in visible if b.day >= start]
    history = [b.close for b in visible if b.day < start]
    if len(active) < 2 or active[0].day != start or active[-1].day != end or len(history) < 200:
        raise ValueError("Incomplete fold or warmup")
    previous_day = next(b.day for b in reversed(visible) if b.day < start)
    cash, units, held_closes = 1.0, 0.0, 0
    next_signal_index = -1
    curve, trades = [], []
    rate = 15 / 10000

    def record(bar, side, notional, before, reason):
        trade = {"signal_day": previous_day, "day": bar.day, "fill": "open",
                 "side": side, "reason": reason, "price": bar.open,
                 "units": notional / bar.open, "notional": notional,
                 "equity_before": before, "cost": notional * rate,
                 "turnover_fraction": notional / before, "held_closes": held_closes}
        trades.append(trade)

    for index, bar in enumerate(active):
        before = cash + units * bar.open
        boundary = index == len(active) - 1
        evidence = signal(history, genes) if benchmark is None else None
        if units:
            reason = None
            if boundary:
                reason = "fold_boundary"
            elif benchmark is None and history[-1] >= evidence["mean"]:
                reason = "mean_reversion"
            elif benchmark is None and held_closes >= genes["max_hold"]:
                reason = "max_hold"
            if reason:
                notional = units * bar.open
                record(bar, "sell", notional, before, reason)
                cash += notional * (1 - rate)
                units, held_closes = 0.0, 0
                next_signal_index = index + genes["cooldown"]
            elif benchmark is None:
                # Fixed risk-only execution sizing. Never increase existing units.
                cap = genes["exposure_cap"]
                excess = units * bar.open - cap * before
                if excess > 1e-12:
                    notional = excess / (1 - cap * rate)
                    record(bar, "sell", notional, before, "exposure_cap")
                    cash += notional * (1 - rate)
                    units -= notional / bar.open
        elif not boundary and benchmark != "cash":
            allowed = benchmark == "btc" or (index - 1 >= next_signal_index and evidence["enter"])
            if allowed:
                cap = 1.0 if benchmark == "btc" else genes["exposure_cap"]
                notional = cap * before / (1 + cap * rate)
                record(bar, "buy", notional, before, "entry")
                units = notional / bar.open
                cash -= notional * (1 + rate)
                held_closes = 0
        opening_equity = cash + units * bar.open
        opening_weight = units * bar.open / opening_equity
        if benchmark is None and opening_weight > genes["exposure_cap"] + 1e-10:
            raise ArithmeticError("Opening exposure exceeded its cap")
        if cash < -1e-12 or units < -1e-12:
            raise ArithmeticError("Borrowing or short position is forbidden")
        equity = cash + units * bar.close
        close_weight = units * bar.close / equity
        curve.append({"day": bar.day, "equity": equity, "weight": opening_weight,
                      "close_weight": close_weight, "units": units, "cash": cash})
        if units:
            held_closes += 1
        history.append(bar.close)
        previous_day = bar.day
    measured = metrics(curve, trades)
    gross_turnover = sum(t["turnover_fraction"] for t in trades)
    annualized = gross_turnover * 365.25 / len(active)
    measured.update(gross_equity_normalized_turnover=gross_turnover,
                    annualized_turnover=annualized,
                    turnover_disqualified=turnover_disqualified(annualized),
                    max_opening_exposure=max(r["weight"] for r in curve),
                    max_close_exposure=max(r["close_weight"] for r in curve),
                    entries=sum(t["side"] == "buy" for t in trades),
                    data_role="development_retrospective_only")
    return {"metrics": measured, "curve": curve, "trades": trades}
