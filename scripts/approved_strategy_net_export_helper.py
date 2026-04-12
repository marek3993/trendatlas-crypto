from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


CASH_EQUIVALENT_ASSETS = {"", "CASH", "USD", "USDT", "NAN", "NONE", "NULL"}


@dataclass(frozen=True)
class NetCostExportConfig:
    annual_borrow_cost: float = 0.0
    tradable_transition_slippage_bps: float = 10.0
    fee_side_mode: str = "taker"
    taker_fee_bps: float = 4.5
    maker_fee_bps: float = 1.5
    staking_discount_pct: float = 0.0
    referral_discount_pct: float = 0.0


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


def _is_empty_token(value: object) -> bool:
    text = str(value).strip().upper()
    return text in {"", "NAN", "NONE", "NULL"}


def _is_numeric_token(value: object) -> bool:
    text = str(value).strip()
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def normalize_regime_position_to_asset(regime: object, position: object) -> str:
    regime_text = str(regime).strip().upper()
    position_text = str(position).strip().upper()

    if regime_text in {"CASH", "USD", "USDT"}:
        return "CASH"
    if regime_text == "BTC":
        return "BTC"
    if regime_text == "BASE":
        return "BASE"
    if regime_text == "CANDIDATE":
        if _is_empty_token(position_text) or _is_numeric_token(position_text):
            return "CANDIDATE"
        return position_text

    if _is_empty_token(position_text):
        return "CASH"
    if _is_numeric_token(position_text):
        return regime_text or "BASE"
    return position_text


def normalize_explicit_asset(value: object) -> str:
    text = str(value).strip().upper()
    if text in {"", "NAN", "NONE", "NULL"}:
        return "CASH"
    return text


def _build_equity_curve(ret_series: pd.Series) -> pd.Series:
    return (1.0 + pd.to_numeric(ret_series, errors="coerce").fillna(0.0)).cumprod()


def _compute_total_return_pct(ret_series: pd.Series) -> float:
    eq = _build_equity_curve(ret_series)
    if eq.empty:
        return np.nan
    return float((eq.iloc[-1] - 1.0) * 100.0)


def _compute_cagr_pct(ret_series: pd.Series, date_series: pd.Series) -> float:
    eq = _build_equity_curve(ret_series)
    if eq.empty:
        return np.nan
    start_dt = pd.to_datetime(date_series.iloc[0], errors="coerce")
    end_dt = pd.to_datetime(date_series.iloc[-1], errors="coerce")
    if pd.isna(start_dt) or pd.isna(end_dt):
        return np.nan
    days = max(int((end_dt - start_dt).days), 1)
    years = days / 365.25
    if years <= 0 or eq.iloc[-1] <= 0:
        return np.nan
    return float(((eq.iloc[-1] ** (1.0 / years)) - 1.0) * 100.0)


def _compute_max_drawdown_pct(ret_series: pd.Series) -> float:
    eq = _build_equity_curve(ret_series)
    if eq.empty:
        return np.nan
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min() * 100.0)


def _subset_since(df: pd.DataFrame, start_date: str) -> pd.DataFrame:
    return df.loc[df["date"] >= pd.Timestamp(start_date)].copy().reset_index(drop=True)


