from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


CASH_ASSETS = {"", "CASH", "USD", "USDC", "USDT", "NONE", "OUT_OF_MARKET"}
TERMINAL_EXCHANGE_STATES = {
    "filled",
    "canceled",
    "cancelled",
    "rejected",
    "margincanceled",
    "margincancelled",
    "margin_canceled",
    "ioc_canceled",
    "ioc_cancelled",
    "mintradentlrejected",
    "perpmarginrejected",
    "reduceonlyrejected",
}
FINAL_JOURNAL_STATES = {
    "FILLED_AND_ALIGNED",
    "FILLED_WITH_RESIDUAL",
    "PARTIAL",
    "REJECTED",
    "UNCERTAIN",
    "NO_ACTION",
    "BLOCKED",
    "EXITED_ENTRY_FAILED_STAYING_CASH",
    "ENTRY_FAILED_STAYING_CASH",
}


class ExecutionSafetyError(RuntimeError):
    def __init__(self, reasons: list[str] | str) -> None:
        self.reasons = reasons if isinstance(reasons, list) else [reasons]
        super().__init__(" | ".join(self.reasons))


class ExchangeAdapter(Protocol):
    def query_order_by_cloid(self, cloid: str) -> dict[str, Any]: ...

    def submit_ioc_order(self, step: Mapping[str, Any]) -> dict[str, Any]: ...

    def cancel_order(self, order: Mapping[str, Any]) -> dict[str, Any]: ...


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def valid_asset_symbol(value: Any) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9._:/-]{0,63}", normalize_asset(value)))


def is_cash(value: Any) -> bool:
    return normalize_asset(value) in CASH_ASSETS


def as_float(value: Any, *, field: str) -> float:
    try:
        result = float(str(value))
    except Exception as exc:
        raise ExecutionSafetyError(f"invalid_numeric:{field}") from exc
    if not math.isfinite(result):
        raise ExecutionSafetyError(f"non_finite_numeric:{field}")
    return result


