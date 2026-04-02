
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "hyperliquid_execution"

API_BASE = {
    "mainnet": "https://api.hyperliquid.xyz",
    "testnet": "https://api.hyperliquid-testnet.xyz",
}

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def validate_address(address: str) -> str:
    address = address.strip()
    if not ADDRESS_RE.match(address):
        raise ValueError(
            "Neplatná Hyperliquid/EVM adresa. Očakávam formát 0x + 40 hex znakov."
        )
    return address


def post_info(session: requests.Session, base_url: str, payload: dict[str, Any]) -> Any:
    url = f"{base_url}/info"
    resp = session.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def normalize_positions(clearinghouse_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for item in clearinghouse_state.get("assetPositions", []) or []:
        position = item.get("position", {}) if isinstance(item, dict) else {}
        leverage = position.get("leverage", {}) if isinstance(position, dict) else {}

        rows.append(
            {
                "coin": position.get("coin"),
                "szi": safe_float(position.get("szi")),
                "entryPx": safe_float(position.get("entryPx")),
                "positionValue": safe_float(position.get("positionValue")),
                "unrealizedPnl": safe_float(position.get("unrealizedPnl")),
                "returnOnEquity": safe_float(position.get("returnOnEquity")),
                "marginUsed": safe_float(position.get("marginUsed")),
                "liquidationPx": safe_float(position.get("liquidationPx")),
                "leverage_type": leverage.get("type"),
                "leverage_value": leverage.get("value"),
                "leverage_rawUsd": safe_float(leverage.get("rawUsd")),
                "position_wrapper_type": item.get("type") if isinstance(item, dict) else None,
            }
        )

    return rows


def normalize_open_orders(
    frontend_open_orders: Any,
    plain_open_orders: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    source = frontend_open_orders if isinstance(frontend_open_orders, list) else []
    if source:
        for item in source:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "coin": item.get("coin"),
                    "oid": item.get("oid"),
                    "side": item.get("side"),
                    "limitPx": safe_float(item.get("limitPx")),
                    "origSz": safe_float(item.get("origSz")),
                    "sz": safe_float(item.get("sz")),
                    "timestamp": item.get("timestamp"),
                    "orderType": item.get("orderType"),
                    "reduceOnly": item.get("reduceOnly"),
                    "tif": item.get("tif"),
                    "isTrigger": item.get("isTrigger"),
                    "triggerPx": safe_float(item.get("triggerPx")),
                    "triggerCondition": item.get("triggerCondition"),
                    "source": "frontendOpenOrders",
                }
            )
        return rows

    source = plain_open_orders if isinstance(plain_open_orders, list) else []
    for item in source:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "coin": item.get("coin"),
                "oid": item.get("oid"),
                "side": item.get("side"),
                "limitPx": safe_float(item.get("limitPx")),
                "origSz": None,
                "sz": safe_float(item.get("sz")),
                "timestamp": item.get("timestamp"),
                "orderType": None,
                "reduceOnly": None,
                "tif": None,
                "isTrigger": None,
                "triggerPx": None,
                "triggerCondition": None,
                "source": "openOrders",
            }
        )

    return rows


def normalize_spot_balances(spot_state: Any) -> list[dict[str, Any]]:
    if not isinstance(spot_state, dict):
        return []

    balances = spot_state.get("balances", [])
    if not isinstance(balances, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in balances:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "coin": item.get("coin"),
                "token": item.get("token"),
                "total": safe_float(item.get("total")),
                "hold": safe_float(item.get("hold")),
                "entryNtl": safe_float(item.get("entryNtl")),
            }
        )
    return rows


