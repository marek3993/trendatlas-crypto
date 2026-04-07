from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from research_os_dev_only_feature_output_common import (
    build_manifest,
    build_quality_report,
    feature_file_paths,
    save_csv,
    save_json,
)
from research_os_dev_only_feature_anti_leakage import run_feature_output_checks


ROOT = Path(__file__).resolve().parents[1]
PHASE67_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase67j_no_neo_main_paper.csv"
PHASE68_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68i_dynamic_ladder_candidate_paper.csv"
OHLCV_DIR = ROOT / "data" / "ohlcv"
LOOKBACK_DAYS = 20
EPSILON = 1e-9
WICK_BODY_DENOMINATOR_FLOOR_SHARE = 0.10

FAMILY_ID = "pre_move_structure_quality_stack"
FAMILY_TYPE = "pre-move"
REQUIRED_COLUMNS = [
    "date",
    "asset",
    "base_ret",
    "range_pct",
    "wick_body_ratio",
    "local_volatility",
    "trend_score",
    "compression_tightness",
    "compression_duration",
    "release_asymmetry",
    "acceleration_build",
    "failed_break_pre_signal",
    "bar_quality_consistency",
    "feature_ready_flag",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only pre-move structure feature probe")
    parser.add_argument(
        "--asset",
        default="",
        help="Optional asset filter such as DOGE or DOGEUSDT.",
    )
    return parser.parse_args()


def normalize_asset_label(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text or text in {"NAN", "NONE"}:
        return ""
    if text.endswith("USDT"):
        return text[:-4]
    return text


def to_float(value: object) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return 0.0
    return float(numeric)


def round_value(value: float) -> float:
    return round(float(value), 6)


def load_ohlcv(asset_code: str, cache: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    if asset_code in cache:
        return cache[asset_code]

    path = OHLCV_DIR / f"{asset_code}USDT_1d.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing OHLCV input for {asset_code}: {path}")

    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).set_index("date")
    df["base_ret"] = df["close"].pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df["range_pct"] = ((df["high"] - df["low"]) / df["close"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    df["range_pct"] = df["range_pct"].fillna(0.0)
    df["body_size"] = (df["close"] - df["open"]).abs()
    df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
    wick_total = df["upper_wick"] + df["lower_wick"]
    body_floor = (df["high"] - df["low"]) * WICK_BODY_DENOMINATOR_FLOOR_SHARE
    effective_body_size = pd.concat([df["body_size"], body_floor], axis=1).max(axis=1)
    df["wick_body_ratio"] = (wick_total / (effective_body_size + EPSILON)).clip(lower=0.0, upper=10.0)
    df["local_volatility"] = df["base_ret"].rolling(10).std(ddof=0)
    price_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_location"] = ((2.0 * df["close"] - df["high"] - df["low"]) / price_range).clip(-1.0, 1.0)
    cache[asset_code] = df
    return df


def load_candidate_rows(asset_filter: str) -> pd.DataFrame:
    phase67 = pd.read_csv(PHASE67_PAPER_PATH)
    phase68 = pd.read_csv(PHASE68_PAPER_PATH)

    phase67["date"] = pd.to_datetime(phase67["date"], errors="coerce")
    phase68["date"] = pd.to_datetime(phase68["date"], errors="coerce")

    phase67 = phase67.dropna(subset=["date"]).copy()
    phase68 = phase68.dropna(subset=["date"]).copy()
    phase67["executed_regime"] = phase67["executed_regime"].fillna("").astype(str).str.strip().str.upper()
    phase68["asset_code"] = phase68["overlay_candidate_clean"].map(normalize_asset_label)

    merged = phase68.merge(
        phase67[["date", "executed_regime"]],
        on="date",
        how="inner",
        suffixes=("", "_phase67"),
    )
    merged = merged[(merged["asset_code"] != "") & (merged["executed_regime"] != "CASH")].copy()

    normalized_filter = normalize_asset_label(asset_filter)
    if normalized_filter:
        merged = merged[merged["asset_code"] == normalized_filter].copy()

    merged = merged.sort_values("date").reset_index(drop=True)
    return merged


def compute_compression_duration(window: pd.DataFrame) -> int:
    reference_range = window["range_pct"].median()
    reference_vol = window["local_volatility"].dropna().tail(5).mean()
    if pd.isna(reference_vol) or reference_vol <= 0:
        reference_vol = window["base_ret"].abs().mean()
    calm_mask = (window["range_pct"] <= reference_range) & (window["base_ret"].abs() <= reference_vol + EPSILON)

    duration = 0
    for is_calm in reversed(calm_mask.tolist()):
        if not is_calm:
            break
        duration += 1
    return duration


def compute_failed_breaks(window: pd.DataFrame) -> int:
    failed_breaks = 0
    for idx in range(3, len(window)):
        current = window.iloc[idx]
        prior = window.iloc[idx - 3 : idx]
        upside_failed = current["high"] > prior["high"].max() and current["close"] < prior["high"].max()
        downside_failed = current["low"] < prior["low"].min() and current["close"] > prior["low"].min()
        failed_breaks += int(upside_failed or downside_failed)
    return failed_breaks


def build_feature_row(context_row: pd.Series, ohlcv: pd.DataFrame) -> Dict[str, object] | None:
    date = context_row["date"]
    if date not in ohlcv.index:
        return None

    position = ohlcv.index.get_loc(date)
    if isinstance(position, slice):
        position = position.stop - 1
    if position + 1 < LOOKBACK_DAYS:
        return None

    window = ohlcv.iloc[position + 1 - LOOKBACK_DAYS : position + 1].copy()
    recent = window.tail(5)
    historical = window.tail(10)
    prior_reference = window.head(10)

    recent_range_mean = recent["range_pct"].mean()
    prior_range_mean = prior_reference["range_pct"].mean()
    compression_tightness = 1.0 - (recent_range_mean / (prior_range_mean + EPSILON))
    compression_tightness = float(np.clip(compression_tightness, 0.0, 1.0))

    release_asymmetry = float(np.clip(recent["close_location"].tail(3).mean(), -1.0, 1.0))

    acceleration_build = float(
        np.nanmean(np.diff(window["base_ret"].tail(4).to_numpy()))
        if len(window) >= 4
        else 0.0
    )

    range_consistency = 1.0 - (historical["range_pct"].std(ddof=0) / (historical["range_pct"].mean() + EPSILON))
    wick_penalty = 1.0 / (1.0 + historical["wick_body_ratio"].mean())
    bar_quality_consistency = float(np.clip(range_consistency * wick_penalty, 0.0, 1.0))

    return {
        "date": date.strftime("%Y-%m-%d"),
        "asset": f"{context_row['asset_code']}USDT",
        "base_ret": round_value(window["base_ret"].iloc[-1]),
        "range_pct": round_value(window["range_pct"].iloc[-1]),
        "wick_body_ratio": round_value(window["wick_body_ratio"].iloc[-1]),
        "local_volatility": round_value(window["local_volatility"].iloc[-1]),
        "trend_score": round_value(to_float(context_row.get("trend_score", 0.0))),
        "compression_tightness": round_value(compression_tightness),
        "compression_duration": int(compute_compression_duration(window)),
        "release_asymmetry": round_value(release_asymmetry),
        "acceleration_build": round_value(acceleration_build),
        "failed_break_pre_signal": int(compute_failed_breaks(window)),
        "bar_quality_consistency": round_value(bar_quality_consistency),
        "feature_ready_flag": True,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "strategy_advancement": False,
    }


def build_real_rows(asset_filter: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    ohlcv_cache: Dict[str, pd.DataFrame] = {}

    for _, context_row in load_candidate_rows(asset_filter).iterrows():
        asset_code = str(context_row["asset_code"])
        try:
            ohlcv = load_ohlcv(asset_code, ohlcv_cache)
        except FileNotFoundError:
            continue

        feature_row = build_feature_row(context_row, ohlcv)
        if feature_row is not None:
            rows.append(feature_row)

    return rows


def main() -> None:
    args = parse_args()
    rows = build_real_rows(args.asset)
    paths = feature_file_paths(FAMILY_ID)
    columns = REQUIRED_COLUMNS

    checks = run_feature_output_checks(columns=columns, required_columns=REQUIRED_COLUMNS, rows=rows)

    save_csv(paths["features_csv"], rows, REQUIRED_COLUMNS)
    save_json(
        paths["manifest_json"],
        build_manifest(
            family_id=FAMILY_ID,
            family_type=FAMILY_TYPE,
            input_refs=[
                "data/ohlcv/*.csv",
                str(PHASE67_PAPER_PATH),
                str(PHASE68_PAPER_PATH),
            ],
            features_csv_path=paths["features_csv"],
            quality_json_path=paths["quality_json"],
            profile_json_path=paths["profile_json"],
            column_schema=REQUIRED_COLUMNS,
            row_count=len(rows),
        ),
    )
    save_json(
        paths["quality_json"],
        build_quality_report(
            family_id=FAMILY_ID,
            row_count=len(rows),
            required_columns=REQUIRED_COLUMNS,
            leakage_checks=checks,
        ),
    )

    print(f"{FAMILY_ID} dev-only outputs generated")
    print(paths["features_csv"])
    print(paths["manifest_json"])
    print(paths["quality_json"])


if __name__ == "__main__":
    main()
