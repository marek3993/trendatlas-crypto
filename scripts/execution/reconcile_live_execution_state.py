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

INTENT_PATH = OUTPUTS_DIR / "intents" / "latest_execution_intent.json"
SNAPSHOT_PATH = OUTPUTS_DIR / "read_only" / "hyperliquid_account_snapshot.json"
MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"

RECON_DIR = OUTPUTS_DIR / "reconciliation"
LOGS_DIR = OUTPUTS_DIR / "logs"

REPORT_PATH = RECON_DIR / "latest_reconciliation_report.json"
QUALITY_PATH = RECON_DIR / "latest_reconciliation_quality.json"
MANIFEST_PATH = RECON_DIR / "latest_reconciliation_manifest.json"
LOG_PATH = LOGS_DIR / "reconcile_live_execution_state.log"


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


def extract_open_positions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("raw", {})
    clearinghouse = raw.get("clearinghouseState", {})
    asset_positions = clearinghouse.get("assetPositions", [])

    active_positions: list[dict[str, Any]] = []
    if not isinstance(asset_positions, list):
        return active_positions

    for item in asset_positions:
        if not isinstance(item, dict):
            continue

        position = item.get("position") or item.get("pos") or item
        if not isinstance(position, dict):
            continue

        coin = normalize_asset(
            position.get("coin")
            or position.get("asset")
            or item.get("coin")
            or item.get("asset")
        )

        size_raw = (
            position.get("szi")
            or position.get("size")
            or position.get("positionSize")
            or 0
        )

        try:
            size_val = float(str(size_raw))
        except Exception:
            size_val = 0.0

        if abs(size_val) > 0:
            active_positions.append(
                {
                    "coin": coin or "UNKNOWN",
                    "size": size_val,
                    "raw": item,
                }
            )

    return active_positions


def derive_current_state(open_positions: list[dict[str, Any]]) -> dict[str, Any]:
    if not open_positions:
        return {
            "normalized_state": "CASH",
            "active_positions_count": 0,
            "active_asset": "CASH",
            "multi_position": False,
        }

    unique_assets = sorted({normalize_asset(x.get("coin")) for x in open_positions if normalize_asset(x.get("coin"))})
    if len(unique_assets) == 1:
        return {
            "normalized_state": unique_assets[0],
            "active_positions_count": len(open_positions),
            "active_asset": unique_assets[0],
            "multi_position": len(open_positions) > 1,
        }

    return {
        "normalized_state": "MULTI_ASSET",
        "active_positions_count": len(open_positions),
        "active_asset": "MULTI_ASSET",
        "multi_position": True,
    }


def main() -> None:
    RECON_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] reconcile_live_execution_state")

    intent = read_json(INTENT_PATH)
    snapshot = read_json(SNAPSHOT_PATH)
    mode_cfg = read_json(MODE_CONFIG_PATH)
    live_order_policy = read_json(LIVE_ORDER_POLICY_PATH)

    signal_id = str(intent.get("signal_id", "")).strip()
    if not signal_id:
        fail("Intent missing signal_id")

    target_asset = normalize_asset(intent.get("target_asset"))
    if not target_asset:
        fail("Intent missing target_asset")

    open_positions = extract_open_positions(snapshot)
    current_state = derive_current_state(open_positions)

    open_orders = snapshot.get("raw", {}).get("openOrders", [])
    open_orders_count = len(open_orders) if isinstance(open_orders, list) else 0

    reconciled = current_state["normalized_state"] == target_asset
    reconciliation_action = "none"
    mismatch_reason = None

    if not reconciled:
        mismatch_reason = f"current_state={current_state['normalized_state']} target_asset={target_asset}"
        if current_state["normalized_state"] == "CASH" and target_asset != "CASH":
            reconciliation_action = "would_enter_target_asset"
        elif current_state["normalized_state"] != "CASH" and target_asset == "CASH":
            reconciliation_action = "would_exit_to_cash"
        else:
            reconciliation_action = "would_rotate_position"

    report = {
        "report_type": "live_execution_reconciliation_report",
        "generated_at_utc": utc_now_iso(),
        "signal_id": signal_id,
        "mode": str(mode_cfg.get("mode", "")).strip(),
        "trading_enabled": bool(mode_cfg.get("trading_enabled", False)),
        "kill_switch": bool(mode_cfg.get("kill_switch", True)),
        "allow_live_orders": bool(live_order_policy.get("allow_live_orders", False)),
        "target_asset": target_asset,
        "current_state": current_state["normalized_state"],
        "active_asset": current_state["active_asset"],
        "active_positions_count": current_state["active_positions_count"],
        "multi_position": current_state["multi_position"],
        "open_orders_count": open_orders_count,
        "reconciled": reconciled,
        "reconciliation_action": reconciliation_action,
        "mismatch_reason": mismatch_reason,
        "open_positions": open_positions,
        "source_paths": {
            "intent_path": str(INTENT_PATH.resolve()),
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
            "mode_config_path": str(MODE_CONFIG_PATH.resolve()),
            "live_order_policy_path": str(LIVE_ORDER_POLICY_PATH.resolve()),
        },
        "notes": [
            "Reconciliation artifact only.",
            "No real orders are placed by this script.",
            "Used to verify whether current exchange state matches target execution intent.",
        ],
    }

    quality = {
        "reconciliation_ok": True,
        "signal_present": bool(signal_id),
        "target_asset_present": bool(target_asset),
        "reconciled": reconciled,
        "current_state": current_state["normalized_state"],
        "target_asset": target_asset,
        "open_orders_count": open_orders_count,
    }

    manifest = {
        "artifact_name": "latest_reconciliation_report",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(INTENT_PATH.resolve()),
            str(SNAPSHOT_PATH.resolve()),
            str(MODE_CONFIG_PATH.resolve()),
            str(LIVE_ORDER_POLICY_PATH.resolve()),
        ],
        "output_paths": [
            str(REPORT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "status": "success",
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {REPORT_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[END] reconcile_live_execution_state success reconciled={reconciled}")


if __name__ == "__main__":
    main()