def build_net_cost_export_frame(
    df: pd.DataFrame,
    *,
    date_col: str = "date",
    gross_return_col: str,
    config: NetCostExportConfig,
    held_asset_col: str | None = None,
    regime_col: str | None = None,
    position_col: str | None = None,
    leverage_col: str | None = None,
    daily_borrow_cost_col: str | None = None,
    tradable_slippage_cost_col: str | None = None,
    trading_fees_daily_col: str | None = None,
    funding_daily_col: str | None = None,
) -> pd.DataFrame:
    if date_col not in df.columns:
        raise KeyError(f"Missing required date column: {date_col}")
    if gross_return_col not in df.columns:
        raise KeyError(f"Missing required gross return column: {gross_return_col}")
    if held_asset_col is None and (regime_col is None or position_col is None):
        raise ValueError("Provide held_asset_col or both regime_col and position_col.")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)
    out["gross_return"] = pd.to_numeric(df[gross_return_col], errors="coerce").fillna(0.0)

    if held_asset_col is not None:
        out["held_asset"] = df[held_asset_col].map(normalize_explicit_asset)
    else:
        out["held_asset"] = [
            normalize_regime_position_to_asset(regime=row_regime, position=row_position)
            for row_regime, row_position in zip(df[regime_col], df[position_col], strict=False)
        ]

    if leverage_col is None:
        leverage = np.where(out["held_asset"].isin(CASH_EQUIVALENT_ASSETS), 0.0, 1.0)
        out["effective_leverage"] = pd.Series(leverage, index=out.index, dtype="float64")
    else:
        out["effective_leverage"] = pd.to_numeric(df[leverage_col], errors="coerce").fillna(0.0)

    prev_asset = out["held_asset"].shift(1).fillna("")
    prev_leverage = pd.to_numeric(out["effective_leverage"].shift(1), errors="coerce").fillna(0.0)
    curr_leverage = pd.to_numeric(out["effective_leverage"], errors="coerce").fillna(0.0)

    has_prev = prev_asset != ""
    out["asset_transition_day"] = (has_prev & (out["held_asset"] != prev_asset)).fillna(False)

    prev_notional = np.where(prev_asset.isin(CASH_EQUIVALENT_ASSETS), 0.0, prev_leverage)
    curr_notional = np.where(out["held_asset"].isin(CASH_EQUIVALENT_ASSETS), 0.0, curr_leverage)
    same_asset = prev_asset == out["held_asset"]
    out["trading_turnover_notional"] = np.where(
        has_prev,
        np.where(
            same_asset,
            np.abs(curr_notional - prev_notional),
            prev_notional + curr_notional,
        ),
        0.0,
    )

    if daily_borrow_cost_col is not None and daily_borrow_cost_col in df.columns:
        out["daily_borrow_cost"] = pd.to_numeric(df[daily_borrow_cost_col], errors="coerce").fillna(0.0)
    else:
        borrowed_fraction = np.maximum(curr_leverage - 1.0, 0.0)
        out["daily_borrow_cost"] = borrowed_fraction * (float(config.annual_borrow_cost) / 365.25)

    if tradable_slippage_cost_col is not None and tradable_slippage_cost_col in df.columns:
        out["tradable_slippage_cost"] = pd.to_numeric(df[tradable_slippage_cost_col], errors="coerce").fillna(0.0)
    else:
        slippage_rate = float(config.tradable_transition_slippage_bps) / 10000.0
        out["tradable_slippage_cost"] = np.where(out["asset_transition_day"], slippage_rate, 0.0)

    effective_trading_fee_bps = resolve_fee_rate_bps(
        fee_side_mode=config.fee_side_mode,
        taker_fee_bps=config.taker_fee_bps,
        maker_fee_bps=config.maker_fee_bps,
        staking_discount_pct=config.staking_discount_pct,
        referral_discount_pct=config.referral_discount_pct,
    )
    if trading_fees_daily_col is not None and trading_fees_daily_col in df.columns:
        out["trading_fees_daily"] = pd.to_numeric(df[trading_fees_daily_col], errors="coerce").fillna(0.0)
    else:
        out["trading_fees_daily"] = out["trading_turnover_notional"] * (effective_trading_fee_bps / 10000.0)

    if funding_daily_col is not None and funding_daily_col in df.columns:
        out["funding_daily"] = pd.to_numeric(df[funding_daily_col], errors="coerce").fillna(0.0)
    else:
        out["funding_daily"] = 0.0

    out["net_return"] = (
        out["gross_return"]
        - out["daily_borrow_cost"]
        - out["tradable_slippage_cost"]
        - out["trading_fees_daily"]
        - out["funding_daily"]
    ).clip(lower=-0.999999)
    out["equity_curve_gross"] = _build_equity_curve(out["gross_return"])
    out["equity_curve_net"] = _build_equity_curve(out["net_return"])

    out["fee_side_mode"] = str(config.fee_side_mode).strip().lower()
    out["taker_fee_bps"] = float(config.taker_fee_bps)
    out["maker_fee_bps"] = float(config.maker_fee_bps)
    out["staking_discount_pct"] = float(config.staking_discount_pct)
    out["referral_discount_pct"] = float(config.referral_discount_pct)
    out["effective_trading_fee_bps"] = float(effective_trading_fee_bps)
    out["annual_borrow_cost_pct"] = float(config.annual_borrow_cost * 100.0)
    out["tradable_transition_slippage_bps"] = float(config.tradable_transition_slippage_bps)

    return out.dropna(subset=["date"]).reset_index(drop=True)


