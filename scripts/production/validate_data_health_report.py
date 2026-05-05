from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.data_health_common import (
    ACTION_VALUES,
    DEFAULT_OUTPUT_DIR,
    QUALITY_ARTIFACT_TYPE,
    REPORT_ARTIFACT_TYPE,
    SCHEMA_VERSION,
    STATUS_VALUES,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate centralized MRV1 data health report outputs.")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_OUTPUT_DIR / "data_health_report.json")
    parser.add_argument("--quality-path", type=Path, default=DEFAULT_OUTPUT_DIR / "data_health_report.quality.json")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not contain a top-level JSON object.")
    return payload


def main() -> None:
    args = parse_args()
    report = load_json(args.report_path)
    quality = load_json(args.quality_path)

    errors: list[str] = []
    if report.get("artifact_type") != REPORT_ARTIFACT_TYPE:
        errors.append("Report artifact_type mismatch.")
    if quality.get("artifact_type") != QUALITY_ARTIFACT_TYPE:
        errors.append("Quality artifact_type mismatch.")
    if int(report.get("schema_version") or 0) != SCHEMA_VERSION:
        errors.append("Report schema_version mismatch.")
    if int(quality.get("schema_version") or 0) != SCHEMA_VERSION:
        errors.append("Quality schema_version mismatch.")

    sources = report.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("Report sources must be a non-empty list.")
    else:
        source_ids: list[str] = []
        for index, source in enumerate(sources):
            context = f"sources[{index}]"
            if not isinstance(source, dict):
                errors.append(f"{context} must be an object.")
                continue
            source_id = str(source.get("source_id") or "").strip()
            status = str(source.get("status") or "").strip()
            action = str(source.get("action") or "").strip()
            if not source_id:
                errors.append(f"{context}.source_id is missing.")
            source_ids.append(source_id)
            if status not in STATUS_VALUES:
                errors.append(f"{context}.status has invalid value {status!r}.")
            if action not in ACTION_VALUES:
                errors.append(f"{context}.action has invalid value {action!r}.")
        if len(source_ids) != len(set(source_ids)):
            errors.append("Duplicate source_id values detected.")

    print(json.dumps({"status": "passed" if not errors else "failed", "errors": errors}, indent=2, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
