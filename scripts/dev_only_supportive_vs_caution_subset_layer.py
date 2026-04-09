from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from research_os_dev_only_bot_compare_common import MANDATORY_DEV_FLAGS, save_csv, save_json, timestamp_utc


ROOT = Path(__file__).resolve().parents[1]
INPUT_COMPARE_CSV_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_bot_compare"
    / "anomaly_vs_response_shape_aligned_comparison.csv"
)
INPUT_COMPARE_JSON_PATH = (
    ROOT
    / "outputs"
    / "research_os"
    / "dev_only"
    / "non_authoritative_bot_compare"
    / "anomaly_vs_response_shape_aligned_comparison.json"
)
OUTPUT_ROOT = ROOT / "outputs" / "research_os" / "dev_only" / "non_authoritative_subset_layer"

ARTIFACT_ID = "supportive_vs_caution_subset_layer_v1"
SOURCE_COMPARE_ID = "anomaly_vs_response_shape_aligned_comparison"
REQUIRED_INPUT_COLUMNS = [
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
]
ROWS_CSV_COLUMNS = [
    "date",
    "entity",
    "subset_class",
    "anomaly_interestingness_score",
    "anomaly_active_family_count",
    "anomaly_cluster_note",
    "response_shape_follow_through_quality",
    "response_shape_false_start_risk",
    "response_shape_volatility_damage_shape",
    "response_shape_recovery_vs_exhaustion",
    "response_shape_context",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
]
ALLOWED_AGREEMENT_CLASSES = {
    "overlap_supportive",
    "overlap_caution",
    "overlap_mixed",
}
MANDATORY_JSON_LOCKS = {
    "analysis_mode": "descriptive_subset_only",
    "candidate_selection": False,
    "official_edge_claim": False,
    "fuzzy_matching_used": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build supportive vs caution subset layer from aligned compare outputs")
    parser.add_argument("--input-csv", type=str, default=str(INPUT_COMPARE_CSV_PATH))
    parser.add_argument("--input-json", type=str, default=str(INPUT_COMPARE_JSON_PATH))
    return parser.parse_args()


def with_json_locks(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    out.update(MANDATORY_JSON_LOCKS)
    return out


def output_paths() -> Dict[str, Path]:
    return {
        "summary_json": OUTPUT_ROOT / f"{ARTIFACT_ID}.summary.json",
        "rows_csv": OUTPUT_ROOT / f"{ARTIFACT_ID}.rows.csv",
        "supportive_watchlist_json": OUTPUT_ROOT / "supportive_subset_watchlist.json",
        "caution_watchlist_json": OUTPUT_ROOT / "caution_subset_watchlist.json",
        "supportive_concentration_json": OUTPUT_ROOT / "supportive_subset_concentration_summary.json",
        "caution_concentration_json": OUTPUT_ROOT / "caution_subset_concentration_summary.json",
        "supportive_persistence_json": OUTPUT_ROOT / "supportive_subset_persistence_summary.json",
        "caution_persistence_json": OUTPUT_ROOT / "caution_subset_persistence_summary.json",
        "manifest_json": OUTPUT_ROOT / f"{ARTIFACT_ID}.manifest.json",
        "quality_json": OUTPUT_ROOT / f"{ARTIFACT_ID}.quality.json",
    }


def load_compare_rows(csv_path: Path, json_path: Path) -> tuple[pd.DataFrame, str, str]:
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        return normalize_compare_frame(df), "csv", csv_path.stem

    if not json_path.exists():
        raise FileNotFoundError(f"Missing aligned compare input: {csv_path} or {json_path}")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] | None = None
    for key in ["comparison_rows", "rows", "watchlist_rows"]:
        value = payload.get(key)
        if isinstance(value, list):
            rows = value
            break
    if rows is None:
        raise ValueError(
            f"{json_path.name}: fallback json does not contain row data under comparison_rows, rows, or watchlist_rows"
        )
    source_compare_id = str(payload.get("artifact_id") or json_path.stem)
    return normalize_compare_frame(pd.DataFrame(rows)), "json", source_compare_id


def normalize_compare_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(column).strip() for column in out.columns]
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    if "entity" in out.columns:
        out["entity"] = out["entity"].fillna("").astype(str).str.strip().str.upper()
    if "agreement_class" in out.columns:
        out["agreement_class"] = out["agreement_class"].fillna("").astype(str).str.strip()

    numeric_columns = [
        "anomaly_interestingness_score",
        "anomaly_active_family_count",
        "response_shape_follow_through_quality",
        "response_shape_false_start_risk",
        "response_shape_volatility_damage_shape",
        "response_shape_recovery_vs_exhaustion",
    ]
    for column in numeric_columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    for column in ["anomaly_cluster_note", "response_shape_context"]:
        if column in out.columns:
            out[column] = out[column].fillna("").astype(str).str.strip()

    out = out.dropna(subset=["date"])
    out["date"] = out["date"].dt.normalize()
    return out


