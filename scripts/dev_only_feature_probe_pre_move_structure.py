from __future__ import annotations

import argparse
from typing import Any, Dict, List

from research_os_dev_only_feature_output_common import (
    build_manifest,
    build_quality_report,
    feature_file_paths,
    save_csv,
    save_json,
)
from research_os_dev_only_feature_anti_leakage import run_feature_output_checks


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
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only pre-move structure feature probe")
    parser.add_argument("--asset", default="BTCUSDT")
    return parser.parse_args()


def build_demo_rows(asset: str) -> List[Dict[str, Any]]:
    return [
        {
            "date": "2026-04-01",
            "asset": asset,
            "base_ret": 0.0042,
            "range_pct": 0.0180,
            "wick_body_ratio": 1.10,
            "local_volatility": 0.0210,
            "trend_score": 0.42,
            "compression_tightness": 0.77,
            "compression_duration": 4,
            "release_asymmetry": 0.31,
            "acceleration_build": 0.18,
            "failed_break_pre_signal": 0,
            "bar_quality_consistency": 0.74,
            "feature_ready_flag": True,
            "dev_only": True,
            "non_authoritative": True,
        },
        {
            "date": "2026-04-02",
            "asset": asset,
            "base_ret": 0.0025,
            "range_pct": 0.0150,
            "wick_body_ratio": 0.95,
            "local_volatility": 0.0180,
            "trend_score": 0.47,
            "compression_tightness": 0.81,
            "compression_duration": 5,
            "release_asymmetry": 0.36,
            "acceleration_build": 0.22,
            "failed_break_pre_signal": 0,
            "bar_quality_consistency": 0.79,
            "feature_ready_flag": True,
            "dev_only": True,
            "non_authoritative": True,
        },
    ]


def main() -> None:
    args = parse_args()
    rows = build_demo_rows(args.asset)
    paths = feature_file_paths(FAMILY_ID)
    columns = list(rows[0].keys())

    checks = run_feature_output_checks(columns=columns, required_columns=REQUIRED_COLUMNS, rows=rows)

    save_csv(paths["features_csv"], rows, REQUIRED_COLUMNS)
    save_json(
        paths["manifest_json"],
        build_manifest(
            family_id=FAMILY_ID,
            family_type=FAMILY_TYPE,
            input_refs=[
                "data/ohlcv/*.csv",
                "outputs/execution/app_exports/phase67j_no_neo_main_paper.csv",
                "outputs/execution/app_exports/phase68i_dynamic_ladder_candidate_paper.csv",
            ],
            features_csv_path=paths["features_csv"],
            quality_json_path=paths["quality_json"],
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
