from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: Missing dependency 'requests'. Install with: pip install requests")
    sys.exit(1)


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "execution" / "config"
OUTPUT_DIR = ROOT / "outputs" / "execution"
READ_ONLY_DIR = OUTPUT_DIR / "read_only"
LOGS_DIR = OUTPUT_DIR / "logs"

ACCOUNT_CONFIG_PATH = CONFIG_DIR / "hyperliquid_account.json"
ACCOUNT_TEMPLATE_PATH = CONFIG_DIR / "hyperliquid_account.json.template"
MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"

SNAPSHOT_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot.json"
QUALITY_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot_quality.json"
MANIFEST_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot_manifest.json"
LOG_PATH = LOGS_DIR / "hyperliquid_read_only_snapshot.log"

INFO_URL = "https://api.hyperliquid.xyz/info"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(msg: str) -> None:
    line = msg
    print(line)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


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


def ensure_dirs() -> None:
    READ_ONLY_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def post_info(payload: dict[str, Any]) -> Any:
    try:
        resp = requests.post(INFO_URL, json=payload, timeout=30)
    except requests.RequestException as e:
        fail(f"Hyperliquid request failed: {e}")

    if resp.status_code != 200:
        fail(f"Hyperliquid HTTP {resp.status_code}: {resp.text[:500]}")

    try:
        return resp.json()
    except Exception as e:
        fail(f"Hyperliquid returned non-JSON response: {e}")
    raise RuntimeError("unreachable")


def main() -> None:
    ensure_dirs()
    started_at = utc_now_iso()
    log("[START] hyperliquid_read_only_snapshot")

    mode_cfg = read_json(MODE_CONFIG_PATH)
    if mode_cfg.get("mode") != "read_only":
        fail(f"execution_mode.json must have mode='read_only'. Current: {mode_cfg.get('mode')}")
    if bool(mode_cfg.get("trading_enabled")):
        fail("execution_mode.json has trading_enabled=true. Read-only script refuses to run.")
    if not bool(mode_cfg.get("kill_switch")):
        fail("execution_mode.json must keep kill_switch=true for read-only milestone.")

    if not ACCOUNT_CONFIG_PATH.exists():
        fail(
            f"Missing required file: {ACCOUNT_CONFIG_PATH}. "
            f"Create it by copying {ACCOUNT_TEMPLATE_PATH.name} and filling account_address."
        )

    account_cfg = read_json(ACCOUNT_CONFIG_PATH)
    account_address = str(account_cfg.get("account_address", "")).strip()
    if not account_address or "PASTE_" in account_address:
        fail(f"execution/config/hyperliquid_account.json must contain a real account_address.")

    log(f"[CONFIG] mode=read_only trading_enabled={mode_cfg.get('trading_enabled')} kill_switch={mode_cfg.get('kill_switch')}")
    log(f"[CONFIG] account_address={account_address}")

    payloads = {
        "clearinghouseState": {"type": "clearinghouseState", "user": account_address},
        "openOrders": {"type": "openOrders", "user": account_address},
        "userFills": {"type": "userFills", "user": account_address}
    }

    log("[FETCH] clearinghouseState")
    clearinghouse_state = post_info(payloads["clearinghouseState"])

    log("[FETCH] openOrders")
    open_orders = post_info(payloads["openOrders"])

    log("[FETCH] userFills")
    user_fills = post_info(payloads["userFills"])

    positions = []
    margin_summary = {}
    balances = {}
    withdrawable = None

    if isinstance(clearinghouse_state, dict):
        asset_positions = clearinghouse_state.get("assetPositions", [])
        if isinstance(asset_positions, list):
            positions = asset_positions
        margin_summary = clearinghouse_state.get("marginSummary", {})
        balances = clearinghouse_state.get("crossMarginSummary", {})
        withdrawable = clearinghouse_state.get("withdrawable")

    snapshot = {
        "snapshot_type": "hyperliquid_read_only_account_snapshot",
        "as_of_utc": utc_now_iso(),
        "execution_mode": mode_cfg.get("mode"),
        "trading_enabled": bool(mode_cfg.get("trading_enabled")),
        "kill_switch": bool(mode_cfg.get("kill_switch")),
        "account_address": account_address,
        "source": {
            "provider": "Hyperliquid",
            "info_url": INFO_URL
        },
        "raw": {
            "clearinghouseState": clearinghouse_state,
            "openOrders": open_orders,
            "userFills": user_fills
        },
        "summary": {
            "positions_count": len(positions) if isinstance(positions, list) else 0,
            "open_orders_count": len(open_orders) if isinstance(open_orders, list) else 0,
            "recent_fills_count": len(user_fills) if isinstance(user_fills, list) else 0,
            "withdrawable": withdrawable,
            "margin_summary": margin_summary,
            "cross_margin_summary": balances
        }
    }

    quality = {
        "snapshot_ok": True,
        "mode_ok": mode_cfg.get("mode") == "read_only",
        "trading_disabled_ok": bool(mode_cfg.get("trading_enabled")) is False,
        "kill_switch_ok": bool(mode_cfg.get("kill_switch")) is True,
        "account_address_present": True,
        "http_source": INFO_URL,
        "positions_count": snapshot["summary"]["positions_count"],
        "open_orders_count": snapshot["summary"]["open_orders_count"],
        "recent_fills_count": snapshot["summary"]["recent_fills_count"]
    }

    manifest = {
        "artifact_name": "hyperliquid_read_only_account_snapshot",
        "generated_at_utc": utc_now_iso(),
        "script_path": str(Path(__file__).resolve()),
        "config_paths": [
            str(MODE_CONFIG_PATH.resolve()),
            str(ACCOUNT_CONFIG_PATH.resolve())
        ],
        "output_paths": [
            str(SNAPSHOT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve())
        ],
        "status": "success",
        "started_at_utc": started_at
    }

    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {SNAPSHOT_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log("[END] hyperliquid_read_only_snapshot success")


if __name__ == "__main__":
    main()