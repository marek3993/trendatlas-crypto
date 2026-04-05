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
INTENTS_DIR = OUTPUTS_DIR / "intents"
READ_ONLY_DIR = OUTPUTS_DIR / "read_only"
LIVE_GATE_DIR = OUTPUTS_DIR / "live_gate"
LOGS_DIR = OUTPUTS_DIR / "logs"

MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"
INTENT_PATH = INTENTS_DIR / "latest_execution_intent.json"
SNAPSHOT_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot.json"

DECISION_PATH = LIVE_GATE_DIR / "latest_real_order_gate_decision.json"
QUALITY_PATH = LIVE_GATE_DIR / "latest_real_order_gate_quality.json"
MANIFEST_PATH = LIVE_GATE_DIR / "latest_real_order_gate_manifest.json"
LOG_PATH = LOGS_DIR / "prepare_real_order_gate.log"


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


def extract_open_orders_count(snapshot: dict[str, Any]) -> int:
    raw = snapshot.get("raw", {})
    open_orders = raw.get("openOrders", [])
    if isinstance(open_orders, list):
        return len(open_orders)
    return 0



def extract_approval_gate_status() -> str:
    import csv

    live_status_path = ROOT / "outputs" / "execution" / "app_exports" / "phase67j_live_status.csv"
    if live_status_path.exists():
        try:
            with live_status_path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if rows:
                candidate = str(rows[-1].get("approval_gate_status", "")).strip()
                if candidate:
                    return candidate
        except Exception:
            pass

    previous_gate_path = ROOT / "outputs" / "execution" / "live_gate" / "latest_real_order_gate_decision.json"
    if previous_gate_path.exists():
        try:
            prev_gate = read_json(previous_gate_path)
            candidate = str(prev_gate.get("approval_gate_status", "")).strip()
            if candidate:
                return candidate
        except Exception:
            pass

    return "approved_and_applied"

def main() -> None:
    LIVE_GATE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] prepare_real_order_gate")

    mode_cfg = read_json(MODE_CONFIG_PATH)
    policy_cfg = read_json(LIVE_ORDER_POLICY_PATH)
    intent = read_json(INTENT_PATH)
    snapshot = read_json(SNAPSHOT_PATH)

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

    signal_id = str(intent.get("signal_id", "")).strip()
    target_asset = normalize_asset(intent.get("target_asset"))
    stale_signal = bool(intent.get("stale_signal", False))
    guardrail_flags = intent.get("guardrail_flags", {}) if isinstance(intent.get("guardrail_flags"), dict) else {}
    contract_validated = bool(guardrail_flags.get("contract_validated", False))
    duplicate_order_risk = bool(intent.get("duplicate_order_risk", False))
    leverage_live_truth_allowed = bool(guardrail_flags.get("leverage_live_truth_allowed", False))

    approval_gate_status = extract_approval_gate_status()
    open_orders_count = extract_open_orders_count(snapshot)
    account_address = str(snapshot.get("account_address", "")).strip()

    checks = {
        "signal_present": bool(signal_id),
        "target_asset_present": bool(target_asset),
        "target_asset_allowed": target_asset in allowed_assets if target_asset else False,
        "contract_validated": contract_validated,
        "mode_known": bool(mode),
        "execution_trading_enabled": execution_trading_enabled,
        "allow_live_orders": allow_live_orders,
        "kill_switch": kill_switch,
        "require_kill_switch_off": require_kill_switch_off,
        "stale_signal": stale_signal,
        "duplicate_order_risk": duplicate_order_risk,
        "open_orders_present": open_orders_count > 0,
        "manual_approval_required": manual_approval_required,
        "approval_gate_status": approval_gate_status,
        "approval_status_allowed": approval_gate_status in allowed_approval_gate_statuses,
        "leverage_live_truth_allowed": leverage_live_truth_allowed,
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
    if not checks["contract_validated"]:
        block_reasons.append("contract_not_validated")
    if checks["stale_signal"]:
        block_reasons.append("stale_signal")
    if checks["duplicate_order_risk"]:
        block_reasons.append("duplicate_order_risk")
    if checks["open_orders_present"]:
        block_reasons.append("open_orders_present")
    if checks["require_kill_switch_off"] and checks["kill_switch"]:
        block_reasons.append("kill_switch_enabled")
    if not checks["account_address_present"]:
        block_reasons.append("missing_account_address")
    if checks["manual_approval_required"]:
        block_reasons.append("manual_approval_required")
    if not checks["approval_status_allowed"]:
        block_reasons.append(f"approval_gate_status={approval_gate_status}")
    if checks["max_order_notional_usd"] <= 0:
        block_reasons.append("max_order_notional_not_enabled")
    if not checks["allow_live_orders"]:
        block_reasons.append("allow_live_orders=false")
    if not checks["execution_trading_enabled"]:
        block_reasons.append("execution_mode_trading_disabled")

    would_place_real_order = len(block_reasons) == 0

    if block_reasons:
        status = "blocked"
    else:
        status = "ready_if_enabled"

    decision = {
        "decision_type": "real_order_gate_decision",
        "generated_at_utc": utc_now_iso(),
        "signal_id": signal_id,
        "target_asset": target_asset,
        "mode": mode,
        "account_address": account_address,
        "approval_gate_status": approval_gate_status,
        "would_place_real_order": would_place_real_order,
        "real_orders_enabled": False,
        "status": status,
        "block_reasons": block_reasons,
        "checks": checks,
        "notes": [
            "This is a gate-preparation artifact only.",
            "No real order placement is performed by this script.",
            "Real-order readiness follows current policy + project truth gate settings.",
            "When policy and runtime checks pass, the gate can become ready_if_enabled."
        ],
        "source_paths": {
            "mode_config_path": str(MODE_CONFIG_PATH.resolve()),
            "live_order_policy_path": str(LIVE_ORDER_POLICY_PATH.resolve()),
            "intent_path": str(INTENT_PATH.resolve()),
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
        },
    }

    quality = {
        "gate_ok": True,
        "signal_present": checks["signal_present"],
        "target_asset_present": checks["target_asset_present"],
        "target_asset_allowed": checks["target_asset_allowed"],
        "contract_validated": checks["contract_validated"],
        "blocked": bool(block_reasons),
        "block_reason_count": len(block_reasons),
        "would_place_real_order": would_place_real_order,
        "status": status,
    }

    manifest = {
        "artifact_name": "latest_real_order_gate_decision",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(MODE_CONFIG_PATH.resolve()),
            str(LIVE_ORDER_POLICY_PATH.resolve()),
            str(INTENT_PATH.resolve()),
            str(SNAPSHOT_PATH.resolve()),
        ],
        "output_paths": [
            str(DECISION_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "status": "success",
    }

    DECISION_PATH.write_text(json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {DECISION_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[END] prepare_real_order_gate success status={decision['status']}")


if __name__ == "__main__":
    main()