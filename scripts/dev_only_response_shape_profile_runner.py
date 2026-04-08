from __future__ import annotations

from research_os_dev_only_response_shape_output_common import (
    build_profile_payload,
    load_response_shape_frame,
    refresh_manifest_profile_path,
    response_shape_file_paths,
    save_json,
)


BOT_ID = "response_shape_bot_v1"
NUMERIC_COLUMNS = [
    "observed_return_3d",
    "observed_return_5d",
    "observed_return_10d",
    "observed_max_drawdown_5d",
    "observed_max_drawdown_10d",
    "observed_recovery_from_5d_low_to_10d",
    "observed_realized_volatility_10d",
    "observed_downside_volatility_10d",
    "follow_through_quality",
    "false_start_risk",
    "volatility_damage_shape",
    "recovery_vs_exhaustion",
]


def main() -> None:
    paths = response_shape_file_paths(BOT_ID)
    frame = load_response_shape_frame(paths["features_csv"])
    payload = build_profile_payload(bot_id=BOT_ID, df=frame, numeric_columns=NUMERIC_COLUMNS)
    save_json(paths["profile_json"], payload)
    refresh_manifest_profile_path(paths["manifest_json"], paths["profile_json"])

    print(f"{BOT_ID} response-shape profile generated")
    print(paths["profile_json"])


if __name__ == "__main__":
    main()
