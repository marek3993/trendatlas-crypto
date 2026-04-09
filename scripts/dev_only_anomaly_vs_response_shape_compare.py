from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import pandas as pd

from research_os_dev_only_bot_compare_common import (
    MANDATORY_DEV_FLAGS,
    compare_file_paths,
    save_csv,
    save_json,
    timestamp_utc,
    with_dev_flags,
)


ROOT = Path(__file__).resolve().parents[1]
ANOMALY_CSV_PATH = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_features" / "anomaly_ranking_heuristics.csv"
RESPONSE_CSV_PATH = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_response_shape" / "response_shape_bot_v1.features.csv"

COMPARE_ID = "anomaly_vs_response_shape_comparison"
CSV_COLUMNS = [
    "date",
    "entity",
    "anomaly_interestingness_score",
    "anomaly_active_family_count",
    "anomaly_cluster_note",
    "response_shape_follow_through_quality",
    "response_shape_false_start_risk",
    "response_shape_volatility_damage_shape",
    "response_shape_recovery_vs_exhaustion",
    "response_shape_context",
    "agreement_class",
    "comparison_note",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare anomaly operating layer vs response_shape_bot_v1 by exact shared keys")
    parser.add_argument("--anomaly-csv", type=str, default=str(ANOMALY_CSV_PATH))
    parser.add_argument("--response-csv", type=str, default=str(RESPONSE_CSV_PATH))
    return parser.parse_args()


def load_anomaly_rows(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["entity"] = df["entity"].fillna("").astype(str).str.upper().str.strip()
    keep = [
        "date",
        "entity",
        "interestingness_score",
        "active_family_count",
        "cluster_note",
    ]
    out = df[keep].copy()
    out = out.rename(
        columns={
            "interestingness_score": "anomaly_interestingness_score",
            "active_family_count": "anomaly_active_family_count",
            "cluster_note": "anomaly_cluster_note",
        }
    )
    return out.dropna(subset=["date"]).drop_duplicates(subset=["date", "entity"], keep="first")


def load_response_rows(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["entity"] = df["selected_asset"].fillna("").astype(str).str.upper().str.strip()
    keep = [
        "date",
        "entity",
        "follow_through_quality",
        "false_start_risk",
        "volatility_damage_shape",
        "recovery_vs_exhaustion",
        "response_regime_context",
    ]
    out = df[keep].copy()
    out = out.rename(
        columns={
            "follow_through_quality": "response_shape_follow_through_quality",
            "false_start_risk": "response_shape_false_start_risk",
            "volatility_damage_shape": "response_shape_volatility_damage_shape",
            "recovery_vs_exhaustion": "response_shape_recovery_vs_exhaustion",
            "response_regime_context": "response_shape_context",
        }
    )
    return out.dropna(subset=["date"]).drop_duplicates(subset=["date", "entity"], keep="first")


def classify_overlap(row: pd.Series) -> str:
    anomaly_present = pd.notna(row["anomaly_interestingness_score"])
    response_present = pd.notna(row["response_shape_follow_through_quality"])
    if anomaly_present and response_present:
        follow = float(row["response_shape_follow_through_quality"])
        false_start = float(row["response_shape_false_start_risk"])
        volatility_damage = float(row["response_shape_volatility_damage_shape"])
        if follow > 0.0 and false_start <= 0.02 and volatility_damage <= 0.35:
            return "overlap_supportive"
        if follow <= 0.0 or false_start >= 0.05 or volatility_damage >= 0.60:
            return "overlap_caution"
        return "overlap_mixed"
    if anomaly_present:
        return "anomaly_only"
    return "response_shape_only"


def comparison_note(row: pd.Series) -> str:
    cls = row["agreement_class"]
    if cls == "anomaly_only":
        return "anomaly operating row has no exact response-shape match on date+entity"
    if cls == "response_shape_only":
        return "response-shape row has no exact anomaly operating match on date+entity"
    if cls == "overlap_supportive":
        return "exact shared key shows anomaly overlap alongside constructive response-shape aftermath"
    if cls == "overlap_caution":
        return "exact shared key shows overlap but the aftermath profile is cautionary or false-start prone"
    return "exact shared key exists but overlap is mixed rather than clearly supportive or cautionary"


def build_comparison_rows(anomaly_df: pd.DataFrame, response_df: pd.DataFrame) -> List[Dict[str, object]]:
    merged = anomaly_df.merge(response_df, on=["date", "entity"], how="outer")
    merged["agreement_class"] = merged.apply(classify_overlap, axis=1)
    merged["comparison_note"] = merged.apply(comparison_note, axis=1)
    merged = merged.sort_values(
        by=["date", "entity", "agreement_class"],
        ascending=[True, True, True],
        kind="mergesort",
    )

    rows: List[Dict[str, object]] = []
    for _, row in merged.iterrows():
        payload = {
            "date": row["date"],
            "entity": row["entity"],
            "anomaly_interestingness_score": None if pd.isna(row.get("anomaly_interestingness_score")) else round(float(row["anomaly_interestingness_score"]), 6),
            "anomaly_active_family_count": None if pd.isna(row.get("anomaly_active_family_count")) else int(row["anomaly_active_family_count"]),
            "anomaly_cluster_note": "" if pd.isna(row.get("anomaly_cluster_note")) else str(row["anomaly_cluster_note"]),
            "response_shape_follow_through_quality": None if pd.isna(row.get("response_shape_follow_through_quality")) else round(float(row["response_shape_follow_through_quality"]), 6),
            "response_shape_false_start_risk": None if pd.isna(row.get("response_shape_false_start_risk")) else round(float(row["response_shape_false_start_risk"]), 6),
            "response_shape_volatility_damage_shape": None if pd.isna(row.get("response_shape_volatility_damage_shape")) else round(float(row["response_shape_volatility_damage_shape"]), 6),
            "response_shape_recovery_vs_exhaustion": None if pd.isna(row.get("response_shape_recovery_vs_exhaustion")) else round(float(row["response_shape_recovery_vs_exhaustion"]), 6),
            "response_shape_context": "" if pd.isna(row.get("response_shape_context")) else str(row["response_shape_context"]),
            "agreement_class": str(row["agreement_class"]),
            "comparison_note": str(row["comparison_note"]),
        }
        payload.update(MANDATORY_DEV_FLAGS)
        rows.append(payload)
    return rows


def build_watchlist_payload(
    *,
    artifact_type: str,
    artifact_id: str,
    rows: List[Dict[str, object]],
    note: str,
) -> Dict[str, object]:
    return with_dev_flags(
        {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "generated_at_utc": timestamp_utc(),
            "row_count": len(rows),
            "watchlist_rows": rows,
            "note": note,
        }
    )


def disagreement_priority(row: Dict[str, object]) -> float:
    if row["agreement_class"] == "anomaly_only":
        return float(row["anomaly_interestingness_score"] or 0.0) + float(row["anomaly_active_family_count"] or 0.0)
    return (
        abs(float(row["response_shape_follow_through_quality"] or 0.0))
        + float(row["response_shape_false_start_risk"] or 0.0)
        + abs(float(row["response_shape_recovery_vs_exhaustion"] or 0.0))
        + float(row["response_shape_volatility_damage_shape"] or 0.0)
    )


def main() -> None:
    args = parse_args()
    anomaly_df = load_anomaly_rows(Path(args.anomaly_csv))
    response_df = load_response_rows(Path(args.response_csv))
    rows = build_comparison_rows(anomaly_df, response_df)
    paths = compare_file_paths(COMPARE_ID)

    agreement_rows = [
        row
        for row in rows
        if row["agreement_class"] == "overlap_supportive"
    ]
    disagreement_rows = [
        row
        for row in rows
        if row["agreement_class"] in {"anomaly_only", "response_shape_only", "overlap_caution"}
    ]
    disagreement_rows = sorted(
        disagreement_rows,
        key=lambda row: (
            -disagreement_priority(row),
            row["date"],
            row["entity"],
        ),
    )

    comparison_payload = with_dev_flags(
        {
            "artifact_type": "dev_only_bot_compare_summary",
            "artifact_id": COMPARE_ID,
            "generated_at_utc": timestamp_utc(),
            "shared_key_rule": "exact date + entity alignment only",
            "input_refs": {
                "anomaly_ranking_heuristics_csv": str(Path(args.anomaly_csv)),
                "response_shape_features_csv": str(Path(args.response_csv)),
            },
            "counts": {
                "anomaly_row_count": int(len(anomaly_df)),
                "response_shape_row_count": int(len(response_df)),
                "comparison_row_count": int(len(rows)),
                "overlap_row_count": int(sum(row["agreement_class"].startswith("overlap_") for row in rows)),
                "agreement_row_count": int(len(agreement_rows)),
                "disagreement_row_count": int(len(disagreement_rows)),
                "anomaly_only_row_count": int(sum(row["agreement_class"] == "anomaly_only" for row in rows)),
                "response_shape_only_row_count": int(sum(row["agreement_class"] == "response_shape_only" for row in rows)),
            },
            "agreement_class_counts": {
                key: int(sum(row["agreement_class"] == key for row in rows))
                for key in sorted({row["agreement_class"] for row in rows})
            },
            "semantic_locks": [
                "no_strategy_score",
                "no_winner_language",
                "no_tradability_language",
                "no_leverage_guidance",
                "no_official_edge_claims",
            ],
            "status": "generated_dev_only_bot_compare",
        }
    )

    save_csv(paths["comparison_csv"], rows, CSV_COLUMNS)
    save_json(paths["comparison_json"], comparison_payload)
    save_json(
        paths["agreement_watchlist_json"],
        build_watchlist_payload(
            artifact_type="dev_only_bot_compare_agreement_watchlist",
            artifact_id="anomaly_vs_response_shape_agreement_watchlist",
            rows=agreement_rows[:20],
            note="No fuzzy joins. Rows appear here only when anomaly operating and response-shape share the exact same date+entity key and the aftermath profile is constructive.",
        ),
    )
    save_json(
        paths["disagreement_watchlist_json"],
        build_watchlist_payload(
            artifact_type="dev_only_bot_compare_disagreement_watchlist",
            artifact_id="anomaly_vs_response_shape_disagreement_watchlist",
            rows=disagreement_rows[:20],
            note="Rows appear here when the exact shared-key compare is missing on one side or when the overlap aftermath profile is cautionary.",
        ),
    )

    print(f"{COMPARE_ID} generated")
    print(paths["comparison_json"])
    print(paths["comparison_csv"])
    print(paths["agreement_watchlist_json"])
    print(paths["disagreement_watchlist_json"])


if __name__ == "__main__":
    main()
