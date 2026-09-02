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
    MODE_CONFIG_PATH,
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
SOURCE_CONTRACT_DIR = OUTPUTS_DIR / "source_contract"

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
SOURCE_CONTRACT_REPORT_PATH = SOURCE_CONTRACT_DIR / "execution_source_contract_report.json"
SOURCE_CONTRACT_QUALITY_PATH = SOURCE_CONTRACT_DIR / "execution_source_contract_quality.json"

UI_CONFIRMATION_TEXT = "POTVRDZUJEM VYKONAT OBCHOD"
BACKEND_CONFIRM_TOKEN = "CONTROLLED_REAL_ORDER"

MATERIALIZE_SCRIPT_PATH = ROOT / "scripts" / "execution" / "materialize_execution_app_exports.py"
READ_ONLY_SNAPSHOT_SCRIPT_PATH = ROOT / "scripts" / "execution" / "hyperliquid_read_only_snapshot.py"
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
    READ_ONLY_SNAPSHOT_SCRIPT_PATH.resolve(),
    VALIDATE_CONTRACT_SCRIPT_PATH.resolve(),
    RENDER_STATUS_SCRIPT_PATH.resolve(),
    BUILD_INTENT_SCRIPT_PATH.resolve(),
    DRY_RUN_SCRIPT_PATH.resolve(),
    RECONCILE_SCRIPT_PATH.resolve(),
    PREPARE_GATE_SCRIPT_PATH.resolve(),
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


