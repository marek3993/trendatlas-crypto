from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_UP
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: Missing dependency 'requests'. Install with: pip install requests")
    sys.exit(1)


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution.hyperliquid_credentials import (  # noqa: E402
    get_account_setup as get_secure_account_setup,
    load_secret_key as load_systemd_secret_key,
)
from scripts.execution.hyperliquid_read_only_snapshot import (  # noqa: E402
    summarize_balance_sources as summarize_read_only_balance_sources,
)

EXECUTION_DIR = ROOT / "execution"
CONFIG_DIR = EXECUTION_DIR / "config"
OUTPUTS_DIR = ROOT / "outputs" / "execution"

ACCOUNT_CONFIG_PATH = CONFIG_DIR / "hyperliquid_account.json"
ACCOUNT_TEMPLATE_PATH = CONFIG_DIR / "hyperliquid_account.json.template"
MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"
GATE_PATH = OUTPUTS_DIR / "live_gate" / "latest_real_order_gate_decision.json"
SUBMIT_PREVIEW_PATH = OUTPUTS_DIR / "submit_preview" / "latest_submit_preview_decision.json"

CANARY_DIR = OUTPUTS_DIR / "canary"
LOGS_DIR = OUTPUTS_DIR / "logs"
LOG_PATH = LOGS_DIR / "hyperliquid_live_canary.log"

MAINNET_API_URL = "https://api.hyperliquid.xyz"
INFO_URL = f"{MAINNET_API_URL}/info"
EXCHANGE_URL = f"{MAINNET_API_URL}/exchange"

MANUAL_CONFIRM_TOKEN = "LIVE_CANARY"
MIN_CANARY_NOTIONAL_USD = 10.0
DEFAULT_SLIPPAGE = 0.01
DEFAULT_EXPIRES_AFTER_MS = 180_000
DEFAULT_POLL_SECONDS = 15.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.5
POSITION_TOLERANCE = 1e-9

TERMINAL_ORDER_STATES = {
    "canceled",
    "cancelled",
    "filled",
    "rejected",
    "rejection",
    "error",
    "triggered",
    "margin_canceled",
    "ioc_cancelled",
    "ioc_canceled",
}


@dataclass(frozen=True)
class CryptoDeps:
    msgpack: Any
    Account: Any
    encode_typed_data: Any
    keccak: Any
    to_hex: Any


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(message: str) -> None:
    print(message)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def fail(message: str, code: int = 1) -> None:
    log(f"ERROR: {message}")
    raise SystemExit(code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON in {path}: {exc}")
    except Exception as exc:
        fail(f"Failed reading {path}: {exc}")
    raise RuntimeError("unreachable")


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_side(value: Any) -> str:
    side = str(value or "").strip().lower()
    if side not in {"buy", "sell"}:
        fail(f"Unsupported side: {value}")
    return side


def require_crypto_deps() -> CryptoDeps:
    try:
        import msgpack
        from eth_account import Account
        from eth_account.messages import encode_typed_data
        from eth_utils import keccak, to_hex
    except ImportError:
        fail(
            "Missing signing dependencies. Install with: "
            "pip install eth-account eth-utils msgpack"
        )
    return CryptoDeps(
        msgpack=msgpack,
        Account=Account,
        encode_typed_data=encode_typed_data,
        keccak=keccak,
        to_hex=to_hex,
    )


def post_json(url: str, payload: dict[str, Any]) -> Any:
    try:
        response = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as exc:
        fail(f"Hyperliquid request failed: {exc}")

    if response.status_code != 200:
        fail(f"Hyperliquid HTTP {response.status_code}: {response.text[:500]}")

    try:
        return response.json()
    except Exception as exc:
        fail(f"Hyperliquid returned non-JSON response: {exc}")
    raise RuntimeError("unreachable")


def info_request(payload: dict[str, Any]) -> Any:
    return post_json(INFO_URL, payload)


def exchange_request(payload: dict[str, Any]) -> Any:
    return post_json(EXCHANGE_URL, payload)


def try_info_request(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "payload_type": payload.get("type"),
            "response": post_json(INFO_URL, payload),
        }
    except SystemExit as exc:
        return {
            "ok": False,
            "payload_type": payload.get("type"),
            "error": f"info_request_failed:exit_code:{exc.code}",
        }


def ensure_manual_execution(manual_confirm: str) -> None:
    if manual_confirm != MANUAL_CONFIRM_TOKEN:
        fail(
            "Manual confirmation missing. "
            f"Pass --manual-confirm {MANUAL_CONFIRM_TOKEN} to unlock live canary flow."
        )


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=False)


def address_to_bytes(address: str) -> bytes:
    return bytes.fromhex(address[2:] if address.startswith("0x") else address)


def action_hash(
    crypto: CryptoDeps,
    action: Any,
    vault_address: str | None,
    nonce: int,
    expires_after: int | None,
) -> bytes:
    encoded = crypto.msgpack.packb(action)
    encoded += nonce.to_bytes(8, "big")
    if vault_address is None:
        encoded += b"\x00"
    else:
        encoded += b"\x01"
        encoded += address_to_bytes(vault_address)
    if expires_after is not None:
        encoded += b"\x00"
        encoded += expires_after.to_bytes(8, "big")
    return crypto.keccak(encoded)


def construct_phantom_agent(action_hash_bytes: bytes, is_mainnet: bool) -> dict[str, Any]:
    return {
        "source": "a" if is_mainnet else "b",
        "connectionId": action_hash_bytes,
    }


