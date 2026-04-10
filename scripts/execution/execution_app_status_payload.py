from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_execution_mode_posture(
    *,
    mode: str,
    trading_enabled: bool,
    kill_switch: bool,
) -> str:
    normalized_mode = str(mode or "").strip().lower() or "unknown"
    if normalized_mode == "live" and trading_enabled and not kill_switch:
        return "live"
    if normalized_mode == "read_only" and not trading_enabled and kill_switch:
        return "safe"
    return "custom"


def build_execution_mode_posture_payload(
    *,
    mode: str,
    trading_enabled: bool,
    kill_switch: bool,
    source_path: str | None = None,
) -> dict[str, Any]:
    return {
        "mode": str(mode or "").strip().lower() or "unknown",
        "trading_enabled": bool(trading_enabled),
        "kill_switch": bool(kill_switch),
        "posture": normalize_execution_mode_posture(
            mode=mode,
            trading_enabled=trading_enabled,
            kill_switch=kill_switch,
        ),
        "source_path": source_path,
        "read_model_only": True,
    }


def build_trading_operation_mode_read_model(
    payload: dict[str, Any] | None,
    *,
    source_path: str | None = None,
) -> dict[str, Any]:
    source_payload = payload if isinstance(payload, dict) else {}
    return {
        "mode": str(source_payload.get("mode") or "").strip().lower() or "manual",
        "updated_at_utc": str(source_payload.get("updated_at_utc") or "").strip() or None,
        "updated_by": str(source_payload.get("updated_by") or "").strip() or "system",
        "fail_closed": bool(source_payload.get("fail_closed", False)),
        "error": str(source_payload.get("error") or "").strip() or None,
        "source_path": source_path
        or str(source_payload.get("path") or source_payload.get("source_path") or "").strip()
        or None,
        "read_model_only": True,
    }


def build_execution_app_status(
    *,
    mode: str,
    trading_enabled: bool = False,
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
    trading_operation_mode: dict[str, Any] | None = None,
    execution_mode_posture: dict[str, Any] | None = None,
    strategy_freshness: dict[str, Any] | None = None,
    error: Any = None,
) -> dict[str, Any]:
    strategy_freshness_payload = (
        strategy_freshness if isinstance(strategy_freshness, dict) else {}
    )
    return {
        "status_type": "execution_app_status",
        "as_of_utc": utc_now_iso(),
        "mode": mode,
        "trading_enabled": trading_enabled,
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
        "trading_operation_mode": trading_operation_mode,
        "execution_mode_posture": execution_mode_posture,
        "strategy_freshness": strategy_freshness_payload,
        "latest_successful_refresh_runtime_utc": strategy_freshness_payload.get(
            "latest_successful_refresh_runtime_utc"
        ),
        "latest_refresh_run_status": strategy_freshness_payload.get("latest_refresh_run_status")
        or strategy_freshness_payload.get("refresh_status"),
        "latest_refresh_run_id": strategy_freshness_payload.get("latest_refresh_run_id")
        or strategy_freshness_payload.get("refresh_run_id"),
        "latest_strategy_artifact_date": strategy_freshness_payload.get(
            "latest_strategy_artifact_date"
        ),
        "latest_trend_calculation_date": strategy_freshness_payload.get(
            "latest_trend_calculation_date"
        ),
        "latest_wallet_sync_utc": strategy_freshness_payload.get("latest_wallet_sync_utc"),
        "latest_available_closed_utc_date": strategy_freshness_payload.get(
            "latest_available_closed_utc_date"
        ),
        "refresh_currentness_state": strategy_freshness_payload.get("refresh_currentness_state")
        or strategy_freshness_payload.get("freshness_state"),
        "refresh_currentness_reason": strategy_freshness_payload.get("refresh_currentness_reason")
        or strategy_freshness_payload.get("freshness_detail_text"),
        "error": error,
        "source_paths": source_paths,
    }
