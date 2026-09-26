"""Economic route identity, independent of exchange support and account holdings."""
from __future__ import annotations

import math
from typing import Any

from scripts.production.causal_performance import asset

FIELDS = (
    "route_type", "base_economic_asset", "candidate_asset",
    "candidate_trigger_active", "resolved_execution_asset", "resolution_reason",
    "signal_available_at",
)


def resolve_route(*, route_type: str, base_economic_asset: str,
                  candidate_asset: str, candidate_trigger_active: bool,
                  target_exposure: float, signal_available_at: str) -> dict[str, Any]:
    route = str(route_type).upper()
    base, candidate = asset(base_economic_asset), asset(candidate_asset)
    if not isinstance(candidate_trigger_active, bool):
        raise ValueError("Candidate trigger must be an explicit boolean")
    exposure = float(target_exposure)
    if not math.isfinite(exposure) or exposure < 0:
        raise ValueError("Invalid route exposure")
    if route == "CASH":
        if exposure != 0:
            raise ValueError("CASH route requires zero exposure")
        resolved, reason = "CASH", "cash_route"
    elif route == "BTC":
        resolved, reason = "BTC", "btc_route"
    elif route == "BASE":
        resolved, reason = base, "same_interval_base_holding"
        if candidate_trigger_active:
            raise ValueError("BASE cannot claim an active candidate route")
    elif route == "CANDIDATE":
        if not candidate_trigger_active:
            raise ValueError("CANDIDATE route requires its actual trigger")
        resolved, reason = candidate, "active_candidate_trigger"
    else:
        raise ValueError("Unknown route: " + route)
    if route != "CASH" and (resolved == "CASH" or exposure <= 0):
        raise ValueError("Risk route requires a concrete asset and positive exposure")
    return dict(route_type=route, base_economic_asset=base, candidate_asset=candidate,
                candidate_trigger_active=candidate_trigger_active,
                resolved_execution_asset=resolved, resolution_reason=reason,
                signal_available_at=signal_available_at, target_exposure=exposure)


def validate_target_identity(snapshot: dict[str, Any]) -> None:
    """Consumers cannot silently fall back to a weekly candidate or an old label."""
    missing = set(FIELDS) - set(snapshot)
    if missing:
        raise ValueError("Missing production route identity: " + ", ".join(sorted(missing)))
    intent = snapshot["execution_intent"]
    expected = resolve_route(**{k: snapshot[k] for k in FIELDS if k not in {
        "resolved_execution_asset", "resolution_reason"}},
        target_exposure=intent["target_exposure"])
    for key in ("resolved_execution_asset", "resolution_reason"):
        if snapshot[key] != expected[key]:
            raise ValueError("Production route derivation mismatch: " + key)
    for key in ("current_asset", "actual_held_asset", "authorized_tradable_asset"):
        if asset(snapshot[key]) != expected["resolved_execution_asset"]:
            raise ValueError("Production target identity mismatch: " + key)
    if intent["target_asset"] != expected["resolved_execution_asset"]:
        raise ValueError("Execution intent diverges from resolved production asset")
    if any(intent.get(k) != snapshot[k] for k in FIELDS):
        raise ValueError("Execution intent route lineage differs from Production Core")
