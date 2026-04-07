from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path
from typing import Any, Dict, List

from research_os_dev_only_anomaly_operating_common import (
    FAMILY_SUMMARY_CSV_PATH,
    FAMILY_SUMMARY_JSON_PATH,
    HISTORY_ROOT,
    INTERACTIONS_CSV_PATH,
    INTERACTIONS_HISTORY_JSON_PATH,
    INTERACTIONS_JSON_PATH,
    INTERACTION_STABILITY_JSON_PATH,
    OPERATING_HISTORY_MANIFEST_JSON_PATH,
    RANKING_CSV_PATH,
    RANKING_HISTORY_JSON_PATH,
    RANKING_JSON_PATH,
    RANKING_STABILITY_JSON_PATH,
)
from research_os_dev_only_feature_output_common import ensure_parent, save_json, timestamp_utc, with_dev_flags


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist dev-only anomaly operating history and stability summaries")
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--cycle-generated-at-utc", required=True)
    return parser.parse_args()


def load_json_or_default(path: Path, default_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default_payload
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def load_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def split_pipe_values(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [part for part in text.split("|") if part]


def snapshot_dir(cycle_id: str) -> Path:
    return HISTORY_ROOT / cycle_id


def copy_snapshot_file(source: Path, destination: Path) -> None:
    ensure_parent(destination)
    shutil.copy2(source, destination)


def write_snapshot(cycle_id: str) -> Dict[str, str]:
    target_dir = snapshot_dir(cycle_id)
    snapshot_map = {
        "family_summary_json": target_dir / FAMILY_SUMMARY_JSON_PATH.name,
        "family_summary_csv": target_dir / FAMILY_SUMMARY_CSV_PATH.name,
        "cross_family_interactions_json": target_dir / INTERACTIONS_JSON_PATH.name,
        "cross_family_interactions_csv": target_dir / INTERACTIONS_CSV_PATH.name,
        "ranking_heuristics_json": target_dir / RANKING_JSON_PATH.name,
        "ranking_heuristics_csv": target_dir / RANKING_CSV_PATH.name,
    }
    source_map = {
        "family_summary_json": FAMILY_SUMMARY_JSON_PATH,
        "family_summary_csv": FAMILY_SUMMARY_CSV_PATH,
        "cross_family_interactions_json": INTERACTIONS_JSON_PATH,
        "cross_family_interactions_csv": INTERACTIONS_CSV_PATH,
        "ranking_heuristics_json": RANKING_JSON_PATH,
        "ranking_heuristics_csv": RANKING_CSV_PATH,
    }
    for key, source in source_map.items():
        copy_snapshot_file(source, snapshot_map[key])
    return {key: str(path) for key, path in snapshot_map.items()}


def upsert_cycle_record(records: List[Dict[str, Any]], cycle_record: Dict[str, Any]) -> List[Dict[str, Any]]:
    filtered = [record for record in records if str(record.get("cycle_id")) != str(cycle_record.get("cycle_id"))]
    filtered.append(cycle_record)
    return sorted(filtered, key=lambda item: str(item.get("cycle_id")))


def build_interaction_cycle_record(
    *,
    cycle_id: str,
    cycle_generated_at_utc: str,
    snapshot_refs: Dict[str, str],
) -> Dict[str, Any]:
    current_payload = load_json_or_default(INTERACTIONS_JSON_PATH, {})
    return with_dev_flags(
        {
            "cycle_id": cycle_id,
            "cycle_generated_at_utc": cycle_generated_at_utc,
            "interesting_row_count": as_int(current_payload.get("interesting_row_count")),
            "pair_interactions": current_payload.get("pair_interactions", []),
            "top_interaction_clusters": current_payload.get("top_interaction_clusters", []),
            "snapshot_refs": {
                "cross_family_interactions_json": snapshot_refs["cross_family_interactions_json"],
                "cross_family_interactions_csv": snapshot_refs["cross_family_interactions_csv"],
                "family_summary_json": snapshot_refs["family_summary_json"],
                "family_summary_csv": snapshot_refs["family_summary_csv"],
            },
        }
    )


def build_interaction_history(
    *,
    cycle_id: str,
    cycle_generated_at_utc: str,
    snapshot_refs: Dict[str, str],
) -> Dict[str, Any]:
    default_payload = with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_cross_family_interactions_history",
            "artifact_id": "anomaly_cross_family_interactions_history",
            "created_at_utc": cycle_generated_at_utc,
            "cycle_count": 0,
            "cycles": [],
            "status": "initialized",
        }
    )
    payload = load_json_or_default(INTERACTIONS_HISTORY_JSON_PATH, default_payload)
    cycle_record = build_interaction_cycle_record(
        cycle_id=cycle_id,
        cycle_generated_at_utc=cycle_generated_at_utc,
        snapshot_refs=snapshot_refs,
    )
    cycles = upsert_cycle_record(list(payload.get("cycles", [])), cycle_record)
    payload.update(
        with_dev_flags(
            {
                "artifact_type": "dev_only_anomaly_cross_family_interactions_history",
                "artifact_id": "anomaly_cross_family_interactions_history",
                "latest_cycle_id": cycle_id,
                "latest_cycle_generated_at_utc": cycle_generated_at_utc,
                "cycle_count": len(cycles),
                "cycles": cycles,
                "status": "updated_dev_only_interaction_history",
            }
        )
    )
    return payload


