from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


MANDATORY_DEV_FLAGS = {
    "dev_only": True,
    "non_authoritative": True,
    "official_truth": False,
    "strategy_advancement": False,
}

OUTPUT_ROOT = Path(r"C:\Users\benda\Desktop\market_regime_v1\outputs\research_os\dev_only\non_authoritative_features")


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def with_dev_flags(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out.update(MANDATORY_DEV_FLAGS)
    return out


def feature_file_paths(family_id: str) -> Dict[str, Path]:
    base = OUTPUT_ROOT / family_id
    return {
        "features_csv": Path(str(base) + ".features.csv"),
        "manifest_json": Path(str(base) + ".manifest.json"),
        "quality_json": Path(str(base) + ".quality.json"),
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
    family_id: str,
    family_type: str,
    input_refs: List[str],
    features_csv_path: Path,
    quality_json_path: Path,
    column_schema: List[str],
    row_count: int,
) -> Dict[str, Any]:
    return with_dev_flags(
        {
            "artifact_type": "dev_only_feature_output_manifest",
            "artifact_id": f"{family_id}_manifest",
            "generated_at_utc": timestamp_utc(),
            "family_id": family_id,
            "family_type": family_type,
            "output_files": {
                "features_csv": str(features_csv_path),
                "quality_json": str(quality_json_path),
            },
            "input_refs": input_refs,
            "column_schema": column_schema,
            "row_count": row_count,
            "status": "generated_dev_only_feature_output",
        }
    )


def build_quality_report(
    *,
    family_id: str,
    row_count: int,
    required_columns: List[str],
    leakage_checks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return with_dev_flags(
        {
            "artifact_type": "dev_only_feature_quality_report",
            "artifact_id": f"{family_id}_quality",
            "generated_at_utc": timestamp_utc(),
            "family_id": family_id,
            "row_count": row_count,
            "required_columns": required_columns,
            "leakage_checks": leakage_checks,
            "status": "passed" if all(item["ok"] for item in leakage_checks) else "failed",
        }
    )