def l1_payload(phantom_agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": {
            "chainId": 1337,
            "name": "Exchange",
            "verifyingContract": "0x0000000000000000000000000000000000000000",
            "version": "1",
        },
        "types": {
            "Agent": [
                {"name": "source", "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": "Agent",
        "message": phantom_agent,
    }


def sign_inner(crypto: CryptoDeps, wallet: Any, data: dict[str, Any]) -> dict[str, Any]:
    structured_data = crypto.encode_typed_data(full_message=data)
    signed = wallet.sign_message(structured_data)
    return {
        "r": crypto.to_hex(signed["r"]),
        "s": crypto.to_hex(signed["s"]),
        "v": signed["v"],
    }


def sign_l1_action(
    crypto: CryptoDeps,
    wallet: Any,
    action: Any,
    vault_address: str | None,
    nonce: int,
    expires_after: int | None,
    is_mainnet: bool,
) -> dict[str, Any]:
    hashed = action_hash(crypto, action, vault_address, nonce, expires_after)
    phantom_agent = construct_phantom_agent(hashed, is_mainnet)
    return sign_inner(crypto, wallet, l1_payload(phantom_agent))


def recover_agent_or_user_from_l1_action(
    crypto: CryptoDeps,
    action: Any,
    signature: dict[str, Any],
    vault_address: str | None,
    nonce: int,
    expires_after: int | None,
    is_mainnet: bool,
) -> str:
    hashed = action_hash(crypto, action, vault_address, nonce, expires_after)
    phantom_agent = construct_phantom_agent(hashed, is_mainnet)
    structured_data = crypto.encode_typed_data(full_message=l1_payload(phantom_agent))
    return crypto.Account.recover_message(
        structured_data,
        vrs=[signature["v"], signature["r"], signature["s"]],
    )


def float_to_wire(value: float) -> str:
    rounded = f"{value:.8f}"
    if abs(float(rounded) - value) >= 1e-12:
        raise ValueError(f"float_to_wire causes rounding: {value}")
    normalized = Decimal(rounded).normalize()
    return f"{normalized:f}"


def order_type_to_wire(order_type: dict[str, Any]) -> dict[str, Any]:
    if "limit" in order_type:
        return {"limit": order_type["limit"]}
    raise ValueError(f"Unsupported order type: {order_type}")


def order_request_to_wire(order: dict[str, Any], asset: int) -> dict[str, Any]:
    wire = {
        "a": asset,
        "b": bool(order["is_buy"]),
        "p": float_to_wire(float(order["limit_px"])),
        "s": float_to_wire(float(order["sz"])),
        "r": bool(order["reduce_only"]),
        "t": order_type_to_wire(order["order_type"]),
    }
    cloid = str(order.get("cloid") or "").strip()
    if cloid:
        if not cloid.startswith("0x") or len(cloid) != 34:
            raise ValueError("Hyperliquid CLOID must be a 128-bit 0x-prefixed hex string")
        int(cloid[2:], 16)
        wire["c"] = cloid
    return wire


def make_action(order_wire: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "order",
        "orders": [order_wire],
        "grouping": "na",
    }


def load_secret_key(account_cfg: dict[str, Any]) -> str:
    return load_systemd_secret_key(account_cfg)


def get_account_setup(account_cfg: dict[str, Any], crypto: CryptoDeps) -> dict[str, Any]:
    return get_secure_account_setup(account_cfg, crypto)


def fetch_meta() -> dict[str, Any]:
    meta = info_request({"type": "meta"})
    if not isinstance(meta, dict) or not isinstance(meta.get("universe"), list):
        fail("Hyperliquid meta response is missing universe data")
    return meta


def fetch_all_mids() -> dict[str, Any]:
    mids = info_request({"type": "allMids"})
    if not isinstance(mids, dict):
        fail("Hyperliquid allMids response is not a JSON object")
    return mids


def fetch_user_state(account_address: str) -> dict[str, Any]:
    payload = {"type": "clearinghouseState", "user": account_address}
    state = info_request(payload)
    if not isinstance(state, dict):
        fail("Hyperliquid clearinghouseState response is not a JSON object")
    return state


def fetch_spot_user_state(account_address: str) -> dict[str, Any] | None:
    payload = {"type": "spotClearinghouseState", "user": account_address}
    result = try_info_request(payload)
    if not result["ok"]:
        return None
    response = result["response"]
    return response if isinstance(response, dict) else None


def fetch_open_orders(account_address: str) -> list[dict[str, Any]]:
    orders = info_request({"type": "openOrders", "user": account_address})
    return orders if isinstance(orders, list) else []


def fetch_user_fills_by_time(account_address: str, start_time_ms: int, end_time_ms: int | None = None) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "type": "userFillsByTime",
        "user": account_address,
        "startTime": start_time_ms,
        "aggregateByTime": False,
    }
    if end_time_ms is not None:
        payload["endTime"] = end_time_ms
    fills = info_request(payload)
    return fills if isinstance(fills, list) else []


def fetch_order_status(account_address: str, oid: int | str) -> Any:
    return info_request({"type": "orderStatus", "user": account_address, "oid": oid})


def fetch_user_abstraction(account_address: str) -> Any:
    return info_request({"type": "userAbstraction", "user": account_address})


def fetch_user_role(account_address: str) -> Any:
    return info_request({"type": "userRole", "user": account_address})


def fetch_extra_agents(account_address: str) -> list[dict[str, Any]]:
    response = info_request({"type": "extraAgents", "user": account_address})
    return response if isinstance(response, list) else []


def build_market_map(meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    market_map: dict[str, dict[str, Any]] = {}
    for asset, entry in enumerate(meta.get("universe", [])):
        if not isinstance(entry, dict):
            continue
        coin = normalize_asset(entry.get("name"))
        if not coin:
            continue
        market_map[coin] = {
            "asset": asset,
            "sz_decimals": int(entry.get("szDecimals", 0)),
            "raw": entry,
        }
    return market_map


def compute_limit_price(mid_price: float, is_buy: bool, slippage: float, sz_decimals: int) -> float:
    adjusted = mid_price * (1 + slippage if is_buy else 1 - slippage)
    decimals = max(0, 6 - sz_decimals)
    return round(float(f"{adjusted:.5g}"), decimals)


def quantize_up(value: float, decimals: int) -> float:
    step = Decimal("1").scaleb(-decimals)
    return float(Decimal(str(value)).quantize(step, rounding=ROUND_UP))


def compute_order_size(notional_usd: float, limit_price: float, sz_decimals: int) -> float:
    if limit_price <= 0:
        fail(f"Invalid limit price for size computation: {limit_price}")
    raw_size = notional_usd / limit_price
    size = quantize_up(raw_size, sz_decimals)
    if size <= 0:
        fail("Computed canary size rounded to zero")
    return size


def extract_positions(user_state: dict[str, Any]) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    asset_positions = user_state.get("assetPositions", [])
    if not isinstance(asset_positions, list):
        return positions

    for item in asset_positions:
        if not isinstance(item, dict):
            continue
        position = item.get("position") or item
        if not isinstance(position, dict):
            continue
        coin = normalize_asset(position.get("coin") or item.get("coin"))
        size_raw = position.get("szi") or position.get("size") or position.get("positionSize") or 0
        try:
            size = float(str(size_raw))
        except Exception:
            size = 0.0
        if abs(size) > POSITION_TOLERANCE:
            positions.append(
                {
                    "coin": coin or "UNKNOWN",
                    "size": size,
                    "raw": item,
                }
            )
    return positions


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


def summarize_snapshot(
    account_address: str,
    state: dict[str, Any],
    spot_state: dict[str, Any] | None,
    open_orders: list[dict[str, Any]],
    account_abstraction: Any = None,
) -> dict[str, Any]:
    positions = extract_positions(state)
    margin_summary = state.get("marginSummary", {}) if isinstance(state.get("marginSummary"), dict) else {}
    cross_summary = state.get("crossMarginSummary", {}) if isinstance(state.get("crossMarginSummary"), dict) else {}
    balance_summary = summarize_read_only_balance_sources(
        state,
        spot_state,
        account_abstraction,
    )
    return {
        "account_address": account_address,
        "positions": positions,
        "positions_count": len(positions),
        "open_orders_count": len(open_orders),
        "open_orders": open_orders,
        "margin_summary": margin_summary,
        "cross_margin_summary": cross_summary,
        "withdrawable": state.get("withdrawable"),
        "balance_source_of_truth": balance_summary["balance_source_of_truth"],
        "account_equity_usd": balance_summary["account_equity_usd"],
        "free_collateral_usd": balance_summary["free_collateral_usd"],
        "available_balance_usd": balance_summary["available_balance_usd"],
        "withdrawable_usd": balance_summary["withdrawable_usd"],
        "margin_used_usd": balance_summary["margin_used_usd"],
        "position_notional_usd": balance_summary["position_notional_usd"],
        "free_collateral_source": balance_summary["free_collateral_source"],
        "withdrawable_source": balance_summary["withdrawable_source"],
        "account_abstraction": balance_summary["account_abstraction"],
        "perp_account_value": balance_summary["perp_account_value"],
        "perp_withdrawable": balance_summary["perp_withdrawable"],
        "spot_balance_count": balance_summary["spot_balance_count"],
        "spot_balance_symbols": balance_summary["spot_balance_symbols"],
        "spot_stable_total_usd": balance_summary["spot_stable_total_usd"],
        "spot_stable_available_usd": balance_summary["spot_stable_available_usd"],
        "spot_source_available": balance_summary["spot_source_available"],
        "raw": {
            "clearinghouseState": state,
            "spotClearinghouseState": spot_state,
            "openOrders": open_orders,
        },
    }


def find_position_size(snapshot: dict[str, Any], coin: str) -> float:
    for position in snapshot.get("positions", []):
        if normalize_asset(position.get("coin")) == coin:
            return float(position.get("size", 0.0))
    return 0.0


def extract_agent_addresses(extra_agents: list[dict[str, Any]]) -> list[str]:
    addresses: list[str] = []
    for entry in extra_agents:
        if not isinstance(entry, dict):
            continue
        address = str(entry.get("address", "")).strip()
        if address:
            addresses.append(address.lower())
    return addresses


def build_submit_normalization_fallback(
    response: Any,
    reason: str,
    *,
    exchange_status: Any = None,
) -> dict[str, Any]:
    return {
        "exchange_status": exchange_status,
        "acknowledged": False,
        "oid": None,
        "submit_state": "manual_review_required",
        "fill": None,
        "resting": None,
        "error": reason,
        "raw": response,
        "raw_type": type(response).__name__,
        "normalization_ok": False,
        "needs_manual_review": True,
    }


def normalize_submit_response(response: Any) -> dict[str, Any]:
    if isinstance(response, str):
        return build_submit_normalization_fallback(response, "non_dict_submit_response:string")
    if not isinstance(response, dict):
        return build_submit_normalization_fallback(
            response,
            f"non_dict_submit_response:{type(response).__name__}",
        )

    exchange_status = response.get("status")
    normalized = {
        "exchange_status": exchange_status,
        "acknowledged": False,
        "oid": None,
        "submit_state": "unknown",
        "fill": None,
        "resting": None,
        "error": None,
        "raw": response,
        "raw_type": type(response).__name__,
        "normalization_ok": False,
        "needs_manual_review": False,
    }

    response_body = response.get("response")
    if response_body is None:
        if exchange_status == "ok":
            return build_submit_normalization_fallback(
                response,
                "missing_response_field_on_ok_submit",
                exchange_status=exchange_status,
            )
        normalized["submit_state"] = "error"
        normalized["error"] = response.get("error") or response.get("message") or "missing_response_field"
        normalized["normalization_ok"] = True
        return normalized

    if not isinstance(response_body, dict):
        return build_submit_normalization_fallback(
            response,
            f"unexpected_response_field_type:{type(response_body).__name__}",
            exchange_status=exchange_status,
        )

    response_type = str(response_body.get("type", "")).strip().lower()
    if exchange_status == "ok" and response_type == "default":
        normalized["submit_state"] = "acknowledged_non_order_action"
        normalized["acknowledged"] = True
        normalized["normalization_ok"] = True
        return normalized

    data_body = response_body.get("data")
    if not isinstance(data_body, dict):
        return build_submit_normalization_fallback(
            response,
            f"unexpected_response_data_type:{type(data_body).__name__}",
            exchange_status=exchange_status,
        )

    statuses = data_body.get("statuses")
    if not isinstance(statuses, list):
        return build_submit_normalization_fallback(
            response,
            f"unexpected_statuses_type:{type(statuses).__name__}",
            exchange_status=exchange_status,
        )
    if not statuses:
        return build_submit_normalization_fallback(
            response,
            "empty_statuses_list",
            exchange_status=exchange_status,
        )

    entry = statuses[0]
    if not isinstance(entry, dict):
        return build_submit_normalization_fallback(
            response,
            f"unexpected_status_entry_type:{type(entry).__name__}",
            exchange_status=exchange_status,
        )

    if "filled" in entry and isinstance(entry["filled"], dict):
        filled = entry["filled"]
        normalized["submit_state"] = "filled"
        normalized["fill"] = filled
        normalized["oid"] = filled.get("oid")
        normalized["acknowledged"] = exchange_status == "ok"
        normalized["normalization_ok"] = True
        return normalized

    if "resting" in entry and isinstance(entry["resting"], dict):
        resting = entry["resting"]
        normalized["submit_state"] = "resting"
        normalized["resting"] = resting
        normalized["oid"] = resting.get("oid")
        normalized["acknowledged"] = exchange_status == "ok"
        normalized["normalization_ok"] = True
        return normalized

    if "error" in entry:
        normalized["submit_state"] = "error"
        normalized["error"] = entry.get("error")
        normalized["normalization_ok"] = True
        return normalized

    return build_submit_normalization_fallback(
        response,
        "unrecognized_status_entry_shape",
        exchange_status=exchange_status,
    )


def normalize_order_status(raw: Any, fallback_oid: int | None) -> dict[str, Any]:
    normalized = {
        "oid": fallback_oid,
        "status": "unknown",
        "terminal": False,
        "order_present": False,
        "raw": raw,
    }

    if isinstance(raw, dict):
        if isinstance(raw.get("order"), dict):
            order = raw["order"]
            normalized["order_present"] = True
            normalized["oid"] = order.get("oid", fallback_oid)
            status_value = str(raw.get("status", order.get("status", ""))).strip().lower()
            if status_value:
                normalized["status"] = status_value
        elif isinstance(raw.get("data"), dict):
            return normalize_order_status(raw["data"], fallback_oid)
        elif isinstance(raw.get("statuses"), list) and raw["statuses"]:
            return normalize_order_status(raw["statuses"][0], fallback_oid)
        elif "error" in raw:
            normalized["status"] = "error"
        else:
            for key in ("status", "state", "orderStatus"):
                candidate = str(raw.get(key, "")).strip().lower()
                if candidate:
                    normalized["status"] = candidate
                    break
    elif isinstance(raw, list) and raw:
        return normalize_order_status(raw[0], fallback_oid)

    normalized["terminal"] = normalized["status"] in TERMINAL_ORDER_STATES
    return normalized


def filter_fills_for_oid(fills: list[dict[str, Any]], oid: int | None) -> list[dict[str, Any]]:
    if oid is None:
        return []
    matched: list[dict[str, Any]] = []
    for fill in fills:
        if not isinstance(fill, dict):
            continue
        if fill.get("oid") == oid:
            matched.append(fill)
    return matched


def summarize_fills(fills: list[dict[str, Any]]) -> dict[str, Any]:
    total_size = 0.0
    total_px_size = 0.0
    for fill in fills:
        try:
            size = abs(float(str(fill.get("sz", 0.0))))
        except Exception:
            size = 0.0
        try:
            px = float(str(fill.get("px", 0.0)))
        except Exception:
            px = 0.0
        total_size += size
        total_px_size += size * px
    average_px = total_px_size / total_size if total_size > POSITION_TOLERANCE else None
    return {
        "fills_count": len(fills),
        "filled_size": total_size,
        "average_px": average_px,
        "fills": fills,
    }


def build_artifact_paths(run_dir: Path) -> dict[str, Path]:
    return {
        "preflight": run_dir / "canary_preflight.json",
        "submit_response": run_dir / "canary_submit_response.json",
        "order_timeline": run_dir / "canary_order_timeline.json",
        "post_snapshot": run_dir / "canary_post_snapshot.json",
        "reconciliation": run_dir / "canary_reconciliation.json",
        "rollback_plan": run_dir / "canary_rollback_plan.json",
        "manifest": run_dir / "canary_manifest.json",
    }


def create_run_dir(command: str, coin: str) -> tuple[str, Path]:
    run_id = f"{utc_now_compact()}_{command}_{coin.lower()}"
    run_dir = CANARY_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


def load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def verify_agent_authorization(account_address: str, signer_address: str) -> dict[str, Any]:
    role_response = fetch_user_role(account_address)
    extra_agents = fetch_extra_agents(account_address)
    role_text = compact_json(role_response).lower()
    looks_like_agent_account = "agent" in role_text and "user" not in role_text
    agent_addresses = extract_agent_addresses(extra_agents)
    signer_authorized = signer_address.lower() in agent_addresses
    return {
        "user_role": role_response,
        "extra_agents": extra_agents,
        "looks_like_agent_account": looks_like_agent_account,
        "authorized_agent_addresses": agent_addresses,
        "signer_authorized": signer_authorized,
    }


def build_preflight(
    args: argparse.Namespace,
    account_setup: dict[str, Any],
    market_map: dict[str, dict[str, Any]],
    mids: dict[str, Any],
    snapshot: dict[str, Any],
    mode_cfg: dict[str, Any],
    policy_cfg: dict[str, Any],
    gate_context: dict[str, Any] | None,
    submit_context: dict[str, Any] | None,
    auth_probe: dict[str, Any],
    agent_verification: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    coin = normalize_asset(args.coin)
    allowed_assets = {
        normalize_asset(item) for item in policy_cfg.get("allowed_assets", [])
        if str(item).strip()
    }
    market_entry = market_map.get(coin)
    positions = snapshot.get("positions", [])
    buy_slippage = float(args.slippage)

    abort_conditions: list[str] = []

    if not account_setup["account_address"]:
        abort_conditions.append("missing_account_address")
    if args.execute_live and args.manual_confirm != MANUAL_CONFIRM_TOKEN:
        abort_conditions.append("manual_confirm_token_missing_or_invalid")
    if normalize_asset(mode_cfg.get("mode")) != "LIVE":
        abort_conditions.append("execution_mode_not_live")
    if not bool(mode_cfg.get("trading_enabled", False)):
        abort_conditions.append("execution_trading_disabled")
    if bool(policy_cfg.get("require_kill_switch_off", True)) and bool(mode_cfg.get("kill_switch", True)):
        abort_conditions.append("kill_switch_enabled")
    if not bool(policy_cfg.get("allow_live_orders", False)):
        abort_conditions.append("allow_live_orders=false")
    if bool(policy_cfg.get("manual_approval_required", False)):
        abort_conditions.append("manual_approval_required=true")
    if coin == "CASH":
        abort_conditions.append("cash_not_supported_for_canary")
    if coin not in allowed_assets:
        abort_conditions.append("coin_not_allowlisted")
    if market_entry is None:
        abort_conditions.append("coin_not_listed_in_hyperliquid_meta")
    if snapshot.get("open_orders_count", 0) > 0:
        abort_conditions.append("open_orders_present")
    if len(positions) > 0 and args.command == "run":
        abort_conditions.append("active_positions_present")
    if args.notional_usd < MIN_CANARY_NOTIONAL_USD and args.command == "run":
        abort_conditions.append(f"canary_notional_below_{MIN_CANARY_NOTIONAL_USD:.0f}_usd_minimum")

    max_notional = float(policy_cfg.get("max_order_notional_usd", 0.0))
    if max_notional <= 0:
        abort_conditions.append("max_order_notional_not_enabled")
    elif args.notional_usd > max_notional and args.command == "run":
        abort_conditions.append("canary_notional_exceeds_policy_max")

    if buy_slippage <= 0 or buy_slippage > 0.05:
        abort_conditions.append("slippage_out_of_bounds")

    if not auth_probe["signature_roundtrip_ok"]:
        abort_conditions.append("signing_roundtrip_failed")

    if account_setup["uses_agent_wallet"]:
        if agent_verification is None:
            abort_conditions.append("agent_wallet_verification_missing")
        else:
            if agent_verification["looks_like_agent_account"]:
                abort_conditions.append("account_address_looks_like_agent_wallet_not_main_account")
            if not agent_verification["signer_authorized"]:
                abort_conditions.append("signer_not_authorized_in_extra_agents")

    mid_price = None
    limit_price = None
    order_size = None
    sz_decimals = None
    preview_side = normalize_side(args.side)

    if market_entry is not None:
        sz_decimals = int(market_entry["sz_decimals"])
        try:
            mid_price = float(str(mids[coin]))
        except Exception:
            abort_conditions.append("missing_mid_price")
        if mid_price is not None:
            if args.command == "run":
                preview_side = normalize_side(args.side)
                limit_price = compute_limit_price(mid_price, preview_side == "buy", buy_slippage, sz_decimals)
                order_size = compute_order_size(args.notional_usd, limit_price, sz_decimals)
                if order_size * limit_price + POSITION_TOLERANCE < MIN_CANARY_NOTIONAL_USD:
                    abort_conditions.append("computed_order_notional_below_exchange_minimum")
            else:
                current_position_size = find_position_size(snapshot, coin)
                current_size = abs(current_position_size)
                if current_size <= POSITION_TOLERANCE:
                    abort_conditions.append("rollback_position_not_found")
                else:
                    preview_side = "sell" if current_position_size > 0 else "buy"
                    limit_price = compute_limit_price(mid_price, preview_side == "buy", buy_slippage, sz_decimals)
                    order_size = current_size

    order_preview = {
        "coin": coin,
        "side": preview_side,
        "notional_usd": args.notional_usd,
        "mid_price": mid_price,
        "limit_price": limit_price,
        "size": order_size,
        "slippage": buy_slippage,
        "expires_after_ms": int(args.expires_after_ms),
        "sz_decimals": sz_decimals,
    }

    preflight = {
        "artifact_type": "hyperliquid_live_canary_preflight",
        "generated_at_utc": utc_now_iso(),
        "command": args.command,
        "execute_live": bool(args.execute_live),
        "manual_confirm_token_ok": args.manual_confirm == MANUAL_CONFIRM_TOKEN,
        "account_address": account_setup["account_address"],
        "signer_address": account_setup["signer_address"],
        "uses_agent_wallet": account_setup["uses_agent_wallet"],
        "mode_config": mode_cfg,
        "live_order_policy": {
            "allow_live_orders": bool(policy_cfg.get("allow_live_orders", False)),
            "manual_approval_required": bool(policy_cfg.get("manual_approval_required", False)),
            "require_kill_switch_off": bool(policy_cfg.get("require_kill_switch_off", True)),
            "max_order_notional_usd": max_notional,
            "allowed_assets": sorted(allowed_assets),
        },
        "snapshot_summary": {
            "positions_count": snapshot.get("positions_count", 0),
            "open_orders_count": snapshot.get("open_orders_count", 0),
            "positions": snapshot.get("positions", []),
            "withdrawable": snapshot.get("withdrawable"),
            "margin_summary": snapshot.get("margin_summary", {}),
            "balance_source_of_truth": snapshot.get("balance_source_of_truth"),
            "account_equity_usd": snapshot.get("account_equity_usd"),
            "free_collateral_usd": snapshot.get("free_collateral_usd"),
            "available_balance_usd": snapshot.get("available_balance_usd"),
            "withdrawable_usd": snapshot.get("withdrawable_usd"),
            "margin_used_usd": snapshot.get("margin_used_usd"),
            "position_notional_usd": snapshot.get("position_notional_usd"),
            "account_abstraction": snapshot.get("account_abstraction"),
            "perp_account_value": snapshot.get("perp_account_value"),
            "perp_withdrawable": snapshot.get("perp_withdrawable"),
            "spot_balance_count": snapshot.get("spot_balance_count"),
            "spot_balance_symbols": snapshot.get("spot_balance_symbols", []),
            "spot_stable_total_usd": snapshot.get("spot_stable_total_usd"),
            "spot_stable_available_usd": snapshot.get("spot_stable_available_usd"),
            "spot_source_available": snapshot.get("spot_source_available"),
        },
        "auth_probe": auth_probe,
        "agent_verification": agent_verification,
        "order_preview": order_preview,
        "upstream_context": {
            "gate_status": None if gate_context is None else gate_context.get("status"),
            "gate_block_reasons": None if gate_context is None else gate_context.get("block_reasons"),
            "submit_preview_status": None if submit_context is None else submit_context.get("status"),
            "submit_block_reasons": None if submit_context is None else submit_context.get("submit_block_reasons"),
        },
        "abort_conditions_before_first_live_order": abort_conditions,
        "status": "ready" if not abort_conditions else "blocked",
        "notes": [
            "Manual canary only. This script never loops and never auto-repeats live orders.",
            "The primary canary command submits at most one live order.",
            "Rollback is a separate manual command and must be invoked explicitly if needed.",
            "expiresAfter is short-lived on every signed action to reduce stale-submit risk.",
        ],
    }
    return preflight, abort_conditions, order_preview


def build_order_request(
    market_map: dict[str, dict[str, Any]],
    coin: str,
    side: str,
    order_size: float,
    limit_price: float,
    reduce_only: bool,
    cloid: str | None = None,
) -> dict[str, Any]:
    market_entry = market_map[coin]
    order = {
        "coin": coin,
        "is_buy": side == "buy",
        "sz": order_size,
        "limit_px": limit_price,
        "order_type": {"limit": {"tif": "Ioc"}},
        "reduce_only": reduce_only,
        "cloid": cloid,
    }
    return {
        "order": order,
        "asset": int(market_entry["asset"]),
        "wire": order_request_to_wire(order, int(market_entry["asset"])),
    }


def submit_signed_action(
    crypto: CryptoDeps,
    account_setup: dict[str, Any],
    action: dict[str, Any],
    expires_after_ms: int,
) -> dict[str, Any]:
    nonce = int(time.time() * 1000) + int(os.environ.get("HYPERLIQUID_TIME_OFFSET_MS", "0"))
    expires_after = nonce + expires_after_ms if expires_after_ms > 0 else None
    signature = sign_l1_action(
        crypto=crypto,
        wallet=account_setup["wallet"],
        action=action,
        vault_address=account_setup["vault_address"],
        nonce=nonce,
        expires_after=expires_after,
        is_mainnet=True,
    )
    payload: dict[str, Any] = {
        "action": action,
        "nonce": nonce,
        "signature": signature,
    }
    if account_setup["vault_address"]:
        payload["vaultAddress"] = account_setup["vault_address"]
    if expires_after is not None:
        payload["expiresAfter"] = expires_after
    return {
        "nonce": nonce,
        "expires_after": expires_after,
        "signature": signature,
        "payload": payload,
        "response": exchange_request(payload),
    }


def poll_order_timeline(
    account_address: str,
    oid: int | None,
    timeout_seconds: float,
    interval_seconds: float,
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    if oid is None:
        return timeline

    deadline = time.time() + timeout_seconds
    while time.time() <= deadline:
        raw = fetch_order_status(account_address, oid)
        normalized = normalize_order_status(raw, oid)
        timeline.append(
            {
                "polled_at_utc": utc_now_iso(),
                "raw": raw,
                "normalized": normalized,
            }
        )
        if normalized["terminal"]:
            break
        time.sleep(interval_seconds)
    return timeline


def maybe_cancel_order(
    crypto: CryptoDeps,
    account_setup: dict[str, Any],
    market_map: dict[str, dict[str, Any]],
    coin: str,
    oid: int | None,
    expires_after_ms: int,
) -> dict[str, Any] | None:
    if oid is None:
        return None
    market_entry = market_map.get(coin)
    if market_entry is None:
        return None
    cancel_action = {
        "type": "cancel",
        "cancels": [{"a": int(market_entry["asset"]), "o": oid}],
    }
    return submit_signed_action(
        crypto=crypto,
        account_setup=account_setup,
        action=cancel_action,
        expires_after_ms=expires_after_ms,
    )


def build_reconciliation(
    args: argparse.Namespace,
    preflight: dict[str, Any],
    submit_result: dict[str, Any] | None,
    submit_normalized: dict[str, Any] | None,
    timeline: list[dict[str, Any]],
    fills_summary: dict[str, Any],
    pre_snapshot: dict[str, Any],
    post_snapshot: dict[str, Any],
    rollback_command: str | None,
) -> dict[str, Any]:
    coin = normalize_asset(args.coin)
    pre_size = find_position_size(pre_snapshot, coin)
    post_size = find_position_size(post_snapshot, coin)
    filled_size = float(fills_summary.get("filled_size", 0.0))
    side = normalize_side(args.side)
    expected_delta = 0.0
    if args.command == "run":
        expected_delta = filled_size if side == "buy" else -filled_size
    elif args.command == "rollback":
        expected_delta = post_size - pre_size

    last_timeline = timeline[-1]["normalized"] if timeline else None
    final_order_status = (
        last_timeline["status"] if last_timeline else
        (submit_normalized["submit_state"] if submit_normalized else "unknown")
    )
    open_orders_cleared = post_snapshot.get("open_orders_count", 0) == 0
    actual_delta = post_size - pre_size
    exchange_acknowledged = bool(
        submit_normalized
        and submit_normalized.get("acknowledged")
        and not submit_normalized.get("needs_manual_review")
    )
    needs_manual_review = bool(submit_normalized and submit_normalized.get("needs_manual_review"))

    if args.command == "run":
        position_delta_matches = abs(actual_delta - expected_delta) <= 1e-6
        rollback_required = abs(post_size) > POSITION_TOLERANCE
    else:
        position_delta_matches = abs(post_size) <= 1e-6
        rollback_required = abs(post_size) > POSITION_TOLERANCE

    final_state_reconciled = bool(
        submit_normalized
        and exchange_acknowledged
        and open_orders_cleared
        and not needs_manual_review
        and (
            final_order_status in TERMINAL_ORDER_STATES
            or final_order_status in {"filled", "resting"}
        )
        and position_delta_matches
    )

    reconciliation = {
        "artifact_type": "hyperliquid_live_canary_reconciliation",
        "generated_at_utc": utc_now_iso(),
        "command": args.command,
        "coin": coin,
        "submit_acknowledged": exchange_acknowledged,
        "order_submitted": submit_result is not None,
        "exchange_acknowledged": exchange_acknowledged,
        "final_order_status": final_order_status,
        "final_order_terminal": final_order_status in TERMINAL_ORDER_STATES,
        "pre_position_size": pre_size,
        "post_position_size": post_size,
        "position_delta": actual_delta,
        "filled_size": filled_size,
        "fills_count": fills_summary.get("fills_count", 0),
        "average_fill_px": fills_summary.get("average_px"),
        "open_orders_cleared": open_orders_cleared,
        "position_delta_matches_expected": position_delta_matches,
        "final_state_reconciled": final_state_reconciled,
        "needs_manual_review": needs_manual_review,
        "submit_normalization_ok": bool(submit_normalized and submit_normalized.get("normalization_ok")),
        "submit_normalization_error": None if not submit_normalized else submit_normalized.get("error"),
        "rollback_required": rollback_required,
        "rollback_command": rollback_command,
        "evidence": {
            "order_submitted": submit_result is not None,
            "exchange_acknowledged": exchange_acknowledged,
            "final_state_reconciled": final_state_reconciled,
        },
        "notes": [
            "Reconciliation here refers to exchange lifecycle evidence for the canary order and resulting position delta.",
            "A filled canary may still require manual rollback if post_position_size is non-zero after the primary run.",
            "Rollback is intentionally a separate manual action to avoid automatic repeated live orders.",
        ],
        "preflight_abort_conditions": preflight.get("abort_conditions_before_first_live_order", []),
    }
    return reconciliation


def build_rollback_plan(args: argparse.Namespace, reconciliation: dict[str, Any]) -> dict[str, Any]:
    if args.command == "rollback":
        instructions = [
            "If rollback still leaves exposure, re-enable kill switch immediately and inspect the latest canary artifacts before any further manual action.",
            "Do not launch another canary run until positions_count == 0 and open_orders_count == 0 in a fresh post-activity snapshot.",
        ]
    else:
        instructions = [
            "If the primary canary fills and leaves non-zero exposure, do not rerun canary.",
            "Flip kill switch back on unless you are immediately executing the rollback command.",
            "Run the exact rollback command below as a separate manual invocation.",
        ]

    return {
        "artifact_type": "hyperliquid_live_canary_rollback_plan",
        "generated_at_utc": utc_now_iso(),
        "command": args.command,
        "rollback_required": bool(reconciliation.get("rollback_required")),
        "rollback_command": reconciliation.get("rollback_command"),
        "instructions": instructions,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual Hyperliquid live canary flow with strict preflight, submit, polling, and reconciliation artifacts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Submit exactly one minimal live canary order.")
    rollback_parser = subparsers.add_parser("rollback", help="Submit exactly one manual rollback close order.")

    for subparser in (run_parser, rollback_parser):
        subparser.add_argument("--coin", required=True, help="Hyperliquid perp coin, e.g. BTC or ETH.")
        subparser.add_argument("--manual-confirm", required=True, help=f"Must equal {MANUAL_CONFIRM_TOKEN}.")
        subparser.add_argument("--execute-live", action="store_true", help="Actually submit the live signed action.")
        subparser.add_argument("--side", default="buy", choices=["buy", "sell"], help="Primary canary side.")
        subparser.add_argument("--slippage", type=float, default=DEFAULT_SLIPPAGE, help="Aggressive IOC slippage as a decimal.")
        subparser.add_argument("--expires-after-ms", type=int, default=DEFAULT_EXPIRES_AFTER_MS, help="Short action expiry window in milliseconds.")
        subparser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS, help="Total order-status polling time.")
        subparser.add_argument("--poll-interval-seconds", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS, help="Polling cadence in seconds.")

    run_parser.add_argument("--notional-usd", type=float, default=MIN_CANARY_NOTIONAL_USD, help="Primary canary notional in USD.")
    rollback_parser.set_defaults(notional_usd=0.0)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coin = normalize_asset(args.coin)
    run_id, run_dir = create_run_dir(args.command, coin)
    artifact_paths = build_artifact_paths(run_dir)

    log(f"[START] hyperliquid_live_canary command={args.command} coin={coin} run_id={run_id}")

    crypto = require_crypto_deps()
    account_cfg = read_json(ACCOUNT_CONFIG_PATH)
    mode_cfg = read_json(MODE_CONFIG_PATH)
    policy_cfg = read_json(LIVE_ORDER_POLICY_PATH)
    gate_context = load_optional_json(GATE_PATH)
    submit_context = load_optional_json(SUBMIT_PREVIEW_PATH)

    account_setup = get_account_setup(account_cfg, crypto)
    auth_probe_nonce = int(time.time() * 1000) + int(os.environ.get("HYPERLIQUID_TIME_OFFSET_MS", "0"))
    auth_probe_action = {"type": "noop"}
    auth_probe_signature = sign_l1_action(
        crypto=crypto,
        wallet=account_setup["wallet"],
        action=auth_probe_action,
        vault_address=account_setup["vault_address"],
        nonce=auth_probe_nonce,
        expires_after=auth_probe_nonce + args.expires_after_ms,
        is_mainnet=True,
    )
    auth_probe_recovered = recover_agent_or_user_from_l1_action(
        crypto=crypto,
        action=auth_probe_action,
        signature=auth_probe_signature,
        vault_address=account_setup["vault_address"],
        nonce=auth_probe_nonce,
        expires_after=auth_probe_nonce + args.expires_after_ms,
        is_mainnet=True,
    )
    auth_probe = {
        "signer_address": account_setup["signer_address"],
        "recovered_address": auth_probe_recovered,
        "signature_roundtrip_ok": auth_probe_recovered.lower() == account_setup["signer_address"].lower(),
    }

    agent_verification = None
    if account_setup["uses_agent_wallet"]:
        agent_verification = verify_agent_authorization(
            account_address=account_setup["account_address"],
            signer_address=account_setup["signer_address"],
        )

    meta = fetch_meta()
    market_map = build_market_map(meta)
    mids = fetch_all_mids()
    pre_state = fetch_user_state(account_setup["account_address"])
    pre_spot_state = fetch_spot_user_state(account_setup["account_address"])
    pre_open_orders = fetch_open_orders(account_setup["account_address"])
    account_abstraction = fetch_user_abstraction(account_setup["account_address"])
    pre_snapshot = summarize_snapshot(
        account_setup["account_address"],
        pre_state,
        pre_spot_state,
        pre_open_orders,
        account_abstraction,
    )

    preflight, abort_conditions, order_preview = build_preflight(
        args=args,
        account_setup=account_setup,
        market_map=market_map,
        mids=mids,
        snapshot=pre_snapshot,
        mode_cfg=mode_cfg,
        policy_cfg=policy_cfg,
        gate_context=gate_context,
        submit_context=submit_context,
        auth_probe=auth_probe,
        agent_verification=agent_verification,
    )
    write_json(artifact_paths["preflight"], preflight)

    if not args.execute_live:
        rollback_plan = {
            "artifact_type": "hyperliquid_live_canary_rollback_plan",
            "generated_at_utc": utc_now_iso(),
            "command": args.command,
            "rollback_required": False,
            "rollback_command": None,
            "instructions": [
                "Preview-only run. No live order was submitted.",
                "If you want the live canary, rerun with --execute-live and the exact manual confirm token.",
            ],
        }
        write_json(artifact_paths["rollback_plan"], rollback_plan)
        manifest = {
            "artifact_name": "hyperliquid_live_canary",
            "generated_at_utc": utc_now_iso(),
            "run_id": run_id,
            "command": args.command,
            "status": "preview_only",
            "output_paths": {key: str(path.resolve()) for key, path in artifact_paths.items()},
            "notes": ["No live order submitted because --execute-live was not set."],
        }
        write_json(artifact_paths["manifest"], manifest)
        log("[END] hyperliquid_live_canary preview_only")
        return

    if abort_conditions:
        rollback_plan = {
            "artifact_type": "hyperliquid_live_canary_rollback_plan",
            "generated_at_utc": utc_now_iso(),
            "command": args.command,
            "rollback_required": False,
            "rollback_command": None,
            "instructions": [
                "No live order was sent because preflight blocked before first submit.",
                "Resolve the recorded abort conditions before rerunning the manual canary.",
            ],
        }
        write_json(artifact_paths["rollback_plan"], rollback_plan)
        manifest = {
            "artifact_name": "hyperliquid_live_canary",
            "generated_at_utc": utc_now_iso(),
            "run_id": run_id,
            "command": args.command,
            "status": "blocked_before_first_live_order",
            "output_paths": {key: str(path.resolve()) for key, path in artifact_paths.items()},
            "notes": ["No live order submitted."],
        }
        write_json(artifact_paths["manifest"], manifest)
        fail("Canary preflight blocked before first live order")

    ensure_manual_execution(args.manual_confirm)

    if order_preview["size"] is None or order_preview["limit_price"] is None:
        fail("Order preview incomplete after preflight")

    effective_side = normalize_side(args.side)
    reduce_only = args.command == "rollback"
    if args.command == "rollback":
        current_size = find_position_size(pre_snapshot, coin)
        effective_side = "sell" if current_size > 0 else "buy"

    order_bundle = build_order_request(
        market_map=market_map,
        coin=coin,
        side=effective_side,
        order_size=float(order_preview["size"]),
        limit_price=float(order_preview["limit_price"]),
        reduce_only=reduce_only,
    )
    action = make_action(order_bundle["wire"])

    submit_result = submit_signed_action(
        crypto=crypto,
        account_setup=account_setup,
        action=action,
        expires_after_ms=int(args.expires_after_ms),
    )
    submit_artifact = {
        "artifact_type": "hyperliquid_live_canary_submit_response",
        "generated_at_utc": utc_now_iso(),
        "command": args.command,
        "coin": coin,
        "side": effective_side,
        "reduce_only": reduce_only,
        "nonce": submit_result["nonce"],
        "expires_after": submit_result["expires_after"],
        "action": action,
        "payload_without_signature": {
            "action": submit_result["payload"]["action"],
            "nonce": submit_result["payload"]["nonce"],
            "vaultAddress": submit_result["payload"].get("vaultAddress"),
            "expiresAfter": submit_result["payload"].get("expiresAfter"),
        },
        "submit_normalized": None,
        "raw_exchange_response": submit_result["response"],
        "raw_exchange_response_type": type(submit_result["response"]).__name__,
    }
    write_json(artifact_paths["submit_response"], submit_artifact)

    try:
        submit_normalized = normalize_submit_response(submit_result["response"])
    except Exception as exc:
        submit_normalized = build_submit_normalization_fallback(
            submit_result["response"],
            f"normalize_submit_response_exception:{type(exc).__name__}:{exc}",
        )
    submit_artifact["submit_normalized"] = submit_normalized
    write_json(artifact_paths["submit_response"], submit_artifact)

    oid = submit_normalized.get("oid")
    timeline = poll_order_timeline(
        account_address=account_setup["account_address"],
        oid=oid,
        timeout_seconds=float(args.poll_seconds),
        interval_seconds=float(args.poll_interval_seconds),
    )

    latest_status = timeline[-1]["normalized"] if timeline else None
    if latest_status and not latest_status["terminal"] and oid is not None:
        cancel_result = maybe_cancel_order(
            crypto=crypto,
            account_setup=account_setup,
            market_map=market_map,
            coin=coin,
            oid=oid,
            expires_after_ms=int(args.expires_after_ms),
        )
        if cancel_result is not None:
            timeline.append(
                {
                    "polled_at_utc": utc_now_iso(),
                    "raw": {
                        "cancel_response": cancel_result["response"],
                        "cancel_nonce": cancel_result["nonce"],
                        "cancel_expires_after": cancel_result["expires_after"],
                    },
                    "normalized": {
                        "oid": oid,
                        "status": "cancel_submitted",
                        "terminal": False,
                        "order_present": True,
                    },
                }
            )
            timeline.extend(
                poll_order_timeline(
                    account_address=account_setup["account_address"],
                    oid=oid,
                    timeout_seconds=float(args.poll_seconds),
                    interval_seconds=float(args.poll_interval_seconds),
                )
            )

    fills = fetch_user_fills_by_time(
        account_address=account_setup["account_address"],
        start_time_ms=max(0, submit_result["nonce"] - 2_000),
        end_time_ms=int(time.time() * 1000),
    )
    matched_fills = filter_fills_for_oid(fills, oid)
    fills_summary = summarize_fills(matched_fills)

    post_state = fetch_user_state(account_setup["account_address"])
    post_spot_state = fetch_spot_user_state(account_setup["account_address"])
    post_open_orders = fetch_open_orders(account_setup["account_address"])
    post_snapshot = summarize_snapshot(
        account_setup["account_address"],
        post_state,
        post_spot_state,
        post_open_orders,
        account_abstraction,
    )
    write_json(artifact_paths["order_timeline"], timeline)
    write_json(artifact_paths["post_snapshot"], post_snapshot)

    rollback_command = None
    if args.command == "run" and abs(find_position_size(post_snapshot, coin)) > POSITION_TOLERANCE:
        rollback_command = (
            f".\\.venv\\Scripts\\python.exe scripts/execution/hyperliquid_live_canary.py rollback "
            f"--coin {coin} --manual-confirm {MANUAL_CONFIRM_TOKEN} --execute-live"
        )

    reconciliation = build_reconciliation(
        args=args,
        preflight=preflight,
        submit_result=submit_result,
        submit_normalized=submit_normalized,
        timeline=timeline,
        fills_summary=fills_summary,
        pre_snapshot=pre_snapshot,
        post_snapshot=post_snapshot,
        rollback_command=rollback_command,
    )
    rollback_plan = build_rollback_plan(args, reconciliation)
    write_json(artifact_paths["reconciliation"], reconciliation)
    write_json(artifact_paths["rollback_plan"], rollback_plan)

    manifest = {
        "artifact_name": "hyperliquid_live_canary",
        "generated_at_utc": utc_now_iso(),
        "run_id": run_id,
        "command": args.command,
        "coin": coin,
        "status": (
            "success_with_rollback_required"
            if reconciliation["rollback_required"]
            else "success"
        ),
        "input_paths": {
            "account_config_path": str(ACCOUNT_CONFIG_PATH.resolve()),
            "execution_mode_path": str(MODE_CONFIG_PATH.resolve()),
            "live_order_policy_path": str(LIVE_ORDER_POLICY_PATH.resolve()),
            "gate_path": str(GATE_PATH.resolve()) if GATE_PATH.exists() else None,
            "submit_preview_path": str(SUBMIT_PREVIEW_PATH.resolve()) if SUBMIT_PREVIEW_PATH.exists() else None,
        },
        "output_paths": {key: str(path.resolve()) for key, path in artifact_paths.items()},
        "evidence": reconciliation["evidence"],
    }
    write_json(artifact_paths["manifest"], manifest)

    log(
        "[END] hyperliquid_live_canary "
        f"run_id={run_id} final_order_status={reconciliation['final_order_status']} "
        f"rollback_required={reconciliation['rollback_required']}"
    )


if __name__ == "__main__":
    main()
