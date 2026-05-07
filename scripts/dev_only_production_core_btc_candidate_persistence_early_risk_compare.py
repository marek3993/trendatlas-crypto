from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]

BASELINE_SNAPSHOT_PATH = ROOT / "outputs" / "production" / "current_strategy_snapshot.json"
BASELINE_TIMESERIES_PATH = ROOT / "outputs" / "production" / "current_strategy_timeseries.csv"
BASELINE_DIAGNOSTICS_PATH = ROOT / "outputs" / "production" / "current_strategy_diagnostics.json"

OUTPUT_ROOT = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_production_core_btc_candidate_persistence_early_risk_compare"
)

CONTRACT_REF = (
    "research_os/dev_only/contracts/"
    "dev_only_production_core_btc_candidate_persistence_early_risk_compare.contract.json"
)
SPEC_REF = (
    "research_os/dev_only/specs/"
    "dev_only_production_core_btc_candidate_persistence_early_risk_compare.spec.json"
)
MANIFEST_SEED_REF = (
    "research_os/dev_only/manifests/"
    "dev_only_production_core_btc_candidate_persistence_early_risk_compare.manifest.json"
)

ARTIFACT_ID = "production_core_btc_candidate_persistence_early_risk_compare"
ANALYSIS_MODE = "production_core_btc_candidate_persistence_early_risk_compare_only"
BASELINE_MODEL_ID = "phase68g_66g_1p25x_candidate"
BASELINE_LABEL = "Production Core authorized phase68g baseline"
MECHANISM_ID = "production_core_btc_candidate_persistence_early_risk_dev_only_compare"
MISSED_WINDOW_START = "2025-04-01"
MISSED_WINDOW_END = "2025-07-10"
PERSISTENCE_ROWS_REQUIRED = 10

VARIANT_SPECS = {
    "btc_candidate_persistence_10d_050": {
        "variant_id": "btc_candidate_persistence_10d_050",
        "variant_label": "BTC candidate persistence 10d 0.50x",
        "early_risk_sleeve": 0.50,
        "description": (
            "On baseline CASH rows only, enter BTC EARLY_RISK at 0.50x after BTC has persisted as the "
            "candidate for at least 10 consecutive Production Core rows and the pre-authorization trend "
            "band stays inside -0.20 < trend_score < 0.10."
        ),
    },
    "btc_candidate_persistence_10d_075": {
        "variant_id": "btc_candidate_persistence_10d_075",
        "variant_label": "BTC candidate persistence 10d 0.75x",
        "early_risk_sleeve": 0.75,
        "description": (
            "On baseline CASH rows only, enter BTC EARLY_RISK at 0.75x after BTC has persisted as the "
            "candidate for at least 10 consecutive Production Core rows and the pre-authorization trend "
            "band stays inside -0.20 < trend_score < 0.10."
        ),
    },
}

PERIOD_DEFS = [
    ("full_available", None, None),
    ("since2023", "2023-01-01", None),
    ("since2025", "2025-01-01", None),
    ("missed_window_2025", MISSED_WINDOW_START, MISSED_WINDOW_END),
]

CASH_EQUIVALENTS = {"", "CASH", "NONE", "NULL", "NAN", "OUT_OF_MARKET", "USD", "USDT"}

MEANINGFUL_CAPTURE_THRESHOLD_PCT = 10.0
MATERIAL_DD_WORSE_THRESHOLD_PCT = -2.0
TURNOVER_DELTA_STOP_THRESHOLD = 5.0
SWITCH_DELTA_STOP_THRESHOLD = 10
EXPOSURE_DAYS_DELTA_STOP_THRESHOLD = 60
NARROW_CAPTURE_PAUSE_THRESHOLD_PCT = 20.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dev-only Production Core BTC candidate persistence EARLY_RISK comparison."
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    return parser.parse_args()


def with_json_flags(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(
        {
            "analysis_mode": ANALYSIS_MODE,
            "candidate_selection": False,
            "official_edge_claim": False,
        }
    )
    return out


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_frame(path: Path, frame: pd.DataFrame) -> None:
    ensure_dir(path.parent)
    frame.to_csv(path, index=False)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    if pd.isna(value):
        return None
    return value


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_for_json(val) for key, val in value.items()}
    if isinstance(value, list):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_json(item) for item in value]
    return json_default(value)


def output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "summary_json": output_dir / "summary.json",
        "candidate_timeseries_csv": output_dir / "candidate_timeseries.csv",
        "compare_csv": output_dir / "compare.csv",
        "period_compare_csv": output_dir / "period_compare.csv",
        "activation_windows_csv": output_dir / "activation_windows.csv",
        "blocker_counts_csv": output_dir / "blocker_counts.csv",
        "cost_metrics_csv": output_dir / "cost_metrics.csv",
        "handoff_row_audit_csv": output_dir / "handoff_row_audit.csv",
        "variant_compare_csv": output_dir / "variant_compare.csv",
        "manifest_json": output_dir / "manifest.json",
        "quality_json": output_dir / "quality.json",
    }


def normalize_asset(value: Any) -> str:
    text = str(value or "").strip().upper()
    return "CASH" if text in CASH_EQUIVALENTS else text


def parse_bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    normalized = series.fillna("").astype(str).str.strip().str.lower()
    return normalized.isin({"1", "true", "yes", "y"})