def summarize_net_cost_export(
    export_df: pd.DataFrame,
    *,
    model: str,
    switch_count: int | float | None = None,
    trade_count: int | float | None = None,
) -> dict:
    if export_df.empty:
        raise ValueError("Cannot summarize an empty export frame.")

    since2023 = _subset_since(export_df, "2023-01-01")
    since2025 = _subset_since(export_df, "2025-01-01")

    output: dict[str, object] = {
        "model": model,
        "total_return_pct_gross": round(_compute_total_return_pct(export_df["gross_return"]), 2),
        "total_return_pct_net": round(_compute_total_return_pct(export_df["net_return"]), 2),
        "cagr_pct_gross": round(_compute_cagr_pct(export_df["gross_return"], export_df["date"]), 2),
        "cagr_pct_net": round(_compute_cagr_pct(export_df["net_return"], export_df["date"]), 2),
        "max_drawdown_pct_gross": round(_compute_max_drawdown_pct(export_df["gross_return"]), 2),
        "max_drawdown_pct_net": round(_compute_max_drawdown_pct(export_df["net_return"]), 2),
        "since2023_cagr_pct_gross": round(_compute_cagr_pct(since2023["gross_return"], since2023["date"]), 2) if not since2023.empty else np.nan,
        "since2023_cagr_pct_net": round(_compute_cagr_pct(since2023["net_return"], since2023["date"]), 2) if not since2023.empty else np.nan,
        "since2025_cagr_pct_gross": round(_compute_cagr_pct(since2025["gross_return"], since2025["date"]), 2) if not since2025.empty else np.nan,
        "since2025_cagr_pct_net": round(_compute_cagr_pct(since2025["net_return"], since2025["date"]), 2) if not since2025.empty else np.nan,
        "trading_fees_total_pct": round(float(export_df["trading_fees_daily"].sum() * 100.0), 4),
        "funding_total_pct": round(float(export_df["funding_daily"].sum() * 100.0), 4),
        "borrow_cost_total_pct": round(float(export_df["daily_borrow_cost"].sum() * 100.0), 4),
        "tradable_slippage_cost_total_pct": round(float(export_df["tradable_slippage_cost"].sum() * 100.0), 4),
        "trade_count": int(export_df["asset_transition_day"].sum()) if trade_count is None else int(float(trade_count)),
        "cash_days_pct": round(float(export_df["held_asset"].isin(CASH_EQUIVALENT_ASSETS).mean() * 100.0), 4),
        "btc_days_pct": round(float((export_df["held_asset"] == "BTC").mean() * 100.0), 4),
        "annual_borrow_cost_pct": float(export_df["annual_borrow_cost_pct"].iloc[0]),
        "tradable_transition_slippage_bps": float(export_df["tradable_transition_slippage_bps"].iloc[0]),
        "fee_side_mode": str(export_df["fee_side_mode"].iloc[0]),
        "taker_fee_bps": float(export_df["taker_fee_bps"].iloc[0]),
        "maker_fee_bps": float(export_df["maker_fee_bps"].iloc[0]),
        "staking_discount_pct": float(export_df["staking_discount_pct"].iloc[0]),
        "referral_discount_pct": float(export_df["referral_discount_pct"].iloc[0]),
        "effective_trading_fee_bps": float(export_df["effective_trading_fee_bps"].iloc[0]),
        "latest_available_date": export_df["date"].max().strftime("%Y-%m-%d"),
    }
    if switch_count is not None:
        output["switch_count"] = int(float(switch_count))
    return output
