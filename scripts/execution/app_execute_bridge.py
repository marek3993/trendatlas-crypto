from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution.hyperliquid_live_canary import (  # noqa: E402
    ACCOUNT_CONFIG_PATH,
    MODE_CONFIG_PATH,
    fetch_open_orders,
    fetch_spot_user_state,
    fetch_user_state,
    info_request,
    summarize_snapshot,
)
from scripts.execution.trading_operation_mode import (  # noqa: E402
    DEFAULT_TRADING_OPERATION_MODE_PATH,
    load_trading_operation_mode_payload,
    write_trading_operation_mode_payload,
)


OUTPUTS_DIR = ROOT / "outputs" / "execution"
CONFIG_DIR = ROOT / "execution" / "config"
READ_ONLY_DIR = OUTPUTS_DIR / "read_only"
LIVE_STATUS_DIR = OUTPUTS_DIR / "live_status"
DRY_RUN_DIR = OUTPUTS_DIR / "dry_run"
RECON_DIR = OUTPUTS_DIR / "reconciliation"
LIVE_GATE_DIR = OUTPUTS_DIR / "live_gate"
SUBMIT_DIR = OUTPUTS_DIR / "submit_preview"
LOGS_DIR = OUTPUTS_DIR / "logs"

LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"
TRADING_OPERATION_MODE_PATH = DEFAULT_TRADING_OPERATION_MODE_PATH

SNAPSHOT_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot.json"
SNAPSHOT_QUALITY_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot_quality.json"
SNAPSHOT_MANIFEST_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot_manifest.json"
STATUS_PATH = LIVE_STATUS_DIR / "execution_status.json"
DRY_RUN_DECISION_PATH = DRY_RUN_DIR / "latest_dry_run_decision.json"
RECON_PATH = RECON_DIR / "latest_reconciliation_report.json"
GATE_PATH = LIVE_GATE_DIR / "latest_real_order_gate_decision.json"
SUBMIT_PREVIEW_DECISION_PATH = SUBMIT_DIR / "latest_submit_preview_decision.json"
SUBMIT_EXCHANGE_RESPONSE_PATH = SUBMIT_DIR / "latest_submit_exchange_response.json"
SUBMIT_POST_SNAPSHOT_PATH = SUBMIT_DIR / "latest_submit_post_snapshot.json"
POST_SUBMIT_RECON_PATH = SUBMIT_DIR / "latest_post_submit_reconciliation.json"
LOG_PATH = LOGS_DIR / "app_execute_bridge.log"

UI_CONFIRMATION_TEXT = "POTVRDZUJEM VYKONAT OBCHOD"
BACKEND_CONFIRM_TOKEN = "CONTROLLED_REAL_ORDER"

MATERIALIZE_SCRIPT_PATH = ROOT / "scripts" / "execution" / "materialize_execution_app_exports.py"
VALIDATE_CONTRACT_SCRIPT_PATH = ROOT / "scripts" / "execution" / "validate_execution_source_contract.py"
RENDER_STATUS_SCRIPT_PATH = ROOT / "scripts" / "execution" / "render_execution_app_status.py"
BUILD_INTENT_SCRIPT_PATH = ROOT / "scripts" / "execution" / "build_execution_intent_from_strategy_exports.py"
DRY_RUN_SCRIPT_PATH = ROOT / "scripts" / "execution" / "run_dry_execution_bridge.py"
RECONCILE_SCRIPT_PATH = ROOT / "scripts" / "execution" / "reconcile_live_execution_state.py"
PREPARE_GATE_SCRIPT_PATH = ROOT / "scripts" / "execution" / "prepare_real_order_gate.py"
SUBMIT_SCRIPT_PATH = ROOT / "scripts" / "execution" / "submit_controlled_real_order.py"

