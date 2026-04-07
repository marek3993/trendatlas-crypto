from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from research_os_dev_only_feature_output_common import OUTPUT_ROOT, ensure_parent, timestamp_utc, with_dev_flags


FAMILY_IDS = [
    "pre_move_structure_quality_stack",
    "participation_breadth_confirmation_stack",
    "cross_asset_decoupling_stack",
    "liquidity_stress_anomaly_stack",
    "event_context_flags_stack",
]

SUMMARY_JSON_PATH = OUTPUT_ROOT / "anomaly_feature_family_summary.json"
SUMMARY_CSV_PATH = OUTPUT_ROOT / "anomaly_feature_family_summary.csv"
SUMMARY_CSV_COLUMNS = [
    "family_id",
    "row_count",
    "date_min",
    "date_max",
    "coverage_count",
    "coverage_values",
    "null_free_status",
    "quality_status",
    "top_anomaly_concentration_summary",
    "major_guardrails_triggered",
    "readiness_note",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]


def family_paths(family_id: str) -> Dict[str, Path]:
    base = OUTPUT_ROOT / family_id
    return {
        "profile_json": Path(str(base) + ".profile.json"),
        "quality_json": Path(str(base) + ".quality.json"),
    }


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_top_anomaly_concentration_summary(profile: Dict[str, Any]) -> str:
    coverage = profile.get("asset_or_leader_coverage", {})
    coverage_column = str(coverage.get("coverage_column", "coverage"))
    top_rows = profile.get("top_abnormal_rows", [])
    if not top_rows:
        return "no abnormal rows present"

    counts: Dict[str, int] = {}
    for row in top_rows:
        value = str(row.get(coverage_column, "")).strip()
        if value:
            counts[value] = counts.get(value, 0) + 1

    if not counts:
        return "top abnormal rows lack coverage labels"

    winner_value, winner_count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return f"{winner_value} appears in {winner_count}/{len(top_rows)} top abnormal rows"


def build_guardrail_summary(profile: Dict[str, Any]) -> str:
    guardrails = profile.get("profile_guardrails", {})
    triggered = sorted(
        name
        for name, payload in guardrails.items()
        if isinstance(payload, dict) and str(payload.get("status", "")).strip().lower() == "guardrail_triggered"
    )
    if not triggered:
        return "none"
    return "; ".join(triggered)


def build_readiness_note(*, quality_status: str, null_free_status: bool, guardrail_summary: str) -> str:
    if quality_status != "passed":
        return "quality checks need attention before inspection use"
    if not null_free_status:
        return "shape is usable but null cleanup is still needed"
    if guardrail_summary != "none":
        return "inspection-ready with guardrail review recommended"
    return "inspection-ready with no active guardrail warnings"


def build_family_row(family_id: str) -> Dict[str, Any]:
    paths = family_paths(family_id)
    profile = load_json(paths["profile_json"])
    quality = load_json(paths["quality_json"])

    coverage = profile.get("asset_or_leader_coverage", {})
    coverage_values = list(coverage.get("values_sorted", []))
    null_count_per_column = profile.get("null_count_per_column", {})
    null_free_status = all(int(value) == 0 for value in null_count_per_column.values())
    quality_status = str(quality.get("status", "unknown"))
    guardrail_summary = build_guardrail_summary(profile)

    row = {
        "family_id": family_id,
        "row_count": int(profile.get("row_count", 0)),
        "date_min": str(profile.get("date_min", "")),
        "date_max": str(profile.get("date_max", "")),
        "coverage_count": int(coverage.get("unique_count", 0)),
        "coverage_values": coverage_values,
        "null_free_status": null_free_status,
        "quality_status": quality_status,
        "top_anomaly_concentration_summary": build_top_anomaly_concentration_summary(profile),
        "major_guardrails_triggered": guardrail_summary,
        "readiness_note": build_readiness_note(
            quality_status=quality_status,
            null_free_status=null_free_status,
            guardrail_summary=guardrail_summary,
        ),
    }
    return with_dev_flags(row)


def save_summary_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    ensure_parent(path)
    serializable_rows = []
    for row in rows:
        serializable = dict(row)
        serializable["coverage_values"] = "|".join(row["coverage_values"])
        serializable_rows.append(serializable)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(serializable_rows)


def main() -> None:
    rows = [build_family_row(family_id) for family_id in FAMILY_IDS]
    summary_payload = with_dev_flags(
        {
            "artifact_type": "dev_only_anomaly_feature_family_summary",
            "artifact_id": "anomaly_feature_family_summary",
            "generated_at_utc": timestamp_utc(),
            "family_count": len(rows),
            "families": rows,
            "status": "generated_dev_only_unified_summary",
        }
    )

    ensure_parent(SUMMARY_JSON_PATH)
    SUMMARY_JSON_PATH.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    save_summary_csv(SUMMARY_CSV_PATH, rows)

    print("dev-only anomaly feature family summary generated")
    print(SUMMARY_JSON_PATH)
    print(SUMMARY_CSV_PATH)


if __name__ == "__main__":
    main()
