from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


CASH_EQUIVALENT_ASSETS = {
    "",
    "0",
    "0.0",
    "0.00",
    "CASH",
    "USD",
    "USDT",
    "NAN",
    "NONE",
    "NULL",
}
UNSUPPORTED_PROXY_ASSETS = {
    "BASELINE_RISK",
    "EARLY_RISK",
    "FULL_RISK",
}
AUTHORITATIVE_HELD_ASSET_FIELDS = (
    "portfolio_held_asset",
    "held_asset_public",
    "held_asset",
    "tradable_governed_asset",
    "baseline_held_asset",
)


def _normalize_asset_token(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"NAN", "NONE", "NULL"}:
        return ""
    return text


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def resolve_authoritative_day_metric_state(row: pd.Series) -> str:
    if _as_bool(row.get("cash_day")) is True:
        return "CASH"

    for field in AUTHORITATIVE_HELD_ASSET_FIELDS:
        token = _normalize_asset_token(row.get(field))
        if not token:
            continue
        if token in CASH_EQUIVALENT_ASSETS:
            return "CASH"
        if token in UNSUPPORTED_PROXY_ASSETS:
            return "UNSUPPORTED"
        if token == "BTC":
            return "BTC"
        return "OTHER"

    return "OTHER"


def derive_strategy_day_metrics_from_frame(frame: pd.DataFrame) -> dict[str, float] | None:
    if frame.empty:
        return {}

    relevant_columns = {"cash_day", *AUTHORITATIVE_HELD_ASSET_FIELDS}
    if not any(column in frame.columns for column in relevant_columns):
        return {}

    day_metric_states = frame.apply(resolve_authoritative_day_metric_state, axis=1)
    if day_metric_states.empty:
        return {}
    if bool((day_metric_states == "UNSUPPORTED").any()):
        return None

    cash_days_pct = round(float((day_metric_states == "CASH").mean() * 100.0), 4)
    btc_days_pct = round(float((day_metric_states == "BTC").mean() * 100.0), 4)
    return {
        "cash_days_pct": cash_days_pct,
        "btc_days_pct": btc_days_pct,
    }


def derive_strategy_day_metrics_from_csv(path: str | Path) -> dict[str, float] | None:
    csv_path = Path(path)
    if not csv_path.exists() or not csv_path.is_file():
        return {}
    frame = pd.read_csv(csv_path)
    return derive_strategy_day_metrics_from_frame(frame)
