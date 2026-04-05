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
        "current_position": "unknown_read_raw_positions_snapshot",
        "last_action": "snapshot_refresh",
        "last_action_result": "success",
        "guardrails_ok": True,
        "stale_signal": None,
        "signal_id": None,
        "target_asset": None,
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
