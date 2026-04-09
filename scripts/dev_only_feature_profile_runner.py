from __future__ import annotations

import argparse

import pandas as pd

from research_os_dev_only_feature_output_common import feature_file_paths
from research_os_dev_only_feature_profile_common import (
    build_profile_payload,
    load_feature_frame,
    refresh_manifest_profile_path,
    write_profile,
)


FAMILY_CONFIG = {
    "pre_move_structure_quality_stack": {
        "coverage_column": "asset",
        "numeric_columns": [
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
        ],
    },
    "participation_breadth_confirmation_stack": {
        "coverage_column": "leader_asset",
        "numeric_columns": [
            "breadth_count",
            "participation_ratio",
            "leader_follower_spread",
            "cluster_confirmation_ratio",
            "internal_agreement_score",
            "breadth_thrust",
            "participation_divergence",
        ],
    },
    "cross_asset_decoupling_stack": {
        "coverage_column": "asset",
        "numeric_columns": [
            "rolling_correlation_break",
            "beta_deviation",
            "relative_momentum_decoupling",
            "leader_lag_follower_escape",
            "isolated_strength_flag",
            "isolated_weakness_flag",
        ],
    },
    "liquidity_stress_anomaly_stack": {
        "coverage_column": "asset",
        "numeric_columns": [
            "abnormal_volume_burst",
            "liquidity_dry_up",
            "stress_persistence",
            "liquidity_vacuum_proxy",
            "unstable_reversal_pressure",
        ],
    },
    "event_context_flags_stack": {
        "coverage_column": "asset",
        "numeric_columns": [
            "session_transition_flag",
            "scheduled_event_proximity_flag",
            "post_event_stabilization_flag",
            "pre_event_compression_flag",
            "funding_reset_context_flag",
            "volatility_regime_shift_flag",
        ],
    },
}

PRE_MOVE_PHASE67_PAPER_PATH = r"C:\Users\benda\Desktop\market_regime_v1\outputs\execution\app_exports\phase67j_no_neo_main_paper.csv"
PRE_MOVE_PHASE68_PAPER_PATH = r"C:\Users\benda\Desktop\market_regime_v1\outputs\execution\app_exports\phase68i_dynamic_ladder_candidate_paper.csv"
PRE_MOVE_WICK_EXTREME_THRESHOLD = 8.0


