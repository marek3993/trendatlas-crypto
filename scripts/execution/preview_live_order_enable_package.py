from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]

SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
EXECUTION_DIR = ROOT / "execution"
CONFIG_DIR = EXECUTION_DIR / "config"
OUTPUTS_DIR = ROOT / "outputs" / "execution"

PROJECT_TRUTH_PATH = SOURCE_OF_TRUTH_DIR / "project_truth.json"
CURRENT_ISSUES_PATH = SOURCE_OF_TRUTH_DIR / "current_issues.md"

MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"

INTENT_PATH = OUTPUTS_DIR / "intents" / "latest_execution_intent.json"
SNAPSHOT_PATH = OUTPUTS_DIR / "read_only" / "hyperliquid_account_snapshot.json"
GATE_PATH = OUTPUTS_DIR / "live_gate" / "latest_real_order_gate_decision.json"
RECON_PATH = OUTPUTS_DIR / "reconciliation" / "latest_reconciliation_report.json"
SUBMIT_PREVIEW_PATH = OUTPUTS_DIR / "submit_preview" / "latest_submit_preview_decision.json"

PREVIEW_DIR = OUTPUTS_DIR / "enable_preview"
LOGS_DIR = OUTPUTS_DIR / "logs"

PREVIEW_PATH = PREVIEW_DIR / "live_order_enable_package_preview.json"
QUALITY_PATH = PREVIEW_DIR / "live_order_enable_package_preview_quality.json"
MANIFEST_PATH = PREVIEW_DIR / "live_order_enable_package_preview_manifest.json"
LOG_PATH = LOGS_DIR / "preview_live_order_enable_package.log"

PREVIEW_MAX_ORDER_NOTIONAL_USD = 250.0


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


