from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from research_os_dev_only_feature_anti_leakage import run_feature_output_checks
from research_os_dev_only_feature_output_common import MANDATORY_DEV_FLAGS, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]

SPOT_PATH = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"
LEGACY_FUNDING_PATH = ROOT / "data" / "funding" / "BTCUSDT_funding.csv"

RAW_BINANCE_DIR = ROOT / "data" / "raw" / "binance"
RAW_FUNDING_DIR = RAW_BINANCE_DIR / "funding_history" / "BTCUSDT"
RAW_BASIS_5M_DIR = RAW_BINANCE_DIR / "basis_5m" / "BTCUSDT"
RAW_BASIS_1H_DIR = RAW_BINANCE_DIR / "basis_1h" / "BTCUSDT"
RAW_PREMIUM_5M_DIR = RAW_BINANCE_DIR / "premium_klines_5m" / "BTCUSDT"
RAW_OPEN_INTEREST_1H_DIR = RAW_BINANCE_DIR / "open_interest_hist_1h" / "BTCUSDT"
RAW_OPEN_INTEREST_5M_DIR = RAW_BINANCE_DIR / "open_interest_hist_5m" / "BTCUSDT"
RAW_FUNDING_INFO_DIR = RAW_BINANCE_DIR / "funding_info_snapshots" / "ALL"

OUTPUT_DIR = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_btc_derivatives_daily_panel"
OUTPUT_CSV = OUTPUT_DIR / "btc_derivatives_daily_panel.csv"
OUTPUT_MANIFEST = OUTPUT_DIR / "btc_derivatives_daily_panel.manifest.json"
OUTPUT_QUALITY = OUTPUT_DIR / "btc_derivatives_daily_panel.quality.json"

FAMILY_ID = "btc_derivatives_daily_panel"
FAMILY_TYPE = "dev_only_research_data_layer"
FUNDING_LOOKBACK_DAYS = 7
MIN_READY_CONSECUTIVE_DAYS = 90
MAX_ALLOWED_RECENCY_LAG_DAYS = 3

PANEL_COLUMNS = [
    "date",
    "btc_spot_close",
    "btc_spot_volume",
    "funding_rate_daily",
    "funding_rate_lookback",
    "funding_mark_price_daily",
    "basis_daily",
    "basis_last",
    "basis_abs_daily",
    "premium_daily",
    "premium_last",
    "open_interest_daily",
    "open_interest_contracts_daily",
    "open_interest_change",
    "leverage_proxy",
    "funding_source",
    "basis_source",
    "premium_source",
    "open_interest_source",
    "leverage_proxy_source",
    "funding_observation_count",
    "basis_observation_count",
    "premium_observation_count",
    "open_interest_observation_count",
    "funding_expected_observation_count",
    "basis_expected_observation_count",
    "premium_expected_observation_count",
    "open_interest_expected_observation_count",
    "funding_coverage_ok",
    "basis_coverage_ok",
    "premium_coverage_ok",
    "open_interest_coverage_ok",
    "open_interest_end_of_day_ok",
    "funding_missing_flag",
    "funding_lookback_missing_flag",
    "basis_missing_flag",
    "premium_missing_flag",
    "open_interest_missing_flag",
    "open_interest_change_missing_flag",
    "leverage_proxy_missing_flag",
    "missing_data_flag",
    "daily_causal_ready",
    "probe_input_ready_flag",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


@dataclass(frozen=True)
class VerdictBundle:
    ready_for_dev_only_probe: bool
    verdict: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a dev-only causally-safe daily BTC derivatives panel."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory for the CSV + manifest + quality outputs.",
    )
    parser.add_argument(
        "--funding-lookback-days",
        type=int,
        default=FUNDING_LOOKBACK_DAYS,
        help="Calendar-day lookback for funding_rate_lookback.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="",
        help="Optional YYYY-MM-DD override for the panel start date.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit non-zero unless the resulting panel is READY_FOR_DEV_ONLY_PROBE.",
    )
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def with_dev_flags(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    return out


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    if pd.isna(value):
        return None
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )


def read_parquet_dir(path: Path) -> pd.DataFrame:
    files = sorted(path.glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)


