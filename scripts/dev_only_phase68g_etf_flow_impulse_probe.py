from __future__ import annotations

from typing import Any

import pandas as pd

from approved_strategy_net_export_helper import NetCostExportConfig, build_net_cost_export_frame


FLOW_3D_FLOOR_USD = 500_000_000.0
BTC_EMA_DAYS = 10


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(column).strip() for column in out.columns]
    return out


def to_bool_series(series: pd.Series) -> pd.Series:
    lowered = series.fillna("").astype(str).str.strip().str.lower()
    return lowered.isin({"1", "true", "yes", "y"})


def to_float_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def compound_return(values: pd.Series) -> float:
    return float((1.0 + to_float_series(values)).prod() - 1.0)


def count_switches(state_series: pd.Series) -> int:
    states = state_series.fillna("").astype(str)
    if states.empty:
        return 0
    prev = states.shift(1).fillna("")
    return int(states.ne(prev).sum() - (1 if states.iloc[0] != "" else 0))


def count_trade_days(weight_series: pd.Series) -> int:
    return int(to_bool_series(weight_series.astype(bool)).sum())


def load_btc_frame(path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    raw = normalize_columns(raw)
    if "date" not in raw.columns or "close" not in raw.columns:
        raise ValueError(f"{path.name}: missing date/close columns")
    out = raw.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["close"] = to_float_series(out["close"])
    out = out.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates(
        subset=["date"],
        keep="last",
    )
    out["btc_return"] = (
        out["close"]
        .pct_change()
        .replace([float("inf"), float("-inf")], pd.NA)
        .fillna(0.0)
    )
    out["btc_ema10"] = out["close"].ewm(
        span=BTC_EMA_DAYS,
        adjust=False,
        min_periods=BTC_EMA_DAYS,
    ).mean()
    out["btc_price_filter_pass"] = out["close"] > out["btc_ema10"]
    return out.set_index("date")[["close", "btc_return", "btc_ema10", "btc_price_filter_pass"]].rename(
        columns={"close": "btc_close"}
    )


def load_etf_panel(path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    raw = normalize_columns(raw)
    required = [
        "date",
        "us_trading_session_date",
        "flow_3d_sum_usd",
        "flow_2_of_last_3_positive_flag",
        "probe_input_ready_flag",
        "causal_available_for_btc_utc_day",
        "dev_only",
        "non_authoritative",
        "official_truth",
        "strategy_advancement",
    ]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing required columns {missing}")

    out = raw.copy()
    for column in ("date", "us_trading_session_date", "causal_available_for_btc_utc_day"):
        out[column] = pd.to_datetime(out[column], errors="coerce")
    out = out.dropna(subset=["date", "us_trading_session_date", "causal_available_for_btc_utc_day"])
    out = out.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    out["flow_3d_sum_usd"] = to_float_series(out["flow_3d_sum_usd"])
    out["flow_2_of_last_3_positive_flag"] = to_bool_series(out["flow_2_of_last_3_positive_flag"])
    out["probe_input_ready_flag"] = to_bool_series(out["probe_input_ready_flag"])
    out["dev_only"] = to_bool_series(out["dev_only"])
    out["non_authoritative"] = to_bool_series(out["non_authoritative"])
    out["official_truth"] = to_bool_series(out["official_truth"])
    out["strategy_advancement"] = to_bool_series(out["strategy_advancement"])
    return out.set_index("date")


def build_overlap_frame(
    baseline_df: pd.DataFrame,
    etf_df: pd.DataFrame,
    btc_df: pd.DataFrame,
) -> pd.DataFrame:
    frame = baseline_df.join(etf_df, how="inner").join(btc_df, how="inner")
    frame = frame.sort_index()
    if frame.empty:
        raise ValueError("No overlapping dates across baseline, ETF panel, and BTC causal data")

    frame["flow_3d_sum_pass"] = frame["flow_3d_sum_usd"].fillna(float("-inf")) >= FLOW_3D_FLOOR_USD
    frame["baseline_cash"] = frame["cash_day"].astype(bool)
    frame["baseline_full_risk"] = ~frame["baseline_cash"]
    frame["hard_invalidation_on"] = frame["stress_block_active"].astype(bool)
    frame["btc_price_filter_pass"] = frame["btc_price_filter_pass"].fillna(False).astype(bool)
    frame["permission_inputs_true"] = (
        frame["probe_input_ready_flag"].astype(bool)
        & frame["flow_2_of_last_3_positive_flag"].astype(bool)
        & frame["flow_3d_sum_pass"].astype(bool)
        & frame["btc_price_filter_pass"].astype(bool)
        & ~frame["hard_invalidation_on"].astype(bool)
    )
    frame["permission_on"] = frame["baseline_cash"] & frame["permission_inputs_true"]
    frame["permission_on_while_baseline_full_risk"] = (
        frame["baseline_full_risk"] & frame["permission_inputs_true"]
    )
    return frame


def build_full_history_frame(
    baseline_df: pd.DataFrame,
    etf_df: pd.DataFrame,
    btc_df: pd.DataFrame,
) -> pd.DataFrame:
    frame = baseline_df.join(btc_df, how="inner").sort_index()
    if frame.empty:
        raise ValueError("No overlapping dates across the baseline and BTC causal data")

    frame = frame.join(etf_df, how="left")
    frame["etf_flow_feature_available"] = frame["causal_available_for_btc_utc_day"].notna()
    if not bool(frame["etf_flow_feature_available"].any()):
        raise ValueError("No ETF-flow causal rows are available on the baseline date universe")

    first_evidence_date = pd.Timestamp(
        frame.index[frame["etf_flow_feature_available"]].min()
    )
    frame["etf_flow_evidence_window"] = frame.index >= first_evidence_date

    frame["flow_2_of_last_3_positive_flag"] = (
        frame["flow_2_of_last_3_positive_flag"].where(frame["etf_flow_feature_available"])
    )
    frame["probe_input_ready_flag"] = (
        frame["probe_input_ready_flag"].where(frame["etf_flow_feature_available"])
    )
    frame["dev_only"] = frame["dev_only"].where(frame["etf_flow_feature_available"])
    frame["non_authoritative"] = frame["non_authoritative"].where(
        frame["etf_flow_feature_available"]
    )
    frame["official_truth"] = frame["official_truth"].where(frame["etf_flow_feature_available"])
    frame["strategy_advancement"] = frame["strategy_advancement"].where(
        frame["etf_flow_feature_available"]
    )

    feature_mask = frame["etf_flow_feature_available"].astype(bool)
    frame["flow_2_of_last_3_positive_eval"] = (
        frame["flow_2_of_last_3_positive_flag"]
        .where(feature_mask)
        .ffill()
        .fillna(False)
        .astype(bool)
    )
    raw_flow_3d_sum = pd.to_numeric(frame["flow_3d_sum_usd"], errors="coerce")
    frame["flow_3d_sum_pass"] = raw_flow_3d_sum.fillna(float("-inf")) >= FLOW_3D_FLOOR_USD
    frame["baseline_cash"] = frame["cash_day"].astype(bool)
    frame["baseline_full_risk"] = ~frame["baseline_cash"]
    frame["hard_invalidation_on"] = frame["stress_block_active"].astype(bool)
    frame["btc_price_filter_pass"] = frame["btc_price_filter_pass"].fillna(False).astype(bool)
    frame["permission_inputs_true"] = (
        feature_mask
        & frame["probe_input_ready_flag"].fillna(False).astype(bool)
        & frame["flow_2_of_last_3_positive_flag"].fillna(False).astype(bool)
        & frame["flow_3d_sum_pass"].astype(bool)
        & frame["btc_price_filter_pass"].astype(bool)
        & ~frame["hard_invalidation_on"].astype(bool)
    )
    frame["permission_on"] = frame["baseline_cash"] & frame["permission_inputs_true"]
    frame["permission_on_while_baseline_full_risk"] = (
        frame["baseline_full_risk"] & frame["permission_inputs_true"]
    )
    return frame


def build_export_metrics(
    frame: pd.DataFrame,
    cost_cfg: NetCostExportConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline_source = frame.reset_index().rename(columns={"index": "date"}).copy()
    baseline_source["held_asset"] = baseline_source["portfolio_held_asset"]
    baseline_source["gross_return"] = baseline_source["realistic_ret_gross"]
    baseline_source["leverage"] = baseline_source["effective_leverage"]
    baseline_source["daily_borrow_cost_model"] = baseline_source.get("daily_borrow_cost", 0.0)
    baseline_source["tradable_slippage_cost_model"] = baseline_source.get(
        "tradable_slippage_cost",
        0.0,
    )

    probe_source = frame.reset_index().rename(columns={"index": "date"}).copy()
    probe_source["held_asset"] = probe_source["probe_held_asset"]
    probe_source["gross_return"] = probe_source["probe_strategy_return_gross"]
    probe_source["leverage"] = probe_source["probe_effective_leverage"]
    probe_source["daily_borrow_cost_model"] = 0.0
    probe_source["tradable_slippage_cost_model"] = 0.0
    probe_source.loc[
        probe_source["probe_state"].eq("FULL_RISK"),
        "daily_borrow_cost_model",
    ] = baseline_source["daily_borrow_cost_model"]
    probe_source.loc[
        probe_source["probe_state"].eq("FULL_RISK"),
        "tradable_slippage_cost_model",
    ] = baseline_source["tradable_slippage_cost_model"]

    prev_probe_asset = probe_source["held_asset"].shift(1).fillna("")
    prev_probe_state = probe_source["probe_state"].shift(1).fillna("")
    has_prev = prev_probe_asset.ne("")
    early_transition_cost = float(cost_cfg.tradable_transition_slippage_bps) / 10000.0
    extra_early_transition = (
        has_prev
        & probe_source["held_asset"].ne(prev_probe_asset)
        & (
            probe_source["probe_state"].eq("EARLY_RISK")
            | prev_probe_state.eq("EARLY_RISK")
        )
        & ~probe_source["probe_state"].eq("FULL_RISK")
    )
    probe_source.loc[
        extra_early_transition,
        "tradable_slippage_cost_model",
    ] = (
        probe_source.loc[extra_early_transition, "tradable_slippage_cost_model"]
        + early_transition_cost
    )

    baseline_export = build_net_cost_export_frame(
        baseline_source,
        date_col="date",
        gross_return_col="gross_return",
        held_asset_col="held_asset",
        leverage_col="leverage",
        daily_borrow_cost_col="daily_borrow_cost_model",
        tradable_slippage_cost_col="tradable_slippage_cost_model",
        config=cost_cfg,
    )
    probe_export = build_net_cost_export_frame(
        probe_source,
        date_col="date",
        gross_return_col="gross_return",
        held_asset_col="held_asset",
        leverage_col="leverage",
        daily_borrow_cost_col="daily_borrow_cost_model",
        tradable_slippage_cost_col="tradable_slippage_cost_model",
        config=cost_cfg,
    )

    baseline_export = baseline_export.set_index("date").add_prefix("baseline_")
    probe_export = probe_export.set_index("date").add_prefix("probe_")

    merged = frame.drop(
        columns=[column for column in baseline_export.columns if column in frame.columns],
        errors="ignore",
    )
    merged = merged.drop(
        columns=[column for column in probe_export.columns if column in merged.columns],
        errors="ignore",
    )
    merged = merged.join(baseline_export, how="left").join(probe_export, how="left")
    merged["baseline_state"] = merged["baseline_cash"].map({True: "CASH", False: "FULL_RISK"})

    return baseline_export, probe_export, merged


def build_activation_windows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty or "probe_state" not in frame.columns:
        return []

    indexed = frame.copy()
    if not isinstance(indexed.index, pd.DatetimeIndex):
        if "date" not in indexed.columns:
            return []
        indexed.index = pd.to_datetime(indexed["date"], errors="coerce")
    indexed = indexed.loc[indexed.index.notna()].copy()

    active_mask = indexed["probe_state"].eq("EARLY_RISK")
    if not active_mask.any():
        return []

    group_ids = active_mask.ne(active_mask.shift(1, fill_value=False)).cumsum()
    active_groups = group_ids.loc[active_mask]
    rows: list[dict[str, Any]] = []

    for window_number, (_, positions) in enumerate(active_groups.groupby(active_groups), start=1):
        date_index = list(positions.index)
        start_date = pd.Timestamp(date_index[0])
        end_date = pd.Timestamp(date_index[-1])
        window_slice = indexed.loc[start_date:end_date].copy()

        end_position = indexed.index.get_loc(end_date)
        if isinstance(end_position, slice):
            end_position = end_position.stop - 1
        next_row = indexed.iloc[end_position + 1] if end_position + 1 < len(indexed) else None
        handoff_date = None
        exit_reason = "dataset_end" if next_row is None else str(next_row.get("probe_exit_reason") or "")
        if next_row is not None and bool(next_row.get("baseline_handoff_day", False)):
            handoff_date = pd.Timestamp(indexed.index[end_position + 1])
        if not exit_reason:
            exit_reason = "still_open_at_dataset_end" if next_row is None else "unknown"

        window_id = str(window_slice.iloc[0].get("probe_window_id") or f"window_{window_number:03d}")
        bucket = "since2025" if start_date >= pd.Timestamp("2025-01-01") else "since2024"

        rows.append(
            {
                "window_id": window_id,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "baseline_handoff_date": "" if handoff_date is None else handoff_date.strftime("%Y-%m-%d"),
                "lead_days_vs_baseline_full_risk": 0
                if handoff_date is None
                else int((handoff_date - start_date).days),
                "net_contribution_pct_vs_baseline": round(
                    (
                        compound_return(window_slice["probe_net_return"])
                        - compound_return(window_slice["baseline_net_return"])
                    )
                    * 100.0,
                    6,
                ),
                "gross_contribution_pct_vs_baseline": round(
                    (
                        compound_return(window_slice["probe_gross_return"])
                        - compound_return(window_slice["baseline_gross_return"])
                    )
                    * 100.0,
                    6,
                ),
                "bucket": bucket,
                "false_start": handoff_date is None,
                "exit_reason": exit_reason,
                "early_risk_days": int(len(window_slice)),
                "entry_flow_3d_sum_usd": float(to_float_series(window_slice["flow_3d_sum_usd"]).iloc[0]),
                "entry_flow_2_of_last_3_positive_flag": bool(
                    to_bool_series(window_slice["flow_2_of_last_3_positive_flag"]).iloc[0]
                ),
                "entry_btc_close": float(to_float_series(window_slice["btc_close"]).iloc[0]),
                "entry_btc_ema10": float(to_float_series(window_slice["btc_ema10"]).iloc[0]),
            }
        )

    return rows