def build_interaction_stability(history_payload: Dict[str, Any]) -> Dict[str, Any]:
    cycles = list(history_payload.get("cycles", []))
    total_cycles = max(len(cycles), 1)

    pair_stats: Dict[str, Dict[str, Any]] = {}
    cluster_stats: Dict[str, Dict[str, Any]] = {}

    for cycle in cycles:
        cycle_id = str(cycle.get("cycle_id", ""))
        for row in cycle.get("pair_interactions", []):
            overlap_row_count = as_int(row.get("overlap_row_count"))
            if overlap_row_count <= 0:
                continue
            pair_key = str(row.get("family_pair", ""))
            stats = pair_stats.setdefault(
                pair_key,
                {
                    "family_pair": pair_key,
                    "family_a": str(row.get("family_a", "")),
                    "family_b": str(row.get("family_b", "")),
                    "cycles_seen": 0,
                    "first_seen_cycle_id": cycle_id,
                    "last_seen_cycle_id": cycle_id,
                    "overlap_counts": [],
                    "joint_scores": [],
                    "latest_top_entities": [],
                },
            )
            stats["cycles_seen"] += 1
            stats["last_seen_cycle_id"] = cycle_id
            stats["overlap_counts"].append(overlap_row_count)
            stats["joint_scores"].append(as_float(row.get("mean_joint_interestingness")))
            stats["latest_top_entities"] = list(row.get("top_entities", []))

        cycle_cluster_rows: Dict[str, Dict[str, Any]] = {}
        for row in cycle.get("top_interaction_clusters", []):
            active_families = list(row.get("active_families", []))
            cluster_key = f"{row.get('entity','')}||{'|'.join(active_families)}"
            cycle_cluster = cycle_cluster_rows.setdefault(
                cluster_key,
                {
                    "entity": str(row.get("entity", "")),
                    "active_families": active_families,
                    "dates_seen": set(),
                    "best_interestingness": 0.0,
                    "max_active_family_count": 0,
                },
            )
            cycle_cluster["dates_seen"].add(str(row.get("date", "")))
            cycle_cluster["best_interestingness"] = max(
                float(cycle_cluster["best_interestingness"]),
                as_float(row.get("interaction_interestingness")),
            )
            cycle_cluster["max_active_family_count"] = max(
                as_int(cycle_cluster["max_active_family_count"]),
                as_int(row.get("active_family_count")),
            )

        for cluster_key, cycle_cluster in cycle_cluster_rows.items():
            stats = cluster_stats.setdefault(
                cluster_key,
                {
                    "entity": cycle_cluster["entity"],
                    "active_families": cycle_cluster["active_families"],
                    "cycle_ids_seen": set(),
                    "first_seen_cycle_id": cycle_id,
                    "last_seen_cycle_id": cycle_id,
                    "dates_seen": set(),
                    "cycle_best_interestingness": [],
                    "max_active_family_count": 0,
                },
            )
            stats["cycle_ids_seen"].add(cycle_id)
            stats["last_seen_cycle_id"] = cycle_id
            stats["dates_seen"].update(cycle_cluster["dates_seen"])
            stats["cycle_best_interestingness"].append(cycle_cluster["best_interestingness"])
            stats["max_active_family_count"] = max(
                stats["max_active_family_count"],
                as_int(cycle_cluster["max_active_family_count"]),
            )

    stable_pairs = []
    for stats in pair_stats.values():
        cycles_seen = as_int(stats["cycles_seen"])
        stable_pairs.append(
            with_dev_flags(
                {
                    "family_pair": stats["family_pair"],
                    "family_a": stats["family_a"],
                    "family_b": stats["family_b"],
                    "cycles_seen": cycles_seen,
                    "persistence_ratio": round(float(cycles_seen / total_cycles), 6),
                    "first_seen_cycle_id": stats["first_seen_cycle_id"],
                    "last_seen_cycle_id": stats["last_seen_cycle_id"],
                    "mean_overlap_row_count": round(float(sum(stats["overlap_counts"]) / len(stats["overlap_counts"])), 6),
                    "max_overlap_row_count": max(stats["overlap_counts"]),
                    "mean_joint_interestingness": round(float(sum(stats["joint_scores"]) / len(stats["joint_scores"])), 6),
                    "latest_top_entities": stats["latest_top_entities"],
                    "stability_note": "recurred across recorded cycles" if cycles_seen > 1 else "single recorded cycle so far",
                }
            )
        )

    stable_clusters = []
    for stats in cluster_stats.values():
        cycles_seen = len(stats["cycle_ids_seen"])
        stable_clusters.append(
            with_dev_flags(
                {
                    "entity": stats["entity"],
                    "active_families": stats["active_families"],
                    "cycles_seen": cycles_seen,
                    "persistence_ratio": round(float(cycles_seen / total_cycles), 6),
                    "first_seen_cycle_id": stats["first_seen_cycle_id"],
                    "last_seen_cycle_id": stats["last_seen_cycle_id"],
                    "sample_dates": sorted(stats["dates_seen"])[:5],
                    "mean_interaction_interestingness": round(
                        float(sum(stats["cycle_best_interestingness"]) / len(stats["cycle_best_interestingness"])),
                        6,
                    ),
                    "max_active_family_count": stats["max_active_family_count"],
                    "stability_note": "recurred across recorded cycles" if cycles_seen > 1 else "single recorded cycle so far",
                }
            )
        )

    stable_pairs = sorted(
        stable_pairs,
        key=lambda item: (-as_int(item["cycles_seen"]), -as_float(item["mean_overlap_row_count"]), item["family_pair"]),
    )
    stable_clusters = sorted(
        stable_clusters,
        key=lambda item: (-as_int(item["cycles_seen"]), -as_float(item["mean_interaction_interestingness"]), item["entity"]),
    )

    return with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_cross_family_interaction_stability",
            "artifact_id": "anomaly_cross_family_interaction_stability",
            "generated_at_utc": timestamp_utc(),
            "history_cycle_count": len(cycles),
            "semantic_note": "recurrence here means repeated anomaly interaction surfacing only, not strategy value",
            "stable_pairs": stable_pairs[:25],
            "stable_clusters": stable_clusters[:25],
            "status": "generated_dev_only_interaction_stability",
        }
    )