def bool_or_default(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def main() -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] preview_live_order_enable_package")

    project_truth = read_json(PROJECT_TRUTH_PATH)
    mode_cfg = read_json(MODE_CONFIG_PATH)
    policy_cfg = read_json(LIVE_ORDER_POLICY_PATH)
    intent = read_json(INTENT_PATH)
    snapshot = read_json(SNAPSHOT_PATH)
    gate = read_json(GATE_PATH)
    recon = read_json(RECON_PATH)
    submit_preview = read_json(SUBMIT_PREVIEW_PATH)

    app_live_mode_contract = project_truth.get("app_live_mode_contract", {})
    current_contract = app_live_mode_contract.get("current", {}) if isinstance(app_live_mode_contract, dict) else {}

    current_signal_id = str(intent.get("signal_id", "")).strip()
    current_target_asset = normalize_asset(intent.get("target_asset"))
    current_target_regime = str(intent.get("target_regime", "")).strip()

    current_gate_status = str(gate.get("status", "")).strip()
    current_gate_block_reasons = gate.get("block_reasons", []) if isinstance(gate.get("block_reasons"), list) else []
    current_approval_gate_status = str(gate.get("approval_gate_status", "")).strip()

    current_reconciled = bool_or_default(recon.get("reconciled"), False)
    current_state = normalize_asset(recon.get("current_state"))
    open_orders_count = int(recon.get("open_orders_count", 0))

    current_mode = str(mode_cfg.get("mode", "")).strip()
    current_trading_enabled = bool_or_default(mode_cfg.get("trading_enabled"), False)
    current_kill_switch = bool_or_default(mode_cfg.get("kill_switch"), True)

    current_allow_live_orders = bool_or_default(policy_cfg.get("allow_live_orders"), False)
    current_manual_approval_required = bool_or_default(policy_cfg.get("manual_approval_required"), True)
    current_require_kill_switch_off = bool_or_default(policy_cfg.get("require_kill_switch_off"), True)
    current_allowed_assets = [
        normalize_asset(x)
        for x in policy_cfg.get("allowed_assets", [])
        if str(x).strip()
    ]

    preview_target_values = {
        "approval_gate_status": "live_order_enabled_and_approved",
        "real_order_gate_status": "ready_if_enabled",
        "execution_mode": {
            "mode": "live",
            "trading_enabled": True,
            "kill_switch": False if current_require_kill_switch_off else current_kill_switch,
        },
        "live_order_policy": {
            "allow_live_orders": True,
            "allowed_approval_gate_statuses": ["live_order_enabled_and_approved"],
            "manual_approval_required": True,
            "manual_approval_for_first_order_status": "still_required",
            "require_kill_switch_off": current_require_kill_switch_off,
            "max_order_notional_usd": PREVIEW_MAX_ORDER_NOTIONAL_USD,
            "allowed_assets": current_allowed_assets,
        },
    }

    counterfactual_blockers: list[str] = []

    if not current_signal_id:
        counterfactual_blockers.append("missing_signal_id")
    if not current_target_asset:
        counterfactual_blockers.append("missing_target_asset")
    if current_target_asset not in current_allowed_assets:
        counterfactual_blockers.append("target_asset_not_allowlisted")
    if open_orders_count > 0:
        counterfactual_blockers.append("open_orders_present")
    if not current_reconciled:
        counterfactual_blockers.append("reconciliation_not_passed")

    counterfactual_blockers.append("manual_approval_not_yet_satisfied")

    if current_target_asset == "CASH" and current_state == "CASH":
        counterfactual_blockers.append("no_actionable_order_current_signal_is_cash_and_already_reconciled")

    if current_gate_status == "blocked":
        counterfactual_blockers.append("current_runtime_gate_still_blocked_until_package_is_actually_applied")

    counterfactual_would_submit = len(counterfactual_blockers) == 0

    preview = {
        "artifact_type": "live_order_enable_package_preview",
        "generated_at_utc": utc_now_iso(),
        "current_truth_snapshot": {
            "current_live_truth": project_truth.get("leverage_truth", {}).get("current_live_truth"),
            "current_app_live_mode": current_contract.get("live_truth_mode"),
            "current_approval_gate_status": current_contract.get("approval_gate_status"),
            "current_real_order_eligible_status": current_contract.get("real_order_eligible_status"),
        },
        "affected_files_and_contracts": [
            str(PROJECT_TRUTH_PATH.resolve()),
            str(CURRENT_ISSUES_PATH.resolve()),
            str(MODE_CONFIG_PATH.resolve()),
            str(LIVE_ORDER_POLICY_PATH.resolve()),
            str(INTENT_PATH.resolve()),
            str(SNAPSHOT_PATH.resolve()),
            str(GATE_PATH.resolve()),
            str(RECON_PATH.resolve()),
            str(SUBMIT_PREVIEW_PATH.resolve()),
        ],
        "preview_target_values": preview_target_values,
        "counterfactual_preflight": {
            "signal_id": current_signal_id,
            "target_asset": current_target_asset,
            "target_regime": current_target_regime,
            "current_state": current_state,
            "current_gate_status": current_gate_status,
            "current_gate_block_reasons": current_gate_block_reasons,
            "current_submit_preview_status": submit_preview.get("status"),
            "reconciled": current_reconciled,
            "open_orders_count": open_orders_count,
            "would_submit_if_package_applied_now": counterfactual_would_submit,
            "blockers_if_applied_now": counterfactual_blockers,
        },
        "exact_preflight_checklist_before_future_enable": [
            "approval_gate_status == live_order_enabled_and_approved",
            "real_order_gate_status == ready_if_enabled",
            "execution_mode.trading_enabled == true",
            "live_order_policy.allow_live_orders == true",
            "kill switch policy satisfied",
            "max_order_notional_usd > 0",
            "target asset on allowlist",
            "fresh valid intent exists",
            "account snapshot exists and account address present",
            "open_orders_count == 0",
            "reconciliation passes",
            "manual approval explicitly satisfied for first order",
            "submit preview would_submit == true",
        ],
        "notes": [
            "Preview only. No file is applied by this script.",
            "No trading is enabled by this script.",
            "No real order is placed by this script.",
            "Current blocked state of the real system remains unchanged."
        ],
        "source_paths": {
            "project_truth_path": str(PROJECT_TRUTH_PATH.resolve()),
            "mode_config_path": str(MODE_CONFIG_PATH.resolve()),
            "live_order_policy_path": str(LIVE_ORDER_POLICY_PATH.resolve()),
            "intent_path": str(INTENT_PATH.resolve()),
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
            "gate_path": str(GATE_PATH.resolve()),
            "reconciliation_path": str(RECON_PATH.resolve()),
            "submit_preview_path": str(SUBMIT_PREVIEW_PATH.resolve()),
        },
    }

    quality = {
        "preview_ok": True,
        "current_system_still_blocked": True,
        "counterfactual_would_submit_if_applied_now": counterfactual_would_submit,
        "counterfactual_blocker_count": len(counterfactual_blockers),
        "preview_max_order_notional_usd": PREVIEW_MAX_ORDER_NOTIONAL_USD,
        "manual_approval_still_required_in_preview": True,
    }

    manifest = {
        "artifact_name": "live_order_enable_package_preview",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(PROJECT_TRUTH_PATH.resolve()),
            str(MODE_CONFIG_PATH.resolve()),
            str(LIVE_ORDER_POLICY_PATH.resolve()),
            str(INTENT_PATH.resolve()),
            str(SNAPSHOT_PATH.resolve()),
            str(GATE_PATH.resolve()),
            str(RECON_PATH.resolve()),
            str(SUBMIT_PREVIEW_PATH.resolve()),
        ],
        "output_paths": [
            str(PREVIEW_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "status": "success",
    }

    PREVIEW_PATH.write_text(json.dumps(preview, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {PREVIEW_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log("[END] preview_live_order_enable_package success")


if __name__ == "__main__":
    main()