def build_pre_move_guardrails(frame: pd.DataFrame) -> tuple[dict, dict]:
    phase67 = pd.read_csv(PRE_MOVE_PHASE67_PAPER_PATH)
    phase68 = pd.read_csv(PRE_MOVE_PHASE68_PAPER_PATH)
    phase67["date"] = pd.to_datetime(phase67["date"], errors="coerce")
    phase68["date"] = pd.to_datetime(phase68["date"], errors="coerce")
    phase67["executed_regime"] = phase67["executed_regime"].fillna("").astype(str).str.strip().str.upper()
    phase68["overlay_candidate_clean"] = phase68["overlay_candidate_clean"].fillna("").astype(str).str.strip().str.upper()

    overlay_assets = sorted(
        f"{asset}USDT"
        for asset in phase68["overlay_candidate_clean"].replace("", pd.NA).dropna().unique().tolist()
    )
    merged = phase68.merge(phase67[["date", "executed_regime"]], on="date", how="inner")
    gated_assets = sorted(
        f"{asset}USDT"
        for asset in merged.loc[
            (merged["overlay_candidate_clean"] != "") & (merged["executed_regime"] != "CASH"),
            "overlay_candidate_clean",
        ].unique().tolist()
    )

    extreme_mask = pd.to_numeric(frame["wick_body_ratio"], errors="coerce").fillna(0.0) >= PRE_MOVE_WICK_EXTREME_THRESHOLD
    extreme_rows = frame.loc[extreme_mask, ["date", "asset", "wick_body_ratio"]].copy()
    extreme_rows["date"] = pd.to_datetime(extreme_rows["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    extreme_rows = extreme_rows.sort_values(["wick_body_ratio", "date", "asset"], ascending=[False, True, True]).head(5)

    guardrails = {
        "extreme_wick_body_ratio_guardrail": {
            "threshold": PRE_MOVE_WICK_EXTREME_THRESHOLD,
            "row_count": int(extreme_mask.sum()),
            "top_rows": [
                {
                    "date": str(row["date"]),
                    "asset": str(row["asset"]),
                    "wick_body_ratio": round(float(row["wick_body_ratio"]), 6),
                }
                for _, row in extreme_rows.iterrows()
            ],
            "status": "guardrail_triggered" if int(extreme_mask.sum()) > 0 else "guardrail_clear",
        }
    }
    extra_sections = {
        "coverage_diagnostic": {
            "coverage_shape_status": "narrow_by_current_overlay_gating",
            "intended_by_current_gating": True,
            "gating_rule": "rows require non-empty phase68 overlay_candidate_clean and non-CASH phase67 executed_regime",
            "phase68_overlay_candidate_unique_assets": overlay_assets,
            "gated_feature_asset_coverage": gated_assets,
        }
    }
    return guardrails, extra_sections


def build_breadth_guardrails(frame: pd.DataFrame) -> tuple[dict, pd.Series]:
    degenerate_mask = (
        (pd.to_numeric(frame["breadth_count"], errors="coerce").fillna(0.0) <= 0.0)
        & (pd.to_numeric(frame["participation_ratio"], errors="coerce").fillna(0.0) <= 0.0)
        & (pd.to_numeric(frame["cluster_confirmation_ratio"], errors="coerce").fillna(0.0) <= 0.0)
    )
    degenerate_rows = frame.loc[degenerate_mask, ["date", "leader_asset", "breadth_thrust", "participation_divergence"]].copy()
    degenerate_rows["date"] = pd.to_datetime(degenerate_rows["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    degenerate_rows = degenerate_rows.sort_values(
        ["participation_divergence", "date", "leader_asset"],
        ascending=[False, True, True],
    ).head(5)

    guardrails = {
        "degenerate_empty_participation_guardrail": {
            "rule": "breadth_count == 0 and participation_ratio == 0 and cluster_confirmation_ratio == 0",
            "row_count": int(degenerate_mask.sum()),
            "top_rows": [
                {
                    "date": str(row["date"]),
                    "leader_asset": str(row["leader_asset"]),
                    "breadth_thrust": round(float(row["breadth_thrust"]), 6),
                    "participation_divergence": round(float(row["participation_divergence"]), 6),
                }
                for _, row in degenerate_rows.iterrows()
            ],
            "profile_abnormal_list_policy": "deprioritize_degenerate_empty_participation_rows_but_keep_them_counted",
            "status": "guardrail_triggered" if int(degenerate_mask.sum()) > 0 else "guardrail_clear",
        }
    }
    return guardrails, degenerate_mask


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build compact dev-only feature profile artifact for one family")
    parser.add_argument("--family", required=True, choices=sorted(FAMILY_CONFIG))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    family_id = args.family
    config = FAMILY_CONFIG[family_id]
    paths = feature_file_paths(family_id)
    frame = load_feature_frame(paths["features_csv"])
    profile_guardrails = None
    deprioritize_mask = None
    extra_row_fields = None
    extra_sections = None

    if family_id == "pre_move_structure_quality_stack":
        profile_guardrails, extra_sections = build_pre_move_guardrails(frame)
    elif family_id == "participation_breadth_confirmation_stack":
        frame = frame.copy()
        profile_guardrails, deprioritize_mask = build_breadth_guardrails(frame)
        frame["profile_guardrail_reason"] = ""
        frame.loc[deprioritize_mask, "profile_guardrail_reason"] = "degenerate_empty_participation"
        extra_row_fields = ["profile_guardrail_reason"]

    payload = build_profile_payload(
        family_id=family_id,
        df=frame,
        coverage_column=config["coverage_column"],
        numeric_columns=config["numeric_columns"],
        profile_guardrails=profile_guardrails,
        deprioritize_mask=deprioritize_mask,
        extra_row_fields=extra_row_fields,
        extra_sections=extra_sections,
    )
    write_profile(paths["profile_json"], payload)
    refresh_manifest_profile_path(paths["manifest_json"], paths["profile_json"])

    print(f"{family_id} dev-only profile generated")
    print(paths["profile_json"])


if __name__ == "__main__":
    main()