def extract_current_position(payload: dict[str, Any]) -> str:
    open_position = payload.get("open_position")
    if isinstance(open_position, dict):
        symbol = normalize_asset(open_position.get("symbol"))
        if symbol:
            return symbol
    return normalize_asset(payload.get("current_position")) or "CASH"


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
            "free_collateral_usd": status_payload.get("free_collateral_usd"),
            "available_balance_usd": status_payload.get("available_balance_usd"),
            "withdrawable_usd": status_payload.get("withdrawable_usd"),
            "margin_used_usd": status_payload.get("margin_used_usd"),
            "position_notional_usd": status_payload.get("position_notional_usd"),
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
    source_path = str(
        mode_payload.get("path")
        or mode_payload.get("source_path")
        or TRADING_OPERATION_MODE_PATH.resolve()
    )
    trading_operation_mode = {
        "mode": mode,
        "updated_at_utc": updated_at_utc or None,
        "updated_by": updated_by,
        "fail_closed": fail_closed,
        "error": error or None,
        "source_path": source_path,
        "authority": "execution/config/trading_operation_mode.json",
    }

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
                "path": source_path,
            }
        ],
        "artifact_paths": {
            "trading_operation_mode_path": source_path,
        },
        "trading_operation_mode": trading_operation_mode,
        "result_summary": {
            "mode": mode,
            "updated_at_utc": updated_at_utc,
            "updated_by": updated_by,
            "fail_closed": fail_closed,
            "error": error or None,
            "trading_operation_mode": trading_operation_mode,
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
    steps.append(
        run_allowlisted_script(
            script_path=READ_ONLY_SNAPSHOT_SCRIPT_PATH,
            step_name="refresh_operational_snapshot",
        )
    )
    steps.append(
        run_allowlisted_script(
            script_path=MATERIALIZE_SCRIPT_PATH,
            step_name="materialize_execution_app_runtime_snapshot",
            arguments=["--runtime-snapshot-only"],
        )
    )
    steps.append(
        run_allowlisted_script(
            script_path=RENDER_STATUS_SCRIPT_PATH,
            step_name="render_execution_app_status",
        )
    )
    return summarize_refresh_artifacts(steps)


def run_dry_run_operational_refresh_steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    steps.append(
        run_allowlisted_script(
            script_path=READ_ONLY_SNAPSHOT_SCRIPT_PATH,
            step_name="refresh_operational_snapshot",
        )
    )
    steps.append(
        run_allowlisted_script(
            script_path=RENDER_STATUS_SCRIPT_PATH,
            step_name="render_execution_app_status",
        )
    )
    return steps


def source_contract_block_details(
    *,
    reason: str,
    failed_step: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    block_reasons = ["source_contract_invalid_before_intent_gate"]
    hard_required_missing = []
    if isinstance(report, dict):
        hard_required_missing = [
            str(item)
            for item in report.get("hard_required_missing", []) or []
            if str(item).strip()
        ]
        block_reasons.extend(hard_required_missing)
    details: dict[str, Any] = {
        "block_reasons": dedupe_texts(block_reasons),
        "intent_gate_mutation_status": "not_started",
        "stale_execution_artifacts_usable": False,
        "source_contract_report_path": str(SOURCE_CONTRACT_REPORT_PATH.resolve()),
        "source_contract_quality_path": str(SOURCE_CONTRACT_QUALITY_PATH.resolve()),
        "user_summary": (
            "Dry-run zablokovany pred vytvorenim intent/gate: source contract nie je platny. "
            "Spusti Pi fast daily authority wrapper a publishni aktualne authority/app exporty."
        ),
        "source_contract_failure_reason": reason,
    }
    if failed_step is not None:
        details["failed_step"] = failed_step
    if quality is not None:
        details["source_contract_quality"] = quality
    if report is not None:
        details["source_contract_status"] = report.get("contract_status")
        details["source_contract_hard_required_missing"] = hard_required_missing
    return details


def run_source_contract_preflight(steps: list[dict[str, Any]]) -> None:
    try:
        steps.append(
            run_allowlisted_script(
                script_path=VALIDATE_CONTRACT_SCRIPT_PATH,
                step_name="validate_execution_source_contract",
            )
        )
    except AppBridgeError as exc:
        raise AppBridgeError(
            str(exc),
            status="blocked",
            details=source_contract_block_details(
                reason=str(exc),
                failed_step=exc.details.get("failed_step"),
            ),
        ) from exc

    quality = read_json(SOURCE_CONTRACT_QUALITY_PATH)
    report = read_json(SOURCE_CONTRACT_REPORT_PATH)
    ready = as_bool(quality.get("ready_for_intent_builder"))
    contract_status = str(
        quality.get("contract_status") or report.get("contract_status") or ""
    ).strip().lower()
    if ready is not True or contract_status != "valid":
        reason = (
            "Execution source contract invalid after validation "
            f"(contract_status={contract_status or 'missing'} "
            f"ready_for_intent_builder={quality.get('ready_for_intent_builder')!r})"
        )
        raise AppBridgeError(
            reason,
            status="blocked",
            details=source_contract_block_details(
                reason=reason,
                quality=quality,
                report=report,
            ),
        )


def run_dry_run_action() -> dict[str, Any]:
    steps = run_dry_run_operational_refresh_steps()
    run_source_contract_preflight(steps)
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
    steps.append(
        run_allowlisted_script(
            script_path=MATERIALIZE_SCRIPT_PATH,
            step_name="materialize_execution_app_runtime_snapshot",
            arguments=["--runtime-snapshot-only"],
        )
    )
    return summarize_dry_run_artifacts(steps)


def run_live_execute_action(
    *,
    ui_confirmation_text: str,
    backend_confirm_token: str,
) -> dict[str, Any]:
    del ui_confirmation_text, backend_confirm_token
    raise AppBridgeError(
        "Manual app live execution is intentionally disabled; use the canonical production service.",
        status="blocked",
        details={
            "block_reasons": [
                "manual_app_live_execution_disabled_use_mrv1_production_service"
            ],
            "user_summary": (
                "Ručné odoslanie obchodu z aplikácie je vypnuté. "
                "Live vykonávanie vlastní iba kanonická produkčná služba."
            ),
        },
    )


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
            "and fail-closed redirection of legacy live execution requests."
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