def parse_utc(value: Any, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ExecutionSafetyError(f"missing_timestamp:{field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExecutionSafetyError(f"invalid_timestamp:{field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deterministic_execution_id(
    *,
    signal_id: str,
    target_asset: str,
    target_exposure: float,
    transition_identity: Mapping[str, Any],
) -> str:
    payload = {
        "signal_id": str(signal_id).strip(),
        "target_asset": normalize_asset(target_asset),
        "target_exposure": format(float(target_exposure), ".12g"),
        "transition_identity": transition_identity,
    }
    return f"exec_{canonical_json_hash(payload)[:32]}"


def deterministic_cloid(execution_id: str, step_index: int) -> str:
    # Hyperliquid accepts a 128-bit client order id encoded as 0x + 32 hex chars.
    return "0x" + hashlib.sha256(f"{execution_id}:{step_index}".encode("utf-8")).hexdigest()[:32]


def snapshot_summary(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = snapshot.get("summary")
    return summary if isinstance(summary, Mapping) else snapshot


def account_abstraction(snapshot: Mapping[str, Any]) -> str:
    summary = snapshot_summary(snapshot)
    value = summary.get("account_abstraction") or snapshot.get("account_abstraction")
    return str(value or "").strip()


def account_equity_and_available(snapshot: Mapping[str, Any]) -> tuple[float, float, str]:
    summary = snapshot_summary(snapshot)
    abstraction = account_abstraction(snapshot)
    normalized_abstraction = abstraction.lower()
    if normalized_abstraction in {"unifiedaccount", "portfoliomargin"}:
        equity_value = summary.get("spot_stable_total_usd")
        available_value = summary.get("spot_stable_available_usd")
        source = f"{abstraction}_spot_stable"
    else:
        equity_value = summary.get("perp_account_value")
        available_value = summary.get("perp_withdrawable")
        source = "perp_clearinghouse"
    equity = as_float(equity_value, field="account_equity_usd")
    try:
        available = as_float(available_value, field="available_balance_usd") if available_value is not None else 0.0
    except ExecutionSafetyError:
        available = 0.0  # Unknown ENTRY capacity never prevents reducing risk.
    if equity <= 0:
        raise ExecutionSafetyError("account_equity_not_positive")
    return equity, max(available, 0.0), source


def extract_positions(snapshot: Mapping[str, Any], mids: Mapping[str, float]) -> list[dict[str, Any]]:
    raw = snapshot.get("raw")
    if not isinstance(raw, Mapping):
        raise ExecutionSafetyError("account_raw_state_missing_or_invalid")
    clearinghouse = raw.get("clearinghouseState")
    if not isinstance(clearinghouse, Mapping):
        raise ExecutionSafetyError("account_clearinghouse_state_missing_or_invalid")
    raw_positions = clearinghouse.get("assetPositions")
    if not isinstance(raw_positions, list):
        raise ExecutionSafetyError("account_positions_missing_or_invalid")
    positions: list[dict[str, Any]] = []
    seen_assets: set[str] = set()
    for item in raw_positions:
        if not isinstance(item, Mapping) or not isinstance(item.get("position"), Mapping):
            raise ExecutionSafetyError("account_position_row_invalid")
        position = item["position"]
        raw_asset = position.get("coin")
        asset = normalize_asset(raw_asset)
        if not isinstance(raw_asset, str) or not valid_asset_symbol(asset) or is_cash(asset):
            raise ExecutionSafetyError("account_position_symbol_invalid")
        if asset in seen_assets:
            raise ExecutionSafetyError(f"account_position_duplicate:{asset}")
        seen_assets.add(asset)
        if "szi" not in position:
            raise ExecutionSafetyError(f"account_position_size_missing:{asset}")
        size = as_float(position["szi"], field=f"position.{asset}.size")
        if size == 0:
            continue
        raw_value = position.get("positionValue")
        # An unavailable ENTRY market must not prevent decoding existing exits.
        reference_price = as_float(mids.get(asset, 0), field=f"mids.{asset}")
        notional_abs = (
            abs(as_float(raw_value, field=f"position.{asset}.positionValue"))
            if raw_value is not None
            else abs(size) * reference_price
        )
        positions.append(
            {
                "asset": asset,
                "size": size,
                "notional_usd": math.copysign(notional_abs, size),
                "reference_price": reference_price,
                "raw": item,
            }
        )
    return positions


def _quantize_size(notional: float, price: float, decimals: int) -> float:
    if price <= 0 or notional <= 0:
        return 0.0
    step = Decimal("1").scaleb(-int(decimals))
    size = (Decimal(str(notional)) / Decimal(str(price))).quantize(step, rounding=ROUND_DOWN)
    return float(size)


def _step(
    *,
    execution_id: str,
    step_index: int,
    asset: str,
    side: str,
    delta_notional: float,
    reference_price: float,
    size_decimals: int,
    slippage_bps: float,
    reduce_only: bool,
    exact_quantity: float | None = None,
) -> dict[str, Any]:
    is_buy = side == "BUY"
    adjusted_price = reference_price * (
        1 + slippage_bps / 10_000 if is_buy else 1 - slippage_bps / 10_000
    )
    limit_price = round(float(f"{adjusted_price:.5g}"), max(0, 6 - int(size_decimals)))
    # Quantity represents the strategy notional at the fresh reference mid. The
    # limit price is only a slippage guard and must not silently undersize target.
    quantity = abs(exact_quantity) if exact_quantity is not None else _quantize_size(abs(delta_notional), reference_price, size_decimals)
    return {
        "step_index": step_index,
        "cloid": deterministic_cloid(execution_id, step_index),
        "asset": asset,
        "side": side,
        "delta_notional_usd": round(abs(delta_notional), 8),
        "reference_price": reference_price,
        "limit_price": limit_price,
        "quantity": quantity,
        "size_decimals": int(size_decimals),
        "reduce_only": bool(reduce_only),
        "phase": "EXIT" if reduce_only else "ENTRY",
        "full_close": bool(reduce_only and exact_quantity is not None),
        "time_in_force": "Ioc",
    }


def build_execution_plan(
    *,
    production: Mapping[str, Any],
    intent: Mapping[str, Any],
    gate: Mapping[str, Any],
    account_snapshot: Mapping[str, Any],
    policy: Mapping[str, Any],
    mids: Mapping[str, float],
    size_decimals: Mapping[str, int],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reasons: list[str] = []
    prod_intent = production.get("execution_intent")
    if not isinstance(prod_intent, Mapping):
        raise ExecutionSafetyError("production_execution_intent_missing")

    expected = {
        "signal_id": prod_intent.get("signal_id"),
        "target_asset": normalize_asset(prod_intent.get("target_asset")),
        "target_exposure": as_float(prod_intent.get("target_exposure"), field="production.target_exposure"),
        "closed_day": str(production.get("closed_day") or "").strip(),
        "strategy_model": str(production.get("strategy_version") or "").strip(),
    }
    actual = {
        "signal_id": str(intent.get("signal_id") or "").strip(),
        "target_asset": normalize_asset(intent.get("target_asset")),
        "target_exposure": as_float(intent.get("target_size_pct"), field="intent.target_size_pct"),
        "closed_day": str(intent.get("as_of_source") or "").strip(),
        "strategy_model": str(intent.get("strategy_model") or "").strip(),
    }
    for key in ("signal_id", "target_asset", "closed_day", "strategy_model"):
        if expected[key] != actual[key]:
            reasons.append(f"production_intent_mismatch:{key}")
    if abs(expected["target_exposure"] - actual["target_exposure"]) > 1e-9:
        reasons.append("production_intent_mismatch:target_exposure")
    if str(production.get("validation", {}).get("status") or "").lower() != "passed":
        reasons.append("production_validation_not_passed")
    if bool(intent.get("stale_signal")) or bool(prod_intent.get("stale_signal")):
        reasons.append("stale_strategy")
    if bool(intent.get("allow_live_order_candidate")) != bool(prod_intent.get("allow_live_order_candidate")):
        reasons.append("allow_live_order_candidate_mismatch")
    if gate.get("signal_id") != actual["signal_id"]:
        reasons.append("intent_gate_mismatch:signal_id")
    if normalize_asset(gate.get("target_asset")) != actual["target_asset"]:
        reasons.append("intent_gate_mismatch:target_asset")
    gate_context = gate.get("production_signal_context")
    if not isinstance(gate_context, Mapping) or str(gate_context.get("closed_day") or "") != expected["closed_day"]:
        reasons.append("intent_gate_mismatch:closed_day")

    max_age = as_float(policy.get("account_snapshot_max_age_seconds"), field="policy.account_snapshot_max_age_seconds")
    age = (now - parse_utc(account_snapshot.get("as_of_utc"), field="account_snapshot.as_of_utc")).total_seconds()
    if age < -5 or age > max_age:
        reasons.append("stale_account_snapshot")

    target_asset = actual["target_asset"]
    target_exposure = actual["target_exposure"]
    if not valid_asset_symbol(target_asset):
        reasons.append("invalid_target_asset")
    if target_exposure < 0 or (is_cash(target_asset) and target_exposure != 0):
        reasons.append("invalid_target_exposure")
    if not is_cash(target_asset) and (target_exposure <= 0 or not prod_intent.get("allow_live_order_candidate")):
        reasons.append("strategy_disallows_live_candidate")
    if not is_cash(target_asset) and production.get("trend_permission_active") is False:
        reasons.append("strategy_trend_permission_inactive")
    slippage_bps = as_float(policy.get("max_slippage_bps"), field="policy.max_slippage_bps")
    if slippage_bps <= 0 or slippage_bps > 500:
        reasons.append("invalid_slippage_policy")
    # Leverage is an exchange margin setting, never an independent strategy cap.
    entry_policy_reasons: list[str] = []
    try:
        execution_leverage = max(math.ceil(target_exposure), int(policy.get("execution_leverage", 1)), 1)
        margin_buffer_fraction = as_float(policy.get("margin_buffer_fraction", 0), field="policy.margin_buffer_fraction")
    except (ExecutionSafetyError, ValueError, TypeError, OverflowError):
        execution_leverage, margin_buffer_fraction = 1, 0
        entry_policy_reasons.append("invalid_entry_margin_policy")
    if not 0 <= margin_buffer_fraction <= 0.5:
        entry_policy_reasons.append("invalid_margin_buffer_policy")
    equity, available, equity_source = account_equity_and_available(account_snapshot)
    positions = extract_positions(account_snapshot, mids)
    raw = account_snapshot.get("raw")
    open_orders = raw.get("openOrders", []) if isinstance(raw, Mapping) else []
    if not isinstance(open_orders, list):
        reasons.append("open_orders_unreadable")
        open_orders = []
    cancel_orders = []
    for order in open_orders:
        if not isinstance(order, Mapping):
            reasons.append("open_order_details_unreadable")
            continue
        # Ownership is explicit or proven by a prior durable journal CLOID by
        # the execution engine. Unknown user orders are never cancelled blindly.
        cancel_orders.append({**order, "asset": normalize_asset(order.get("coin") or order.get("asset"))})

    target_notional = 0.0 if is_cash(target_asset) else equity * target_exposure
    tolerance = max(equity * as_float(policy.get("reconciliation_tolerance_fraction_of_equity"), field="policy.reconciliation_tolerance_fraction_of_equity"), 0.01)
    post_trade_tolerance = max(equity * as_float(policy.get("post_trade_tolerance_fraction_of_equity"), field="policy.post_trade_tolerance_fraction_of_equity"), 0.01)
    min_notional = as_float(policy.get("minimum_order_notional_usd"), field="policy.minimum_order_notional_usd")
    unwanted = [p for p in positions if is_cash(target_asset) or p["asset"] != target_asset or p["size"] < 0]
    current_target = next((p for p in positions if p["asset"] == target_asset and p["size"] > 0), None)
    target_current_notional = float(current_target["notional_usd"]) if current_target else 0.0
    current_notional = sum(float(p["notional_usd"]) for p in positions)
    current_asset = positions[0]["asset"] if len(positions) == 1 else ("MULTI_ASSET" if positions else "CASH")
    planned_delta = target_notional - target_current_notional if not is_cash(target_asset) else -current_notional
    precision_limited_residual = bool(current_target and abs(planned_delta) < min_notional and abs(planned_delta) <= post_trade_tolerance)
    if unwanted:
        action = "EXIT" if is_cash(target_asset) else "ROTATE"
    elif is_cash(target_asset) or abs(planned_delta) <= tolerance or precision_limited_residual:
        action = "NO_ACTION"
    else:
        action = "INCREASE" if planned_delta > 0 else "REDUCE"
    transition_identity = {
        "account_address": str(account_snapshot.get("account_address") or "").strip().lower(),
        "positions": sorted((p["asset"], round(float(p["size"]), 12)) for p in positions),
        "target_notional_usd": round(target_notional, 2),
        "action": action,
    }
    execution_id = deterministic_execution_id(signal_id=actual["signal_id"], target_asset=target_asset, target_exposure=target_exposure, transition_identity=transition_identity)
    steps: list[dict[str, Any]] = []
    exit_reasons: list[str] = []
    entry_reasons: list[str] = entry_policy_reasons if not is_cash(target_asset) else []

    def add_step(asset: str, delta: float, *, reduce_only: bool, exact_quantity: float | None = None) -> None:
        blockers = exit_reasons if reduce_only else entry_reasons
        price = mids.get(asset)
        precision = size_decimals.get(asset)
        if price is None or not math.isfinite(float(price)) or float(price) <= 0:
            blockers.append(f"market_unavailable:{asset}")
            return
        if precision is None or not isinstance(precision, int) or not 0 <= precision <= 8:
            blockers.append(f"missing_exchange_precision:{asset}")
            return
        row = _step(execution_id=execution_id, step_index=len(steps), asset=asset, side="BUY" if delta > 0 else "SELL", delta_notional=abs(delta), reference_price=float(price), size_decimals=precision, slippage_bps=slippage_bps, reduce_only=reduce_only, exact_quantity=exact_quantity)
        row["exchange_leverage"] = execution_leverage
        if row["quantity"] <= 0 or row["limit_price"] <= 0:
            blockers.append(f"invalid_quantity:{asset}")
        # The exchange permits reduce-only position closure below entry minimum.
        if not reduce_only and row["delta_notional_usd"] + 1e-9 < min_notional:
            blockers.append(f"order_below_exchange_minimum:{asset}")
        row["block_reasons"] = list(blockers)
        steps.append(row)

    for position in sorted(unwanted, key=lambda p: p["asset"]):
        add_step(position["asset"], -float(position["notional_usd"]), reduce_only=True, exact_quantity=abs(float(position["size"])))
    if not is_cash(target_asset) and abs(planned_delta) > tolerance and not precision_limited_residual:
        add_step(target_asset, planned_delta, reduce_only=planned_delta < 0)
    increasing_notional = max(0, target_notional - target_current_notional)
    required_initial_margin = increasing_notional / execution_leverage * (1 + margin_buffer_fraction)
    if increasing_notional > tolerance and required_initial_margin > available + tolerance:
        entry_reasons.append("insufficient_margin_or_available_balance")
    exits = [step for step in steps if step["reduce_only"]]
    # An ENTRY failure never invalidates an independently executable EXIT.
    global_reasons = list(reasons) + exit_reasons
    if entry_reasons and not exits and not cancel_orders:
        global_reasons.extend(entry_reasons)
    return {
        "plan_type": "trendatlas_production_execution_plan",
        "generated_at_utc": utc_now_iso(), "signal_id": actual["signal_id"],
        "execution_id": execution_id, "strategy_model": actual["strategy_model"], "closed_day": actual["closed_day"],
        "asset": target_asset, "side": steps[-1]["side"] if steps else None,
        "account_address": str(account_snapshot.get("account_address") or "").strip().lower(),
        "current_asset": current_asset, "current_positions": positions,
        "current_notional_usd": round(current_notional, 8), "target_notional_usd": round(target_notional, 8),
        "delta_notional_usd": round(planned_delta, 8), "target_exposure": target_exposure,
        "account_equity_usd": equity, "available_balance_usd": available, "execution_leverage": execution_leverage,
        "required_initial_margin_usd": required_initial_margin, "account_equity_source": equity_source,
        "reference_price": mids.get(target_asset),
        "planned_quantity": sum(float(step["quantity"]) for step in steps if step["asset"] == target_asset),
        "action": action,
        "reason": "precision_limited_residual_within_post_trade_tolerance" if precision_limited_residual and not unwanted else f"reconcile_{current_asset}_to_{target_asset}_{target_exposure:g}x",
        "tolerance_notional_usd": tolerance, "steps": steps, "cancel_orders": cancel_orders,
        "entry_block_reasons": sorted(set(entry_reasons)), "exit_block_reasons": sorted(set(exit_reasons)),
        "unwanted_positions": unwanted, "block_reasons": sorted(set(global_reasons)),
        "status": "BLOCKED" if global_reasons else ("NO_ACTION" if action == "NO_ACTION" and not cancel_orders else "READY"),
    }


def validate_canonical_provenance(
    *,
    production_path: Path,
    intent_path: Path,
    account_path: Path,
    gate: Mapping[str, Any],
    allow_unavailable_owner_snapshot: bool = False,
) -> list[str]:
    fingerprints = gate.get("source_fingerprints")
    fingerprints = fingerprints if isinstance(fingerprints, Mapping) else {}
    expected = {
        "production_snapshot_sha256": sha256_file(production_path),
        "intent_sha256": sha256_file(intent_path),
    }
    optional_account = allow_unavailable_owner_snapshot and gate.get("account_validation_scope") == "per_account_exchange" and gate.get("account_snapshot_available") is False
    if optional_account:
        if fingerprints.get("account_snapshot_sha256") is not None:
            return ["bad_provenance_hash:unavailable_account_snapshot"]
    else:
        expected["account_snapshot_sha256"] = sha256_file(account_path)
    return [f"bad_provenance_hash:{key}" for key, value in expected.items() if fingerprints.get(key) != value]


def validate_live_preflight(
    *,
    plan: Mapping[str, Any],
    production: Mapping[str, Any],
    intent: Mapping[str, Any],
    gate: Mapping[str, Any],
    mode: Mapping[str, Any],
    policy: Mapping[str, Any],
    data_health: Mapping[str, Any],
    provenance_reasons: list[str],
) -> list[str]:
    reasons = list(plan.get("block_reasons", [])) + list(provenance_reasons)
    if mode.get("kill_switch") is not False:
        reasons.append("kill_switch_not_off")
    if str(gate.get("status") or "") != "ready_if_enabled" or gate.get("would_place_real_order") is not True:
        reasons.append("real_order_gate_not_ready")
    if gate.get("real_orders_enabled") is not True:
        reasons.append("gate_real_orders_not_enabled")
    summary = data_health.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    if bool(summary.get("block_execution")):
        reasons.append("data_health_blocks_execution")
    if str(summary.get("execution_status") or "").lower() not in {"ok", "passed"}:
        reasons.append("data_health_execution_not_ok")
    if bool(intent.get("stale_signal")):
        reasons.append("stale_signal")
    # A validated CASH target must be allowed to reduce/exit strategy exposure.
    # allow_live_order_candidate governs market entry, not risk-reducing exit.
    if not bool(intent.get("allow_live_order_candidate")) and plan.get("action") != "EXIT":
        reasons.append("strategy_disallows_live_candidate")
    if str(production.get("validation", {}).get("status") or "").lower() != "passed":
        reasons.append("production_validation_not_passed")
    return sorted(set(str(reason) for reason in reasons if str(reason).strip()))


def post_trade_alignment(
    residual_plan: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[bool, float, list[str]]:
    """Judge final alignment using the explicit post-trade tolerance.

    Sub-minimum or precision-limited residuals are execution feasibility details,
    not evidence that canonical state is stale. Every other planner blocker remains
    fail-closed.
    """
    equity = as_float(residual_plan.get("account_equity_usd"), field="post_trade.account_equity_usd")
    tolerance = max(
        equity
        * as_float(
            policy.get("post_trade_tolerance_fraction_of_equity"),
            field="policy.post_trade_tolerance_fraction_of_equity",
        ),
        0.01,
    )
    residual = abs(as_float(residual_plan.get("delta_notional_usd"), field="post_trade.delta_notional_usd"))
    feasibility_prefixes = (
        "order_below_exchange_minimum:",
        "invalid_quantity:",
        "insufficient_margin_or_available_balance",
    )
    critical = [
        str(reason)
        for reason in residual_plan.get("block_reasons", [])
        if not str(reason).startswith(feasibility_prefixes)
    ]
    return residual <= tolerance and not critical and not residual_plan.get("unwanted_positions") and not residual_plan.get("cancel_orders"), tolerance, critical


@dataclass
class ExecutionJournal:
    root: Path

    def path_for(self, execution_id: str) -> Path:
        return self.root / f"{execution_id}.json"

    @property
    def latest_path(self) -> Path:
        return self.root / "latest_execution_journal.json"

    def read(self, execution_id: str) -> dict[str, Any] | None:
        path = self.path_for(execution_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ExecutionSafetyError("execution_journal_not_object")
        return payload

    def prior_for_signal_target(
        self,
        *,
        signal_id: str,
        target_asset: str,
        exclude_execution_id: str,
    ) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        matches: list[dict[str, Any]] = []
        for path in self.root.glob("exec_*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                raise ExecutionSafetyError(f"execution_journal_unreadable:{path.name}")
            if not isinstance(payload, dict):
                raise ExecutionSafetyError(f"execution_journal_not_object:{path.name}")
            plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
            if str(payload.get("execution_id") or "") == exclude_execution_id:
                continue
            if str(payload.get("signal_id") or "") != signal_id:
                continue
            if normalize_asset(plan.get("asset")) != normalize_asset(target_asset):
                continue
            matches.append(payload)
        return matches

    def unresolved_for_account(self, *, account_address: str, exclude_execution_id: str) -> list[dict[str, Any]]:
        """Unknown requests survive both day changes and strategy rotations."""
        unresolved = []
        safe_states = {"PREPARED", "NO_ACTION", "BLOCKED", "FILLED_AND_ALIGNED", "FILLED_WITH_RESIDUAL", "REJECTED", "ENTRY_FAILED_STAYING_CASH", "EXITED_ENTRY_FAILED_STAYING_CASH"}
        for path in self.root.glob("exec_*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ExecutionSafetyError(f"execution_journal_unreadable:{path.name}") from exc
            if not isinstance(payload, dict):
                raise ExecutionSafetyError(f"execution_journal_not_object:{path.name}")
            prior_account = str((payload.get("plan") or {}).get("account_address") or "").lower()
            if prior_account and account_address and prior_account != account_address.lower():
                continue
            if payload.get("execution_id") != exclude_execution_id and payload.get("state") not in safe_states and payload.get("submission_started") is not False:
                unresolved.append(payload)
        return unresolved

    def write(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        execution_id = str(data.get("execution_id") or "").strip()
        if not execution_id:
            raise ExecutionSafetyError("journal_execution_id_missing")
        data["updated_at_utc"] = utc_now_iso()
        self.root.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for path in (self.path_for(execution_id), self.latest_path):
            temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            with temp.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        if os.name != "nt":
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return data

    def prepare(self, plan: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
        existing = self.read(str(plan["execution_id"]))
        if existing is not None:
            return existing
        return self.write({
            "journal_type": "trendatlas_production_execution_journal",
            "execution_id": plan["execution_id"],
            "signal_id": plan["signal_id"],
            "run_id": run_id,
            "state": "PREPARED",
            "submission_started": False,
            "prepared_at_utc": utc_now_iso(),
            "plan": dict(plan),
            "steps": [
                {"cloid": step["cloid"], "state": "PREPARED", "request": step}
                for step in plan.get("steps", [])
            ],
            "events": [{"at_utc": utc_now_iso(), "state": "PREPARED"}],
        })

    def transition(self, payload: Mapping[str, Any], state: str, **fields: Any) -> dict[str, Any]:
        updated = dict(payload)
        updated.update(fields)
        updated["state"] = state
        if state == "SUBMITTING" or any(row.get("state") in {"SUBMITTING", "ACKNOWLEDGED", "VERIFIED", "REJECTED"} for row in updated.get("steps", [])):
            updated["submission_started"] = True
        events = list(updated.get("events", []))
        events.append({"at_utc": utc_now_iso(), "state": state})
        updated["events"] = events
        return self.write(updated)


def recover_existing_execution(
    journal_payload: Mapping[str, Any],
    adapter: ExchangeAdapter,
) -> dict[str, Any]:
    state = str(journal_payload.get("state") or "")
    if state == "PREPARED":
        return {"status": "SAFE_TO_SUBMIT", "reason": "prepared_before_submit"}
    if state in {"NO_ACTION", "BLOCKED"}:
        return {"status": "DO_NOT_SUBMIT", "reason": f"journal_final:{state}"}
    evidence: list[dict[str, Any]] = []
    any_found = False
    any_open = False
    any_unknown = False
    for index, row in enumerate(journal_payload.get("steps", [])):
        if not isinstance(row, Mapping):
            continue
        # New journals persist each step before submission. A PREPARED later
        # step cannot have been submitted; legacy journals need CLOID lookup.
        if row.get("state") == "PREPARED" and "active_step_index" in journal_payload and index != journal_payload["active_step_index"]:
            continue
        cloid = str(row.get("cloid") or "")
        response = adapter.query_order_by_cloid(cloid)
        status = str(response.get("status") or "missing").lower()
        found = bool(response.get("found")) or status not in {"", "missing", "unknown", "not_found"}
        any_found = any_found or found
        any_open = any_open or status == "open"
        any_unknown = any_unknown or not found
        evidence.append({"cloid": cloid, "status": status, "found": found, "raw": response})
    if any_found and not any_unknown:
        return {
            "status": "DO_NOT_SUBMIT",
            "reason": "exchange_cloid_evidence_present",
            "open_order_present": any_open,
            "evidence": evidence,
        }
    return {
        "status": "UNCERTAIN",
        "reason": "submission_state_without_exchange_cloid_evidence",
        "evidence": evidence,
    }


def execute_plan_once(
    *,
    plan: Mapping[str, Any],
    run_id: str,
    journal: ExecutionJournal,
    adapter: ExchangeAdapter,
    refresh_and_verify: Callable[[Mapping[str, Any], list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    if plan.get("status") == "BLOCKED":
        raise ExecutionSafetyError(list(plan.get("block_reasons", [])) or ["plan_blocked"])
    payload = journal.prepare(plan, run_id=run_id)
    action_results: list[dict[str, Any]] = list(payload.get("action_results", []))
    requested = False
    verified_exit = any(row.get("step", {}).get("full_close") for row in action_results)
    verification: dict[str, Any] | None = None

    def finish(status: str, **fields: Any) -> dict[str, Any]:
        nonlocal payload
        payload = journal.transition(payload, status, action_results=action_results, **fields)
        return {"status": status, "order_requested": requested, "action_results": action_results, "journal": payload, **fields}

    def entry_failed(reasons: list[str], evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
        readback = dict(evidence or refresh_and_verify(plan, action_results))
        positions = readback.get("positions", [])
        if positions:
            return finish("FILLED_WITH_RESIDUAL", entry_block_reasons=reasons, post_trade=readback)
        status = "EXITED_ENTRY_FAILED_STAYING_CASH" if verified_exit else "ENTRY_FAILED_STAYING_CASH"
        return finish(status, entry_block_reasons=reasons, post_trade=readback, staying_cash=True)

    # Resolve prior journal attempts before any new exchange write. The current
    # plan came from a fresh account; unknown CLOIDs still forbid blind retry.
    prior_records = journal.prior_for_signal_target(signal_id=str(plan["signal_id"]), target_asset=str(plan["asset"]), exclude_execution_id=str(plan["execution_id"]))
    prior_records += journal.unresolved_for_account(account_address=str(plan.get("account_address") or ""), exclude_execution_id=str(plan["execution_id"]))
    checked_journals: set[str] = set()
    for prior in prior_records:
        prior_id = str(prior.get("execution_id"))
        if prior_id in checked_journals:
            continue
        checked_journals.add(prior_id)
        if prior.get("submission_started") is False:
            continue
        if prior.get("state") in {"PREPARED", "NO_ACTION", "BLOCKED", "ENTRY_FAILED_STAYING_CASH", "EXITED_ENTRY_FAILED_STAYING_CASH"}:
            continue
        evidence = recover_existing_execution(prior, adapter)
        statuses = {str(row.get("status") or "").lower() for row in evidence.get("evidence", []) if row.get("found")}
        if evidence.get("status") == "UNCERTAIN" or not statuses or not statuses.issubset(TERMINAL_EXCHANGE_STATES):
            verification = refresh_and_verify(plan, action_results)
            return finish("UNCERTAIN", recovery=evidence, post_trade=verification)
        verification = refresh_and_verify(plan, action_results)

    # An automatic executor may cancel only orders whose ownership is explicit
    # or is proved by a durable journal CLOID, never arbitrary user orders.
    owned_cloids: set[str] = set()
    owned_orders: set[tuple[str, str]] = set()
    if plan.get("cancel_orders"):
        for path in journal.root.glob("exec_*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            journal_account = str((record.get("plan") or {}).get("account_address") or "").lower()
            if journal_account and journal_account != str(plan.get("account_address") or "").lower():
                continue
            for row in record.get("steps", []):
                owned_cloids.add(str(row.get("cloid")))
                oid = (row.get("response") or {}).get("oid")
                if oid is not None:
                    owned_orders.add((normalize_asset((row.get("request") or {}).get("asset")), str(oid)))
        cancellations = []
        for order in plan["cancel_orders"]:
            identity = (normalize_asset(order.get("asset")), str(order.get("oid")))
            if not (order.get("managed_by_execution") is True or str(order.get("cloid")) in owned_cloids or identity in owned_orders):
                return finish("BLOCKED", block_reasons=["open_order_ownership_unknown"])
            payload = journal.transition(payload, "CANCELLING", cancellation_request=dict(order), cancellations=cancellations)
            try:
                result = adapter.cancel_order(order)
            except Exception as exc:
                verification = refresh_and_verify(plan, action_results)
                return finish("UNCERTAIN", cancel_error=type(exc).__name__, post_trade=verification)
            cancellations.append({"order": order, "response": result})
            payload = journal.transition(payload, "CANCELLED", cancellations=cancellations)
        verification = refresh_and_verify(plan, action_results)
        if verification.get("open_orders"):
            return finish("BLOCKED", block_reasons=["conflicting_orders_not_cancelled"], post_trade=verification)

    if plan.get("action") == "NO_ACTION":
        return finish("NO_ACTION")
    steps_state = [dict(row) for row in payload.get("steps", [])]
    active_index = payload.get("active_step_index", 0)
    state = str(payload.get("state") or "")
    if state in FINAL_JOURNAL_STATES - {"UNCERTAIN", "PARTIAL"}:
        verification = refresh_and_verify(plan, action_results)
        # Final evidence is immutable in meaning: publication retry never sends
        # the completed order again even if a residual requires a future plan.
        return {"status": state, "order_requested": False, "action_results": action_results, "post_trade": verification, "journal": payload}

    for index, original_step in enumerate(plan.get("steps", [])):
        step = dict(original_step)
        row_state = str(steps_state[index].get("state") or "PREPARED")
        possibly_submitted = row_state != "PREPARED" or (state == "SUBMITTING" and active_index == index)
        if possibly_submitted:
            evidence = adapter.query_order_by_cloid(str(step["cloid"]))
            exchange_status = str(evidence.get("status") or "unknown").lower()
            if evidence.get("found") and exchange_status == "filled" and not any(item.get("step", {}).get("cloid") == step["cloid"] for item in action_results):
                action_results.append({"step": step, "response": {"acknowledged": True, "submit_state": "filled", "recovered_by_cloid": True}})
            verification = refresh_and_verify(plan, action_results)
            if not evidence.get("found") or exchange_status not in TERMINAL_EXCHANGE_STATES:
                return finish("UNCERTAIN", recovery=evidence, post_trade=verification)
            if exchange_status != "filled":
                if not step["reduce_only"] and verified_exit:
                    return entry_failed([f"entry_exchange_{exchange_status}"], verification)
                return finish("REJECTED", recovery=evidence, post_trade=verification)
            if step["reduce_only"]:
                if not verification.get("safe_for_next_step"):
                    return finish("PARTIAL", post_trade=verification)
                verified_exit = verified_exit or bool(step.get("full_close"))
            steps_state[index]["state"] = "VERIFIED"
            payload = journal.transition(payload, "VERIFIED", steps=steps_state)
            continue

        if not step["reduce_only"]:
            # Recompute sizing, support, precision and margin after EXIT. A
            # close can release collateral or change equity before this step.
            verification = verification or refresh_and_verify(plan, action_results)
            residual = verification.get("residual_plan")
            if isinstance(residual, Mapping):
                entry_reasons = list(residual.get("entry_block_reasons", []))
                if residual.get("unwanted_positions") or verification.get("open_orders"):
                    return finish("PARTIAL", post_trade=verification)
                if residual.get("block_reasons"):
                    entry_reasons.extend(residual["block_reasons"])
                if entry_reasons:
                    return entry_failed(sorted(set(entry_reasons)), verification)
                replacement = next((candidate for candidate in residual.get("steps", []) if not candidate.get("reduce_only")), None)
                if replacement is None:
                    return finish(str(verification.get("status") or "NO_ACTION"), post_trade=verification)
                step = {**replacement, "cloid": original_step["cloid"], "step_index": index}
            elif plan.get("entry_block_reasons"):
                return entry_failed(list(plan["entry_block_reasons"]), verification)

        steps_state[index] = {**steps_state[index], "request": step, "state": "SUBMITTING"}
        payload = journal.transition(payload, "SUBMITTING", active_step_index=index, steps=steps_state)
        requested = True
        try:
            response = adapter.submit_ioc_order(step)
        except BaseException as exc:
            # Even when an exception hides exchange acceptance, do read-back;
            # a future recovery must query the same CLOID before any residual.
            verification = refresh_and_verify(plan, action_results)
            return finish("UNCERTAIN", submit_error=type(exc).__name__, post_trade=verification)
        submit_state = str(response.get("submit_state") or response.get("status") or "unknown").lower()
        ambiguous = response.get("normalization_ok") is False or submit_state in {"unknown", "manual_review_required", "uncertain"}
        acknowledged = bool(response.get("acknowledged")) and submit_state != "error" and not ambiguous
        action_results.append({"step": step, "response": response})
        steps_state[index] = {**steps_state[index], "state": "SUBMITTING" if ambiguous else "ACKNOWLEDGED" if acknowledged else "REJECTED", "response": response}
        payload = journal.transition(payload, steps_state[index]["state"], steps=steps_state, action_results=action_results)
        verification = refresh_and_verify(plan, action_results)
        if ambiguous:
            return finish("UNCERTAIN", post_trade=verification)
        if not acknowledged:
            if not step["reduce_only"] and verified_exit:
                return entry_failed([str(response.get("error") or "entry_rejected")], verification)
            return finish("REJECTED", post_trade=verification)
        if step["reduce_only"] and step.get("full_close"):
            if not verification.get("safe_for_next_step"):
                return finish("PARTIAL", post_trade=verification)
            verified_exit = True
        steps_state[index]["state"] = "VERIFIED"
        payload = journal.transition(payload, "VERIFIED", steps=steps_state)

    verification = verification or refresh_and_verify(plan, action_results)
    # An unavailable market may mean there was no ENTRY step to execute at all.
    residual = verification.get("residual_plan")
    final_entry_reasons = list(residual.get("entry_block_reasons", [])) if isinstance(residual, Mapping) else list(plan.get("entry_block_reasons", []))
    if final_entry_reasons and not is_cash(plan.get("asset")):
        return entry_failed(final_entry_reasons, verification)
    status = str(verification.get("status") or "UNCERTAIN")
    return finish(status if status in FINAL_JOURNAL_STATES else "UNCERTAIN", post_trade=verification)