def build_summary(
    network: str,
    account: str,
    clearinghouse_state: dict[str, Any],
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    spot_balances: list[dict[str, Any]],
    portfolio: Any,
) -> dict[str, Any]:
    margin_summary = (
        clearinghouse_state.get("marginSummary", {})
        if isinstance(clearinghouse_state, dict)
        else {}
    )
    cross_margin_summary = (
        clearinghouse_state.get("crossMarginSummary", {})
        if isinstance(clearinghouse_state, dict)
        else {}
    )

    account_value = safe_float(margin_summary.get("accountValue"))
    withdrawable = safe_float(clearinghouse_state.get("withdrawable"))

    nonzero_positions = [
        row for row in positions if row.get("szi") not in (None, 0.0)
    ]
    nonzero_balances = [
        row for row in spot_balances if (row.get("total") or 0.0) != 0.0
    ]

    portfolio_periods: list[str] = []
    if isinstance(portfolio, list):
        for item in portfolio:
            if isinstance(item, list) and item:
                portfolio_periods.append(str(item[0]))

    return {
        "generated_at_utc": now_utc_iso(),
        "network": network,
        "account": account,
        "account_value": account_value,
        "withdrawable": withdrawable,
        "total_margin_used": safe_float(margin_summary.get("totalMarginUsed")),
        "total_ntl_pos": safe_float(margin_summary.get("totalNtlPos")),
        "total_raw_usd": safe_float(margin_summary.get("totalRawUsd")),
        "cross_account_value": safe_float(cross_margin_summary.get("accountValue")),
        "positions_count": len(positions),
        "nonzero_positions_count": len(nonzero_positions),
        "open_orders_count": len(open_orders),
        "spot_balances_count": len(spot_balances),
        "nonzero_spot_balances_count": len(nonzero_balances),
        "position_coins": [row.get("coin") for row in nonzero_positions if row.get("coin")],
        "open_order_coins": sorted(
            {str(row.get("coin")) for row in open_orders if row.get("coin")}
        ),
        "spot_balance_coins": [row.get("coin") for row in nonzero_balances if row.get("coin")],
        "portfolio_periods": portfolio_periods,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hyperliquid read-only account snapshot")
    parser.add_argument("--network", choices=["mainnet", "testnet"], required=True)
    parser.add_argument("--account", required=True, help="0x... public account address")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    network = args.network
    account = validate_address(args.account)
    base_url = API_BASE[network]

    ensure_dir(OUT_DIR)

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    print("[HL-READONLY] START", flush=True)
    print(f"[HL-READONLY] network={network}", flush=True)
    print(f"[HL-READONLY] account={account}", flush=True)
    print(f"[HL-READONLY] base_url={base_url}", flush=True)

    clearinghouse_state = post_info(
        session,
        base_url,
        {"type": "clearinghouseState", "user": account},
    )
    print("[HL-READONLY] fetched=clearinghouseState", flush=True)

    open_orders = post_info(
        session,
        base_url,
        {"type": "openOrders", "user": account},
    )
    print("[HL-READONLY] fetched=openOrders", flush=True)

    try:
        frontend_open_orders = post_info(
            session,
            base_url,
            {"type": "frontendOpenOrders", "user": account},
        )
        print("[HL-READONLY] fetched=frontendOpenOrders", flush=True)
    except Exception as exc:
        frontend_open_orders = []
        print(f"[HL-READONLY] frontendOpenOrders_fallback={exc}", flush=True)

    try:
        spot_state = post_info(
            session,
            base_url,
            {"type": "spotClearinghouseState", "user": account},
        )
        print("[HL-READONLY] fetched=spotClearinghouseState", flush=True)
    except Exception as exc:
        spot_state = {}
        print(f"[HL-READONLY] spotClearinghouseState_fallback={exc}", flush=True)

    try:
        portfolio = post_info(
            session,
            base_url,
            {"type": "portfolio", "user": account},
        )
        print("[HL-READONLY] fetched=portfolio", flush=True)
    except Exception as exc:
        portfolio = []
        print(f"[HL-READONLY] portfolio_fallback={exc}", flush=True)

    positions_rows = normalize_positions(clearinghouse_state)
    open_orders_rows = normalize_open_orders(frontend_open_orders, open_orders)
    spot_balance_rows = normalize_spot_balances(spot_state)

    snapshot_payload = {
        "generated_at_utc": now_utc_iso(),
        "network": network,
        "account": account,
        "base_url": base_url,
        "clearinghouseState": clearinghouse_state,
        "openOrders": open_orders,
        "frontendOpenOrders": frontend_open_orders,
        "spotClearinghouseState": spot_state,
        "portfolio": portfolio,
        "normalized": {
            "positions": positions_rows,
            "open_orders": open_orders_rows,
            "spot_balances": spot_balance_rows,
        },
    }

    summary_payload = build_summary(
        network=network,
        account=account,
        clearinghouse_state=clearinghouse_state,
        positions=positions_rows,
        open_orders=open_orders_rows,
        spot_balances=spot_balance_rows,
        portfolio=portfolio,
    )

    account_snapshot_path = OUT_DIR / "account_snapshot.json"
    positions_path = OUT_DIR / "positions.csv"
    open_orders_path = OUT_DIR / "open_orders.csv"
    summary_path = OUT_DIR / "execution_account_summary.json"

    write_json(account_snapshot_path, snapshot_payload)
    write_csv(positions_path, positions_rows)
    write_csv(open_orders_path, open_orders_rows)
    write_json(summary_path, summary_payload)

    print("[HL-READONLY] status=OK", flush=True)
    print(f"[HL-READONLY] account_snapshot={account_snapshot_path}", flush=True)
    print(f"[HL-READONLY] positions_csv={positions_path}", flush=True)
    print(f"[HL-READONLY] open_orders_csv={open_orders_path}", flush=True)
    print(f"[HL-READONLY] execution_account_summary={summary_path}", flush=True)


if __name__ == "__main__":
    main()