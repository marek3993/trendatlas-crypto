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
PHASE68G_ACTIVE_MODEL = "phase68g_66g_1p25x_candidate"
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


def _is_explicit_cash_token(token: str) -> bool:
    return bool(token) and token in CASH_EQUIVALENT_ASSETS


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


def resolve_phase68g_day_metric_state(row: pd.Series) -> str:
    if _as_bool(row.get("cash_day")) is True:
        return "CASH"

    portfolio_token = _normalize_asset_token(row.get("portfolio_held_asset"))
    if _is_explicit_cash_token(portfolio_token):
        return "CASH"
    if portfolio_token == "BTC":
        return "BTC"
    if portfolio_token and portfolio_token not in UNSUPPORTED_PROXY_ASSETS:
        return "OTHER"

    if _as_bool(row.get("use_baseline_exposure")) is True:
        baseline_token = _normalize_asset_token(row.get("baseline_held_asset"))
        if _is_explicit_cash_token(baseline_token):
            return "CASH"
        if baseline_token in {"BTC", "BASELINE_RISK"}:
            return "BTC"
        if baseline_token and baseline_token not in UNSUPPORTED_PROXY_ASSETS:
            return "OTHER"
        return "UNSUPPORTED"

    if portfolio_token in UNSUPPORTED_PROXY_ASSETS:
        return "UNSUPPORTED"

    if not portfolio_token:
        return "UNSUPPORTED"

    return "OTHER"


def derive_strategy_day_metrics_from_frame(
    frame: pd.DataFrame,
    *,
    model: str | None = None,
) -> dict[str, float] | None:
    if frame.empty:
        return {}

    relevant_columns = {"cash_day", *AUTHORITATIVE_HELD_ASSET_FIELDS}
    if not any(column in frame.columns for column in relevant_columns):
        return {}

    model_key = str(model or "").strip()
    if model_key == PHASE68G_ACTIVE_MODEL:
        day_metric_states = frame.apply(resolve_phase68g_day_metric_state, axis=1)
    else:
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


def derive_strategy_day_metrics_from_csv(
    path: str | Path,
    *,
    model: str | None = None,
) -> dict[str, float] | None:
    csv_path = Path(path)
    if not csv_path.exists() or not csv_path.is_file():
        return {}
    frame = pd.read_csv(csv_path)
    return derive_strategy_day_metrics_from_frame(frame, model=model)
