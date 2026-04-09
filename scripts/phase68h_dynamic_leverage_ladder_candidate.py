from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

PHASE66G_DIR = OUTPUTS / "phase66g_production_candidate_live"
DEFAULT_GOVERNANCE_PAPER = PHASE66G_DIR / "phase66g_production_soft_filters_paper.csv"
DEFAULT_TREND = PHASE66G_DIR / "phase66g_trend_barometer_history.csv"
DEFAULT_DECISIONS = PHASE66G_DIR / "phase66g_production_candidate_decisions.csv"

PHASE68H_DIR = OUTPUTS / "phase68h_dynamic_leverage_ladder_candidate"


@dataclass(frozen=True)
class ValidationVariant:
    model: str
    mode: str  # static | dynamic
    target_leverage: float


VARIANTS: list[ValidationVariant] = [
    ValidationVariant("phase68h_66g_1p00x_portfolio_exposure_baseline", "static", 1.00),
    ValidationVariant("phase68h_66g_1p25x_static_reference", "static", 1.25),
    ValidationVariant("phase68h_66g_1p50x_static_reference", "static", 1.50),
    ValidationVariant("phase68h_dynamic_ladder_candidate", "dynamic", 0.0),
]


BLANK_OVERRIDE_MARKERS = {"", "NAN", "NONE", "NULL", "BASELINE", "CORE"}
CASH_EQUIVALENT_ASSETS = {"", "CASH", "USD", "USDT", "NAN", "NONE", "NULL"}


