from __future__ import annotations

import csv
from typing import Any, Dict, List

import pandas as pd

from research_os_dev_only_anomaly_operating_common import (
    FAMILY_IDS,
    RANKING_CSV_PATH,
    RANKING_JSON_PATH,
    build_cluster_note,
    build_guardrail_lookup,
    build_interesting_rows_only,
)
from research_os_dev_only_feature_output_common import ensure_parent, save_json, timestamp_utc, with_dev_flags


CSV_COLUMNS = [
    "rank",
    "date",
    "entity",
    "active_family_count",
    "support_ratio",
    "mean_active_anomaly_score",
    "max_active_anomaly_score",
    "interestingness_score",
    "interestingness_band",
    "active_families",
    "guardrail_context",
    "cluster_note",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def interestingness_band(active_family_count: int) -> str:
    if active_family_count >= 4:
        return "broad-cluster"
    if active_family_count == 3:
        return "multi-family"
    if active_family_count == 2:
        return "paired"
    return "single-family"


def build_ranked_rows(frame: pd.DataFrame, guardrail_lookup: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    grouped = frame.groupby(["date", "entity"], sort=False)
    for (date, entity), group in grouped:
        active_families = sorted(group["family_id"].astype(str).tolist())
        if not active_families:
            continue
        active_guardrails = sorted(
            f"{family_id}:{guardrail_name}"
            for family_id in active_families
            for guardrail_name in guardrail_lookup.get(family_id, [])
        )
        active_family_count = int(len(active_families))
        mean_score = float(group["family_anomaly_score"].mean())
        max_score = float(group["family_anomaly_score"].max())
        interestingness = round(float(active_family_count * 1.25 + mean_score + 0.5 * max_score), 6)
        rows.append(
            with_dev_flags(
                {
                    "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                    "entity": str(entity),
                    "active_family_count": active_family_count,
                    "support_ratio": round(float(active_family_count / len(FAMILY_IDS)), 6),
                    "mean_active_anomaly_score": round(mean_score, 6),
                    "max_active_anomaly_score": round(max_score, 6),
                    "interestingness_score": interestingness,
                    "interestingness_band": interestingness_band(active_family_count),
                    "active_families": active_families,
                    "guardrail_context": active_guardrails,
                    "cluster_note": build_cluster_note(active_families),
                }
            )
        )

    rows = sorted(
        rows,
        key=lambda item: (
            -float(item["interestingness_score"]),
            -int(item["active_family_count"]),
            item["date"],
            item["entity"],
        ),
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def build_band_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        band = str(row["interestingness_band"])
        counts[band] = counts.get(band, 0) + 1
    return counts


def save_csv_rows(path, rows: List[Dict[str, Any]]) -> None:
    ensure_parent(path)
    serialized_rows = []
    for row in rows:
        serialized = dict(row)
        serialized["active_families"] = "|".join(row["active_families"])
        serialized["guardrail_context"] = "|".join(row["guardrail_context"])
        serialized_rows.append(serialized)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(serialized_rows)


def main() -> None:
    interesting_rows = build_interesting_rows_only()
    guardrail_lookup = build_guardrail_lookup()
    ranked_rows = build_ranked_rows(interesting_rows, guardrail_lookup)
    payload = with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_ranking_heuristics",
            "artifact_id": "anomaly_ranking_heuristics",
            "generated_at_utc": timestamp_utc(),
            "semantic_note": "interestingness only, not strategy score, not tradability, not leverage guidance",
            "heuristic_definition": "interestingness_score = active_family_count * 1.25 + mean_active_anomaly_score + 0.5 * max_active_anomaly_score",
            "ranked_row_count": len(ranked_rows),
            "interestingness_band_counts": build_band_counts(ranked_rows),
            "top_ranked_rows": ranked_rows[:50],
            "status": "generated_dev_only_ranking_heuristics",
        }
    )

    save_json(RANKING_JSON_PATH, payload)
    save_csv_rows(RANKING_CSV_PATH, ranked_rows)

    print("dev-only anomaly ranking heuristics generated")
    print(RANKING_JSON_PATH)
    print(RANKING_CSV_PATH)


if __name__ == "__main__":
    main()
