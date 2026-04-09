from __future__ import annotations

import argparse
from typing import Dict, List

import numpy as np

from research_os_dev_only_feature_anti_leakage import run_feature_output_checks
from research_os_dev_only_feature_inputs_common import (
    CORE_OHLCV_DIR,
    EPSILON,
    PHASE67_PAPER_PATH,
    TOP100_OHLCV_DIR,
    load_active_leader_rows,
    load_daily_ohlcv,
    round_value,
)
from research_os_dev_only_feature_output_common import (
    build_manifest,
    build_quality_report,
    feature_file_paths,
    save_csv,
    save_json,
)


LOOKBACK_DAYS = 30
REFERENCE_DAYS = 20

FAMILY_ID = "liquidity_stress_anomaly_stack"
FAMILY_TYPE = "toxic-subset"
REQUIRED_COLUMNS = [
    "date",
    "asset",
    "abnormal_volume_burst",
    "liquidity_dry_up",
    "stress_persistence",
    "liquidity_vacuum_proxy",
    "unstable_reversal_pressure",
    "feature_ready_flag",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only liquidity stress anomaly feature probe")
    parser.add_argument("--asset", default="", help="Optional asset filter such as ICP or ICPUSDT.")
    return parser.parse_args()


def build_feature_row(date, asset: str, asset_cache: Dict[str, object]) -> Dict[str, object] | None:
    asset_frame = load_daily_ohlcv(asset, asset_cache, directories=[TOP100_OHLCV_DIR, CORE_OHLCV_DIR])
    if date not in asset_frame.index:
        return None

    position = asset_frame.index.get_loc(date)
    if isinstance(position, slice):
        position = position.stop - 1
    if position + 1 < LOOKBACK_DAYS:
        return None

    window = asset_frame.iloc[position + 1 - LOOKBACK_DAYS : position + 1].copy()
    reference = window.tail(REFERENCE_DAYS)
    recent = window.tail(5)
    current = window.iloc[-1]

    reference_dollar_volume = max(float(reference["dollar_volume_proxy"].median()), EPSILON)
    abnormal_volume_burst = float(np.clip(current["dollar_volume_proxy"] / reference_dollar_volume, 0.0, 10.0))
    liquidity_dry_up = float(np.clip(reference_dollar_volume / max(float(current["dollar_volume_proxy"]), EPSILON), 0.0, 10.0))

    range_reference = max(float(reference["range_pct"].median()), EPSILON)
    vol_reference = reference["realized_volatility_10"].dropna()
    realized_vol_reference = max(float(vol_reference.median()) if not vol_reference.empty else recent["base_ret"].abs().mean(), EPSILON)

    stress_mask = (recent["range_pct"] > range_reference) | (recent["realized_volatility_10"].fillna(0.0) > realized_vol_reference)
    stress_persistence = float(stress_mask.mean())

    liquidity_vacuum_proxy = float(np.clip(current["range_pct"] * liquidity_dry_up, 0.0, 10.0))
    unstable_reversal_pressure = float(
        np.clip(
            current["wick_share"] * (current["realized_volatility_10"] / realized_vol_reference) * (1.0 + stress_persistence),
            0.0,
            10.0,
        )
    )

    return {
        "date": date.strftime("%Y-%m-%d"),
        "asset": asset,
        "abnormal_volume_burst": round_value(abnormal_volume_burst),
        "liquidity_dry_up": round_value(liquidity_dry_up),
        "stress_persistence": round_value(stress_persistence),
        "liquidity_vacuum_proxy": round_value(liquidity_vacuum_proxy),
        "unstable_reversal_pressure": round_value(unstable_reversal_pressure),
        "feature_ready_flag": True,
        "dev_only": True,
        "non_authoritative": True,
        "official_truth": False,
        "strategy_advancement": False,
    }


def build_rows(asset_filter: str) -> List[Dict[str, object]]:
    active_rows = load_active_leader_rows(asset_filter)
    asset_cache: Dict[str, object] = {}
    rows: List[Dict[str, object]] = []
    for _, row in active_rows.iterrows():
        feature_row = build_feature_row(row["date"], str(row["asset"]), asset_cache)
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
