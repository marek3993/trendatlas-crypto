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
STABLE_BALANCE_SYMBOLS = {"USDC", "USD", "USDT", "CASH"}
NUMERIC_EPSILON = 1e-9
HTTP_SESSION = requests.Session()
HTTP_SESSION.trust_env = False


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


def validate_runtime_posture(mode_cfg: dict[str, Any]) -> dict[str, Any]:
    mode = str(mode_cfg.get("mode") or "").strip().lower()
    trading_enabled = bool(mode_cfg.get("trading_enabled"))
    kill_switch = bool(mode_cfg.get("kill_switch"))

    if mode == "read_only":
        if trading_enabled:
            fail("execution_mode.json has trading_enabled=true. Read-only posture is invalid.")
        if not kill_switch:
            fail("execution_mode.json must keep kill_switch=true for read-only posture.")
        return {
            "mode": mode,
            "trading_enabled": trading_enabled,
            "kill_switch": kill_switch,
            "runtime_posture": "read_only_guarded",
        }

    if mode == "live":
        return {
            "mode": mode,
            "trading_enabled": trading_enabled,
            "kill_switch": kill_switch,
            "runtime_posture": "live_runtime_read_only_observability",
        }

    fail(
        "execution_mode.json must use mode='read_only' or mode='live' for account observability. "
        f"Current: {mode_cfg.get('mode')}"
    )
    raise RuntimeError("unreachable")


def post_info(payload: dict[str, Any]) -> Any:
    try:
        resp = HTTP_SESSION.post(INFO_URL, json=payload, timeout=30)
    except requests.RequestException as e:
        fail(f"Hyperliquid request failed: {e}")

    if resp.status_code != 200:
        fail(f"Hyperliquid HTTP {resp.status_code}: {resp.text[:500]}")

    try:
        return resp.json()
    except Exception as e:
        fail(f"Hyperliquid returned non-JSON response: {e}")
    raise RuntimeError("unreachable")