def build_ranking_cycle_record(
    *,
    cycle_id: str,
    cycle_generated_at_utc: str,
    snapshot_refs: Dict[str, str],
) -> Dict[str, Any]:
    current_payload = load_json_or_default(RANKING_JSON_PATH, {})
    ranking_rows = []
    for row in load_csv_rows(RANKING_CSV_PATH):
        ranking_rows.append(
            with_dev_flags(
                {
                    "rank": as_int(row.get("rank")),
                    "date": str(row.get("date", "")),
                    "entity": str(row.get("entity", "")),
                    "active_family_count": as_int(row.get("active_family_count")),
                    "support_ratio": as_float(row.get("support_ratio")),
                    "mean_active_anomaly_score": as_float(row.get("mean_active_anomaly_score")),
                    "max_active_anomaly_score": as_float(row.get("max_active_anomaly_score")),
                    "interestingness_score": as_float(row.get("interestingness_score")),
                    "interestingness_band": str(row.get("interestingness_band", "")),
                    "active_families": split_pipe_values(row.get("active_families")),
                    "guardrail_context": split_pipe_values(row.get("guardrail_context")),
                    "cluster_note": str(row.get("cluster_note", "")),
                }
            )
        )

    return with_dev_flags(
        {
            "cycle_id": cycle_id,
            "cycle_generated_at_utc": cycle_generated_at_utc,
            "ranked_row_count": as_int(current_payload.get("ranked_row_count")),
            "interestingness_band_counts": current_payload.get("interestingness_band_counts", {}),
            "ranked_rows": ranking_rows,
            "snapshot_refs": {
                "ranking_heuristics_json": snapshot_refs["ranking_heuristics_json"],
                "ranking_heuristics_csv": snapshot_refs["ranking_heuristics_csv"],
                "family_summary_json": snapshot_refs["family_summary_json"],
                "family_summary_csv": snapshot_refs["family_summary_csv"],
            },
        }
    )


