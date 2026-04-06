from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution.hyperliquid_live_canary import (  # noqa: E402
    DEFAULT_EXPIRES_AFTER_MS,
    DEFAULT_SLIPPAGE,
    POSITION_TOLERANCE,
    build_market_map,
    build_order_request,
    compute_limit_price,
    compute_order_size,
    fetch_all_mids,
    fetch_meta,
    fetch_open_orders,
    fetch_spot_user_state,
    fetch_user_fills_by_time,
    fetch_user_state,
    filter_fills_for_oid,
    get_account_setup,
    normalize_submit_response,
    recover_agent_or_user_from_l1_action,
    require_crypto_deps,
    sign_l1_action,
    submit_signed_action,
    summarize_fills,
    summarize_snapshot,
    verify_agent_authorization,
)


EXECUTION_DIR = ROOT / "execution"
CONFIG_DIR = EXECUTION_DIR / "config"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
APP_EXPORTS_DIR = OUTPUTS_DIR / "app_exports"

ACCOUNT_CONFIG_PATH = CONFIG_DIR / "hyperliquid_account.json"
MODE_CONFIG_PATH = CONFIG_DIR / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = CONFIG_DIR / "live_order_policy.json"

DEFAULT_INTENT_PATH = OUTPUTS_DIR / "intents" / "latest_execution_intent.json"
DEFAULT_GATE_PATH = OUTPUTS_DIR / "live_gate" / "latest_real_order_gate_decision.json"
DEFAULT_RECON_PATH = OUTPUTS_DIR / "reconciliation" / "latest_reconciliation_report.json"
DEFAULT_SNAPSHOT_PATH = OUTPUTS_DIR / "read_only" / "hyperliquid_account_snapshot.json"

SUBMIT_DIR = OUTPUTS_DIR / "submit_preview"
LOGS_DIR = OUTPUTS_DIR / "logs"

DECISION_PATH = SUBMIT_DIR / "latest_submit_preview_decision.json"
QUALITY_PATH = SUBMIT_DIR / "latest_submit_preview_quality.json"
MANIFEST_PATH = SUBMIT_DIR / "latest_submit_preview_manifest.json"
REQUEST_PAYLOAD_PATH = SUBMIT_DIR / "latest_submit_request_payload.json"
EXCHANGE_RESPONSE_PATH = SUBMIT_DIR / "latest_submit_exchange_response.json"
LEVERAGE_RESPONSE_PATH = SUBMIT_DIR / "latest_submit_leverage_action_response.json"
PRE_SNAPSHOT_PATH = SUBMIT_DIR / "latest_submit_pre_snapshot.json"
POST_SNAPSHOT_PATH = SUBMIT_DIR / "latest_submit_post_snapshot.json"
POST_RECON_PATH = SUBMIT_DIR / "latest_post_submit_reconciliation.json"
LOG_PATH = LOGS_DIR / "submit_controlled_real_order.log"

MANUAL_CONFIRM_TOKEN = "CONTROLLED_REAL_ORDER"
DEFAULT_EXCHANGE_MARGIN_MODE = "cross"


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        fail(f"Missing required CSV: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            rows = list(reader)
            return header, rows
    except Exception as exc:
        fail(f"Failed reading CSV {path}: {exc}")
    raise RuntimeError("unreachable")


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_margin_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"cross", "isolated"}:
        return mode
    return DEFAULT_EXCHANGE_MARGIN_MODE


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(str(value))
    except Exception:
        return None


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(str(value))
    except Exception:
        return None
    if abs(parsed - round(parsed)) > 1e-9:
        return None
    return int(round(parsed))


