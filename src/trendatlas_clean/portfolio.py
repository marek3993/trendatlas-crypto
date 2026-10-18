"""Pure portfolio reconciliation. No credentials, network, or exchange mutations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import math
import re


def number(value, name: str = "number") -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"INVALID_{name.upper()}") from exc
    if not math.isfinite(result):
        raise ValueError(f"NONFINITE_{name.upper()}")
    return result


@dataclass(frozen=True)
class Policy:
    maker_wait_seconds: float = 300
    poll_seconds: float = 5
    max_slippage_bps: float = 50
    minimum_notional_usd: float = 10
    tolerance_fraction: float = 0.01
    fee_reserve_bps: float = 10
    max_rebalance_rounds: int = 3

    def __post_init__(self):
        for k, v in asdict(self).items():
            if number(v, k) < 0:
                raise ValueError(f"NEGATIVE_{k.upper()}")
        if self.poll_seconds <= 0 or self.max_rebalance_rounds < 1 or self.max_rebalance_rounds > 20:
            raise ValueError("INVALID_EXECUTION_POLL_OR_ROUNDS")
        if not 0 < self.tolerance_fraction < 0.1 or self.max_slippage_bps > 500:
            raise ValueError("INVALID_EXECUTION_TOLERANCE_OR_SLIPPAGE")


@dataclass(frozen=True)
class Market:
    key: str
    logical: str
    venue: str
    coin: str
    asset_id: int
    size_decimals: int
    mark: float
    entry_available: bool = True
    token_index: int | None = None
    unit_multiplier: int = 1

    def __post_init__(self):
        if self.venue not in {"spot", "perp"} or self.logical == "BASE":
            raise ValueError("INVALID_MARKET_VENUE_OR_ASSET")
        if self.asset_id < 0 or not 0 <= self.size_decimals <= 8 or number(self.mark, "mark") <= 0:
            raise ValueError("INVALID_MARKET_METADATA")


@dataclass
class Catalog:
    markets: dict[str, Market]
    routes: dict[str, str]

    def target(self, logical: str) -> Market | None:
        key = self.routes.get(logical)
        return self.markets.get(key) if key else None


@dataclass(frozen=True)
class Position:
    market_key: str
    quantity: float
    mark: float
    logical: str
    venue: str
    leverage: int | None = None


@dataclass
class Account:
    equity: float
    positions: dict[str, Position]
    spot_cash_free: float
    perp_margin_free: float
    abstraction: str = "unifiedAccount"
    open_orders: list[dict] = field(default_factory=list)
    entry_blockers: list[str] = field(default_factory=list)
    as_of_utc: str = ""


@dataclass(frozen=True)
class Trade:
    phase: str
    market_key: str
    logical: str
    side: str
    quantity: float
    reduce_only: bool
    reference_price: float
    target_quantity: float

    @property
    def notional(self):
        return self.quantity * self.reference_price


@dataclass
class Plan:
    exits: list[Trade]
    entries: list[Trade]
    targets: dict[str, float]
    entry_blockers: list[str]
    exit_blockers: list[str]
    dust: list[dict]
    equity: float
    target_nav_after_cost_reserve: float

    def public(self):
        return asdict(self)


def normalized_weights(raw: dict) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("MISSING_TARGET_WEIGHTS")
    result = {}
    for coin, value in raw.items():
        if not isinstance(coin, str) or not re.fullmatch(r"[A-Z0-9]+", coin) or coin == "BASE":
            raise ValueError("INVALID_TARGET_ASSET_OR_BASE")
        w = number(value, "weight")
        if w < 0:
            raise ValueError("NEGATIVE_TARGET_WEIGHT")
        if w:
            result[coin] = w
    if sum(result.values()) > 1 + 1e-12:
        raise ValueError("TARGET_EXCEEDS_ONE_X")
    return {c: w for c, w in result.items() if c != "CASH"}


def size_down(quantity: float, decimals: int) -> float:
    if quantity < 0 or not math.isfinite(quantity):
        raise ValueError("INVALID_ORDER_SIZE")
    return float(Decimal(str(quantity)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN))


def order_price(raw: float, market: Market, *, round_up: bool) -> float:
    d = Decimal(str(number(raw, "order_price")))
    if d <= 0:
        raise ValueError("NONPOSITIVE_ORDER_PRICE")
    if d == d.to_integral_value():
        return float(d)
    decimal_quantum = Decimal(1).scaleb(-max(0, (8 if market.venue == "spot" else 6) - market.size_decimals))
    significant_quantum = Decimal(1).scaleb(d.adjusted() - 4)
    quantum = max(decimal_quantum, significant_quantum)
    return float(d.quantize(quantum, rounding=ROUND_UP if round_up else ROUND_DOWN))


def plan(weights: dict, account: Account, catalog: Catalog, policy: Policy = Policy()) -> Plan:
    """Missing ENTRY dependencies do not erase or invalidate independent EXITs."""
    weights = normalized_weights(weights)
    equity = number(account.equity, "account_equity")
    if equity <= 0:
        raise ValueError("NONPOSITIVE_ACCOUNT_EQUITY")
    entry_blockers = list(account.entry_blockers)
    desired_routes = {}
    for logical, w in sorted(weights.items()):
        market = catalog.target(logical)
        if market is None or not market.entry_available:
            entry_blockers.append(f"MARKET_UNAVAILABLE:{logical}")
            continue
        desired_routes[market.key] = w
    # Reserve costs against post-trade NAV, rather than silently adding leverage
    # to a nominal 1x portfolio. Signal weights themselves are never changed.
    reserve_rate = (policy.fee_reserve_bps + policy.max_slippage_bps) / 10000
    nav = equity
    for _ in range(20):
        turnover = 0.0
        for key in set(account.positions) | set(desired_routes):
            p = account.positions.get(key)
            current = p.quantity * p.mark if p else 0.0
            turnover += abs(desired_routes.get(key, 0) * nav - current)
        new_nav = max(0, equity - turnover * reserve_rate)
        if abs(new_nav - nav) < 1e-10:
            nav = new_nav
            break
        nav = new_nav
    targets = {key: w * nav for key, w in desired_routes.items()}
    exits, entries, exit_blockers, dust = [], [], [], []
    tolerance = max(0.01, equity * policy.tolerance_fraction)
    for key in sorted(set(account.positions) | set(targets)):
        pos = account.positions.get(key)
        market = catalog.markets.get(key)
        current_qty = number(pos.quantity, "position_quantity") if pos else 0.0
        if market is None:
            if current_qty:
                exit_blockers.append(f"EXIT_MARKET_UNAVAILABLE:{key}")
            continue
        desired_qty = size_down(targets.get(key, 0) / market.mark, market.size_decimals)
        if current_qty < 0:
            quantity, side, phase = abs(current_qty), "BUY", "EXIT"
        else:
            delta = desired_qty - current_qty
            # Fully close an unwanted coin even if its notional is below the
            # percentage tolerance (perp reduce-only closure may be below $10).
            closing = desired_qty == 0 and current_qty > 0
            if not closing and abs(delta * market.mark) <= tolerance:
                continue
            quantity, side, phase = abs(delta), "BUY" if delta > 0 else "SELL", "ENTRY" if delta > 0 else "EXIT"
        qty = size_down(quantity, market.size_decimals)
        reduce_only = phase == "EXIT" and market.venue == "perp"
        if qty <= 0 or (qty * market.mark < policy.minimum_notional_usd and not reduce_only):
            dust.append({"market_key": key, "logical": market.logical, "phase": phase, "quantity": quantity,
                         "notional_usd": quantity * market.mark, "reason": "EXCHANGE_MINIMUM_OR_PRECISION"})
            continue
        trade = Trade(phase, key, market.logical, side, qty, reduce_only, market.mark, desired_qty)
        (exits if phase == "EXIT" else entries).append(trade)
    return Plan(exits, entries, targets, sorted(set(entry_blockers)), sorted(set(exit_blockers)), dust, equity, nav)


def reconcile(weights: dict, account: Account, catalog: Catalog, policy: Policy = Policy()) -> dict:
    p = plan(weights, account, catalog, policy)
    leverage_errors = [k for k, pos in account.positions.items()
                       if pos.quantity and pos.venue == "perp" and k in p.targets and pos.leverage != 1]
    unresolved = bool(p.exits or p.entries or p.exit_blockers or p.entry_blockers or leverage_errors)
    if p.dust:
        # Dust is explicitly visible, never falsely published as a zero position.
        status = "ALIGNED_WITH_EXCHANGE_DUST" if not unresolved else "NOT_ALIGNED"
    else:
        status = "ALIGNED" if not unresolved else "NOT_ALIGNED"
    gross = sum(abs(p.quantity * p.mark) for p in account.positions.values()) / account.equity
    return {"status": status, "aligned": not unresolved, "actual_gross_exposure": gross,
            "equity_usd": account.equity, "actual_positions": {k: asdict(v) for k, v in account.positions.items() if v.quantity},
            "unexecuted_dust": p.dust, "entry_blockers": p.entry_blockers, "exit_blockers": p.exit_blockers,
            "leverage_errors": leverage_errors, "remaining_exits": [asdict(t) for t in p.exits],
            "remaining_entries": [asdict(t) for t in p.entries]}
