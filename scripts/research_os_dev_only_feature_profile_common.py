from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from research_os_dev_only_feature_output_common import save_json, timestamp_utc, with_dev_flags


EPSILON = 1e-9


def load_feature_frame(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def count_nulls_by_column(df: pd.DataFrame) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for column in df.columns:
        series = df[column]
        null_count = int(series.isna().sum())
        if series.dtype == object:
            blanks = series.fillna("").astype(str).str.strip().eq("").sum()
            null_count = int(blanks)
        out[column] = null_count
    return out


def build_coverage(df: pd.DataFrame, coverage_column: str) -> Dict[str, Any]:
    coverage = df[coverage_column].fillna("").astype(str).str.strip()
    coverage = coverage[coverage != ""]
    counts = coverage.value_counts().sort_index()
    return {
        "coverage_column": coverage_column,
        "unique_count": int(coverage.nunique()),
        "values_sorted": sorted(counts.index.tolist()),
        "row_count_by_value": {key: int(value) for key, value in counts.to_dict().items()},
    }


def build_numeric_summary(df: pd.DataFrame, numeric_columns: List[str]) -> Dict[str, Dict[str, float | None]]:
    out: Dict[str, Dict[str, float | None]] = {}
    for column in numeric_columns:
        series = pd.to_numeric(df[column], errors="coerce")
        clean = series.dropna()
        if clean.empty:
            out[column] = {"min": None, "max": None, "mean": None}
            continue
        out[column] = {
            "min": round(float(clean.min()), 6),
            "max": round(float(clean.max()), 6),
            "mean": round(float(clean.mean()), 6),
        }
    return out


def compute_anomaly_scores(df: pd.DataFrame, numeric_columns: List[str]) -> pd.Series:
    score_parts: List[pd.Series] = []
    for column in numeric_columns:
        series = pd.to_numeric(df[column], errors="coerce")
        clean = series.dropna()
        if clean.empty:
            continue
        std = float(clean.std(ddof=0))
        if std <= EPSILON:
            normalized = pd.Series(0.0, index=df.index)
        else:
            mean = float(clean.mean())
            normalized = ((series - mean).abs() / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        score_parts.append(normalized)

    if not score_parts:
        return pd.Series(0.0, index=df.index, dtype=float)

    stacked = pd.concat(score_parts, axis=1)
    return stacked.mean(axis=1)


def build_top_abnormal_rows(
    df: pd.DataFrame,
    *,
    coverage_column: str,
    numeric_columns: List[str],
    top_n: int = 5,
    deprioritize_mask: pd.Series | None = None,
    extra_row_fields: List[str] | None = None,
) -> List[Dict[str, Any]]:
    scored = df.copy()
    scored["anomaly_score"] = compute_anomaly_scores(scored, numeric_columns)
    scored["__coverage_value"] = scored[coverage_column].fillna("").astype(str)
    scored["__date_sort"] = pd.to_datetime(scored["date"], errors="coerce")
    if deprioritize_mask is None:
        scored["__guardrail_deprioritized"] = False
    else:
        scored["__guardrail_deprioritized"] = deprioritize_mask.reindex(scored.index).fillna(False).astype(bool)
    scored = scored.sort_values(
        by=["__guardrail_deprioritized", "anomaly_score", "__date_sort", "__coverage_value"],
        ascending=[True, False, True, True],
        kind="mergesort",
    ).head(top_n)

    rows: List[Dict[str, Any]] = []
    row_fields = extra_row_fields or []
    for _, row in scored.iterrows():
        feature_values = {}
        for column in numeric_columns:
            value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
            feature_values[column] = None if pd.isna(value) else round(float(value), 6)
        date_value = row["date"]
        if pd.notna(date_value):
            date_text = pd.Timestamp(date_value).strftime("%Y-%m-%d")
        else:
            date_text = ""
        payload = {
            "date": date_text,
            coverage_column: str(row[coverage_column]),
            "anomaly_score": round(float(row["anomaly_score"]), 6),
            "feature_values": feature_values,
        }
        for field in row_fields:
            if field in row.index:
                payload[field] = row[field]
        rows.append(payload)
    return rows


def build_profile_payload(
    *,
    family_id: str,
    df: pd.DataFrame,
    coverage_column: str,
    numeric_columns: List[str],
    profile_guardrails: Dict[str, Any] | None = None,
    deprioritize_mask: pd.Series | None = None,
    extra_row_fields: List[str] | None = None,
    extra_sections: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    summary_df = df.drop(columns=extra_row_fields or [], errors="ignore")
    date_series = pd.to_datetime(summary_df["date"], errors="coerce")
    payload = {
        "artifact_type": "dev_only_feature_profile_report",
        "artifact_id": f"{family_id}_profile",
        "generated_at_utc": timestamp_utc(),
        "family_id": family_id,
        "row_count": int(len(summary_df)),
        "date_min": "" if date_series.dropna().empty else date_series.min().strftime("%Y-%m-%d"),
        "date_max": "" if date_series.dropna().empty else date_series.max().strftime("%Y-%m-%d"),
        "asset_or_leader_coverage": build_coverage(summary_df, coverage_column),
        "null_count_per_column": count_nulls_by_column(summary_df),
        "numeric_feature_summary": build_numeric_summary(summary_df, numeric_columns),
        "anomaly_score_definition": "mean absolute z-score across configured numeric feature columns",
        "top_abnormal_rows": build_top_abnormal_rows(
            df,
            coverage_column=coverage_column,
            numeric_columns=numeric_columns,
            deprioritize_mask=deprioritize_mask,
            extra_row_fields=extra_row_fields,
        ),
        "status": "generated_dev_only_feature_profile",
    }
    if profile_guardrails is not None:
        payload["profile_guardrails"] = profile_guardrails
    if extra_sections:
        payload.update(extra_sections)
    return with_dev_flags(payload)


def write_profile(path: Path, payload: Dict[str, Any]) -> None:
    save_json(path, payload)


def refresh_manifest_profile_path(manifest_path: Path, profile_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_files = manifest.setdefault("output_files", {})
    output_files["profile_json"] = str(profile_path)
    save_json(manifest_path, manifest)