def first_nonempty(mapping: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        text = str(mapping.get(key, "")).strip()
        if text:
            return text
    return None


def ensure_manual_execution(args: argparse.Namespace) -> None:
    if not args.execute_live:
        return
    if args.manual_confirm != MANUAL_CONFIRM_TOKEN:
        fail(
            "Manual confirmation missing. "
            f"Pass --manual-confirm {MANUAL_CONFIRM_TOKEN} together with --execute-live."
        )


def build_source_paths(args: argparse.Namespace) -> dict[str, str]:
    return {
        "mode_config_path": str(MODE_CONFIG_PATH.resolve()),
        "live_order_policy_path": str(LIVE_ORDER_POLICY_PATH.resolve()),
        "account_config_path": str(ACCOUNT_CONFIG_PATH.resolve()),
        "intent_path": str(args.intent_path.resolve()),
        "gate_path": str(args.gate_path.resolve()),
        "reconciliation_path": str(args.reconciliation_path.resolve()),
        "snapshot_override_path": (
            str(args.snapshot_path.resolve()) if args.snapshot_path is not None else None
        ),
    }


def extract_snapshot_positions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    positions = snapshot.get("positions", [])
    if isinstance(positions, list) and positions:
        return positions

    raw = snapshot.get("raw", {}) if isinstance(snapshot.get("raw"), dict) else {}
    clearinghouse = raw.get("clearinghouseState", {}) if isinstance(raw.get("clearinghouseState"), dict) else {}
    asset_positions = clearinghouse.get("assetPositions", [])
    if not isinstance(asset_positions, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in asset_positions:
        if not isinstance(item, dict):
            continue
        position = item.get("position") if isinstance(item.get("position"), dict) else item
        coin = normalize_asset(position.get("coin") if isinstance(position, dict) else item.get("coin"))
        size = to_float(position.get("szi") if isinstance(position, dict) else item.get("szi"))
        if not coin or size is None:
            continue
        normalized.append(
            {
                "coin": coin,
                "size": size,
                "raw": item,
            }
        )
    return normalized


def extract_snapshot_open_orders_count(snapshot: dict[str, Any]) -> int:
    raw_value = snapshot.get("open_orders_count")
    parsed = to_int(raw_value)
    if parsed is not None:
        return parsed

    summary = snapshot.get("summary", {})
    if isinstance(summary, dict):
        parsed = to_int(summary.get("open_orders_count"))
        if parsed is not None:
            return parsed

    raw = snapshot.get("raw", {}) if isinstance(snapshot.get("raw"), dict) else {}
    open_orders = raw.get("openOrders", [])
    if isinstance(open_orders, list):
        return len(open_orders)
    return 0


def derive_current_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    positions = extract_snapshot_positions(snapshot)

    active = [
        position
        for position in positions
        if abs(float(position.get("size", 0.0))) > POSITION_TOLERANCE
    ]
    if not active:
        return {
            "normalized_state": "CASH",
            "active_positions_count": 0,
            "active_asset": "CASH",
            "multi_position": False,
            "active_positions": [],
        }

    unique_assets = sorted(
        {
            normalize_asset(position.get("coin"))
            for position in active
            if normalize_asset(position.get("coin"))
        }
    )
    if len(unique_assets) == 1:
        return {
            "normalized_state": unique_assets[0],
            "active_positions_count": len(active),
            "active_asset": unique_assets[0],
            "multi_position": len(active) > 1,
            "active_positions": active,
        }

    return {
        "normalized_state": "MULTI_ASSET",
        "active_positions_count": len(active),
        "active_asset": "MULTI_ASSET",
        "multi_position": True,
        "active_positions": active,
    }


def extract_position(snapshot: dict[str, Any], coin: str) -> dict[str, Any] | None:
    for position in extract_snapshot_positions(snapshot):
        if normalize_asset(position.get("coin")) == coin:
            return position
    return None


def extract_current_leverage(position: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(position, dict):
        return {
            "value": None,
            "margin_mode": None,
            "is_cross": None,
            "source": "no_position",
        }

    raw = position.get("raw", {}) if isinstance(position.get("raw"), dict) else {}
    payload = raw.get("position") if isinstance(raw.get("position"), dict) else raw
    leverage = payload.get("leverage") if isinstance(payload, dict) else None
    if not isinstance(leverage, dict):
        return {
            "value": None,
            "margin_mode": None,
            "is_cross": None,
            "source": "position_missing_leverage",
        }

    margin_mode = normalize_margin_mode(leverage.get("type"))
    return {
        "value": to_float(leverage.get("value")),
        "margin_mode": margin_mode,
        "is_cross": margin_mode == "cross",
        "source": "position.leverage",
        "raw": leverage,
    }


def compute_total_trading_equity_usd(snapshot: dict[str, Any]) -> float | None:
    summary = snapshot
    if isinstance(snapshot.get("summary"), dict):
        summary = snapshot["summary"]

    spot_total = to_float(summary.get("spot_stable_total_usd"))
    perp_account_value = to_float(summary.get("perp_account_value"))
    account_equity = to_float(summary.get("account_equity_usd"))

    parts = [value for value in (spot_total, perp_account_value) if value is not None]
    if parts:
        return float(sum(parts))
    return account_equity


def resolve_live_status_row(intent: dict[str, Any]) -> tuple[Path, dict[str, str]]:
    source_paths = intent.get("source_paths", {})
    live_status_raw = None
    if isinstance(source_paths, dict):
        live_status_raw = source_paths.get("phase67j_live_status")
    if isinstance(live_status_raw, str) and live_status_raw.strip():
        live_status_path = Path(live_status_raw)
    else:
        live_status_path = APP_EXPORTS_DIR / "phase67j_live_status.csv"

    _, rows = read_csv_rows(live_status_path)
    if not rows:
        fail(f"No rows found in {live_status_path}")
    return live_status_path, rows[-1]


def resolve_leverage_context(intent: dict[str, Any], target_asset: str) -> dict[str, Any]:
    if target_asset == "CASH":
        return {
            "needed": False,
            "resolved": True,
            "strategy_target_leverage": None,
            "strategy_leverage_source_field": None,
            "exchange_leverage_target": None,
            "exchange_leverage_source_field": None,
            "exchange_margin_mode": None,
            "exchange_margin_mode_source_field": None,
            "exchange_leverage_blocker": None,
            "live_status_path": None,
            "paper_path": None,
            "paper_row": None,
            "leverage_mode": None,
            "notes": ["CASH intent does not require leverage resolution."],
        }

    live_status_path, live_status_row = resolve_live_status_row(intent)
    leverage_mode = first_nonempty(
        live_status_row,
        ["leverage_mode", "execution_profile"],
    )

    deployment_label = first_nonempty(
        live_status_row,
        ["deployment_candidate_label", "live_truth_mode"],
    )
    if not deployment_label:
        return {
            "needed": True,
            "resolved": False,
            "exchange_leverage_blocker": (
                f"missing_deployment_candidate_label::{live_status_path}"
            ),
            "live_status_path": str(live_status_path.resolve()),
            "leverage_mode": leverage_mode,
            "notes": ["Live status row is missing deployment_candidate_label/live_truth_mode."],
        }

    paper_path = APP_EXPORTS_DIR / f"{deployment_label}.csv"
    if not paper_path.exists():
        paper_path = APP_EXPORTS_DIR / f"{deployment_label}_paper.csv"
    if not paper_path.exists():
        return {
            "needed": True,
            "resolved": False,
            "exchange_leverage_blocker": (
                f"missing_leverage_paper::{deployment_label}::{paper_path}"
            ),
            "live_status_path": str(live_status_path.resolve()),
            "paper_path": str(paper_path.resolve()),
            "leverage_mode": leverage_mode,
            "notes": ["Could not find deployment candidate paper export."],
        }

    as_of_source = str(intent.get("as_of_source", "")).strip()
    if not as_of_source:
        return {
            "needed": True,
            "resolved": False,
            "exchange_leverage_blocker": "missing_intent_as_of_source",
            "live_status_path": str(live_status_path.resolve()),
            "paper_path": str(paper_path.resolve()),
            "leverage_mode": leverage_mode,
            "notes": ["Intent is missing as_of_source required for leverage row resolution."],
        }

    _, rows = read_csv_rows(paper_path)
    matching_rows = [row for row in rows if str(row.get("date", "")).strip() == as_of_source]
    if not matching_rows:
        return {
            "needed": True,
            "resolved": False,
            "exchange_leverage_blocker": (
                f"missing_leverage_row_for_as_of_source::{paper_path}::{as_of_source}"
            ),
            "live_status_path": str(live_status_path.resolve()),
            "paper_path": str(paper_path.resolve()),
            "leverage_mode": leverage_mode,
            "notes": ["No leverage paper row matched intent.as_of_source."],
        }

    paper_row = matching_rows[-1]
    asset_fields = [
        "tradable_governed_asset",
        "overlay_candidate_clean",
        "overlay_candidate_raw",
        "portfolio_held_asset",
    ]
    explicit_assets: dict[str, str] = {}
    for field in asset_fields:
        candidate = normalize_asset(paper_row.get(field))
        if candidate and candidate != "BASELINE_RISK":
            explicit_assets[field] = candidate

    if not explicit_assets:
        return {
            "needed": True,
            "resolved": False,
            "exchange_leverage_blocker": (
                f"missing_explicit_target_asset_mapping::{paper_path}::{as_of_source}"
            ),
            "live_status_path": str(live_status_path.resolve()),
            "paper_path": str(paper_path.resolve()),
            "paper_row": paper_row,
            "leverage_mode": leverage_mode,
            "notes": ["Leverage paper row did not contain an explicit non-baseline target asset field."],
        }

    if target_asset not in set(explicit_assets.values()):
        return {
            "needed": True,
            "resolved": False,
            "exchange_leverage_blocker": (
                f"leverage_row_asset_mismatch::{paper_path}::{as_of_source}::{target_asset}"
            ),
            "live_status_path": str(live_status_path.resolve()),
            "paper_path": str(paper_path.resolve()),
            "paper_row": paper_row,
            "explicit_assets": explicit_assets,
            "leverage_mode": leverage_mode,
            "notes": ["Leverage paper row asset mapping does not match intent.target_asset."],
        }

    strategy_target_leverage = None
    strategy_leverage_source_field = None
    for field in ("target_leverage", "effective_leverage"):
        parsed = to_float(paper_row.get(field))
        if parsed is not None:
            strategy_target_leverage = parsed
            strategy_leverage_source_field = field
            break

    if strategy_target_leverage is None or strategy_target_leverage <= 0:
        return {
            "needed": True,
            "resolved": False,
            "exchange_leverage_blocker": (
                f"missing_strategy_leverage_target::{paper_path}::{as_of_source}::target_leverage/effective_leverage"
            ),
            "live_status_path": str(live_status_path.resolve()),
            "paper_path": str(paper_path.resolve()),
            "paper_row": paper_row,
            "explicit_assets": explicit_assets,
            "leverage_mode": leverage_mode,
            "notes": ["Strategy leverage target is missing from leverage paper row."],
        }

    exchange_leverage_target = None
    exchange_leverage_source_field = None
    exchange_margin_mode = None
    exchange_margin_mode_source_field = None

    explicit_candidates: list[tuple[str, Any]] = []
    for field in (
        "exchange_leverage",
        "target_exchange_leverage",
        "hyperliquid_exchange_leverage",
    ):
        explicit_candidates.append((f"intent.{field}", intent.get(field)))
        explicit_candidates.append((f"paper_row.{field}", paper_row.get(field)))

    for field, value in explicit_candidates:
        parsed = to_int(value)
        if parsed is not None and parsed > 0:
            exchange_leverage_target = parsed
            exchange_leverage_source_field = field
            break

    margin_mode_candidates: list[tuple[str, Any]] = [
        ("intent.exchange_margin_mode", intent.get("exchange_margin_mode")),
        ("intent.hyperliquid_margin_mode", intent.get("hyperliquid_margin_mode")),
        ("paper_row.exchange_margin_mode", paper_row.get("exchange_margin_mode")),
        ("paper_row.hyperliquid_margin_mode", paper_row.get("hyperliquid_margin_mode")),
    ]
    for field, value in margin_mode_candidates:
        normalized = str(value or "").strip().lower()
        if normalized in {"cross", "isolated"}:
            exchange_margin_mode = normalized
            exchange_margin_mode_source_field = field
            break

    notes = [
        "Strategy exposure sizing uses target_leverage if present, otherwise effective_leverage.",
        "Live exchange leverage update requires an explicit integer exchange leverage target compatible with Hyperliquid updateLeverage.",
    ]

    exchange_leverage_blocker = None
    if exchange_leverage_target is None:
        exchange_leverage_blocker = (
            "missing_exchange_leverage_target::"
            f"intent[target_exchange_leverage|exchange_leverage|hyperliquid_exchange_leverage]::"
            f"{paper_path}[target_exchange_leverage|exchange_leverage|hyperliquid_exchange_leverage]"
        )

    return {
        "needed": True,
        "resolved": True,
        "strategy_target_leverage": strategy_target_leverage,
        "strategy_leverage_source_field": strategy_leverage_source_field,
        "exchange_leverage_target": exchange_leverage_target,
        "exchange_leverage_source_field": exchange_leverage_source_field,
        "exchange_margin_mode": exchange_margin_mode,
        "exchange_margin_mode_source_field": exchange_margin_mode_source_field,
        "exchange_leverage_blocker": exchange_leverage_blocker,
        "live_status_path": str(live_status_path.resolve()),
        "paper_path": str(paper_path.resolve()),
        "paper_row": paper_row,
        "explicit_assets": explicit_assets,
        "leverage_mode": leverage_mode,
        "notes": notes,
    }


def build_auth_context(account_cfg: dict[str, Any]) -> dict[str, Any]:
    crypto = require_crypto_deps()
    account_setup = get_account_setup(account_cfg, crypto)
    auth_nonce = int(time.time() * 1000) + int(os.environ.get("HYPERLIQUID_TIME_OFFSET_MS", "0"))
    expires_after = auth_nonce + DEFAULT_EXPIRES_AFTER_MS
    auth_action = {"type": "noop"}
    signature = sign_l1_action(
        crypto=crypto,
        wallet=account_setup["wallet"],
        action=auth_action,
        vault_address=account_setup["vault_address"],
        nonce=auth_nonce,
        expires_after=expires_after,
        is_mainnet=True,
    )
    recovered = recover_agent_or_user_from_l1_action(
        crypto=crypto,
        action=auth_action,
        signature=signature,
        vault_address=account_setup["vault_address"],
        nonce=auth_nonce,
        expires_after=expires_after,
        is_mainnet=True,
    )
    auth_probe = {
        "signer_address": account_setup["signer_address"],
        "account_address": account_setup["account_address"],
        "recovered_address": recovered,
        "signature_roundtrip_ok": recovered.lower() == account_setup["signer_address"].lower(),
        "uses_agent_wallet": account_setup["uses_agent_wallet"],
    }

    agent_verification = None
    if account_setup["uses_agent_wallet"]:
        agent_verification = verify_agent_authorization(
            account_address=account_setup["account_address"],
            signer_address=account_setup["signer_address"],
        )

    return {
        "crypto": crypto,
        "account_setup": account_setup,
        "auth_probe": auth_probe,
        "agent_verification": agent_verification,
    }


def load_snapshot_for_planning(
    args: argparse.Namespace,
    account_address: str,
) -> dict[str, Any]:
    if not args.execute_live:
        snapshot_path = args.snapshot_path or DEFAULT_SNAPSHOT_PATH
        return read_json(snapshot_path)

    state = fetch_user_state(account_address)
    spot_state = fetch_spot_user_state(account_address)
    open_orders = fetch_open_orders(account_address)
    return summarize_snapshot(account_address, state, spot_state, open_orders)


def refresh_live_snapshot(account_address: str) -> dict[str, Any]:
    state = fetch_user_state(account_address)
    spot_state = fetch_spot_user_state(account_address)
    open_orders = fetch_open_orders(account_address)
    return summarize_snapshot(account_address, state, spot_state, open_orders)


def build_order_step(
    *,
    coin: str,
    side: str,
    order_size: float,
    reduce_only: bool,
    market_map: dict[str, dict[str, Any]],
    mids: dict[str, Any],
    slippage: float,
    reason: str,
    desired_notional_usd: float | None = None,
) -> dict[str, Any]:
    mid_price = to_float(mids.get(coin))
    if mid_price is None or mid_price <= 0:
        fail(f"Missing valid mid price for {coin}")

    market_entry = market_map.get(coin)
    if market_entry is None:
        fail(f"{coin} missing from Hyperliquid meta universe")

    sz_decimals = int(market_entry["sz_decimals"])
    limit_price = compute_limit_price(
        mid_price=mid_price,
        is_buy=side == "buy",
        slippage=slippage,
        sz_decimals=sz_decimals,
    )
    bundle = build_order_request(
        market_map=market_map,
        coin=coin,
        side=side,
        order_size=order_size,
        limit_price=limit_price,
        reduce_only=reduce_only,
    )
    return {
        "step_type": "order",
        "reason": reason,
        "coin": coin,
        "side": side,
        "reduce_only": reduce_only,
        "mid_price": mid_price,
        "limit_price": limit_price,
        "order_size": order_size,
        "notional_usd": abs(order_size * limit_price),
        "desired_notional_usd": desired_notional_usd,
        "market_asset": int(market_entry["asset"]),
        "payload_action": {
            "type": "order",
            "orders": [bundle["wire"]],
            "grouping": "na",
        },
        "bundle": bundle,
    }


def build_leverage_step(
    *,
    coin: str,
    exchange_leverage_target: int,
    exchange_margin_mode: str,
    reason: str,
    market_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    market_entry = market_map.get(coin)
    if market_entry is None:
        fail(f"{coin} missing from Hyperliquid meta universe")

    return {
        "step_type": "leverage_update",
        "reason": reason,
        "coin": coin,
        "exchange_leverage_target": exchange_leverage_target,
        "exchange_margin_mode": exchange_margin_mode,
        "payload_action": {
            "type": "updateLeverage",
            "asset": int(market_entry["asset"]),
            "isCross": exchange_margin_mode == "cross",
            "leverage": int(exchange_leverage_target),
        },
    }


def build_execution_plan(
    *,
    intent: dict[str, Any],
    snapshot: dict[str, Any],
    market_map: dict[str, dict[str, Any]],
    mids: dict[str, Any],
    policy_cfg: dict[str, Any],
    gate: dict[str, Any],
    recon: dict[str, Any],
    leverage_ctx: dict[str, Any],
    mode_cfg: dict[str, Any],
    slippage: float,
    execute_live: bool,
) -> dict[str, Any]:
    signal_id = str(intent.get("signal_id", "")).strip()
    target_asset = normalize_asset(intent.get("target_asset"))
    target_regime = str(intent.get("target_regime", "")).strip()

    allowed_assets = {
        normalize_asset(item)
        for item in policy_cfg.get("allowed_assets", [])
        if str(item).strip()
    }
    allowed_approval_gate_statuses = {
        str(item).strip()
        for item in policy_cfg.get("allowed_approval_gate_statuses", [])
        if str(item).strip()
    }
    manual_approval_required = bool(policy_cfg.get("manual_approval_required", True))
    require_kill_switch_off = bool(policy_cfg.get("require_kill_switch_off", True))
    max_order_notional_usd = float(policy_cfg.get("max_order_notional_usd", 0.0))

    current_state = derive_current_state(snapshot)
    current_asset = current_state["normalized_state"]
    current_position = None if current_asset in {"CASH", "MULTI_ASSET"} else current_state["active_positions"][0]
    current_position_size = (
        0.0 if current_position is None else float(current_position.get("size", 0.0))
    )

    gate_status = str(gate.get("status", "")).strip()
    approval_gate_status = str(gate.get("approval_gate_status", "")).strip()
    recon_open_orders_count = int(recon.get("open_orders_count", 0))
    snapshot_open_orders_count = extract_snapshot_open_orders_count(snapshot)

    checks = {
        "signal_present": bool(signal_id),
        "target_asset_present": bool(target_asset),
        "target_asset_allowed": target_asset in allowed_assets if target_asset else False,
        "gate_status": gate_status,
        "gate_ready": gate_status == "ready_if_enabled",
        "approval_gate_status": approval_gate_status,
        "approval_status_allowed": approval_gate_status in allowed_approval_gate_statuses,
        "mode": str(mode_cfg.get("mode", "")).strip(),
        "trading_enabled": bool(mode_cfg.get("trading_enabled", False)),
        "kill_switch": bool(mode_cfg.get("kill_switch", True)),
        "allow_live_orders": bool(policy_cfg.get("allow_live_orders", False)),
        "manual_approval_required": manual_approval_required,
        "require_kill_switch_off": require_kill_switch_off,
        "intent_stale_signal": bool(intent.get("stale_signal", False)),
        "duplicate_order_risk": bool(intent.get("duplicate_order_risk", False)),
        "snapshot_open_orders_count": snapshot_open_orders_count,
        "upstream_reconciliation_open_orders_count": recon_open_orders_count,
        "current_state": current_asset,
        "multi_position": bool(current_state["multi_position"]),
        "target_regime": target_regime,
        "max_order_notional_usd": max_order_notional_usd,
        "strategy_target_leverage": leverage_ctx.get("strategy_target_leverage"),
        "exchange_leverage_target": leverage_ctx.get("exchange_leverage_target"),
    }

    block_reasons: list[str] = []
    if not checks["signal_present"]:
        block_reasons.append("missing_signal_id")
    if not checks["target_asset_present"]:
        block_reasons.append("missing_target_asset")
    if not checks["target_asset_allowed"]:
        block_reasons.append("target_asset_not_allowlisted")
    if not checks["gate_ready"]:
        block_reasons.append(f"gate_status={gate_status}")
    if not checks["approval_status_allowed"]:
        block_reasons.append(f"approval_gate_status={approval_gate_status}")
    if not checks["trading_enabled"]:
        block_reasons.append("execution_mode_trading_disabled")
    if not checks["allow_live_orders"]:
        block_reasons.append("allow_live_orders=false")
    if checks["require_kill_switch_off"] and checks["kill_switch"]:
        block_reasons.append("kill_switch_enabled")
    if checks["manual_approval_required"]:
        block_reasons.append("manual_approval_required")
    if checks["intent_stale_signal"]:
        block_reasons.append("stale_signal")
    if checks["duplicate_order_risk"]:
        block_reasons.append("duplicate_order_risk")
    if snapshot_open_orders_count > 0:
        block_reasons.append("open_orders_present_before_first_submit")
    if recon_open_orders_count > 0:
        block_reasons.append("upstream_reconciliation_reports_open_orders")
    if current_state["multi_position"]:
        block_reasons.append("multi_asset_live_exposure_unsupported")
    if current_asset == "MULTI_ASSET":
        block_reasons.append("ambiguous_current_live_state")

    strategy_target_leverage = leverage_ctx.get("strategy_target_leverage")
    exchange_leverage_target = leverage_ctx.get("exchange_leverage_target")
    exchange_margin_mode = leverage_ctx.get("exchange_margin_mode")
    exchange_leverage_blocker = leverage_ctx.get("exchange_leverage_blocker")

    if target_asset != "CASH" and not leverage_ctx.get("resolved", False):
        block_reasons.append(str(exchange_leverage_blocker or "leverage_resolution_failed"))

    if target_asset != "CASH" and strategy_target_leverage is None:
        block_reasons.append("missing_strategy_target_leverage")

    total_trading_equity_usd = compute_total_trading_equity_usd(snapshot)
    if target_asset != "CASH" and (total_trading_equity_usd is None or total_trading_equity_usd <= 0):
        block_reasons.append("missing_positive_total_trading_equity_usd")

    current_target_position = extract_position(snapshot, target_asset)
    current_target_size = (
        0.0 if current_target_position is None else float(current_target_position.get("size", 0.0))
    )
    current_target_leverage = extract_current_leverage(current_target_position)

    steps: list[dict[str, Any]] = []
    target_size = None
    target_notional_usd = None
    target_limit_price = None

    if not block_reasons:
        if target_asset == "CASH":
            if current_asset != "CASH":
                close_coin = normalize_asset(current_position.get("coin")) if current_position else ""
                close_side = "sell" if current_position_size > 0 else "buy"
                close_size = abs(current_position_size)
                steps.append(
                    build_order_step(
                        coin=close_coin,
                        side=close_side,
                        order_size=close_size,
                        reduce_only=True,
                        market_map=market_map,
                        mids=mids,
                        slippage=slippage,
                        reason="close_to_cash",
                        desired_notional_usd=None,
                    )
                )
        else:
            if exchange_leverage_target is None:
                block_reasons.append(str(exchange_leverage_blocker))
            else:
                if exchange_margin_mode is None:
                    if current_target_leverage.get("margin_mode") in {"cross", "isolated"}:
                        exchange_margin_mode = str(current_target_leverage["margin_mode"])
                    else:
                        exchange_margin_mode = DEFAULT_EXCHANGE_MARGIN_MODE

                target_notional_usd = float(total_trading_equity_usd or 0.0) * float(strategy_target_leverage or 0.0)
                if target_notional_usd <= 0:
                    block_reasons.append("non_positive_target_notional_usd")
                elif max_order_notional_usd <= 0:
                    block_reasons.append("max_order_notional_not_enabled")
                elif target_notional_usd > max_order_notional_usd:
                    block_reasons.append(
                        f"target_notional_exceeds_policy_max::{target_notional_usd:.6f}>{max_order_notional_usd:.6f}"
                    )
                else:
                    market_entry = market_map.get(target_asset)
                    mid_price = to_float(mids.get(target_asset))
                    if market_entry is None:
                        block_reasons.append(f"target_asset_not_in_hyperliquid_meta::{target_asset}")
                    elif mid_price is None or mid_price <= 0:
                        block_reasons.append(f"missing_mid_price::{target_asset}")
                    else:
                        target_limit_price = compute_limit_price(
                            mid_price=mid_price,
                            is_buy=True,
                            slippage=slippage,
                            sz_decimals=int(market_entry["sz_decimals"]),
                        )
                        target_size = compute_order_size(
                            notional_usd=target_notional_usd,
                            limit_price=target_limit_price,
                            sz_decimals=int(market_entry["sz_decimals"]),
                        )

                        if current_asset not in {"CASH", target_asset}:
                            close_coin = normalize_asset(current_position.get("coin")) if current_position else ""
                            close_side = "sell" if current_position_size > 0 else "buy"
                            close_size = abs(current_position_size)
                            steps.append(
                                build_order_step(
                                    coin=close_coin,
                                    side=close_side,
                                    order_size=close_size,
                                    reduce_only=True,
                                    market_map=market_map,
                                    mids=mids,
                                    slippage=slippage,
                                    reason="rotate_close_current_asset",
                                    desired_notional_usd=None,
                                )
                            )

                        leverage_needs_update = False
                        if current_target_leverage.get("value") is None:
                            leverage_needs_update = True
                        elif abs(float(current_target_leverage["value"]) - float(exchange_leverage_target)) > 1e-9:
                            leverage_needs_update = True

                        if leverage_needs_update:
                            steps.append(
                                build_leverage_step(
                                    coin=target_asset,
                                    exchange_leverage_target=int(exchange_leverage_target),
                                    exchange_margin_mode=str(exchange_margin_mode),
                                    reason="target_exchange_leverage_change_required",
                                    market_map=market_map,
                                )
                            )

                        delta_size = target_size - current_target_size
                        if abs(delta_size) > POSITION_TOLERANCE:
                            steps.append(
                                build_order_step(
                                    coin=target_asset,
                                    side="buy" if delta_size > 0 else "sell",
                                    order_size=abs(delta_size),
                                    reduce_only=delta_size < 0,
                                    market_map=market_map,
                                    mids=mids,
                                    slippage=slippage,
                                    reason=(
                                        "enter_target_asset"
                                        if current_asset == "CASH"
                                        else ("rebalance_same_asset" if current_asset == target_asset else "rotate_into_target_asset")
                                    ),
                                    desired_notional_usd=target_notional_usd,
                                )
                            )

    if block_reasons:
        status = "blocked"
    elif not steps:
        status = "no_action_needed"
    else:
        status = "ready_if_enabled" if not execute_live else "ready_to_submit"

    return {
        "status": status,
        "signal_id": signal_id,
        "target_asset": target_asset,
        "target_regime": target_regime,
        "current_state": current_asset,
        "current_position_size": current_position_size,
        "current_target_size": current_target_size,
        "current_target_leverage": current_target_leverage,
        "target_size": target_size,
        "target_notional_usd": target_notional_usd,
        "target_limit_price": target_limit_price,
        "total_trading_equity_usd": total_trading_equity_usd,
        "steps": steps,
        "block_reasons": block_reasons,
        "checks": checks,
        "leverage_context": leverage_ctx,
        "snapshot_state": current_state,
    }


def execute_exchange_step(
    *,
    step: dict[str, Any],
    crypto: Any,
    account_setup: dict[str, Any],
    expires_after_ms: int,
) -> dict[str, Any]:
    submit_result = submit_signed_action(
        crypto=crypto,
        account_setup=account_setup,
        action=step["payload_action"],
        expires_after_ms=expires_after_ms,
    )
    normalized = normalize_submit_response(submit_result["response"])
    return {
        "step_type": step["step_type"],
        "reason": step["reason"],
        "coin": step["coin"],
        "submitted_at_utc": utc_now_iso(),
        "nonce": submit_result["nonce"],
        "expires_after": submit_result["expires_after"],
        "payload_without_signature": {
            "action": submit_result["payload"]["action"],
            "nonce": submit_result["payload"]["nonce"],
            "vaultAddress": submit_result["payload"].get("vaultAddress"),
            "expiresAfter": submit_result["payload"].get("expiresAfter"),
        },
        "raw_exchange_response": submit_result["response"],
        "submit_normalized": normalized,
    }


def determine_final_status(
    *,
    preview_only: bool,
    plan: dict[str, Any],
    action_results: list[dict[str, Any]],
    final_snapshot: dict[str, Any],
    final_target_leverage: dict[str, Any],
) -> str:
    if plan["block_reasons"]:
        return "blocked"
    if plan["status"] == "no_action_needed":
        return "no_action_needed"
    if preview_only:
        return "submitted"

    if any(result["submit_normalized"].get("needs_manual_review") for result in action_results):
        return "manual_review_required"

    if extract_snapshot_open_orders_count(final_snapshot) > 0:
        return "resting"

    target_asset = plan["target_asset"]
    final_state = derive_current_state(final_snapshot)["normalized_state"]
    target_position = extract_position(final_snapshot, target_asset)
    final_target_size = 0.0 if target_position is None else float(target_position.get("size", 0.0))

    if target_asset == "CASH":
        return "filled" if final_state == "CASH" else "reconciliation_failed"

    target_size = plan.get("target_size")
    if target_size is None:
        return "reconciliation_failed"

    if final_state != target_asset:
        return "reconciliation_failed"

    if abs(final_target_size - float(target_size)) > POSITION_TOLERANCE:
        return "reconciliation_failed"

    leverage_step_present = any(result["step_type"] == "leverage_update" for result in action_results)
    order_step_present = any(result["step_type"] == "order" for result in action_results)

    exchange_leverage_target = plan["leverage_context"].get("exchange_leverage_target")
    if leverage_step_present and exchange_leverage_target is not None:
        final_leverage_value = final_target_leverage.get("value")
        if final_leverage_value is not None and abs(float(final_leverage_value) - float(exchange_leverage_target)) > 1e-9:
            return "reconciliation_failed"

    if order_step_present:
        return "filled"
    if leverage_step_present:
        return "submitted"
    return "submitted"


def build_post_submit_reconciliation(
    *,
    started_at_utc: str,
    preview_only: bool,
    plan: dict[str, Any],
    pre_snapshot: dict[str, Any],
    post_snapshot: dict[str, Any],
    action_results: list[dict[str, Any]],
    fills_summary: dict[str, Any],
    final_status: str,
) -> dict[str, Any]:
    target_asset = plan["target_asset"]
    final_state = derive_current_state(post_snapshot)
    final_target_position = extract_position(post_snapshot, target_asset)
    final_target_leverage = extract_current_leverage(final_target_position)
    strategy_target_leverage = plan["leverage_context"].get("strategy_target_leverage")
    exchange_leverage_target = plan["leverage_context"].get("exchange_leverage_target")

    order_oids = [
        result["submit_normalized"].get("oid")
        for result in action_results
        if result["step_type"] == "order"
    ]
    open_orders_count_after = extract_snapshot_open_orders_count(post_snapshot)

    return {
        "artifact_type": "controlled_real_order_post_submit_reconciliation",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at_utc,
        "preview_only": preview_only,
        "signal_id": plan["signal_id"],
        "target_asset": target_asset,
        "target_regime": plan["target_regime"],
        "final_status": final_status,
        "current_state_before": derive_current_state(pre_snapshot)["normalized_state"],
        "current_state_after": final_state["normalized_state"],
        "target_size": plan.get("target_size"),
        "final_target_size": (
            None
            if final_target_position is None
            else float(final_target_position.get("size", 0.0))
        ),
        "target_notional_usd": plan.get("target_notional_usd"),
        "strategy_target_leverage": strategy_target_leverage,
        "exchange_leverage_target": exchange_leverage_target,
        "final_exchange_leverage": final_target_leverage,
        "open_orders_count_after": open_orders_count_after,
        "positions_after": extract_snapshot_positions(post_snapshot),
        "order_oids": order_oids,
        "fills_summary": fills_summary,
        "action_results": action_results,
        "checks": {
            "target_state_reached": (
                final_state["normalized_state"] == target_asset
                if target_asset != "CASH"
                else final_state["normalized_state"] == "CASH"
            ),
            "open_orders_cleared": open_orders_count_after == 0,
            "manual_review_required": final_status == "manual_review_required",
            "reconciliation_failed": final_status == "reconciliation_failed",
        },
        "notes": [
            "Strategy exposure sizing uses strategy_target_leverage from upstream leverage artifacts.",
            "Exchange leverage update uses only explicit integer exchange leverage targets compatible with Hyperliquid updateLeverage.",
            "No retries or polling loops are performed here; this is a strict one-shot controlled execution pass.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled Hyperliquid real-order submitter with preview-by-default, "
            "explicit leverage resolution, and one-shot reconciliation artifacts."
        )
    )
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="Actually submit live exchange actions. Default is preview-only.",
    )
    parser.add_argument(
        "--manual-confirm",
        default="",
        help=f"Required together with --execute-live. Must equal {MANUAL_CONFIRM_TOKEN}.",
    )
    parser.add_argument(
        "--intent-path",
        type=Path,
        default=DEFAULT_INTENT_PATH,
        help="Execution intent JSON to use. Defaults to outputs/execution/intents/latest_execution_intent.json",
    )
    parser.add_argument(
        "--gate-path",
        type=Path,
        default=DEFAULT_GATE_PATH,
        help="Gate decision JSON to use.",
    )
    parser.add_argument(
        "--reconciliation-path",
        type=Path,
        default=DEFAULT_RECON_PATH,
        help="Upstream reconciliation JSON to use as evidence context.",
    )
    parser.add_argument(
        "--snapshot-path",
        type=Path,
        default=None,
        help=(
            "Optional snapshot JSON override for preview-only planning tests. "
            "Ignored when --execute-live is used."
        ),
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=DEFAULT_SLIPPAGE,
        help="Aggressive IOC slippage as a decimal.",
    )
    parser.add_argument(
        "--expires-after-ms",
        type=int,
        default=DEFAULT_EXPIRES_AFTER_MS,
        help="Short exchange action expiry window in milliseconds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_manual_execution(args)

    SUBMIT_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at_utc = utc_now_iso()
    log(
        "[START] submit_controlled_real_order "
        f"execute_live={args.execute_live} intent_path={args.intent_path}"
    )

    mode_cfg = read_json(MODE_CONFIG_PATH)
    policy_cfg = read_json(LIVE_ORDER_POLICY_PATH)
    account_cfg = read_json(ACCOUNT_CONFIG_PATH)
    intent = read_json(args.intent_path)
    gate = read_json(args.gate_path)
    recon = read_json(args.reconciliation_path)

    preview_account_address = str(account_cfg.get("account_address", "")).strip()
    if not preview_account_address:
        fail("execution/config/hyperliquid_account.json missing account_address")

    auth_probe: dict[str, Any] = {
        "skipped": not args.execute_live,
        "signature_roundtrip_ok": not args.execute_live,
        "uses_agent_wallet": False,
    }
    agent_verification = None
    account_setup: dict[str, Any] | None = None
    crypto: Any = None
    account_address_for_snapshot = preview_account_address

    if args.execute_live:
        auth_context = build_auth_context(account_cfg)
        auth_probe = auth_context["auth_probe"]
        agent_verification = auth_context["agent_verification"]
        account_setup = auth_context["account_setup"]
        crypto = auth_context["crypto"]
        account_address_for_snapshot = account_setup["account_address"]

    pre_snapshot = load_snapshot_for_planning(args, account_address_for_snapshot)
    write_json(PRE_SNAPSHOT_PATH, pre_snapshot)

    leverage_ctx = resolve_leverage_context(intent, normalize_asset(intent.get("target_asset")))
    pre_snapshot_state = derive_current_state(pre_snapshot)["normalized_state"]
    needs_market_data = not (
        normalize_asset(intent.get("target_asset")) == "CASH"
        and pre_snapshot_state == "CASH"
    )
    if needs_market_data:
        meta = fetch_meta()
        market_map = build_market_map(meta)
        mids = fetch_all_mids()
    else:
        market_map = {}
        mids = {}

    plan = build_execution_plan(
        intent=intent,
        snapshot=pre_snapshot,
        market_map=market_map,
        mids=mids,
        policy_cfg=policy_cfg,
        gate=gate,
        recon=recon,
        leverage_ctx=leverage_ctx,
        mode_cfg=mode_cfg,
        slippage=float(args.slippage),
        execute_live=bool(args.execute_live),
    )

    auth_block_reasons: list[str] = []
    if not auth_probe["signature_roundtrip_ok"]:
        auth_block_reasons.append("signing_roundtrip_failed")
    if args.execute_live and account_setup is not None and account_setup["uses_agent_wallet"]:
        if agent_verification is None:
            auth_block_reasons.append("agent_wallet_verification_missing")
        else:
            if agent_verification.get("looks_like_agent_account"):
                auth_block_reasons.append("account_address_looks_like_agent_wallet_not_main_account")
            if not agent_verification.get("signer_authorized"):
                auth_block_reasons.append("signer_not_authorized_in_extra_agents")

    if auth_block_reasons:
        plan["block_reasons"].extend(auth_block_reasons)
        plan["status"] = "blocked"

    request_payload_artifact = {
        "artifact_type": "controlled_real_order_submit_request_payload",
        "generated_at_utc": utc_now_iso(),
        "preview_only": not args.execute_live,
        "signal_id": plan["signal_id"],
        "target_asset": plan["target_asset"],
        "steps": [
            {
                "step_type": step["step_type"],
                "reason": step["reason"],
                "coin": step["coin"],
                "payload_action": step["payload_action"],
                "side": step.get("side"),
                "reduce_only": step.get("reduce_only"),
                "order_size": step.get("order_size"),
                "limit_price": step.get("limit_price"),
                "notional_usd": step.get("notional_usd"),
                "exchange_leverage_target": step.get("exchange_leverage_target"),
                "exchange_margin_mode": step.get("exchange_margin_mode"),
            }
            for step in plan["steps"]
        ],
        "notes": [
            "This artifact preserves the exact planned request actions before any live submit.",
            "Preview mode writes the same action plan but does not call the exchange.",
        ],
    }
    write_json(REQUEST_PAYLOAD_PATH, request_payload_artifact)

    action_results: list[dict[str, Any]] = []
    post_snapshot = pre_snapshot
    fills_summary: dict[str, Any] = {
        "fills_count": 0,
        "filled_size": 0.0,
        "average_px": None,
        "fills": [],
    }
    leverage_action_response = {
        "artifact_type": "controlled_real_order_leverage_action_response",
        "generated_at_utc": utc_now_iso(),
        "preview_only": not args.execute_live,
        "signal_id": plan["signal_id"],
        "target_asset": plan["target_asset"],
        "leverage_action_result": None,
    }

    if args.execute_live and account_setup is not None and not plan["block_reasons"] and plan["steps"]:
        log("[LIVE] submitting controlled execution steps")

        for step in plan["steps"]:
            result = execute_exchange_step(
                step=step,
                crypto=crypto,
                account_setup=account_setup,
                expires_after_ms=int(args.expires_after_ms),
            )
            action_results.append(result)

            if step["step_type"] == "leverage_update":
                leverage_action_response["leverage_action_result"] = result

            if step["step_type"] == "order":
                post_snapshot = refresh_live_snapshot(account_setup["account_address"])
                if extract_snapshot_open_orders_count(post_snapshot) > 0:
                    break
                if step["reason"] == "rotate_close_current_asset":
                    current_after_close = derive_current_state(post_snapshot)["normalized_state"]
                    if current_after_close != "CASH":
                        break
            else:
                post_snapshot = refresh_live_snapshot(account_setup["account_address"])

        order_nonces = [
            int(result["nonce"])
            for result in action_results
            if result["step_type"] == "order"
        ]
        if order_nonces:
            fills = fetch_user_fills_by_time(
                account_address=account_setup["account_address"],
                start_time_ms=max(0, min(order_nonces) - 2_000),
                end_time_ms=int(time.time() * 1000),
            )
            matched: list[dict[str, Any]] = []
            for result in action_results:
                if result["step_type"] != "order":
                    continue
                matched.extend(
                    filter_fills_for_oid(
                        fills,
                        result["submit_normalized"].get("oid"),
                    )
                )
            fills_summary = summarize_fills(matched)
    write_json(LEVERAGE_RESPONSE_PATH, leverage_action_response)
    write_json(
        EXCHANGE_RESPONSE_PATH,
        {
            "artifact_type": "controlled_real_order_exchange_response",
            "generated_at_utc": utc_now_iso(),
            "preview_only": not args.execute_live,
            "signal_id": plan["signal_id"],
            "target_asset": plan["target_asset"],
            "action_results": action_results,
        },
    )

    if not args.execute_live or not action_results:
        post_snapshot = pre_snapshot

    write_json(POST_SNAPSHOT_PATH, post_snapshot)

    final_target_position = extract_position(post_snapshot, plan["target_asset"])
    final_target_leverage = extract_current_leverage(final_target_position)
    final_status = determine_final_status(
        preview_only=not args.execute_live,
        plan=plan,
        action_results=action_results,
        final_snapshot=post_snapshot,
        final_target_leverage=final_target_leverage,
    )
    post_reconciliation = build_post_submit_reconciliation(
        started_at_utc=started_at_utc,
        preview_only=not args.execute_live,
        plan=plan,
        pre_snapshot=pre_snapshot,
        post_snapshot=post_snapshot,
        action_results=action_results,
        fills_summary=fills_summary,
        final_status=final_status,
    )
    write_json(POST_RECON_PATH, post_reconciliation)

    decision = {
        "submit_type": "controlled_real_order_submit_decision",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at_utc,
        "preview_only": not args.execute_live,
        "signal_id": plan["signal_id"],
        "target_asset": plan["target_asset"],
        "target_regime": plan["target_regime"],
        "status": final_status if args.execute_live else plan["status"],
        "would_submit": bool(plan["steps"]) and not bool(plan["block_reasons"]),
        "real_order_sent": bool(args.execute_live and action_results),
        "submit_block_reasons": plan["block_reasons"],
        "checks": plan["checks"],
        "auth_probe": auth_probe,
        "agent_verification": agent_verification,
        "pre_submit_snapshot_state": plan["snapshot_state"],
        "strategy_target_leverage": leverage_ctx.get("strategy_target_leverage"),
        "strategy_leverage_source_field": leverage_ctx.get("strategy_leverage_source_field"),
        "exchange_leverage_target": leverage_ctx.get("exchange_leverage_target"),
        "exchange_leverage_source_field": leverage_ctx.get("exchange_leverage_source_field"),
        "exchange_margin_mode": (
            leverage_ctx.get("exchange_margin_mode")
            or final_target_leverage.get("margin_mode")
            or DEFAULT_EXCHANGE_MARGIN_MODE
        ),
        "exchange_margin_mode_source_field": leverage_ctx.get("exchange_margin_mode_source_field"),
        "exchange_leverage_blocker": leverage_ctx.get("exchange_leverage_blocker"),
        "submit_plan": {
            "current_state": plan["current_state"],
            "current_position_size": plan["current_position_size"],
            "current_target_size": plan["current_target_size"],
            "target_size": plan["target_size"],
            "target_notional_usd": plan["target_notional_usd"],
            "target_limit_price": plan["target_limit_price"],
            "total_trading_equity_usd": plan["total_trading_equity_usd"],
            "steps": request_payload_artifact["steps"],
        },
        "final_post_submit_reconciliation_path": str(POST_RECON_PATH.resolve()),
        "source_paths": build_source_paths(args),
        "notes": [
            "Preview mode preserves the full execution plan and evidence artifacts without sending exchange actions.",
            "Live submit uses one-shot exchange actions only; there are no retry loops here.",
            "If non-CASH intent lacks an explicit integer exchange leverage target, the script blocks instead of guessing.",
        ],
    }

    quality = {
        "submit_preview_ok": True,
        "status": decision["status"],
        "would_submit": decision["would_submit"],
        "real_order_sent": decision["real_order_sent"],
        "block_reason_count": len(plan["block_reasons"]),
        "strategy_target_leverage_present": leverage_ctx.get("strategy_target_leverage") is not None,
        "exchange_leverage_target_present": leverage_ctx.get("exchange_leverage_target") is not None,
        "post_submit_reconciliation_path": str(POST_RECON_PATH.resolve()),
    }

    manifest = {
        "artifact_name": "latest_submit_preview_decision",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at_utc,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(MODE_CONFIG_PATH.resolve()),
            str(LIVE_ORDER_POLICY_PATH.resolve()),
            str(ACCOUNT_CONFIG_PATH.resolve()),
            str(args.intent_path.resolve()),
            str(args.gate_path.resolve()),
            str(args.reconciliation_path.resolve()),
            str(PRE_SNAPSHOT_PATH.resolve()),
        ],
        "output_paths": [
            str(DECISION_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
            str(REQUEST_PAYLOAD_PATH.resolve()),
            str(EXCHANGE_RESPONSE_PATH.resolve()),
            str(LEVERAGE_RESPONSE_PATH.resolve()),
            str(PRE_SNAPSHOT_PATH.resolve()),
            str(POST_SNAPSHOT_PATH.resolve()),
            str(POST_RECON_PATH.resolve()),
        ],
        "status": decision["status"],
    }

    write_json(DECISION_PATH, decision)
    write_json(QUALITY_PATH, quality)
    write_json(MANIFEST_PATH, manifest)

    log(f"[SAVED] {DECISION_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[SAVED] {REQUEST_PAYLOAD_PATH}")
    log(f"[SAVED] {EXCHANGE_RESPONSE_PATH}")
    log(f"[SAVED] {LEVERAGE_RESPONSE_PATH}")
    log(f"[SAVED] {PRE_SNAPSHOT_PATH}")
    log(f"[SAVED] {POST_SNAPSHOT_PATH}")
    log(f"[SAVED] {POST_RECON_PATH}")
    log(f"[END] submit_controlled_real_order status={decision['status']}")


if __name__ == "__main__":
    main()