def build_ranking_history(
    *,
    cycle_id: str,
    cycle_generated_at_utc: str,
    snapshot_refs: Dict[str, str],
) -> Dict[str, Any]:
    default_payload = with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_ranking_history",
            "artifact_id": "anomaly_ranking_history",
            "created_at_utc": cycle_generated_at_utc,
            "cycle_count": 0,
            "cycles": [],
            "status": "initialized",
        }
    )
    payload = load_json_or_default(RANKING_HISTORY_JSON_PATH, default_payload)
    cycle_record = build_ranking_cycle_record(
        cycle_id=cycle_id,
        cycle_generated_at_utc=cycle_generated_at_utc,
        snapshot_refs=snapshot_refs,
    )
    cycles = upsert_cycle_record(list(payload.get("cycles", [])), cycle_record)
    payload.update(
        with_dev_flags(
            {
                "artifact_type": "dev_only_anomaly_ranking_history",
                "artifact_id": "anomaly_ranking_history",
                "latest_cycle_id": cycle_id,
                "latest_cycle_generated_at_utc": cycle_generated_at_utc,
                "cycle_count": len(cycles),
                "cycles": cycles,
                "status": "updated_dev_only_ranking_history",
            }
        )
    )
    return payload


def build_ranking_stability(history_payload: Dict[str, Any]) -> Dict[str, Any]:
    cycles = list(history_payload.get("cycles", []))
    total_cycles = max(len(cycles), 1)
    entity_stats: Dict[str, Dict[str, Any]] = {}
    exact_row_stats: Dict[str, Dict[str, Any]] = {}

    for cycle in cycles:
        cycle_id = str(cycle.get("cycle_id", ""))
        cycle_entity_rows: Dict[str, Dict[str, Any]] = {}
        for row in cycle.get("ranked_rows", []):
            entity = str(row.get("entity", ""))
            cycle_entity = cycle_entity_rows.setdefault(
                entity,
                {
                    "bands": [],
                    "best_rank": None,
                    "max_support_ratio": 0.0,
                },
            )
            current_rank = as_int(row.get("rank"))
            cycle_entity["bands"].append(str(row.get("interestingness_band", "")))
            cycle_entity["best_rank"] = (
                current_rank
                if cycle_entity["best_rank"] is None
                else min(as_int(cycle_entity["best_rank"]), current_rank)
            )
            cycle_entity["max_support_ratio"] = max(
                as_float(cycle_entity["max_support_ratio"]),
                as_float(row.get("support_ratio")),
            )

            exact_key = f"{row.get('date','')}||{entity}"
            exact_stat = exact_row_stats.setdefault(
                exact_key,
                {
                    "date": str(row.get("date", "")),
                    "entity": entity,
                    "cycles_seen": set(),
                    "ranks": [],
                    "bands": [],
                    "first_seen_cycle_id": cycle_id,
                    "last_seen_cycle_id": cycle_id,
                },
            )
            exact_stat["cycles_seen"].add(cycle_id)
            exact_stat["last_seen_cycle_id"] = cycle_id
            exact_stat["ranks"].append(current_rank)
            exact_stat["bands"].append(str(row.get("interestingness_band", "")))

        for entity, cycle_entity in cycle_entity_rows.items():
            bands = [band for band in cycle_entity["bands"] if band]
            dominant_band = sorted(
                {band: bands.count(band) for band in set(bands)}.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
            entity_stat = entity_stats.setdefault(
                entity,
                {
                    "entity": entity,
                    "cycles_seen": set(),
                    "best_ranks": [],
                    "bands": [],
                    "support_ratios": [],
                    "first_seen_cycle_id": cycle_id,
                    "last_seen_cycle_id": cycle_id,
                },
            )
            entity_stat["cycles_seen"].add(cycle_id)
            entity_stat["last_seen_cycle_id"] = cycle_id
            entity_stat["best_ranks"].append(as_int(cycle_entity["best_rank"]))
            entity_stat["bands"].append(dominant_band)
            entity_stat["support_ratios"].append(as_float(cycle_entity["max_support_ratio"]))

    stable_entities = []
    for stats in entity_stats.values():
        bands = [band for band in stats["bands"] if band]
        dominant_band = sorted({band: bands.count(band) for band in set(bands)}.items(), key=lambda item: (-item[1], item[0]))[0][0]
        cycles_seen = len(stats["cycles_seen"])
        stable_entities.append(
            with_dev_flags(
                {
                    "entity": stats["entity"],
                    "cycles_seen": cycles_seen,
                    "persistence_ratio": round(float(cycles_seen / total_cycles), 6),
                    "first_seen_cycle_id": stats["first_seen_cycle_id"],
                    "last_seen_cycle_id": stats["last_seen_cycle_id"],
                    "best_rank": min(stats["best_ranks"]),
                    "mean_rank": round(float(sum(stats["best_ranks"]) / len(stats["best_ranks"])), 6),
                    "dominant_band": dominant_band,
                    "max_support_ratio": round(float(max(stats["support_ratios"])), 6),
                    "stability_note": "recurred across recorded cycles" if cycles_seen > 1 else "single recorded cycle so far",
                }
            )
        )

    stable_rows = []
    for stats in exact_row_stats.values():
        cycles_seen = len(stats["cycles_seen"])
        stable_rows.append(
            with_dev_flags(
                {
                    "date": stats["date"],
                    "entity": stats["entity"],
                    "cycles_seen": cycles_seen,
                    "persistence_ratio": round(float(cycles_seen / total_cycles), 6),
                    "first_seen_cycle_id": stats["first_seen_cycle_id"],
                    "last_seen_cycle_id": stats["last_seen_cycle_id"],
                    "best_rank": min(stats["ranks"]),
                    "mean_rank": round(float(sum(stats["ranks"]) / len(stats["ranks"])), 6),
                    "latest_band": stats["bands"][-1] if stats["bands"] else "",
                    "stability_note": "recurred across recorded cycles" if cycles_seen > 1 else "single recorded cycle so far",
                }
            )
        )

    stable_entities = sorted(
        stable_entities,
        key=lambda item: (-as_int(item["cycles_seen"]), as_float(item["mean_rank"]), item["entity"]),
    )
    stable_rows = sorted(
        stable_rows,
        key=lambda item: (-as_int(item["cycles_seen"]), as_float(item["mean_rank"]), item["date"], item["entity"]),
    )

    return with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_ranking_stability",
            "artifact_id": "anomaly_ranking_stability",
            "generated_at_utc": timestamp_utc(),
            "history_cycle_count": len(cycles),
            "semantic_note": "persistence and recurrence here mean repeated anomaly interestingness only, not strategy value or candidate quality",
            "stable_entities": stable_entities[:25],
            "stable_ranked_rows": stable_rows[:25],
            "status": "generated_dev_only_ranking_stability",
        }
    )


