from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_execution_app_status(
    *,
    mode: str,
    kill_switch: bool,
    account_address: Any,
    positions_count: int,
    open_orders_count: int,
    recent_fills_count: int,
    current_position: str,
    last_action: str,
    last_action_result: str,
    stale_signal: bool | None,
    signal_id: str | None,
    target_asset: str | None,
    source_paths: dict[str, str],
    error: Any = None,
) -> dict[str, Any]:
    return {
        "status_type": "execution_app_status",
        "as_of_utc": utc_now_iso(),
        "mode": mode,
        "trading_enabled": False,
        "kill_switch": kill_switch,
        "status": "ok",
        "provider": "Hyperliquid",
        "account_address": account_address,
        "positions_count": positions_count,
        "open_orders_count": open_orders_count,
        "recent_fills_count": recent_fills_count,
        "current_position": current_position,
        "last_action": last_action,
        "last_action_result": last_action_result,
        "guardrails_ok": True,
        "stale_signal": stale_signal,
        "signal_id": signal_id,
        "target_asset": target_asset,
        "error": error,
        "source_paths": source_paths,
    }
