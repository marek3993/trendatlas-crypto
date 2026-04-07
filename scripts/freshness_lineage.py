from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


DATE_COL_CANDIDATES = ("date", "datetime", "timestamp", "time", "dt", "ts")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_iso_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def read_last_date(path: Path, date_col_candidates: tuple[str, ...] = DATE_COL_CANDIDATES) -> str | None:
    if not path.exists() or not path.is_file():
        return None

    rows = read_csv_rows(path)
    if not rows:
        return None

    for candidate in date_col_candidates:
        if candidate not in rows[0]:
            continue
        raw = str(rows[-1].get(candidate, "")).strip()
        if raw:
            return parse_iso_date(raw).isoformat()

    return None


def read_single_csv_value(path: Path, field: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    rows = read_csv_rows(path)
    if not rows:
        return None
    value = str(rows[0].get(field, "")).strip()
    return value or None


def compute_first_missing_date(
    source_last_date: str | None,
    raw_last_date: str | None,
    output_last_date: str | None,
) -> str | None:
    source_last = parse_iso_date(source_last_date)
    raw_last = parse_iso_date(raw_last_date)
    output_last = parse_iso_date(output_last_date)

    producible_horizon = min(
        (value for value in (source_last, raw_last) if value is not None),
        default=None,
    )
    if producible_horizon is None or output_last is None:
        return None
    if output_last >= producible_horizon:
        return None
    return (output_last + timedelta(days=1)).isoformat()


def build_producer_lineage(
    *,
    producer_script: str | Path,
    source_file: str | Path,
    raw_file: str | Path,
    output_file: str | Path,
    date_semantics: str,
) -> dict[str, str | None]:
    source_path = Path(source_file)
    raw_path = Path(raw_file)
    output_path = Path(output_file)

    source_last_date = read_last_date(source_path)
    raw_last_date = read_last_date(raw_path)
    output_last_date = read_last_date(output_path)

    return {
        "producer_script": str(Path(producer_script).resolve()),
        "source_file": str(source_path),
        "source_last_date": source_last_date,
        "raw_last_date": raw_last_date,
        "output_last_date": output_last_date,
        "first_missing_date_if_any": compute_first_missing_date(
            source_last_date=source_last_date,
            raw_last_date=raw_last_date,
            output_last_date=output_last_date,
        ),
        "date_semantics": date_semantics,
    }
