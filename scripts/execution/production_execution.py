from __future__ import annotations

import hashlib
import json
import math
import os
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
}


class ExecutionSafetyError(RuntimeError):
    def __init__(self, reasons: list[str] | str) -> None:
        self.reasons = reasons if isinstance(reasons, list) else [reasons]
        super().__init__(" | ".join(self.reasons))


class ExchangeAdapter(Protocol):
    def query_order_by_cloid(self, cloid: str) -> dict[str, Any]: ...

    def submit_ioc_order(self, step: Mapping[str, Any]) -> dict[str, Any]: ...


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


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
    available = as_float(available_value, field="available_balance_usd")
    if equity <= 0:
        raise ExecutionSafetyError("account_equity_not_positive")
    if available < 0:
        raise ExecutionSafetyError("available_balance_negative")
    return equity, available, source


def extract_positions(snapshot: Mapping[str, Any], mids: Mapping[str, float]) -> list[dict[str, Any]]:
    raw = snapshot.get("raw")
    clearinghouse = raw.get("clearinghouseState") if isinstance(raw, Mapping) else None
    raw_positions = clearinghouse.get("assetPositions", []) if isinstance(clearinghouse, Mapping) else []
    positions: list[dict[str, Any]] = []
    if not isinstance(raw_positions, list):
        return positions
    for item in raw_positions:
        if not isinstance(item, Mapping):
            continue
        position = item.get("position") if isinstance(item.get("position"), Mapping) else item
        asset = normalize_asset(position.get("coin"))
        if not asset:
            continue
        size = as_float(position.get("szi", position.get("size", 0)), field=f"position.{asset}.size")
        if abs(size) <= 1e-12:
            continue
        raw_value = position.get("positionValue")
        reference_price = as_float(mids.get(asset), field=f"mids.{asset}")
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

    allowed_assets = {normalize_asset(item) for item in policy.get("allowed_assets", [])}
    target_asset = actual["target_asset"]
    target_exposure = actual["target_exposure"]
    if target_exposure < 0:
        reasons.append("negative_target_exposure")
    if not is_cash(target_asset) and target_asset not in allowed_assets:
        reasons.append("disallowed_asset")
    max_exposure = as_float(policy.get("max_strategy_target_exposure"), field="policy.max_strategy_target_exposure")
    if target_exposure > max_exposure + 1e-12:
        reasons.append("target_exposure_exceeds_relative_safety_ceiling")
    slippage_bps = as_float(policy.get("max_slippage_bps"), field="policy.max_slippage_bps")
    if slippage_bps <= 0 or slippage_bps > 500:
        reasons.append("invalid_slippage_policy")
    execution_leverage = as_float(policy.get("execution_leverage"), field="policy.execution_leverage")
    max_execution_leverage = as_float(
        policy.get("max_execution_leverage"), field="policy.max_execution_leverage"
    )
    if execution_leverage < 1 or execution_leverage > max_execution_leverage:
        reasons.append("invalid_execution_leverage_policy")
    margin_buffer_fraction = as_float(
        policy.get("margin_buffer_fraction"), field="policy.margin_buffer_fraction"
    )
    if margin_buffer_fraction < 0 or margin_buffer_fraction > 0.5:
        reasons.append("invalid_margin_buffer_policy")

    equity, available, equity_source = account_equity_and_available(account_snapshot)
    positions = extract_positions(account_snapshot, mids)
    raw = account_snapshot.get("raw")
    open_orders = raw.get("openOrders", []) if isinstance(raw, Mapping) else []
    if not isinstance(open_orders, list):
        reasons.append("open_orders_unreadable")
        open_orders = []
    if open_orders:
        reasons.append("conflicting_open_order")
    if len(positions) > 1:
        reasons.append("multiple_positions_require_manual_reconciliation")

    target_notional = 0.0 if is_cash(target_asset) else equity * target_exposure
    tolerance = max(equity * as_float(
        policy.get("reconciliation_tolerance_fraction_of_equity"),
        field="policy.reconciliation_tolerance_fraction_of_equity",
    ), 0.01)
    post_trade_tolerance = max(equity * as_float(
        policy.get("post_trade_tolerance_fraction_of_equity"),
        field="policy.post_trade_tolerance_fraction_of_equity",
    ), 0.01)
    min_notional = as_float(
        policy.get("minimum_order_notional_usd"),
        field="policy.minimum_order_notional_usd",
    )
    current = positions[0] if len(positions) == 1 else None
    current_asset = current["asset"] if current else "CASH"
    current_notional = float(current["notional_usd"]) if current else 0.0

    if is_cash(target_asset):
        action = "NO_ACTION" if current is None else "EXIT"
        planned_delta = -current_notional
    elif current is None:
        action = "INCREASE"
        planned_delta = target_notional
    elif current_asset != target_asset or current_notional < 0:
        action = "ROTATE"
        planned_delta = target_notional - current_notional
    else:
        planned_delta = target_notional - current_notional
        if abs(planned_delta) <= tolerance:
            action = "NO_ACTION"
        elif planned_delta > 0:
            action = "INCREASE"
        else:
            action = "REDUCE"

    precision_limited_residual = (
        action in {"INCREASE", "REDUCE"}
        and current is not None
        and current_asset == target_asset
        and abs(planned_delta) < min_notional
        and abs(planned_delta) <= post_trade_tolerance
    )
    if precision_limited_residual:
        action = "NO_ACTION"

    transition_identity = {
        "current_asset": current_asset,
        "current_notional_usd": round(current_notional, 2),
        "target_notional_usd": round(target_notional, 2),
        "action": action,
    }
    execution_id = deterministic_execution_id(
        signal_id=actual["signal_id"],
        target_asset=target_asset,
        target_exposure=target_exposure,
        transition_identity=transition_identity,
    )
    steps: list[dict[str, Any]] = []
    if action in {"EXIT", "ROTATE"} and current is not None:
        steps.append(_step(
            execution_id=execution_id,
            step_index=len(steps),
            asset=current_asset,
            side="SELL" if current["size"] > 0 else "BUY",
            delta_notional=abs(current_notional),
            reference_price=as_float(mids.get(current_asset), field=f"mids.{current_asset}"),
            size_decimals=int(size_decimals.get(current_asset, -1)),
            slippage_bps=slippage_bps,
            reduce_only=True,
            exact_quantity=abs(float(current["size"])),
        ))
    if action in {"INCREASE", "REDUCE"}:
        steps.append(_step(
            execution_id=execution_id,
            step_index=len(steps),
            asset=target_asset,
            side="BUY" if planned_delta > 0 else "SELL",
            delta_notional=abs(planned_delta),
            reference_price=as_float(mids.get(target_asset), field=f"mids.{target_asset}"),
            size_decimals=int(size_decimals.get(target_asset, -1)),
            slippage_bps=slippage_bps,
            reduce_only=planned_delta < 0,
        ))
    elif action == "ROTATE" and not is_cash(target_asset):
        steps.append(_step(
            execution_id=execution_id,
            step_index=len(steps),
            asset=target_asset,
            side="BUY",
            delta_notional=target_notional,
            reference_price=as_float(mids.get(target_asset), field=f"mids.{target_asset}"),
            size_decimals=int(size_decimals.get(target_asset, -1)),
            slippage_bps=slippage_bps,
            reduce_only=False,
        ))

    for step in steps:
        step["exchange_leverage"] = int(execution_leverage)
        if step["size_decimals"] < 0:
            reasons.append(f"missing_exchange_precision:{step['asset']}")
        if step["quantity"] <= 0:
            reasons.append(f"invalid_quantity:{step['asset']}")
        if step["delta_notional_usd"] + 1e-9 < min_notional:
            reasons.append(f"order_below_exchange_minimum:{step['asset']}")
    delta_fraction = abs(planned_delta) / equity
    if delta_fraction > as_float(policy.get("max_delta_fraction_of_equity"), field="policy.max_delta_fraction_of_equity") + 1e-12:
        reasons.append("delta_exceeds_relative_safety_ceiling")
    increasing_notional = sum(step["delta_notional_usd"] for step in steps if not step["reduce_only"])
    required_initial_margin = (
        increasing_notional / execution_leverage * (1 + margin_buffer_fraction)
        if execution_leverage > 0
        else float("inf")
    )
    if required_initial_margin > available + tolerance:
        reasons.append("insufficient_margin_or_available_balance")

    plan = {
        "plan_type": "trendatlas_production_execution_plan",
        "generated_at_utc": utc_now_iso(),
        "signal_id": actual["signal_id"],
        "execution_id": execution_id,
        "strategy_model": actual["strategy_model"],
        "closed_day": actual["closed_day"],
        "asset": target_asset,
        "side": steps[-1]["side"] if steps else None,
        "current_asset": current_asset,
        "current_notional_usd": round(current_notional, 8),
        "target_notional_usd": round(target_notional, 8),
        "delta_notional_usd": round(planned_delta, 8),
        "target_exposure": target_exposure,
        "account_equity_usd": equity,
        "available_balance_usd": available,
        "execution_leverage": execution_leverage,
        "required_initial_margin_usd": required_initial_margin,
        "account_equity_source": equity_source,
        "reference_price": None if is_cash(target_asset) else as_float(mids.get(target_asset), field=f"mids.{target_asset}"),
        "planned_quantity": sum(float(step["quantity"]) for step in steps if step["asset"] == target_asset),
        "action": action,
        "reason": (
            "precision_limited_residual_within_post_trade_tolerance"
            if precision_limited_residual
            else f"reconcile_{current_asset}_to_{target_asset}_{target_exposure:g}x"
        ),
        "tolerance_notional_usd": tolerance,
        "steps": steps,
        "block_reasons": sorted(set(reasons)),
        "status": "BLOCKED" if reasons else ("NO_ACTION" if action == "NO_ACTION" else "READY"),
    }
    return plan


