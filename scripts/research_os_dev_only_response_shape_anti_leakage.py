from __future__ import annotations

from typing import Any, Dict, List


CONTROL_FLAG_COLUMNS = {
    "analysis_mode",
    "live_decision_ready",
    "dev_only",
    "non_authoritative",
    "official_truth",
    "strategy_advancement",
}

FORBIDDEN_COLUMN_TOKENS = (
    "future",
    "next_bar",
    "target",
    "winner",
    "promotion",
    "tradability",
    "candidate_quality",
    "leverage_guidance",
    "allocation_signal",
    "recommended_action",
    "live_order",
)

DESCRIPTIVE_DIMENSION_COLUMNS = {
    "follow_through_quality",
    "false_start_risk",
    "volatility_damage_shape",
    "recovery_vs_exhaustion",
    "response_regime_context",
}

REQUIRED_ANALYSIS_MODE = "descriptive_aftermath_only"


def check_required_columns(columns: List[str], required_columns: List[str]) -> Dict[str, Any]:
    missing = [column for column in required_columns if column not in columns]
    return {
        "name": "required_columns_present",
        "ok": len(missing) == 0,
        "detail": "all required columns present" if not missing else f"missing columns: {missing}",
    }


def check_forbidden_columns(columns: List[str]) -> Dict[str, Any]:
    bad = []
    for column in columns:
        normalized = column.strip().lower()
        if normalized in CONTROL_FLAG_COLUMNS:
            continue
        for token in FORBIDDEN_COLUMN_TOKENS:
            if token in normalized:
                bad.append(column)
                break
    return {
        "name": "forbidden_decision_or_authoritative_columns_absent",
        "ok": len(bad) == 0,
        "detail": "no forbidden columns found" if not bad else f"forbidden columns: {bad}",
    }


def check_hindsight_columns(columns: List[str]) -> Dict[str, Any]:
    bad = []
    hindsight_tokens = ("return", "drawdown", "recovery", "volatility")
    for column in columns:
        normalized = column.strip().lower()
        if normalized in CONTROL_FLAG_COLUMNS or normalized in DESCRIPTIVE_DIMENSION_COLUMNS:
            continue
        if any(token in normalized for token in hindsight_tokens) and not normalized.startswith("observed_"):
            bad.append(column)
    return {
        "name": "hindsight_columns_are_explicitly_observed",
        "ok": len(bad) == 0,
        "detail": "all hindsight columns use observed_ prefix" if not bad else f"ambiguous hindsight columns: {bad}",
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


def check_semantic_scope(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    bad_rows = 0
    for row in rows:
        mode_ok = str(row.get("analysis_mode", "")).strip() == REQUIRED_ANALYSIS_MODE
        live_ok = str(row.get("live_decision_ready", "")).lower() in {"false", "0"}
        if not (mode_ok and live_ok):
            bad_rows += 1
    return {
        "name": "descriptive_aftermath_scope_locked",
        "ok": bad_rows == 0,
        "detail": "rows are locked to descriptive aftermath semantics"
        if bad_rows == 0
        else f"rows outside descriptive aftermath scope count={bad_rows}",
    }


def run_response_shape_output_checks(
    *,
    columns: List[str],
    required_columns: List[str],
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        check_required_columns(columns, required_columns),
        check_forbidden_columns(columns),
        check_hindsight_columns(columns),
        check_dev_flags(rows),
        check_semantic_scope(rows),
    ]
