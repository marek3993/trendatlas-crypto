from __future__ import annotations

from typing import Any

import pandas as pd

try:
    from dev_only_phase68g_etf_flow_impulse_probe import to_bool_series
except ImportError:
    from scripts.dev_only_phase68g_etf_flow_impulse_probe import to_bool_series


EARLY_RISK_WEIGHT = 0.5


def build_cooldown_state_machine(
    frame: pd.DataFrame,
    cooldown_days: int,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    out = frame.copy()

    probe_states: list[str] = []
    probe_window_ids: list[str] = []
    probe_exit_reasons: list[str] = []
    baseline_handoff_day: list[bool] = []
    early_risk_active_flags: list[bool] = []
    cooldown_active_flags: list[bool] = []
    cooldown_blocked_entry_flags: list[bool] = []
    cooldown_event_ids: list[str] = []

    early_active = False
    current_window_id = ""
    window_counter = 0

    cooldown_start_date: pd.Timestamp | None = None
    cooldown_end_date: pd.Timestamp | None = None
    active_cooldown_event_index: int | None = None
    cooldown_events: list[dict[str, Any]] = []

    def clear_cooldown(
        clear_trigger_date: pd.Timestamp | None,
        clear_reason: str,
        baseline_clear: bool,
    ) -> None:
        nonlocal active_cooldown_event_index, cooldown_end_date, cooldown_start_date
        if active_cooldown_event_index is None:
            cooldown_start_date = None
            cooldown_end_date = None
            return

        event = cooldown_events[active_cooldown_event_index]
        if (
            clear_trigger_date is not None
            and cooldown_start_date is not None
            and clear_trigger_date > cooldown_start_date
        ):
            actual_last_active_date = min(
                clear_trigger_date - pd.Timedelta(days=1),
                cooldown_end_date,
            )
        else:
            actual_last_active_date = None

        if (
            actual_last_active_date is not None
            and actual_last_active_date >= event["cooldown_start_date"]
        ):
            event["actual_last_active_date"] = actual_last_active_date.strftime("%Y-%m-%d")
        else:
            event["actual_last_active_date"] = ""

        event["clear_trigger_date"] = (
            ""
            if clear_trigger_date is None
            else clear_trigger_date.strftime("%Y-%m-%d")
        )
        event["clear_reason"] = clear_reason
        event["cleared_by_baseline_full_risk_flag"] = baseline_clear
        event["blocked_entry_dates"] = ",".join(event["blocked_entry_dates"])

        cooldown_start_date = None
        cooldown_end_date = None
        active_cooldown_event_index = None

    for date_value, row in out.iterrows():
        current_date = pd.Timestamp(date_value)

        if (
            active_cooldown_event_index is not None
            and cooldown_end_date is not None
            and current_date > cooldown_end_date
        ):
            clear_cooldown(
                clear_trigger_date=cooldown_end_date + pd.Timedelta(days=1),
                clear_reason="scheduled_expiry",
                baseline_clear=False,
            )

        baseline_cash = bool(row["baseline_cash"])
        hard_invalidation_on = bool(row["hard_invalidation_on"])
        price_filter_pass = bool(row["btc_price_filter_pass"])
        flow_two_of_three_positive = bool(row["flow_2_of_last_3_positive_flag"])
        permission_on = bool(row["permission_on"])

        exit_reason = ""
        row_window_id = ""
        cooldown_active_today = False
        cooldown_blocked_today = False
        cooldown_event_id_today = ""

        if early_active and not baseline_cash:
            state = "FULL_RISK"
            row_window_id = current_window_id
            exit_reason = "baseline_full_risk_handoff"
            early_active = False
            clear_cooldown(
                clear_trigger_date=current_date,
                clear_reason="baseline_full_risk_clear",
                baseline_clear=True,
            )
        elif early_active and not flow_two_of_three_positive:
            state = "CASH"
            row_window_id = current_window_id
            exit_reason = "flow_2_of_3_not_positive"
            early_active = False
        elif early_active and not price_filter_pass:
            state = "CASH"
            row_window_id = current_window_id
            exit_reason = "btc_price_filter_failed"
            early_active = False
        elif early_active and hard_invalidation_on:
            state = "CASH"
            row_window_id = current_window_id
            exit_reason = "hard_invalidation_on"
            early_active = False
        elif early_active:
            state = "EARLY_RISK"
            row_window_id = current_window_id
        elif baseline_cash:
            if (
                active_cooldown_event_index is not None
                and cooldown_start_date is not None
                and cooldown_end_date is not None
                and cooldown_start_date <= current_date <= cooldown_end_date
            ):
                cooldown_active_today = True
                cooldown_event_id_today = str(
                    cooldown_events[active_cooldown_event_index]["cooldown_event_id"]
                )
                cooldown_events[active_cooldown_event_index]["cooldown_active_days_observed"] += 1
                if permission_on:
                    cooldown_blocked_today = True
                    cooldown_events[active_cooldown_event_index]["cooldown_blocked_entry_days"] += 1
                    cooldown_events[active_cooldown_event_index]["blocked_entry_dates"].append(
                        current_date.strftime("%Y-%m-%d")
                    )

            if not cooldown_active_today and permission_on:
                window_counter += 1
                current_window_id = f"window_{window_counter:03d}"
                state = "EARLY_RISK"
                row_window_id = current_window_id
                early_active = True
            else:
                state = "CASH"
        else:
            state = "FULL_RISK"
            clear_cooldown(
                clear_trigger_date=current_date,
                clear_reason="baseline_full_risk_clear",
                baseline_clear=True,
            )

        if exit_reason and exit_reason != "baseline_full_risk_handoff":
            event_id = f"cooldown_{len(cooldown_events) + 1:03d}"
            cooldown_start_date = current_date + pd.Timedelta(days=1)
            cooldown_end_date = current_date + pd.Timedelta(days=cooldown_days)
            cooldown_events.append(
                {
                    "cooldown_event_id": event_id,
                    "failed_window_id": current_window_id,
                    "failed_exit_date": current_date.strftime("%Y-%m-%d"),
                    "failed_exit_reason": exit_reason,
                    "cooldown_start_date": cooldown_start_date,
                    "scheduled_cooldown_end_date": cooldown_end_date,
                    "actual_last_active_date": "",
                    "clear_trigger_date": "",
                    "clear_reason": "",
                    "cleared_by_baseline_full_risk_flag": False,
                    "cooldown_active_days_observed": 0,
                    "cooldown_blocked_entry_days": 0,
                    "blocked_entry_dates": [],
                }
            )
            active_cooldown_event_index = len(cooldown_events) - 1

        probe_states.append(state)
        probe_window_ids.append(row_window_id)
        probe_exit_reasons.append(exit_reason)
        baseline_handoff_day.append(exit_reason == "baseline_full_risk_handoff")
        early_risk_active_flags.append(state == "EARLY_RISK")
        cooldown_active_flags.append(cooldown_active_today)
        cooldown_blocked_entry_flags.append(cooldown_blocked_today)
        cooldown_event_ids.append(cooldown_event_id_today)

        if exit_reason:
            current_window_id = ""

    if active_cooldown_event_index is not None:
        dataset_end = pd.Timestamp(out.index.max())
        if cooldown_start_date is not None and dataset_end < cooldown_start_date:
            clear_cooldown(
                clear_trigger_date=None,
                clear_reason="not_started_by_dataset_end",
                baseline_clear=False,
            )
        else:
            clear_cooldown(
                clear_trigger_date=dataset_end + pd.Timedelta(days=1),
                clear_reason="dataset_end",
                baseline_clear=False,
            )

    for event in cooldown_events:
        if isinstance(event["cooldown_start_date"], pd.Timestamp):
            event["cooldown_start_date"] = event["cooldown_start_date"].strftime("%Y-%m-%d")
        if isinstance(event["scheduled_cooldown_end_date"], pd.Timestamp):
            event["scheduled_cooldown_end_date"] = event["scheduled_cooldown_end_date"].strftime(
                "%Y-%m-%d"
            )
        if isinstance(event["blocked_entry_dates"], list):
            event["blocked_entry_dates"] = ",".join(event["blocked_entry_dates"])

    out["probe_state"] = probe_states
    out["probe_window_id"] = probe_window_ids
    out["probe_exit_reason"] = probe_exit_reasons
    out["baseline_handoff_day"] = baseline_handoff_day
    out["early_risk_active"] = early_risk_active_flags
    out["cooldown_active"] = cooldown_active_flags
    out["cooldown_blocked_entry"] = cooldown_blocked_entry_flags
    out["cooldown_event_id"] = cooldown_event_ids
    out["probe_held_asset"] = out["portfolio_held_asset"]
    out.loc[out["probe_state"].eq("EARLY_RISK"), "probe_held_asset"] = "BTC"
    out.loc[out["probe_state"].eq("CASH"), "probe_held_asset"] = "CASH"
    out["probe_effective_leverage"] = out["effective_leverage"]
    out.loc[out["probe_state"].eq("EARLY_RISK"), "probe_effective_leverage"] = EARLY_RISK_WEIGHT
    out.loc[out["probe_state"].eq("CASH"), "probe_effective_leverage"] = 0.0
    out["probe_strategy_return_gross"] = out["realistic_ret_gross"].astype(float)
    out.loc[
        out["probe_state"].eq("EARLY_RISK"),
        "probe_strategy_return_gross",
    ] = out.loc[out["probe_state"].eq("EARLY_RISK"), "btc_return"].fillna(0.0).astype(float) * EARLY_RISK_WEIGHT
    out.loc[out["probe_state"].eq("CASH"), "probe_strategy_return_gross"] = 0.0

    return out, cooldown_events


def decorate_cooldown_events(
    cooldown_events: list[dict[str, Any]],
    variant_def: dict[str, Any],
) -> list[dict[str, Any]]:
    return [{**variant_def, **event} for event in cooldown_events]


def build_blocker_rows(
    frame: pd.DataFrame,
    variant_def: dict[str, Any],
) -> list[dict[str, Any]]:
    periods = (
        ("full_etf_overlap", None),
        ("since2025", "2025-01-01"),
    )
    indexed = frame.copy()
    if not isinstance(indexed.index, pd.DatetimeIndex):
        if "date" in indexed.columns:
            indexed.index = pd.to_datetime(indexed["date"], errors="coerce")
        else:
            return []
    indexed = indexed.loc[indexed.index.notna()].copy()

    rows: list[dict[str, Any]] = []
    for period_name, start_date in periods:
        period_frame = indexed if start_date is None else indexed.loc[indexed.index >= pd.Timestamp(start_date)]
        if period_frame.empty:
            continue
        rows.append(
            {
                "variant_id": str(variant_def.get("variant_id") or ""),
                "model_id": str(variant_def.get("model_id") or ""),
                "cooldown_days": int(variant_def.get("cooldown_days") or 0),
                "period": period_name,
                "period_start": pd.Timestamp(period_frame.index.min()).strftime("%Y-%m-%d"),
                "period_end": pd.Timestamp(period_frame.index.max()).strftime("%Y-%m-%d"),
                "baseline_not_cash": int((~to_bool_series(period_frame["baseline_cash"])).sum()),
                "etf_flow_not_ready": int((~to_bool_series(period_frame["probe_input_ready_flag"])).sum()),
                "flow_2_of_3_not_positive": int(
                    (~to_bool_series(period_frame["flow_2_of_last_3_positive_flag"])).sum()
                ),
                "flow_3d_sum_below_floor": int((~to_bool_series(period_frame["flow_3d_sum_pass"])).sum()),
                "btc_price_filter_failed": int(
                    (~to_bool_series(period_frame["btc_price_filter_pass"])).sum()
                ),
                "hard_invalidation_on": int(to_bool_series(period_frame["hard_invalidation_on"]).sum()),
                "permission_on_but_baseline_already_full_risk": int(
                    to_bool_series(period_frame["permission_on_while_baseline_full_risk"]).sum()
                ),
                "cooldown_active_days": int(to_bool_series(period_frame["cooldown_active"]).sum()),
                "cooldown_blocked_entry_days": int(
                    to_bool_series(period_frame["cooldown_blocked_entry"]).sum()
                ),
            }
        )
    return rows


def select_recent_useful_window(
    activation_windows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not activation_windows:
        return None

    viable = [row for row in activation_windows if not bool(row.get("false_start", False))]
    if not viable:
        return None

    positive = [
        row
        for row in viable
        if float(row.get("net_contribution_pct_vs_baseline", 0.0) or 0.0) > 0.0
    ]
    pool = positive or viable
    return max(
        pool,
        key=lambda row: str(row.get("end_date") or row.get("start_date") or ""),
    )
