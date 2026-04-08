from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd


MANDATORY_DEV_FLAGS = {
    "dev_only": True,
    "non_authoritative": True,
    "official_truth": False,
    "strategy_advancement": False,
}

MANDATORY_SEMANTIC_FIELDS = {
    "analysis_mode": "descriptive_aftermath_only",
    "live_decision_ready": False,
}

OUTPUT_ROOT = Path(
    r"C:\Users\benda\Desktop\market_regime_v1\outputs\research_os\dev_only\non_authoritative_response_shape"
)
EPSILON = 1e-9


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def with_dev_flags(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    return out


def with_semantic_scope(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_SEMANTIC_FIELDS)
    return out


def response_shape_file_paths(bot_id: str) -> Dict[str, Path]:
    return {
        "features_csv": OUTPUT_ROOT / f"{bot_id}.features.csv",
        "manifest_json": OUTPUT_ROOT / f"{bot_id}.manifest.json",
        "quality_json": OUTPUT_ROOT / f"{bot_id}.quality.json",
        "profile_json": OUTPUT_ROOT / f"{bot_id}.profile.json",
    }


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_manifest(
    *,
    bot_id: str,
    input_refs: List[str],
    features_csv_path: Path,
    quality_json_path: Path,
    profile_json_path: Path | None,
    column_schema: List[str],
    row_count: int,
    lookahead_horizon_days: int,
    contract_refs: List[str],
    spec_refs: List[str],
    notes: List[str],
) -> Dict[str, Any]:
    output_files = {
        "features_csv": str(features_csv_path),
        "quality_json": str(quality_json_path),
    }
    if profile_json_path is not None:
        output_files["profile_json"] = str(profile_json_path)

    return with_dev_flags(
        with_semantic_scope(
            {
                "artifact_type": "dev_only_response_shape_output_manifest",
                "artifact_id": f"{bot_id}_manifest",
                "generated_at_utc": timestamp_utc(),
                "bot_id": bot_id,
                "output_namespace": str(OUTPUT_ROOT),
                "output_files": output_files,
                "input_refs": input_refs,
                "column_schema": column_schema,
                "row_count": row_count,
                "lookahead_horizon_days": lookahead_horizon_days,
                "contract_refs": contract_refs,
                "spec_refs": spec_refs,
                "notes": notes,
                "status": "generated_dev_only_response_shape_output",
            }
        )
    )


def build_quality_report(
    *,
    bot_id: str,
    row_count: int,
    required_columns: List[str],
    leakage_checks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return with_dev_flags(
        with_semantic_scope(
            {
                "artifact_type": "dev_only_response_shape_quality_report",
                "artifact_id": f"{bot_id}_quality",
                "generated_at_utc": timestamp_utc(),
                "bot_id": bot_id,
                "row_count": row_count,
                "required_columns": required_columns,
                "leakage_checks": leakage_checks,
                "status": "passed" if all(item["ok"] for item in leakage_checks) else "failed",
            }
        )
    )


def load_response_shape_frame(path: Path) -> pd.DataFrame:
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
            null_count = int(series.fillna("").astype(str).str.strip().eq("").sum())
        out[column] = null_count
    return out


def build_distribution(df: pd.DataFrame, column: str) -> Dict[str, Any]:
    values = df[column].fillna("").astype(str).str.strip()
    values = values[values != ""]
    counts = values.value_counts().sort_index()
    return {
        "column": column,
        "unique_count": int(values.nunique()),
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
    parts: List[pd.Series] = []
    for column in numeric_columns:
        series = pd.to_numeric(df[column], errors="coerce")
        clean = series.dropna()
        if clean.empty:
            continue
        std = float(clean.std(ddof=0))
        if std <= EPSILON:
            normalized = pd.Series(0.0, index=df.index, dtype=float)
        else:
            mean = float(clean.mean())
            normalized = ((series - mean).abs() / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        parts.append(normalized)
    if not parts:
        return pd.Series(0.0, index=df.index, dtype=float)
    return pd.concat(parts, axis=1).mean(axis=1)


def build_top_abnormal_rows(
    df: pd.DataFrame,
    *,
    numeric_columns: List[str],
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    scored = df.copy()
    scored["anomaly_score"] = compute_anomaly_scores(scored, numeric_columns)
    scored["__date_sort"] = pd.to_datetime(scored["date"], errors="coerce")
    scored = scored.sort_values(
        by=["anomaly_score", "__date_sort", "event_id"],
        ascending=[False, True, True],
        kind="mergesort",
    ).head(top_n)

    rows: List[Dict[str, Any]] = []
    for _, row in scored.iterrows():
        payload = {
            "date": "" if pd.isna(row["date"]) else pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
            "event_id": str(row.get("event_id", "")),
            "selected_asset": str(row.get("selected_asset", "")),
            "response_regime_context": str(row.get("response_regime_context", "")),
            "anomaly_score": round(float(row["anomaly_score"]), 6),
            "feature_values": {},
        }
        for column in numeric_columns:
            value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
            payload["feature_values"][column] = None if pd.isna(value) else round(float(value), 6)
        rows.append(payload)
    return rows


def build_profile_payload(
    *,
    bot_id: str,
    df: pd.DataFrame,
    numeric_columns: List[str],
) -> Dict[str, Any]:
    date_series = pd.to_datetime(df["date"], errors="coerce")
    return with_dev_flags(
        with_semantic_scope(
            {
                "artifact_type": "dev_only_response_shape_profile_report",
                "artifact_id": f"{bot_id}_profile",
                "generated_at_utc": timestamp_utc(),
                "bot_id": bot_id,
                "row_count": int(len(df)),
                "date_min": "" if date_series.dropna().empty else date_series.min().strftime("%Y-%m-%d"),
                "date_max": "" if date_series.dropna().empty else date_series.max().strftime("%Y-%m-%d"),
                "selected_asset_coverage": build_distribution(df, "selected_asset"),
                "entry_regime_distribution": build_distribution(df, "entry_regime"),
                "response_regime_context_distribution": build_distribution(df, "response_regime_context"),
                "null_count_per_column": count_nulls_by_column(df),
                "numeric_feature_summary": build_numeric_summary(df, numeric_columns),
                "anomaly_score_definition": "mean absolute z-score across configured response-shape numeric columns",
                "top_abnormal_rows": build_top_abnormal_rows(df, numeric_columns=numeric_columns),
                "status": "generated_dev_only_response_shape_profile",
            }
        )
    )


def refresh_manifest_profile_path(manifest_path: Path, profile_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_files = manifest.setdefault("output_files", {})
    output_files["profile_json"] = str(profile_path)
    save_json(manifest_path, manifest)
