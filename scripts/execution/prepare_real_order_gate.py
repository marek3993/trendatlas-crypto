from __future__ import annotations

import argparse
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
PRODUCTION_DIR = ROOT / "outputs" / "production"

MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"
INTENT_PATH = INTENTS_DIR / "latest_execution_intent.json"
ACCOUNT_SNAPSHOT_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot.json"
PRODUCTION_SNAPSHOT_PATH = PRODUCTION_DIR / "current_strategy_snapshot.json"
AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH = (
    OUTPUTS_DIR / "authority" / "latest_successful_snapshot.json"
)

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
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def fail(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing required file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON in {path}: {exc}")
    except Exception as exc:
        fail(f"Failed reading {path}: {exc}")
    if not isinstance(payload, dict):
        fail(f"Expected JSON object in {path}")
    return payload
    raise RuntimeError("unreachable")


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def extract_open_orders_count(snapshot: dict[str, Any]) -> int:
    raw = snapshot.get("raw", {})
    open_orders = raw.get("openOrders", [])
    if isinstance(open_orders, list):
        return len(open_orders)
    return 0


def normalize_iso_day_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        raise ValueError(f"{context} is not an ISO day: {value}")
    return text


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def require_text(value: Any, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    return text


def require_float(value: Any, context: str) -> float:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    return float(text)


def load_production_snapshot_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    if str(snapshot.get("artifact_type") or "").strip() != "current_strategy_snapshot":
        raise ValueError("production snapshot artifact_type must be current_strategy_snapshot")

    validation = require_mapping(snapshot.get("validation"), "production snapshot validation")
    validation_status = str(validation.get("status") or "").strip().lower()
    if validation_status != "passed":
        raise ValueError(
            f"production snapshot validation.status must be passed (actual={validation_status or 'missing'})"
        )

    execution_intent = require_mapping(
        snapshot.get("execution_intent"),
        "production snapshot execution_intent",
    )
    closed_day = normalize_iso_day_text(
        snapshot.get("closed_day"),
        context="production snapshot closed_day",
    )
    signal_id = require_text(
        execution_intent.get("signal_id"),
        "production snapshot execution_intent.signal_id",
    )
    target_asset = normalize_asset(
        require_text(
            execution_intent.get("target_asset"),
            "production snapshot execution_intent.target_asset",
        )
    )
    target_exposure = require_float(
        execution_intent.get("target_exposure"),
        "production snapshot execution_intent.target_exposure",
    )
    stale_signal = bool(execution_intent.get("stale_signal", False))
    allow_live_order_candidate = bool(
        execution_intent.get("allow_live_order_candidate", False)
    )
    strategy_version = require_text(
        snapshot.get("strategy_version"),
        "production snapshot strategy_version",
    )

    return {
        "closed_day": closed_day,
        "signal_id": signal_id,
        "target_asset": target_asset,
        "target_exposure": target_exposure,
        "stale_signal": stale_signal,
        "allow_live_order_candidate": allow_live_order_candidate,
        "validation_status": validation_status,
        "strategy_version": strategy_version,
        "strategy_status": str(snapshot.get("strategy_status") or "").strip(),
        "execution_intent": execution_intent,
    }


def extract_authority_approval_gate_context(
    *,
    expected_strategy_model: str,
    expected_closed_day: str,
) -> dict[str, Any]:
    payload = read_json(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH)
    product_snapshot = payload.get("app_product_snapshot")
    if not isinstance(product_snapshot, dict):
        raise ValueError(
            "authority latest_successful_snapshot missing app_product_snapshot"
        )
    live_public_state = product_snapshot.get("live_public_state")
    if not isinstance(live_public_state, dict):
        raise ValueError(
            "authority latest_successful_snapshot missing app_product_snapshot.live_public_state"
        )
    approval_gate_status = str(live_public_state.get("approval_gate_status") or "").strip()
    strategy_model = str(product_snapshot.get("main_strategy_model") or "").strip()
    product_closed_day = normalize_iso_day_text(
        product_snapshot.get("strategy_last_closed_day"),
        context="authority latest_successful_snapshot app_product_snapshot.strategy_last_closed_day",
    )
    target_closed_day = normalize_iso_day_text(
        payload.get("target_closed_day_utc"),
        context="authority latest_successful_snapshot target_closed_day_utc",
    )
    return {
        "approval_gate_status": approval_gate_status,
        "strategy_model": strategy_model,
        "product_closed_day": product_closed_day,
        "target_closed_day": target_closed_day,
        "expected_strategy_model": expected_strategy_model,
        "expected_closed_day": expected_closed_day,
        "source_path": str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare latest real-order gate decision from production snapshot, intent, account, mode, and policy inputs."
    )
    parser.add_argument("--mode-config-path", type=Path, default=MODE_CONFIG_PATH)
    parser.add_argument("--live-order-policy-path", type=Path, default=LIVE_ORDER_POLICY_PATH)
    parser.add_argument("--intent-path", type=Path, default=INTENT_PATH)
    parser.add_argument("--snapshot-path", type=Path, default=ACCOUNT_SNAPSHOT_PATH)
    parser.add_argument(
        "--production-snapshot-path",
        type=Path,
        default=PRODUCTION_SNAPSHOT_PATH,
    )
    parser.add_argument("--decision-path", type=Path, default=DECISION_PATH)
    parser.add_argument("--quality-path", type=Path, default=QUALITY_PATH)
    parser.add_argument("--manifest-path", type=Path, default=MANIFEST_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    LIVE_GATE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] prepare_real_order_gate")

    mode_cfg = read_json(args.mode_config_path)
    policy_cfg = read_json(args.live_order_policy_path)
    intent = read_json(args.intent_path)
    account_snapshot = read_json(args.snapshot_path)
    production_snapshot = read_json(args.production_snapshot_path)

    try:
        production_context = load_production_snapshot_context(production_snapshot)
    except Exception as exc:
        fail(f"Real-order gate blocked: invalid production snapshot ({type(exc).__name__}: {exc})")

    mode = str(mode_cfg.get("mode", "")).strip()
    execution_trading_enabled = bool(mode_cfg.get("trading_enabled", False))
    kill_switch = bool(mode_cfg.get("kill_switch", True))

    allow_live_orders = bool(policy_cfg.get("allow_live_orders", False))
    manual_approval_required = bool(policy_cfg.get("manual_approval_required", True))
    require_kill_switch_off = bool(policy_cfg.get("require_kill_switch_off", True))
    max_order_notional_usd = float(policy_cfg.get("max_order_notional_usd", 0.0))
    allowed_assets = {
        normalize_asset(x)
        for x in policy_cfg.get("allowed_assets", [])
        if str(x).strip()
    }
    allowed_approval_gate_statuses = {
        str(x).strip()
        for x in policy_cfg.get("allowed_approval_gate_statuses", [])
        if str(x).strip()
    }

    signal_id = str(intent.get("signal_id") or "").strip()
    target_asset = normalize_asset(intent.get("target_asset"))
    stale_signal = bool(intent.get("stale_signal", False))
    allow_live_order_candidate = bool(intent.get("allow_live_order_candidate", False))
    guardrail_flags = (
        intent.get("guardrail_flags", {})
        if isinstance(intent.get("guardrail_flags"), dict)
        else {}
    )
    contract_validated = bool(guardrail_flags.get("contract_validated", False))
    duplicate_order_risk = bool(intent.get("duplicate_order_risk", False))
    leverage_live_truth_allowed = bool(
        guardrail_flags.get("leverage_live_truth_allowed", False)
    )

    signal_as_of_source = str(intent.get("as_of_source") or "").strip()
    signal_strategy_model = str(intent.get("strategy_model") or "").strip()
    approval_source_error: str | None = None
    authority_approval_context: dict[str, Any] | None = None
    try:
        authority_approval_context = extract_authority_approval_gate_context(
            expected_strategy_model=production_context["strategy_version"],
            expected_closed_day=production_context["closed_day"],
        )
    except Exception as exc:
        approval_source_error = str(exc)

    approval_gate_status = str(
        (authority_approval_context or {}).get("approval_gate_status") or ""
    ).strip()
    open_orders_count = extract_open_orders_count(account_snapshot)
    account_address = str(account_snapshot.get("account_address", "")).strip()

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
        "approval_source_readable": approval_source_error is None,
        "approval_gate_status": approval_gate_status,
        "approval_status_present": bool(approval_gate_status),
        "approval_source_model_match": (
            authority_approval_context is not None
            and str(authority_approval_context.get("strategy_model") or "").strip()
            == production_context["strategy_version"]
        ),
        "approval_source_day_match": (
            authority_approval_context is not None
            and str(authority_approval_context.get("product_closed_day") or "").strip()
            == production_context["closed_day"]
            and str(authority_approval_context.get("target_closed_day") or "").strip()
            == production_context["closed_day"]
        ),
        "approval_status_allowed": approval_gate_status in allowed_approval_gate_statuses,
        "leverage_live_truth_allowed": leverage_live_truth_allowed,
        "max_order_notional_usd": max_order_notional_usd,
        "account_address_present": bool(account_address),
        "production_snapshot_validation_passed": (
            production_context["validation_status"] == "passed"
        ),
        "production_snapshot_closed_day_present": bool(production_context["closed_day"]),
        "production_snapshot_signal_present": bool(production_context["signal_id"]),
        "production_snapshot_target_asset_present": bool(
            production_context["target_asset"]
        ),
        "production_snapshot_allow_live_order_candidate": production_context[
            "allow_live_order_candidate"
        ],
        "production_snapshot_stale_signal": production_context["stale_signal"],
        "intent_day_matches_production_snapshot": (
            signal_as_of_source == production_context["closed_day"]
        ),
        "intent_signal_matches_production_snapshot": (
            signal_id == production_context["signal_id"]
        ),
        "intent_target_asset_matches_production_snapshot": (
            target_asset == production_context["target_asset"]
        ),
        "intent_stale_signal_matches_production_snapshot": (
            stale_signal == production_context["stale_signal"]
        ),
        "intent_strategy_model_matches_production_snapshot": (
            signal_strategy_model == production_context["strategy_version"]
        ),
        "intent_allow_live_order_candidate_matches_snapshot": (
            allow_live_order_candidate
            == production_context["allow_live_order_candidate"]
        ),
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
    if not checks["approval_source_readable"]:
        block_reasons.append(f"approval_source_unreadable:{approval_source_error}")
    if not checks["approval_status_present"]:
        block_reasons.append("missing_approval_gate_status")
    if not checks["approval_source_model_match"]:
        block_reasons.append("approval_source_model_mismatch")
    if not checks["approval_source_day_match"]:
        block_reasons.append("approval_source_day_mismatch")
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
    if not checks["production_snapshot_validation_passed"]:
        block_reasons.append("production_snapshot_validation_not_passed")
    if not checks["production_snapshot_closed_day_present"]:
        block_reasons.append("production_snapshot_closed_day_missing")
    if not checks["production_snapshot_signal_present"]:
        block_reasons.append("production_snapshot_signal_missing")
    if not checks["production_snapshot_target_asset_present"]:
        block_reasons.append("production_snapshot_target_asset_missing")
    if not checks["production_snapshot_allow_live_order_candidate"]:
        block_reasons.append("production_snapshot_allow_live_order_candidate=false")
    if checks["production_snapshot_stale_signal"]:
        block_reasons.append("production_snapshot_stale_signal")
    if not checks["intent_day_matches_production_snapshot"]:
        block_reasons.append("intent_day_mismatch_vs_production_snapshot")
    if not checks["intent_signal_matches_production_snapshot"]:
        block_reasons.append("intent_signal_mismatch_vs_production_snapshot")
    if not checks["intent_target_asset_matches_production_snapshot"]:
        block_reasons.append("intent_target_asset_mismatch_vs_production_snapshot")
    if not checks["intent_stale_signal_matches_production_snapshot"]:
        block_reasons.append("intent_stale_signal_mismatch_vs_production_snapshot")
    if not checks["intent_strategy_model_matches_production_snapshot"]:
        block_reasons.append("intent_strategy_model_mismatch_vs_production_snapshot")
    if not checks["intent_allow_live_order_candidate_matches_snapshot"]:
        block_reasons.append(
            "intent_allow_live_order_candidate_mismatch_vs_production_snapshot"
        )

    would_place_real_order = len(block_reasons) == 0
    status = "ready_if_enabled" if would_place_real_order else "blocked"

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
        "production_signal_context": {
            "strategy_version": production_context["strategy_version"],
            "closed_day": production_context["closed_day"],
            "validation_status": production_context["validation_status"],
            "signal_id": production_context["signal_id"],
            "target_asset": production_context["target_asset"],
            "target_exposure": production_context["target_exposure"],
            "allow_live_order_candidate": production_context[
                "allow_live_order_candidate"
            ],
        },
        "notes": [
            "This is a gate-preparation artifact only.",
            "Strategy signal truth is read from outputs/production/current_strategy_snapshot.json.",
            "No real order placement is performed by this script.",
            "Real-order readiness still requires current policy, approval, account, and safety checks.",
        ],
        "source_paths": {
            "mode_config_path": str(args.mode_config_path.resolve()),
            "live_order_policy_path": str(args.live_order_policy_path.resolve()),
            "intent_path": str(args.intent_path.resolve()),
            "account_snapshot_path": str(args.snapshot_path.resolve()),
            "production_snapshot_path": str(args.production_snapshot_path.resolve()),
            "authority_latest_successful_snapshot_path": str(
                AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()
            ),
        },
    }

    quality = {
        "gate_ok": True,
        "signal_present": checks["signal_present"],
        "target_asset_present": checks["target_asset_present"],
        "target_asset_allowed": checks["target_asset_allowed"],
        "contract_validated": checks["contract_validated"],
        "production_snapshot_validation_passed": checks[
            "production_snapshot_validation_passed"
        ],
        "intent_day_matches_production_snapshot": checks[
            "intent_day_matches_production_snapshot"
        ],
        "intent_signal_matches_production_snapshot": checks[
            "intent_signal_matches_production_snapshot"
        ],
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
            str(args.mode_config_path.resolve()),
            str(args.live_order_policy_path.resolve()),
            str(args.intent_path.resolve()),
            str(args.snapshot_path.resolve()),
            str(args.production_snapshot_path.resolve()),
        ],
        "output_paths": [
            str(args.decision_path.resolve()),
            str(args.quality_path.resolve()),
            str(args.manifest_path.resolve()),
        ],
        "status": "success",
    }

    args.decision_path.parent.mkdir(parents=True, exist_ok=True)
    args.quality_path.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    args.decision_path.write_text(
        json.dumps(decision, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    args.quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    args.manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log(f"[SAVED] {args.decision_path}")
    log(f"[SAVED] {args.quality_path}")
    log(f"[SAVED] {args.manifest_path}")
    log(f"[END] prepare_real_order_gate success status={decision['status']}")


if __name__ == "__main__":
    main()
