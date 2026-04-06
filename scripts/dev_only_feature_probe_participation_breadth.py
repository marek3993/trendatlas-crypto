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


FAMILY_ID = "participation_breadth_confirmation_stack"
FAMILY_TYPE = "confidence-stack"
REQUIRED_COLUMNS = [
    "date",
    "leader_asset",
    "breadth_count",
    "participation_ratio",
    "leader_follower_spread",
    "cluster_confirmation_ratio",
    "internal_agreement_score",
    "breadth_thrust",
    "participation_divergence",
    "feature_ready_flag",
    "dev_only",
    "non_authoritative",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dev-only participation breadth feature probe")
    parser.add_argument("--leader-asset", default="BTCUSDT")
    return parser.parse_args()


def build_demo_rows(leader_asset: str) -> List[Dict[str, Any]]:
    return [
        {
            "date": "2026-04-01",
            "leader_asset": leader_asset,
            "breadth_count": 8,
            "participation_ratio": 0.62,
            "leader_follower_spread": 0.14,
            "cluster_confirmation_ratio": 0.58,
            "internal_agreement_score": 0.61,
            "breadth_thrust": 0.21,
            "participation_divergence": 0.11,
            "feature_ready_flag": True,
            "dev_only": True,
            "non_authoritative": True,
        },
        {
            "date": "2026-04-02",
            "leader_asset": leader_asset,
            "breadth_count": 10,
            "participation_ratio": 0.70,
            "leader_follower_spread": 0.09,
            "cluster_confirmation_ratio": 0.67,
            "internal_agreement_score": 0.69,
            "breadth_thrust": 0.28,
            "participation_divergence": 0.07,
            "feature_ready_flag": True,
            "dev_only": True,
            "non_authoritative": True,
        },
    ]


def main() -> None:
    args = parse_args()
    rows = build_demo_rows(args.leader_asset)
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
                "data/ohlcv_phase67_top100/*.csv",
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
