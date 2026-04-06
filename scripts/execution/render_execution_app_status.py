from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs" / "execution"
READ_ONLY_DIR = OUTPUT_DIR / "read_only"
LIVE_STATUS_DIR = OUTPUT_DIR / "live_status"
LOGS_DIR = OUTPUT_DIR / "logs"
CONFIG_DIR = ROOT / "execution" / "config"

SNAPSHOT_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot.json"
QUALITY_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot_quality.json"
MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
STATUS_PATH = LIVE_STATUS_DIR / "execution_status.json"
STATUS_MANIFEST_PATH = LIVE_STATUS_DIR / "execution_status_manifest.json"
LOG_PATH = LOGS_DIR / "render_execution_app_status.log"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(str(value))
    except Exception:
        return None


def first_float(payload: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        if key not in payload:
            continue
        parsed = to_float(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def maybe_pct_from_fraction(value: float | None) -> float | None:
    if value is None:
        return None
    if -1.0 <= value <= 1.0:
        return value * 100.0
    return value


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def extract_open_position(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    raw = snapshot.get("raw", {})
    clearinghouse = raw.get("clearinghouseState", {})
    asset_positions = clearinghouse.get("assetPositions", [])
    if not isinstance(asset_positions, list):
        return None

    active_positions: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for item in asset_positions:
        if not isinstance(item, dict):
            continue
        position = item.get("position") or item.get("pos") or item
        if not isinstance(position, dict):
            continue

        size = first_float(position, ["szi", "size", "positionSize"])
        if size is None or abs(size) <= 0:
            continue

        active_positions.append((item, position, size))

    if not active_positions:
        return None

    primary_item, primary_position, size = active_positions[0]
    symbol = normalize_asset(
        primary_position.get("coin")
        or primary_position.get("asset")
        or primary_item.get("coin")
        or primary_item.get("asset")
    ) or "UNKNOWN"

    position_value = first_float(primary_position, ["positionValue", "position_value"])
    mark_price = first_float(primary_position, ["markPx", "mark_price"])
    if mark_price is None and position_value is not None and abs(size) > 0:
        mark_price = abs(position_value / size)

    return {
        "symbol": symbol,
        "side": "LONG" if size > 0 else "SHORT",
        "size": abs(size),
        "entry_price": first_float(primary_position, ["entryPx", "entry_price"]),
        "mark_price": mark_price,
        "unrealized_pnl_usd": first_float(primary_position, ["unrealizedPnl", "unrealized_pnl", "upl"]),
        "unrealized_pnl_pct": maybe_pct_from_fraction(
            first_float(primary_position, ["returnOnEquity", "unrealizedPnlPct", "roe"])
        ),
    }


def main() -> None:
    LIVE_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log("[START] render_execution_app_status")

    snapshot = read_json(SNAPSHOT_PATH)
    quality = read_json(QUALITY_PATH)
    mode_cfg = read_json(MODE_CONFIG_PATH)

    if not bool(quality.get("snapshot_ok")):
        fail("Snapshot quality says snapshot_ok=false")
    if snapshot.get("snapshot_type") != "hyperliquid_read_only_account_snapshot":
        fail("Unexpected snapshot_type")

    summary = snapshot.get("summary", {})
    mode = str(mode_cfg.get("mode", "read_only")).strip() or "read_only"
    trading_enabled = bool(mode_cfg.get("trading_enabled", False))
    kill_switch = bool(mode_cfg.get("kill_switch", True))
    open_position = extract_open_position(snapshot)
    current_position = open_position["symbol"] if open_position else "CASH"

    status = {
        "status_type": "execution_app_status",
        "as_of_utc": utc_now_iso(),
        "mode": mode,
        "trading_enabled": trading_enabled,
        "kill_switch": kill_switch,
        "status": "ok",
        "provider": "Hyperliquid",
        "account_address": snapshot.get("account_address"),
        "positions_count": int(summary.get("positions_count", 0)),
        "open_orders_count": int(summary.get("open_orders_count", 0)),
        "recent_fills_count": int(summary.get("recent_fills_count", 0)),
        "current_position": current_position,
        "last_action": "snapshot_refresh",
        "last_action_result": "success",
        "guardrails_ok": True,
        "stale_signal": None,
        "signal_id": None,
        "target_asset": None,
        "account_equity_usd": to_float(summary.get("account_equity_usd")),
        "available_balance_usd": to_float(summary.get("available_balance_usd")),
        "balance_source_of_truth": summary.get("balance_source_of_truth"),
        "open_position": open_position,
        "error": None,
        "source_paths": {
            "snapshot_path": str(SNAPSHOT_PATH.resolve()),
            "quality_path": str(QUALITY_PATH.resolve()),
            "mode_config_path": str(MODE_CONFIG_PATH.resolve())
        }
    }

    manifest = {
        "artifact_name": "execution_app_status",
        "generated_at_utc": utc_now_iso(),
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(SNAPSHOT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MODE_CONFIG_PATH.resolve())
        ],
        "output_path": str(STATUS_PATH.resolve()),
        "status": "success"
    }

    STATUS_PATH.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    STATUS_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"[SAVED] {STATUS_PATH}")
    log(f"[SAVED] {STATUS_MANIFEST_PATH}")
    log("[END] render_execution_app_status success")


if __name__ == "__main__":
    main()
