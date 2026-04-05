from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

EXECUTION_DIR = ROOT / "execution"
CONFIG_DIR = EXECUTION_DIR / "config"
OUTPUTS_DIR = ROOT / "outputs" / "execution"

MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"

INTENT_PATH = OUTPUTS_DIR / "intents" / "latest_execution_intent.json"
SNAPSHOT_PATH = OUTPUTS_DIR / "read_only" / "hyperliquid_account_snapshot.json"
GATE_PATH = OUTPUTS_DIR / "live_gate" / "latest_real_order_gate_decision.json"
RECON_PATH = OUTPUTS_DIR / "reconciliation" / "latest_reconciliation_report.json"

SUBMIT_DIR = OUTPUTS_DIR / "submit_preview"
LOGS_DIR = OUTPUTS_DIR / "logs"

DECISION_PATH = SUBMIT_DIR / "latest_submit_preview_decision.json"
QUALITY_PATH = SUBMIT_DIR / "latest_submit_preview_quality.json"
MANIFEST_PATH = SUBMIT_DIR / "latest_submit_preview_manifest.json"
LOG_PATH = LOGS_DIR / "submit_controlled_real_order.log"


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def log(msg: str) -> None:
    print(msg)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def fail(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"Invalid JSON in {path}: {e}")
    except Exception as e:
        fail(f"Failed reading {path}: {e}")
    raise RuntimeError("unreachable")


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def main() -> None:
    SUBMIT_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] submit_controlled_real_order")

    mode_cfg = read_json(MODE_CONFIG_PATH)
    policy_cfg = read_json(LIVE_ORDER_POLICY_PATH)
    intent = read_json(INTENT_PATH)
    snapshot = read_json(SNAPSHOT_PATH)
    gate = read_json(GATE_PATH)
    recon = read_json(RECON_PATH)

    signal_id = str(intent.get("signal_id", "")).strip()
    target_asset = normalize_asset(intent.get("target_asset"))
    target_regime = str(intent.get("target_regime", "")).strip()

    mode = str(mode_cfg.get("mode", "")).strip()
    execution_trading_enabled = bool(mode_cfg.get("trading_enabled", False))
    kill_switch = bool(mode_cfg.get("kill_switch", True))

    allow_live_orders = bool(policy_cfg.get("allow_live_orders", False))
    manual_approval_required = bool(policy_cfg.get("manual_approval_required", True))
    require_kill_switch_off = bool(policy_cfg.get("require_kill_switch_off", True))
    max_order_notional_usd = float(policy_cfg.get("max_order_notional_usd", 0.0))
    allowed_assets = {
        normalize_asset(x) for x in policy_cfg.get("allowed_assets", [])
        if str(x).strip()
    }
    allowed_approval_gate_statuses = {
        str(x).strip() for x in policy_cfg.get("allowed_approval_gate_statuses", [])
        if str(x).strip()
    }

    gate_status = str(gate.get("status", "")).strip()
    gate_block_reasons = gate.get("block_reasons", []) if isinstance(gate.get("block_reasons"), list) else []
    approval_gate_status = str(gate.get("approval_gate_status", "")).strip()

    reconciled = bool(recon.get("reconciled", False))
    current_state = normalize_asset(recon.get("current_state"))
    open_orders_count = int(recon.get("open_orders_count", 0))

    account_address = str(snapshot.get("account_address", "")).strip()

    checks = {
        "signal_present": bool(signal_id),
        "target_asset_present": bool(target_asset),
        "target_asset_allowed": target_asset in allowed_assets if target_asset else False,
        "gate_file_present": True,
        "gate_status": gate_status,
        "gate_is_ready": gate_status == "ready_if_enabled",
        "gate_block_reason_count": len(gate_block_reasons),
        "approval_gate_status": approval_gate_status,
        "approval_status_allowed": approval_gate_status in allowed_approval_gate_statuses,
        "reconciliation_present": True,
        "reconciled": reconciled,
        "current_state": current_state,
        "open_orders_count": open_orders_count,
        "mode_known": bool(mode),
        "execution_trading_enabled": execution_trading_enabled,
        "allow_live_orders": allow_live_orders,
        "kill_switch": kill_switch,
        "require_kill_switch_off": require_kill_switch_off,
        "manual_approval_required": manual_approval_required,
        "max_order_notional_usd": max_order_notional_usd,
        "account_address_present": bool(account_address),
    }

    block_reasons: list[str] = []

    if not checks["signal_present"]:
        block_reasons.append("missing_signal_id")
    if not checks["target_asset_present"]:
        block_reasons.append("missing_target_asset")
    if not checks["target_asset_allowed"]:
        block_reasons.append("target_asset_not_allowlisted")
    if not checks["approval_status_allowed"]:
        block_reasons.append(f"approval_gate_status={approval_gate_status}")
    if not checks["reconciled"]:
        block_reasons.append("reconciliation_not_passed")
    if checks["open_orders_count"] > 0:
        block_reasons.append("open_orders_present")
    if checks["require_kill_switch_off"] and checks["kill_switch"]:
        block_reasons.append("kill_switch_enabled")
    if checks["manual_approval_required"]:
        block_reasons.append("manual_approval_required")
    if checks["max_order_notional_usd"] <= 0:
        block_reasons.append("max_order_notional_not_enabled")
    if not checks["allow_live_orders"]:
        block_reasons.append("allow_live_orders=false")
    if not checks["execution_trading_enabled"]:
        block_reasons.append("execution_mode_trading_disabled")
    if not checks["account_address_present"]:
        block_reasons.append("missing_account_address")

    # preserve current blocked gate result explicitly
    if gate_status == "blocked":
        if "upstream_gate_blocked" not in block_reasons:
            block_reasons.append("upstream_gate_blocked")

    would_submit = len(block_reasons) == 0

    if would_submit:
        status = "ready_if_enabled"
    else:
        status = "blocked"

    submit_preview = {
        "submit_type": "controlled_real_order_submit_preview",
        "generated_at_utc": utc_now_iso(),
        "signal_id": signal_id,
        "target_asset": target_asset,
        "target_regime": target_regime,
        "account_address": account_address,
        "mode": mode,
        "approval_gate_status": approval_gate_status,
        "status": status,
        "would_submit": would_submit,
        "real_order_sent": False,
        "submit_block_reasons": block_reasons,
        "submit_payload_preview": {
            "exchange": "Hyperliquid",
            "symbol": target_asset,
            "side": None if target_asset == "CASH" else "BUY_OR_RECONCILE",
            "max_order_notional_usd": max_order_notional_usd,
            "execution_profile": "controlled_real_order_preview_only",
        },
        "checks": checks,
        "notes": [
            "Disabled-ready submit skeleton only.",
            "No real order placement is performed by this script.",
            "This layer validates final pre-submit conditions and builds payload preview only.",
            "Submit preview reflects current gate state and policy."
        ],
        "source_paths": {
            "mode_config_path": str(MODE_CONFIG_PATH.resolve()),
            "live_order_policy_path": str(LIVE_ORDER_POLICY_PATH.resolve()),
            "intent_path": str(INTENT_PATH.resolve()),
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
            "gate_path": str(GATE_PATH.resolve()),
            "reconciliation_path": str(RECON_PATH.resolve()),
        },
    }

    quality = {
        "submit_preview_ok": True,
        "status": status,
        "would_submit": would_submit,
        "block_reason_count": len(block_reasons),
        "approval_status_allowed": checks["approval_status_allowed"],
        "reconciled": checks["reconciled"],
        "allow_live_orders": checks["allow_live_orders"],
        "execution_trading_enabled": checks["execution_trading_enabled"],
    }

    manifest = {
        "artifact_name": "latest_submit_preview_decision",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(MODE_CONFIG_PATH.resolve()),
            str(LIVE_ORDER_POLICY_PATH.resolve()),
            str(INTENT_PATH.resolve()),
            str(SNAPSHOT_PATH.resolve()),
            str(GATE_PATH.resolve()),
            str(RECON_PATH.resolve()),
        ],
        "output_paths": [
            str(DECISION_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "status": "success",
    }

    DECISION_PATH.write_text(json.dumps(submit_preview, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {DECISION_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[END] submit_controlled_real_order success status={status}")


if __name__ == "__main__":
    main()