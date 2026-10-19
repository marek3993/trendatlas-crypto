"""One dated, checksum-bound publication. Never consumes legacy model or wallet metrics."""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .backtest import Costs, metrics, replay
from .core import STRATEGY_ID, price_returns, target_weights
from .data import Panel
from .fetch_data import _atomic_bytes

START = "2021-01-01"

def build_public(panel: Panel, universe: dict) -> tuple[dict, pd.DataFrame]:
    weights = target_weights(panel.close, panel.quote_volume)
    ledger = replay(panel, weights).loc[START:]
    if ledger.empty or not ledger.index.equals(pd.date_range(START, ledger.index[-1], freq="D")) or ledger.invalid_return_or_nav.any():
        raise ValueError("CLEAN_PUBLIC_HISTORY_INCOMPLETE")
    btc = price_returns(panel.close)["BTC"].reindex(ledger.index)
    if btc.isna().any():
        raise ValueError("BTC_BENCHMARK_INCOMPLETE")
    series = ledger.copy()
    series["clean_equity"] = (1 + series.net_return).cumprod()
    series["btc_return"] = btc
    series["btc_equity"] = (1 + btc).cumprod()
    series["date"] = series.index.strftime("%Y-%m-%d")
    label = lambda row: ";".join(f"{c}={w:.4f}" for c, w in sorted(row.items()) if w > 1e-12) or "CASH"
    decided = weights.reindex(ledger.index).fillna(0.0)
    series["target_weights"] = decided.apply(label, axis=1)
    series["held_weights"] = weights.shift(1).reindex(ledger.index).fillna(0.0).apply(label, axis=1)
    c = panel.close["BTC"].ffill(limit=3)
    series["btc_trend"] = (sum(np.sign(c / c.shift(L) - 1.0) for L in (20, 40, 80, 160)) / 4).reindex(ledger.index)
    annual = []
    for year, part in ledger.groupby(ledger.index.year):
        annual.append({"year": int(year), "return_pct": metrics(part)["total_return_pct"],
                       "btc_return_pct": float(((1 + btc.reindex(part.index)).prod() - 1) * 100),
                       "partial_year": str(part.index[-1].date()) != f"{year}-12-31"})
    last = ledger.loc[ledger.index[-1] - pd.DateOffset(years=1) + pd.Timedelta(days=1):]
    result = {"schema_version": 1, "strategy_id": STRATEGY_ID, "kind": "HISTORICAL_BACKTEST_AFTER_COSTS",
              "window": {"start": START, "end": str(ledger.index[-1].date()), "days": len(ledger)},
              "since_2021": metrics(ledger), "last_12_months": metrics(last),
              "btc_last_12_months_pct": float(((1 + btc.reindex(last.index)).prod() - 1) * 100),
              "cash_days_pct": float(ledger.cash_weight.eq(1).mean() * 100), "annual": annual,
              "costs": asdict(Costs()), "maker_fraction_assumption": 0.7,
              "cost_accounting": "daily drift rebalancing, post-cost NAV reserve; not only target-weight changes",
              "funding_source": "Binance observed; missing days explicitly use BTC/default proxy",
              "universe": universe, "input_sha256": panel.input_sha256,
              "parameter_provenance": "fixed_user_supplied_parameters; historical results already inspected; no untouched OOS claim",
              "real_account_pnl": False}
    return result, series.reset_index(drop=True)

def publish_public(panel: Panel, universe: dict, state_dir: Path) -> dict:
    result, series = build_public(panel, universe)
    body = series.to_csv(index=False, float_format="%.17g").encode()
    result["timeseries_sha256"] = hashlib.sha256(body).hexdigest()
    # JSON is the commit marker. Readers verify the CSV hash, so a crash cannot mix versions.
    _atomic_bytes(state_dir / "clean5050_timeseries.csv", body)
    _atomic_bytes(state_dir / "clean5050_metrics.json", json.dumps(result, indent=2, allow_nan=False).encode()+b"\n")
    return result
