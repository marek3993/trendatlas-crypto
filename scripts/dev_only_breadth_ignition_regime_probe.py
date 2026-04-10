from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

import pandas as pd

import dev_only_cash_overstay_diagnostic as cash_diag
from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_breadth_ignition_regime_probe"
)

BASELINE_MODEL = "phase67j_no_neo_main"
PROBE_MODEL = "breadth_ignition_regime_probe"
MECHANISM_ID = "cross_sectional_breadth_ignition_regime"

BASELINE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / f"{BASELINE_MODEL}_paper.csv"
PHASE68I_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
PHASE68I_SUMMARY_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_summary.csv"

UNIVERSE_SYMBOLS = ["ADA", "AVAX", "BNB", "BTC", "DOGE", "DOT", "ETH", "LINK", "LTC", "SOL", "TRX", "XRP"]
MIN_ELIGIBLE_ASSETS = 8
MEDIUM_TREND_DAYS = 20
LONG_TREND_DAYS = 120
BREADTH_SMOOTHING_EWMA_SPAN_DAYS = 21
BREADTH_IGNITION_THRESHOLD = 2.0 / 3.0
IGNITION_PERSISTENCE_DAYS = 3

JSON_LOCKS = {
    "analysis_mode": "breadth_ignition_regime_probe_only",
    "candidate_selection": False,
    "official_edge_claim": False,
}

UNIVERSE_RULE = (
    "Fixed liquid core universe from data/ohlcv only: ADA, AVAX, BNB, BTC, DOGE, DOT, ETH, LINK, LTC, SOL, TRX, XRP. "
    "An asset is daily eligible only after its own 120-day moving average is available; the breadth signal is valid "
    "only when at least 8 of the 12 fixed assets are eligible."
)
BREADTH_FORMULA = (
    "For each date, breadth = count(eligible assets with close > own 120-day SMA and own 20-day SMA > own 120-day SMA) "
    "/ count(eligible assets)."
)
SMOOTHING_RULE = (
    "Smooth daily breadth with a single causal EWMA using span=21 trading days, adjust=False, and min_periods=21."
)
THRESHOLD_RULE = (
    "Breadth ignition candidate is true when the causal smoothed breadth is at least 2/3, with the fixed-universe "
    "minimum eligibility rule already satisfied."
)
PERSISTENCE_RULE = (
    "Ignition turns ON only after the threshold candidate is true for 3 consecutive available days; no pilot state, "
    "no Pilot-to-Full ladder, and no persistence exposure extension after the candidate turns false."
)
STATE_RULE = (
    "Baseline risk days remain unchanged. On baseline CASH days only, the probe enters full BTC risk when breadth "
    "ignition is ON and the existing hard BTC risk-off invalidation is false; otherwise it remains CASH."
)
WHY_DIFFERENT = {
    "soft_gate_line": "It does not soften a BTC entry gate or reuse the prior early-entry gate logic; it measures broad cross-sectional participation.",
    "persistence_line": "It does not hold exposure because a prior constructive window existed; exposure requires current smoothed breadth ignition.",
    "pre_activation_line": "It does not add an asset-specific high-conviction pre-activation sleeve; it uses fixed-universe breadth only.",
    "pilot_to_full_line": "It has no Pilot state, no Pilot-to-Full ladder, and no partial-weight state machine.",
    "l1_trend_filter_line": "It does not estimate a one-sided BTC endpoint slope; the signal comes from smoothed participation across the liquid universe.",
}
STOP_RULE = (
    "stop if breadth generalization still requires materially higher switching/churn, or if drawdown worsens materially, "
    "or if net gains disappear, or if the signal behaves like another noisy activation layer"
)