def try_post_info(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = HTTP_SESSION.post(INFO_URL, json=payload, timeout=30)
    except requests.RequestException as e:
        return {
            "ok": False,
            "payload_type": payload.get("type"),
            "error": f"request_exception:{type(e).__name__}:{e}",
        }

    if resp.status_code != 200:
        return {
            "ok": False,
            "payload_type": payload.get("type"),
            "http_status": resp.status_code,
            "error": resp.text[:500],
        }

    try:
        return {
            "ok": True,
            "payload_type": payload.get("type"),
            "response": resp.json(),
        }
    except Exception as e:
        return {
            "ok": False,
            "payload_type": payload.get("type"),
            "error": f"non_json_response:{type(e).__name__}:{e}",
        }


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


def extract_spot_balance_rows(spot_state: Any) -> list[dict[str, Any]]:
    if isinstance(spot_state, list):
        raw_rows = spot_state
    elif isinstance(spot_state, dict):
        raw_rows = []
        for key in ("balances", "tokenBalances", "spotBalances", "assets"):
            candidate = spot_state.get(key)
            if isinstance(candidate, list):
                raw_rows = candidate
                break
    else:
        raw_rows = []

    rows: list[dict[str, Any]] = []
    for entry in raw_rows:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("balance")
        candidate_dicts = [nested, entry] if isinstance(nested, dict) else [entry]
        coin = ""
        for candidate in candidate_dicts:
            coin = str(
                candidate.get("coin")
                or candidate.get("token")
                or candidate.get("name")
                or candidate.get("asset")
                or ""
            ).strip().upper()
            if coin:
                break
        total = None
        hold = None
        for candidate in candidate_dicts:
            total = first_float(
                candidate,
                ["total", "balance", "amount", "totalBalance", "totalRaw", "equity"],
            )
            if total is not None:
                break
        for candidate in candidate_dicts:
            hold = first_float(candidate, ["hold"])
            if hold is not None:
                break
        rows.append(
            {
                "coin": coin or "UNKNOWN",
                "token": entry.get("token"),
                "total": total,
                "hold": hold,
                "raw": entry,
            }
        )
    return rows


def sum_spot_balances(
    rows: list[dict[str, Any]],
) -> tuple[float | None, float | None, float | None]:
    matching = [row for row in rows if row.get("coin") in STABLE_BALANCE_SYMBOLS]
    if not matching:
        return None, None, None
    total = (
        sum(float(row["total"]) for row in matching)
        if all(row.get("total") is not None for row in matching)
        else None
    )
    hold = (
        sum(float(row["hold"]) for row in matching)
        if all(row.get("hold") is not None for row in matching)
        else None
    )
    free_after_hold = None
    if total is not None and hold is not None:
        candidate = total - hold
        if candidate >= -NUMERIC_EPSILON and candidate <= total + NUMERIC_EPSILON:
            free_after_hold = max(candidate, 0.0)
    return total, hold, free_after_hold


def stable_available_after_maintenance(
    spot_state: Any,
    rows: list[dict[str, Any]],
) -> float | None:
    if not isinstance(spot_state, dict):
        return None
    raw_values = spot_state.get("tokenToAvailableAfterMaintenance")
    if not isinstance(raw_values, list):
        return None
    stable_tokens = {
        int(row["token"])
        for row in rows
        if row.get("coin") in STABLE_BALANCE_SYMBOLS
        and isinstance(row.get("token"), (int, float))
    }
    values: list[float] = []
    for entry in raw_values:
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        try:
            token = int(entry[0])
        except (TypeError, ValueError):
            continue
        value = to_float(entry[1])
        if token in stable_tokens and value is not None:
            values.append(value)
    return sum(values) if values else None


def summarize_balance_sources(
    clearinghouse_state: Any,
    spot_state: Any,
    account_abstraction: Any = None,
) -> dict[str, Any]:
    perp_margin_summary = {}
    perp_cross_summary = {}
    perp_withdrawable = None
    if isinstance(clearinghouse_state, dict):
        perp_margin_summary = (
            clearinghouse_state.get("marginSummary", {})
            if isinstance(clearinghouse_state.get("marginSummary"), dict)
            else {}
        )
        perp_cross_summary = (
            clearinghouse_state.get("crossMarginSummary", {})
            if isinstance(clearinghouse_state.get("crossMarginSummary"), dict)
            else {}
        )
        perp_withdrawable = to_float(clearinghouse_state.get("withdrawable"))

    perp_account_value = first_float(perp_margin_summary, ["accountValue"])
    if perp_account_value is None:
        perp_account_value = first_float(perp_cross_summary, ["accountValue"])

    margin_used_usd = first_float(perp_margin_summary, ["totalMarginUsed"])
    if margin_used_usd is None:
        margin_used_usd = first_float(perp_cross_summary, ["totalMarginUsed"])
    position_notional_usd = first_float(perp_margin_summary, ["totalNtlPos"])
    if position_notional_usd is None:
        position_notional_usd = first_float(perp_cross_summary, ["totalNtlPos"])
    maintenance_margin_used_usd = (
        to_float(clearinghouse_state.get("crossMaintenanceMarginUsed"))
        if isinstance(clearinghouse_state, dict)
        else None
    )

    spot_rows = extract_spot_balance_rows(spot_state)
    spot_stable_total, spot_stable_hold, spot_stable_available = sum_spot_balances(spot_rows)
    available_after_maintenance_usd = stable_available_after_maintenance(spot_state, spot_rows)
    spot_source_available = isinstance(spot_state, (dict, list))

    balance_source_of_truth = "perp_clearinghouse"
    account_equity_usd = perp_account_value
    free_collateral_usd = perp_withdrawable
    free_collateral_source = "clearinghouseState.withdrawable"
    withdrawable_usd = perp_withdrawable
    withdrawable_source = "clearinghouseState.withdrawable"

    abstraction = str(account_abstraction or "").strip()
    unified_balance = abstraction.lower() in {"unifiedaccount", "portfoliomargin"}
    if unified_balance:
        balance_source_of_truth = "spot_stable_balance"
        account_equity_usd = spot_stable_total if spot_source_available else None
        free_collateral_usd = spot_stable_available
        free_collateral_source = (
            "spotClearinghouseState.stable_total_minus_native_hold"
            if free_collateral_usd is not None
            else "unavailable_missing_or_incoherent_spot_total_hold"
        )
        # Hyperliquid documents individual perp DEX user states as not meaningful
        # for unified and portfolio-margin API users. Preserve the raw diagnostic,
        # but do not publish it as a unified-account withdrawable amount.
        withdrawable_usd = None
        withdrawable_source = "unavailable_individual_perp_state_not_meaningful"
        if (
            margin_used_usd is not None
            and margin_used_usd > NUMERIC_EPSILON
            and (spot_stable_hold is None or spot_stable_hold <= NUMERIC_EPSILON)
        ):
            free_collateral_usd = None
            free_collateral_source = "unavailable_incoherent_nonzero_margin_without_native_hold"

    return {
        "balance_source_of_truth": balance_source_of_truth,
        "account_equity_usd": account_equity_usd,
        "free_collateral_usd": free_collateral_usd,
        "available_balance_usd": free_collateral_usd,
        "free_collateral_status": "available" if free_collateral_usd is not None else "unavailable",
        "free_collateral_source": free_collateral_source,
        "withdrawable_usd": withdrawable_usd,
        "withdrawable_status": "available" if withdrawable_usd is not None else "unavailable",
        "withdrawable_source": withdrawable_source,
        "margin_used_usd": margin_used_usd,
        "position_notional_usd": position_notional_usd,
        "maintenance_margin_used_usd": maintenance_margin_used_usd,
        "available_after_maintenance_usd": available_after_maintenance_usd,
        "perp_account_value": perp_account_value,
        "perp_withdrawable": perp_withdrawable,
        "spot_balance_count": len(spot_rows),
        "spot_balance_symbols": sorted({row["coin"] for row in spot_rows if row.get("coin")}),
        "spot_stable_total_usd": spot_stable_total,
        "spot_stable_hold_usd": spot_stable_hold,
        "spot_stable_available_usd": spot_stable_available,
        "spot_source_available": spot_source_available,
        "account_abstraction": abstraction or None,
        "spot_balance_usable_for_perps": unified_balance,
    }


def main() -> None:
    ensure_dirs()
    started_at = utc_now_iso()
    log("[START] hyperliquid_read_only_snapshot")

    mode_cfg = read_json(MODE_CONFIG_PATH)
    runtime_posture = validate_runtime_posture(mode_cfg)

    if not ACCOUNT_CONFIG_PATH.exists():
        fail(
            f"Missing required file: {ACCOUNT_CONFIG_PATH}. "
            f"Create it by copying {ACCOUNT_TEMPLATE_PATH.name} and filling account_address."
        )

    account_cfg = read_json(ACCOUNT_CONFIG_PATH)
    account_address = str(account_cfg.get("account_address", "")).strip()
    if not account_address or "PASTE_" in account_address:
        fail(f"execution/config/hyperliquid_account.json must contain a real account_address.")

    log(
        "[CONFIG] "
        f"mode={runtime_posture['mode']} "
        f"trading_enabled={runtime_posture['trading_enabled']} "
        f"kill_switch={runtime_posture['kill_switch']} "
        f"runtime_posture={runtime_posture['runtime_posture']}"
    )
    log(f"[CONFIG] account_address={account_address}")

    payloads = {
        "clearinghouseState": {"type": "clearinghouseState", "user": account_address},
        "spotClearinghouseState": {"type": "spotClearinghouseState", "user": account_address},
        "openOrders": {"type": "openOrders", "user": account_address},
        "userFills": {"type": "userFills", "user": account_address},
        "userAbstraction": {"type": "userAbstraction", "user": account_address},
    }

    log("[FETCH] clearinghouseState")
    clearinghouse_state = post_info(payloads["clearinghouseState"])

    log("[FETCH] spotClearinghouseState")
    spot_clearinghouse_result = try_post_info(payloads["spotClearinghouseState"])
    if spot_clearinghouse_result["ok"]:
        spot_clearinghouse_state = spot_clearinghouse_result["response"]
    else:
        spot_clearinghouse_state = None
        log(
            "[WARN] spotClearinghouseState unavailable: "
            f"{spot_clearinghouse_result.get('error')}"
        )

    log("[FETCH] openOrders")
    open_orders = post_info(payloads["openOrders"])

    log("[FETCH] userFills")
    user_fills = post_info(payloads["userFills"])

    log("[FETCH] userAbstraction")
    user_abstraction_result = try_post_info(payloads["userAbstraction"])
    user_abstraction = (
        user_abstraction_result.get("response")
        if user_abstraction_result.get("ok")
        else None
    )
    if not user_abstraction_result.get("ok"):
        log(f"[WARN] userAbstraction unavailable: {user_abstraction_result.get('error')}")

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

    balance_summary = summarize_balance_sources(
        clearinghouse_state,
        spot_clearinghouse_state,
        user_abstraction,
    )

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
            "spotClearinghouseState": (
                spot_clearinghouse_state
                if spot_clearinghouse_result["ok"]
                else {"fetch_error": spot_clearinghouse_result}
            ),
            "openOrders": open_orders,
            "userFills": user_fills,
            "userAbstraction": (
                user_abstraction
                if user_abstraction_result.get("ok")
                else {"fetch_error": user_abstraction_result}
            ),
        },
        "summary": {
            "positions_count": len(positions) if isinstance(positions, list) else 0,
            "open_orders_count": len(open_orders) if isinstance(open_orders, list) else 0,
            "recent_fills_count": len(user_fills) if isinstance(user_fills, list) else 0,
            "runtime_posture": runtime_posture["runtime_posture"],
            "withdrawable": withdrawable,
            "margin_summary": margin_summary,
            "cross_margin_summary": balances,
            "balance_source_of_truth": balance_summary["balance_source_of_truth"],
            "account_equity_usd": balance_summary["account_equity_usd"],
            "free_collateral_usd": balance_summary["free_collateral_usd"],
            "available_balance_usd": balance_summary["available_balance_usd"],
            "free_collateral_status": balance_summary["free_collateral_status"],
            "free_collateral_source": balance_summary["free_collateral_source"],
            "withdrawable_usd": balance_summary["withdrawable_usd"],
            "withdrawable_status": balance_summary["withdrawable_status"],
            "withdrawable_source": balance_summary["withdrawable_source"],
            "margin_used_usd": balance_summary["margin_used_usd"],
            "position_notional_usd": balance_summary["position_notional_usd"],
            "maintenance_margin_used_usd": balance_summary["maintenance_margin_used_usd"],
            "available_after_maintenance_usd": balance_summary["available_after_maintenance_usd"],
            "perp_account_value": balance_summary["perp_account_value"],
            "perp_withdrawable": balance_summary["perp_withdrawable"],
            "spot_balance_count": balance_summary["spot_balance_count"],
            "spot_balance_symbols": balance_summary["spot_balance_symbols"],
            "spot_stable_total_usd": balance_summary["spot_stable_total_usd"],
            "spot_stable_hold_usd": balance_summary["spot_stable_hold_usd"],
            "spot_stable_available_usd": balance_summary["spot_stable_available_usd"],
            "spot_source_available": balance_summary["spot_source_available"],
            "account_abstraction": balance_summary["account_abstraction"],
            "spot_balance_usable_for_perps": balance_summary["spot_balance_usable_for_perps"],
        }
    }

    quality = {
        "snapshot_ok": True,
        "mode_ok": runtime_posture["mode"] in {"read_only", "live"},
        "trading_disabled_ok": (
            bool(mode_cfg.get("trading_enabled")) is False
            if runtime_posture["mode"] == "read_only"
            else None
        ),
        "kill_switch_ok": (
            bool(mode_cfg.get("kill_switch")) is True
            if runtime_posture["mode"] == "read_only"
            else None
        ),
        "runtime_posture": runtime_posture["runtime_posture"],
        "account_address_present": True,
        "http_source": INFO_URL,
        "positions_count": snapshot["summary"]["positions_count"],
        "open_orders_count": snapshot["summary"]["open_orders_count"],
        "recent_fills_count": snapshot["summary"]["recent_fills_count"],
        "balance_source_of_truth": snapshot["summary"]["balance_source_of_truth"],
        "account_equity_usd": snapshot["summary"]["account_equity_usd"],
        "free_collateral_usd": snapshot["summary"]["free_collateral_usd"],
        "available_balance_usd": snapshot["summary"]["available_balance_usd"],
        "withdrawable_usd": snapshot["summary"]["withdrawable_usd"],
        "margin_used_usd": snapshot["summary"]["margin_used_usd"],
        "position_notional_usd": snapshot["summary"]["position_notional_usd"],
        "spot_source_available": snapshot["summary"]["spot_source_available"],
        "account_abstraction": snapshot["summary"]["account_abstraction"],
        "spot_balance_usable_for_perps": snapshot["summary"]["spot_balance_usable_for_perps"],
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
        "started_at_utc": started_at,
        "runtime_posture": runtime_posture["runtime_posture"],
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
