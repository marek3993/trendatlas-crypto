from __future__ import annotations

import csv
from itertools import combinations
from typing import Any, Dict, List

import pandas as pd

from research_os_dev_only_anomaly_operating_common import (
    FAMILY_IDS,
    INTERACTIONS_CSV_PATH,
    INTERACTIONS_JSON_PATH,
    build_cluster_note,
    build_guardrail_lookup,
    build_interesting_rows_only,
)
from research_os_dev_only_feature_output_common import ensure_parent, save_json, timestamp_utc, with_dev_flags


CSV_COLUMNS = [
    "family_pair",
    "family_a",
    "family_b",
    "overlap_row_count",
    "shared_entity_count",
    "date_min",
    "date_max",
    "mean_joint_interestingness",
    "top_entities",
    "interaction_note",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def build_pair_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for family_a, family_b in combinations(FAMILY_IDS, 2):
        left = frame[frame["family_id"] == family_a][["date", "entity", "family_anomaly_score"]].rename(
            columns={"family_anomaly_score": "score_a"}
        )
        right = frame[frame["family_id"] == family_b][["date", "entity", "family_anomaly_score"]].rename(
            columns={"family_anomaly_score": "score_b"}
        )
        overlap = left.merge(right, on=["date", "entity"], how="inner")
        overlap = overlap.sort_values(["date", "entity"], kind="mergesort")

        if overlap.empty:
            date_min = ""
            date_max = ""
            mean_joint_interestingness = 0.0
            top_entities: List[str] = []
            note = "no shared interesting rows"
        else:
            overlap["joint_interestingness"] = (overlap["score_a"] + overlap["score_b"]) / 2.0
            entity_counts = overlap["entity"].value_counts().sort_values(ascending=False)
            top_entities = entity_counts.head(3).index.tolist()
            date_min = overlap["date"].min().strftime("%Y-%m-%d")
            date_max = overlap["date"].max().strftime("%Y-%m-%d")
            mean_joint_interestingness = round(float(overlap["joint_interestingness"].mean()), 6)
            note = "repeated shared anomaly surfacing" if len(overlap) >= 3 else "light shared anomaly surfacing"

        row = with_dev_flags(
            {
                "family_pair": f"{family_a}__{family_b}",
                "family_a": family_a,
                "family_b": family_b,
                "overlap_row_count": int(len(overlap)),
                "shared_entity_count": int(overlap["entity"].nunique()) if not overlap.empty else 0,
                "date_min": date_min,
                "date_max": date_max,
                "mean_joint_interestingness": mean_joint_interestingness,
                "top_entities": top_entities,
                "interaction_note": note,
            }
        )
        rows.append(row)
    return rows


def build_top_clusters(frame: pd.DataFrame, guardrail_lookup: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    clusters: List[Dict[str, Any]] = []
    grouped = frame.groupby(["date", "entity"], sort=False)
    for (date, entity), group in grouped:
        active_families = sorted(group["family_id"].astype(str).tolist())
        if len(active_families) < 2:
            continue
        active_guardrails = sorted(
            f"{family_id}:{guardrail_name}"
            for family_id in active_families
            for guardrail_name in guardrail_lookup.get(family_id, [])
        )
        mean_score = float(group["family_anomaly_score"].mean())
        max_score = float(group["family_anomaly_score"].max())
        clusters.append(
            with_dev_flags(
                {
                    "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                    "entity": str(entity),
                    "active_family_count": int(len(active_families)),
                    "active_families": active_families,
                    "interaction_interestingness": round(float(len(active_families) + mean_score + 0.5 * max_score), 6),
                    "mean_active_score": round(mean_score, 6),
                    "max_active_score": round(max_score, 6),
                    "guardrail_context": active_guardrails,
                    "interaction_note": build_cluster_note(active_families),
                }
            )
        )

    clusters = sorted(
        clusters,
        key=lambda item: (
            -int(item["active_family_count"]),
            -float(item["interaction_interestingness"]),
            item["date"],
            item["entity"],
        ),
    )
    return clusters[:25]


def save_csv_rows(path, rows: List[Dict[str, Any]]) -> None:
    ensure_parent(path)
    serialized_rows = []
    for row in rows:
        serialized = dict(row)
        serialized["top_entities"] = "|".join(row["top_entities"])
        serialized_rows.append(serialized)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(serialized_rows)


def main() -> None:
    interesting_rows = build_interesting_rows_only()
    guardrail_lookup = build_guardrail_lookup()
    pair_rows = build_pair_rows(interesting_rows)
    top_clusters = build_top_clusters(interesting_rows, guardrail_lookup)
    payload = with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_cross_family_interactions",
            "artifact_id": "anomaly_cross_family_interactions",
            "generated_at_utc": timestamp_utc(),
            "family_count": len(FAMILY_IDS),
            "interesting_row_count": int(len(interesting_rows)),
            "pair_interactions": pair_rows,
            "top_interaction_clusters": top_clusters,
            "status": "generated_dev_only_cross_family_interactions",
        }
    )

    save_json(INTERACTIONS_JSON_PATH, payload)
    save_csv_rows(INTERACTIONS_CSV_PATH, pair_rows)

    print("dev-only anomaly cross-family interactions generated")
    print(INTERACTIONS_JSON_PATH)
    print(INTERACTIONS_CSV_PATH)


if __name__ == "__main__":
    main()
