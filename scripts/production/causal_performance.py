"""Pure model accounting. No runtime I/O, authority, account or execution imports.

Targets are decisions; holdings are established only at an available price.
Daily proxy bars use open-to-open intervals, never a same-day close decision.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

FORBIDDEN_ASSETS = {"BASE", "BASELINE", "CORE", "BASELINE_RISK", "CANDIDATE", "ALT", "", "NAN", "NONE", "NAT"}

@dataclass(frozen=True)
class Costs:
    fee_rate: float = 0.00045
    slippage_rate: float = 0.001
    annual_borrow: float = 0.12
    daily_funding_proxy: float = 0.0003

    def __post_init__(self):
        if any(not np.isfinite(x) or x < 0 for x in self.__dict__.values()):
            raise ValueError("Invalid cost rate")

def asset(value):
    name = str(value).strip().upper()
    if name.endswith("USDT"):
        name = name[:-4]
    if name in FORBIDDEN_ASSETS or not name.isalnum() or name.isnumeric():
        raise ValueError("Concrete economic asset required: " + name)
    return name

def economic_assets(governance, base_holdings):
    """BASE is a strategy route. Its holding comes from the same return interval.

    A weekly candidate does not replace a BASE holding when its trigger is off.
    Explicit joins reject ambiguous keys; ordering and column positions do not matter.
    """
    if governance.date.duplicated().any() or base_holdings.date.duplicated().any():
        raise ValueError("Duplicate lineage day")
    joined = governance.merge(base_holdings[["date", "base_asset"]], on="date", how="left", validate="one_to_one")
    result = []
    for row in joined.itertuples(index=False):
        regime = str(row.executed_regime).upper()
        if regime == "CASH":
            result.append("CASH")
        elif regime == "BTC":
            result.append("BTC")
        elif regime == "BASE":
            result.append(asset(row.base_asset))
        elif regime == "CANDIDATE":
            result.append(asset(row.executed_position))
        else:
            raise ValueError("Unknown economic route: " + regime)
    return pd.Series(result, index=governance.index)

def validate_signals(signals):
    required = {"signal_data_day", "signal_available_at", "selected_asset", "target_exposure", "source_file", "source_row"}
    if not required <= set(signals):
        raise ValueError("Missing signal lineage")
    s = signals.copy()
    s["signal_data_day"] = pd.to_datetime(s.signal_data_day, utc=True)
    s["signal_available_at"] = pd.to_datetime(s.signal_available_at, utc=True, format="ISO8601")
    if s.signal_data_day.duplicated().any() or s.signal_available_at.duplicated().any():
        raise ValueError("Duplicate signal keys")
    if s.signal_data_day.isna().any() or s.signal_available_at.isna().any():
        raise ValueError("Missing signal time")
    if (s.signal_available_at <= s.signal_data_day + pd.Timedelta(days=1)).any():
        raise ValueError("Signal must be available after data-day close")
    s["selected_asset"] = s.selected_asset.map(asset)
    exposure = pd.to_numeric(s.target_exposure, errors="raise")
    if (~np.isfinite(exposure)).any() or (exposure < 0).any():
        raise ValueError("Invalid exposure")
    if (s.selected_asset.eq("CASH") != exposure.eq(0)).any():
        raise ValueError("CASH/exposure mismatch")
    s = s.sort_values("signal_available_at").reset_index(drop=True)
    if not s.signal_data_day.is_monotonic_increasing:
        raise ValueError("Signal availability reverses data-day ordering")
    return s

def prepare_prices(prices):
    p = prices.copy()
    p["asset"] = p.asset.map(asset)
    p["timestamp"] = pd.to_datetime(p.timestamp, utc=True)
    if p.timestamp.isna().any() or p.duplicated(["asset", "timestamp"]).any():
        raise ValueError("Missing or duplicate price key")
    if (~np.isfinite(p.price)).any() or (p.price <= 0).any():
        raise ValueError("Invalid price")
    if p[["source_file", "source_row"]].isna().any().any():
        raise ValueError("Missing price provenance")
    return p.set_index(["asset", "timestamp"]).sort_index()

def build_ledger(signals, prices, *, start, end, costs=Costs()):
    """Evaluate daily intervals [start, end); end may be a terminal close mark.

    Funding is explicitly a friction proxy, charged on all held notional; legacy
    borrowing is retained as an additional conservative financing charge above 1x.
    No inference of actual account PnL or fills is performed.
    """
    s, p = validate_signals(signals), prepare_prices(prices)
    dates = pd.date_range(start, end, freq="D", tz="UTC")
    if len(dates) < 2 or dates[-1] != pd.Timestamp(end, tz="UTC"):
        raise ValueError("At least one complete daily interval required")
    rows, old_asset, old_exposure, cursor, current = [], "CASH", 0.0, 0, None
    previous_target = 0.0
    for t, finish in zip(dates[:-1], dates[1:]):
        while cursor < len(s) and s.iloc[cursor].signal_available_at <= t:
            current = s.iloc[cursor]
            cursor += 1
        held = "CASH" if current is None else current.selected_asset
        target_exposure = 0.0 if current is None else float(current.target_exposure)
        transition = held != old_asset or target_exposure != previous_target
        # Fixed units between target changes; do not silently rebalance daily for free.
        exposure = target_exposure if transition else old_exposure
        turnover = (abs(exposure-old_exposure) if held == old_asset else old_exposure+exposure) if transition else 0.0
        if held != "CASH":
            try:
                a, b = p.loc[(held,t)], p.loc[(held,finish)]
            except KeyError as exc:
                raise ValueError(f"Missing {held} execution interval {t} / {finish}") from exc
            pa, pb = float(a.price), float(b.price)
            raw = pb / pa - 1.0
            source_a, source_b, row_a, row_b = a.source_file, b.source_file, int(a.source_row), int(b.source_row)
        else:
            pa = pb = np.nan
            raw, source_a, source_b, row_a, row_b = 0.0, "", "", 0, 0
        # An exit also needs a price for the old economic asset, not the new one.
        exit_price = np.nan
        exit_file, exit_row = "", 0
        if transition and old_asset != "CASH":
            try:
                old = p.loc[(old_asset,t)]
            except KeyError as exc:
                raise ValueError("Missing exit price for " + old_asset) from exc
            exit_price, exit_file, exit_row = float(old.price), old.source_file, int(old.source_row)
        fees, slip = turnover*costs.fee_rate, turnover*costs.slippage_rate
        borrow = max(exposure-1,0)*costs.annual_borrow/365.25
        funding = exposure*costs.daily_funding_proxy
        gross = exposure*raw
        net = gross-fees-slip-borrow-funding
        if net <= -1:
            raise ValueError("Model insolvent; no clipping permitted")
        rows.append({"date": t.strftime("%Y-%m-%d"),
                     "signal_data_day": "" if current is None else current.signal_data_day.strftime("%Y-%m-%d"),
                     "signal_available_at": "" if current is None else current.signal_available_at.isoformat(),
                     "availability_basis": "initial_cash" if current is None else current.get("availability_basis", "provided"),
                     "execution_assumption": "Binance spot daily open proxy; first observed open after signal availability; not Hyperliquid fill",
                     "return_interval_start": t.isoformat(), "return_interval_end": finish.isoformat(),
                     "previous_held_asset": old_asset, "previous_exposure": old_exposure,
                     "selected_asset": held, "executed_held_asset": held, "exposure": exposure,
                     "target_exposure": target_exposure,
                     "source_price_start": pa, "source_price_end": pb,
                     "price_source_file_start": source_a, "price_source_file_end": source_b,
                     "price_source_row_start": row_a, "price_source_row_end": row_b,
                     "price_source_column_start": "" if held == "CASH" else a.get("source_column", "price"),
                     "price_source_column_end": "" if held == "CASH" else b.get("source_column", "price"),
                     "raw_asset_return": raw, "gross_strategy_return": gross,
                     "fees": fees, "slippage": slip, "borrow": borrow, "funding": funding,
                     "funding_source": "fixed_3bp_per_day_full_notional_proxy_not_observed",
                     "net_strategy_return": net, "transition_flag": transition, "turnover": turnover,
                     "exit_price": exit_price, "exit_source_file": exit_file, "exit_source_row": exit_row,
                     "source_file": "initial_cash" if current is None else current.source_file,
                     "source_row": 0 if current is None else int(current.source_row)})
        old_asset, old_exposure = held, exposure*(1+raw)/(1+net)
        previous_target = target_exposure
    out = pd.DataFrame(rows)
    out["model_equity"] = (1+out.net_strategy_return).cumprod()
    validate_ledger(out)
    return out

def validate_ledger(frame):
    if frame.empty:
        raise ValueError("Empty model ledger")
    numeric = frame[["exposure", "gross_strategy_return", "net_strategy_return", "fees", "slippage", "borrow", "funding"]]
    if not np.isfinite(numeric.to_numpy()).all() or (frame.exposure < 0).any():
        raise ValueError("Invalid ledger number")
    active = frame.exposure > 0
    frame.executed_held_asset.map(asset)
    if (frame.loc[active,"executed_held_asset"] == "CASH").any():
        raise ValueError("CASH PnL exposure")
    available = pd.to_datetime(frame.signal_available_at, utc=True, errors="coerce")
    if available[active].isna().any():
        raise ValueError("Missing active signal availability")
    active_prices = frame.loc[active, ["source_price_start", "source_price_end"]]
    if not np.isfinite(active_prices.to_numpy()).all() or (active_prices <= 0).any().any():
        raise ValueError("Missing active source price")
    if (pd.to_datetime(frame.return_interval_start, utc=True)[active] < available[active]).any():
        raise ValueError("PnL before signal availability")
    expected = frame.exposure * (frame.source_price_end/frame.source_price_start-1).fillna(0)
    if not np.allclose(expected,frame.gross_strategy_return,rtol=1e-12,atol=1e-12):
        raise ValueError("Gross not explained by prices and exposure")
    costs = frame[["fees","slippage","borrow","funding"]].sum(axis=1)
    if not np.allclose(frame.gross_strategy_return-costs,frame.net_strategy_return,rtol=1e-12,atol=1e-12):
        raise ValueError("Costs do not reconcile")
    if ((~frame.transition_flag) & ((frame.fees != 0) | (frame.slippage != 0))).any():
        raise ValueError("Transition costs without executed change")

def model_chart(ledger, btc_prices):
    validate_ledger(ledger)
    price = prepare_prices(btc_prices)
    start = pd.Timestamp(ledger.return_interval_start.iloc[0])
    anchor = float(price.loc[("BTC",start)].price)
    ends = pd.to_datetime(ledger.return_interval_end,utc=True)
    return pd.DataFrame({"date": ends.dt.strftime("%Y-%m-%d"),
                         "model_index": (1+ledger.net_strategy_return).cumprod(),
                         "btc_index": [float(price.loc[("BTC",t)].price)/anchor for t in ends],
                         "model_authorized_exposure_x": ledger.exposure,
                         "model_authorized_return_net": ledger.net_strategy_return,
                         "model_authorized_return_gross": ledger.gross_strategy_return,
                         "model_transition_cost": ledger.fees+ledger.slippage,
                         "model_asset_transition_day": ledger.transition_flag})

def account_chart(exchange_ledger):
    if exchange_ledger.get("ledger_type") != "exchange_native_real_account":
        raise ValueError("Exchange-native account ledger required")
    rows = pd.DataFrame(exchange_ledger["rows"])
    if not {"date","cash_flow_adjusted_return"} <= set(rows):
        raise ValueError("Account return evidence required")
    return pd.DataFrame({"date": rows.date,
                         "real_account_index": (1+rows.cash_flow_adjusted_return).cumprod()})
