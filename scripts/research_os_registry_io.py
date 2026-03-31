from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def timestamp_local() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ensure_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def extract_numeric_score(run_dir: Path) -> Optional[float]:
    candidates = [
        run_dir / "metrics.json",
        run_dir / "summary.json",
        run_dir / "quality_report.json",
    ]
    score_keys = [
        "score",
        "primary_metric_value",
        "cagr_pct",
        "total_return_pct",
        "since2025_cagr_pct",
    ]

    for path in candidates:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for key in score_keys:
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    return float(value)

    summary_csv = run_dir / "summary.csv"
    compare_csv = run_dir / "compare.csv"

    for csv_path in [summary_csv, compare_csv]:
        if csv_path.exists():
            try:
                with csv_path.open("r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                if not rows:
                    continue
                first = rows[0]
                for key in score_keys:
                    if key in first:
                        try:
                            return float(first[key])
                        except Exception:
                            continue
            except Exception:
                continue

    return None


def update_candidates_registry(path: Path, candidate_id: str, fields: Dict[str, Any]) -> None:
    if not path.exists():
        raise RuntimeError(f"candidates_registry.csv missing: {path}")

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames or []

    if "candidate_id" not in headers:
        raise RuntimeError("candidates_registry.csv missing candidate_id header")

    target_row = None
    for row in rows:
        if row.get("candidate_id") == candidate_id:
            target_row = row
            break

    if target_row is None:
        target_row = {header: "" for header in headers}
        target_row["candidate_id"] = candidate_id
        rows.append(target_row)

    for key, value in fields.items():
        if key in headers:
            target_row[key] = "" if value is None else str(value)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)