def normalize_day(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()


def load_spot_daily() -> pd.DataFrame:
    df = pd.read_csv(SPOT_PATH)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["date", "close", "volume"]).copy()
    df["date"] = df["date"].dt.normalize()
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    out = df.set_index("date")[["close", "volume"]].rename(
        columns={
            "close": "btc_spot_close",
            "volume": "btc_spot_volume",
        }
    )
    return out.astype(float)


def load_funding_daily() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    if LEGACY_FUNDING_PATH.exists():
        legacy = pd.read_csv(LEGACY_FUNDING_PATH)
        legacy["funding_ts_utc"] = pd.to_datetime(legacy["funding_time"], unit="ms", utc=True, errors="coerce")
        legacy["funding_rate"] = pd.to_numeric(legacy["funding_rate"], errors="coerce")
        legacy["mark_price"] = pd.to_numeric(legacy["mark_price"], errors="coerce")
        legacy["source"] = "binance_legacy_csv"
        frames.append(legacy[["funding_ts_utc", "funding_rate", "mark_price", "source"]])

    raw = read_parquet_dir(RAW_FUNDING_DIR)
    if not raw.empty:
        raw["funding_ts_utc"] = pd.to_datetime(raw["funding_time_utc"], utc=True, errors="coerce")
        raw["funding_rate"] = pd.to_numeric(raw["funding_rate"], errors="coerce")
        raw["mark_price"] = pd.to_numeric(raw["mark_price"], errors="coerce")
        raw["source"] = "binance_raw_parquet"
        frames.append(raw[["funding_ts_utc", "funding_rate", "mark_price", "source"]])

    if not frames:
        return pd.DataFrame(
            columns=[
                "funding_rate_daily",
                "funding_mark_price_daily",
                "funding_source",
                "funding_observation_count",
                "funding_expected_observation_count",
                "funding_coverage_ok",
            ]
        )

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=["funding_ts_utc", "funding_rate"]).copy()
    combined["source_priority"] = combined["source"].map(
        {
            "binance_raw_parquet": 0,
            "binance_legacy_csv": 1,
        }
    )
    combined = combined.sort_values(["funding_ts_utc", "source_priority"]).drop_duplicates(
        subset=["funding_ts_utc"], keep="first"
    )
    combined["date"] = normalize_day(combined["funding_ts_utc"])

    grouped = combined.groupby("date", dropna=True)
    out = pd.DataFrame(index=sorted(grouped.groups.keys()))
    out["funding_rate_daily"] = grouped["funding_rate"].sum()
    out["funding_mark_price_daily"] = grouped["mark_price"].last()
    out["funding_observation_count"] = grouped.size().astype(int)
    out["funding_expected_observation_count"] = 3
    out["funding_last_ts_utc"] = grouped["funding_ts_utc"].max()
    out["funding_source"] = grouped["source"].apply(
        lambda values: "+".join(sorted(pd.Series(values).dropna().astype(str).unique()))
    )
    out["funding_coverage_ok"] = (
        (out["funding_observation_count"] == out["funding_expected_observation_count"])
        & (pd.to_datetime(out["funding_last_ts_utc"], utc=True).dt.hour == 16)
    )
    return out