def build_history_manifest(
    *,
    cycle_id: str,
    cycle_generated_at_utc: str,
    snapshot_refs: Dict[str, str],
    interaction_history: Dict[str, Any],
    ranking_history: Dict[str, Any],
) -> Dict[str, Any]:
    return with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_operating_history_manifest",
            "artifact_id": "anomaly_operating_history_manifest",
            "generated_at_utc": timestamp_utc(),
            "latest_cycle_id": cycle_id,
            "latest_cycle_generated_at_utc": cycle_generated_at_utc,
            "history_cycle_count": max(as_int(interaction_history.get("cycle_count")), as_int(ranking_history.get("cycle_count"))),
            "history_root": str(HISTORY_ROOT),
            "latest_snapshot_dir": str(snapshot_dir(cycle_id)),
            "latest_snapshot_refs": snapshot_refs,
            "output_refs": {
                "anomaly_cross_family_interactions_history_json": str(INTERACTIONS_HISTORY_JSON_PATH),
                "anomaly_cross_family_interaction_stability_json": str(INTERACTION_STABILITY_JSON_PATH),
                "anomaly_ranking_history_json": str(RANKING_HISTORY_JSON_PATH),
                "anomaly_ranking_stability_json": str(RANKING_STABILITY_JSON_PATH),
                "anomaly_operating_history_manifest_json": str(OPERATING_HISTORY_MANIFEST_JSON_PATH),
            },
            "status": "updated_dev_only_operating_history_manifest",
        }
    )


