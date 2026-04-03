from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = ROOT / "outputs" / "execution"
INTENTS_DIR = OUTPUTS_DIR / "intents"
READ_ONLY_DIR = OUTPUTS_DIR / "read_only"
DRY_RUN_DIR = OUTPUTS_DIR / "dry_run"
LIVE_STATUS_DIR = OUTPUTS_DIR / "live_status"
LOGS_DIR = OUTPUTS_DIR / "logs"

INTENT_PATH = INTENTS_DIR / "latest_execution_intent.json"
INTENT_QUALITY_PATH = INTENTS_DIR / "latest_execution_intent_quality.json"
SNAPSHOT_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot.json"
SNAPSHOT_QUALITY_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot_quality.json"

DECISION_PATH = DRY_RUN_DIR / "latest_dry_run_decision.json"
QUALITY_PATH = DRY_RUN_DIR / "latest_dry_run_decision_quality.json"
MANIFEST_PATH = DRY_RUN_DIR / "latest_dry_run_decision_manifest.json"
ACTION_LOG_PATH = LOGS_DIR / "execution_action_log.jsonl"
RUN_LOG_PATH = LOGS_DIR / "run_dry_execution_bridge.log"
APP_STATUS_PATH = LIVE_STATUS_DIR / "execution_status.json"


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
    with RUN_LOG_PATH.open("a", encoding="utf-8") as f:
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


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def normalize_hl_state(value: str | None) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NONE", "NULL"}:
        return "UNKNOWN"
    if text in {"CASH", "USDC"}:
        return "CASH"
    return text


def extract_current_position_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw = snapshot.get("raw", {})
    clearinghouse = raw.get("clearinghouseState", {})
    asset_positions = clearinghouse.get("assetPositions", [])

    active_positions: list[dict[str, Any]] = []
    if isinstance(asset_positions, list):
        for item in asset_positions:
            if not isinstance(item, dict):
                continue
            position = item.get("position") or item.get("pos") or item
            if not isinstance(position, dict):
                continue

            size_candidates = [
                position.get("szi"),
                position.get("size"),
                position.get("positionSize"),
            ]
            size_value = None
            for candidate in size_candidates:
                if candidate is None:
                    continue
                try:
                    size_value = float(str(candidate))
                    break
                except Exception:
                    continue

            if size_value is not None and abs(size_value) > 0:
                active_positions.append(item)

    if active_positions:
        return {
            "normalized_state": "HAS_OPEN_POSITION",
            "active_positions_count": len(active_positions),
            "active_positions": active_positions,
        }

    return {
        "normalized_state": "CASH",
        "active_positions_count": 0,
        "active_positions": [],
    }