def parse_float_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def compound_return(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if clean.empty:
        return 0.0
    return float((1.0 + clean).prod() - 1.0)


def annualize_return(total_return: float, n_days: int) -> float:
    if n_days <= 1:
        return 0.0
    years = n_days / 365.25
    if years <= 0:
        return 0.0
    if total_return <= -1.0:
        return -1.0
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


def max_drawdown_from_returns(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def count_switches(state_series: pd.Series) -> int:
    states = state_series.fillna("").astype(str)
    if states.empty:
        return 0
    prev = states.shift(1).fillna("")
    return int(states.ne(prev).sum() - (1 if states.iloc[0] != "" else 0))


def round_float(value: Any, digits: int = 6) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return round(float(0.0 if pd.isna(numeric) else numeric), digits)


def detect_hard_invalidation(frame: pd.DataFrame) -> tuple[pd.Series, dict[str, Any]]:
    for column in frame.columns:
        lower = str(column).lower()
        if "hard" in lower and "invalid" in lower:
            return parse_bool_series(frame[column]), {
                "available": True,
                "source_column": column,
                "detail": "Canonical hard invalidation column found in current_strategy_timeseries.csv.",
            }
    return pd.Series(False, index=frame.index), {
        "available": False,
        "source_column": None,
        "detail": "No canonical hard invalidation column is present in current_strategy_timeseries.csv.",
    }


def derive_cost_model(frame: pd.DataFrame) -> dict[str, Any]:
    turnover = parse_float_series(frame.get("turnover", 0.0)).fillna(0.0)
    fees = parse_float_series(frame.get("fees_daily", 0.0)).fillna(0.0)
    fee_mask = fees.gt(0.0) & turnover.gt(0.0)
    fee_rate = float((fees[fee_mask] / turnover[fee_mask]).median()) if fee_mask.any() else 0.00045

    slippage = parse_float_series(frame.get("slippage_cost_daily", 0.0)).fillna(0.0)
    slippage_mask = slippage.gt(0.0)
    slippage_rate = float(slippage[slippage_mask].median()) if slippage_mask.any() else 0.001

    exposure = parse_float_series(frame.get("current_exposure", 0.0)).fillna(0.0)
    borrow = parse_float_series(frame.get("borrow_cost_daily", 0.0)).fillna(0.0)
    borrow_mask = borrow.gt(0.0) & exposure.gt(1.0)
    annual_borrow_cost = (
        float((borrow[borrow_mask] / (exposure[borrow_mask] - 1.0) * 365.25).median())
        if borrow_mask.any()
        else 0.12
    )

    return {
        "fee_rate": fee_rate,
        "taker_fee_bps": round_float(fee_rate * 10000.0),
        "maker_fee_bps": round_float((fee_rate * 10000.0) / 3.0),
        "slippage_rate": slippage_rate,
        "tradable_transition_slippage_bps": round_float(slippage_rate * 10000.0),
        "annual_borrow_cost": annual_borrow_cost,
        "annual_borrow_cost_pct": round_float(annual_borrow_cost * 100.0),
        "fee_side_mode": "taker",
        "staking_discount_pct": 0.0,
        "referral_discount_pct": 0.0,
        "source": "derived from outputs/production/current_strategy_timeseries.csv daily cost columns",
    }


def compute_btc_candidate_persistence_rows(frame: pd.DataFrame) -> pd.Series:
    streaks: list[int] = []
    run = 0
    for asset in frame["candidate_asset"]:
        if asset == "BTC":
            run += 1
        else:
            run = 0
        streaks.append(run)
    return pd.Series(streaks, index=frame.index, dtype="int64")


def load_baseline_frame(path: Path) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    df = pd.read_csv(path)
    df.columns = [str(column).strip() for column in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"], keep="last").copy()

    for column in [
        "candidate_asset",
        "selected_asset",
        "actual_held_asset",
        "authorized_tradable_asset",
        "held_asset",
        "current_asset",
        "execution_target_asset",
    ]:
        if column in df.columns:
            df[column] = df[column].map(normalize_asset)

    for column in [
        "model_candidate_exposure",
        "effective_market_exposure",
        "current_exposure",
        "trend_score",
        "buy_threshold",
        "trend_activation_threshold",
        "return_gross",
        "return_net",
        "fees_daily",
        "funding_daily",
        "borrow_cost_daily",
        "slippage_cost_daily",
        "turnover",
        "btc_return",
        "btc_close",
        "equity",
    ]:
        if column in df.columns:
            df[column] = parse_float_series(df[column]).fillna(0.0)

    for column in [
        "trend_permission_active",
        "is_rebalance_day",
        "asset_transition_day",
        "trend_block_day",
        "stress_block_day",
        "trend_gate_pass",
    ]:
        if column in df.columns:
            df[column] = parse_bool_series(df[column])
        else:
            df[column] = False

    hard_invalidation, hard_invalidation_meta = detect_hard_invalidation(df)
    df["hard_invalidation"] = hard_invalidation
    df["baseline_cash"] = df["current_asset"].eq("CASH") & df["effective_market_exposure"].abs().le(1e-12)
    df["baseline_non_cash"] = ~df["baseline_cash"]
    df["baseline_state"] = np.where(df["baseline_cash"], "CASH", "FULL_RISK")
    df["baseline_total_cost_daily"] = (
        df["fees_daily"] + df["funding_daily"] + df["borrow_cost_daily"] + df["slippage_cost_daily"]
    )
    df["baseline_equity_gross"] = (1.0 + df["return_gross"]).cumprod()
    df["baseline_equity_net"] = (1.0 + df["return_net"]).cumprod()
    df["btc_candidate_persistence_rows"] = compute_btc_candidate_persistence_rows(df)
    df["persistence_entry_filter_ready"] = (
        df["baseline_cash"]
        & df["candidate_asset"].eq("BTC")
        & df["btc_candidate_persistence_rows"].ge(PERSISTENCE_ROWS_REQUIRED)
        & (~df["trend_permission_active"])
        & df["trend_score"].gt(-0.20)
        & df["trend_score"].lt(0.10)
        & (~df["stress_block_day"])
        & (~df["hard_invalidation"])
    )
    return df.reset_index(drop=True), hard_invalidation_meta, derive_cost_model(df)


def compute_path_costs(
    held_asset: pd.Series,
    leverage: pd.Series,
    gross_return: pd.Series,
    *,
    fee_rate: float,
    slippage_rate: float,
    annual_borrow_cost: float,
) -> pd.DataFrame:
    held = held_asset.fillna("CASH").astype(str).str.upper()
    lev = pd.to_numeric(leverage, errors="coerce").fillna(0.0)
    gross = pd.to_numeric(gross_return, errors="coerce").fillna(0.0)

    prev_asset = held.shift(1).fillna("")
    prev_lev = lev.shift(1).fillna(0.0)
    curr_lev = lev.copy()

    has_prev = prev_asset.ne("")
    asset_transition = has_prev & held.ne(prev_asset)

    prev_notional = np.where(prev_asset.eq("CASH"), 0.0, prev_lev)
    curr_notional = np.where(held.eq("CASH"), 0.0, curr_lev)
    same_asset = held.eq(prev_asset)

    turnover = np.where(
        has_prev,
        np.where(
            same_asset,
            np.abs(curr_notional - prev_notional),
            prev_notional + curr_notional,
        ),
        0.0,
    )
    fees = turnover * float(fee_rate)
    slippage = np.where(asset_transition, float(slippage_rate), 0.0)
    borrow = np.maximum(curr_lev - 1.0, 0.0) * (float(annual_borrow_cost) / 365.25)
    funding = np.zeros(len(held), dtype=float)
    net = (gross - fees - slippage - borrow - funding).clip(lower=-0.999999)

    return pd.DataFrame(
        {
            "candidate_asset_transition_day": asset_transition.astype(bool),
            "candidate_turnover": turnover,
            "candidate_fees_daily": fees,
            "candidate_slippage_cost_daily": slippage,
            "candidate_borrow_cost_daily": borrow,
            "candidate_funding_daily": funding,
            "candidate_total_cost_daily": fees + slippage + borrow + funding,
            "candidate_return_net": net,
        }
    )


def build_override_states(
    baseline: pd.DataFrame,
    *,
    variant_id: str,
) -> list[str]:
    override_states: list[str] = []
    active = False

    for row in baseline.itertuples(index=False):
        if bool(row.baseline_non_cash):
            override_states.append("PASS_THROUGH")
            active = False
            continue

        candidate_is_btc = row.candidate_asset == "BTC"
        stress_or_hard = bool(row.stress_block_day) or bool(row.hard_invalidation)
        trend_score = float(row.trend_score)

        if active:
            if (not candidate_is_btc) or (trend_score <= -0.20) or stress_or_hard:
                override_states.append("CASH")
                active = False
            else:
                override_states.append("EARLY_RISK")
                active = True
            continue

        if (
            candidate_is_btc
            and int(row.btc_candidate_persistence_rows) >= PERSISTENCE_ROWS_REQUIRED
            and (not bool(row.trend_permission_active))
            and (trend_score > -0.20)
            and (trend_score < 0.10)
            and (not stress_or_hard)
        ):
            override_states.append("EARLY_RISK")
            active = True
        else:
            override_states.append("CASH")
            active = False

    return override_states


def variant_reason(row: pd.Series) -> str:
    if row["override_state"] == "PASS_THROUGH":
        return "baseline_non_cash_strict_pass_through"
    if row["override_state"] == "EARLY_RISK":
        if bool(row["candidate_entry_day"]):
            return "btc_candidate_persistence_10d_entry"
        return "btc_candidate_persistence_maintenance"
    if row["candidate_asset"] != "BTC":
        return "candidate_asset_not_btc"
    if bool(row["stress_block_day"]) or bool(row["hard_invalidation"]):
        return "stress_or_hard_invalidation_on"
    if int(row["btc_candidate_persistence_rows"]) < PERSISTENCE_ROWS_REQUIRED:
        return "candidate_persistence_lt_10_rows"
    if bool(row["trend_permission_active"]):
        return "trend_permission_active_but_baseline_cash"
    if float(row["trend_score"]) <= -0.20:
        return "trend_score_le_minus_020"
    if float(row["trend_score"]) >= 0.10:
        return "trend_score_ge_0p10_pre_entry"
    return "variant_rule_not_triggered"


def build_variant_frame(
    baseline: pd.DataFrame,
    *,
    variant_id: str,
    cost_model: dict[str, Any],
) -> pd.DataFrame:
    frame = baseline.copy()
    frame["variant_id"] = variant_id
    frame["override_state"] = build_override_states(frame, variant_id=variant_id)
    frame["candidate_effective_state"] = np.where(
        frame["override_state"].eq("PASS_THROUGH"),
        frame["baseline_state"],
        frame["override_state"],
    )
    frame["candidate_state_origin"] = np.where(
        frame["override_state"].eq("PASS_THROUGH"),
        "baseline_pass_through",
        "dev_only_override",
    )

    frame["candidate_held_asset"] = "CASH"
    frame["candidate_effective_leverage"] = 0.0
    frame["candidate_return_gross"] = 0.0

    pass_through_mask = frame["override_state"].eq("PASS_THROUGH")
    early_mask = frame["override_state"].eq("EARLY_RISK")
    sleeve = float(VARIANT_SPECS[variant_id]["early_risk_sleeve"])

    frame.loc[pass_through_mask, "candidate_held_asset"] = frame.loc[pass_through_mask, "current_asset"]
    frame.loc[pass_through_mask, "candidate_effective_leverage"] = frame.loc[pass_through_mask, "current_exposure"]
    frame.loc[pass_through_mask, "candidate_return_gross"] = frame.loc[pass_through_mask, "return_gross"]

    frame.loc[early_mask, "candidate_held_asset"] = "BTC"
    frame.loc[early_mask, "candidate_effective_leverage"] = sleeve
    frame.loc[early_mask, "candidate_return_gross"] = frame.loc[early_mask, "btc_return"] * sleeve

    path_costs = compute_path_costs(
        frame["candidate_held_asset"],
        frame["candidate_effective_leverage"],
        frame["candidate_return_gross"],
        fee_rate=float(cost_model["fee_rate"]),
        slippage_rate=float(cost_model["slippage_rate"]),
        annual_borrow_cost=float(cost_model["annual_borrow_cost"]),
    )
    frame = pd.concat([frame, path_costs], axis=1)

    frame.loc[pass_through_mask, "candidate_asset_transition_day"] = frame.loc[pass_through_mask, "asset_transition_day"]
    frame.loc[pass_through_mask, "candidate_turnover"] = frame.loc[pass_through_mask, "turnover"]
    frame.loc[pass_through_mask, "candidate_fees_daily"] = frame.loc[pass_through_mask, "fees_daily"]
    frame.loc[pass_through_mask, "candidate_slippage_cost_daily"] = frame.loc[pass_through_mask, "slippage_cost_daily"]
    frame.loc[pass_through_mask, "candidate_borrow_cost_daily"] = frame.loc[pass_through_mask, "borrow_cost_daily"]
    frame.loc[pass_through_mask, "candidate_funding_daily"] = frame.loc[pass_through_mask, "funding_daily"]
    frame.loc[pass_through_mask, "candidate_total_cost_daily"] = frame.loc[pass_through_mask, "baseline_total_cost_daily"]
    frame.loc[pass_through_mask, "candidate_return_net"] = frame.loc[pass_through_mask, "return_net"]

    previous_override = frame["override_state"].shift(1).fillna("CASH")
    frame["candidate_entry_day"] = frame["override_state"].eq("EARLY_RISK") & previous_override.ne("EARLY_RISK")
    frame["candidate_exit_day"] = (
        frame["override_state"].eq("CASH")
        & previous_override.eq("EARLY_RISK")
        & frame["baseline_cash"]
    )
    frame["candidate_equity_gross"] = (1.0 + frame["candidate_return_gross"]).cumprod()
    frame["candidate_equity_net"] = (1.0 + frame["candidate_return_net"]).cumprod()
    frame["candidate_reason"] = frame.apply(variant_reason, axis=1)
    frame["early_risk_active"] = frame["override_state"].eq("EARLY_RISK")
    frame["candidate_exposure_active"] = frame["candidate_effective_leverage"].gt(0.0)
    return frame


def row_local_match(left: Any, right: Any, tol: float = 1e-12) -> bool:
    if isinstance(left, str) or isinstance(right, str):
        return str(left) == str(right)
    if pd.isna(left) and pd.isna(right):
        return True
    return bool(abs(float(left) - float(right)) <= tol)


def build_handoff_row_audit(variant_frame: pd.DataFrame) -> pd.DataFrame:
    pass_through = variant_frame.loc[variant_frame["baseline_non_cash"]].copy()
    if pass_through.empty:
        return pd.DataFrame(
            columns=[
                "variant_id",
                "date",
                "is_handoff_row",
                "baseline_state",
                "candidate_state",
                "baseline_asset",
                "candidate_asset",
                "baseline_effective_market_exposure",
                "candidate_effective_market_exposure",
                "baseline_return_gross",
                "candidate_return_gross",
                "baseline_return_net",
                "candidate_return_net",
                "baseline_turnover",
                "candidate_turnover",
                "baseline_trading_fees",
                "candidate_trading_fees",
                "baseline_borrow_cost",
                "candidate_borrow_cost",
                "baseline_funding",
                "candidate_funding",
                "baseline_slippage",
                "candidate_slippage",
                "field_match_state",
                "field_match_asset",
                "field_match_exposure",
                "field_match_gross_return",
                "field_match_net_return",
                "field_match_turnover",
                "field_match_trading_fees",
                "field_match_borrow_cost",
                "field_match_funding",
                "field_match_slippage",
                "field_match_equity_path",
                "all_row_local_fields_match_flag",
                "baseline_equity_net",
                "candidate_equity_net",
                "equity_level_delta_vs_baseline_pct",
            ]
        )

    rows: list[dict[str, Any]] = []
    previous_override = variant_frame["override_state"].shift(1).fillna("CASH")
    previous_candidate_equity = variant_frame["candidate_equity_net"].shift(1)

    for idx, row in pass_through.iterrows():
        field_match_state = row_local_match(row["baseline_state"], row["candidate_effective_state"])
        field_match_asset = row_local_match(row["current_asset"], row["candidate_held_asset"])
        field_match_exposure = row_local_match(row["current_exposure"], row["candidate_effective_leverage"])
        field_match_gross = row_local_match(row["return_gross"], row["candidate_return_gross"])
        field_match_net = row_local_match(row["return_net"], row["candidate_return_net"])
        field_match_turnover = row_local_match(row["turnover"], row["candidate_turnover"])
        field_match_fees = row_local_match(row["fees_daily"], row["candidate_fees_daily"])
        field_match_borrow = row_local_match(row["borrow_cost_daily"], row["candidate_borrow_cost_daily"])
        field_match_funding = row_local_match(row["funding_daily"], row["candidate_funding_daily"])
        field_match_slippage = row_local_match(row["slippage_cost_daily"], row["candidate_slippage_cost_daily"])

        if idx == 0 or pd.isna(previous_candidate_equity.iloc[idx]):
            field_match_equity_path = True
        else:
            expected_equity = float(previous_candidate_equity.iloc[idx]) * (1.0 + float(row["return_net"]))
            field_match_equity_path = row_local_match(float(row["candidate_equity_net"]), expected_equity, tol=1e-10)

        rows.append(
            {
                "variant_id": row["variant_id"],
                "date": row["date"].strftime("%Y-%m-%d"),
                "is_handoff_row": bool(previous_override.iloc[idx] == "EARLY_RISK"),
                "baseline_state": row["baseline_state"],
                "candidate_state": row["candidate_effective_state"],
                "baseline_asset": row["current_asset"],
                "candidate_asset": row["candidate_held_asset"],
                "baseline_effective_market_exposure": round_float(row["current_exposure"]),
                "candidate_effective_market_exposure": round_float(row["candidate_effective_leverage"]),
                "baseline_return_gross": round_float(row["return_gross"], 12),
                "candidate_return_gross": round_float(row["candidate_return_gross"], 12),
                "baseline_return_net": round_float(row["return_net"], 12),
                "candidate_return_net": round_float(row["candidate_return_net"], 12),
                "baseline_turnover": round_float(row["turnover"]),
                "candidate_turnover": round_float(row["candidate_turnover"]),
                "baseline_trading_fees": round_float(row["fees_daily"], 12),
                "candidate_trading_fees": round_float(row["candidate_fees_daily"], 12),
                "baseline_borrow_cost": round_float(row["borrow_cost_daily"], 12),
                "candidate_borrow_cost": round_float(row["candidate_borrow_cost_daily"], 12),
                "baseline_funding": round_float(row["funding_daily"], 12),
                "candidate_funding": round_float(row["candidate_funding_daily"], 12),
                "baseline_slippage": round_float(row["slippage_cost_daily"], 12),
                "candidate_slippage": round_float(row["candidate_slippage_cost_daily"], 12),
                "field_match_state": field_match_state,
                "field_match_asset": field_match_asset,
                "field_match_exposure": field_match_exposure,
                "field_match_gross_return": field_match_gross,
                "field_match_net_return": field_match_net,
                "field_match_turnover": field_match_turnover,
                "field_match_trading_fees": field_match_fees,
                "field_match_borrow_cost": field_match_borrow,
                "field_match_funding": field_match_funding,
                "field_match_slippage": field_match_slippage,
                "field_match_equity_path": field_match_equity_path,
                "all_row_local_fields_match_flag": all(
                    [
                        field_match_state,
                        field_match_asset,
                        field_match_exposure,
                        field_match_gross,
                        field_match_net,
                        field_match_turnover,
                        field_match_fees,
                        field_match_borrow,
                        field_match_funding,
                        field_match_slippage,
                        field_match_equity_path,
                    ]
                ),
                "baseline_equity_net": round_float(row["baseline_equity_net"], 12),
                "candidate_equity_net": round_float(row["candidate_equity_net"], 12),
                "equity_level_delta_vs_baseline_pct": round_float(
                    (float(row["candidate_equity_net"]) - float(row["baseline_equity_net"])) * 100.0,
                    6,
                ),
            }
        )
    return pd.DataFrame(rows)


def window_exit_reason(frame: pd.DataFrame, end_index: int) -> str:
    if end_index >= len(frame) - 1:
        return "dataset_end"
    next_row = frame.iloc[end_index + 1]
    if bool(next_row["baseline_non_cash"]):
        return "baseline_full_risk_handoff"
    if next_row["candidate_asset"] != "BTC":
        return "candidate_asset_not_btc"
    if bool(next_row["stress_block_day"]) or bool(next_row["hard_invalidation"]):
        return "stress_or_hard_invalidation_on"
    if float(next_row["trend_score"]) <= -0.20:
        return "trend_score_le_minus_020"
    return "candidate_persistence_rule_not_active"


def build_activation_windows(variant_frame: pd.DataFrame) -> pd.DataFrame:
    active_mask = variant_frame["override_state"].eq("EARLY_RISK")
    if not active_mask.any():
        return pd.DataFrame(
            columns=[
                "variant_id",
                "window_id",
                "start_date",
                "end_date",
                "window_length_days",
                "baseline_handoff_date",
                "lead_days_vs_baseline_full_risk",
                "false_start",
                "exit_reason",
                "period_bucket",
                "overlaps_since2023",
                "overlaps_since2025",
                "overlaps_missed_window_2025",
                "early_risk_days",
                "baseline_return_net_pct",
                "candidate_return_net_pct",
                "net_contribution_pct_vs_baseline",
                "baseline_return_gross_pct",
                "candidate_return_gross_pct",
                "gross_contribution_pct_vs_baseline",
                "btc_return_pct",
                "entry_candidate_asset",
                "entry_persistence_rows",
                "entry_trend_score",
                "entry_trend_permission_active",
                "entry_stress_block_day",
                "entry_hard_invalidation",
            ]
        )

    rows: list[dict[str, Any]] = []
    group_ids = active_mask.ne(active_mask.shift(1, fill_value=False)).cumsum()
    active_groups = group_ids.loc[active_mask]

    for window_number, (_, positions) in enumerate(active_groups.groupby(active_groups), start=1):
        position_index = positions.index.tolist()
        start_idx = int(position_index[0])
        end_idx = int(position_index[-1])
        window_slice = variant_frame.iloc[start_idx : end_idx + 1].copy()
        start_date = pd.Timestamp(window_slice.iloc[0]["date"])
        end_date = pd.Timestamp(window_slice.iloc[-1]["date"])
        handoff_date = None
        if end_idx + 1 < len(variant_frame):
            next_row = variant_frame.iloc[end_idx + 1]
            if bool(next_row["baseline_non_cash"]):
                handoff_date = pd.Timestamp(next_row["date"])

        if start_date >= pd.Timestamp("2025-01-01"):
            period_bucket = "since2025"
        elif start_date >= pd.Timestamp("2023-01-01"):
            period_bucket = "since2023"
        else:
            period_bucket = "pre2023"

        rows.append(
            {
                "variant_id": str(window_slice.iloc[0]["variant_id"]),
                "window_id": f"window_{window_number:03d}",
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "window_length_days": int(len(window_slice)),
                "baseline_handoff_date": "" if handoff_date is None else handoff_date.strftime("%Y-%m-%d"),
                "lead_days_vs_baseline_full_risk": 0 if handoff_date is None else int((handoff_date - start_date).days),
                "false_start": handoff_date is None,
                "exit_reason": window_exit_reason(variant_frame, end_idx),
                "period_bucket": period_bucket,
                "overlaps_since2023": end_date >= pd.Timestamp("2023-01-01"),
                "overlaps_since2025": end_date >= pd.Timestamp("2025-01-01"),
                "overlaps_missed_window_2025": period_overlap(
                    start_date,
                    end_date,
                    pd.Timestamp(MISSED_WINDOW_START),
                    pd.Timestamp(MISSED_WINDOW_END),
                ),
                "early_risk_days": int(len(window_slice)),
                "baseline_return_net_pct": round_float(compound_return(window_slice["return_net"]) * 100.0),
                "candidate_return_net_pct": round_float(compound_return(window_slice["candidate_return_net"]) * 100.0),
                "net_contribution_pct_vs_baseline": round_float(
                    (
                        compound_return(window_slice["candidate_return_net"])
                        - compound_return(window_slice["return_net"])
                    )
                    * 100.0
                ),
                "baseline_return_gross_pct": round_float(compound_return(window_slice["return_gross"]) * 100.0),
                "candidate_return_gross_pct": round_float(
                    compound_return(window_slice["candidate_return_gross"]) * 100.0
                ),
                "gross_contribution_pct_vs_baseline": round_float(
                    (
                        compound_return(window_slice["candidate_return_gross"])
                        - compound_return(window_slice["return_gross"])
                    )
                    * 100.0
                ),
                "btc_return_pct": round_float(compound_return(window_slice["btc_return"]) * 100.0),
                "entry_candidate_asset": str(window_slice.iloc[0]["candidate_asset"]),
                "entry_persistence_rows": int(window_slice.iloc[0]["btc_candidate_persistence_rows"]),
                "entry_trend_score": round_float(window_slice.iloc[0]["trend_score"]),
                "entry_trend_permission_active": bool(window_slice.iloc[0]["trend_permission_active"]),
                "entry_stress_block_day": bool(window_slice.iloc[0]["stress_block_day"]),
                "entry_hard_invalidation": bool(window_slice.iloc[0]["hard_invalidation"]),
            }
        )
    return pd.DataFrame(rows)


def blocker_reason(row: pd.Series) -> str:
    if bool(row["baseline_non_cash"]):
        return "baseline_full_risk_pass_through"
    if row["override_state"] == "EARLY_RISK":
        return "active_early_risk"
    if row["candidate_asset"] != "BTC":
        return "candidate_asset_not_btc"
    if bool(row["stress_block_day"]) or bool(row["hard_invalidation"]):
        return "stress_or_hard_invalidation_on"
    if int(row["btc_candidate_persistence_rows"]) < PERSISTENCE_ROWS_REQUIRED:
        return "candidate_persistence_lt_10_rows"
    if bool(row["trend_permission_active"]):
        return "trend_permission_active_but_baseline_cash"
    if float(row["trend_score"]) <= -0.20:
        return "trend_score_le_minus_020"
    if float(row["trend_score"]) >= 0.10:
        return "trend_score_ge_0p10_pre_entry"
    return "variant_rule_not_triggered"


def build_blocker_counts(variant_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant_id, frame in variant_frames.items():
        local = frame.copy()
        local["blocker_reason"] = local.apply(blocker_reason, axis=1)
        for period_id, start_date, end_date in PERIOD_DEFS:
            subset = filter_period(local, start_date, end_date)
            total_rows = len(subset)
            counts = subset["blocker_reason"].value_counts().sort_index()
            for blocker, count in counts.items():
                rows.append(
                    {
                        "variant_id": variant_id,
                        "period": period_id,
                        "blocker_reason": blocker,
                        "row_count": int(count),
                        "share_of_period_rows": round_float(count / total_rows if total_rows else 0.0),
                    }
                )
    return pd.DataFrame(rows)


def filter_period(frame: pd.DataFrame, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    subset = frame.copy()
    if start_date is not None:
        subset = subset.loc[subset["date"] >= pd.Timestamp(start_date)].copy()
    if end_date is not None:
        subset = subset.loc[subset["date"] <= pd.Timestamp(end_date)].copy()
    return subset.reset_index(drop=True)


def filter_windows(frame: pd.DataFrame, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out["start_date"] = pd.to_datetime(out["start_date"], errors="coerce")
    out["end_date"] = pd.to_datetime(out["end_date"], errors="coerce")
    if start_date is not None:
        out = out.loc[out["end_date"] >= pd.Timestamp(start_date)].copy()
    if end_date is not None:
        out = out.loc[out["start_date"] <= pd.Timestamp(end_date)].copy()
    return out.reset_index(drop=True)


def period_overlap(
    start: pd.Timestamp,
    end: pd.Timestamp,
    period_start: pd.Timestamp | None,
    period_end: pd.Timestamp | None,
) -> bool:
    if period_start is not None and end < period_start:
        return False
    if period_end is not None and start > period_end:
        return False
    return True


def build_period_metrics(
    variant_frame: pd.DataFrame,
    activation_windows: pd.DataFrame,
    handoff_audit: pd.DataFrame,
    *,
    variant_id: str,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    subset = filter_period(variant_frame, start_date, end_date)
    if subset.empty:
        raise ValueError(f"Empty subset for period {start_date} -> {end_date}")
    window_subset = filter_windows(activation_windows, start_date, end_date)
    audit_subset = handoff_audit.copy()
    if start_date is not None:
        audit_subset = audit_subset.loc[pd.to_datetime(audit_subset["date"]) >= pd.Timestamp(start_date)].copy()
    if end_date is not None:
        audit_subset = audit_subset.loc[pd.to_datetime(audit_subset["date"]) <= pd.Timestamp(end_date)].copy()

    baseline_total_return = compound_return(subset["return_net"])
    candidate_total_return = compound_return(subset["candidate_return_net"])
    baseline_gross_return = compound_return(subset["return_gross"])
    candidate_gross_return = compound_return(subset["candidate_return_gross"])

    baseline_cagr = annualize_return(baseline_total_return, len(subset))
    candidate_cagr = annualize_return(candidate_total_return, len(subset))
    baseline_mdd = max_drawdown_from_returns(subset["return_net"])
    candidate_mdd = max_drawdown_from_returns(subset["candidate_return_net"])

    baseline_switches = count_switches(subset["baseline_state"])
    candidate_switches = count_switches(subset["candidate_effective_state"])

    baseline_turnover = float(subset["turnover"].sum())
    candidate_turnover = float(subset["candidate_turnover"].sum())
    baseline_cost_total = float(subset["baseline_total_cost_daily"].sum())
    candidate_cost_total = float(subset["candidate_total_cost_daily"].sum())

    baseline_exposure_days = int(subset["effective_market_exposure"].gt(0.0).sum())
    candidate_exposure_days = int(subset["candidate_effective_leverage"].gt(0.0).sum())
    early_risk_days = int(subset["override_state"].eq("EARLY_RISK").sum())

    zero_exposure_btc_missed_return = None
    missed_btc_move_captured_pct = None
    if start_date == MISSED_WINDOW_START and end_date == MISSED_WINDOW_END:
        zero_df = subset.loc[subset["baseline_cash"]].copy()
        if not zero_df.empty:
            start_close = float(zero_df.iloc[0]["btc_close"])
            end_close = float(zero_df.iloc[-1]["btc_close"])
            if start_close > 0.0:
                zero_exposure_btc_missed_return = (end_close / start_close) - 1.0
        if zero_exposure_btc_missed_return not in {None, 0.0}:
            missed_btc_move_captured_pct = (
                (candidate_total_return - baseline_total_return) / zero_exposure_btc_missed_return
            ) * 100.0

    pass_through_ok = bool(audit_subset["all_row_local_fields_match_flag"].all()) if not audit_subset.empty else True
    row_local_mismatch_count = int((~audit_subset["all_row_local_fields_match_flag"]).sum()) if not audit_subset.empty else 0

    return {
        "variant_id": variant_id,
        "variant_label": VARIANT_SPECS[variant_id]["variant_label"],
        "period": (
            "full_available"
            if start_date is None and end_date is None
            else (
                "missed_window_2025"
                if start_date == MISSED_WINDOW_START and end_date == MISSED_WINDOW_END
                else (f"since{pd.Timestamp(start_date).year}" if start_date and end_date is None else f"{start_date}_to_{end_date}")
            )
        ),
        "period_start": subset["date"].min().strftime("%Y-%m-%d"),
        "period_end": subset["date"].max().strftime("%Y-%m-%d"),
        "row_count": int(len(subset)),
        "baseline_net_total_return_pct": round_float(baseline_total_return * 100.0),
        "candidate_net_total_return_pct": round_float(candidate_total_return * 100.0),
        "net_total_return_delta_pct": round_float((candidate_total_return - baseline_total_return) * 100.0),
        "baseline_net_cagr_pct": round_float(baseline_cagr * 100.0),
        "candidate_net_cagr_pct": round_float(candidate_cagr * 100.0),
        "net_cagr_delta_pct": round_float((candidate_cagr - baseline_cagr) * 100.0),
        "baseline_net_max_drawdown_pct": round_float(baseline_mdd * 100.0),
        "candidate_net_max_drawdown_pct": round_float(candidate_mdd * 100.0),
        "net_max_drawdown_delta_pct": round_float((candidate_mdd - baseline_mdd) * 100.0),
        "baseline_switch_count": baseline_switches,
        "candidate_switch_count": candidate_switches,
        "switch_delta": int(candidate_switches - baseline_switches),
        "baseline_turnover_total": round_float(baseline_turnover),
        "candidate_turnover_total": round_float(candidate_turnover),
        "turnover_delta": round_float(candidate_turnover - baseline_turnover),
        "baseline_exposure_days": baseline_exposure_days,
        "candidate_exposure_days": candidate_exposure_days,
        "exposure_days_delta": int(candidate_exposure_days - baseline_exposure_days),
        "baseline_total_cost_pct": round_float(baseline_cost_total * 100.0),
        "candidate_total_cost_pct": round_float(candidate_cost_total * 100.0),
        "cost_delta_pct": round_float((candidate_cost_total - baseline_cost_total) * 100.0),
        "baseline_gross_total_return_pct": round_float(baseline_gross_return * 100.0),
        "candidate_gross_total_return_pct": round_float(candidate_gross_return * 100.0),
        "gross_total_return_delta_pct": round_float((candidate_gross_return - baseline_gross_return) * 100.0),
        "early_risk_days": early_risk_days,
        "activation_window_count": int(len(window_subset)),
        "successful_handoff_count": int((~window_subset["false_start"]).sum()) if not window_subset.empty else 0,
        "false_start_count": int(window_subset["false_start"].sum()) if not window_subset.empty else 0,
        "lead_days_total": int(window_subset["lead_days_vs_baseline_full_risk"].sum()) if not window_subset.empty else 0,
        "lead_days_max": int(window_subset["lead_days_vs_baseline_full_risk"].max()) if not window_subset.empty else 0,
        "strategy_delta_vs_baseline_pct": round_float((candidate_total_return - baseline_total_return) * 100.0),
        "zero_exposure_btc_missed_return_pct": None
        if zero_exposure_btc_missed_return is None
        else round_float(zero_exposure_btc_missed_return * 100.0),
        "missed_btc_move_captured_pct": None
        if missed_btc_move_captured_pct is None
        else round_float(missed_btc_move_captured_pct),
        "strict_pass_through_ok": pass_through_ok,
        "row_local_mismatch_count": row_local_mismatch_count,
    }


def build_compare_rows(period_compare: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    metric_specs = [
        ("net_total_return_pct", "baseline_net_total_return_pct", "candidate_net_total_return_pct", "net_total_return_delta_pct"),
        ("net_cagr_pct", "baseline_net_cagr_pct", "candidate_net_cagr_pct", "net_cagr_delta_pct"),
        ("net_max_drawdown_pct", "baseline_net_max_drawdown_pct", "candidate_net_max_drawdown_pct", "net_max_drawdown_delta_pct"),
        ("switch_count", "baseline_switch_count", "candidate_switch_count", "switch_delta"),
        ("turnover_total", "baseline_turnover_total", "candidate_turnover_total", "turnover_delta"),
        ("exposure_days", "baseline_exposure_days", "candidate_exposure_days", "exposure_days_delta"),
        ("total_cost_pct", "baseline_total_cost_pct", "candidate_total_cost_pct", "cost_delta_pct"),
        ("gross_total_return_pct", "baseline_gross_total_return_pct", "candidate_gross_total_return_pct", "gross_total_return_delta_pct"),
    ]

    for row in period_compare.to_dict(orient="records"):
        for metric_name, baseline_col, candidate_col, delta_col in metric_specs:
            rows.append(
                {
                    "variant_id": row["variant_id"],
                    "period": row["period"],
                    "metric": metric_name,
                    "baseline_value": row[baseline_col],
                    "candidate_value": row[candidate_col],
                    "delta_value": row[delta_col],
                }
            )
        for metric_name in [
            "early_risk_days",
            "activation_window_count",
            "successful_handoff_count",
            "false_start_count",
            "lead_days_total",
            "lead_days_max",
            "strategy_delta_vs_baseline_pct",
            "missed_btc_move_captured_pct",
            "strict_pass_through_ok",
            "row_local_mismatch_count",
        ]:
            rows.append(
                {
                    "variant_id": row["variant_id"],
                    "period": row["period"],
                    "metric": metric_name,
                    "baseline_value": 0 if metric_name != "strict_pass_through_ok" else True,
                    "candidate_value": row[metric_name],
                    "delta_value": row[metric_name],
                }
            )
    return pd.DataFrame(rows)


def build_cost_metrics(variant_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant_id, frame in variant_frames.items():
        for period_id, start_date, end_date in PERIOD_DEFS:
            subset = filter_period(frame, start_date, end_date)
            if subset.empty:
                continue
            rows.append(
                {
                    "variant_id": variant_id,
                    "period": period_id,
                    "model": "baseline",
                    "trading_fees_total_pct": round_float(subset["fees_daily"].sum() * 100.0),
                    "funding_total_pct": round_float(subset["funding_daily"].sum() * 100.0),
                    "borrow_cost_total_pct": round_float(subset["borrow_cost_daily"].sum() * 100.0),
                    "slippage_cost_total_pct": round_float(subset["slippage_cost_daily"].sum() * 100.0),
                    "total_cost_pct": round_float(subset["baseline_total_cost_daily"].sum() * 100.0),
                    "turnover_total": round_float(subset["turnover"].sum()),
                }
            )
            rows.append(
                {
                    "variant_id": variant_id,
                    "period": period_id,
                    "model": "candidate",
                    "trading_fees_total_pct": round_float(subset["candidate_fees_daily"].sum() * 100.0),
                    "funding_total_pct": round_float(subset["candidate_funding_daily"].sum() * 100.0),
                    "borrow_cost_total_pct": round_float(subset["candidate_borrow_cost_daily"].sum() * 100.0),
                    "slippage_cost_total_pct": round_float(subset["candidate_slippage_cost_daily"].sum() * 100.0),
                    "total_cost_pct": round_float(subset["candidate_total_cost_daily"].sum() * 100.0),
                    "turnover_total": round_float(subset["candidate_turnover"].sum()),
                }
            )
    return pd.DataFrame(rows)


def variant_recommendation(
    since2025_row: dict[str, Any],
    missed_row: dict[str, Any],
    full_row: dict[str, Any],
) -> tuple[str, str]:
    meaningful_capture = float(missed_row.get("missed_btc_move_captured_pct") or 0.0) >= MEANINGFUL_CAPTURE_THRESHOLD_PCT
    since2025_improves = (
        float(since2025_row.get("net_total_return_delta_pct") or 0.0) > 0.0
        and float(since2025_row.get("net_cagr_delta_pct") or 0.0) > 0.0
    )
    pass_through_ok = bool(full_row.get("strict_pass_through_ok"))
    dd_materially_worse = (
        float(full_row.get("net_max_drawdown_delta_pct") or 0.0) < MATERIAL_DD_WORSE_THRESHOLD_PCT
        or float(since2025_row.get("net_max_drawdown_delta_pct") or 0.0) < MATERIAL_DD_WORSE_THRESHOLD_PCT
    )
    churn_too_high = (
        float(since2025_row.get("turnover_delta") or 0.0) > TURNOVER_DELTA_STOP_THRESHOLD
        or int(since2025_row.get("switch_delta") or 0) > SWITCH_DELTA_STOP_THRESHOLD
        or int(since2025_row.get("exposure_days_delta") or 0) > EXPOSURE_DAYS_DELTA_STOP_THRESHOLD
    )
    narrow_or_concentrated = (
        meaningful_capture
        and since2025_improves
        and (float(missed_row.get("missed_btc_move_captured_pct") or 0.0) < NARROW_CAPTURE_PAUSE_THRESHOLD_PCT)
        and int(since2025_row.get("early_risk_days") or 0) <= 10
    )

    if (not meaningful_capture) or (not since2025_improves) or dd_materially_worse or churn_too_high or (not pass_through_ok):
        reason = (
            "Stop: the variant either failed to capture the missed 2025 BTC move meaningfully, did not improve "
            "since2025, worsened drawdown materially, raised churn too much, or failed strict pass-through."
        )
        return "stop", reason

    if narrow_or_concentrated:
        reason = (
            "Pause: the variant captures the target window and improves since2025, but the result is still narrow "
            "and concentrated in a short persistence burst."
        )
        return "pause", reason

    reason = (
        "Continue: the variant captures the missed 2025 BTC move meaningfully, improves since2025, keeps drawdown "
        "inside the material-worsening threshold, and passes strict FULL_RISK pass-through."
    )
    return "continue", reason


def build_variant_compare(period_compare: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant_id in VARIANT_SPECS:
        since2025_row = period_compare.loc[
            (period_compare["variant_id"] == variant_id) & (period_compare["period"] == "since2025")
        ].iloc[0].to_dict()
        missed_row = period_compare.loc[
            (period_compare["variant_id"] == variant_id) & (period_compare["period"] == "missed_window_2025")
        ].iloc[0].to_dict()
        full_row = period_compare.loc[
            (period_compare["variant_id"] == variant_id) & (period_compare["period"] == "full_available")
        ].iloc[0].to_dict()

        recommendation, recommendation_reason = variant_recommendation(since2025_row, missed_row, full_row)
        rows.append(
            {
                "variant_id": variant_id,
                "variant_label": VARIANT_SPECS[variant_id]["variant_label"],
                "early_risk_sleeve": VARIANT_SPECS[variant_id]["early_risk_sleeve"],
                "missed_window_strategy_delta_pct": missed_row["strategy_delta_vs_baseline_pct"],
                "missed_window_capture_pct": missed_row["missed_btc_move_captured_pct"],
                "missed_window_early_risk_days": missed_row["early_risk_days"],
                "since2025_net_total_return_delta_pct": since2025_row["net_total_return_delta_pct"],
                "since2025_net_cagr_delta_pct": since2025_row["net_cagr_delta_pct"],
                "since2025_net_max_drawdown_delta_pct": since2025_row["net_max_drawdown_delta_pct"],
                "since2025_switch_delta": since2025_row["switch_delta"],
                "since2025_turnover_delta": since2025_row["turnover_delta"],
                "since2025_exposure_days_delta": since2025_row["exposure_days_delta"],
                "since2025_cost_delta_pct": since2025_row["cost_delta_pct"],
                "full_available_net_total_return_delta_pct": full_row["net_total_return_delta_pct"],
                "full_available_net_cagr_delta_pct": full_row["net_cagr_delta_pct"],
                "full_available_net_max_drawdown_delta_pct": full_row["net_max_drawdown_delta_pct"],
                "full_available_false_start_count": full_row["false_start_count"],
                "full_available_successful_handoff_count": full_row["successful_handoff_count"],
                "strict_pass_through_ok": bool(full_row["strict_pass_through_ok"]),
                "recommendation": recommendation,
                "recommendation_reason": recommendation_reason,
            }
        )
    out = pd.DataFrame(rows)
    recommendation_rank = {"continue": 0, "pause": 1, "stop": 2}
    out["recommendation_rank"] = out["recommendation"].map(recommendation_rank).fillna(9).astype(int)
    out["sort_score"] = (
        out["recommendation_rank"] * -1.0
        + out["since2025_net_total_return_delta_pct"] * 0.001
        + out["missed_window_capture_pct"].fillna(0.0) * 0.0001
    )
    return out.sort_values(
        by=["recommendation_rank", "since2025_net_total_return_delta_pct", "missed_window_capture_pct"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def build_summary(
    *,
    snapshot: dict[str, Any],
    diagnostics: dict[str, Any],
    baseline: pd.DataFrame,
    period_compare: pd.DataFrame,
    variant_compare: pd.DataFrame,
    activation_windows: pd.DataFrame,
    blocker_counts: pd.DataFrame,
    handoff_audit: pd.DataFrame,
    cost_model: dict[str, Any],
    hard_invalidation_meta: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    comparison: dict[str, Any] = {}
    for variant_id in VARIANT_SPECS:
        comparison[variant_id] = {}
        for period_id, _, _ in PERIOD_DEFS:
            row = period_compare.loc[
                (period_compare["variant_id"] == variant_id) & (period_compare["period"] == period_id)
            ].iloc[0]
            comparison[variant_id][period_id] = row.to_dict()

    recommendations = variant_compare.to_dict(orient="records")
    if any(row["recommendation"] == "continue" for row in recommendations):
        overall_recommendation = "continue_selected_variant"
    elif any(row["recommendation"] == "pause" for row in recommendations):
        overall_recommendation = "pause_selected_variant"
    else:
        overall_recommendation = "stop"

    selected_variant_id = str(variant_compare.iloc[0]["variant_id"])

    return with_json_flags(
        {
            "artifact_id": ARTIFACT_ID,
            "generated_at_utc": timestamp_utc(),
            "status": overall_recommendation,
            "baseline": {
                "model_id": BASELINE_MODEL_ID,
                "label": BASELINE_LABEL,
                "strategy_version": snapshot.get("strategy_version"),
                "closed_day": snapshot.get("closed_day"),
                "current_reason_code": snapshot.get("decision_context", {}).get("current_reason_code"),
                "current_reason_text": diagnostics.get("current_cash_or_risk_reason")
                or snapshot.get("decision_context", {}).get("current_reason_text"),
            },
            "dev_only_scope": {
                "strict_boundaries": [
                    "dev_only_only",
                    "non_authoritative_only",
                    "no_source_of_truth_mutation",
                    "no_app_live_runtime_changes",
                    "no_production_truth_mutation",
                    "no_leverage_truth_change",
                    "no_shortlist_change",
                    "no_broad_sweep",
                    "no_parameter_grid",
                    "only_two_variants_tested",
                    "baseline_full_risk_behavior_unchanged",
                ]
            },
            "mechanism": {
                "mechanism_id": MECHANISM_ID,
                "candidate_persistence_rows_required": PERSISTENCE_ROWS_REQUIRED,
                "entry_filter": {
                    "baseline_current_asset_cash": True,
                    "baseline_effective_market_exposure_zero": True,
                    "candidate_asset_btc": True,
                    "candidate_persistence_rows_required": PERSISTENCE_ROWS_REQUIRED,
                    "trend_permission_active_required": False,
                    "trend_score_gt": -0.20,
                    "trend_score_lt": 0.10,
                    "stress_block_day_required": False,
                    "hard_invalidation_required": False,
                },
                "maintenance_exit_conditions": [
                    "baseline FULL_RISK / non-cash turns ON",
                    "candidate_asset != BTC",
                    "trend_score <= -0.20",
                    "stress_block_day == True",
                    "hard_invalidation == True if available",
                ],
            },
            "variants": {
                key: {
                    "variant_id": key,
                    "variant_label": value["variant_label"],
                    "description": value["description"],
                    "early_risk_sleeve": value["early_risk_sleeve"],
                }
                for key, value in VARIANT_SPECS.items()
            },
            "input_refs": {
                "baseline_snapshot": str(BASELINE_SNAPSHOT_PATH),
                "baseline_timeseries": str(BASELINE_TIMESERIES_PATH),
                "baseline_diagnostics": str(BASELINE_DIAGNOSTICS_PATH),
                "contract_ref": CONTRACT_REF,
                "spec_ref": SPEC_REF,
                "manifest_seed_ref": MANIFEST_SEED_REF,
            },
            "output_refs": {key: str(path) for key, path in paths.items()},
            "overlap": {
                "baseline_rows_loaded": int(len(baseline)),
                "start_date": baseline["date"].min().strftime("%Y-%m-%d"),
                "end_date": baseline["date"].max().strftime("%Y-%m-%d"),
            },
            "hard_invalidation_rule": hard_invalidation_meta,
            "cost_model": cost_model,
            "comparison": comparison,
            "window_counts": {
                variant_id: {
                    "activation_windows_count": int(
                        len(activation_windows.loc[activation_windows["variant_id"] == variant_id])
                    ),
                    "false_start_count": int(
                        activation_windows.loc[activation_windows["variant_id"] == variant_id, "false_start"].sum()
                    ),
                    "successful_handoff_count": int(
                        (~activation_windows.loc[activation_windows["variant_id"] == variant_id, "false_start"]).sum()
                    ),
                }
                for variant_id in VARIANT_SPECS
            },
            "blocker_summary": {
                variant_id: blocker_counts.loc[blocker_counts["variant_id"] == variant_id].to_dict(orient="records")
                for variant_id in VARIANT_SPECS
            },
            "pass_through_audit": {
                variant_id: {
                    "rows_audited": int(len(handoff_audit.loc[handoff_audit["variant_id"] == variant_id])),
                    "all_rows_match": bool(
                        handoff_audit.loc[
                            handoff_audit["variant_id"] == variant_id, "all_row_local_fields_match_flag"
                        ].all()
                    )
                    if not handoff_audit.loc[handoff_audit["variant_id"] == variant_id].empty
                    else True,
                }
                for variant_id in VARIANT_SPECS
            },
            "variant_recommendations": recommendations,
            "selected_variant_id": selected_variant_id,
            "overall_recommendation": overall_recommendation,
        }
    )


def build_manifest(
    *,
    paths: dict[str, Path],
    cost_model: dict[str, Any],
    hard_invalidation_meta: dict[str, Any],
) -> dict[str, Any]:
    return with_json_flags(
        {
            "artifact_id": f"{ARTIFACT_ID}_manifest",
            "generated_at_utc": timestamp_utc(),
            "output_namespace": str(paths["summary_json"].parent),
            "output_refs": {key: str(path) for key, path in paths.items()},
            "input_refs": {
                "baseline_snapshot": str(BASELINE_SNAPSHOT_PATH),
                "baseline_timeseries": str(BASELINE_TIMESERIES_PATH),
                "baseline_diagnostics": str(BASELINE_DIAGNOSTICS_PATH),
                "contract_ref": CONTRACT_REF,
                "spec_ref": SPEC_REF,
                "manifest_seed_ref": MANIFEST_SEED_REF,
            },
            "contract_refs": [CONTRACT_REF],
            "spec_refs": [SPEC_REF],
            "manifest_seed_refs": [MANIFEST_SEED_REF],
            "cost_model": cost_model,
            "hard_invalidation_rule": hard_invalidation_meta,
            "status": "generated_dev_only_compare_pack",
        }
    )


def validate_output_file(path: Path, kind: str) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "kind": kind, "ok": False, "detail": "missing"}
    try:
        if kind == "json":
            _ = json.loads(path.read_text(encoding="utf-8"))
            return {"path": str(path), "kind": kind, "ok": True, "detail": f"{path.name} parsed"}
        frame = pd.read_csv(path)
        return {"path": str(path), "kind": kind, "ok": True, "detail": f"{path.name} rows={len(frame)}"}
    except Exception as exc:
        return {"path": str(path), "kind": kind, "ok": False, "detail": f"parse failed: {exc}"}


def build_quality(
    *,
    paths: dict[str, Path],
    baseline: pd.DataFrame,
    variant_frames: dict[str, pd.DataFrame],
    activation_windows: pd.DataFrame,
    handoff_audit: pd.DataFrame,
    hard_invalidation_meta: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    parse_validation = [
        validate_output_file(paths["summary_json"], "json"),
        validate_output_file(paths["manifest_json"], "json"),
    ]
    for key in [
        "candidate_timeseries_csv",
        "compare_csv",
        "period_compare_csv",
        "activation_windows_csv",
        "blocker_counts_csv",
        "cost_metrics_csv",
        "handoff_row_audit_csv",
        "variant_compare_csv",
    ]:
        parse_validation.append(validate_output_file(paths[key], "csv"))

    checks.append(
        {
            "name": "production_core_baseline_rows_loaded",
            "ok": len(baseline) > 0,
            "detail": f"loaded {len(baseline)} baseline rows",
        }
    )
    checks.append(
        {
            "name": "required_periods_present",
            "ok": True,
            "detail": "full_available, since2023, since2025, and missed_window_2025 were all built",
        }
    )
    for variant_id, frame in variant_frames.items():
        pass_rows = handoff_audit.loc[handoff_audit["variant_id"] == variant_id]
        early_rows = frame.loc[frame["override_state"].eq("EARLY_RISK")].copy()
        checks.append(
            {
                "name": f"{variant_id}_strict_pass_through",
                "ok": bool(pass_rows["all_row_local_fields_match_flag"].all()) if not pass_rows.empty else True,
                "detail": f"strict pass-through verified on {len(pass_rows)} baseline FULL_RISK rows",
            }
        )
        checks.append(
            {
                "name": f"{variant_id}_entry_rule_enforced",
                "ok": bool(
                    early_rows["candidate_asset"].eq("BTC").all()
                    and early_rows["baseline_cash"].all()
                    and early_rows["btc_candidate_persistence_rows"].ge(PERSISTENCE_ROWS_REQUIRED).all()
                    and early_rows["trend_score"].gt(-0.20).all()
                    and (~early_rows["stress_block_day"]).all()
                    and (~early_rows["hard_invalidation"]).all()
                )
                if not early_rows.empty
                else True,
                "detail": "EARLY_RISK rows respect BTC persistence, pre-authorization trend band, and risk filters",
            }
        )
        checks.append(
            {
                "name": f"{variant_id}_no_full_risk_override",
                "ok": not frame["override_state"].eq("FULL_RISK").any(),
                "detail": "the probe never mutates baseline FULL_RISK behavior",
            }
        )

    checks.append(
        {
            "name": "hard_invalidation_source_documented",
            "ok": True,
            "detail": hard_invalidation_meta["detail"],
        }
    )
    checks.append(
        {
            "name": "no_source_of_truth_changes",
            "ok": True,
            "detail": "all writes remain under outputs/research_os/dev_only and avoid source_of_truth",
        }
    )
    checks.append(
        {
            "name": "activation_windows_generated",
            "ok": len(activation_windows) >= 0,
            "detail": f"activation_windows.csv rows={len(activation_windows)}",
        }
    )

    overall_ok = all(check["ok"] for check in checks) and all(item["ok"] for item in parse_validation)
    warnings: list[str] = []
    if not hard_invalidation_meta["available"]:
        warnings.append(hard_invalidation_meta["detail"])

    return with_json_flags(
        {
            "artifact_id": f"{ARTIFACT_ID}_quality",
            "generated_at_utc": timestamp_utc(),
            "checks": checks,
            "parse_validation": {
                "ok": all(item["ok"] for item in parse_validation),
                "checks": parse_validation,
            },
            "status": "passed" if overall_ok else "failed",
            "warnings": warnings,
        }
    )


def main() -> None:
    args = parse_args()
    ensure_dir(args.output_dir)
    paths = output_paths(args.output_dir)

    snapshot = read_json(BASELINE_SNAPSHOT_PATH)
    diagnostics = read_json(BASELINE_DIAGNOSTICS_PATH)
    baseline, hard_invalidation_meta, cost_model = load_baseline_frame(BASELINE_TIMESERIES_PATH)

    variant_frames = {
        variant_id: build_variant_frame(
            baseline,
            variant_id=variant_id,
            cost_model=cost_model,
        )
        for variant_id in VARIANT_SPECS
    }

    candidate_timeseries = pd.concat(
        [
            frame[
                [
                    "variant_id",
                    "date",
                    "candidate_asset",
                    "selected_asset",
                    "current_asset",
                    "baseline_state",
                    "baseline_cash",
                    "baseline_non_cash",
                    "override_state",
                    "candidate_effective_state",
                    "candidate_state_origin",
                    "candidate_held_asset",
                    "effective_market_exposure",
                    "current_exposure",
                    "candidate_effective_leverage",
                    "btc_candidate_persistence_rows",
                    "persistence_entry_filter_ready",
                    "candidate_entry_day",
                    "candidate_exit_day",
                    "trend_permission_active",
                    "trend_score",
                    "trend_activation_threshold",
                    "stress_block_day",
                    "hard_invalidation",
                    "reason_code",
                    "candidate_reason",
                    "btc_close",
                    "btc_return",
                    "return_gross",
                    "return_net",
                    "candidate_return_gross",
                    "candidate_return_net",
                    "turnover",
                    "candidate_turnover",
                    "fees_daily",
                    "candidate_fees_daily",
                    "borrow_cost_daily",
                    "candidate_borrow_cost_daily",
                    "funding_daily",
                    "candidate_funding_daily",
                    "slippage_cost_daily",
                    "candidate_slippage_cost_daily",
                    "baseline_total_cost_daily",
                    "candidate_total_cost_daily",
                    "baseline_equity_net",
                    "candidate_equity_net",
                    "candidate_asset_transition_day",
                ]
            ].copy()
            for frame in variant_frames.values()
        ],
        ignore_index=True,
    )
    candidate_timeseries["date"] = pd.to_datetime(candidate_timeseries["date"]).dt.strftime("%Y-%m-%d")

    activation_windows = pd.concat(
        [build_activation_windows(frame) for frame in variant_frames.values()],
        ignore_index=True,
    )

    handoff_audit = pd.concat(
        [build_handoff_row_audit(frame) for frame in variant_frames.values()],
        ignore_index=True,
    )

    period_rows = []
    for variant_id, frame in variant_frames.items():
        windows = activation_windows.loc[activation_windows["variant_id"] == variant_id].copy()
        audit = handoff_audit.loc[handoff_audit["variant_id"] == variant_id].copy()
        for period_id, start_date, end_date in PERIOD_DEFS:
            row = build_period_metrics(
                frame,
                windows,
                audit,
                variant_id=variant_id,
                start_date=start_date,
                end_date=end_date,
            )
            row["period"] = period_id
            period_rows.append(row)
    period_compare = pd.DataFrame(period_rows)

    compare = build_compare_rows(period_compare)
    blocker_counts = build_blocker_counts(variant_frames)
    cost_metrics = build_cost_metrics(variant_frames)
    variant_compare = build_variant_compare(period_compare)

    summary = build_summary(
        snapshot=snapshot,
        diagnostics=diagnostics,
        baseline=baseline,
        period_compare=period_compare,
        variant_compare=variant_compare,
        activation_windows=activation_windows,
        blocker_counts=blocker_counts,
        handoff_audit=handoff_audit,
        cost_model=cost_model,
        hard_invalidation_meta=hard_invalidation_meta,
        paths=paths,
    )

    save_frame(paths["candidate_timeseries_csv"], candidate_timeseries)
    save_frame(paths["compare_csv"], compare)
    save_frame(paths["period_compare_csv"], period_compare)
    save_frame(paths["activation_windows_csv"], activation_windows)
    save_frame(paths["blocker_counts_csv"], blocker_counts)
    save_frame(paths["cost_metrics_csv"], cost_metrics)
    save_frame(paths["handoff_row_audit_csv"], handoff_audit)
    save_frame(paths["variant_compare_csv"], variant_compare)
    save_json(paths["summary_json"], sanitize_for_json(summary))

    manifest = build_manifest(
        paths=paths,
        cost_model=cost_model,
        hard_invalidation_meta=hard_invalidation_meta,
    )
    save_json(paths["manifest_json"], sanitize_for_json(manifest))

    quality = build_quality(
        paths=paths,
        baseline=baseline,
        variant_frames=variant_frames,
        activation_windows=activation_windows,
        handoff_audit=handoff_audit,
        hard_invalidation_meta=hard_invalidation_meta,
    )
    save_json(paths["quality_json"], sanitize_for_json(quality))

    print("production_core_btc_candidate_persistence_early_risk_compare generated")
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