ALLOWLISTED_ACTIONS = {
    "dry_run",
    "get_mode",
    "live_execute",
    "refresh",
    "set_automatic_mode",
    "set_manual_mode",
}
ALLOWLISTED_SCRIPTS = {
    MATERIALIZE_SCRIPT_PATH.resolve(),
    VALIDATE_CONTRACT_SCRIPT_PATH.resolve(),
    RENDER_STATUS_SCRIPT_PATH.resolve(),
    BUILD_INTENT_SCRIPT_PATH.resolve(),
    DRY_RUN_SCRIPT_PATH.resolve(),
    RECONCILE_SCRIPT_PATH.resolve(),
    PREPARE_GATE_SCRIPT_PATH.resolve(),
    SUBMIT_SCRIPT_PATH.resolve(),
}
LIVE_ORDER_ACTIONS = {
    "simulate_enter_target_asset",
    "simulate_exit_to_cash",
    "simulate_rotate_position",
}
LIVE_SUCCESS_STATUSES = {"submitted", "filled", "resting"}


class AppBridgeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: str = "failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.details = details or {}


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def log(message: str) -> None:
    print(message)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AppBridgeError(f"Missing required file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AppBridgeError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AppBridgeError(f"Expected JSON object in {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sanitize_output(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return None


def get_nested_value(payload: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def dedupe_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def format_utc_for_summary(value: Any) -> str:
    text = str(value or "").strip()
    return text or "neznamy cas"


def run_allowlisted_script(
    *,
    script_path: Path,
    step_name: str,
    arguments: list[str] | None = None,
    timeout_sec: int = 300,
) -> dict[str, Any]:
    resolved_path = script_path.resolve()
    if resolved_path not in ALLOWLISTED_SCRIPTS:
        raise AppBridgeError(
            f"Script is not allowlisted for app bridge: {resolved_path}",
            status="failed",
        )

    command = [sys.executable, str(resolved_path), *(arguments or [])]
    started_at_utc = utc_now_iso()
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppBridgeError(
            f"{step_name} timed out after {timeout_sec} seconds.",
            status="failed",
            details={
                "step_name": step_name,
                "script_path": str(resolved_path),
                "command": command,
                "timeout_sec": timeout_sec,
            },
        ) from exc

    stdout_text = sanitize_output(result.stdout or "")
    stderr_text = sanitize_output(result.stderr or "")
    step_result = {
        "step_name": step_name,
        "script_path": str(resolved_path),
        "command": command,
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "returncode": int(result.returncode),
        "ok": result.returncode == 0,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }
    if result.returncode != 0:
        raise AppBridgeError(
            f"{step_name} failed with exit code {result.returncode}: "
            f"{stderr_text or stdout_text or 'no output'}",
            status="failed",
            details={"failed_step": step_result},
        )
    return step_result


def load_account_address() -> str:
    account_cfg = read_json(ACCOUNT_CONFIG_PATH)
    account_address = str(account_cfg.get("account_address", "")).strip()
    if not account_address:
        raise AppBridgeError(
            f"{ACCOUNT_CONFIG_PATH} missing account_address required for operational refresh",
            status="failed",
        )
    return account_address


def extract_current_position(payload: dict[str, Any]) -> str:
    open_position = payload.get("open_position")
    if isinstance(open_position, dict):
        symbol = normalize_asset(open_position.get("symbol"))
        if symbol:
            return symbol
    return normalize_asset(payload.get("current_position")) or "CASH"


def build_operational_snapshot_artifacts() -> dict[str, Any]:
    account_address = load_account_address()
    mode_cfg = read_json(MODE_CONFIG_PATH)

    state = fetch_user_state(account_address)
    spot_state = fetch_spot_user_state(account_address)
    open_orders = fetch_open_orders(account_address)
    user_fills = info_request({"type": "userFills", "user": account_address})
    if not isinstance(user_fills, list):
        user_fills = []

    summary = summarize_snapshot(account_address, state, spot_state, open_orders)
    snapshot = {
        "snapshot_type": "hyperliquid_read_only_account_snapshot",
        "as_of_utc": utc_now_iso(),
        "execution_mode": str(mode_cfg.get("mode") or "").strip() or "unknown",
        "trading_enabled": bool(mode_cfg.get("trading_enabled", False)),
        "kill_switch": bool(mode_cfg.get("kill_switch", True)),
        "account_address": account_address,
        "source": {
            "provider": "Hyperliquid",
            "info_url": "https://api.hyperliquid.xyz/info",
            "bridge_source": "scripts/execution/app_execute_bridge.py",
        },
        "raw": {
            "clearinghouseState": state,
            "spotClearinghouseState": spot_state,
            "openOrders": open_orders,
            "userFills": user_fills,
        },
        "summary": {
            "positions_count": summary.get("positions_count"),
            "open_orders_count": summary.get("open_orders_count"),
            "recent_fills_count": len(user_fills),
            "withdrawable": summary.get("withdrawable"),
            "margin_summary": summary.get("margin_summary"),
            "cross_margin_summary": summary.get("cross_margin_summary"),
            "balance_source_of_truth": summary.get("balance_source_of_truth"),
            "account_equity_usd": summary.get("account_equity_usd"),
            "available_balance_usd": summary.get("available_balance_usd"),
            "perp_account_value": summary.get("perp_account_value"),
            "perp_withdrawable": summary.get("perp_withdrawable"),
            "spot_balance_count": summary.get("spot_balance_count"),
            "spot_balance_symbols": summary.get("spot_balance_symbols"),
            "spot_stable_total_usd": summary.get("spot_stable_total_usd"),
            "spot_stable_available_usd": summary.get("spot_stable_available_usd"),
            "spot_source_available": summary.get("spot_source_available"),
        },
    }
    quality = {
        "snapshot_ok": True,
        "mode": snapshot["execution_mode"],
        "trading_enabled": snapshot["trading_enabled"],
        "kill_switch": snapshot["kill_switch"],
        "account_address_present": True,
        "positions_count": snapshot["summary"]["positions_count"],
        "open_orders_count": snapshot["summary"]["open_orders_count"],
        "recent_fills_count": snapshot["summary"]["recent_fills_count"],
        "balance_source_of_truth": snapshot["summary"]["balance_source_of_truth"],
        "account_equity_usd": snapshot["summary"]["account_equity_usd"],
        "available_balance_usd": snapshot["summary"]["available_balance_usd"],
    }
    manifest = {
        "artifact_name": "hyperliquid_account_snapshot_from_app_bridge",
        "generated_at_utc": utc_now_iso(),
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(ACCOUNT_CONFIG_PATH.resolve()),
            str(MODE_CONFIG_PATH.resolve()),
        ],
        "output_paths": [
            str(SNAPSHOT_PATH.resolve()),
            str(SNAPSHOT_QUALITY_PATH.resolve()),
            str(SNAPSHOT_MANIFEST_PATH.resolve()),
        ],
        "status": "success",
    }

    write_json(SNAPSHOT_PATH, snapshot)
    write_json(SNAPSHOT_QUALITY_PATH, quality)
    write_json(SNAPSHOT_MANIFEST_PATH, manifest)

    return {
        "step_name": "refresh_operational_snapshot",
        "ok": True,
        "snapshot_path": str(SNAPSHOT_PATH.resolve()),
        "quality_path": str(SNAPSHOT_QUALITY_PATH.resolve()),
        "manifest_path": str(SNAPSHOT_MANIFEST_PATH.resolve()),
        "account_address": account_address,
        "mode": snapshot["execution_mode"],
        "trading_enabled": snapshot["trading_enabled"],
        "kill_switch": snapshot["kill_switch"],
        "finished_at_utc": utc_now_iso(),
    }


def summarize_refresh_artifacts(steps: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot = read_json(SNAPSHOT_PATH)
    status_payload = read_json(STATUS_PATH)
    current_position = extract_current_position(status_payload)
    open_orders_count = status_payload.get("open_orders_count")
    recent_fills_count = status_payload.get("recent_fills_count")
    as_of_utc = format_utc_for_summary(
        status_payload.get("as_of_utc") or snapshot.get("as_of_utc")
    )

    return {
        "status": "refreshed",
        "steps": steps,
        "artifact_paths": {
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
            "status_path": str(STATUS_PATH.resolve()),
        },
        "result_summary": {
            "as_of_utc": status_payload.get("as_of_utc") or snapshot.get("as_of_utc"),
            "mode": status_payload.get("mode") or snapshot.get("execution_mode"),
            "trading_enabled": status_payload.get("trading_enabled"),
            "kill_switch": status_payload.get("kill_switch"),
            "current_position": current_position,
            "open_orders_count": open_orders_count,
            "recent_fills_count": recent_fills_count,
            "account_equity_usd": status_payload.get("account_equity_usd"),
            "available_balance_usd": status_payload.get("available_balance_usd"),
        },
        "user_summary": (
            "Refresh hotovy: "
            f"pozicia {current_position}, otvorene prikazy {open_orders_count}, "
            f"posledny sync {as_of_utc}."
        ),
    }


def summarize_dry_run_artifacts(steps: list[dict[str, Any]]) -> dict[str, Any]:
    dry_run_payload = read_json(DRY_RUN_DECISION_PATH)
    gate_payload = read_json(GATE_PATH)
    recon_payload = read_json(RECON_PATH)

    recommended_action = str(dry_run_payload.get("recommended_action") or "").strip()
    target_asset = normalize_asset(dry_run_payload.get("target_asset")) or "N/A"
    would_place_order = bool(
        get_nested_value(dry_run_payload, "simulated_order", "would_place_order")
    )
    gate_status = str(gate_payload.get("status") or "").strip() or "neznamy"

    if would_place_order:
        summary = (
            "Dry-run hotovy: "
            f"odporucana akcia {recommended_action}, cielovy asset {target_asset}, "
            "realny order by sa podla dry-run path pripravil."
        )
        dry_run_status = "dry_run_ready"
    else:
        summary = (
            "Dry-run hotovy: "
            f"odporucana akcia {recommended_action or 'neznamy stav'}, "
            "dry-run neukazuje potrebu realneho submitu."
        )
        dry_run_status = "dry_run_no_action"

    return {
        "status": dry_run_status,
        "steps": steps,
        "artifact_paths": {
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
            "status_path": str(STATUS_PATH.resolve()),
            "dry_run_decision_path": str(DRY_RUN_DECISION_PATH.resolve()),
            "reconciliation_path": str(RECON_PATH.resolve()),
            "gate_path": str(GATE_PATH.resolve()),
        },
        "result_summary": {
            "generated_at_utc": dry_run_payload.get("generated_at_utc"),
            "recommended_action": recommended_action,
            "target_asset": target_asset,
            "would_place_order": would_place_order,
            "gate_status": gate_status,
            "current_state": recon_payload.get("current_state"),
            "reconciled": recon_payload.get("reconciled"),
        },
        "user_summary": summary,
    }


def summarize_trading_operation_mode_action(
    *,
    action: str,
    mode_payload: dict[str, Any],
    step_name: str,
) -> dict[str, Any]:
    mode = str(mode_payload.get("mode") or "").strip().lower() or "manual"
    fail_closed = bool(mode_payload.get("fail_closed", False))
    updated_at_utc = str(mode_payload.get("updated_at_utc") or "").strip()
    updated_by = str(mode_payload.get("updated_by") or "").strip() or "system"
    error = str(mode_payload.get("error") or "").strip()

    if action == "get_mode":
        if fail_closed:
            user_summary = (
                "Rezim obchodovania sa nepodarilo nacitat. "
                "System fail-closed pouziva manualny rezim."
            )
        else:
            user_summary = (
                "Aktualny rezim obchodovania je "
                + ("automaticky." if mode == "automatic" else "manualny.")
            )
    else:
        user_summary = (
            "Rezim obchodovania je nastaveny na "
            + ("automaticke obchody." if mode == "automatic" else "manualne obchody.")
        )

    return {
        "status": "mode_loaded" if action == "get_mode" else "mode_updated",
        "steps": [
            {
                "step_name": step_name,
                "ok": not fail_closed if action == "get_mode" else True,
                "mode": mode,
                "fail_closed": fail_closed,
                "updated_at_utc": updated_at_utc,
                "updated_by": updated_by,
                "error": error or None,
                "path": str(TRADING_OPERATION_MODE_PATH.resolve()),
            }
        ],
        "artifact_paths": {
            "trading_operation_mode_path": str(TRADING_OPERATION_MODE_PATH.resolve()),
        },
        "result_summary": {
            "mode": mode,
            "updated_at_utc": updated_at_utc,
            "updated_by": updated_by,
            "fail_closed": fail_closed,
            "error": error or None,
        },
        "user_summary": user_summary,
    }


def run_get_mode_action() -> dict[str, Any]:
    return summarize_trading_operation_mode_action(
        action="get_mode",
        mode_payload=load_trading_operation_mode_payload(TRADING_OPERATION_MODE_PATH),
        step_name="read_trading_operation_mode",
    )


def run_set_mode_action(mode: str) -> dict[str, Any]:
    return summarize_trading_operation_mode_action(
        action=f"set_{mode}_mode",
        mode_payload=write_trading_operation_mode_payload(
            mode,
            updated_by="app",
            path=TRADING_OPERATION_MODE_PATH,
        ),
        step_name="write_trading_operation_mode",
    )


def validate_live_submit_readiness() -> dict[str, Any]:
    mode_cfg = read_json(MODE_CONFIG_PATH)
    policy_cfg = read_json(LIVE_ORDER_POLICY_PATH)
    gate_payload = read_json(GATE_PATH)
    dry_run_payload = read_json(DRY_RUN_DECISION_PATH)

    checks = (
        gate_payload.get("checks", {})
        if isinstance(gate_payload.get("checks"), dict)
        else {}
    )
    gate_block_reasons = [
        str(item).strip()
        for item in gate_payload.get("block_reasons", []) or []
        if str(item).strip()
    ]
    recommended_action = str(dry_run_payload.get("recommended_action") or "").strip()
    target_asset = normalize_asset(dry_run_payload.get("target_asset"))
    dry_run_would_place_order = as_bool(
        get_nested_value(dry_run_payload, "simulated_order", "would_place_order")
    )

    reasons: list[str] = []

    if str(mode_cfg.get("mode") or "").strip().lower() != "live":
        reasons.append("execution_mode.json nema mode=live.")
    if as_bool(mode_cfg.get("trading_enabled")) is not True:
        reasons.append("execution_mode.json nema trading_enabled=true.")
    if as_bool(policy_cfg.get("allow_live_orders")) is not True:
        reasons.append("live_order_policy.json nema allow_live_orders=true.")
    if as_bool(policy_cfg.get("manual_approval_required")) is True:
        reasons.append("live_order_policy.json stale vyzaduje manual_approval_required=true.")
    if (
        as_bool(policy_cfg.get("require_kill_switch_off")) is True
        and as_bool(mode_cfg.get("kill_switch")) is True
    ):
        reasons.append("live_order_policy.json vyzaduje kill_switch=false.")

    gate_status = str(gate_payload.get("status") or "").strip()
    if gate_status != "ready_if_enabled":
        reasons.append(
            f"latest_real_order_gate_decision.json nema status ready_if_enabled (je {gate_status or 'neznamy'})."
        )
    if as_bool(gate_payload.get("would_place_real_order")) is not True:
        reasons.append("latest_real_order_gate_decision.json nema would_place_real_order=true.")
    if as_bool(checks.get("approval_status_allowed")) is not True:
        reasons.append("Gate nepotvrdzuje approval_status_allowed=true.")
    if as_bool(checks.get("execution_trading_enabled")) is not True:
        reasons.append("Gate nepotvrdzuje execution_trading_enabled=true.")
    if as_bool(checks.get("allow_live_orders")) is not True:
        reasons.append("Gate nepotvrdzuje allow_live_orders=true.")
    if as_bool(checks.get("account_address_present")) is not True:
        reasons.append("Gate nepotvrdzuje account_address_present=true.")
    if as_bool(checks.get("leverage_live_truth_allowed")) is not True:
        reasons.append("Gate nepotvrdzuje leverage_live_truth_allowed=true.")
    reasons.extend(gate_block_reasons)

    if not target_asset:
        reasons.append("latest_dry_run_decision.json nema target_asset.")
    if dry_run_would_place_order is not True:
        reasons.append(
            "latest_dry_run_decision.json neukazuje realny order path "
            f"(recommended_action={recommended_action or 'neznamy'})."
        )
    if recommended_action not in LIVE_ORDER_ACTIONS:
        reasons.append(
            "latest_dry_run_decision.json nema live-submit odporucanie "
            f"(recommended_action={recommended_action or 'neznamy'})."
        )
    if as_bool(dry_run_payload.get("stale_signal")) is True:
        reasons.append("latest_dry_run_decision.json hlasi stale_signal=true.")
    if as_bool(dry_run_payload.get("duplicate_order_risk")) is True:
        reasons.append("latest_dry_run_decision.json hlasi duplicate_order_risk=true.")
    if as_bool(get_nested_value(dry_run_payload, "guardrails", "contract_validated")) is not True:
        reasons.append("latest_dry_run_decision.json nema guardrails.contract_validated=true.")

    reasons = dedupe_texts(reasons)
    validation = {
        "mode_config_path": str(MODE_CONFIG_PATH.resolve()),
        "live_order_policy_path": str(LIVE_ORDER_POLICY_PATH.resolve()),
        "gate_path": str(GATE_PATH.resolve()),
        "dry_run_path": str(DRY_RUN_DECISION_PATH.resolve()),
        "mode": mode_cfg.get("mode"),
        "trading_enabled": mode_cfg.get("trading_enabled"),
        "kill_switch": mode_cfg.get("kill_switch"),
        "allow_live_orders": policy_cfg.get("allow_live_orders"),
        "manual_approval_required": policy_cfg.get("manual_approval_required"),
        "gate_status": gate_status,
        "gate_would_place_real_order": gate_payload.get("would_place_real_order"),
        "gate_leverage_live_truth_allowed": checks.get("leverage_live_truth_allowed"),
        "dry_run_recommended_action": recommended_action,
        "dry_run_target_asset": target_asset,
        "dry_run_would_place_order": dry_run_would_place_order,
        "block_reasons": reasons,
        "ok": not reasons,
    }
    if reasons:
        raise AppBridgeError(
            "Live execute zablokovane: " + " | ".join(reasons),
            status="blocked",
            details={
                "validation": validation,
                "block_reasons": reasons,
                "user_summary": "Live execute zablokovane. " + " | ".join(reasons),
            },
        )
    return validation


def summarize_live_submit_artifacts(
    steps: list[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    decision = read_json(SUBMIT_PREVIEW_DECISION_PATH)
    exchange_response = read_json(SUBMIT_EXCHANGE_RESPONSE_PATH)
    post_snapshot = read_json(SUBMIT_POST_SNAPSHOT_PATH)
    post_recon = read_json(POST_SUBMIT_RECON_PATH)

    submit_status = str(decision.get("status") or "").strip() or "unknown"
    submit_block_reasons = dedupe_texts(
        [
            str(item).strip()
            for item in decision.get("submit_block_reasons", []) or []
            if str(item).strip()
        ]
    )
    submit_steps = decision.get("submit_plan", {}).get("steps", [])
    order_step_present = any(
        isinstance(step, dict) and str(step.get("step_type") or "").strip() == "order"
        for step in submit_steps
    )
    leverage_step_present = any(
        isinstance(step, dict) and str(step.get("step_type") or "").strip() == "leverage_update"
        for step in submit_steps
    )
    action_results = exchange_response.get("action_results", [])
    action_results_count = len(action_results) if isinstance(action_results, list) else 0
    order_oids = get_nested_value(post_recon, "order_oids")
    order_oids_count = len(order_oids) if isinstance(order_oids, list) else 0
    fills_count = get_nested_value(post_recon, "fills_summary", "fills_count")
    final_state_after = str(post_recon.get("current_state_after") or "").strip() or "unknown"
    real_exchange_action_sent = action_results_count > 0

    if submit_block_reasons:
        raise AppBridgeError(
            "Controlled submit vratil block reasons: " + " | ".join(submit_block_reasons),
            status="blocked",
            details={
                "validation": validation,
                "block_reasons": submit_block_reasons,
                "submit_status": submit_status,
                "user_summary": "Live execute zablokovane po submit path validacii. "
                + " | ".join(submit_block_reasons),
            },
        )

    if not real_exchange_action_sent:
        raise AppBridgeError(
            "Controlled submit neodoslal ziadnu realnu backend akciu.",
            status="blocked",
            details={
                "validation": validation,
                "submit_status": submit_status,
                "block_reasons": [
                    "submit_controlled_real_order.py nevratil ziadne exchange action_results."
                ],
                "user_summary": (
                    "Live execute neskoncil realnou backend akciou. "
                    "Skontroluj submit preview artefakty."
                ),
            },
        )

    if submit_status not in LIVE_SUCCESS_STATUSES:
        raise AppBridgeError(
            f"Controlled submit skoncil stavom {submit_status}.",
            status=submit_status,
            details={
                "validation": validation,
                "submit_status": submit_status,
                "user_summary": (
                    f"Live execute skoncil stavom {submit_status}. "
                    "Skontroluj post-submit artefakty."
                ),
            },
        )

    if order_step_present:
        action_text = "bola odoslana order akcia"
    elif leverage_step_present:
        action_text = "bola odoslana iba leverage update akcia, nie order"
    else:
        action_text = "bola odoslana backend akcia"

    user_summary = (
        "Live execute hotovy: "
        f"{action_text}, status {submit_status}, "
        f"cielovy asset {normalize_asset(decision.get('target_asset')) or 'N/A'}, "
        f"stav po akcii {final_state_after}."
    )

    return {
        "status": submit_status,
        "steps": steps,
        "artifact_paths": {
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
            "status_path": str(STATUS_PATH.resolve()),
            "dry_run_decision_path": str(DRY_RUN_DECISION_PATH.resolve()),
            "reconciliation_path": str(RECON_PATH.resolve()),
            "gate_path": str(GATE_PATH.resolve()),
            "submit_preview_decision_path": str(SUBMIT_PREVIEW_DECISION_PATH.resolve()),
            "submit_exchange_response_path": str(SUBMIT_EXCHANGE_RESPONSE_PATH.resolve()),
            "submit_post_snapshot_path": str(SUBMIT_POST_SNAPSHOT_PATH.resolve()),
            "post_submit_reconciliation_path": str(POST_SUBMIT_RECON_PATH.resolve()),
        },
        "validation": validation,
        "result_summary": {
            "submit_status": submit_status,
            "target_asset": decision.get("target_asset"),
            "target_regime": decision.get("target_regime"),
            "current_state_after": post_recon.get("current_state_after"),
            "action_results_count": action_results_count,
            "order_oids_count": order_oids_count,
            "fills_count": fills_count,
            "order_step_present": order_step_present,
            "leverage_step_present": leverage_step_present,
            "generated_at_utc": decision.get("generated_at_utc"),
            "post_snapshot_as_of_utc": post_snapshot.get("as_of_utc"),
        },
        "user_summary": user_summary,
    }


def run_refresh_action() -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    steps.append(build_operational_snapshot_artifacts())
    steps.append(
        run_allowlisted_script(
            script_path=RENDER_STATUS_SCRIPT_PATH,
            step_name="render_execution_app_status",
        )
    )
    return summarize_refresh_artifacts(steps)


def run_dry_run_action() -> dict[str, Any]:
    refresh_result = run_refresh_action()
    steps = list(refresh_result["steps"])
    steps.append(
        run_allowlisted_script(
            script_path=MATERIALIZE_SCRIPT_PATH,
            step_name="materialize_execution_app_exports",
        )
    )
    steps.append(
        run_allowlisted_script(
            script_path=VALIDATE_CONTRACT_SCRIPT_PATH,
            step_name="validate_execution_source_contract",
        )
    )
    steps.append(
        run_allowlisted_script(
            script_path=BUILD_INTENT_SCRIPT_PATH,
            step_name="build_execution_intent_from_strategy_exports",
        )
    )
    steps.append(
        run_allowlisted_script(
            script_path=DRY_RUN_SCRIPT_PATH,
            step_name="run_dry_execution_bridge",
        )
    )
    steps.append(
        run_allowlisted_script(
            script_path=RECONCILE_SCRIPT_PATH,
            step_name="reconcile_live_execution_state",
        )
    )
    steps.append(
        run_allowlisted_script(
            script_path=PREPARE_GATE_SCRIPT_PATH,
            step_name="prepare_real_order_gate",
        )
    )
    return summarize_dry_run_artifacts(steps)


def run_live_execute_action(
    *,
    ui_confirmation_text: str,
    backend_confirm_token: str,
) -> dict[str, Any]:
    if ui_confirmation_text.strip() != UI_CONFIRMATION_TEXT:
        raise AppBridgeError(
            "Live execute zablokovane: potvrdenie v UI sa nezhoduje s presnym textom.",
            status="blocked",
            details={
                "block_reasons": ["ui_confirmation_text_mismatch"],
                "user_summary": (
                    "Live execute zablokovane. Potvrdzovaci text sa nezhoduje s pozadovanym textom."
                ),
            },
        )
    if backend_confirm_token != BACKEND_CONFIRM_TOKEN:
        raise AppBridgeError(
            "Live execute zablokovane: backend confirm token mismatch.",
            status="blocked",
            details={
                "block_reasons": ["backend_confirm_token_mismatch"],
                "user_summary": (
                    "Live execute zablokovane. Backend token sa nezhoduje s allowlistnutym tokenom."
                ),
            },
        )

    dry_run_result = run_dry_run_action()
    steps = list(dry_run_result["steps"])
    validation = validate_live_submit_readiness()
    steps.append(
        run_allowlisted_script(
            script_path=SUBMIT_SCRIPT_PATH,
            step_name="submit_controlled_real_order_live",
            arguments=[
                "--execute-live",
                "--manual-confirm",
                BACKEND_CONFIRM_TOKEN,
            ],
        )
    )
    return summarize_live_submit_artifacts(steps, validation)


def run_app_execute_action(
    *,
    action: str,
    ui_confirmation_text: str = "",
    backend_confirm_token: str = "",
) -> dict[str, Any]:
    started_at_utc = utc_now_iso()
    normalized_action = str(action or "").strip().lower()
    result: dict[str, Any] = {
        "action": normalized_action,
        "started_at_utc": started_at_utc,
        "finished_at_utc": started_at_utc,
        "ok": False,
        "status": "blocked",
        "steps": [],
        "artifact_paths": {},
        "result_summary": {},
        "block_reasons": [],
        "error": None,
        "user_summary": "",
    }

    try:
        if normalized_action not in ALLOWLISTED_ACTIONS:
            raise AppBridgeError(
                f"Unsupported app execute action: {normalized_action or 'missing'}",
                status="blocked",
                details={
                    "block_reasons": [f"unsupported_action:{normalized_action or 'missing'}"],
                    "user_summary": "APP bridge nepodporuje pozadovanu akciu.",
                },
            )

        if normalized_action == "get_mode":
            payload = run_get_mode_action()
        elif normalized_action == "set_manual_mode":
            payload = run_set_mode_action("manual")
        elif normalized_action == "set_automatic_mode":
            payload = run_set_mode_action("automatic")
        elif normalized_action == "refresh":
            payload = run_refresh_action()
        elif normalized_action == "dry_run":
            payload = run_dry_run_action()
        else:
            payload = run_live_execute_action(
                ui_confirmation_text=ui_confirmation_text,
                backend_confirm_token=backend_confirm_token,
            )

        result.update(payload)
        result["ok"] = True
        result["status"] = str(payload.get("status") or "success")
    except AppBridgeError as exc:
        result["error"] = str(exc)
        result["status"] = exc.status
        result.update(exc.details)
    except SystemExit as exc:
        result["error"] = (
            "Execution bridge child path exited early with SystemExit "
            f"code={exc.code}."
        )
        result["status"] = "failed"
        result["user_summary"] = (
            "Akcia zlyhala v podriadenej execution vetve. "
            "Skontroluj execution logy a posledne artefakty."
        )
    except Exception as exc:  # pragma: no cover - defensive fallback only
        result["error"] = str(exc)
        result["status"] = "failed"
    finally:
        result["finished_at_utc"] = utc_now_iso()
        result["block_reasons"] = dedupe_texts(
            [
                str(item).strip()
                for item in result.get("block_reasons", []) or []
                if str(item).strip()
            ]
        )
        result["user_summary"] = str(
            result.get("user_summary")
            or result.get("error")
            or f"Akcia {normalized_action or 'unknown'} sa skoncila bez summary."
        ).strip()

    log(
        "[APP_EXECUTE] "
        f"action={result['action']} status={result['status']} error={result['error'] or 'none'}"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "App-facing execution bridge for operational refresh, dry-run recompute, "
            "and one-shot live submit via the controlled backend path."
        )
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=sorted(ALLOWLISTED_ACTIONS),
        help="Bridge action to run.",
    )
    parser.add_argument(
        "--ui-confirmation-text",
        default="",
        help="Required exact UI confirmation text for live_execute.",
    )
    parser.add_argument(
        "--backend-confirm-token",
        default="",
        help="Required backend token for live_execute.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_app_execute_action(
        action=args.action,
        ui_confirmation_text=args.ui_confirmation_text,
        backend_confirm_token=args.backend_confirm_token,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
