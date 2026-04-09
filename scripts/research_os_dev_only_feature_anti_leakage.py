from __future__ import annotations

from typing import Any, Dict, List


CONTROL_FLAG_COLUMNS = {
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
}


FORBIDDEN_COLUMN_TOKENS = (
    "future",
    "forward_return",
    "next_bar",
    "target",
    "label",
    "winner",
    "promotion",
    "official",
)


def check_required_columns(columns: List[str], required_columns: List[str]) -> Dict[str, Any]:
    missing = [col for col in required_columns if col not in columns]
    return {
        "name": "required_columns_present",
        "ok": len(missing) == 0,
        "detail": "all required columns present" if not missing else f"missing columns: {missing}",
    }


def check_forbidden_columns(columns: List[str]) -> Dict[str, Any]:
    bad = []
    for col in columns:
        normalized = col.strip().lower()
        if normalized in CONTROL_FLAG_COLUMNS:
            continue
        for token in FORBIDDEN_COLUMN_TOKENS:
            if token in normalized:
                bad.append(col)
                break
    return {
        "name": "forbidden_future_or_authoritative_columns_absent",
        "ok": len(bad) == 0,
        "detail": "no forbidden columns found" if not bad else f"forbidden columns: {bad}",
    }


def check_dev_flags(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    bad_rows = 0
    for row in rows:
        row_ok = True
        if str(row.get("dev_only", "")).lower() not in {"true", "1"}:
            row_ok = False
        if str(row.get("non_authoritative", "")).lower() not in {"true", "1"}:
            row_ok = False
        if str(row.get("official_truth", "")).lower() not in {"false", "0"}:
            row_ok = False
        if str(row.get("strategy_advancement", "")).lower() not in {"false", "0"}:
            row_ok = False
        if not row_ok:
            bad_rows += 1
    return {
        "name": "dev_only_flags_present_on_rows",
        "ok": bad_rows == 0,
        "detail": "row dev-only flags valid" if bad_rows == 0 else f"rows with invalid flags count={bad_rows}",
    }


def run_feature_output_checks(
    *,
    columns: List[str],
    required_columns: List[str],
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        check_required_columns(columns, required_columns),
        check_forbidden_columns(columns),
        check_dev_flags(rows),
    ]