def aggregate_basis_daily(df: pd.DataFrame, *, source_name: str, expected_count: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
    df["basis_rate"] = pd.to_numeric(df["basis_rate"], errors="coerce")
    df["basis"] = pd.to_numeric(df["basis"], errors="coerce")
    df = df.dropna(subset=["ts_utc", "basis_rate", "basis"]).copy()
    if df.empty:
        return pd.DataFrame()
    df["date"] = normalize_day(df["ts_utc"])
    grouped = df.groupby("date", dropna=True)
    out = pd.DataFrame(index=sorted(grouped.groups.keys()))
    out["basis_daily"] = grouped["basis_rate"].mean()
    out["basis_last"] = grouped["basis_rate"].last()
    out["basis_abs_daily"] = grouped["basis"].mean()
    out["basis_observation_count"] = grouped.size().astype(int)
    out["basis_expected_observation_count"] = expected_count
    out["basis_last_ts_utc"] = grouped["ts_utc"].max()
    out["basis_source"] = source_name
    if expected_count == 288:
        last_ok = pd.to_datetime(out["basis_last_ts_utc"], utc=True).dt.strftime("%H:%M") == "23:55"
    else:
        last_ok = pd.to_datetime(out["basis_last_ts_utc"], utc=True).dt.strftime("%H:%M") == "23:00"
    out["basis_coverage_ok"] = (out["basis_observation_count"] == expected_count) & last_ok
    return out


def load_basis_daily() -> tuple[pd.DataFrame, dict[str, Any]]:
    basis_5m = aggregate_basis_daily(
        read_parquet_dir(RAW_BASIS_5M_DIR),
        source_name="binance_basis_5m",
        expected_count=288,
    )
    basis_1h = aggregate_basis_daily(
        read_parquet_dir(RAW_BASIS_1H_DIR),
        source_name="binance_basis_1h_fallback",
        expected_count=24,
    )

    if basis_5m.empty and basis_1h.empty:
        return pd.DataFrame(), {"annualized_basis_rate_all_null": True, "contract_type_all_null": True}

    combined = basis_5m.copy()
    if combined.empty:
        combined = basis_1h.copy()
    elif not basis_1h.empty:
        missing_days = basis_1h.index.difference(combined.index)
        if len(missing_days) > 0:
            combined = pd.concat([combined, basis_1h.loc[missing_days]], axis=0).sort_index()

    metadata = {
        "annualized_basis_rate_all_null": True,
        "contract_type_all_null": True,
    }
    raw_basis = pd.concat(
        [frame for frame in [read_parquet_dir(RAW_BASIS_5M_DIR), read_parquet_dir(RAW_BASIS_1H_DIR)] if not frame.empty],
        ignore_index=True,
    )
    if not raw_basis.empty:
        if "annualized_basis_rate" in raw_basis.columns:
            metadata["annualized_basis_rate_all_null"] = bool(raw_basis["annualized_basis_rate"].isna().all())
        if "contractType" in raw_basis.columns:
            metadata["contract_type_all_null"] = bool(raw_basis["contractType"].isna().all())
    return combined, metadata


def load_premium_daily() -> pd.DataFrame:
    df = read_parquet_dir(RAW_PREMIUM_5M_DIR)
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts_close_utc"] = pd.to_datetime(df["ts_close_utc"], utc=True, errors="coerce")
    df["premium_close"] = pd.to_numeric(df["premium_close"], errors="coerce")
    df = df.dropna(subset=["ts_close_utc", "premium_close"]).copy()
    if df.empty:
        return pd.DataFrame()
    df["date"] = normalize_day(df["ts_close_utc"])
    grouped = df.groupby("date", dropna=True)
    out = pd.DataFrame(index=sorted(grouped.groups.keys()))
    out["premium_daily"] = grouped["premium_close"].mean()
    out["premium_last"] = grouped["premium_close"].last()
    out["premium_observation_count"] = grouped.size().astype(int)
    out["premium_expected_observation_count"] = 288
    out["premium_last_ts_utc"] = grouped["ts_close_utc"].max()
    out["premium_source"] = "binance_premium_klines_5m"
    last_ok = pd.to_datetime(out["premium_last_ts_utc"], utc=True).dt.strftime("%H:%M:%S.%f") == "23:59:59.999000"
    out["premium_coverage_ok"] = (out["premium_observation_count"] == 288) & last_ok
    return out


def aggregate_open_interest_daily(df: pd.DataFrame, *, source_name: str, expected_count: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
    df["oi_value"] = pd.to_numeric(df["oi_value"], errors="coerce")
    df["oi_contracts"] = pd.to_numeric(df["oi_contracts"], errors="coerce")
    df["CMCCirculatingSupply"] = pd.to_numeric(df["CMCCirculatingSupply"], errors="coerce")
    df = df.dropna(subset=["ts_utc", "oi_value", "oi_contracts"]).copy()
    if df.empty:
        return pd.DataFrame()
    df["date"] = normalize_day(df["ts_utc"])
    grouped = df.groupby("date", dropna=True)
    out = pd.DataFrame(index=sorted(grouped.groups.keys()))
    out["open_interest_daily"] = grouped["oi_value"].last()
    out["open_interest_contracts_daily"] = grouped["oi_contracts"].last()
    out["open_interest_supply_daily"] = grouped["CMCCirculatingSupply"].last()
    out["open_interest_observation_count"] = grouped.size().astype(int)
    out["open_interest_expected_observation_count"] = expected_count
    out["open_interest_last_ts_utc"] = grouped["ts_utc"].max()
    out["open_interest_source"] = source_name
    last_minute = pd.to_datetime(out["open_interest_last_ts_utc"], utc=True).dt.strftime("%H:%M")
    end_of_day_ok = last_minute.isin(["23:00", "23:55"])
    out["open_interest_end_of_day_ok"] = end_of_day_ok
    out["open_interest_coverage_ok"] = (
        (out["open_interest_observation_count"] == expected_count) & end_of_day_ok
    )
    return out


def load_open_interest_daily() -> pd.DataFrame:
    oi_1h = aggregate_open_interest_daily(
        read_parquet_dir(RAW_OPEN_INTEREST_1H_DIR),
        source_name="binance_open_interest_1h",
        expected_count=24,
    )
    oi_5m = aggregate_open_interest_daily(
        read_parquet_dir(RAW_OPEN_INTEREST_5M_DIR),
        source_name="binance_open_interest_5m",
        expected_count=288,
    )

    candidates = []
    for frame, source_rank in [(oi_1h, 1), (oi_5m, 2)]:
        if frame.empty:
            continue
        tmp = frame.reset_index().rename(columns={"index": "date"})
        tmp["source_rank"] = source_rank
        tmp["coverage_rank"] = tmp["open_interest_coverage_ok"].astype(int)
        tmp["end_of_day_rank"] = tmp["open_interest_end_of_day_ok"].astype(int)
        candidates.append(tmp)

    if not candidates:
        return pd.DataFrame()

    combined = pd.concat(candidates, ignore_index=True)
    combined = combined.sort_values(
        [
            "date",
            "coverage_rank",
            "end_of_day_rank",
            "open_interest_observation_count",
            "open_interest_last_ts_utc",
            "source_rank",
        ],
        ascending=[True, False, False, False, False, False],
    )
    chosen = combined.drop_duplicates(subset=["date"], keep="first").set_index("date").sort_index()
    return chosen[
        [
            "open_interest_daily",
            "open_interest_contracts_daily",
            "open_interest_supply_daily",
            "open_interest_observation_count",
            "open_interest_expected_observation_count",
            "open_interest_last_ts_utc",
            "open_interest_source",
            "open_interest_end_of_day_ok",
            "open_interest_coverage_ok",
        ]
    ]


def build_calendar_index(spot: pd.DataFrame, start_date_text: str | None) -> pd.DatetimeIndex:
    if start_date_text:
        start_date = pd.Timestamp(start_date_text)
    else:
        start_date = pd.Timestamp("2019-09-10")
    end_date = pd.Timestamp(spot.index.max())
    return pd.date_range(start_date, end_date, freq="D")


def compute_gap_days(index: pd.DatetimeIndex, present_mask: pd.Series) -> list[str]:
    missing = index[present_mask.reindex(index, fill_value=False) == False]
    return [timestamp.strftime("%Y-%m-%d") for timestamp in missing]


def summarize_presence_window(index: pd.DatetimeIndex, present_mask: pd.Series) -> dict[str, Any]:
    aligned = present_mask.reindex(index, fill_value=False).astype(bool)
    if not aligned.any():
        return {
            "first_present_date": None,
            "last_present_date": None,
            "internal_gap_days": [],
            "trailing_missing_days": [],
        }

    present_index = index[aligned]
    first_present = present_index[0]
    last_present = present_index[-1]
    within_window = (index >= first_present) & (index <= last_present)
    internal_gap_index = index[within_window & ~aligned]
    trailing_missing_index = index[index > last_present]
    return {
        "first_present_date": first_present.strftime("%Y-%m-%d"),
        "last_present_date": last_present.strftime("%Y-%m-%d"),
        "internal_gap_days": [timestamp.strftime("%Y-%m-%d") for timestamp in internal_gap_index],
        "trailing_missing_days": [timestamp.strftime("%Y-%m-%d") for timestamp in trailing_missing_index],
    }


def compute_consecutive_true_count(series: pd.Series) -> int:
    best = 0
    current = 0
    for value in series.fillna(False).astype(bool):
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def summarize_field_coverage(panel: pd.DataFrame, column: str) -> dict[str, Any]:
    present = panel[column].notna()
    if not present.any():
        return {
            "non_null_count": 0,
            "first_non_null_date": None,
            "last_non_null_date": None,
        }
    non_null_index = pd.DatetimeIndex(panel.index[present])
    return {
        "non_null_count": int(present.sum()),
        "first_non_null_date": non_null_index[0].strftime("%Y-%m-%d"),
        "last_non_null_date": non_null_index[-1].strftime("%Y-%m-%d"),
    }


def derive_verdict(*, panel: pd.DataFrame, spot_last_date: pd.Timestamp) -> tuple[VerdictBundle, int]:
    max_probe_ready_days = compute_consecutive_true_count(panel["probe_input_ready_flag"])
    core_complete_mask = panel[
        [
            "funding_rate_daily",
            "basis_daily",
            "premium_daily",
            "open_interest_daily",
        ]
    ].notna().all(axis=1)
    if core_complete_mask.any():
        last_core_date = panel.index[core_complete_mask][-1]
        recency_lag_days = int((spot_last_date - last_core_date).days)
    else:
        recency_lag_days = int((spot_last_date - panel.index.min()).days)

    if max_probe_ready_days >= MIN_READY_CONSECUTIVE_DAYS and recency_lag_days <= MAX_ALLOWED_RECENCY_LAG_DAYS:
        return (
            VerdictBundle(
                ready_for_dev_only_probe=True,
                verdict="READY_FOR_DEV_ONLY_PROBE",
                reason="Panel has sufficient consecutive probe-ready days and acceptable recency versus spot.",
            ),
            recency_lag_days,
        )

    if panel["probe_input_ready_flag"].sum() == 0:
        return (
            VerdictBundle(
                ready_for_dev_only_probe=False,
                verdict="NOT_AVAILABLE",
                reason="No days satisfy the full probe input contract after strict funding lookback and core field checks.",
            ),
            recency_lag_days,
        )

    return (
        VerdictBundle(
            ready_for_dev_only_probe=False,
            verdict="NOT_AVAILABLE",
            reason="Probe-ready window exists but is too short or too stale for a dev-only derivatives-reset probe.",
        ),
        recency_lag_days,
    )


def build_panel(*, funding_lookback_days: int, start_date_text: str | None) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    spot = load_spot_daily()
    funding = load_funding_daily()
    basis, basis_metadata = load_basis_daily()
    premium = load_premium_daily()
    open_interest = load_open_interest_daily()

    calendar_index = build_calendar_index(spot, start_date_text)
    panel = pd.DataFrame(index=calendar_index)
    panel = panel.join(spot, how="left")
    panel = panel.join(funding, how="left")
    panel = panel.join(basis, how="left")
    panel = panel.join(premium, how="left")
    panel = panel.join(open_interest, how="left")

    panel["funding_rate_lookback"] = (
        panel["funding_rate_daily"].rolling(funding_lookback_days, min_periods=funding_lookback_days).mean()
    )
    panel["open_interest_change"] = pd.NA
    previous_dates = panel.index.to_series().shift(1)
    previous_oi = panel["open_interest_daily"].shift(1)
    consecutive_days = (panel.index.to_series() - previous_dates) == timedelta(days=1)
    valid_change = (
        panel["open_interest_daily"].notna()
        & previous_oi.notna()
        & (previous_oi != 0)
        & consecutive_days.fillna(False)
    )
    panel.loc[valid_change, "open_interest_change"] = (
        panel.loc[valid_change, "open_interest_daily"] / previous_oi.loc[valid_change]
    ) - 1.0

    market_cap_proxy = panel["open_interest_supply_daily"] * panel["btc_spot_close"]
    valid_leverage = panel["open_interest_daily"].notna() & market_cap_proxy.notna() & (market_cap_proxy > 0)
    panel["leverage_proxy"] = pd.NA
    panel.loc[valid_leverage, "leverage_proxy"] = (
        panel.loc[valid_leverage, "open_interest_daily"] / market_cap_proxy.loc[valid_leverage]
    )
    panel["leverage_proxy_source"] = pd.NA
    panel.loc[valid_leverage, "leverage_proxy_source"] = "proxy_oi_value_div_estimated_spot_market_cap"

    panel["funding_missing_flag"] = panel["funding_rate_daily"].isna()
    panel["funding_lookback_missing_flag"] = panel["funding_rate_lookback"].isna()
    panel["basis_missing_flag"] = panel["basis_daily"].isna()
    panel["premium_missing_flag"] = panel["premium_daily"].isna()
    panel["open_interest_missing_flag"] = panel["open_interest_daily"].isna()
    panel["open_interest_change_missing_flag"] = panel["open_interest_change"].isna()
    panel["leverage_proxy_missing_flag"] = panel["leverage_proxy"].isna()
    panel["missing_data_flag"] = panel[
        [
            "funding_missing_flag",
            "basis_missing_flag",
            "premium_missing_flag",
            "open_interest_missing_flag",
            "leverage_proxy_missing_flag",
        ]
    ].any(axis=1)

    panel["daily_causal_ready"] = (
        panel["btc_spot_close"].notna()
        & panel["funding_rate_daily"].notna()
        & panel["basis_daily"].notna()
        & panel["premium_daily"].notna()
        & panel["open_interest_daily"].notna()
        & panel["funding_coverage_ok"].fillna(False)
        & panel["basis_coverage_ok"].fillna(False)
        & panel["premium_coverage_ok"].fillna(False)
        & panel["open_interest_end_of_day_ok"].fillna(False)
    )
    panel["probe_input_ready_flag"] = (
        panel["daily_causal_ready"]
        & panel["funding_rate_lookback"].notna()
        & panel["open_interest_change"].notna()
        & panel["leverage_proxy"].notna()
    )

    panel["date"] = panel.index.strftime("%Y-%m-%d")
    for flag_column, flag_value in MANDATORY_DEV_FLAGS.items():
        panel[flag_column] = flag_value

    for column in PANEL_COLUMNS:
        if column not in panel.columns:
            panel[column] = pd.NA
    panel = panel[PANEL_COLUMNS].copy()

    funding_present_mask = funding["funding_rate_daily"].notna() if not funding.empty else pd.Series(dtype=bool)
    basis_present_mask = basis["basis_daily"].notna() if not basis.empty else pd.Series(dtype=bool)
    premium_present_mask = premium["premium_daily"].notna() if not premium.empty else pd.Series(dtype=bool)
    oi_present_mask = open_interest["open_interest_daily"].notna() if not open_interest.empty else pd.Series(dtype=bool)

    funding_presence = summarize_presence_window(calendar_index, funding_present_mask)
    basis_presence = summarize_presence_window(calendar_index, basis_present_mask)
    premium_presence = summarize_presence_window(calendar_index, premium_present_mask)
    open_interest_presence = summarize_presence_window(calendar_index, oi_present_mask)

    panel_level_meta = {
        "coverage_windows": {
            "spot": {
                "first_present_date": panel.loc[panel["btc_spot_close"].notna(), "date"].iloc[0],
                "last_present_date": panel.loc[panel["btc_spot_close"].notna(), "date"].iloc[-1],
                "internal_gap_days": [],
                "trailing_missing_days": [],
            },
            "funding": funding_presence,
            "basis": basis_presence,
            "premium": premium_presence,
            "open_interest": open_interest_presence,
        },
        "basis_metadata": basis_metadata,
        "funding_snapshot_metadata_available": RAW_FUNDING_INFO_DIR.exists(),
    }

    quality = {
        "panel_start_date": panel["date"].iloc[0],
        "panel_end_date": panel["date"].iloc[-1],
        "spot_last_date": spot.index.max().strftime("%Y-%m-%d"),
        "field_coverage": {
            "funding_rate_daily": summarize_field_coverage(panel.set_index(pd.to_datetime(panel["date"])), "funding_rate_daily"),
            "basis_daily": summarize_field_coverage(panel.set_index(pd.to_datetime(panel["date"])), "basis_daily"),
            "premium_daily": summarize_field_coverage(panel.set_index(pd.to_datetime(panel["date"])), "premium_daily"),
            "open_interest_daily": summarize_field_coverage(panel.set_index(pd.to_datetime(panel["date"])), "open_interest_daily"),
            "leverage_proxy": summarize_field_coverage(panel.set_index(pd.to_datetime(panel["date"])), "leverage_proxy"),
        },
        "coverage_windows": panel_level_meta["coverage_windows"],
        "daily_causal_ready_days": int(panel["daily_causal_ready"].sum()),
        "probe_input_ready_days": int(panel["probe_input_ready_flag"].sum()),
        "max_consecutive_daily_causal_ready_days": compute_consecutive_true_count(panel["daily_causal_ready"]),
        "max_consecutive_probe_input_ready_days": compute_consecutive_true_count(panel["probe_input_ready_flag"]),
        "first_daily_causal_ready_date": (
            panel.loc[panel["daily_causal_ready"], "date"].iloc[0] if panel["daily_causal_ready"].any() else None
        ),
        "last_daily_causal_ready_date": (
            panel.loc[panel["daily_causal_ready"], "date"].iloc[-1] if panel["daily_causal_ready"].any() else None
        ),
        "first_probe_input_ready_date": (
            panel.loc[panel["probe_input_ready_flag"], "date"].iloc[0] if panel["probe_input_ready_flag"].any() else None
        ),
        "last_probe_input_ready_date": (
            panel.loc[panel["probe_input_ready_flag"], "date"].iloc[-1] if panel["probe_input_ready_flag"].any() else None
        ),
        "limitations": [],
    }

    if funding_presence["internal_gap_days"]:
        quality["limitations"].append(
            f"Funding daily history has internal missing UTC days inside its coverage window: {funding_presence['internal_gap_days']}"
        )
    if funding_presence["trailing_missing_days"]:
        quality["limitations"].append(
            f"Funding daily history goes stale after {funding_presence['last_present_date']} with trailing missing UTC days through panel end: {funding_presence['trailing_missing_days']}"
        )
    if basis_presence["internal_gap_days"]:
        quality["limitations"].append(
            f"Basis daily history has internal missing UTC days inside its coverage window: {basis_presence['internal_gap_days']}"
        )
    if basis_presence["trailing_missing_days"]:
        quality["limitations"].append(
            f"Basis daily history goes stale after {basis_presence['last_present_date']} with trailing missing UTC days through panel end: {basis_presence['trailing_missing_days']}"
        )
    if premium_presence["internal_gap_days"]:
        quality["limitations"].append(
            f"Premium daily history has internal missing UTC days inside its coverage window: {premium_presence['internal_gap_days']}"
        )
    if premium_presence["trailing_missing_days"]:
        quality["limitations"].append(
            f"Premium daily history goes stale after {premium_presence['last_present_date']} with trailing missing UTC days through panel end: {premium_presence['trailing_missing_days']}"
        )
    if open_interest_presence["trailing_missing_days"]:
        quality["limitations"].append(
            f"Open-interest daily history is extremely short and goes stale after {open_interest_presence['last_present_date']} with trailing missing UTC days through panel end: {open_interest_presence['trailing_missing_days']}"
        )
    if panel_level_meta["basis_metadata"]["annualized_basis_rate_all_null"]:
        quality["limitations"].append("Basis annualized_basis_rate is fully null in the raw Binance datasets.")
    if panel_level_meta["basis_metadata"]["contract_type_all_null"]:
        quality["limitations"].append("Basis contractType metadata is fully null in the raw Binance datasets.")
    quality["limitations"].append("Exact estimated leverage ratio is unavailable; leverage_proxy is an explicit proxy only.")
    quality["limitations"].append("No multi-venue aggregation is available; all derivatives inputs are Binance-only.")

    verdict, recency_lag_days = derive_verdict(
        panel=panel.set_index(pd.to_datetime(panel["date"])),
        spot_last_date=spot.index.max(),
    )
    quality["recency_lag_days_vs_spot_for_core_fields"] = recency_lag_days
    quality["ready_for_dev_only_probe"] = verdict.ready_for_dev_only_probe
    quality["verdict"] = verdict.verdict
    quality["verdict_reason"] = verdict.reason

    return panel, panel_level_meta, quality


def build_manifest(*, output_dir: Path, funding_lookback_days: int) -> dict[str, Any]:
    return with_dev_flags(
        {
            "artifact_type": "dev_only_btc_derivatives_daily_panel_manifest",
            "artifact_id": FAMILY_ID,
            "generated_at_utc": timestamp_utc(),
            "family_id": FAMILY_ID,
            "family_type": FAMILY_TYPE,
            "output_files": {
                "panel_csv": str(output_dir / OUTPUT_CSV.name),
                "manifest_json": str(output_dir / OUTPUT_MANIFEST.name),
                "quality_json": str(output_dir / OUTPUT_QUALITY.name),
            },
            "input_refs": [
                str(SPOT_PATH),
                str(LEGACY_FUNDING_PATH),
                str(RAW_FUNDING_DIR),
                str(RAW_BASIS_5M_DIR),
                str(RAW_BASIS_1H_DIR),
                str(RAW_PREMIUM_5M_DIR),
                str(RAW_OPEN_INTEREST_1H_DIR),
                str(RAW_OPEN_INTEREST_5M_DIR),
                str(RAW_FUNDING_INFO_DIR),
            ],
            "column_schema": PANEL_COLUMNS,
            "utc_closed_day_semantics": {
                "date_field_meaning": "UTC closed market day D aggregated only from timestamps inside D.",
                "downstream_usage_rule": "Rows for UTC day D are intended for D+1 daily research use only.",
                "funding_rate_daily_definition": "Sum of all BTC funding fixes that fall inside UTC day D.",
                "funding_rate_lookback_definition": f"{funding_lookback_days}-calendar-day rolling mean of funding_rate_daily requiring a fully populated window.",
                "basis_daily_definition": "Arithmetic mean of Binance 5m basis_rate across UTC day D, with 1h fallback only if 5m day is unavailable.",
                "premium_daily_definition": "Arithmetic mean of Binance 5m premium_close across UTC day D.",
                "open_interest_daily_definition": "Best-available end-of-day Binance oi_value snapshot for UTC day D, favoring full-day coverage over higher frequency partial days.",
                "open_interest_change_definition": "One-day percent change in open_interest_daily, only across consecutive UTC days.",
                "leverage_proxy_definition": "Proxy only: open_interest_daily divided by estimated spot market cap using CMCCirculatingSupply * btc_spot_close.",
            },
            "source_metadata": {
                "funding_primary_sources": ["binance_legacy_csv", "binance_raw_parquet"],
                "basis_primary_source": "binance_basis_5m",
                "basis_fallback_source": "binance_basis_1h_fallback",
                "premium_primary_source": "binance_premium_klines_5m",
                "open_interest_sources": ["binance_open_interest_1h", "binance_open_interest_5m"],
                "exact_estimated_leverage_ratio_available": False,
                "multi_venue_available": False,
            },
            "status": "generated_dev_only_research_data_layer",
        }
    )


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    panel, panel_level_meta, quality = build_panel(
        funding_lookback_days=int(args.funding_lookback_days),
        start_date_text=str(args.start_date).strip() or None,
    )

    panel_path = output_dir / OUTPUT_CSV.name
    manifest_path = output_dir / OUTPUT_MANIFEST.name
    quality_path = output_dir / OUTPUT_QUALITY.name

    panel.to_csv(panel_path, index=False)

    checks = run_feature_output_checks(
        columns=PANEL_COLUMNS,
        required_columns=PANEL_COLUMNS,
        rows=panel.to_dict(orient="records"),
    )

    manifest = build_manifest(output_dir=output_dir, funding_lookback_days=int(args.funding_lookback_days))
    manifest["row_count"] = int(len(panel))
    manifest["panel_level_meta"] = panel_level_meta

    quality_payload = with_dev_flags(
        {
            "artifact_type": "dev_only_btc_derivatives_daily_panel_quality",
            "artifact_id": f"{FAMILY_ID}_quality",
            "generated_at_utc": timestamp_utc(),
            "family_id": FAMILY_ID,
            "row_count": int(len(panel)),
            "required_columns": PANEL_COLUMNS,
            "leakage_checks": checks,
            "status": "passed" if all(item["ok"] for item in checks) else "failed",
            **quality,
        }
    )

    write_json(manifest_path, manifest)
    write_json(quality_path, quality_payload)

    print(f"{FAMILY_ID} dev-only output generated")
    print(panel_path)
    print(manifest_path)
    print(quality_path)
    print(f"verdict={quality_payload['verdict']}")
    print(f"ready_for_dev_only_probe={quality_payload['ready_for_dev_only_probe']}")

    if args.require_ready and not quality_payload["ready_for_dev_only_probe"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