def validate_canonical_provenance(
    *,
    production_path: Path,
    intent_path: Path,
    account_path: Path,
    gate: Mapping[str, Any],
) -> list[str]:
    fingerprints = gate.get("source_fingerprints")
    fingerprints = fingerprints if isinstance(fingerprints, Mapping) else {}
    expected = {
        "production_snapshot_sha256": sha256_file(production_path),
        "intent_sha256": sha256_file(intent_path),
        "account_snapshot_sha256": sha256_file(account_path),
    }
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
    if str(mode.get("mode") or "").lower() != "live":
        reasons.append("execution_mode_not_live")
    if mode.get("trading_enabled") is not True:
        reasons.append("trading_enabled_not_true")
    if policy.get("allow_live_orders") is not True:
        reasons.append("allow_live_orders_not_true")
    if policy.get("manual_approval_required") is True:
        reasons.append("manual_approval_required")
    if policy.get("require_kill_switch_off", True) and mode.get("kill_switch") is not False:
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
    return residual <= tolerance and not critical, tolerance, critical


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
    for row in journal_payload.get("steps", []):
        if not isinstance(row, Mapping):
            continue
        cloid = str(row.get("cloid") or "")
        response = adapter.query_order_by_cloid(cloid)
        status = str(response.get("status") or "missing").lower()
        found = bool(response.get("found")) or status not in {"", "missing", "unknown", "not_found"}
        any_found = any_found or found
        any_open = any_open or status == "open"
        evidence.append({"cloid": cloid, "status": status, "found": found, "raw": response})
    if any_found:
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
    if plan.get("action") == "NO_ACTION":
        payload = journal.prepare(plan, run_id=run_id)
        journal.transition(payload, "NO_ACTION")
        return {"status": "NO_ACTION", "order_requested": False, "action_results": []}

    for prior in journal.prior_for_signal_target(
        signal_id=str(plan["signal_id"]),
        target_asset=str(plan["asset"]),
        exclude_execution_id=str(plan["execution_id"]),
    ):
        prior_state = str(prior.get("state") or "")
        if prior_state == "PREPARED":
            continue
        prior_recovery = recover_existing_execution(prior, adapter)
        evidence = prior_recovery.get("evidence", [])
        statuses = {
            str(row.get("status") or "").lower()
            for row in evidence
            if isinstance(row, Mapping) and row.get("found")
        }
        if not statuses or not statuses.issubset(TERMINAL_EXCHANGE_STATES):
            return {
                "status": "UNCERTAIN",
                "order_requested": False,
                "recovery": {
                    "reason": "prior_same_signal_transition_not_terminal",
                    "prior_execution_id": prior.get("execution_id"),
                    "prior_state": prior_state,
                    "exchange_recovery": prior_recovery,
                },
            }

    payload = journal.prepare(plan, run_id=run_id)
    recovery = recover_existing_execution(payload, adapter)
    if recovery["status"] == "DO_NOT_SUBMIT":
        payload = journal.transition(payload, "UNCERTAIN", recovery=recovery)
        return {"status": "UNCERTAIN", "order_requested": False, "recovery": recovery, "journal": payload}
    if recovery["status"] == "UNCERTAIN":
        payload = journal.transition(payload, "UNCERTAIN", recovery=recovery)
        return {"status": "UNCERTAIN", "order_requested": False, "recovery": recovery, "journal": payload}

    action_results: list[dict[str, Any]] = []
    steps_state = [dict(row) for row in payload.get("steps", [])]
    for index, step in enumerate(plan.get("steps", [])):
        payload = journal.transition(payload, "SUBMITTING", active_step_index=index)
        try:
            response = adapter.submit_ioc_order(step)
        except BaseException as exc:
            payload = journal.transition(
                payload,
                "UNCERTAIN",
                submit_error=f"{type(exc).__name__}:{exc}",
                active_step_index=index,
            )
            return {
                "status": "UNCERTAIN",
                "order_requested": True,
                "action_results": action_results,
                "error": f"{type(exc).__name__}:{exc}",
                "journal": payload,
            }
        normalized_state = str(response.get("submit_state") or response.get("status") or "unknown").lower()
        steps_state[index] = {
            **steps_state[index],
            "state": "ACKNOWLEDGED" if bool(response.get("acknowledged")) else "REJECTED",
            "response": response,
        }
        action_results.append({"step": step, "response": response})
        payload = journal.transition(
            payload,
            "ACKNOWLEDGED" if bool(response.get("acknowledged")) else "REJECTED",
            steps=steps_state,
            action_results=action_results,
        )
        if not bool(response.get("acknowledged")) or normalized_state == "error":
            return {"status": "REJECTED", "order_requested": True, "action_results": action_results, "journal": payload}
        # Rotation is deliberately serialized: verify the close before submitting entry.
        if index + 1 < len(plan.get("steps", [])):
            interim = refresh_and_verify(plan, action_results)
            if not bool(interim.get("safe_for_next_step")):
                payload = journal.transition(payload, "PARTIAL", post_trade=interim)
                return {"status": "PARTIAL", "order_requested": True, "action_results": action_results, "post_trade": interim, "journal": payload}

    verification = refresh_and_verify(plan, action_results)
    status = str(verification.get("status") or "UNCERTAIN")
    if status not in FINAL_JOURNAL_STATES:
        status = "UNCERTAIN"
    payload = journal.transition(payload, status, post_trade=verification)
    return {
        "status": status,
        "order_requested": True,
        "action_results": action_results,
        "post_trade": verification,
        "journal": payload,
    }