def main() -> None:
    DRY_RUN_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] run_dry_execution_bridge")

    intent = read_json(INTENT_PATH)
    intent_quality = read_json(INTENT_QUALITY_PATH)
    snapshot = read_json(SNAPSHOT_PATH)
    snapshot_quality = read_json(SNAPSHOT_QUALITY_PATH)

    if not bool(intent_quality.get("intent_ok")):
        fail("latest_execution_intent_quality.json says intent_ok=false")
    if not bool(snapshot_quality.get("snapshot_ok")):
        fail("hyperliquid_account_snapshot_quality.json says snapshot_ok=false")
    if bool(intent.get("trading_enabled")):
        fail("Intent says trading_enabled=true. Dry-run bridge refuses to run.")
    if snapshot.get("execution_mode") != "read_only":
        fail("Snapshot execution_mode must be read_only for dry-run bridge stage.")

    signal_id = str(intent.get("signal_id", "")).strip()
    if not signal_id:
        fail("Intent missing signal_id")

    target_asset = normalize_hl_state(intent.get("target_asset"))
    stale_signal = bool(intent.get("stale_signal"))
    guardrail_flags = intent.get("guardrail_flags", {})
    if not bool(guardrail_flags.get("contract_validated")):
        fail("Intent guardrail contract_validated is false")
    if not bool(guardrail_flags.get("kill_switch_required")):
        fail("Intent guardrail kill_switch_required is false")

    current_position_state = extract_current_position_state(snapshot)
    current_state = normalize_hl_state(current_position_state.get("normalized_state"))

    open_orders = snapshot.get("raw", {}).get("openOrders", [])
    open_orders_count = len(open_orders) if isinstance(open_orders, list) else 0

    duplicate_order_risk = False
    recommended_action = "hold_no_action"
    decision_reason = "target_matches_current_state"

    if stale_signal:
        recommended_action = "block_stale_signal"
        decision_reason = "stale_signal"
    elif open_orders_count > 0:
        recommended_action = "block_open_orders_present"
        decision_reason = "open_orders_present"
        duplicate_order_risk = True
    elif target_asset == "CASH" and current_state == "CASH":
        recommended_action = "hold_cash"
        decision_reason = "already_in_cash"
    elif target_asset == "CASH" and current_state != "CASH":
        recommended_action = "simulate_exit_to_cash"
        decision_reason = "target_cash_current_not_cash"
    elif target_asset != "CASH" and current_state == "CASH":
        recommended_action = "simulate_enter_target_asset"
        decision_reason = "target_asset_current_cash"
    elif target_asset != current_state:
        recommended_action = "simulate_rotate_position"
        decision_reason = "target_differs_from_current_state"
    else:
        recommended_action = "hold_current_position"
        decision_reason = "target_matches_current_state"

    decision = {
        "decision_type": "dry_run_execution_decision",
        "generated_at_utc": utc_now_iso(),
        "signal_id": signal_id,
        "strategy_model": intent.get("strategy_model"),
        "reference_model": intent.get("reference_model"),
        "benchmark": intent.get("benchmark"),
        "as_of_source": intent.get("as_of_source"),
        "target_asset": target_asset,
        "target_regime": intent.get("target_regime"),
        "current_state": current_state,
        "current_position_details": current_position_state,
        "open_orders_count": open_orders_count,
        "duplicate_order_risk": duplicate_order_risk,
        "stale_signal": stale_signal,
        "recommended_action": recommended_action,
        "decision_reason": decision_reason,
        "simulated_order": {
            "would_place_order": recommended_action in {
                "simulate_enter_target_asset",
                "simulate_exit_to_cash",
                "simulate_rotate_position",
            },
            "side": None,
            "asset": None,
            "size_mode": "not_computed_yet",
            "notional_usd": None,
            "qty": None,
        },
        "guardrails": {
            "trading_enabled": False,
            "kill_switch_required": True,
            "manual_approval_required_for_live_orders": True,
            "contract_validated": bool(guardrail_flags.get("contract_validated")),
            "staleness_ok": bool(intent.get("staleness_ok")),
        },
        "source_paths": {
            "intent_path": str(INTENT_PATH.resolve()),
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
        },
        "notes": [
            "Dry-run only.",
            "No real orders were created.",
            "No size calculation yet.",
        ],
    }

    if decision["simulated_order"]["would_place_order"]:
        if recommended_action == "simulate_enter_target_asset":
            decision["simulated_order"]["side"] = "BUY"
            decision["simulated_order"]["asset"] = target_asset
        elif recommended_action == "simulate_exit_to_cash":
            decision["simulated_order"]["side"] = "SELL_TO_CASH"
            decision["simulated_order"]["asset"] = "CURRENT_POSITION"
        elif recommended_action == "simulate_rotate_position":
            decision["simulated_order"]["side"] = "ROTATE"
            decision["simulated_order"]["asset"] = target_asset

    quality = {
        "dry_run_ok": True,
        "signal_id_present": bool(signal_id),
        "target_asset_present": bool(target_asset),
        "snapshot_read_ok": True,
        "intent_read_ok": True,
        "would_place_order": bool(decision["simulated_order"]["would_place_order"]),
        "recommended_action": recommended_action,
        "stale_signal": stale_signal,
        "duplicate_order_risk": duplicate_order_risk,
    }

    manifest = {
        "artifact_name": "latest_dry_run_decision",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(INTENT_PATH.resolve()),
            str(INTENT_QUALITY_PATH.resolve()),
            str(SNAPSHOT_PATH.resolve()),
            str(SNAPSHOT_QUALITY_PATH.resolve()),
        ],
        "output_paths": [
            str(DECISION_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "status": "success",
    }

    app_status = {
        "status_type": "execution_app_status",
        "as_of_utc": utc_now_iso(),
        "mode": "dry_run",
        "trading_enabled": False,
        "kill_switch": True,
        "status": "ok",
        "provider": "Hyperliquid",
        "account_address": snapshot.get("account_address"),
        "positions_count": int(current_position_state.get("active_positions_count", 0)),
        "open_orders_count": open_orders_count,
        "recent_fills_count": int(snapshot.get("summary", {}).get("recent_fills_count", 0)),
        "current_position": current_state,
        "last_action": "dry_run_execution_bridge",
        "last_action_result": recommended_action,
        "guardrails_ok": True,
        "stale_signal": stale_signal,
        "signal_id": signal_id,
        "target_asset": target_asset,
        "error": None,
        "source_paths": {
            "intent_path": str(INTENT_PATH.resolve()),
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
            "dry_run_decision_path": str(DECISION_PATH.resolve()),
        }
    }

    DECISION_PATH.write_text(json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    APP_STATUS_PATH.write_text(json.dumps(app_status, indent=2, ensure_ascii=False), encoding="utf-8")

    append_jsonl(ACTION_LOG_PATH, {
        "timestamp_utc": utc_now_iso(),
        "action_type": "dry_run_execution_decision",
        "signal_id": signal_id,
        "target_asset": target_asset,
        "current_state": current_state,
        "recommended_action": recommended_action,
        "decision_reason": decision_reason,
        "would_place_order": decision["simulated_order"]["would_place_order"],
        "stale_signal": stale_signal,
        "duplicate_order_risk": duplicate_order_risk,
    })

    log(f"[SAVED] {DECISION_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[SAVED] {APP_STATUS_PATH}")
    log(f"[END] run_dry_execution_bridge success recommended_action={recommended_action}")


if __name__ == "__main__":
    main()