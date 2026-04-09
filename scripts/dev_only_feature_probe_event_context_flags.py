from __future__ import annotations

import argparse
import calendar
from typing import Dict, List

import pandas as pd

from research_os_dev_only_feature_anti_leakage import run_feature_output_checks
from research_os_dev_only_feature_inputs_common import (
    CORE_OHLCV_DIR,
    PHASE67_PAPER_PATH,
    PHASE68_PAPER_PATH,
    TOP100_OHLCV_DIR,
    load_active_leader_rows,
    load_daily_ohlcv,
    load_phase68_context,
)
from research_os_dev_only_feature_output_common import (
    build_manifest,
    build_quality_report,
    feature_file_paths,
    save_csv,
    save_json,
)


LOOKBACK_DAYS = 20

FAMILY_ID = "event_context_flags_stack"
FAMILY_TYPE = "event-context"
REQUIRED_COLUMNS = [
    "date",
    "asset",
    "session_transition_flag",
    "scheduled_event_proximity_flag",
    "post_event_stabilization_flag",
    "pre_event_compression_flag",
    "funding_reset_context_flag",
    "volatility_regime_shift_flag",
    "feature_ready_flag",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only event context flags feature probe")
    parser.add_argument("--asset", default="", help="Optional asset filter such as STX or STXUSDT.")
    return parser.parse_args()


def is_month_boundary_window(date: pd.Timestamp) -> bool:
    last_day = calendar.monthrange(date.year, date.month)[1]
    return date.day <= 2 or date.day >= last_day - 1


def is_next_calendar_boundary(date: pd.Timestamp) -> bool:
    next_day = date + pd.Timedelta(days=1)
    return next_day.weekday() == 0 or is_month_boundary_window(next_day)


def context_event_flag(date: pd.Timestamp, context_by_date: pd.DataFrame) -> int:
    flag_columns = [
        "asset_transition_day",
        "tradable_transition_day",
        "crossed_up_today",
        "crossed_down_today",
        "stress_block_day",
        "trend_block_day",
    ]
    if date not in context_by_date.index:
        return 0
    row = context_by_date.loc[date]
    return int(any(float(row.get(column, 0.0)) > 0.0 for column in flag_columns))


def build_feature_row(
    date: pd.Timestamp,
    asset: str,
    asset_cache: Dict[str, object],
    context_by_date: pd.DataFrame,
) -> Dict[str, object] | None:
    asset_frame = load_daily_ohlcv(asset, asset_cache, directories=[TOP100_OHLCV_DIR, CORE_OHLCV_DIR])
    if date not in asset_frame.index:
        return None

    position = asset_frame.index.get_loc(date)
    if isinstance(position, slice):
        position = position.stop - 1
    if position + 1 < LOOKBACK_DAYS:
        return None

    window = asset_frame.iloc[position + 1 - LOOKBACK_DAYS : position + 1].copy()
    recent = window.tail(5)
    current = window.iloc[-1]

    session_transition_flag = int(date.weekday() == 0)
    scheduled_event_proximity_flag = int(is_month_boundary_window(date) or context_event_flag(date, context_by_date) > 0)

    previous_date = date - pd.Timedelta(days=1)
    previous_context_flag = int(is_month_boundary_window(previous_date) or context_event_flag(previous_date, context_by_date) > 0 or previous_date.weekday() == 0)
    post_event_stabilization_flag = int(
        previous_context_flag > 0
        and abs(float(current["base_ret"])) <= recent["base_ret"].abs().mean()
        and float(current["range_pct"]) <= recent["range_pct"].mean()
    )

    trailing_range_mean = window.tail(3)["range_pct"].mean()
    trailing_abs_ret_mean = window.tail(3)["base_ret"].abs().mean()
    reference_range_mean = window["range_pct"].mean()
    reference_abs_ret_mean = window["base_ret"].abs().mean()
    pre_event_compression_flag = int(
        is_next_calendar_boundary(date)
        and trailing_range_mean <= reference_range_mean
        and trailing_abs_ret_mean <= reference_abs_ret_mean
    )

    funding_reset_context_flag = int(date.weekday() == 4)
    vol5 = recent["base_ret"].std(ddof=0)
    vol20 = window["base_ret"].std(ddof=0)
    volatility_regime_shift_flag = int(vol20 > 0.0 and (vol5 >= vol20 * 1.5 or vol5 <= vol20 * 0.67))

    return {
        "date": date.strftime("%Y-%m-%d"),
        "asset": asset,
        "session_transition_flag": session_transition_flag,
        "scheduled_event_proximity_flag": scheduled_event_proximity_flag,
        "post_event_stabilization_flag": post_event_stabilization_flag,
        "pre_event_compression_flag": pre_event_compression_flag,
        "funding_reset_context_flag": funding_reset_context_flag,
        "volatility_regime_shift_flag": volatility_regime_shift_flag,
        "feature_ready_flag": True,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "strategy_advancement": False,
    }


def build_rows(asset_filter: str) -> List[Dict[str, object]]:
    active_rows = load_active_leader_rows(asset_filter)
    context_by_date = load_phase68_context()
    asset_cache: Dict[str, object] = {}
    rows: List[Dict[str, object]] = []
    for _, row in active_rows.iterrows():
        feature_row = build_feature_row(row["date"], str(row["asset"]), asset_cache, context_by_date)
        if feature_row is not None:
            rows.append(feature_row)
    return rows


def main() -> None:
    args = parse_args()
    rows = build_rows(args.asset)
    paths = feature_file_paths(FAMILY_ID)
    checks = run_feature_output_checks(columns=REQUIRED_COLUMNS, required_columns=REQUIRED_COLUMNS, rows=rows)

    save_csv(paths["features_csv"], rows, REQUIRED_COLUMNS)
    save_json(
        paths["manifest_json"],
        build_manifest(
            family_id=FAMILY_ID,
            family_type=FAMILY_TYPE,
            input_refs=[
                "data/ohlcv_phase67_top100/*.csv",
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
