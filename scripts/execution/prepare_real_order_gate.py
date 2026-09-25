from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.data_health_common import (
    build_report_bundle,
    execution_blocking_sources,
)


ROOT = Path(__file__).resolve().parents[2]

EXECUTION_DIR = ROOT / "execution"
CONFIG_DIR = EXECUTION_DIR / "config"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
INTENTS_DIR = OUTPUTS_DIR / "intents"
READ_ONLY_DIR = OUTPUTS_DIR / "read_only"
LIVE_GATE_DIR = OUTPUTS_DIR / "live_gate"
LOGS_DIR = OUTPUTS_DIR / "logs"
PRODUCTION_DIR = ROOT / "outputs" / "production"
CASH_LIKE_ASSETS = {"CASH", "USD", "USDC", "USDT", "NONE", "OUT_OF_MARKET"}
REAL_ORDER_GATE_HEALTH_GUARD_SOURCE_IDS = frozenset(
    {
        "production_current_strategy_snapshot",
        "production_current_strategy_timeseries",
        "production_current_strategy_diagnostics",
        "production_current_strategy_snapshot_quality",
        "data_ohlcv_btcusdt_1d",
        "execution_latest_execution_intent",
    }
)

MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"
INTENT_PATH = INTENTS_DIR / "latest_execution_intent.json"
ACCOUNT_SNAPSHOT_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot.json"
PRODUCTION_SNAPSHOT_PATH = PRODUCTION_DIR / "current_strategy_snapshot.json"
AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH = (
    OUTPUTS_DIR / "authority" / "latest_successful_snapshot.json"
)
AUTHORITY_LATEST_ATTEMPT_STATUS_PATH = (
    OUTPUTS_DIR / "authority" / "latest_attempt_status.json"
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def is_cash_like_asset(value: Any) -> bool:
    return normalize_asset(value) in CASH_LIKE_ASSETS


def select_real_order_gate_health_blockers(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        source
        for source in execution_blocking_sources(report)
        if str(source.get("source_id") or "").strip()
        in REAL_ORDER_GATE_HEALTH_GUARD_SOURCE_IDS
    ]


def extract_open_orders_count(snapshot: dict[str, Any]) -> int:
    raw = snapshot.get("raw", {})
    open_orders = raw.get("openOrders", [])
    if isinstance(open_orders, list):
        return len(open_orders)
    return 0


def extract_positions_count(snapshot: dict[str, Any]) -> int:
    raw = snapshot.get("raw", {})
    clearinghouse = raw.get("clearinghouseState", {}) if isinstance(raw, dict) else {}
    positions = clearinghouse.get("assetPositions", []) if isinstance(clearinghouse, dict) else []
    if not isinstance(positions, list):
        return 0
    active = 0
    for item in positions:
        if not isinstance(item, dict):
            continue
        position = item.get("position") if isinstance(item.get("position"), dict) else item
        try:
            size = float(str(position.get("szi", position.get("size", 0))))
        except Exception:
            size = 0.0
        if abs(size) > 1e-12:
            active += 1
    return active


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
    if value is None:
        raise ValueError(f"{context} is missing")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{context} is missing")
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"{context} must be finite")
    return number


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
    current_asset = normalize_asset(
        require_text(
            snapshot.get("current_asset"),
            "production snapshot current_asset",
        )
    )
    candidate_asset = normalize_asset(
        require_text(
            snapshot.get("candidate_asset"),
            "production snapshot candidate_asset",
        )
    )
    effective_market_exposure = require_float(
        snapshot.get("effective_market_exposure"),
        "production snapshot effective_market_exposure",
    )
    model_candidate_exposure = require_float(
        snapshot.get("model_candidate_exposure"),
        "production snapshot model_candidate_exposure",
    )
    trend_permission_active = bool(snapshot.get("trend_permission_active", False))
    stale_signal = bool(execution_intent.get("stale_signal", False))
    allow_live_order_candidate = bool(
        execution_intent.get("allow_live_order_candidate", False)
    )
    strategy_version = require_text(
        snapshot.get("strategy_version"),
        "production snapshot strategy_version",
    )
    if target_exposure < 0 or (is_cash_like_asset(target_asset) and target_exposure != 0):
        raise ValueError("production snapshot has invalid target exposure")
    if not trend_permission_active:
        if effective_market_exposure > 1e-9:
            raise ValueError("production snapshot reports exposure while trend_permission_active=false")
        if not is_cash_like_asset(current_asset):
            raise ValueError("production snapshot current_asset must be CASH while trend_permission_active=false")
        if not is_cash_like_asset(target_asset):
            raise ValueError("production snapshot execution target must be CASH while trend_permission_active=false")
        if target_exposure > 1e-9:
            raise ValueError("production snapshot execution target exposure must be 0.0 while trend_permission_active=false")
        if allow_live_order_candidate:
            raise ValueError("production snapshot allow_live_order_candidate must be false while trend_permission_active=false")
    else:
        if target_exposure <= 0:
            raise ValueError("production snapshot non-CASH target exposure must be positive")
        if effective_market_exposure <= 1e-9:
            raise ValueError("production snapshot effective_market_exposure must be above zero while trend_permission_active=true")
        if is_cash_like_asset(target_asset):
            raise ValueError("production snapshot execution target must not be CASH while trend_permission_active=true")

    return {
        "closed_day": closed_day,
        "signal_id": signal_id,
        "target_asset": target_asset,
        "target_exposure": target_exposure,
        "candidate_asset": candidate_asset,
        "current_asset": current_asset,
        "effective_market_exposure": effective_market_exposure,
        "model_candidate_exposure": model_candidate_exposure,
        "trend_permission_active": trend_permission_active,
        "stale_signal": stale_signal,
        "allow_live_order_candidate": allow_live_order_candidate,
        "validation_status": validation_status,
        "strategy_version": strategy_version,
        "strategy_status": str(snapshot.get("strategy_status") or "").strip(),
        "execution_intent": execution_intent,
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
    parser.add_argument(
        "--authority-latest-successful-snapshot-path",
        type=Path,
        default=AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH,
    )
    parser.add_argument(
        "--authority-latest-attempt-status-path",
        type=Path,
        default=AUTHORITY_LATEST_ATTEMPT_STATUS_PATH,
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
    bundle = build_report_bundle(root=ROOT, output_dir=PRODUCTION_DIR, write_outputs=True)
    health_blockers = select_real_order_gate_health_blockers(bundle["report"])
    if health_blockers:
        fail("Real-order gate blocked by direct dependencies: " + " | ".join(f"{item['source_id']}:{item['status']}" for item in health_blockers))
    mode_cfg = read_json(args.mode_config_path)
    policy_cfg = read_json(args.live_order_policy_path)
    intent = read_json(args.intent_path)
    multi_account = os.environ.get("MRV1_EXECUTION_BACKEND") == "multi_account"
    account_snapshot_available = True
    if multi_account:
        try:
            account_snapshot = json.loads(args.snapshot_path.read_text(encoding="utf-8"))
            if not isinstance(account_snapshot, dict):
                raise ValueError("account observation is not an object")
        except (OSError, ValueError):
            account_snapshot = {}
            account_snapshot_available = False
    else:
        account_snapshot = read_json(args.snapshot_path)
    production_snapshot = read_json(args.production_snapshot_path)
    try:
        context = load_production_snapshot_context(production_snapshot)
    except Exception as exc:
        fail(f"Real-order gate blocked: invalid production snapshot ({type(exc).__name__}: {exc})")
    target_asset = normalize_asset(intent.get("target_asset"))
    signal_id = str(intent.get("signal_id") or "").strip()
    target_exposure = require_float(intent.get("target_size_pct"), "intent target exposure")
    target_is_cash = is_cash_like_asset(target_asset)
    positions_count = extract_positions_count(account_snapshot)
    open_orders_count = extract_open_orders_count(account_snapshot)
    no_action_cash = not multi_account and target_is_cash and positions_count == 0 and open_orders_count == 0
    guardrails = intent.get("guardrail_flags") or {}
    checks = {
        "signal_present": bool(signal_id), "target_asset_present": bool(target_asset),
        "target_asset_is_cash": target_is_cash,
        "contract_validated": bool(guardrails.get("contract_validated")),
        "stale_signal": bool(intent.get("stale_signal")),
        "kill_switch": mode_cfg.get("kill_switch") is not False,
        "account_address_present": bool(str(account_snapshot.get("account_address") or "").strip()),
        "production_snapshot_validation_passed": context["validation_status"] == "passed",
        "intent_day_matches_production_snapshot": str(intent.get("as_of_source") or "") == context["closed_day"],
        "intent_signal_matches_production_snapshot": signal_id == context["signal_id"],
        "intent_target_asset_matches_production_snapshot": target_asset == context["target_asset"],
        "intent_target_exposure_matches_production_snapshot": abs(target_exposure - context["target_exposure"]) <= 1e-9,
        "intent_strategy_model_matches_production_snapshot": str(intent.get("strategy_model") or "") == context["strategy_version"],
        "intent_allow_live_order_candidate_matches_snapshot": bool(intent.get("allow_live_order_candidate")) == context["allow_live_order_candidate"],
        "intent_stale_signal_matches_production_snapshot": bool(intent.get("stale_signal")) == context["stale_signal"],
        "positions_count": positions_count, "open_orders_present": open_orders_count > 0,
        "exit_required": target_is_cash and positions_count > 0,
    }
    strategy_reasons = []
    for name, reason in (
        ("signal_present", "missing_signal_id"), ("target_asset_present", "missing_target_asset"),
        ("contract_validated", "contract_not_validated"),
        ("intent_day_matches_production_snapshot", "intent_day_mismatch_vs_production_snapshot"),
        ("intent_signal_matches_production_snapshot", "intent_signal_mismatch_vs_production_snapshot"),
        ("intent_target_asset_matches_production_snapshot", "intent_target_asset_mismatch_vs_production_snapshot"),
        ("intent_target_exposure_matches_production_snapshot", "intent_target_exposure_mismatch_vs_production_snapshot"),
        ("intent_strategy_model_matches_production_snapshot", "intent_strategy_model_mismatch_vs_production_snapshot"),
        ("intent_allow_live_order_candidate_matches_snapshot", "intent_allow_live_order_candidate_mismatch_vs_production_snapshot"),
        ("intent_stale_signal_matches_production_snapshot", "intent_stale_signal_mismatch_vs_production_snapshot"),
    ):
        if not checks[name]:
            strategy_reasons.append(reason)
    if checks["stale_signal"] or context["stale_signal"]:
        strategy_reasons.append("stale_signal")
    if not target_is_cash and not context["allow_live_order_candidate"]:
        strategy_reasons.append("production_snapshot_allow_live_order_candidate=false")
    if policy_cfg.get("sizing_mode") != "equity_target_exposure":
        strategy_reasons.append("equity_target_exposure_sizing_not_enabled")
    block_reasons = list(strategy_reasons)
    if checks["kill_switch"]:
        block_reasons.append("kill_switch_enabled")
    if not multi_account and not checks["account_address_present"]:
        block_reasons.append("missing_account_address")
    if no_action_cash:
        block_reasons.append("no_market_entry_authorized")
    ready = not block_reasons
    status = "ready_if_enabled" if ready else ("no_action" if no_action_cash and block_reasons == ["no_market_entry_authorized"] else "blocked")
    decision = {
        "decision_type": "real_order_gate_decision", "generated_at_utc": utc_now_iso(),
        "signal_id": signal_id, "target_asset": target_asset, "mode": "canonical_invocation",
        "account_address": account_snapshot.get("account_address"),
        "account_validation_scope": "per_account_exchange" if multi_account else "canonical_owner_snapshot",
        "account_snapshot_available": account_snapshot_available,
        "strategy_validated": not strategy_reasons,
        "emergency_execution_blocked": checks["kill_switch"],
        "would_place_real_order": ready, "real_orders_enabled": not checks["kill_switch"],
        "status": status, "block_reasons": block_reasons, "checks": checks,
        "production_signal_context": {key: value for key, value in context.items() if key != "execution_intent"},
        "source_fingerprints": {
            "intent_sha256": sha256_file(args.intent_path),
            "account_snapshot_sha256": sha256_file(args.snapshot_path) if account_snapshot_available else None,
            "production_snapshot_sha256": sha256_file(args.production_snapshot_path),
        },
        "notes": ["Read-only validation of the current Production Core target and canonical intent.", "Exchange feasibility and order reconciliation are evaluated by the executor per account and per step."],
        "source_paths": {
            "mode_config_path": str(args.mode_config_path.resolve()),
            "live_order_policy_path": str(args.live_order_policy_path.resolve()),
            "intent_path": str(args.intent_path.resolve()),
            "account_snapshot_path": str(args.snapshot_path.resolve()),
            "production_snapshot_path": str(args.production_snapshot_path.resolve()),
        },
    }
    quality = {"gate_ok": True, "signal_present": checks["signal_present"], "target_asset_present": checks["target_asset_present"], "contract_validated": checks["contract_validated"], "production_snapshot_validation_passed": True, "intent_day_matches_production_snapshot": checks["intent_day_matches_production_snapshot"], "intent_signal_matches_production_snapshot": checks["intent_signal_matches_production_snapshot"], "blocked": bool(block_reasons), "block_reason_count": len(block_reasons), "would_place_real_order": ready, "status": status}
    manifest = {"artifact_name": "latest_real_order_gate_decision", "generated_at_utc": utc_now_iso(), "started_at_utc": started_at, "script_path": str(Path(__file__).resolve()), "input_paths": list(decision["source_paths"].values()), "output_paths": [str(path.resolve()) for path in (args.decision_path, args.quality_path, args.manifest_path)], "status": "success"}
    for path, payload in ((args.decision_path, decision), (args.quality_path, quality), (args.manifest_path, manifest)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"[SAVED] {path}")
    build_report_bundle(root=ROOT, output_dir=PRODUCTION_DIR, write_outputs=True)
    log(f"[END] prepare_real_order_gate success status={status}")


if __name__ == "__main__":
    main()
