"""Production route reconstruction using the unchanged, pinned decision rules.

Legacy adapter functions below calculate decision state only. None of their
same-day performance columns are exported. Performance is priced independently
from an availability-bound interval ledger, with explicit spot/funding proxies.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.production import causal_performance as causal
from scripts.production.route_identity import FIELDS, resolve_route, validate_target_identity
from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import (
    LIVE_PRODUCTION_STRATEGY_ID, LIVE_STRATEGY_VERSION,
)

CONTRACT = "source_of_truth/production_route_identity_contract.json"
BASE = "outputs/phase60_selective_restore_robustness/phase60_restore_trx_sol_base_paper.csv"
GOVERNANCE = "outputs/phase66g_production_candidate_live/phase66g_production_soft_filters_paper.csv"
TREND = "outputs/phase66g_production_candidate_live/phase66g_trend_barometer_history.csv"
ETF = "outputs/research_os/dev_only/non_authoritative_btc_etf_flow_daily_panel/btc_etf_flow_daily_panel.csv"
FRESHNESS = "outputs/execution/freshness/app_freshness_report.json"


def _read_frame(root, name):
    frame = pd.read_csv(root / name)
    date_column = "date" if "date" in frame else "ts"
    frame = frame.rename(columns={date_column: "date"})
    frame["date"] = pd.to_datetime(frame.date, errors="raise").dt.tz_localize(None)
    if frame.empty or frame.date.isna().any() or frame.date.duplicated().any():
        raise ValueError("Missing or duplicate source day: " + name)
    if not frame.date.is_monotonic_increasing:
        raise ValueError("Unordered source days: " + name)
    return frame


def _metadata(root, name):
    raw = (root / name).read_bytes()
    return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def build_route_inputs(root: Path):
    root = root.resolve()
    contract = json.loads((root / CONTRACT).read_text(encoding="utf-8"))
    if set(contract["required_fields"]) != set(FIELDS):
        raise ValueError("Route contract fields differ from implementation")
    base, governance, trend = (_read_frame(root, name) for name in (BASE, GOVERNANCE, TREND))
    closed = base.date.iloc[-1].strftime("%Y-%m-%d")
    if any(f.date.iloc[-1].strftime("%Y-%m-%d") != closed for f in (governance, trend)):
        raise ValueError("Production route source days disagree")
    lineage = governance.merge(base[["date", "selected"]].rename(columns={"selected": "base_economic_asset"}),
                               on="date", how="left", validate="one_to_one")
    lineage["base_economic_asset"] = lineage.base_economic_asset.map(causal.asset)
    lineage["candidate_asset"] = lineage.chosen_asset.fillna("CASH").replace("", "CASH").map(causal.asset)
    lineage["candidate_trigger_active"] = lineage.executed_regime.eq("CANDIDATE")
    lineage["economic_asset"] = causal.economic_assets(governance,
        base[["date", "selected"]].rename(columns={"selected": "base_asset"}))
    candidate_rows = lineage.candidate_trigger_active
    if not lineage.loc[candidate_rows, "economic_asset"].eq(lineage.loc[candidate_rows, "candidate_asset"]).all():
        raise ValueError("Triggered candidate return identity differs from weekly selection")
    needed = sorted(set(lineage.economic_asset) | set(lineage.base_economic_asset) | {"BTC"})
    needed = [a for a in needed if a != "CASH"]
    prices, files = {}, [CONTRACT, BASE, GOVERNANCE, TREND, ETF, FRESHNESS]
    for symbol in needed:
        name = f"data/ohlcv/{symbol}USDT_1d.csv"
        frame = _read_frame(root, name)
        frame = frame.loc[frame.date <= pd.Timestamp(closed)].set_index("date")
        if frame.empty or frame.index[-1].strftime("%Y-%m-%d") != closed:
            raise ValueError("Price data missing current closed day for " + symbol)
        if not np.isfinite(frame[["open", "close"]]).all().all() or (frame[["open", "close"]] <= 0).any().any():
            raise ValueError("Invalid source prices for " + symbol)
        prices[symbol] = frame
        files.append(name)
    freshness = json.loads((root / FRESHNESS).read_text(encoding="utf-8"))
    # The source producer owns freshness; the orchestrator also checks exact UTC day.
    freshness_day = freshness.get("latest_available_closed_utc_day") or freshness.get("target_closed_day_utc")
    if freshness_day and str(freshness_day)[:10] != closed:
        raise ValueError("Freshness source and route data day disagree")
    return {"root": root, "closed_day": closed, "base": base, "governance": governance,
            "lineage": lineage, "trend": trend, "prices": prices,
            "trend_status_row": {"next_rebalance_date": None},
            "files": {name: _metadata(root, name) for name in files}}


def _availability(root, signals):
    signals["signal_available_at"] = (pd.to_datetime(signals.signal_data_day, utc=True)
        + pd.Timedelta(days=1, hours=12)).astype(str)
    signals["availability_basis"] = "assumed_D_plus_1_12UTC_no_complete_historical_runtime_log"
    observed = {}
    for path in sorted((root / "outputs/execution/production_runs").glob("*/production_run_manifest.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        stage = run.get("stages", {}).get("VALIDATE_PRODUCTION_CORE", {})
        day, at = run.get("target_closed_day"), stage.get("finished_at")
        if day and at and stage.get("status") == "PASSED" and pd.Timestamp(at) > pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1):
            if day not in observed or pd.Timestamp(at) < pd.Timestamp(observed[day]):
                observed[day] = at
    for day, at in observed.items():
        mask = signals.signal_data_day.eq(day)
        signals.loc[mask, "signal_available_at"] = at
        signals.loc[mask, "availability_basis"] = "observed_original_validation_counterfactual_schedule"
    signals.loc[signals.index[-1], "signal_available_at"] = datetime.now(timezone.utc).isoformat()
    signals.loc[signals.index[-1], "availability_basis"] = "current_build_completion"


def _price_rows(inputs):
    result = []
    for symbol, frame in inputs["prices"].items():
        name = f"data/ohlcv/{symbol}USDT_1d.csv"
        for number, row in enumerate(frame.itertuples(), 2):
            result.append({"asset": symbol, "timestamp": row.Index, "price": row.open,
                           "source_file": name, "source_row": number, "source_column": "open"})
        result.append({"asset": symbol, "timestamp": frame.index[-1] + pd.Timedelta(days=1),
                       "price": frame.close.iloc[-1], "source_file": name,
                       "source_row": len(frame) + 1, "source_column": "close_terminal_valuation_only"})
    return pd.DataFrame(result)


def build_route_timeseries(inputs):
    root, lineage, prices = inputs["root"], inputs["lineage"], inputs["prices"]
    for path in (root, root / "scripts", root / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import phase68g_portfolio_exposure_leverage_validation as lev
    from approved_strategy_net_export_helper import NetCostExportConfig
    from scripts.production.strategy_adapters import phase68g_btc_persistence_10d_early_risk_075_adapter as persistence
    from scripts.production.strategy_adapters import phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter as etf
    from scripts.production.strategy_adapters.phase68g_66g_1p25x_candidate_adapter import Phase68g66g1p25xCandidateAdapter
    import dev_only_phase68g_etf_flow_impulse_probe as probe
    import dev_only_phase68g_etf_flow_impulse_cooldown_sensitivity as cooldown

    raw_returns = {a: f.close.pct_change() for a, f in prices.items()}
    gross = [0.0 if r.economic_asset == "CASH" else float(raw_returns[r.economic_asset].loc[r.date])
             for r in lineage.itertuples()]
    portfolio = pd.DataFrame({"date": lineage.date, "base_ret": gross,
                              "portfolio_held_asset": lineage.economic_asset,
                              "is_exposed": lineage.economic_asset.ne("CASH")})
    wrapped = lev.build_validation_wrapper(portfolio, inputs["trend"], pd.DataFrame(),
        lev.ValidationVariant("phase68g_66g_1p25x_candidate", 1.25), 0.12, 10.0, 0.10, 20, -0.08, -0.04)
    cfg = NetCostExportConfig(annual_borrow_cost=0.12, tradable_transition_slippage_bps=10.0,
                              taker_fee_bps=4.5, maker_fee_bps=1.5)
    benchmark = prices["BTC"][["close"]].reset_index().rename(columns={"close": "btc_close"})
    static = Phase68g66g1p25xCandidateAdapter().build_timeseries(
        {"paper_df": wrapped, "benchmark_df": benchmark, "config": cfg})
    pf, _, costs = persistence._prepare_baseline_frame_from_timeseries(static)
    pv = persistence._build_variant_state(pf, costs)
    durable = persistence._build_active_timeseries({"canonical_baseline_timeseries": static,
                                                  "selected_variant_frame": pv["selected_variant_frame"]})
    bf, _ = etf._normalize_baseline_frame_from_timeseries(durable)
    full = probe.build_full_history_frame(bf, probe.load_etf_panel(root / ETF),
                                         probe.load_btc_frame(root / "data/ohlcv/BTCUSDT_1d.csv"))
    state, _ = cooldown.build_cooldown_state_machine(full, 15)
    if state.index[-1].strftime("%Y-%m-%d") != inputs["closed_day"] or len(state) != len(lineage):
        raise ValueError("Decision-state history does not cover route sources")
    signals = pd.DataFrame({"signal_data_day": state.index.strftime("%Y-%m-%d"),
        "selected_asset": state.probe_held_asset.map(causal.asset).to_numpy(),
        "target_exposure": state.probe_effective_leverage.to_numpy(),
        "source_file": "outputs/production/current_strategy_timeseries.csv",
        "source_row": np.arange(len(state)) + 2})
    signals.loc[signals.selected_asset.eq("CASH"), "target_exposure"] = 0.0
    _availability(root, signals)
    routes = []
    by_day = lineage.set_index("date")
    for signal in signals.itertuples():
        source = by_day.loc[pd.Timestamp(signal.signal_data_day)]
        resolved = signal.selected_asset
        route = "CASH" if resolved == "CASH" else "BTC" if resolved == "BTC" else str(source.executed_regime)
        identity = resolve_route(route_type=route, base_economic_asset=source.base_economic_asset,
            candidate_asset=source.candidate_asset, candidate_trigger_active=bool(source.candidate_trigger_active),
            target_exposure=signal.target_exposure, signal_available_at=signal.signal_available_at)
        if identity["resolved_execution_asset"] != resolved:
            raise ValueError("Decision state changed route identity without a strategy rule")
        routes.append(identity)
    route_frame = pd.DataFrame(routes)
    price_rows = _price_rows(inputs)
    end = (pd.Timestamp(inputs["closed_day"]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    ledger = causal.build_ledger(signals, price_rows, start=signals.signal_data_day.iloc[0], end=end)
    frame = pd.DataFrame({"date": signals.signal_data_day})
    for name in FIELDS:
        frame[name] = route_frame[name]
    frame["source_governance_route"] = lineage.executed_regime.to_numpy()
    frame["route_source_file"] = GOVERNANCE
    frame["route_source_row"] = np.arange(len(frame)) + 2
    frame["base_source_file"] = BASE
    frame["base_source_row"] = [int(inputs["base"].index[inputs["base"].date.eq(d)][0]) + 2 for d in lineage.date]
    frame["source_route_economic_asset"] = lineage.economic_asset.to_numpy()
    frame["route_return_asset"] = frame.resolved_execution_asset
    frame["source_route_raw_price_return"] = gross
    for col in ["selected_asset", "actual_held_asset", "authorized_tradable_asset", "held_asset", "current_asset", "execution_target_asset"]:
        frame[col] = frame.resolved_execution_asset
    for col in ["effective_market_exposure", "current_exposure", "exposure", "execution_target_exposure", "model_candidate_exposure"]:
        frame[col] = signals.target_exposure
    for col in ["cash_day", "btc_day", "in_market", "trend_permission_active", "trend_gate_pass", "leverage_active"]:
        frame[col] = frame.resolved_execution_asset.eq("CASH") if col == "cash_day" else frame.resolved_execution_asset.eq("BTC") if col == "btc_day" else signals.target_exposure.gt(1) if col == "leverage_active" else signals.target_exposure.gt(0)
    frame["market_state"] = np.where(frame.cash_day, "CASH", "IN_MARKET")
    frame["regime"] = frame.route_type
    frame["execution_state"] = np.where(frame.cash_day, "cash", "risk_on")
    frame["trend_score"] = inputs["trend"].set_index("date").trend_score.reindex(state.index).fillna(0).to_numpy()
    frame["trend_state"] = np.where(frame.trend_score.gt(0), "positive", "non_positive")
    frame["buy_threshold"] = 0.0
    frame["trend_activation_threshold"] = 0.1
    frame["reason_code"] = frame.resolution_reason
    frame["leverage_state_reason"] = frame.resolution_reason
    for col in ["early_risk_active", "cooldown_blocked_entry", "etf_flow_feature_available", "etf_flow_rule_active", "etf_flow_causal_date_available"]:
        frame[col] = state[col].to_numpy() if col in state else False
    frame["trend_block_day"] = frame.cash_day & frame.trend_score.le(0)
    frame["stress_block_day"] = False
    frame["is_rebalance_day"] = frame.resolved_execution_asset.ne(frame.resolved_execution_asset.shift()) | signals.target_exposure.ne(signals.target_exposure.shift())
    frame["asset_transition_day"] = ledger.transition_flag
    frame["availability_basis"] = signals.availability_basis
    frame["performance_contract"] = "causal_execution_interval_ledger_v1"
    for name in ledger:
        if name != "date":
            frame["performance_" + name] = ledger[name]
    for name in ("return_net", "authorized_return_net", "model_candidate_return_net"):
        frame[name] = ledger.net_strategy_return
    for name in ("return_gross", "authorized_return_gross", "model_candidate_return_gross"):
        frame[name] = ledger.gross_strategy_return
    for name in ("equity", "authorized_equity", "model_candidate_equity"):
        frame[name] = ledger.model_equity
    frame["drawdown_pct"] = (frame.equity / frame.equity.cummax() - 1) * 100
    for name, ledger_name in [("fees", "fees"), ("slippage_cost", "slippage"), ("borrow_cost", "borrow"), ("funding", "funding")]:
        frame[name + "_daily"] = ledger[ledger_name]
        frame[name + "_cumulative"] = ledger[ledger_name].cumsum()
    frame["turnover"] = ledger.turnover
    chart = causal.model_chart(ledger, price_rows.loc[price_rows.asset.eq("BTC")])
    frame["btc_close"] = benchmark.set_index("date").btc_close.reindex(state.index).to_numpy()
    frame["btc_return"] = chart.btc_index.pct_change().fillna(chart.btc_index.iloc[0] - 1)
    frame["btc_baseline_index"] = chart.btc_index
    frame["btc_baseline_equity"] = chart.btc_index
    for window in (7, 30, 90):
        frame[f"rolling_return_{window}d"] = frame.equity.pct_change(window).fillna(0)
    frame["rolling_vol_30d"] = frame.return_net.rolling(30).std().fillna(0) * np.sqrt(365.25)
    frame["rolling_sharpe_90d"] = (frame.return_net.rolling(90).mean() / frame.return_net.rolling(90).std().replace(0, np.nan) * np.sqrt(365.25)).fillna(0)
    frame["strategy_id"], frame["strategy_version"] = LIVE_PRODUCTION_STRATEGY_ID, LIVE_STRATEGY_VERSION
    frame["source_validated"] = True
    # The current target is never retroactively placed into its own closed bar.
    frame.loc[frame.index[-1], "signal_available_at"] = datetime.now(timezone.utc).isoformat()
    return frame.copy()


class CausalRouteAdapter:
    strategy_id = LIVE_PRODUCTION_STRATEGY_ID
    strategy_version = LIVE_STRATEGY_VERSION
    adapter_name = "causal_route_identity_v1"
    route_identity_required = True
    load_inputs = staticmethod(lambda *, root: build_route_inputs(root))
    build_timeseries = staticmethod(build_route_timeseries)

    def build_source_inputs(self, inputs):
        assets = sorted(set(inputs["lineage"].economic_asset) | set(inputs["lineage"].base_economic_asset) | {"BTC", "CASH"})
        return {"adapter_name": self.adapter_name, "validated_closed_day": inputs["closed_day"],
            "files": inputs["files"], "route_identity_contract": CONTRACT,
            "performance_contract": "causal_execution_interval_ledger_v1",
            "performance_assumptions": "daily spot open proxy; historical availability partly assumed; funding 3bp/day proxy; no real account PnL",
            "current_emittable_universe": {"status": "available", "assets": assets,
                "source_kind": "resolved_strategy_routes_with_price_data", "closed_day": inputs["closed_day"],
                "strategy_version": self.strategy_version, "exchange_support": "evaluated_per_entry_against_current_metadata"}}

    def build_snapshot_metrics(self, inputs, timeseries):
        r = timeseries.return_net.to_numpy(dtype=float)
        equity = np.cumprod(1 + r)
        def cagr(values):
            return (np.prod(1 + values) ** (365.25 / len(values)) - 1) * 100 if len(values) else 0.0
        downside = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
        drawdown = equity / np.maximum.accumulate(np.r_[1., equity])[1:] - 1
        metrics = {"total_return_pct_net": round((equity[-1] - 1) * 100, 4),
            "cagr_pct_net": round(cagr(r), 4), "max_drawdown_pct_net": round(drawdown.min() * 100, 4),
            "sharpe": round(np.sqrt(365.25) * r.mean() / r.std(ddof=1), 4) if r.std(ddof=1) else 0.0,
            "sortino": round(np.sqrt(365.25) * r.mean() / downside, 4) if downside else 0.0,
            "cash_days_pct": round(timeseries.performance_executed_held_asset.eq("CASH").mean() * 100, 6),
            "btc_days_pct": round(timeseries.performance_executed_held_asset.eq("BTC").mean() * 100, 6),
            "trade_count": int(timeseries.asset_transition_day.sum()),
            "switch_count": int(timeseries.asset_transition_day.sum())}
        etf_rows = timeseries.etf_flow_feature_available.astype(bool)
        metrics["since_etf_start_cagr_pct"] = round(cagr(r[np.flatnonzero(etf_rows)[0]:]), 4) if etf_rows.any() else 0.0
        for year in (2023, 2025):
            metrics[f"since{year}_cagr_pct_net"] = round(cagr(r[timeseries.date.ge(f"{year}-01-01")]), 4)
        for dest, column in [("trading_fees", "fees_daily"), ("funding", "funding_daily"),
                             ("borrow_cost", "borrow_cost_daily"), ("slippage_cost", "slippage_cost_daily")]:
            metrics[dest + "_total_pct"] = round(float(timeseries[column].sum() * 100), 6)
        return metrics

    def build_reason_text(self, row):
        return f"ModelovĂ„â€šĂ‹ĹĄ cieÄ‚â€žĂ„Äľ {row['resolved_execution_asset']} pri expozĂ„â€šĂ‚Â­cii {float(row['execution_target_exposure']):g}Ă„â€šĂ˘â‚¬â€ť."

    def build_wait_condition(self, row, metrics):
        return {"code": "already_in_target_state", "text": self.build_reason_text(row),
                "current_values": {"target_asset": row["resolved_execution_asset"]},
                "target_condition": {"next_rebalance_date": None}}

    def build_decision_context(self, timeseries):
        from scripts.production.staged_candidate_promotion_support import build_promoted_decision_context
        context = build_promoted_decision_context(timeseries)
        context["current_reason_text"] = self.build_reason_text(timeseries.iloc[-1])
        return context

    def build_diagnostics_payload(self, *, generated_at_utc, inputs, timeseries, validation):
        reason = self.build_reason_text(timeseries.iloc[-1])
        return {"artifact_type": "current_strategy_diagnostics", "schema_version": 1,
            "generated_at_utc": generated_at_utc, "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version, "closed_day": inputs["closed_day"],
            "latest_state_explanation": reason, "current_flatline_explanation": reason,
            "current_cash_or_risk_reason": reason, "recent_regime_changes": [],
            "recent_rebalance_events": [], "current_cost_pressure": {},
            "current_fee_drag_summary": {}, "current_data_health_summary": {"status": "passed"},
            "strategy_improvement_signals": [], "validation": validation}


def validate_route_payloads(*, snapshot, timeseries, diagnostics, adapter, inputs):
    errors = []
    try:
        validate_target_identity(snapshot)
        if snapshot["closed_day"] != inputs["closed_day"] or timeseries.date.iloc[-1] != snapshot["closed_day"]:
            raise ValueError("Route export closed day mismatch")
        if snapshot["strategy_version"] != adapter.strategy_version or snapshot["strategy_id"] != adapter.strategy_id:
            raise ValueError("Route export strategy identity mismatch")
        if snapshot["source_inputs"] != adapter.build_source_inputs(inputs):
            raise ValueError("Route export input fingerprints changed")
        if diagnostics["closed_day"] != snapshot["closed_day"]:
            raise ValueError("Route diagnostics day mismatch")
        # Re-derive from price and strategy sources. This catches label replacement,
        # changed intervals, fake costs, missing rows, and same-day legacy returns.
        expected = adapter.build_timeseries(inputs)
        if len(expected) != len(timeseries):
            raise ValueError("Route export length mismatch")
        for name in expected:
            if name == "signal_available_at":
                left, right = expected[name].iloc[:-1], timeseries[name].iloc[:-1]
            else:
                left, right = expected[name], timeseries[name]
            if pd.api.types.is_numeric_dtype(left) and not pd.api.types.is_bool_dtype(left):
                same = np.allclose(left, right, equal_nan=True, atol=1e-10, rtol=1e-12)
            else:
                same = left.fillna("").astype(str).eq(right.fillna("").astype(str)).all()
            if not same:
                raise ValueError("Route export source derivation mismatch: " + name)
        for name in FIELDS:
            if snapshot[name] != timeseries.iloc[-1][name]:
                raise ValueError("Snapshot/timeseries route mismatch: " + name)
        available = pd.Timestamp(snapshot["signal_available_at"])
        if available.tzinfo is None or not pd.Timestamp(snapshot["closed_day"], tz="UTC") + pd.Timedelta(days=1) < available <= pd.Timestamp.now(tz="UTC"):
            raise ValueError("Current signal availability is not an observed post-close time")
        if snapshot["metrics"] != adapter.build_snapshot_metrics(inputs, timeseries):
            raise ValueError("Metrics do not derive from causal ledger")
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    return {"status": "failed" if errors else "passed", "errors": errors,
            "warnings": ["Historical daily performance is a causal price/funding proxy, not real account PnL."],
            "checks": {"route_identity": not errors, "causal_interval_rederivation": not errors}}