WINDOW_COMPARE_COLUMNS = [
    "window_id",
    "breadth_activation_date",
    "window_end_date",
    "baseline_handoff_date",
    "activation_kind",
    "lead_days_vs_baseline",
    "breadth_risk_days",
    "entry_breadth",
    "entry_smoothed_breadth",
    "entry_eligible_assets",
    "entry_positive_assets",
    "btc_return_gross",
    "baseline_return_gross",
    "probe_return_gross",
    "baseline_return_net",
    "probe_return_net",
    "net_early_move_capture",
    "gross_early_move_capture",
    "exit_reason",
]
STATE_TIME_COLUMNS = ["model", "state", "days", "share_of_total_days"]
COMPARE_COLUMNS = ["metric", "baseline_model", "baseline_value", "probe_model", "probe_value", "delta_probe_minus_baseline"]
COST_COLUMNS = [
    "model",
    "gross_return_pct",
    "net_return_after_costs_pct",
    "net_cagr_pct",
    "max_drawdown_pct",
    "trade_count",
    "switch_count",
    "turnover_pressure",
    "total_cost_pct",
    "breadth_risk_days",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only cross-sectional breadth ignition regime probe")
    parser.add_argument("--baseline-paper", type=str, default=str(BASELINE_PAPER_PATH))
    parser.add_argument("--phase68i-paper", type=str, default=str(PHASE68I_PAPER_PATH))
    parser.add_argument("--phase68i-summary", type=str, default=str(PHASE68I_SUMMARY_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    return {
        "summary_json": OUTPUT_ROOT / "breadth_ignition_regime_probe.summary.json",
        "window_compare_csv": OUTPUT_ROOT / "breadth_ignition_regime_probe.window_compare.csv",
        "state_time_csv": OUTPUT_ROOT / "breadth_ignition_regime_probe.state_time.csv",
        "compare_csv": OUTPUT_ROOT / "breadth_ignition_regime_probe.compare.csv",
        "cost_metrics_csv": OUTPUT_ROOT / "breadth_ignition_regime_probe.cost_metrics.csv",
        "manifest_json": OUTPUT_ROOT / "breadth_ignition_regime_probe.manifest.json",
        "quality_json": OUTPUT_ROOT / "breadth_ignition_regime_probe.quality.json",
    }


def safe_float(value: Any, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(default if pd.isna(numeric) else numeric)


def compound_return(values: pd.Series) -> float:
    return cash_diag.compound_return(values)


def compound_pct(values: pd.Series) -> float:
    return round(compound_return(values) * 100.0, 6)


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if total_return <= -1.0:
        return -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def max_drawdown_from_returns(returns: pd.Series) -> float:
    equity = (1.0 + pd.to_numeric(returns, errors="coerce").fillna(0.0)).cumprod()
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def load_phase68i_cost_assumptions(summary_path: Path, paper_path: Path) -> Dict[str, float]:
    fee_bps = 4.5
    slippage_bps = 10.0
    if summary_path.exists():
        summary_df = pd.read_csv(summary_path)
        if not summary_df.empty and "effective_trading_fee_bps" in summary_df.columns:
            fee_bps = safe_float(summary_df.iloc[0]["effective_trading_fee_bps"], fee_bps)
    if paper_path.exists():
        paper_df = pd.read_csv(paper_path)
        if not paper_df.empty and "tradable_transition_slippage_bps" in paper_df.columns:
            candidate = pd.to_numeric(paper_df["tradable_transition_slippage_bps"], errors="coerce").dropna()
            if not candidate.empty:
                slippage_bps = float(candidate.iloc[0])
    return {
        "trading_fee_bps": round(fee_bps, 6),
        "slippage_bps": round(slippage_bps, 6),
        "turnover_cost_per_unit": round((fee_bps + slippage_bps) / 10000.0, 8),
    }


def load_asset_trend_frame(asset: str) -> pd.DataFrame:
    path = cash_diag.resolve_asset_daily_path(asset)
    if not path.exists():
        raise FileNotFoundError(f"Missing OHLCV input for {asset}: {path}")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").copy()
    df["medium_ma"] = df["close"].rolling(MEDIUM_TREND_DAYS, min_periods=MEDIUM_TREND_DAYS).mean()
    df["long_ma"] = df["close"].rolling(LONG_TREND_DAYS, min_periods=LONG_TREND_DAYS).mean()
    df["breadth_eligible"] = df["long_ma"].notna()
    df["breadth_positive"] = (df["close"] > df["long_ma"]) & (df["medium_ma"] > df["long_ma"])
    return df.set_index("date")[["breadth_eligible", "breadth_positive"]]


def add_breadth_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    eligible_parts: List[pd.Series] = []
    positive_parts: List[pd.Series] = []

    for asset in UNIVERSE_SYMBOLS:
        asset_frame = load_asset_trend_frame(asset).reindex(out.index).ffill()
        eligible_parts.append(asset_frame["breadth_eligible"].fillna(False).astype(bool).rename(asset))
        positive_parts.append(asset_frame["breadth_positive"].fillna(False).astype(bool).rename(asset))

    eligible_df = pd.concat(eligible_parts, axis=1)
    positive_df = pd.concat(positive_parts, axis=1) & eligible_df
    eligible_count = eligible_df.sum(axis=1)
    positive_count = positive_df.sum(axis=1)
    breadth = (positive_count / eligible_count.where(eligible_count.gt(0))).where(eligible_count >= MIN_ELIGIBLE_ASSETS)
    smoothed = breadth.ewm(
        span=BREADTH_SMOOTHING_EWMA_SPAN_DAYS,
        adjust=False,
        min_periods=BREADTH_SMOOTHING_EWMA_SPAN_DAYS,
    ).mean()
    threshold_candidate = smoothed.ge(BREADTH_IGNITION_THRESHOLD).fillna(False)
    ignition_on = threshold_candidate.rolling(
        IGNITION_PERSISTENCE_DAYS,
        min_periods=IGNITION_PERSISTENCE_DAYS,
    ).sum().eq(IGNITION_PERSISTENCE_DAYS)

    out["breadth_eligible_assets"] = eligible_count.astype(int)
    out["breadth_positive_assets"] = positive_count.astype(int)
    out["breadth_share"] = breadth
    out["breadth_smoothed"] = smoothed
    out["breadth_threshold_candidate"] = threshold_candidate
    out["breadth_ignition_on"] = ignition_on.fillna(False)
    return out


def build_probe_frame(baseline_df: pd.DataFrame) -> pd.DataFrame:
    frame = cash_diag.build_analysis_frame(baseline_df).copy()
    frame = add_breadth_columns(frame)
    frame["baseline_cash"] = ~frame["in_market"]
    frame["breadth_hard_risk_off_block"] = frame["risk_off_invalidation_day"].fillna(False).astype(bool)
    frame["breadth_risk_on_permission"] = (
        frame["baseline_cash"] & frame["breadth_ignition_on"] & (~frame["breadth_hard_risk_off_block"])
    )

    breadth_active = False
    current_window_id = ""
    window_counter = 0

    probe_states: List[str] = []
    probe_window_ids: List[str] = []
    handoff_flags: List[bool] = []
    exit_reasons: List[str] = []
    breadth_active_flags: List[bool] = []

    for _, row in frame.iterrows():
        baseline_cash = bool(row["baseline_cash"])
        permission = bool(row["breadth_risk_on_permission"])
        exit_reason = ""
        row_window_id = ""

        if breadth_active and not baseline_cash:
            state = "BASELINE_RISK"
            row_window_id = current_window_id
            exit_reason = "baseline_handoff"
            breadth_active = False
        elif breadth_active and not permission:
            state = "CASH"
            row_window_id = current_window_id
            exit_reason = "hard_risk_off" if bool(row["breadth_hard_risk_off_block"]) else "breadth_ignition_off"
            breadth_active = False
        elif (not breadth_active) and baseline_cash and permission:
            window_counter += 1
            current_window_id = f"window_{window_counter:03d}"
            state = "BREADTH_BTC_RISK"
            row_window_id = current_window_id
            breadth_active = True
        elif breadth_active:
            state = "BREADTH_BTC_RISK"
            row_window_id = current_window_id
        elif baseline_cash:
            state = "CASH"
        else:
            state = "BASELINE_RISK"

        probe_states.append(state)
        probe_window_ids.append(row_window_id)
        handoff_flags.append(exit_reason == "baseline_handoff")
        exit_reasons.append(exit_reason)
        breadth_active_flags.append(state == "BREADTH_BTC_RISK")

        if exit_reason:
            current_window_id = ""

    frame["probe_state"] = probe_states
    frame["breadth_window_id"] = probe_window_ids
    frame["baseline_handoff_day"] = handoff_flags
    frame["probe_exit_reason"] = exit_reasons
    frame["breadth_active"] = breadth_active_flags
    frame["probe_in_market"] = frame["probe_state"].ne("CASH")
    frame["probe_strategy_return_gross"] = pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)
    frame.loc[frame["breadth_active"], "probe_strategy_return_gross"] = pd.to_numeric(
        frame.loc[frame["breadth_active"], "benchmark_return"], errors="coerce"
    ).fillna(0.0)
    return frame


def apply_cost_model(frame: pd.DataFrame, cost_cfg: Dict[str, float]) -> pd.DataFrame:
    out = frame.copy()
    baseline_weight = out["in_market"].astype(float)
    probe_weight = out["probe_in_market"].astype(float)
    out["baseline_exposure_weight"] = baseline_weight
    out["probe_exposure_weight"] = probe_weight
    out["baseline_turnover"] = baseline_weight.diff().abs().fillna(abs(float(baseline_weight.iloc[0])))
    out["probe_turnover"] = probe_weight.diff().abs().fillna(abs(float(probe_weight.iloc[0])))
    turnover_cost = float(cost_cfg["turnover_cost_per_unit"])
    out["baseline_cost"] = out["baseline_turnover"] * turnover_cost
    out["probe_cost"] = out["probe_turnover"] * turnover_cost
    out["baseline_strategy_return_net"] = pd.to_numeric(out["strategy_return"], errors="coerce").fillna(0.0) - out[
        "baseline_cost"
    ]
    out["probe_strategy_return_net"] = out["probe_strategy_return_gross"] - out["probe_cost"]
    return out


def build_activation_windows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    active_ids = [value for value in frame["breadth_window_id"].dropna().unique().tolist() if str(value).strip()]
    for window_id in active_ids:
        window_df = frame.loc[frame["breadth_window_id"].eq(window_id)].copy()
        active_df = window_df.loc[window_df["breadth_active"]]
        if active_df.empty:
            continue
        start_date = pd.Timestamp(active_df.index.min())
        handoff_rows = window_df.loc[window_df["baseline_handoff_day"]]
        exit_rows = window_df.loc[window_df["probe_exit_reason"].ne("")]
        handoff_date = pd.Timestamp(handoff_rows.index.min()) if not handoff_rows.empty else None
        if handoff_date is not None:
            end_date = handoff_date - pd.Timedelta(days=1)
            exit_reason = "baseline_handoff"
        elif not exit_rows.empty:
            end_date = pd.Timestamp(exit_rows.index.min()) - pd.Timedelta(days=1)
            exit_reason = str(exit_rows.iloc[0]["probe_exit_reason"])
        else:
            end_date = pd.Timestamp(active_df.index.max())
            exit_reason = "still_open_at_dataset_end"

        if end_date < start_date:
            end_date = start_date
        window_slice = frame.loc[start_date:end_date].copy()
        entry = frame.loc[start_date]
        baseline_return_net = compound_pct(window_slice["baseline_strategy_return_net"])
        probe_return_net = compound_pct(window_slice["probe_strategy_return_net"])
        baseline_return_gross = compound_pct(window_slice["strategy_return"])
        probe_return_gross = compound_pct(window_slice["probe_strategy_return_gross"])
        btc_return_gross = compound_pct(window_slice["benchmark_return"])

        rows.append(
            {
                "window_id": window_id,
                "breadth_activation_date": start_date.strftime("%Y-%m-%d"),
                "window_end_date": end_date.strftime("%Y-%m-%d"),
                "baseline_handoff_date": "" if handoff_date is None else handoff_date.strftime("%Y-%m-%d"),
                "activation_kind": "cross_sectional_breadth_ignition",
                "lead_days_vs_baseline": 0 if handoff_date is None else int((handoff_date - start_date).days),
                "breadth_risk_days": int(window_slice["breadth_active"].sum()),
                "entry_breadth": round(safe_float(entry["breadth_share"]), 6),
                "entry_smoothed_breadth": round(safe_float(entry["breadth_smoothed"]), 6),
                "entry_eligible_assets": int(safe_float(entry["breadth_eligible_assets"], 0.0)),
                "entry_positive_assets": int(safe_float(entry["breadth_positive_assets"], 0.0)),
                "btc_return_gross": btc_return_gross,
                "baseline_return_gross": baseline_return_gross,
                "probe_return_gross": probe_return_gross,
                "baseline_return_net": baseline_return_net,
                "probe_return_net": probe_return_net,
                "net_early_move_capture": round(probe_return_net - baseline_return_net, 6),
                "gross_early_move_capture": round(probe_return_gross - baseline_return_gross, 6),
                "exit_reason": exit_reason,
            }
        )
    return rows


def build_state_time_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    total_days = int(len(frame))
    specs = [
        (BASELINE_MODEL, "BASELINE_RISK", int(frame["in_market"].sum())),
        (BASELINE_MODEL, "CASH", int((~frame["in_market"]).sum())),
        (PROBE_MODEL, "BASELINE_RISK", int(frame["probe_state"].eq("BASELINE_RISK").sum())),
        (PROBE_MODEL, "BREADTH_BTC_RISK", int(frame["probe_state"].eq("BREADTH_BTC_RISK").sum())),
        (PROBE_MODEL, "CASH", int(frame["probe_state"].eq("CASH").sum())),
    ]
    return [
        {
            "model": model,
            "state": state,
            "days": days,
            "share_of_total_days": round(days / total_days, 6) if total_days else 0.0,
        }
        for model, state, days in specs
    ]


def count_trade_days(weight_series: pd.Series) -> int:
    return int(weight_series.diff().abs().fillna(abs(float(weight_series.iloc[0]))).gt(0.0).sum())


def count_switches(state_series: pd.Series) -> int:
    series = state_series.astype(str)
    if series.empty:
        return 0
    return int(series.ne(series.shift(1)).sum() - 1)


def calc_metrics(
    returns_gross: pd.Series,
    returns_net: pd.Series,
    state_series: pd.Series,
    weight_series: pd.Series,
    *,
    model: str,
    breadth_risk_days: int,
) -> Dict[str, Any]:
    gross_total_return = compound_return(returns_gross)
    net_total_return = compound_return(returns_net)
    net_cagr = annualize_return(net_total_return, len(returns_net))
    max_dd = max_drawdown_from_returns(returns_net)
    total_cost_pct = round(
        (
            pd.to_numeric(returns_gross, errors="coerce").fillna(0.0)
            - pd.to_numeric(returns_net, errors="coerce").fillna(0.0)
        ).sum()
        * 100.0,
        6,
    )
    turnover_pressure = round(weight_series.diff().abs().fillna(abs(float(weight_series.iloc[0]))).sum(), 6)
    return {
        "model": model,
        "gross_return_pct": round(gross_total_return * 100.0, 6),
        "net_return_after_costs_pct": round(net_total_return * 100.0, 6),
        "net_cagr_pct": round(net_cagr * 100.0, 6),
        "max_drawdown_pct": round(max_dd * 100.0, 6),
        "trade_count": int(count_trade_days(weight_series)),
        "switch_count": int(count_switches(state_series)),
        "turnover_pressure": turnover_pressure,
        "total_cost_pct": total_cost_pct,
        "breadth_risk_days": int(breadth_risk_days),
    }


def valid_handoff_windows(activation_windows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in activation_windows if str(row["baseline_handoff_date"]).strip()]


def build_compare_rows(
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    valid_windows = valid_handoff_windows(activation_windows)
    lead_days = [int(row["lead_days_vs_baseline"]) for row in valid_windows]
    net_capture = sum(float(row["net_early_move_capture"]) for row in activation_windows)
    gross_capture = sum(float(row["gross_early_move_capture"]) for row in activation_windows)
    metrics = [
        ("number_of_earlier_activation_windows", 0.0, float(len(valid_windows))),
        ("avg_lead_days_vs_baseline", 0.0, float(sum(lead_days) / len(lead_days)) if lead_days else 0.0),
        ("median_lead_days_vs_baseline", 0.0, float(median(lead_days)) if lead_days else 0.0),
        ("max_lead_days_vs_baseline", 0.0, float(max(lead_days)) if lead_days else 0.0),
        ("net_early_move_capture_pct", 0.0, net_capture),
        ("gross_early_move_capture_pct", 0.0, gross_capture),
        ("trade_count", baseline_metrics["trade_count"], probe_metrics["trade_count"]),
        ("switch_count", baseline_metrics["switch_count"], probe_metrics["switch_count"]),
        ("turnover_pressure", baseline_metrics["turnover_pressure"], probe_metrics["turnover_pressure"]),
        ("net_max_drawdown_pct", baseline_metrics["max_drawdown_pct"], probe_metrics["max_drawdown_pct"]),
        ("net_total_return_pct", baseline_metrics["net_return_after_costs_pct"], probe_metrics["net_return_after_costs_pct"]),
        ("net_cagr_pct", baseline_metrics["net_cagr_pct"], probe_metrics["net_cagr_pct"]),
        ("gross_total_return_pct", baseline_metrics["gross_return_pct"], probe_metrics["gross_return_pct"]),
        ("breadth_risk_days", baseline_metrics["breadth_risk_days"], probe_metrics["breadth_risk_days"]),
    ]
    return [
        {
            "metric": metric,
            "baseline_model": BASELINE_MODEL,
            "baseline_value": float(baseline_value),
            "probe_model": PROBE_MODEL,
            "probe_value": float(probe_value),
            "delta_probe_minus_baseline": float(probe_value) - float(baseline_value),
        }
        for metric, baseline_value, probe_value in metrics
    ]


def build_summary_payload(
    *,
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
    cost_cfg: Dict[str, float],
    input_refs: Dict[str, Any],
) -> Dict[str, Any]:
    valid_windows = valid_handoff_windows(activation_windows)
    lead_days = [int(row["lead_days_vs_baseline"]) for row in valid_windows]
    net_capture = round(sum(float(row["net_early_move_capture"]) for row in activation_windows), 6)
    gross_capture = round(sum(float(row["gross_early_move_capture"]) for row in activation_windows), 6)
    trade_delta = int(probe_metrics["trade_count"] - baseline_metrics["trade_count"])
    switch_delta = int(probe_metrics["switch_count"] - baseline_metrics["switch_count"])
    turnover_delta = round(float(probe_metrics["turnover_pressure"] - baseline_metrics["turnover_pressure"]), 6)
    dd_delta = round(float(probe_metrics["max_drawdown_pct"] - baseline_metrics["max_drawdown_pct"]), 6)
    net_delta = round(float(probe_metrics["net_return_after_costs_pct"] - baseline_metrics["net_return_after_costs_pct"]), 6)
    cagr_delta = round(float(probe_metrics["net_cagr_pct"] - baseline_metrics["net_cagr_pct"]), 6)
    gross_delta = round(float(probe_metrics["gross_return_pct"] - baseline_metrics["gross_return_pct"]), 6)

    earlier_activation_ok = len(valid_windows) > 1
    churn_ok = trade_delta <= 3 and switch_delta <= 3 and turnover_delta <= 3.0
    dd_ok = dd_delta >= -1.0
    net_ok = net_delta > 0.0 and net_capture > 0.0
    stop_triggered = (not earlier_activation_ok) or (not churn_ok) or (not dd_ok) or (not net_ok)
    final_verdict = "stop_condition_triggered" if stop_triggered else "continue_dev_only"

    return with_json_locks(
        {
            "artifact_id": "breadth_ignition_regime_probe",
            "generated_at_utc": timestamp_utc(),
            "final_verdict": final_verdict,
            "mechanism_id": MECHANISM_ID,
            "compare_baseline": BASELINE_MODEL,
            "secondary_context_only": "phase68i_dynamic_ladder_candidate",
            "number_of_earlier_activation_windows": int(len(valid_windows)),
            "lead_days_vs_baseline": {
                "all_valid_handoff_windows": lead_days,
                "avg": round(float(sum(lead_days) / len(lead_days)), 6) if lead_days else 0.0,
                "median": round(float(median(lead_days)), 6) if lead_days else 0.0,
                "max": int(max(lead_days)) if lead_days else 0,
            },
            "net_early_move_capture_pct": net_capture,
            "trade_days_delta": trade_delta,
            "switch_count_delta": switch_delta,
            "turnover_pressure_delta": turnover_delta,
            "net_max_drawdown_delta_pct": dd_delta,
            "net_total_return_delta_pct": net_delta,
            "net_cagr_delta_pct": cagr_delta,
            "gross_metrics_context": {
                "gross_early_move_capture_pct": gross_capture,
                "gross_total_return_baseline_pct": round(float(baseline_metrics["gross_return_pct"]), 6),
                "gross_total_return_probe_pct": round(float(probe_metrics["gross_return_pct"]), 6),
                "gross_total_return_delta_pct": gross_delta,
            },
            "baseline_metrics": baseline_metrics,
            "probe_metrics": probe_metrics,
            "exact_state_regime_rule": STATE_RULE,
            "exact_universe_definition_used": UNIVERSE_RULE,
            "exact_breadth_formula_used": BREADTH_FORMULA,
            "exact_smoothing_rule_used": SMOOTHING_RULE,
            "exact_threshold_rule_used": THRESHOLD_RULE,
            "exact_persistence_rule_used": PERSISTENCE_RULE,
            "exact_why_materially_different": WHY_DIFFERENT,
            "cost_model": {
                "source_context": "phase68i dynamic ladder export fee/slippage fields used only as secondary cost assumptions",
                "trading_fee_bps": cost_cfg["trading_fee_bps"],
                "slippage_bps": cost_cfg["slippage_bps"],
                "turnover_cost_per_unit": cost_cfg["turnover_cost_per_unit"],
            },
            "stop_condition": {
                "rule": STOP_RULE,
                "triggered": bool(stop_triggered),
                "components": {
                    "earlier_activation_ok": bool(earlier_activation_ok),
                    "churn_ok": bool(churn_ok),
                    "drawdown_ok": bool(dd_ok),
                    "net_ok": bool(net_ok),
                },
            },
            "input_refs": input_refs,
            "status": "generated_dev_only_breadth_ignition_regime_probe_summary",
        }
    )


def build_manifest_payload(paths: Dict[str, Path], input_refs: Dict[str, Any]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": "breadth_ignition_regime_probe_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(value) for key, value in paths.items()},
            "input_refs": input_refs,
            "contract_refs": [
                "research_os/dev_only/contracts/dev_only_breadth_ignition_regime_probe.contract.json"
            ],
            "spec_refs": [
                "research_os/dev_only/specs/dev_only_breadth_ignition_regime_probe.spec.json"
            ],
            "manifest_seed_refs": [
                "research_os/dev_only/manifests/dev_only_breadth_ignition_regime_probe.manifest.json"
            ],
            "status": "implementation_pack_ready",
        }
    )


def build_quality_payload(
    frame: pd.DataFrame,
    baseline_metrics: Dict[str, Any],
    probe_metrics: Dict[str, Any],
    activation_windows: List[Dict[str, Any]],
    input_refs: Dict[str, Any],
) -> Dict[str, Any]:
    first_smoothed_idx = frame["breadth_smoothed"].first_valid_index()
    pre_smoothed_ok = True
    if first_smoothed_idx is not None:
        pre_smoothed_ok = not bool(frame.loc[frame.index < first_smoothed_idx, "breadth_ignition_on"].any())
    checks = [
        {
            "name": "fixed_universe_size",
            "ok": len(UNIVERSE_SYMBOLS) == 12 and len(set(UNIVERSE_SYMBOLS)) == len(UNIVERSE_SYMBOLS),
            "detail": ",".join(UNIVERSE_SYMBOLS),
        },
        {
            "name": "single_breadth_formula_recorded",
            "ok": bool(BREADTH_FORMULA),
            "detail": BREADTH_FORMULA,
        },
        {
            "name": "single_smoothing_rule_recorded",
            "ok": bool(SMOOTHING_RULE),
            "detail": SMOOTHING_RULE,
        },
        {
            "name": "single_threshold_rule_recorded",
            "ok": bool(THRESHOLD_RULE),
            "detail": THRESHOLD_RULE,
        },
        {
            "name": "short_persistence_before_signal",
            "ok": pre_smoothed_ok,
            "detail": "breadth ignition cannot turn on before the smoothed breadth series has enough causal history",
        },
        {
            "name": "breadth_risk_only_on_baseline_cash_days",
            "ok": not bool((frame["breadth_active"] & (~frame["baseline_cash"])).any()),
            "detail": "breadth BTC risk never overlaps with baseline risk-on exposure",
        },
        {
            "name": "baseline_risk_days_unchanged",
            "ok": bool(
                (
                    frame.loc[frame["in_market"], "probe_strategy_return_gross"]
                    == pd.to_numeric(frame.loc[frame["in_market"], "strategy_return"], errors="coerce").fillna(0.0)
                ).all()
            ),
            "detail": "baseline in-market daily returns pass through unchanged",
        },
        {
            "name": "no_pilot_ladder_or_sizing_states",
            "ok": not bool(frame["probe_state"].astype(str).str.contains("PILOT|FULL_PRE_BASELINE", regex=True).any()),
            "detail": "probe states are CASH, BREADTH_BTC_RISK, and BASELINE_RISK only",
        },
        {
            "name": "semantic_flags_locked",
            "ok": True,
            "detail": "dev_only=true, non_authoritative=true, official_truth=false, strategy_advancement=false, candidate_selection=false, official_edge_claim=false",
        },
    ]
    return with_json_locks(
        {
            "artifact_id": "breadth_ignition_regime_probe_quality",
            "generated_at_utc": timestamp_utc(),
            "input_refs": input_refs,
            "checks": checks,
            "activation_window_count": int(len(activation_windows)),
            "baseline_metrics": baseline_metrics,
            "probe_metrics": probe_metrics,
            "status": "passed" if all(check["ok"] for check in checks) else "failed",
        }
    )


def main() -> None:
    args = parse_args()
    baseline_path = Path(args.baseline_paper)
    phase68i_paper_path = Path(args.phase68i_paper)
    phase68i_summary_path = Path(args.phase68i_summary)

    baseline_df = cash_diag.load_paper(baseline_path)
    frame = build_probe_frame(baseline_df)
    cost_cfg = load_phase68i_cost_assumptions(phase68i_summary_path, phase68i_paper_path)
    frame = apply_cost_model(frame, cost_cfg)

    activation_windows = build_activation_windows(frame)
    baseline_metrics = calc_metrics(
        returns_gross=frame["strategy_return"],
        returns_net=frame["baseline_strategy_return_net"],
        state_series=frame["in_market"].map({True: "BASELINE_RISK", False: "CASH"}),
        weight_series=frame["baseline_exposure_weight"],
        model=BASELINE_MODEL,
        breadth_risk_days=0,
    )
    probe_metrics = calc_metrics(
        returns_gross=frame["probe_strategy_return_gross"],
        returns_net=frame["probe_strategy_return_net"],
        state_series=frame["probe_state"],
        weight_series=frame["probe_exposure_weight"],
        model=PROBE_MODEL,
        breadth_risk_days=int(frame["breadth_active"].sum()),
    )

    input_refs = {
        "baseline_paper": str(baseline_path),
        "universe_ohlcv": {asset: str(cash_diag.resolve_asset_daily_path(asset)) for asset in UNIVERSE_SYMBOLS},
        "phase68i_paper_secondary_context": str(phase68i_paper_path) if phase68i_paper_path.exists() else None,
        "phase68i_summary_secondary_context": str(phase68i_summary_path) if phase68i_summary_path.exists() else None,
    }
    paths = output_paths()

    save_csv(paths["window_compare_csv"], activation_windows, WINDOW_COMPARE_COLUMNS)
    save_csv(paths["state_time_csv"], build_state_time_rows(frame), STATE_TIME_COLUMNS)
    save_csv(paths["compare_csv"], build_compare_rows(baseline_metrics, probe_metrics, activation_windows), COMPARE_COLUMNS)
    save_csv(paths["cost_metrics_csv"], [baseline_metrics, probe_metrics], COST_COLUMNS)
    save_json(
        paths["summary_json"],
        build_summary_payload(
            baseline_metrics=baseline_metrics,
            probe_metrics=probe_metrics,
            activation_windows=activation_windows,
            cost_cfg=cost_cfg,
            input_refs=input_refs,
        ),
    )
    save_json(paths["manifest_json"], build_manifest_payload(paths, input_refs))
    save_json(
        paths["quality_json"],
        build_quality_payload(
            frame=frame,
            baseline_metrics=baseline_metrics,
            probe_metrics=probe_metrics,
            activation_windows=activation_windows,
            input_refs=input_refs,
        ),
    )

    print("breadth_ignition_regime_probe generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
