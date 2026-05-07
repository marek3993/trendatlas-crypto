from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_adapters.phase68g_btc_persistence_10d_early_risk_075_adapter import (
    CANDIDATE_ID,
    CANDIDATE_LABEL,
    COMPARE_METRIC_SPECS,
    COMPARE_SCHEMA_VERSION,
    DIAGNOSTICS_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    QUALITY_SCHEMA_VERSION,
    ROOT,
    SNAPSHOT_SCHEMA_VERSION,
    STAGED_TIMESERIES_COLUMNS,
    Phase68gBtcPersistence10dEarlyRisk075StagedAdapter,
    build_reason_text,
    capture_protected_state,
    expected_truth_contract_state,
    read_truth_contract_state,
)


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "production" / "candidates" / CANDIDATE_ID
DEFAULT_SNAPSHOT_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_snapshot.json"
DEFAULT_TIMESERIES_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_timeseries.csv"
DEFAULT_DIAGNOSTICS_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_diagnostics.json"
DEFAULT_QUALITY_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_snapshot.quality.json"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_snapshot.manifest.json"
DEFAULT_COMPARE_JSON_PATH = DEFAULT_OUTPUT_DIR / "compare_vs_current_production_core.json"
DEFAULT_COMPARE_CSV_PATH = DEFAULT_OUTPUT_DIR / "compare_vs_current_production_core.csv"


REQUIRED_SNAPSHOT_KEYS = [
    "artifact_type",
    "schema_version",
    "generated_at_utc",
    "candidate_id",
    "candidate_label",
    "base_strategy_version",
    "status",
    "live_truth",
    "app_truth",
    "execution_truth",
    "dev_only_source_lineage",
    "non_authoritative_research_input",
    "official_truth",
    "strategy_advancement",
    "closed_day",
    "compare_universe",
    "current_state",
    "baseline_current_state",
    "metrics",
    "decision_context",
    "source_inputs",
    "validation",
    "provenance",
]

REQUIRED_DIAGNOSTICS_KEYS = [
    "artifact_type",
    "schema_version",
    "generated_at_utc",
    "candidate_id",
    "candidate_label",
    "base_strategy_version",
    "closed_day",
    "compare_universe",
    "latest_state_explanation",
    "baseline_separation_explanation",
    "current_candidate_trade_state",
    "current_baseline_trade_state",
    "metrics",
    "window_counts",
    "blocker_rows",
    "recent_activation_windows",
    "handoff_row_audit",
    "recent_rebalance_events",
    "lineage",
    "compare_summary",
    "validation",
]

TEXT_COLUMNS = {
    "date",
    "candidate_id",
    "candidate_label",
    "base_strategy_version",
    "strategy_id",
    "strategy_version",
    "candidate_asset",
    "selected_asset",
    "actual_held_asset",
    "authorized_tradable_asset",
    "held_asset",
    "current_asset",
    "regime",
    "market_state",
    "execution_state",
    "execution_target_asset",
    "trend_state",
    "leverage_state_reason",
    "reason_code",
    "override_state",
    "candidate_reason",
    "baseline_candidate_asset",
    "baseline_selected_asset",
    "baseline_actual_held_asset",
    "baseline_authorized_tradable_asset",
    "baseline_current_asset",
    "baseline_execution_target_asset",
    "baseline_regime",
    "baseline_market_state",
    "baseline_execution_state",
    "baseline_reason_code",
}

