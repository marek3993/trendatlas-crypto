from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


HOMEPAGE_HELD_STATE_COLUMN_PRIORITY = (
    "portfolio_held_asset",
    "held_asset_public",
    "execution_state",
    "held_asset",
    "state",
)


def _normalize_state_token(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"NAN", "NONE", "NULL"}:
        return ""
    return text


def _select_held_state_column(frame: pd.DataFrame) -> str | None:
    for column in HOMEPAGE_HELD_STATE_COLUMN_PRIORITY:
        if column not in frame.columns:
            continue
        normalized = frame[column].map(_normalize_state_token)
        if bool((normalized != "").any()):
            return column
    return None


def derive_homepage_operational_metrics_from_frame(
    frame: pd.DataFrame,
    *,
    source_path: str | Path | None = None,
) -> dict[str, Any] | None:
    if frame.empty:
        return {}

    held_state_column = _select_held_state_column(frame)
    if not held_state_column:
        return {}

    held_state_series = frame[held_state_column].map(_normalize_state_token).tolist()
    non_empty_held_state_series = [state for state in held_state_series if state]
    if not non_empty_held_state_series:
        return {}

    switch_count = 0
    prev_state: str | None = None
    for state in non_empty_held_state_series:
        if prev_state is not None and state != prev_state:
            switch_count += 1
        prev_state = state

    row_count = len(non_empty_held_state_series)
    cash_days_pct = round(
        float(sum(1 for state in non_empty_held_state_series if state == "CASH") / row_count * 100.0),
        4,
    )
    btc_days_pct = round(
        float(sum(1 for state in non_empty_held_state_series if state == "BTC") / row_count * 100.0),
        4,
    )
    return {
        "held_state_column": held_state_column,
        "held_state_column_priority": list(HOMEPAGE_HELD_STATE_COLUMN_PRIORITY),
        "held_state_series_semantics": "homepage_current_main_strategy_held_state_history",
        "operational_metrics_source_path": None if source_path is None else str(Path(source_path)),
        "held_state_total_rows": len(held_state_series),
        "held_state_non_empty_rows": row_count,
        "held_state_denominator_rows": row_count,
        "held_state_last_value": non_empty_held_state_series[-1],
        "switch_count": switch_count,
        "cash_days_pct": cash_days_pct,
        "btc_days_pct": btc_days_pct,
    }


def derive_homepage_operational_metrics_from_paper(path: str | Path) -> dict[str, Any] | None:
    csv_path = Path(path)
    if not csv_path.exists() or not csv_path.is_file():
        return {}
    frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    return derive_homepage_operational_metrics_from_frame(frame, source_path=csv_path)


def derive_strategy_day_metrics_from_frame(
    frame: pd.DataFrame,
    *,
    model: str | None = None,
) -> dict[str, float] | None:
    del model
    derived = derive_homepage_operational_metrics_from_frame(frame)
    if derived is None or not derived:
        return derived
    return {
        "cash_days_pct": float(derived["cash_days_pct"]),
        "btc_days_pct": float(derived["btc_days_pct"]),
    }


def derive_strategy_day_metrics_from_csv(
    path: str | Path,
    *,
    model: str | None = None,
) -> dict[str, float] | None:
    derived = derive_homepage_operational_metrics_from_paper(path)
    if derived is None or not derived:
        return derived
    del model
    return {
        "cash_days_pct": float(derived["cash_days_pct"]),
        "btc_days_pct": float(derived["btc_days_pct"]),
    }