def clean_text_value(value: object) -> str:
    text = str(value or "").strip()
    return text if text else "unlabeled"


def clean_int_value(value: object) -> int | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return int(numeric)


def build_rows_frame(compare_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    filtered = compare_df[compare_df["agreement_class"].isin(ALLOWED_AGREEMENT_CLASSES)].copy()
    supportive_df = filtered[filtered["agreement_class"].eq("overlap_supportive")].copy()
    caution_df = filtered[filtered["agreement_class"].eq("overlap_caution")].copy()

    subset_df = pd.concat([supportive_df, caution_df], ignore_index=True)
    subset_df["subset_class"] = subset_df["agreement_class"]
    subset_df["date"] = pd.to_datetime(subset_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    subset_df["anomaly_active_family_count"] = subset_df["anomaly_active_family_count"].map(clean_int_value)

    for column in [
        "anomaly_interestingness_score",
        "response_shape_follow_through_quality",
        "response_shape_false_start_risk",
        "response_shape_volatility_damage_shape",
        "response_shape_recovery_vs_exhaustion",
    ]:
        subset_df[column] = pd.to_numeric(subset_df[column], errors="coerce").round(6)

    for column in ["entity", "anomaly_cluster_note", "response_shape_context"]:
        subset_df[column] = subset_df[column].map(clean_text_value)

    for key, value in MANDATORY_DEV_FLAGS.items():
        subset_df[key] = value

    subset_df = subset_df[ROWS_CSV_COLUMNS].sort_values(
        by=["subset_class", "date", "entity"],
        ascending=[True, True, True],
        kind="mergesort",
    )
    return filtered, supportive_df, caution_df, subset_df


def build_top_counts(df: pd.DataFrame, column: str, *, top_n: int = 10) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    values = df[column].map(clean_text_value)
    counts = values.value_counts(dropna=False)
    total = int(counts.sum())
    rows: List[Dict[str, Any]] = []
    for value, count in counts.head(top_n).items():
        rows.append(
            {
                "value": str(value),
                "count": int(count),
                "share": round(float(count) / float(total), 6) if total else 0.0,
            }
        )
    return rows


def build_month_counts(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    date_series = pd.to_datetime(df["date"], errors="coerce")
    month_bucket = date_series.dt.strftime("%Y-%m")
    counts = month_bucket.value_counts().sort_index()
    total = int(counts.sum())
    rows: List[Dict[str, Any]] = []
    for value, count in counts.items():
        rows.append(
            {
                "month_bucket": str(value),
                "count": int(count),
                "share": round(float(count) / float(total), 6) if total else 0.0,
            }
        )
    return rows


def build_concentration_summary(subset_df: pd.DataFrame, *, subset_name: str) -> Dict[str, Any]:
    work = subset_df.copy()
    if "anomaly_active_family_count" in work.columns:
        work["anomaly_active_family_count_label"] = (
            work["anomaly_active_family_count"]
            .map(lambda value: "unlabeled" if pd.isna(value) else str(int(value)))
        )

    return with_json_locks(
        {
            "artifact_id": f"{subset_name}_concentration_summary",
            "generated_at_utc": timestamp_utc(),
            "subset_class": subset_name,
            "row_count": int(len(subset_df)),
            "concentration_dimensions": [
                "entity",
                "anomaly_cluster_note",
                "anomaly_active_family_count",
                "response_shape_context",
                "month_bucket",
            ],
            "top_counts_by_entity": build_top_counts(work, "entity"),
            "top_counts_by_anomaly_cluster_note": build_top_counts(work, "anomaly_cluster_note"),
            "top_counts_by_anomaly_active_family_count": build_top_counts(work, "anomaly_active_family_count_label"),
            "top_counts_by_response_shape_context": build_top_counts(work, "response_shape_context"),
            "month_bucket_counts": build_month_counts(work),
            "shared_key_rule": "exact date + entity only",
            "status": "generated_dev_only_subset_concentration_summary",
        }
    )


def compute_streaks(date_series: pd.Series) -> Dict[str, int]:
    dates = sorted(set(pd.to_datetime(date_series, errors="coerce").dropna().tolist()))
    if not dates:
        return {
            "max_exact_daily_streak_observations": 0,
            "max_near_consecutive_3d_streak_observations": 0,
        }

    def max_streak(max_gap_days: int) -> int:
        best = 1
        current = 1
        for prev, curr in zip(dates, dates[1:]):
            gap_days = int((curr - prev).days)
            if gap_days <= max_gap_days:
                current += 1
            else:
                best = max(best, current)
                current = 1
        return max(best, current)

    return {
        "max_exact_daily_streak_observations": max_streak(1),
        "max_near_consecutive_3d_streak_observations": max_streak(3),
    }


def build_recurrence_rows(df: pd.DataFrame, column: str) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    work = df.copy()
    work[column] = work[column].map(clean_text_value)
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    rows: List[Dict[str, Any]] = []
    for value, group in work.groupby(column, dropna=False, sort=True):
        count = int(len(group))
        if count <= 1:
            continue
        streaks = compute_streaks(group["date"])
        rows.append(
            {
                "value": str(value),
                "count": count,
                "first_seen": group["date"].min().strftime("%Y-%m-%d"),
                "last_seen": group["date"].max().strftime("%Y-%m-%d"),
                **streaks,
            }
        )
    rows.sort(key=lambda item: (-item["count"], item["first_seen"], item["value"]))
    return rows


def build_persistence_summary(subset_df: pd.DataFrame, *, subset_name: str) -> Dict[str, Any]:
    entity_rows = build_recurrence_rows(subset_df, "entity")
    cluster_rows = build_recurrence_rows(subset_df, "anomaly_cluster_note")
    context_rows = build_recurrence_rows(subset_df, "response_shape_context")

    def max_recurrence(rows: List[Dict[str, Any]]) -> int:
        return max((int(row["count"]) for row in rows), default=0)

    return with_json_locks(
        {
            "artifact_id": f"{subset_name}_persistence_summary",
            "generated_at_utc": timestamp_utc(),
            "subset_class": subset_name,
            "row_count": int(len(subset_df)),
            "repeated_entity_count": int(len(entity_rows)),
            "repeated_cluster_count": int(len(cluster_rows)),
            "repeated_context_count": int(len(context_rows)),
            "max_entity_recurrence": max_recurrence(entity_rows),
            "max_cluster_recurrence": max_recurrence(cluster_rows),
            "max_context_recurrence": max_recurrence(context_rows),
            "recurrence_by_entity": entity_rows,
            "recurrence_by_anomaly_cluster_note": cluster_rows,
            "recurrence_by_response_shape_context": context_rows,
            "streak_definition": {
                "max_exact_daily_streak_observations": "Longest run where adjacent observations are exactly 1 calendar day apart.",
                "max_near_consecutive_3d_streak_observations": "Longest run where adjacent observations are at most 3 calendar days apart.",
            },
            "shared_key_rule": "exact date + entity only",
            "status": "generated_dev_only_subset_persistence_summary",
        }
    )


def build_watchlist_rows(subset_df: pd.DataFrame, *, subset_name: str) -> List[Dict[str, Any]]:
    work = subset_df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if subset_name == "supportive_subset":
        sort_by = [
            "response_shape_follow_through_quality",
            "response_shape_false_start_risk",
            "date",
            "entity",
        ]
        ascending = [False, True, True, True]
    else:
        sort_by = [
            "response_shape_false_start_risk",
            "response_shape_volatility_damage_shape",
            "date",
            "entity",
        ]
        ascending = [False, False, True, True]

    work = work.sort_values(by=sort_by, ascending=ascending, kind="mergesort").head(20)
    rows: List[Dict[str, Any]] = []
    for _, row in work.iterrows():
        payload = {
            "date": str(row["date"]),
            "entity": clean_text_value(row["entity"]),
            "subset_class": subset_name,
            "anomaly_interestingness_score": round(float(row["anomaly_interestingness_score"]), 6),
            "anomaly_active_family_count": clean_int_value(row["anomaly_active_family_count"]),
            "anomaly_cluster_note": clean_text_value(row["anomaly_cluster_note"]),
            "response_shape_follow_through_quality": round(float(row["response_shape_follow_through_quality"]), 6),
            "response_shape_false_start_risk": round(float(row["response_shape_false_start_risk"]), 6),
            "response_shape_volatility_damage_shape": round(float(row["response_shape_volatility_damage_shape"]), 6),
            "response_shape_recovery_vs_exhaustion": round(float(row["response_shape_recovery_vs_exhaustion"]), 6),
            "response_shape_context": clean_text_value(row["response_shape_context"]),
        }
        payload.update(MANDATORY_DEV_FLAGS)
        rows.append(payload)
    return rows


def build_watchlist_payload(
    *,
    artifact_id: str,
    subset_name: str,
    rows: List[Dict[str, Any]],
    sort_description: str,
) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": artifact_id,
            "generated_at_utc": timestamp_utc(),
            "subset_class": subset_name,
            "row_count": int(len(rows)),
            "max_rows": 20,
            "sort_rule": sort_description,
            "watchlist_rows": rows,
            "shared_key_rule": "exact date + entity only",
            "status": "generated_dev_only_subset_watchlist",
        }
    )


def build_summary_payload(
    *,
    filtered_df: pd.DataFrame,
    supportive_df: pd.DataFrame,
    caution_df: pd.DataFrame,
    mixed_df: pd.DataFrame,
    input_refs: Dict[str, str],
    source_compare_id: str,
) -> Dict[str, Any]:
    subset_df = pd.concat([supportive_df, caution_df], ignore_index=True)
    entity_recurrence = build_recurrence_rows(subset_df, "entity")
    cluster_recurrence = build_recurrence_rows(subset_df, "anomaly_cluster_note")
    context_recurrence = build_recurrence_rows(subset_df, "response_shape_context")

    return with_json_locks(
        {
            "artifact_id": ARTIFACT_ID,
            "generated_at_utc": timestamp_utc(),
            "source_compare_id": source_compare_id,
            "input_refs": input_refs,
            "row_counts": {
                "total_overlap_rows": int(len(filtered_df)),
                "supportive_rows": int(len(supportive_df)),
                "caution_rows": int(len(caution_df)),
                "mixed_rows": int(len(mixed_df)),
            },
            "concentration_dimensions": [
                "entity",
                "anomaly_cluster_note",
                "anomaly_active_family_count",
                "response_shape_context",
                "month_bucket",
            ],
            "persistence_dimensions": {
                "repeated_entity_count": int(len(entity_recurrence)),
                "repeated_cluster_count": int(len(cluster_recurrence)),
                "repeated_context_count": int(len(context_recurrence)),
                "max_entity_recurrence": max((row["count"] for row in entity_recurrence), default=0),
                "max_cluster_recurrence": max((row["count"] for row in cluster_recurrence), default=0),
                "max_context_recurrence": max((row["count"] for row in context_recurrence), default=0),
            },
            "exact_matching_metadata": {
                "fuzzy_matching_used": False,
                "shared_key_rule": "exact date + entity only",
            },
            "status": "generated_dev_only_subset_summary",
        }
    )


def build_manifest_payload(input_refs: Dict[str, str], paths: Dict[str, Path]) -> Dict[str, Any]:
    return with_json_locks(
        {
            "artifact_id": f"{ARTIFACT_ID}_manifest",
            "generated_at_utc": timestamp_utc(),
            "input_refs": input_refs,
            "output_namespace": str(OUTPUT_ROOT),
            "output_refs": {key: str(path) for key, path in paths.items()},
            "contract_refs": [
                "research_os/dev_only/contracts/supportive_vs_caution_subset_layer_v1.contract.json",
                "research_os/dev_only/contracts/anomaly_vs_response_shape_aligned_compare.contract.json",
            ],
            "spec_refs": [
                "research_os/dev_only/specs/dev_only_supportive_vs_caution_subset_layer.spec.json",
            ],
            "upstream_manifest_refs": [
                "research_os/dev_only/manifests/anomaly_vs_response_shape_aligned_compare.manifest.json",
            ],
            "shared_key_rule": "exact date + entity only",
            "status": "implementation_pack_ready",
        }
    )


def build_quality_payload(
    *,
    compare_df: pd.DataFrame,
    subset_rows_df: pd.DataFrame,
    supportive_watchlist_rows: List[Dict[str, Any]],
    caution_watchlist_rows: List[Dict[str, Any]],
    input_mode: str,
    source_compare_id: str,
) -> Dict[str, Any]:
    missing_columns = [column for column in REQUIRED_INPUT_COLUMNS if column not in compare_df.columns]
    duplicate_key_count = (
        int(
            compare_df.assign(date_str=pd.to_datetime(compare_df["date"], errors="coerce").dt.strftime("%Y-%m-%d"))
            .duplicated(subset=["date_str", "entity"])
            .sum()
        )
        if {"date", "entity"}.issubset(compare_df.columns)
        else 0
    )
    unexpected_classes = sorted(
        set(compare_df.get("agreement_class", pd.Series(dtype=object)).dropna()) - ALLOWED_AGREEMENT_CLASSES
    )
    subset_classes = sorted(set(subset_rows_df.get("subset_class", pd.Series(dtype=object)).dropna()))

    checks = [
        {
            "name": "required_input_columns_present",
            "ok": len(missing_columns) == 0,
            "detail": "all required input columns present" if not missing_columns else f"missing columns: {missing_columns}",
        },
        {
            "name": "exact_date_entity_duplicates_absent",
            "ok": duplicate_key_count == 0,
            "detail": "no duplicate date+entity keys" if duplicate_key_count == 0 else f"duplicate key rows: {duplicate_key_count}",
        },
        {
            "name": "agreement_classes_supported",
            "ok": len(unexpected_classes) == 0,
            "detail": "all agreement classes supported" if not unexpected_classes else f"unexpected classes: {unexpected_classes}",
        },
        {
            "name": "subset_rows_are_supportive_or_caution_only",
            "ok": subset_classes == ["overlap_caution", "overlap_supportive"] or subset_rows_df.empty,
            "detail": "subset rows exclude mixed rows"
            if subset_classes == ["overlap_caution", "overlap_supportive"] or subset_rows_df.empty
            else f"subset classes found: {subset_classes}",
        },
        {
            "name": "watchlists_capped_at_20_rows",
            "ok": len(supportive_watchlist_rows) <= 20 and len(caution_watchlist_rows) <= 20,
            "detail": "watchlist caps respected",
        },
        {
            "name": "fuzzy_matching_disabled",
            "ok": True,
            "detail": "fuzzy_matching_used=false",
        },
    ]

    return with_json_locks(
        {
            "artifact_id": f"{ARTIFACT_ID}_quality",
            "generated_at_utc": timestamp_utc(),
            "source_compare_id": source_compare_id,
            "input_mode": input_mode,
            "row_count": int(len(compare_df)),
            "subset_row_count": int(len(subset_rows_df)),
            "checks": checks,
            "status": "passed" if all(check["ok"] for check in checks) else "failed",
        }
    )


def main() -> None:
    args = parse_args()
    input_csv_path = Path(args.input_csv)
    input_json_path = Path(args.input_json)
    compare_df, input_mode, source_compare_id = load_compare_rows(input_csv_path, input_json_path)

    filtered_df, supportive_df, caution_df, subset_rows_df = build_rows_frame(compare_df)
    mixed_df = filtered_df[filtered_df["agreement_class"].eq("overlap_mixed")].copy()

    supportive_watchlist_rows = build_watchlist_rows(supportive_df, subset_name="supportive_subset")
    caution_watchlist_rows = build_watchlist_rows(caution_df, subset_name="caution_subset")

    paths = output_paths()
    input_refs = {
        "input_csv": str(input_csv_path),
        "input_json_fallback": str(input_json_path),
    }

    save_csv(paths["rows_csv"], subset_rows_df.to_dict("records"), ROWS_CSV_COLUMNS)
    save_json(
        paths["summary_json"],
        build_summary_payload(
            filtered_df=filtered_df,
            supportive_df=supportive_df,
            caution_df=caution_df,
            mixed_df=mixed_df,
            input_refs=input_refs,
            source_compare_id=source_compare_id,
        ),
    )
    save_json(
        paths["supportive_watchlist_json"],
        build_watchlist_payload(
            artifact_id="supportive_subset_watchlist",
            subset_name="supportive_subset",
            rows=supportive_watchlist_rows,
            sort_description="response_shape_follow_through_quality desc, response_shape_false_start_risk asc, date asc, entity asc",
        ),
    )
    save_json(
        paths["caution_watchlist_json"],
        build_watchlist_payload(
            artifact_id="caution_subset_watchlist",
            subset_name="caution_subset",
            rows=caution_watchlist_rows,
            sort_description="response_shape_false_start_risk desc, response_shape_volatility_damage_shape desc, date asc, entity asc",
        ),
    )
    save_json(
        paths["supportive_concentration_json"],
        build_concentration_summary(supportive_df, subset_name="supportive_subset"),
    )
    save_json(
        paths["caution_concentration_json"],
        build_concentration_summary(caution_df, subset_name="caution_subset"),
    )
    save_json(
        paths["supportive_persistence_json"],
        build_persistence_summary(supportive_df, subset_name="supportive_subset"),
    )
    save_json(
        paths["caution_persistence_json"],
        build_persistence_summary(caution_df, subset_name="caution_subset"),
    )
    save_json(paths["manifest_json"], build_manifest_payload(input_refs=input_refs, paths=paths))
    save_json(
        paths["quality_json"],
        build_quality_payload(
            compare_df=filtered_df,
            subset_rows_df=subset_rows_df,
            supportive_watchlist_rows=supportive_watchlist_rows,
            caution_watchlist_rows=caution_watchlist_rows,
            input_mode=input_mode,
            source_compare_id=source_compare_id,
        ),
    )

    print(f"{ARTIFACT_ID} generated")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()


# MRV1 AI LAB hard validation
def _assert_watchlist_subset_purity(rows, expected_subset, label):
    bad = [r for r in rows if str(r.get("subset_class", "")).strip().lower() != expected_subset]
    if bad:
        sample = bad[:3]
        raise ValueError(
            f"{label} contains {len(bad)} non-{expected_subset} rows; sample={sample}"
        )