BOOL_COLUMNS = {
    "trend_permission_active",
    "cash_day",
    "btc_day",
    "in_market",
    "is_rebalance_day",
    "asset_transition_day",
    "trend_block_day",
    "stress_block_day",
    "trend_gate_pass",
    "leverage_active",
    "source_validated",
    "baseline_cash",
    "baseline_full_risk",
    "persistence_entry_filter_ready",
    "early_risk_active",
    "candidate_entry_day",
    "candidate_exit_day",
    "hard_invalidation",
    "dev_only_source_lineage",
    "non_authoritative_research_input",
    "official_truth",
    "live_truth",
    "app_truth",
    "execution_truth",
    "baseline_trend_permission_active",
    "baseline_cash_day",
    "baseline_in_market",
    "baseline_btc_day",
    "baseline_is_rebalance_day",
    "baseline_asset_transition_day",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _read_csv_required(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required CSV file: {path}")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if frame.empty:
        raise ValueError(f"CSV has no rows in {path}")
    return frame


def _check_required_keys(payload: dict[str, Any], keys: list[str], *, context: str, errors: list[str]) -> None:
    for key in keys:
        if key not in payload:
            errors.append(f"{context} missing required field: {key}")


def _compare_text(actual: Any, expected: str, *, context: str, errors: list[str]) -> None:
    actual_text = str(actual or "").strip()
    if actual_text != expected:
        errors.append(f"{context} mismatch: actual={actual_text!r} expected={expected!r}")


def _compare_float(actual: Any, expected: float, *, context: str, errors: list[str], tolerance: float = 1e-9) -> None:
    try:
        actual_value = float(actual)
    except Exception:
        errors.append(f"{context} must be numeric")
        return
    if abs(actual_value - expected) > tolerance:
        errors.append(f"{context} mismatch: actual={actual_value} expected={expected}")


def _mixed_scalar_equal(actual: Any, expected: Any, *, tolerance: float = 1e-9) -> bool:
    if pd.isna(actual) and (expected is None or pd.isna(expected)):
        return True
    if expected is None and (actual is None or pd.isna(actual)):
        return True
    if isinstance(expected, bool) or isinstance(actual, bool):
        actual_text = str(actual).strip().lower()
        expected_text = str(expected).strip().lower()
        if actual_text in {"true", "false"} and expected_text in {"true", "false"}:
            return actual_text == expected_text
    try:
        actual_value = float(actual)
        expected_value = float(expected)
    except Exception:
        return str(actual).strip() == str(expected).strip()
    return abs(actual_value - expected_value) <= tolerance


def _compare_series(actual: pd.Series, expected: pd.Series, *, column: str, errors: list[str]) -> None:
    if column in BOOL_COLUMNS:
        if actual.fillna(False).astype(bool).tolist() != expected.fillna(False).astype(bool).tolist():
            errors.append(f"timeseries rebuilt mismatch for {column}")
        return
    if column in TEXT_COLUMNS:
        if actual.fillna("").astype(str).tolist() != expected.fillna("").astype(str).tolist():
            errors.append(f"timeseries rebuilt mismatch for {column}")
        return
    actual_numeric = pd.to_numeric(actual, errors="coerce").fillna(0.0).round(12)
    expected_numeric = pd.to_numeric(expected, errors="coerce").fillna(0.0).round(12)
    if (actual_numeric - expected_numeric).abs().gt(1e-12).any():
        errors.append(f"timeseries rebuilt mismatch for {column}")


def _protected_hashes_equal(
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    current_state: dict[str, Any],
) -> tuple[bool, list[str]]:
    details: list[str] = []
    all_paths = sorted(set(before_state) | set(after_state) | set(current_state))
    ok = True
    for path in all_paths:
        before_entry = before_state.get(path, {})
        after_entry = after_state.get(path, {})
        current_entry = current_state.get(path, {})
        if before_entry.get("exists") != after_entry.get("exists") or before_entry.get("exists") != current_entry.get("exists"):
            ok = False
            details.append(path)
            continue
        if before_entry.get("exists"):
            if before_entry.get("sha256") != after_entry.get("sha256") or before_entry.get("sha256") != current_entry.get("sha256"):
                ok = False
                details.append(path)
    return ok, details


def _truth_contracts_match() -> tuple[bool, list[str]]:
    current = read_truth_contract_state(root=ROOT)
    expected = expected_truth_contract_state()
    mismatches: list[str] = []
    for key, expected_value in expected.items():
        if str(current.get(key) or "").strip() != expected_value:
            mismatches.append(f"{key}={current.get(key)!r}")
    return (not mismatches), mismatches


def validate_staged_payloads(
    *,
    snapshot: dict[str, Any],
    timeseries: pd.DataFrame,
    diagnostics: dict[str, Any],
    compare_payload: dict[str, Any],
    compare_rows: pd.DataFrame,
    manifest: dict[str, Any],
    adapter: Phase68gBtcPersistence10dEarlyRisk075StagedAdapter,
    inputs: dict[str, Any],
    protected_before: dict[str, Any],
    protected_after: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    _check_required_keys(snapshot, REQUIRED_SNAPSHOT_KEYS, context="snapshot", errors=errors)
    _check_required_keys(diagnostics, REQUIRED_DIAGNOSTICS_KEYS, context="diagnostics", errors=errors)
    _check_required_keys(
        compare_payload,
        [
            "artifact_type",
            "schema_version",
            "generated_at_utc",
            "candidate_id",
            "candidate_label",
            "base_strategy_version",
            "baseline_source_path",
            "candidate_universe_rule",
            "comparison_status",
            "window_counts",
            "selected_variant",
            "durable_baseline_route",
            "windows",
            "blocker_rows",
        ],
        context="compare_payload",
        errors=errors,
    )
    _check_required_keys(
        manifest,
        [
            "artifact_type",
            "schema_version",
            "generated_at_utc",
            "candidate_id",
            "base_strategy_version",
            "adapter_name",
            "build_command",
            "source_inputs",
            "output_paths",
            "protected_paths_before",
            "protected_paths_after",
            "truth_contract_expectations",
            "validation_status",
        ],
        context="manifest",
        errors=errors,
    )

    missing_columns = [column for column in STAGED_TIMESERIES_COLUMNS if column not in timeseries.columns]
    if missing_columns:
        errors.append(f"timeseries missing required columns: {', '.join(missing_columns)}")

    _compare_text(snapshot.get("artifact_type"), "staged_strategy_candidate_snapshot", context="snapshot.artifact_type", errors=errors)
    _compare_text(diagnostics.get("artifact_type"), "staged_strategy_candidate_diagnostics", context="diagnostics.artifact_type", errors=errors)
    _compare_text(compare_payload.get("artifact_type"), "staged_strategy_candidate_compare", context="compare_payload.artifact_type", errors=errors)
    _compare_text(manifest.get("artifact_type"), "staged_strategy_candidate_snapshot_manifest", context="manifest.artifact_type", errors=errors)
    _compare_text(snapshot.get("candidate_id"), CANDIDATE_ID, context="snapshot.candidate_id", errors=errors)
    _compare_text(snapshot.get("candidate_label"), CANDIDATE_LABEL, context="snapshot.candidate_label", errors=errors)
    _compare_text(snapshot.get("base_strategy_version"), adapter.base_strategy_version, context="snapshot.base_strategy_version", errors=errors)
    _compare_text(snapshot.get("status"), "staged_candidate", context="snapshot.status", errors=errors)
    _compare_text(compare_payload.get("baseline_source_path"), "outputs/production/current_strategy_timeseries.csv", context="compare_payload.baseline_source_path", errors=errors)

    if int(snapshot.get("schema_version") or 0) != SNAPSHOT_SCHEMA_VERSION:
        errors.append(
            f"snapshot.schema_version mismatch: actual={snapshot.get('schema_version')} expected={SNAPSHOT_SCHEMA_VERSION}"
        )
    if int(diagnostics.get("schema_version") or 0) != DIAGNOSTICS_SCHEMA_VERSION:
        errors.append(
            f"diagnostics.schema_version mismatch: actual={diagnostics.get('schema_version')} expected={DIAGNOSTICS_SCHEMA_VERSION}"
        )
    if int(compare_payload.get("schema_version") or 0) != COMPARE_SCHEMA_VERSION:
        errors.append(
            f"compare_payload.schema_version mismatch: actual={compare_payload.get('schema_version')} expected={COMPARE_SCHEMA_VERSION}"
        )
    if int(manifest.get("schema_version") or 0) != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"manifest.schema_version mismatch: actual={manifest.get('schema_version')} expected={MANIFEST_SCHEMA_VERSION}"
        )

    checks["candidate_truth_flags_staged_only"] = (
        bool(snapshot.get("live_truth")) is False
        and bool(snapshot.get("app_truth")) is False
        and bool(snapshot.get("execution_truth")) is False
        and bool(snapshot.get("official_truth")) is False
        and bool(snapshot.get("strategy_advancement")) is False
        and bool(snapshot.get("dev_only_source_lineage")) is True
        and bool(snapshot.get("non_authoritative_research_input")) is True
    )
    if not checks["candidate_truth_flags_staged_only"]:
        errors.append("snapshot truth flags must remain staged-only, non-authoritative, and non-promoted")

    current_row = timeseries.iloc[-1]
    _compare_text(snapshot.get("closed_day"), str(current_row["date"]), context="snapshot.closed_day", errors=errors)
    current_state = snapshot.get("current_state")
    if not isinstance(current_state, dict):
        errors.append("snapshot.current_state must be an object")
    else:
        _compare_text(current_state.get("candidate_asset"), str(current_row["candidate_asset"]), context="snapshot.current_state.candidate_asset", errors=errors)
        _compare_text(current_state.get("actual_held_asset"), str(current_row["actual_held_asset"]), context="snapshot.current_state.actual_held_asset", errors=errors)
        _compare_float(current_state.get("effective_market_exposure"), float(current_row["effective_market_exposure"]), context="snapshot.current_state.effective_market_exposure", errors=errors)
        _compare_float(current_state.get("model_candidate_exposure"), float(current_row["model_candidate_exposure"]), context="snapshot.current_state.model_candidate_exposure", errors=errors)
        _compare_text(current_state.get("reason_code"), str(current_row["reason_code"]), context="snapshot.current_state.reason_code", errors=errors)
        _compare_text(current_state.get("reason_text"), build_reason_text(current_row), context="snapshot.current_state.reason_text", errors=errors)

    baseline_state = snapshot.get("baseline_current_state")
    if not isinstance(baseline_state, dict):
        errors.append("snapshot.baseline_current_state must be an object")
    else:
        _compare_text(baseline_state.get("candidate_asset"), str(current_row["baseline_candidate_asset"]), context="snapshot.baseline_current_state.candidate_asset", errors=errors)
        _compare_text(baseline_state.get("actual_held_asset"), str(current_row["baseline_actual_held_asset"]), context="snapshot.baseline_current_state.actual_held_asset", errors=errors)
        _compare_float(baseline_state.get("effective_market_exposure"), float(current_row["baseline_effective_market_exposure"]), context="snapshot.baseline_current_state.effective_market_exposure", errors=errors)
        _compare_text(baseline_state.get("reason_code"), str(current_row["baseline_reason_code"]), context="snapshot.baseline_current_state.reason_code", errors=errors)

    expected_timeseries = adapter.build_candidate_timeseries(inputs)
    replay_errors: list[str] = []
    for column in STAGED_TIMESERIES_COLUMNS:
        _compare_series(timeseries[column], expected_timeseries[column], column=column, errors=replay_errors)
    checks["candidate_rows_match_rebuilt_adapter"] = not replay_errors
    errors.extend(replay_errors)

    early_risk_mask = timeseries["early_risk_active"].fillna(False).astype(bool)
    checks["early_risk_modifies_only_baseline_cash_rows"] = True
    if early_risk_mask.any():
        checks["early_risk_modifies_only_baseline_cash_rows"] = bool(
            timeseries.loc[early_risk_mask, "baseline_cash"].fillna(False).astype(bool).all()
            and timeseries.loc[early_risk_mask, "baseline_actual_held_asset"].fillna("").astype(str).eq("CASH").all()
            and pd.to_numeric(timeseries.loc[early_risk_mask, "baseline_effective_market_exposure"], errors="coerce").fillna(0.0).eq(0.0).all()
        )
    if not checks["early_risk_modifies_only_baseline_cash_rows"]:
        errors.append("EARLY_RISK rows must modify only baseline CASH / out-of-market rows")

    baseline_full_risk_mask = timeseries["baseline_full_risk"].fillna(False).astype(bool)
    checks["baseline_full_risk_rows_pass_through_unchanged"] = True
    if baseline_full_risk_mask.any():
        checks["baseline_full_risk_rows_pass_through_unchanged"] = bool(
            timeseries.loc[baseline_full_risk_mask, "actual_held_asset"].fillna("").astype(str).eq(
                timeseries.loc[baseline_full_risk_mask, "baseline_actual_held_asset"].fillna("").astype(str)
            ).all()
            and pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "effective_market_exposure"], errors="coerce").fillna(0.0).round(12).eq(
                pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "baseline_effective_market_exposure"], errors="coerce").fillna(0.0).round(12)
            ).all()
            and pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "return_net"], errors="coerce").fillna(0.0).round(12).eq(
                pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "baseline_return_net"], errors="coerce").fillna(0.0).round(12)
            ).all()
            and pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "turnover"], errors="coerce").fillna(0.0).round(12).eq(
                pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "baseline_turnover"], errors="coerce").fillna(0.0).round(12)
            ).all()
            and pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "fees_daily"], errors="coerce").fillna(0.0).round(12).eq(
                pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "baseline_fees_daily"], errors="coerce").fillna(0.0).round(12)
            ).all()
            and pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "funding_daily"], errors="coerce").fillna(0.0).round(12).eq(
                pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "baseline_funding_daily"], errors="coerce").fillna(0.0).round(12)
            ).all()
            and pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "borrow_cost_daily"], errors="coerce").fillna(0.0).round(12).eq(
                pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "baseline_borrow_cost_daily"], errors="coerce").fillna(0.0).round(12)
            ).all()
            and pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "slippage_cost_daily"], errors="coerce").fillna(0.0).round(12).eq(
                pd.to_numeric(timeseries.loc[baseline_full_risk_mask, "baseline_slippage_daily"], errors="coerce").fillna(0.0).round(12)
            ).all()
        )
    if not checks["baseline_full_risk_rows_pass_through_unchanged"]:
        errors.append("baseline FULL_RISK rows must pass through unchanged")

    candidate_net_formula = (
        pd.to_numeric(timeseries["authorized_return_gross"], errors="coerce").fillna(0.0)
        - pd.to_numeric(timeseries["fees_daily"], errors="coerce").fillna(0.0)
        - pd.to_numeric(timeseries["funding_daily"], errors="coerce").fillna(0.0)
        - pd.to_numeric(timeseries["borrow_cost_daily"], errors="coerce").fillna(0.0)
        - pd.to_numeric(timeseries["slippage_cost_daily"], errors="coerce").fillna(0.0)
    )
    baseline_net_formula = (
        pd.to_numeric(timeseries["baseline_return_gross"], errors="coerce").fillna(0.0)
        - pd.to_numeric(timeseries["baseline_fees_daily"], errors="coerce").fillna(0.0)
        - pd.to_numeric(timeseries["baseline_funding_daily"], errors="coerce").fillna(0.0)
        - pd.to_numeric(timeseries["baseline_borrow_cost_daily"], errors="coerce").fillna(0.0)
        - pd.to_numeric(timeseries["baseline_slippage_daily"], errors="coerce").fillna(0.0)
    )
    checks["fees_and_costs_included_in_candidate_net_returns"] = bool(
        (
            candidate_net_formula
            - pd.to_numeric(timeseries["authorized_return_net"], errors="coerce").fillna(0.0)
        ).abs().le(1e-9).all()
    )
    checks["fees_and_costs_included_in_baseline_net_returns"] = bool(
        (
            baseline_net_formula
            - pd.to_numeric(timeseries["baseline_return_net"], errors="coerce").fillna(0.0)
        ).abs().le(1e-9).all()
    )
    if not checks["fees_and_costs_included_in_candidate_net_returns"]:
        errors.append("candidate net returns must include fees and modeled costs")
    if not checks["fees_and_costs_included_in_baseline_net_returns"]:
        errors.append("baseline net returns must include fees and modeled costs")

    checks["dev_only_non_authoritative_lineage_preserved"] = bool(
        timeseries["dev_only_source_lineage"].fillna(False).astype(bool).all()
        and timeseries["non_authoritative_research_input"].fillna(False).astype(bool).all()
        and (~timeseries["official_truth"].fillna(False).astype(bool)).all()
        and (~timeseries["live_truth"].fillna(False).astype(bool)).all()
        and (~timeseries["app_truth"].fillna(False).astype(bool)).all()
        and (~timeseries["execution_truth"].fillna(False).astype(bool)).all()
    )
    if not checks["dev_only_non_authoritative_lineage_preserved"]:
        errors.append("dev_only / non_authoritative lineage flags are not preserved on every row")

    expected_compare_payload, expected_compare_rows = adapter.build_compare_payload(inputs)
    checks["compare_windows_match_rebuilt_adapter"] = compare_payload.get("windows") == expected_compare_payload.get("windows")
    if not checks["compare_windows_match_rebuilt_adapter"]:
        errors.append("compare_payload.windows mismatch versus rebuilt adapter")
    if compare_payload.get("blocker_rows") != expected_compare_payload.get("blocker_rows"):
        errors.append("compare_payload.blocker_rows mismatch versus rebuilt adapter")
    if compare_payload.get("window_counts") != expected_compare_payload.get("window_counts"):
        errors.append("compare_payload.window_counts mismatch versus rebuilt adapter")
    if compare_payload.get("selected_variant") != expected_compare_payload.get("selected_variant"):
        errors.append("compare_payload.selected_variant mismatch versus rebuilt adapter")

    expected_compare_rows_df = pd.DataFrame(expected_compare_rows)
    required_compare_columns = [
        "period",
        "metric",
        "baseline_value",
        "candidate_value",
        "delta_candidate_minus_baseline",
        "return_basis_status",
        "net_costs_included",
    ]
    missing_compare_columns = [column for column in required_compare_columns if column not in compare_rows.columns]
    if missing_compare_columns:
        errors.append(f"compare CSV missing required columns: {', '.join(missing_compare_columns)}")
    else:
        actual_rows = compare_rows.loc[:, required_compare_columns].copy()
        expected_rows = expected_compare_rows_df.loc[:, required_compare_columns].copy()
        if len(actual_rows) != len(expected_rows):
            errors.append(f"compare CSV row count mismatch: actual={len(actual_rows)} expected={len(expected_rows)}")
        else:
            for column in ("period", "metric", "return_basis_status"):
                if actual_rows[column].fillna("").astype(str).tolist() != expected_rows[column].fillna("").astype(str).tolist():
                    errors.append(f"compare CSV mismatch for column {column}")
            for column in ("net_costs_included",):
                if actual_rows[column].fillna(False).astype(bool).tolist() != expected_rows[column].fillna(False).astype(bool).tolist():
                    errors.append(f"compare CSV mismatch for column {column}")
            for column in ("baseline_value", "candidate_value", "delta_candidate_minus_baseline"):
                if any(
                    not _mixed_scalar_equal(actual_value, expected_value)
                    for actual_value, expected_value in zip(actual_rows[column].tolist(), expected_rows[column].tolist())
                ):
                    errors.append(f"compare CSV mismatch for column {column}")

    durable_route = snapshot.get("source_inputs", {}).get("durable_baseline_route")
    checks["durable_baseline_route_recorded"] = isinstance(durable_route, dict) and str(durable_route.get("mode") or "").strip() == "canonical_phase68g_source_rebuild"
    if not checks["durable_baseline_route_recorded"]:
        errors.append("snapshot.source_inputs.durable_baseline_route must record the canonical phase68g rebuild route")

    manifest_before = manifest.get("protected_paths_before")
    manifest_after = manifest.get("protected_paths_after")
    current_protected_state = capture_protected_state(root=ROOT)
    protected_ok, protected_details = _protected_hashes_equal(
        manifest_before if isinstance(manifest_before, dict) else protected_before,
        manifest_after if isinstance(manifest_after, dict) else protected_after,
        current_protected_state,
    )
    checks["current_production_outputs_and_truth_files_unchanged"] = protected_ok
    if not protected_ok:
        errors.append("protected files changed unexpectedly: " + ", ".join(protected_details))

    truth_ok, truth_mismatches = _truth_contracts_match()
    checks["live_app_execution_truth_unchanged"] = truth_ok
    if not truth_ok:
        errors.append("live/app/execution truth changed unexpectedly: " + "; ".join(truth_mismatches))

    checks["validation_status_passed"] = True

    status = "passed" if not errors else "failed"
    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def build_quality_payload(
    *,
    validation: dict[str, Any],
    snapshot_path: Path,
    timeseries_path: Path,
    diagnostics_path: Path,
    compare_json_path: Path,
    compare_csv_path: Path,
) -> dict[str, Any]:
    return {
        "artifact_type": "staged_strategy_candidate_snapshot_quality",
        "schema_version": QUALITY_SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "status": validation["status"],
        "error_count": len(validation["errors"]),
        "warning_count": len(validation["warnings"]),
        "errors": list(validation["errors"]),
        "warnings": list(validation["warnings"]),
        "checks": dict(validation["checks"]),
        "validated_paths": {
            "snapshot_path": str(snapshot_path.resolve()),
            "timeseries_path": str(timeseries_path.resolve()),
            "diagnostics_path": str(diagnostics_path.resolve()),
            "compare_json_path": str(compare_json_path.resolve()),
            "compare_csv_path": str(compare_csv_path.resolve()),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed validator for the BTC persistence staged Production Core candidate bundle.")
    parser.add_argument("--candidate", default=CANDIDATE_ID)
    parser.add_argument("--snapshot-path", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--timeseries-path", type=Path, default=DEFAULT_TIMESERIES_PATH)
    parser.add_argument("--diagnostics-path", type=Path, default=DEFAULT_DIAGNOSTICS_PATH)
    parser.add_argument("--quality-path", type=Path, default=DEFAULT_QUALITY_PATH)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--compare-json-path", type=Path, default=DEFAULT_COMPARE_JSON_PATH)
    parser.add_argument("--compare-csv-path", type=Path, default=DEFAULT_COMPARE_CSV_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.candidate != CANDIDATE_ID:
        raise SystemExit(f"Unsupported candidate: {args.candidate!r}")

    adapter = Phase68gBtcPersistence10dEarlyRisk075StagedAdapter()
    snapshot = _read_json_required(args.snapshot_path)
    timeseries = _read_csv_required(args.timeseries_path)
    diagnostics = _read_json_required(args.diagnostics_path)
    compare_payload = _read_json_required(args.compare_json_path)
    compare_rows = _read_csv_required(args.compare_csv_path)
    manifest = _read_json_required(args.manifest_path)
    inputs = adapter.load_inputs(root=ROOT)

    validation = validate_staged_payloads(
        snapshot=snapshot,
        timeseries=timeseries,
        diagnostics=diagnostics,
        compare_payload=compare_payload,
        compare_rows=compare_rows,
        manifest=manifest,
        adapter=adapter,
        inputs=inputs,
        protected_before=manifest.get("protected_paths_before", {}),
        protected_after=manifest.get("protected_paths_after", {}),
    )
    quality = build_quality_payload(
        validation=validation,
        snapshot_path=args.snapshot_path,
        timeseries_path=args.timeseries_path,
        diagnostics_path=args.diagnostics_path,
        compare_json_path=args.compare_json_path,
        compare_csv_path=args.compare_csv_path,
    )
    args.quality_path.parent.mkdir(parents=True, exist_ok=True)
    args.quality_path.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(quality, indent=2, ensure_ascii=False))
    if validation["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
