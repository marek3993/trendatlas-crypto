from __future__ import annotations

"""Build the canonical, read-only Hyperliquid real-account performance ledger.

The ledger deliberately keeps exchange events and equity-change accounting separate.
It never substitutes model data, never infers an external cash flow, and is safe to
rebuild: event identifiers and equity valuation points are deterministic.
"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
READ_ONLY_DIR = ROOT / "outputs" / "execution" / "read_only"
SNAPSHOT_PATH = READ_ONLY_DIR / "hyperliquid_account_snapshot.json"
LEDGER_PATH = READ_ONLY_DIR / "hyperliquid_real_performance_ledger.json"
QUALITY_PATH = READ_ONLY_DIR / "hyperliquid_real_performance_ledger.quality.json"
MANIFEST_PATH = READ_ONLY_DIR / "hyperliquid_real_performance_ledger.manifest.json"
EPSILON = 1e-8


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def as_float(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def utc_from_ms(value: Any) -> str | None:
    parsed = as_float(value)
    if parsed is None:
        return None
    return datetime.fromtimestamp(parsed / 1000.0, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def effective_day(timestamp_utc: str | None) -> str | None:
    return timestamp_utc[:10] if isinstance(timestamp_utc, str) and len(timestamp_utc) >= 10 else None


def canonical_id(prefix: str, payload: dict[str, Any], fields: Iterable[str]) -> str:
    explicit = next((payload.get(key) for key in fields if payload.get(key) not in (None, "")), None)
    if explicit is not None:
        return f"{prefix}:{explicit}"
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}:sha256:{hashlib.sha256(stable.encode('utf-8')).hexdigest()}"


def event_from_fill(fill: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = utc_from_ms(fill.get("time") or fill.get("timestamp"))
    if timestamp is None:
        return None
    fee = as_float(fill.get("fee")) or 0.0
    closed_pnl = as_float(fill.get("closedPnl")) or 0.0
    return {
        "event_id": canonical_id("fill", fill, ("tid", "tradeId", "hash", "oid")),
        "event_type": "fill",
        "timestamp_utc": timestamp,
        "effective_day": effective_day(timestamp),
        "realized_trading_pnl_usd": closed_pnl,
        "fees_usd": -abs(fee),
        "funding_usd": 0.0,
        "deposits_usd": 0.0,
        "withdrawals_usd": 0.0,
        "source": "Hyperliquid userFillsByTime.closedPnl/fee",
        "raw": fill,
    }


def event_from_funding(funding: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = utc_from_ms(funding.get("time") or funding.get("timestamp"))
    if timestamp is None:
        return None
    delta = funding.get("delta") if isinstance(funding.get("delta"), dict) else funding
    amount = as_float(delta.get("usdc"))
    if amount is None:
        return None
    return {
        "event_id": f"funding:{funding.get('time') or funding.get('timestamp')}:{delta.get('coin') or funding.get('coin') or ''}",
        "event_type": "funding",
        "timestamp_utc": timestamp,
        "effective_day": effective_day(timestamp),
        "realized_trading_pnl_usd": 0.0,
        "fees_usd": 0.0,
        "funding_usd": amount,
        "deposits_usd": 0.0,
        "withdrawals_usd": 0.0,
        "source": "Hyperliquid userFunding.usdc",
        "raw": funding,
    }


def event_from_non_funding(update: dict[str, Any], account_address: str) -> dict[str, Any] | None:
    timestamp = utc_from_ms(update.get("time") or update.get("timestamp"))
    delta = update.get("delta") if isinstance(update.get("delta"), dict) else {}
    kind = str(delta.get("type") or "unknown").strip()
    if timestamp is None or not kind:
        return None
    amount = as_float(delta.get("usdc"))
    if amount is None:
        amount = as_float(delta.get("usdcValue"))
    if amount is None:
        amount = as_float(delta.get("amount")) or 0.0
    normalized_account = account_address.lower()
    incoming_send = kind == "send" and str(delta.get("destination") or "").lower() == normalized_account
    outgoing_send = kind == "send" and str(delta.get("user") or "").lower() == normalized_account
    deposits = abs(amount) if kind == "deposit" or incoming_send else 0.0
    withdrawals = abs(amount) if kind == "withdraw" or outgoing_send else 0.0
    return {
        "event_id": canonical_id("nonfunding", update, ("hash", "time")),
        "event_type": kind,
        "timestamp_utc": timestamp,
        "effective_day": effective_day(timestamp),
        "realized_trading_pnl_usd": 0.0,
        "fees_usd": 0.0,
        "funding_usd": 0.0,
        "deposits_usd": deposits,
        "withdrawals_usd": withdrawals,
        "source": "Hyperliquid userNonFundingLedgerUpdates.delta",
        "raw": update,
    }


def extract_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("raw") if isinstance(snapshot.get("raw"), dict) else {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    requested_start = str(summary.get("ledger_start_utc") or "").strip()
    events: list[dict[str, Any]] = []
    for fill in raw.get("userFillsByTime", []) if isinstance(raw.get("userFillsByTime"), list) else []:
        if isinstance(fill, dict):
            event = event_from_fill(fill)
            if event:
                events.append(event)
    for funding in raw.get("userFunding", []) if isinstance(raw.get("userFunding"), list) else []:
        if isinstance(funding, dict):
            event = event_from_funding(funding)
            if event:
                events.append(event)
    for update in raw.get("userNonFundingLedgerUpdates", []) if isinstance(raw.get("userNonFundingLedgerUpdates"), list) else []:
        if isinstance(update, dict):
            event = event_from_non_funding(update, str(snapshot.get("account_address") or ""))
            if event:
                events.append(event)
    return events


def merge_events(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(event.get("event_id")): event for event in existing if isinstance(event, dict) and event.get("event_id")}
    for event in incoming:
        by_id[str(event["event_id"])] = event
    return sorted(by_id.values(), key=lambda event: (str(event.get("timestamp_utc") or ""), str(event.get("event_id"))))


def merge_valuations(existing: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    requested_start = str(summary.get("ledger_start_utc") or "").strip()
    timestamp = str(snapshot.get("as_of_utc") or "").strip()
    equity = as_float(summary.get("account_equity_usd"))
    address = str(snapshot.get("account_address") or "").strip()
    if not timestamp or equity is None or not address:
        return existing
    point = {
        "valuation_id": f"equity:{address.lower()}:{timestamp}",
        "timestamp_utc": timestamp,
        "effective_day": effective_day(timestamp),
        "equity_usd": equity,
        "free_collateral_usd": as_float(summary.get("free_collateral_usd")) if summary.get("free_collateral_usd") is not None else as_float(summary.get("available_balance_usd")),
        "margin_used_usd": as_float(summary.get("margin_used_usd")) if summary.get("margin_used_usd") is not None else as_float((summary.get("margin_summary") or {}).get("totalMarginUsed")),
        "source": "Hyperliquid clearinghouseState/spotClearinghouseState snapshot",
    }
    by_id = {str(row.get("valuation_id")): row for row in existing if isinstance(row, dict) and row.get("valuation_id")}
    raw = snapshot.get("raw") if isinstance(snapshot.get("raw"), dict) else {}
    portfolio = raw.get("portfolio") if isinstance(raw.get("portfolio"), list) else []
    for portfolio_row in portfolio:
        if not isinstance(portfolio_row, list) or len(portfolio_row) != 2 or not isinstance(portfolio_row[1], dict):
            continue
        period_name, period_payload = str(portfolio_row[0]), portfolio_row[1]
        # The non-perp views contain total account value.  They overlap at different
        # resolutions; the timestamp id makes the merge deterministic and idempotent.
        if period_name.startswith("perp"):
            continue
        history = period_payload.get("accountValueHistory", [])
        for row in history if isinstance(history, list) else []:
            if not isinstance(row, list) or len(row) < 2:
                continue
            historical_timestamp = utc_from_ms(row[0])
            historical_equity = as_float(row[1])
            if historical_timestamp is None or historical_equity is None:
                continue
            if requested_start and historical_timestamp < requested_start:
                continue
            valuation_id = f"portfolio_equity:{address.lower()}:{historical_timestamp}"
            by_id[valuation_id] = {
                "valuation_id": valuation_id, "timestamp_utc": historical_timestamp,
                "effective_day": effective_day(historical_timestamp), "equity_usd": historical_equity,
                "free_collateral_usd": None, "margin_used_usd": None,
                "source": f"Hyperliquid portfolio.{period_name}.accountValueHistory",
            }
    by_id[point["valuation_id"]] = point
    return sorted(by_id.values(), key=lambda row: str(row.get("timestamp_utc") or ""))


def _sum(events: list[dict[str, Any]], key: str) -> float:
    return round(sum(as_float(event.get(key)) or 0.0 for event in events), 10)


def _period_return(valuations: list[dict[str, Any]], events: list[dict[str, Any]], start_day: str, end_day: str) -> dict[str, Any]:
    period_vals = [row for row in valuations if start_day <= str(row.get("effective_day") or "") <= end_day]
    if len(period_vals) < 2:
        return {"available": False, "value_pct": None, "reason": "insufficient_equity_valuation_points"}
    # Cash flows are timestamped, but daily snapshots cannot reliably split a same-day
    # valuation around a flow. Mark that return unavailable rather than inventing it.
    flows = [event for event in events if start_day <= str(event.get("effective_day") or "") <= end_day and abs((as_float(event.get("deposits_usd")) or 0.0) - (as_float(event.get("withdrawals_usd")) or 0.0)) > EPSILON]
    if flows:
        return {"available": False, "value_pct": None, "reason": "cash_flow_without_intraday_valuation"}
    start_equity = as_float(period_vals[0].get("equity_usd"))
    end_equity = as_float(period_vals[-1].get("equity_usd"))
    if start_equity is None or end_equity is None or start_equity <= EPSILON:
        return {"available": False, "value_pct": None, "reason": "invalid_starting_equity"}
    return {"available": True, "value_pct": round(((end_equity / start_equity) - 1.0) * 100.0, 8), "reason": None}


def build_ledger(snapshot: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = existing if isinstance(existing, dict) else {}
    account_address = str(snapshot.get("account_address") or "").strip()
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    requested_start = str(summary.get("ledger_start_utc") or "").strip()
    prior_events = previous.get("events", []) if isinstance(previous.get("events"), list) else []
    prior_valuations = previous.get("equity_valuations", []) if isinstance(previous.get("equity_valuations"), list) else []
    if requested_start:
        prior_events = [row for row in prior_events if str(row.get("timestamp_utc") or "") >= requested_start]
        prior_valuations = [row for row in prior_valuations if str(row.get("timestamp_utc") or "") >= requested_start]
    events = merge_events(prior_events, extract_events(snapshot))
    valuations = merge_valuations(prior_valuations, snapshot)
    days = sorted({str(row.get("effective_day")) for row in valuations if row.get("effective_day")})
    daily: list[dict[str, Any]] = []
    cumulative_net_pnl: float | None = None
    for index, day in enumerate(days):
        day_events = [event for event in events if event.get("effective_day") == day]
        day_vals = [row for row in valuations if row.get("effective_day") == day]
        start_value = day_vals[0] if day_vals else {}
        end_value = day_vals[-1] if day_vals else {}
        equity = as_float(end_value.get("equity_usd"))
        deposits, withdrawals = _sum(day_events, "deposits_usd"), _sum(day_events, "withdrawals_usd")
        net_flow = round(deposits - withdrawals, 10)
        prior_equity = as_float(daily[-1].get("equity_usd")) if daily else None
        opening_equity = prior_equity if prior_equity is not None else as_float(start_value.get("equity_usd"))
        if opening_equity is not None and equity is not None and (prior_equity is not None or len(day_vals) > 1):
            daily_pnl = round(equity - opening_equity - net_flow, 10)
        else:
            daily_pnl = None
        if cumulative_net_pnl is None:
            cumulative_net_pnl = daily_pnl
        elif daily_pnl is not None:
            cumulative_net_pnl = round(cumulative_net_pnl + daily_pnl, 10)
        components = round(_sum(day_events, "realized_trading_pnl_usd") + _sum(day_events, "funding_usd") + _sum(day_events, "fees_usd"), 10)
        reconciliation_delta = round(daily_pnl - components, 10) if daily_pnl is not None else None
        daily.append({
            "timestamp_utc": end_value.get("timestamp_utc"), "effective_day": day, "account_address": account_address,
            "equity_usd": equity, "beginning_equity_usd": opening_equity, "free_collateral_usd": as_float(end_value.get("free_collateral_usd")), "margin_used_usd": as_float(end_value.get("margin_used_usd")),
            "deposits_usd": deposits, "withdrawals_usd": withdrawals, "net_external_flow_usd": net_flow,
            "realized_trading_pnl_usd": _sum(day_events, "realized_trading_pnl_usd"), "unrealized_pnl_usd": None,
            "fees_usd": _sum(day_events, "fees_usd"), "funding_usd": _sum(day_events, "funding_usd"),
            "daily_net_pnl_usd": daily_pnl, "cumulative_net_pnl_usd": cumulative_net_pnl,
            "exchange_event_net_pnl_usd": components, "equity_event_reconciliation_delta_usd": reconciliation_delta,
        })
    current = daily[-1] if daily else {}
    current_day = str(current.get("effective_day") or "")
    history_days = len(days)
    windows: dict[str, dict[str, Any]] = {}
    for label, days_count in (("today", 1), ("7d", 7), ("30d", 30), ("90d", 90)):
        if not current_day or history_days < days_count:
            windows[label] = {"available": False, "history_days": history_days, "pnl_usd": None, "return_pct": None, "reason": "insufficient_live_history"}
            continue
        start_day = days[max(0, len(days) - days_count)]
        period_rows = [row for row in daily if start_day <= row["effective_day"] <= current_day]
        pnl_values = [as_float(row.get("daily_net_pnl_usd")) for row in period_rows]
        pnl = round(sum(value for value in pnl_values if value is not None), 10) if all(value is not None for value in pnl_values) else None
        ret = _period_return(valuations, events, start_day, current_day)
        windows[label] = {"available": ret["available"] and pnl is not None, "history_days": history_days, "pnl_usd": pnl, "return_pct": ret["value_pct"], "reason": ret["reason"]}
    if daily and cumulative_net_pnl is not None:
        inception_return = _period_return(valuations, events, days[0], current_day)
    else:
        inception_return = {"available": False, "value_pct": None, "reason": "insufficient_equity_valuation_points"}
    latest_raw = snapshot.get("raw") if isinstance(snapshot.get("raw"), dict) else {}
    positions = latest_raw.get("clearinghouseState", {}).get("assetPositions", []) if isinstance(latest_raw.get("clearinghouseState"), dict) else []
    unrealized = 0.0
    for item in positions if isinstance(positions, list) else []:
        position = item.get("position") if isinstance(item, dict) and isinstance(item.get("position"), dict) else item
        if isinstance(position, dict):
            unrealized += as_float(position.get("unrealizedPnl")) or 0.0
    total_exchange_event_pnl = round(
        _sum(events, "realized_trading_pnl_usd") + _sum(events, "funding_usd") + _sum(events, "fees_usd"),
        10,
    )
    cumulative_reconciliation_delta = (
        round(cumulative_net_pnl - total_exchange_event_pnl, 10)
        if cumulative_net_pnl is not None
        else None
    )
    reconciliation_status = "unavailable" if cumulative_reconciliation_delta is None else ("ok" if abs(cumulative_reconciliation_delta) <= 0.05 else "warning")
    return {
        "ledger_type": "hyperliquid_real_account_performance_ledger", "version": 1, "account_address": account_address,
        "generated_at_utc": utc_now_iso(), "source_complete": all(key in latest_raw for key in ("userFillsByTime", "userFunding", "userNonFundingLedgerUpdates")),
        "missing_sources": [key for key in ("userFillsByTime", "userFunding", "userNonFundingLedgerUpdates") if key not in latest_raw],
        "reconciliation_status": reconciliation_status, "events": events, "equity_valuations": valuations, "daily": daily,
        "live_genesis_date": days[0] if days else None, "history_days": history_days,
        "current": {**current, "unrealized_pnl_usd": round(unrealized, 10), "pnl_since_inception_usd": cumulative_net_pnl, "return_since_inception_pct": inception_return["value_pct"], "return_since_inception_available": inception_return["available"], "return_since_inception_reason": inception_return["reason"], "trading_pnl_since_inception_usd": _sum(events, "realized_trading_pnl_usd"), "fees_since_inception_usd": _sum(events, "fees_usd"), "funding_since_inception_usd": _sum(events, "funding_usd"), "deposits_since_inception_usd": _sum(events, "deposits_usd"), "withdrawals_since_inception_usd": _sum(events, "withdrawals_usd"), "exchange_event_pnl_since_inception_usd": total_exchange_event_pnl, "cumulative_equity_event_reconciliation_delta_usd": cumulative_reconciliation_delta},
        "windows": windows,
        "source_fields": {
            "equity": "clearinghouseState.marginSummary.accountValue or spotClearinghouseState stable balance", "external_cash_flows": "userNonFundingLedgerUpdates.delta.type/usdc", "fills_fees_realized": "userFillsByTime.closedPnl/fee", "funding": "userFunding.usdc", "unrealized": "clearinghouseState.assetPositions[].position.unrealizedPnl"
        },
    }


def load_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the read-only Hyperliquid real-account performance ledger.")
    parser.add_argument("--snapshot-path", type=Path, default=SNAPSHOT_PATH)
    parser.add_argument("--ledger-path", type=Path, default=LEDGER_PATH)
    args = parser.parse_args(argv)
    snapshot = load_json_optional(args.snapshot_path)
    if snapshot is None:
        raise SystemExit(f"Missing or invalid Hyperliquid snapshot: {args.snapshot_path}")
    existing = load_json_optional(args.ledger_path)
    ledger = build_ledger(snapshot, existing)
    args.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    args.ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    quality = {"ledger_ok": True, "source_complete": ledger["source_complete"], "reconciliation_status": ledger["reconciliation_status"], "history_days": ledger["history_days"], "live_genesis_date": ledger["live_genesis_date"]}
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps({"artifact_name": ledger["ledger_type"], "generated_at_utc": ledger["generated_at_utc"], "script_path": str(Path(__file__).resolve()), "input_snapshot_path": str(args.snapshot_path.resolve()), "output_path": str(args.ledger_path.resolve()), "status": "success"}, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