def main() -> None:
    args = parse_args()
    snapshot_refs = write_snapshot(args.cycle_id)
    interaction_history = build_interaction_history(
        cycle_id=args.cycle_id,
        cycle_generated_at_utc=args.cycle_generated_at_utc,
        snapshot_refs=snapshot_refs,
    )
    ranking_history = build_ranking_history(
        cycle_id=args.cycle_id,
        cycle_generated_at_utc=args.cycle_generated_at_utc,
        snapshot_refs=snapshot_refs,
    )
    interaction_stability = build_interaction_stability(interaction_history)
    ranking_stability = build_ranking_stability(ranking_history)
    history_manifest = build_history_manifest(
        cycle_id=args.cycle_id,
        cycle_generated_at_utc=args.cycle_generated_at_utc,
        snapshot_refs=snapshot_refs,
        interaction_history=interaction_history,
        ranking_history=ranking_history,
    )

    save_json(INTERACTIONS_HISTORY_JSON_PATH, interaction_history)
    save_json(INTERACTION_STABILITY_JSON_PATH, interaction_stability)
    save_json(RANKING_HISTORY_JSON_PATH, ranking_history)
    save_json(RANKING_STABILITY_JSON_PATH, ranking_stability)
    save_json(OPERATING_HISTORY_MANIFEST_JSON_PATH, history_manifest)

    print("dev-only anomaly history and stability artifacts updated")
    print(INTERACTIONS_HISTORY_JSON_PATH)
    print(INTERACTION_STABILITY_JSON_PATH)
    print(RANKING_HISTORY_JSON_PATH)
    print(RANKING_STABILITY_JSON_PATH)
    print(OPERATING_HISTORY_MANIFEST_JSON_PATH)


if __name__ == "__main__":
    main()