def log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def pick_col(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    lower_map = {str(c).lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    raise KeyError(f"Chýba required column pre {label}. Kandidáti: {candidates}")


def try_pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {str(c).lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def normalize_asset_label(raw: str) -> str:
    s = str(raw).strip().upper()
    if s in {"", "NAN", "NONE", "NULL", "BASELINE", "CORE"}:
        return "CASH"
    return s


def resolve_fee_rate_bps(
    fee_side_mode: str,
    taker_fee_bps: float,
    maker_fee_bps: float,
    staking_discount_pct: float,
    referral_discount_pct: float,
) -> float:
    side_mode = str(fee_side_mode).strip().lower()
    if side_mode == "taker":
        base_fee_bps = float(taker_fee_bps)
    elif side_mode == "maker":
        base_fee_bps = float(maker_fee_bps)
    elif side_mode == "mixed":
        base_fee_bps = (float(taker_fee_bps) + float(maker_fee_bps)) / 2.0
    else:
        raise ValueError(f"Unsupported fee_side_mode: {fee_side_mode}")

    effective_multiplier = (
        (1.0 - (float(staking_discount_pct) / 100.0))
        * (1.0 - (float(referral_discount_pct) / 100.0))
    )
    return max(base_fee_bps * effective_multiplier, 0.0)


def find_baseline_paper_in_phase66g_dir() -> Path:
    candidates = sorted(
        [
            p
            for p in PHASE66G_DIR.glob("*_paper.csv")
            if p.name.lower() != "phase66g_production_soft_filters_paper.csv"
        ]
    )
    if not candidates:
        raise FileNotFoundError(
            "Nenašiel sa baseline paper copy v phase66g output directory. "
            "Očakávam aspoň jeden *_paper.csv okrem phase66g_production_soft_filters_paper.csv"
        )
    if len(candidates) > 1:
        log(f"[PHASE68H] baseline paper autodiscovery candidates: {[str(p) for p in candidates]}")
    return candidates[0]


def load_governance_paper(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    date_col = pick_col(df, ["date", "ts", "datetime", "timestamp"], "date")
    ret_col = pick_col(
        df,
        ["strategy_ret", "daily_ret", "ret", "return", "strategy_return", "portfolio_ret", "equity_ret"],
        "strategy_ret",
    )
    chosen_col = try_pick_col(
        df,
        ["chosen_asset", "held_asset_public", "selected_asset", "asset", "weekly_authorized_asset", "current_asset"],
    )

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)
    out["base_ret"] = pd.to_numeric(df[ret_col], errors="coerce").fillna(0.0)
    out["overlay_candidate_raw"] = df[chosen_col].astype(str).fillna("") if chosen_col is not None else ""

    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    return out


def load_baseline_paper(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    date_col = pick_col(df, ["date", "ts", "datetime", "timestamp"], "date")
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)

    asset_col = try_pick_col(
        df,
        [
            "executed_position",
            "executed_regime",
            "held_asset_public",
            "portfolio_held_asset",
            "selected_asset",
            "asset",
            "current_asset",
            "weekly_authorized_asset",
            "chosen_asset",
            "symbol",
            "ticker",
            "position_asset",
            "regime_asset",
            "selected_symbol",
            "selected_ticker",
        ],
    )
    exposure_col = try_pick_col(
        df,
        [
            "gross_exposure",
            "exposure",
            "strategy_gross_exposure",
            "position_exposure",
            "portfolio_exposure",
            "is_exposed",
            "in_market",
            "risk_on",
            "invested",
        ],
    )
    cash_col = try_pick_col(
        df,
        ["cash_day", "is_cash", "cash_flag", "in_cash", "risk_off"],
    )
    ret_col = try_pick_col(
        df,
        [
            "strategy_ret",
            "daily_ret",
            "ret",
            "return",
            "strategy_return",
            "portfolio_ret",
            "equity_ret",
        ],
    )

    if asset_col is not None:
        out["baseline_held_asset"] = df[asset_col].astype(str).map(normalize_asset_label)
        out["baseline_asset_source"] = f"asset_col:{asset_col}"

    elif exposure_col is not None:
        exposure_series = pd.to_numeric(df[exposure_col], errors="coerce").fillna(0.0)
        out["baseline_held_asset"] = np.where(exposure_series > 0.0, "BASELINE_RISK", "CASH")
        out["baseline_asset_source"] = f"exposure_col:{exposure_col}"

    elif cash_col is not None:
        raw_cash = df[cash_col]
        if pd.api.types.is_bool_dtype(raw_cash):
            cash_mask = raw_cash.fillna(False)
        else:
            cash_mask = (
                raw_cash.astype(str)
                .str.strip()
                .str.upper()
                .isin(["1", "TRUE", "YES", "Y", "CASH"])
            )
        out["baseline_held_asset"] = np.where(cash_mask, "CASH", "BASELINE_RISK")
        out["baseline_asset_source"] = f"cash_col:{cash_col}"

    elif ret_col is not None:
        ret_series = pd.to_numeric(df[ret_col], errors="coerce").fillna(0.0)
        inferred_series = pd.Series(
            np.where(np.abs(ret_series) > 1e-12, "BASELINE_RISK", None),
            index=df.index,
            dtype="object",
        ).ffill().bfill().fillna("CASH")
        out["baseline_held_asset"] = inferred_series
        out["baseline_asset_source"] = f"ret_fallback:{ret_col}"

    else:
        out["baseline_held_asset"] = "BASELINE_RISK"
        out["baseline_asset_source"] = "hard_fallback_all_exposed"

    out["baseline_held_asset"] = out["baseline_held_asset"].map(normalize_asset_label)
    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)

    if not out.empty:
        log(f"[PHASE68H] baseline asset source: {out['baseline_asset_source'].iloc[0]}")

    return out[["date", "baseline_held_asset", "baseline_asset_source"]].copy()


def build_portfolio_exposure_frame(governance_df: pd.DataFrame, baseline_df: pd.DataFrame) -> pd.DataFrame:
    out = governance_df.merge(baseline_df, on="date", how="left")

    if out["baseline_held_asset"].isna().any():
        out["baseline_held_asset"] = out["baseline_held_asset"].ffill().bfill().fillna("CASH")

    out["overlay_candidate_clean"] = out["overlay_candidate_raw"].astype(str).str.strip().str.upper()
    out["use_baseline_exposure"] = out["overlay_candidate_clean"].isin(BLANK_OVERRIDE_MARKERS)

    out["portfolio_held_asset"] = np.where(
        out["use_baseline_exposure"],
        out["baseline_held_asset"].astype(str),
        out["overlay_candidate_clean"].map(normalize_asset_label),
    )
    out["portfolio_held_asset"] = pd.Series(out["portfolio_held_asset"], index=out.index).map(normalize_asset_label)
    out["is_exposed"] = ~out["portfolio_held_asset"].isin(["CASH", "USD", "USDT"])
    return out


def load_trend_history(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    date_col = pick_col(df, ["date", "ts", "datetime", "timestamp"], "date")
    trend_score_col = pick_col(df, ["trend_score"], "trend_score")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)
    out["trend_score"] = pd.to_numeric(df[trend_score_col], errors="coerce")

    for key in ["trend_state_label", "buy_threshold", "prev_trend_score", "crossed_up_today", "crossed_down_today"]:
        col = try_pick_col(df, [key])
        if col is not None:
            out[key] = df[col]

    out = out.dropna(subset=["date"]).sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    return out


def load_governance_decisions(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Decisions file sa nenašiel: {path}")

    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "decision_date",
                "period_start",
                "period_end",
                "selected_asset",
                "selected",
                "governed_asset",
            ]
        )

    date_col = pick_col(df, ["decision_date", "date", "ts", "datetime"], "decision_date")
    asset_col = pick_col(df, ["selected_asset", "asset", "chosen_asset", "weekly_authorized_asset"], "selected_asset")

    tmp = pd.DataFrame()
    tmp["decision_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)
    tmp["period_start"] = pd.to_datetime(df["period_start"], errors="coerce").dt.tz_localize(None) if "period_start" in df.columns else pd.NaT
    tmp["period_end"] = pd.to_datetime(df["period_end"], errors="coerce").dt.tz_localize(None) if "period_end" in df.columns else pd.NaT
    tmp["selected_asset"] = df[asset_col].astype(str)
    tmp["selected"] = pd.to_numeric(df["selected"], errors="coerce").fillna(0).astype(int) if "selected" in df.columns else 1
    tmp["governed_asset"] = tmp["selected_asset"].map(normalize_asset_label)
    tmp = tmp.dropna(subset=["decision_date"]).sort_values("decision_date").reset_index(drop=True)
    return tmp


def build_governance_transition_calendar(
    decisions_df: pd.DataFrame,
    paper_dates: pd.Series,
) -> tuple[pd.DataFrame, int, dict]:
    meta = {
        "decision_rows_total": int(len(decisions_df)),
        "selected_rows_used": 0,
        "governance_switch_rows": 0,
        "mapped_transition_rows": 0,
        "unmapped_transition_rows": 0,
        "mapping_sources": {},
    }

    if decisions_df.empty:
        empty = pd.DataFrame(
            columns=[
                "decision_date",
                "period_start",
                "period_end",
                "prev_governed_asset",
                "governed_asset",
                "execution_day",
                "execution_source",
            ]
        )
        return empty, 0, meta

    selected_rows = decisions_df.loc[decisions_df["selected"] == 1].copy()
    if selected_rows.empty:
        selected_rows = decisions_df.copy()

    selected_rows = selected_rows.sort_values("decision_date").reset_index(drop=True)
    meta["selected_rows_used"] = int(len(selected_rows))

    selected_rows["prev_governed_asset"] = selected_rows["governed_asset"].shift(1)
    selected_rows["governance_switch"] = (
        (selected_rows["governed_asset"] != selected_rows["prev_governed_asset"])
        & selected_rows["prev_governed_asset"].notna()
    )

    switch_rows = selected_rows.loc[selected_rows["governance_switch"]].copy().reset_index(drop=True)
    governance_switch_count = int(len(switch_rows))
    meta["governance_switch_rows"] = governance_switch_count

    if switch_rows.empty:
        empty = pd.DataFrame(
            columns=[
                "decision_date",
                "period_start",
                "period_end",
                "prev_governed_asset",
                "governed_asset",
                "execution_day",
                "execution_source",
            ]
        )
        return empty, governance_switch_count, meta

    paper_dates_sorted = pd.Series(pd.to_datetime(paper_dates).dropna().sort_values().unique())

    def first_paper_date_on_or_after(ts: pd.Timestamp) -> pd.Timestamp | pd.NaT:
        if pd.isna(ts):
            return pd.NaT
        eligible = paper_dates_sorted.loc[paper_dates_sorted >= ts]
        if eligible.empty:
            return pd.NaT
        return pd.Timestamp(eligible.iloc[0])

    execution_days = []
    execution_sources = []

    for _, row in switch_rows.iterrows():
        execution_day = pd.NaT
        source = "unmapped"

        if pd.notna(row["period_start"]):
            execution_day = first_paper_date_on_or_after(pd.Timestamp(row["period_start"]))
            if pd.notna(execution_day):
                source = "period_start"

        if pd.isna(execution_day):
            execution_day = first_paper_date_on_or_after(pd.Timestamp(row["decision_date"]))
            if pd.notna(execution_day):
                source = "decision_date_fallback"

        execution_days.append(execution_day)
        execution_sources.append(source)

    switch_rows["execution_day"] = execution_days
    switch_rows["execution_source"] = execution_sources

    mapped = switch_rows.loc[switch_rows["execution_day"].notna()].copy()
    if not mapped.empty:
        mapped = mapped.sort_values(["execution_day", "decision_date"]).drop_duplicates(
            subset=["execution_day"], keep="last"
        ).reset_index(drop=True)

    meta["mapped_transition_rows"] = int(len(mapped))
    meta["unmapped_transition_rows"] = int(len(switch_rows) - len(mapped))
    meta["mapping_sources"] = mapped["execution_source"].value_counts(dropna=False).to_dict() if not mapped.empty else {}

    return mapped[
        [
            "decision_date",
            "period_start",
            "period_end",
            "prev_governed_asset",
            "governed_asset",
            "execution_day",
            "execution_source",
        ]
    ].copy(), governance_switch_count, meta


def add_daily_position_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    prev_asset = out["portfolio_held_asset"].shift(1)
    out["asset_transition_day"] = ((out["portfolio_held_asset"] != prev_asset) & prev_asset.notna()).fillna(False)

    days_in_position: list[int] = []
    current_asset = None
    counter = 0
    for asset in out["portfolio_held_asset"].astype(str):
        if asset != current_asset:
            current_asset = asset
            counter = 1
        else:
            counter += 1
        days_in_position.append(counter)

    out["days_in_position"] = days_in_position
    out["switch_day_forced_1x"] = out["is_exposed"] & out["asset_transition_day"]
    out["entry_buffer_day_forced_1x"] = out["is_exposed"] & (~out["asset_transition_day"]) & (out["days_in_position"] == 2)
    return out


def add_baseline_stress_state(df: pd.DataFrame, lookback_days: int, off_threshold: float, on_threshold: float) -> pd.DataFrame:
    out = df.copy()

    out["baseline_equity_curve"] = (1.0 + out["base_ret"]).cumprod()
    rolling_peak = out["baseline_equity_curve"].rolling(lookback_days, min_periods=1).max()
    out["baseline_dd_lookback"] = (out["baseline_equity_curve"] / rolling_peak) - 1.0

    stress_active: list[bool] = []
    active = False
    for dd in out["baseline_dd_lookback"].astype(float):
        if not active and dd <= off_threshold:
            active = True
        elif active and dd >= on_threshold:
            active = False
        stress_active.append(active)

    out["stress_block_active"] = stress_active
    return out


def build_effective_leverage(
    merged: pd.DataFrame,
    variant: ValidationVariant,
    activation_threshold: float,
    dynamic_mid_threshold: float,
    dynamic_mid_leverage: float,
    dynamic_high_leverage: float,
) -> pd.Series:
    eff = pd.Series(1.0, index=merged.index, dtype=float)

    if variant.mode == "static":
        eff.loc[merged["leverage_eligible"]] = float(variant.target_leverage)
        return eff

    # dynamic ladder
    eligible = merged["leverage_eligible"]
    trend_score = pd.to_numeric(merged["trend_score"], errors="coerce").fillna(-999.0)

    high_mask = eligible & (trend_score >= dynamic_mid_threshold)
    mid_mask = eligible & (trend_score >= activation_threshold) & (trend_score < dynamic_mid_threshold)

    eff.loc[mid_mask] = float(dynamic_mid_leverage)
    eff.loc[high_mask] = float(dynamic_high_leverage)
    return eff


def build_validation_wrapper(
    portfolio_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    tradable_transition_df: pd.DataFrame,
    variant: ValidationVariant,
    annual_borrow_cost: float,
    tradable_transition_slippage_bps: float,
    trend_activation_threshold: float,
    stress_lookback_days: int,
    stress_off_threshold: float,
    stress_on_threshold: float,
    dynamic_mid_threshold: float,
    dynamic_mid_leverage: float,
    dynamic_high_leverage: float,
    fee_side_mode: str,
    taker_fee_bps: float,
    maker_fee_bps: float,
    staking_discount_pct: float,
    referral_discount_pct: float,
) -> pd.DataFrame:
    merged = portfolio_df.merge(trend_df, on="date", how="left")

    if merged["trend_score"].isna().any():
        merged["trend_score"] = merged["trend_score"].ffill().bfill()

    merged = add_daily_position_flags(merged)
    merged = add_baseline_stress_state(
        merged,
        lookback_days=stress_lookback_days,
        off_threshold=stress_off_threshold,
        on_threshold=stress_on_threshold,
    )

    tradable_day_map = {}
    if not tradable_transition_df.empty:
        tradable_day_map = tradable_transition_df.set_index("execution_day")["governed_asset"].to_dict()

    merged["tradable_transition_day"] = merged["date"].isin(list(tradable_day_map.keys()))
    merged["tradable_governed_asset"] = merged["date"].map(tradable_day_map).fillna("")

    merged["cash_day"] = ~merged["is_exposed"]
    merged["trend_gate_pass"] = pd.to_numeric(merged["trend_score"], errors="coerce").fillna(-999.0) >= trend_activation_threshold
    merged["trend_block_day"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_day_forced_1x"])
        & (~merged["trend_gate_pass"])
    )
    merged["stress_block_day"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_day_forced_1x"])
        & merged["trend_gate_pass"]
        & merged["stress_block_active"]
    )

    merged["leverage_eligible"] = (
        merged["is_exposed"]
        & (~merged["switch_day_forced_1x"])
        & (~merged["entry_buffer_day_forced_1x"])
        & merged["trend_gate_pass"]
        & (~merged["stress_block_active"])
    )

    merged["effective_leverage"] = build_effective_leverage(
        merged=merged,
        variant=variant,
        activation_threshold=float(trend_activation_threshold),
        dynamic_mid_threshold=float(dynamic_mid_threshold),
        dynamic_mid_leverage=float(dynamic_mid_leverage),
        dynamic_high_leverage=float(dynamic_high_leverage),
    )

    merged["target_leverage"] = np.where(
        variant.mode == "dynamic",
        np.nan,
        float(variant.target_leverage),
    )
    merged["dynamic_mode"] = variant.mode

    borrowed_fraction = np.maximum(merged["effective_leverage"] - 1.0, 0.0)
    daily_borrow_rate = float(annual_borrow_cost) / 365.25

    merged["daily_borrow_cost"] = borrowed_fraction * daily_borrow_rate

    tradable_slippage_rate = float(tradable_transition_slippage_bps) / 10000.0
    merged["tradable_slippage_cost"] = np.where(
        merged["tradable_transition_day"],
        tradable_slippage_rate,
        0.0,
    )

    merged["realistic_ret_gross"] = merged["base_ret"] * merged["effective_leverage"]
    merged["realistic_ret_before_trading_fees"] = (
        merged["realistic_ret_gross"] - merged["daily_borrow_cost"] - merged["tradable_slippage_cost"]
    )

    prev_asset = merged["portfolio_held_asset"].shift(1).astype(str).str.upper().fillna("")
    curr_asset = merged["portfolio_held_asset"].astype(str).str.upper().fillna("")
    prev_notional = np.where(
        prev_asset.isin(CASH_EQUIVALENT_ASSETS),
        0.0,
        pd.to_numeric(merged["effective_leverage"].shift(1), errors="coerce").fillna(0.0),
    )
    curr_notional = np.where(
        curr_asset.isin(CASH_EQUIVALENT_ASSETS),
        0.0,
        pd.to_numeric(merged["effective_leverage"], errors="coerce").fillna(0.0),
    )
    same_asset = prev_asset == curr_asset
    merged["trading_turnover_notional"] = np.where(
        same_asset,
        np.abs(curr_notional - prev_notional),
        prev_notional + curr_notional,
    )

    effective_trading_fee_bps = resolve_fee_rate_bps(
        fee_side_mode=fee_side_mode,
        taker_fee_bps=taker_fee_bps,
        maker_fee_bps=maker_fee_bps,
        staking_discount_pct=staking_discount_pct,
        referral_discount_pct=referral_discount_pct,
    )
    merged["fee_side_mode"] = str(fee_side_mode).strip().lower()
    merged["taker_fee_bps"] = float(taker_fee_bps)
    merged["maker_fee_bps"] = float(maker_fee_bps)
    merged["staking_discount_pct"] = float(staking_discount_pct)
    merged["referral_discount_pct"] = float(referral_discount_pct)
    merged["effective_trading_fee_bps"] = float(effective_trading_fee_bps)
    merged["trading_fees_daily"] = merged["trading_turnover_notional"] * (float(effective_trading_fee_bps) / 10000.0)
    merged["trading_fees_cumulative"] = merged["trading_fees_daily"].cumsum()

    merged["funding_daily"] = 0.0
    merged["funding_cumulative"] = merged["funding_daily"].cumsum()

    merged["realistic_ret_net"] = (
        merged["realistic_ret_before_trading_fees"] - merged["trading_fees_daily"] - merged["funding_daily"]
    )
    merged["realistic_ret_net"] = merged["realistic_ret_net"].clip(lower=-0.999999)
    merged["realistic_ret"] = merged["realistic_ret_net"]

    merged["equity_curve_gross"] = (1.0 + merged["realistic_ret_gross"]).cumprod()
    merged["equity_curve_net"] = (1.0 + merged["realistic_ret_net"]).cumprod()
    merged["equity_curve"] = merged["equity_curve_net"]
    merged["leverage_active"] = merged["effective_leverage"] > 1.0

    merged["leverage_state_reason"] = np.where(
        merged["cash_day"],
        "cash",
        np.where(
            merged["switch_day_forced_1x"],
            "switch_day",
            np.where(
                merged["entry_buffer_day_forced_1x"],
                "entry_buffer_day",
                np.where(
                    merged["stress_block_day"],
                    "stress_block",
                    np.where(
                        merged["trend_block_day"],
                        "trend_gate",
                        np.where(
                            merged["effective_leverage"] >= dynamic_high_leverage,
                            "dynamic_high_1p50",
                            np.where(
                                merged["effective_leverage"] >= dynamic_mid_leverage,
                                "dynamic_mid_1p25" if variant.mode == "dynamic" else "static_leverage_on",
                                "baseline_1x",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    merged["trend_activation_threshold"] = float(trend_activation_threshold)
    merged["stress_off_threshold"] = float(stress_off_threshold)
    merged["stress_on_threshold"] = float(stress_on_threshold)
    merged["tradable_transition_slippage_bps"] = float(tradable_transition_slippage_bps)
    merged["dynamic_mid_threshold"] = float(dynamic_mid_threshold)
    merged["dynamic_mid_leverage"] = float(dynamic_mid_leverage)
    merged["dynamic_high_leverage"] = float(dynamic_high_leverage)

    return merged


def compute_cagr_pct(ret_series: pd.Series, date_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return np.nan
    eq = (1.0 + ret_series.astype(float)).cumprod()
    start_dt = pd.to_datetime(date_series.iloc[0])
    end_dt = pd.to_datetime(date_series.iloc[-1])
    days = max((end_dt - start_dt).days, 1)
    years = days / 365.25
    if years <= 0:
        return np.nan
    return float(((eq.iloc[-1] ** (1.0 / years)) - 1.0) * 100.0)


def compute_max_drawdown_pct(ret_series: pd.Series) -> float:
    if len(ret_series) == 0:
        return np.nan
    eq = (1.0 + ret_series.astype(float)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min() * 100.0)


def subset_since(df: pd.DataFrame, start_date: str) -> pd.DataFrame:
    return df.loc[df["date"] >= pd.Timestamp(start_date)].copy().reset_index(drop=True)


def summarize_variant(
    model: str,
    df: pd.DataFrame,
    annual_borrow_cost: float,
    governance_switch_count: int,
    tradable_transition_count: int,
) -> dict:
    since2023 = subset_since(df, "2023-01-01")
    since2025 = subset_since(df, "2025-01-01")

    cagr_pct = compute_cagr_pct(df["realistic_ret"], df["date"])
    max_dd_pct = compute_max_drawdown_pct(df["realistic_ret"])
    calmar = np.nan
    if pd.notna(cagr_pct) and pd.notna(max_dd_pct) and abs(max_dd_pct) > 1e-9:
        calmar = cagr_pct / abs(max_dd_pct)

    return {
        "model": model,
        "mode": str(df["dynamic_mode"].iloc[0]),
        "target_leverage": pd.to_numeric(df["target_leverage"].iloc[0], errors="coerce"),
        "annual_borrow_cost_pct": float(annual_borrow_cost * 100.0),
        "fee_side_mode": str(df["fee_side_mode"].iloc[0]),
        "taker_fee_bps": float(df["taker_fee_bps"].iloc[0]),
        "maker_fee_bps": float(df["maker_fee_bps"].iloc[0]),
        "staking_discount_pct": float(df["staking_discount_pct"].iloc[0]),
        "referral_discount_pct": float(df["referral_discount_pct"].iloc[0]),
        "effective_trading_fee_bps": float(df["effective_trading_fee_bps"].iloc[0]),
        "tradable_transition_slippage_bps": float(df["tradable_transition_slippage_bps"].iloc[0]),
        "trend_activation_threshold": float(df["trend_activation_threshold"].iloc[0]),
        "dynamic_mid_threshold": float(df["dynamic_mid_threshold"].iloc[0]),
        "dynamic_mid_leverage": float(df["dynamic_mid_leverage"].iloc[0]),
        "dynamic_high_leverage": float(df["dynamic_high_leverage"].iloc[0]),
        "stress_off_threshold": float(df["stress_off_threshold"].iloc[0]),
        "stress_on_threshold": float(df["stress_on_threshold"].iloc[0]),
        "total_return_pct_gross": round(float((df["equity_curve_gross"].iloc[-1] - 1.0) * 100.0), 2) if not df.empty else np.nan,
        "total_return_pct_net": round(float((df["equity_curve_net"].iloc[-1] - 1.0) * 100.0), 2) if not df.empty else np.nan,
        "cagr_pct_gross": round(compute_cagr_pct(df["realistic_ret_gross"], df["date"]), 2),
        "cagr_pct_net": round(cagr_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "max_drawdown_pct_gross": round(compute_max_drawdown_pct(df["realistic_ret_gross"]), 2),
        "max_drawdown_pct_net": round(max_dd_pct, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "calmar": round(calmar, 4) if pd.notna(calmar) else np.nan,
        "since2023_cagr_pct_gross": round(compute_cagr_pct(since2023["realistic_ret_gross"], since2023["date"]), 2) if not since2023.empty else np.nan,
        "since2023_cagr_pct_net": round(compute_cagr_pct(since2023["realistic_ret"], since2023["date"]), 2) if not since2023.empty else np.nan,
        "since2023_cagr_pct": round(compute_cagr_pct(since2023["realistic_ret"], since2023["date"]), 2) if not since2023.empty else np.nan,
        "since2025_cagr_pct_gross": round(compute_cagr_pct(since2025["realistic_ret_gross"], since2025["date"]), 2) if not since2025.empty else np.nan,
        "since2025_cagr_pct_net": round(compute_cagr_pct(since2025["realistic_ret"], since2025["date"]), 2) if not since2025.empty else np.nan,
        "since2025_cagr_pct": round(compute_cagr_pct(since2025["realistic_ret"], since2025["date"]), 2) if not since2025.empty else np.nan,
        "worst_day_pct_gross": round(float(df["realistic_ret_gross"].min() * 100.0), 2) if not df.empty else np.nan,
        "worst_day_pct_net": round(float(df["realistic_ret"].min() * 100.0), 2) if not df.empty else np.nan,
        "worst_day_pct": round(float(df["realistic_ret"].min() * 100.0), 2) if not df.empty else np.nan,
        "borrow_cost_total_pct": round(float(df["daily_borrow_cost"].sum() * 100.0), 4),
        "tradable_slippage_cost_total_pct": round(float(df["tradable_slippage_cost"].sum() * 100.0), 4),
        "trading_turnover_notional_total": round(float(df["trading_turnover_notional"].sum()), 6),
        "trading_fees_total_pct": round(float(df["trading_fees_daily"].sum() * 100.0), 4),
        "funding_total_pct": round(float(df["funding_daily"].sum() * 100.0), 4),
        "governance_switch_count": int(governance_switch_count),
        "exposure_days": int(df["is_exposed"].sum()),
        "asset_transition_count": int(df["asset_transition_day"].sum()),
        "tradable_transition_count": int(tradable_transition_count),
        "eligible_days": int(df["leverage_eligible"].sum()),
        "leverage_active_days": int(df["leverage_active"].sum()),
        "leverage_1p00_days": int((np.isclose(df["effective_leverage"], 1.00)).sum()),
        "leverage_1p25_days": int((np.isclose(df["effective_leverage"], 1.25)).sum()),
        "leverage_1p50_days": int((np.isclose(df["effective_leverage"], 1.50)).sum()),
        "trend_block_days": int(df["trend_block_day"].sum()),
        "stress_block_days": int(df["stress_block_day"].sum()),
        "held_asset_now": str(df["portfolio_held_asset"].iloc[-1]) if not df.empty else "",
        "latest_available_date": df["date"].max().strftime("%Y-%m-%d") if not df.empty else "",
    }


def add_delta_cols(row: dict, ref: dict) -> dict:
    out = row.copy()
    for metric in [
        "total_return_pct_gross",
        "total_return_pct_net",
        "cagr_pct_gross",
        "cagr_pct",
        "max_drawdown_pct_gross",
        "max_drawdown_pct",
        "calmar",
        "since2023_cagr_pct_gross",
        "since2023_cagr_pct",
        "since2025_cagr_pct_gross",
        "since2025_cagr_pct",
        "worst_day_pct_gross",
        "worst_day_pct",
        "borrow_cost_total_pct",
        "tradable_slippage_cost_total_pct",
        "trading_fees_total_pct",
        "funding_total_pct",
    ]:
        out[f"delta_vs_1p00x_{metric}"] = (
            pd.to_numeric(out.get(metric), errors="coerce")
            - pd.to_numeric(ref.get(metric), errors="coerce")
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="PHASE68H dynamic leverage ladder candidate")
    parser.add_argument("--governance-paper", type=str, default=str(DEFAULT_GOVERNANCE_PAPER))
    parser.add_argument("--baseline-paper", type=str, default="")
    parser.add_argument("--trend-history", type=str, default=str(DEFAULT_TREND))
    parser.add_argument("--decisions", type=str, default=str(DEFAULT_DECISIONS))
    parser.add_argument("--annual-borrow-cost", type=float, default=0.12)
    parser.add_argument("--tradable-transition-slippage-bps", type=float, default=10.0)
    parser.add_argument("--trend-activation-threshold", type=float, default=0.10)
    parser.add_argument("--dynamic-mid-threshold", type=float, default=0.50)
    parser.add_argument("--dynamic-mid-leverage", type=float, default=1.25)
    parser.add_argument("--dynamic-high-leverage", type=float, default=1.50)
    parser.add_argument("--stress-lookback-days", type=int, default=20)
    parser.add_argument("--stress-off-threshold", type=float, default=-0.08)
    parser.add_argument("--stress-on-threshold", type=float, default=-0.04)
    parser.add_argument("--fee-side-mode", choices=["taker", "maker", "mixed"], default="taker")
    parser.add_argument("--taker-fee-bps", type=float, default=4.5)
    parser.add_argument("--maker-fee-bps", type=float, default=1.5)
    parser.add_argument("--staking-discount-pct", type=float, default=0.0)
    parser.add_argument("--referral-discount-pct", type=float, default=0.0)
    args = parser.parse_args()

    ensure_dir(PHASE68H_DIR)
    papers_dir = PHASE68H_DIR / "papers"
    ensure_dir(papers_dir)

    governance_paper_path = Path(args.governance_paper)
    baseline_paper_path = Path(args.baseline_paper) if args.baseline_paper else find_baseline_paper_in_phase66g_dir()
    trend_path = Path(args.trend_history)
    decisions_path = Path(args.decisions)

    if not governance_paper_path.exists():
        raise FileNotFoundError(f"Governance paper sa nenašiel: {governance_paper_path}")
    if not baseline_paper_path.exists():
        raise FileNotFoundError(f"Baseline paper sa nenašiel: {baseline_paper_path}")
    if not trend_path.exists():
        raise FileNotFoundError(f"Trend history sa nenašiel: {trend_path}")
    if not decisions_path.exists():
        raise FileNotFoundError(f"Decisions file sa nenašiel: {decisions_path}")

    log("[PHASE68H] Start")
    log(f"[PHASE68H] Governance paper: {governance_paper_path}")
    log(f"[PHASE68H] Baseline paper: {baseline_paper_path}")
    log(f"[PHASE68H] Trend history: {trend_path}")
    log(f"[PHASE68H] Decisions: {decisions_path}")
    log(f"[PHASE68H] Annual borrow cost: {args.annual_borrow_cost:.4f}")
    log(f"[PHASE68H] Tradable transition slippage bps: {args.tradable_transition_slippage_bps:.2f}")
    log(
        "[PHASE68H] Trading fees: "
        f"mode={args.fee_side_mode} "
        f"taker_bps={args.taker_fee_bps:.4f} "
        f"maker_bps={args.maker_fee_bps:.4f} "
        f"staking_discount_pct={args.staking_discount_pct:.2f} "
        f"referral_discount_pct={args.referral_discount_pct:.2f}"
    )
    log(f"[PHASE68H] Trend activation threshold: {args.trend_activation_threshold:.4f}")
    log(f"[PHASE68H] Dynamic mid threshold: {args.dynamic_mid_threshold:.4f}")
    log(f"[PHASE68H] Dynamic ladder: 1.00x -> {args.dynamic_mid_leverage:.2f}x -> {args.dynamic_high_leverage:.2f}x")
    log(f"[PHASE68H] Stress off / on: {args.stress_off_threshold:.4f} / {args.stress_on_threshold:.4f}")

    governance_df = load_governance_paper(governance_paper_path)
    baseline_df = load_baseline_paper(baseline_paper_path)
    portfolio_df = build_portfolio_exposure_frame(governance_df, baseline_df)
    trend_df = load_trend_history(trend_path)
    decisions_df = load_governance_decisions(decisions_path)

    tradable_transition_df, governance_switch_count, mapping_meta = build_governance_transition_calendar(
        decisions_df=decisions_df,
        paper_dates=portfolio_df["date"],
    )
    tradable_transition_count = int(len(tradable_transition_df))

    transition_calendar_path = PHASE68H_DIR / "phase68h_tradable_transition_calendar.csv"
    tradable_transition_df.to_csv(transition_calendar_path, index=False)

    summary_rows: list[dict] = []

    for variant in VARIANTS:
        log(f"[PHASE68H] running {variant.model} | mode={variant.mode}")

        wrapped = build_validation_wrapper(
            portfolio_df=portfolio_df,
            trend_df=trend_df,
            tradable_transition_df=tradable_transition_df,
            variant=variant,
            annual_borrow_cost=float(args.annual_borrow_cost),
            tradable_transition_slippage_bps=float(args.tradable_transition_slippage_bps),
            trend_activation_threshold=float(args.trend_activation_threshold),
            stress_lookback_days=int(args.stress_lookback_days),
            stress_off_threshold=float(args.stress_off_threshold),
            stress_on_threshold=float(args.stress_on_threshold),
            dynamic_mid_threshold=float(args.dynamic_mid_threshold),
            dynamic_mid_leverage=float(args.dynamic_mid_leverage),
            dynamic_high_leverage=float(args.dynamic_high_leverage),
            fee_side_mode=str(args.fee_side_mode),
            taker_fee_bps=float(args.taker_fee_bps),
            maker_fee_bps=float(args.maker_fee_bps),
            staking_discount_pct=float(args.staking_discount_pct),
            referral_discount_pct=float(args.referral_discount_pct),
        )

        summary_rows.append(
            summarize_variant(
                model=variant.model,
                df=wrapped,
                annual_borrow_cost=float(args.annual_borrow_cost),
                governance_switch_count=int(governance_switch_count),
                tradable_transition_count=int(tradable_transition_count),
            )
        )

        wrapped.to_csv(papers_dir / f"{variant.model}_paper.csv", index=False)
        log(f"[PHASE68H] done {variant.model}")

    summary_df = pd.DataFrame(summary_rows)

    baseline_row = summary_df.loc[summary_df["model"] == "phase68h_66g_1p00x_portfolio_exposure_baseline"]
    if baseline_row.empty:
        raise ValueError("Chýba 1.00x portfolio exposure baseline row.")
    baseline = baseline_row.iloc[0].to_dict()

    compare_rows = [add_delta_cols(row, baseline) for row in summary_rows]
    compare_df = pd.DataFrame(compare_rows)
    compare_df = compare_df.sort_values(
        by=[
            "since2025_cagr_pct",
            "calmar",
            "cagr_pct",
            "max_drawdown_pct",
        ],
        ascending=[False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)

    top = compare_df.iloc[0].to_dict()
    dynamic_row = compare_df.loc[compare_df["model"] == "phase68h_dynamic_ladder_candidate"]
    dynamic_focus = dynamic_row.iloc[0].to_dict() if not dynamic_row.empty else top

    summary_path = PHASE68H_DIR / "phase68h_dynamic_leverage_ladder_summary.csv"
    compare_path = PHASE68H_DIR / "phase68h_dynamic_leverage_ladder_compare.csv"
    manifest_path = PHASE68H_DIR / "phase68h_dynamic_leverage_ladder_manifest.json"

    summary_df.to_csv(summary_path, index=False)
    compare_df.to_csv(compare_path, index=False)

    manifest = {
        "phase": "phase68h_dynamic_leverage_ladder_candidate",
        "official_compare_baseline": "phase68h_66g_1p00x_portfolio_exposure_baseline",
        "governance_paper": str(governance_paper_path),
        "baseline_paper": str(baseline_paper_path),
        "trend_history": str(trend_path),
        "decisions_file": str(decisions_path),
        "params": {
            "annual_borrow_cost": float(args.annual_borrow_cost),
            "tradable_transition_slippage_bps": float(args.tradable_transition_slippage_bps),
            "venue": "hyperliquid_perps",
            "fee_side_mode": str(args.fee_side_mode),
            "taker_fee_bps": float(args.taker_fee_bps),
            "maker_fee_bps": float(args.maker_fee_bps),
            "staking_discount_pct": float(args.staking_discount_pct),
            "referral_discount_pct": float(args.referral_discount_pct),
            "effective_trading_fee_bps": float(
                resolve_fee_rate_bps(
                    fee_side_mode=str(args.fee_side_mode),
                    taker_fee_bps=float(args.taker_fee_bps),
                    maker_fee_bps=float(args.maker_fee_bps),
                    staking_discount_pct=float(args.staking_discount_pct),
                    referral_discount_pct=float(args.referral_discount_pct),
                )
            ),
            "funding_mode": "separate_series_zero_when_unavailable",
            "trend_activation_threshold": float(args.trend_activation_threshold),
            "dynamic_mid_threshold": float(args.dynamic_mid_threshold),
            "dynamic_mid_leverage": float(args.dynamic_mid_leverage),
            "dynamic_high_leverage": float(args.dynamic_high_leverage),
            "stress_lookback_days": int(args.stress_lookback_days),
            "stress_off_threshold": float(args.stress_off_threshold),
            "stress_on_threshold": float(args.stress_on_threshold),
            "cash_forced_1x": True,
            "switch_day_forced_1x": True,
            "entry_buffer_day_forced_1x": True,
            "exposure_basis_fix": "portfolio_held_asset = chosen_asset override else baseline held asset by same date",
        },
        "transition_mapping_meta": mapping_meta,
        "governance_switch_count": int(governance_switch_count),
        "tradable_transition_count": int(tradable_transition_count),
        "transition_calendar_file": str(transition_calendar_path),
        "variants": [asdict(v) for v in VARIANTS],
        "summary_file": str(summary_path),
        "compare_file": str(compare_path),
        "papers_dir": str(papers_dir),
        "notes": [
            "1.50x ostáva hlavný leverage smer.",
            "1.25x ostáva softer fallback.",
            "68H testuje fixed dynamic ladder bez broad sweepu.",
            "Dynamic ladder: eligible & trend >= mid threshold -> 1.50x; eligible & trend >= activation threshold -> 1.25x; inak 1.00x.",
            "Borrow/slippage/transition mapping ostávajú rovnaké ako clean 68G basis.",
            "Trading fees sú modelované explicitne cez odhad turnoveru z asset/leverage zmien.",
            "Funding ostáva separátny export field; v current operator path je defaultne 0.0, kým nebude spoľahlivý source.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log("")
    log("=== PHASE68H TOP RESULT ===")
    log(f"model: {top['model']}")
    log(f"mode: {top['mode']}")
    log(f"cagr_pct: {float(top['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(top['max_drawdown_pct']):.2f}")
    log(f"calmar: {float(top['calmar']):.4f}")
    log(f"since2023_cagr_pct: {float(top['since2023_cagr_pct']):.2f}")
    log(f"since2025_cagr_pct: {float(top['since2025_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_cagr_pct: {float(top['delta_vs_1p00x_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_since2025_cagr_pct: {float(top['delta_vs_1p00x_since2025_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_max_drawdown_pct: {float(top['delta_vs_1p00x_max_drawdown_pct']):.2f}")
    log(f"delta_vs_1p00x_calmar: {float(top['delta_vs_1p00x_calmar']):.4f}")
    log("")

    log("=== PHASE68H DYNAMIC RESULT ===")
    log(f"model: {dynamic_focus['model']}")
    log(f"mode: {dynamic_focus['mode']}")
    log(f"cagr_pct: {float(dynamic_focus['cagr_pct']):.2f}")
    log(f"max_drawdown_pct: {float(dynamic_focus['max_drawdown_pct']):.2f}")
    log(f"calmar: {float(dynamic_focus['calmar']):.4f}")
    log(f"since2023_cagr_pct: {float(dynamic_focus['since2023_cagr_pct']):.2f}")
    log(f"since2025_cagr_pct: {float(dynamic_focus['since2025_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_cagr_pct: {float(dynamic_focus['delta_vs_1p00x_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_since2025_cagr_pct: {float(dynamic_focus['delta_vs_1p00x_since2025_cagr_pct']):.2f}")
    log(f"delta_vs_1p00x_max_drawdown_pct: {float(dynamic_focus['delta_vs_1p00x_max_drawdown_pct']):.2f}")
    log(f"delta_vs_1p00x_calmar: {float(dynamic_focus['delta_vs_1p00x_calmar']):.4f}")
    log(f"leverage_1p00_days: {int(pd.to_numeric(dynamic_focus['leverage_1p00_days'], errors='coerce'))}")
    log(f"leverage_1p25_days: {int(pd.to_numeric(dynamic_focus['leverage_1p25_days'], errors='coerce'))}")
    log(f"leverage_1p50_days: {int(pd.to_numeric(dynamic_focus['leverage_1p50_days'], errors='coerce'))}")
    log("")

    log(f"[PHASE68H] Saved summary -> {summary_path}")
    log(f"[PHASE68H] Saved compare -> {compare_path}")
    log(f"[PHASE68H] Saved manifest -> {manifest_path}")
    log(f"[PHASE68H] Saved transition calendar -> {transition_calendar_path}")
    log(f"[PHASE68H] Saved papers -> {papers_dir}")


if __name__ == "__main__":
    main()
