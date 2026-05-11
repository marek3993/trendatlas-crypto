from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_adapters.phase68g_66g_1p25x_candidate_adapter import (
    ADAPTER_NAME,
    CASH_EQUIVALENT_ASSETS,
    MANIFEST_SCHEMA_VERSION,
    PRODUCTION_STRATEGY_ID,
    ROOT,
    SNAPSHOT_SCHEMA_VERSION,
    SOURCE_STRATEGY_VERSION,
    Phase68g66g1p25xCandidateAdapter,
    build_reason_text,
)
from scripts.production.strategy_adapters.phase68g_btc_persistence_10d_early_risk_075_adapter import (
    CANDIDATE_ID as BTC_PERSISTENCE_CANDIDATE_ID,
    Phase68gBtcPersistence10dEarlyRisk075Adapter,
)
from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import (
    CANDIDATE_ID as ETF_FLOW_CANDIDATE_ID,
    Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter,
)
from scripts.production.validate_current_strategy_snapshot import (
    build_quality_payload,
    validate_production_payloads,
)


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "production"
SNAPSHOT_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_snapshot.json"
TIMESERIES_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_timeseries.csv"
DIAGNOSTICS_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_diagnostics.json"
QUALITY_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_snapshot.quality.json"
MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "current_strategy_snapshot.manifest.json"
BTC_PERSISTENCE_SUMMARY_PATH = (
    ROOT
    / "outputs"
    / "execution"
    / "app_exports"
    / "phase68g_btc_persistence_10d_early_risk_075_authoritative_net_compare_export.csv"
)
BTC_PERSISTENCE_PAPER_PATH = (
    ROOT
    / "outputs"
    / "execution"
    / "app_exports"
    / "phase68g_btc_persistence_10d_early_risk_075_paper.csv"
)
APP_FRESHNESS_REPORT_PATH = (
    ROOT / "outputs" / "execution" / "freshness" / "app_freshness_report.json"
)
PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH = (
    ROOT
    / "outputs"
    / "execution"
    / "app_exports"
    / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
)
PHASE68G_MAIN_PAPER_PATH = (
    ROOT
    / "outputs"
    / "execution"
    / "app_exports"
    / "phase68g_66g_1p25x_candidate_paper.csv"
)
PHASE66G_CANONICAL_PAPER_PATH = (
    ROOT
    / "outputs"
    / "execution"
    / "app_exports"
    / "phase66g_production_soft_filters_paper.csv"
)
PHASE66G_LIVE_STATUS_PATH = (
    ROOT / "outputs" / "execution" / "app_exports" / "phase66g_live_status.csv"
)
PHASE66G_TREND_HISTORY_PATH = (
    ROOT / "outputs" / "execution" / "app_exports" / "phase66g_trend_barometer_history.csv"
)
PHASE67J_PAPER_PATH = (
    ROOT / "outputs" / "execution" / "app_exports" / "phase67j_no_neo_main_paper.csv"
)
PHASE67J_LIVE_STATUS_PATH = (
    ROOT / "outputs" / "execution" / "app_exports" / "phase67j_live_status.csv"
)
PHASE66G_DECISIONS_PATH = (
    ROOT
    / "outputs"
    / "phase66g_production_candidate_live"
    / "phase66g_production_candidate_decisions.csv"
)
PHASE68G_SCRIPT_PATH = ROOT / "scripts" / "phase68g_portfolio_exposure_leverage_validation.py"
PHASE68G_SOURCE_DIR = ROOT / "outputs" / "phase68g_portfolio_exposure_leverage_validation"
PHASE68G_SOURCE_PAPER_PATH = (
    PHASE68G_SOURCE_DIR / "papers" / "phase68g_66g_1p25x_candidate_paper.csv"
)
PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH = (
    PHASE68G_SOURCE_DIR / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _path_for_manifest(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _git_commit(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    commit = (result.stdout or "").strip()
    return commit or None


def _resolve_current_strategy_model(root: Path) -> str:
    truth_path = root / "source_of_truth" / "project_truth.json"
    payload = _read_json_required(truth_path)
    app_product_truth = payload.get("app_product_truth")
    if not isinstance(app_product_truth, dict):
        raise ValueError("project_truth.json missing app_product_truth")
    strategy_model = str(app_product_truth.get("main_strategy_model") or "").strip()
    if not strategy_model:
        raise ValueError("project_truth.json missing app_product_truth.main_strategy_model")
    return strategy_model


def _resolve_adapter(strategy_model: str) -> Any:
    if strategy_model == SOURCE_STRATEGY_VERSION:
        return Phase68g66g1p25xCandidateAdapter()
    if strategy_model == BTC_PERSISTENCE_CANDIDATE_ID:
        return Phase68gBtcPersistence10dEarlyRisk075Adapter()
    if strategy_model == ETF_FLOW_CANDIDATE_ID:
        return Phase68gEtfFlowImpulseEarlyRiskCooldown15LiveAdapter()
    raise ValueError(
        "No Production Core v1 adapter is registered for the current official strategy "
        f"(strategy_model={strategy_model})"
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def _atomic_write_csv(path: Path, frame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temp_path, index=False)
    temp_path.replace(path)


def _read_csv_last_value(path: Path, *field_names: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    last_row = rows[-1]
    for field_name in field_names:
        value = str(last_row.get(field_name) or "").strip()
        if value:
            return value
    return None


def _write_single_row_csv(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str]
    if path.exists() and path.is_file():
        with path.open("r", encoding="utf-8", newline="") as f:
            existing_fieldnames = csv.DictReader(f).fieldnames
        fieldnames = list(existing_fieldnames or row.keys())
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    else:
        fieldnames = list(row.keys())
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)
    temp_path.replace(path)


def _last_csv_day(path: Path, *field_names: str) -> str:
    value = _read_csv_last_value(path, *field_names)
    if not value:
        raise ValueError(f"Missing required date in {path}")
    return value


def _single_csv_value(path: Path, *field_names: str) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required CSV file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1:
        raise ValueError(f"Expected exactly one row in {path}, found {len(rows)}")
    for field_name in field_names:
        value = str(rows[0].get(field_name) or "").strip()
        if value:
            return value
    raise ValueError(f"Missing required field {field_names} in {path}")


def _phase68g_dependency_relative(root: Path, path: Path) -> Path:
    return root / path.relative_to(ROOT)


def _rebuild_phase68g_baseline_dependency_from_canonical_inputs(
    *,
    root: Path,
    target_closed_day: str,
) -> dict[str, Any]:
    script_path = _phase68g_dependency_relative(root, PHASE68G_SCRIPT_PATH)
    phase66g_paper_path = _phase68g_dependency_relative(root, PHASE66G_CANONICAL_PAPER_PATH)
    phase66g_live_status_path = _phase68g_dependency_relative(root, PHASE66G_LIVE_STATUS_PATH)
    phase66g_trend_history_path = _phase68g_dependency_relative(root, PHASE66G_TREND_HISTORY_PATH)
    phase67j_paper_path = _phase68g_dependency_relative(root, PHASE67J_PAPER_PATH)
    phase67j_live_status_path = _phase68g_dependency_relative(root, PHASE67J_LIVE_STATUS_PATH)
    phase66g_decisions_path = _phase68g_dependency_relative(root, PHASE66G_DECISIONS_PATH)
    source_paper_path = _phase68g_dependency_relative(root, PHASE68G_SOURCE_PAPER_PATH)
    source_export_path = _phase68g_dependency_relative(root, PHASE68G_SOURCE_AUTHORITATIVE_EXPORT_PATH)
    output_paper_path = _phase68g_dependency_relative(root, PHASE68G_MAIN_PAPER_PATH)
    output_export_path = _phase68g_dependency_relative(root, PHASE68G_MAIN_AUTHORITATIVE_EXPORT_PATH)

    required_paths = [
        script_path,
        phase66g_paper_path,
        phase66g_live_status_path,
        phase66g_trend_history_path,
        phase67j_paper_path,
        phase67j_live_status_path,
        phase66g_decisions_path,
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Cannot rebuild stale phase68g baseline dependency; required canonical inputs are missing "
            f"(missing={missing})"
        )

    phase66g_paper_last_day = _last_csv_day(phase66g_paper_path, "date")
    phase66g_live_day = _single_csv_value(phase66g_live_status_path, "latest_available_date")
    phase66g_trend_day = _last_csv_day(phase66g_trend_history_path, "trend_calc_date", "date")
    phase67j_paper_last_day = _last_csv_day(phase67j_paper_path, "date")
    phase67j_live_day = _single_csv_value(phase67j_live_status_path, "latest_available_date")
    input_days = {
        "phase66g_paper": phase66g_paper_last_day,
        "phase66g_live_status": phase66g_live_day,
        "phase66g_trend_history": phase66g_trend_day,
        "phase67j_paper": phase67j_paper_last_day,
        "phase67j_live_status": phase67j_live_day,
    }
    stale_inputs = {name: day for name, day in input_days.items() if day != target_closed_day}
    if stale_inputs:
        raise ValueError(
            "Cannot rebuild phase68g baseline dependency because canonical inputs are not fresh "
            f"(target_closed_day={target_closed_day} stale_inputs={stale_inputs})"
        )

    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--baseline-paper",
            str(phase67j_paper_path),
            "--governance-paper",
            str(phase66g_paper_path),
            "--trend-history",
            str(phase66g_trend_history_path),
            "--decisions",
            str(phase66g_decisions_path),
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=True,
    )

    rebuilt_paper_day = _last_csv_day(source_paper_path, "date")
    rebuilt_export_day = _single_csv_value(source_export_path, "latest_available_date")
    if rebuilt_paper_day != target_closed_day or rebuilt_export_day != target_closed_day:
        raise ValueError(
            "phase68g baseline rebuild did not reach the canonical closed day "
            f"(target={target_closed_day} paper={rebuilt_paper_day} export={rebuilt_export_day})"
        )

    output_paper_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_paper_path, output_paper_path)
    shutil.copy2(source_export_path, output_export_path)

    return {
        "status": "rebuilt",
        "target_closed_day": target_closed_day,
        "input_days": input_days,
        "source_paper_path": str(source_paper_path),
        "source_export_path": str(source_export_path),
        "paper_path": str(output_paper_path),
        "summary_path": str(output_export_path),
    }


def _maybe_rebuild_phase68g_baseline_dependency_for_btc(
    *,
    root: Path,
) -> dict[str, Any]:
    baseline_adapter = Phase68g66g1p25xCandidateAdapter()
    try:
        inputs = baseline_adapter.load_inputs(
            root=root,
            materialize_to_canonical_closed_day=True,
        )
    except ValueError as exc:
        if "phase68g baseline dependency materialization would cross a rebalance boundary" not in str(exc):
            raise
        freshness_payload = _read_json_required(_phase68g_dependency_relative(root, APP_FRESHNESS_REPORT_PATH))
        target_closed_day = str(freshness_payload.get("latest_closed_utc_date") or "").strip()
        if not target_closed_day:
            raise ValueError("freshness_report.latest_closed_utc_date is required for phase68g rebuild") from exc
        rebuild = _rebuild_phase68g_baseline_dependency_from_canonical_inputs(
            root=root,
            target_closed_day=target_closed_day,
        )
        verified_inputs = baseline_adapter.load_inputs(
            root=root,
            materialize_to_canonical_closed_day=True,
        )
        if str(verified_inputs["closed_day"]) != target_closed_day:
            raise ValueError(
                "phase68g baseline dependency rebuild verification did not reach the target closed day "
                f"(target={target_closed_day} verified={verified_inputs['closed_day']})"
            ) from exc
        return {
            **rebuild,
            "trigger": "stale_baseline_crossed_rebalance_boundary",
            "verified_closed_day": str(verified_inputs["closed_day"]),
        }

    materialization = inputs.get("paper_materialization")
    if isinstance(materialization, dict) and int(materialization.get("carry_forward_rows_added") or 0) > 0:
        return {
            "status": "carry_forward_materializable",
            "target_closed_day": str(inputs["closed_day"]),
            "source_closed_day": str(inputs.get("source_closed_day") or inputs["closed_day"]),
            "carry_forward_rows_added": int(materialization["carry_forward_rows_added"]),
        }
    return {
        "status": "current",
        "target_closed_day": str(inputs["closed_day"]),
        "source_closed_day": str(inputs.get("source_closed_day") or inputs["closed_day"]),
    }


def _maybe_materialize_btc_persistence_dependency(
    *,
    strategy_model: str,
    root: Path,
) -> dict[str, Any]:
    if strategy_model != ETF_FLOW_CANDIDATE_ID:
        return {"status": "skipped", "reason": "not_etf_flow_live_strategy"}

    freshness_path = root / APP_FRESHNESS_REPORT_PATH.relative_to(ROOT)
    if not freshness_path.exists():
        return {"status": "skipped", "reason": "freshness_report_missing"}
    freshness_payload = _read_json_required(freshness_path)
    target_closed_day = str(freshness_payload.get("latest_closed_utc_date") or "").strip()
    if not target_closed_day:
        return {"status": "skipped", "reason": "freshness_closed_day_missing"}

    paper_path = root / BTC_PERSISTENCE_PAPER_PATH.relative_to(ROOT)
    summary_path = root / BTC_PERSISTENCE_SUMMARY_PATH.relative_to(ROOT)
    paper_last_day = _read_csv_last_value(paper_path, "date")
    summary_last_day = _read_csv_last_value(summary_path, "latest_available_date", "date")
    if paper_last_day == target_closed_day and summary_last_day == target_closed_day:
        return {
            "status": "current",
            "target_closed_day": target_closed_day,
            "paper_last_day": paper_last_day,
            "summary_last_day": summary_last_day,
        }

    phase68g_dependency = _maybe_rebuild_phase68g_baseline_dependency_for_btc(root=root)
    btc_adapter = Phase68gBtcPersistence10dEarlyRisk075Adapter()
    btc_inputs = btc_adapter.load_inputs(root=root)
    btc_timeseries = btc_adapter.build_timeseries(btc_inputs)
    materialized_closed_day = str(btc_inputs["closed_day"])
    materialized_last_day = str(btc_timeseries["date"].iloc[-1])
    if materialized_closed_day != target_closed_day or materialized_last_day != target_closed_day:
        raise ValueError(
            "BTC-persistence dependency materialization did not reach the freshness closed day "
            f"(target={target_closed_day} inputs={materialized_closed_day} timeseries={materialized_last_day})"
        )

    metrics_row = dict(btc_adapter.build_snapshot_metrics(btc_inputs, btc_timeseries))
    metrics_row["model"] = BTC_PERSISTENCE_CANDIDATE_ID
    metrics_row["latest_available_date"] = target_closed_day
    _atomic_write_csv(paper_path, btc_timeseries)
    _write_single_row_csv(summary_path, metrics_row)
    return {
        "status": "materialized",
        "target_closed_day": target_closed_day,
        "previous_paper_last_day": paper_last_day,
        "previous_summary_last_day": summary_last_day,
        "paper_last_day": target_closed_day,
        "summary_last_day": target_closed_day,
        "paper_path": str(paper_path),
        "summary_path": str(summary_path),
        "phase68g_baseline_dependency": phase68g_dependency,
    }


def _build_wait_condition(current_row, metrics: dict[str, Any]) -> dict[str, Any]:
    candidate_asset = str(current_row.get("candidate_asset") or "CASH").strip().upper() or "CASH"
    actual_asset = str(
        current_row.get("actual_held_asset", current_row.get("held_asset")) or "CASH"
    ).strip().upper() or "CASH"
    trend_score = float(current_row["trend_score"])
    buy_threshold = float(current_row["buy_threshold"])
    activation_threshold = float(current_row["trend_activation_threshold"])
    trend_permission_active = bool(current_row.get("trend_permission_active", False))
    effective_market_exposure = float(
        current_row.get("effective_market_exposure", current_row.get("exposure", 0.0))
    )
    model_candidate_exposure = float(current_row.get("model_candidate_exposure", 0.0))
    trigger_threshold = activation_threshold if activation_threshold > 0.0 else buy_threshold
    if bool(current_row["cash_day"]) and bool(current_row["stress_block_day"]):
        return {
            "code": "stress_block_active",
            "text": "The strategy is waiting for the stress block to clear before taking market exposure.",
            "current_values": {
                "stress_block_day": True,
                "candidate_asset": candidate_asset,
                "actual_held_asset": actual_asset,
                "trend_score": trend_score,
                "buy_threshold": buy_threshold,
                "trend_permission_active": trend_permission_active,
            },
            "target_condition": {
                "stress_block_day": False,
            },
        }
    if not trend_permission_active and candidate_asset not in CASH_EQUIVALENT_ASSETS:
        return {
            "code": "trend_confirmation_pending_for_candidate_entry",
            "text": (
                f"{candidate_asset} is the current candidate, but the strategy stays in CASH until trend "
                f"confirmation returns ({trend_score:.4f} vs {trigger_threshold:.4f})."
            ),
            "current_values": {
                "candidate_asset": candidate_asset,
                "actual_held_asset": actual_asset,
                "trend_score": trend_score,
                "buy_threshold": buy_threshold,
                "trend_activation_threshold": activation_threshold,
                "trend_permission_active": trend_permission_active,
                "effective_market_exposure": effective_market_exposure,
                "model_candidate_exposure": model_candidate_exposure,
            },
            "target_condition": {
                "trend_score_min": trigger_threshold,
                "trend_permission_active": True,
                "execution_target_asset": candidate_asset,
                "execution_target_exposure": model_candidate_exposure,
            },
        }
    return {
        "code": "already_in_target_state",
        "text": f"The strategy is already in its current authorized state for {actual_asset}.",
        "current_values": {
            "candidate_asset": candidate_asset,
            "actual_held_asset": actual_asset,
            "current_exposure": effective_market_exposure,
            "trend_permission_active": trend_permission_active,
        },
        "target_condition": {
            "next_rebalance_date": None,
        },
    }


def _build_reason_text_for_adapter(adapter, current_row) -> str:
    if hasattr(adapter, "build_reason_text"):
        return str(adapter.build_reason_text(current_row))
    return build_reason_text(current_row)


def _build_wait_condition_for_adapter(adapter, current_row, metrics: dict[str, Any]) -> dict[str, Any]:
    if hasattr(adapter, "build_wait_condition"):
        return adapter.build_wait_condition(current_row, metrics)
    return _build_wait_condition(current_row, metrics)


def _build_pain_points(timeseries, metrics: dict[str, Any], current_row, wait_condition: dict[str, Any]) -> list[dict[str, Any]]:
    pain_points: list[dict[str, Any]] = []
    total_cost_pct = (
        float(metrics["trading_fees_total_pct"])
        + float(metrics["funding_total_pct"])
        + float(metrics["borrow_cost_total_pct"])
        + float(metrics["slippage_cost_total_pct"])
    )
    if float(metrics["cash_days_pct"]) >= 40.0:
        pain_points.append(
            {
                "code": "cash_drag_elevated",
                "severity": "medium",
                "text": f"Cash participation remains elevated at {float(metrics['cash_days_pct']):.4f}% of history.",
                "metric_value": float(metrics["cash_days_pct"]),
                "metric_unit": "pct",
            }
        )
    if total_cost_pct >= 20.0:
        pain_points.append(
            {
                "code": "lifetime_cost_drag_elevated",
                "severity": "medium",
                "text": f"Lifetime modeled cost drag totals {total_cost_pct:.4f}%.",
                "metric_value": total_cost_pct,
                "metric_unit": "pct",
            }
        )
    if float(timeseries["turnover"].tail(90).sum()) >= 8.0:
        pain_points.append(
            {
                "code": "churn_pressure_visible",
                "severity": "medium",
                "text": "Trailing 90-day turnover is elevated, which can amplify fee drag.",
                "metric_value": float(timeseries["turnover"].tail(90).sum()),
                "metric_unit": "notional_multiple",
            }
        )
    if wait_condition["code"] == "trend_confirmation_pending_for_candidate_entry":
        pain_points.append(
            {
                "code": "trend_entry_not_confirmed",
                "severity": "medium",
                "text": (
                    f"{str(current_row.get('candidate_asset') or 'CASH').strip().upper()} is the preferred "
                    "candidate, but trend confirmation is still missing for market entry."
                ),
                "metric_value": float(current_row["trend_score"]),
                "metric_unit": "trend_score",
            }
        )
    if wait_condition["code"] != "already_in_target_state":
        pain_points.append(
            {
                "code": "active_wait_condition",
                "severity": "low",
                "text": wait_condition["text"],
                "metric_value": None,
                "metric_unit": None,
            }
        )
    if not pain_points:
        pain_points.append(
            {
                "code": "no_material_pain_point_flagged",
                "severity": "low",
                "text": "No dominant production pain point was flagged by the current rule set.",
                "metric_value": None,
                "metric_unit": None,
            }
        )
    return pain_points


def _build_snapshot(
    *,
    generated_at_utc: str,
    adapter: Any,
    inputs: dict[str, Any],
    timeseries,
    build_command: str,
    git_commit: str | None,
) -> dict[str, Any]:
    current_row = timeseries.iloc[-1]
    metrics = adapter.build_snapshot_metrics(inputs, timeseries)
    decision_context = adapter.build_decision_context(timeseries)
    wait_condition = _build_wait_condition_for_adapter(adapter, current_row, metrics)
    candidate_asset = str(current_row["candidate_asset"])
    actual_held_asset = str(current_row["actual_held_asset"])
    effective_market_exposure = round(float(current_row["effective_market_exposure"]), 6)
    model_candidate_exposure = round(float(current_row["model_candidate_exposure"]), 6)
    trend_permission_active = bool(current_row["trend_permission_active"])
    execution_target_asset = str(current_row["execution_target_asset"])
    execution_target_exposure = round(float(current_row["execution_target_exposure"]), 6)
    return {
        "artifact_type": "current_strategy_snapshot",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "strategy_id": PRODUCTION_STRATEGY_ID,
        "strategy_version": adapter.strategy_version,
        "closed_day": inputs["closed_day"],
        "strategy_status": "ready",
        "candidate_asset": candidate_asset,
        "selected_asset": str(current_row["selected_asset"]),
        "actual_held_asset": actual_held_asset,
        "authorized_tradable_asset": actual_held_asset,
        "market_state": str(current_row["market_state"]),
        "current_asset": actual_held_asset,
        "current_exposure": effective_market_exposure,
        "effective_market_exposure": effective_market_exposure,
        "model_candidate_exposure": model_candidate_exposure,
        "trend_permission_active": trend_permission_active,
        "current_regime": str(current_row["regime"]),
        "execution_state": str(current_row["execution_state"]),
        "trend_state": str(current_row["trend_state"]),
        "trend_score": round(float(current_row["trend_score"]), 6),
        "next_rebalance_date": str(inputs["trend_status_row"].get("next_rebalance_date") or "").strip() or None,
        "metrics": metrics,
        "decision_context": decision_context,
        "execution_intent": {
            "target_asset": execution_target_asset,
            "target_exposure": execution_target_exposure,
            "signal_id": (
                f"{PRODUCTION_STRATEGY_ID}::{adapter.strategy_version}::{inputs['closed_day']}::"
                f"target_{execution_target_asset}::candidate_{candidate_asset}"
            ),
            "stale_signal": False,
            "allow_live_order_candidate": bool(
                trend_permission_active and execution_target_exposure > 0.0
            ),
        },
        "source_inputs": adapter.build_source_inputs(inputs),
        "validation": {
            "status": "pending",
            "errors": [],
            "warnings": [],
        },
        "provenance": {
            "adapter_name": adapter.adapter_name,
            "source_strategy_export_paths": [
                meta["path"]
                for meta in adapter.build_source_inputs(inputs)["files"].values()
            ],
            "build_command": build_command,
            "git_commit": git_commit,
            "wait_condition": wait_condition,
        },
    }


def _build_diagnostics(
    *,
    generated_at_utc: str,
    adapter: Any,
    inputs: dict[str, Any],
    timeseries,
    validation: dict[str, Any],
) -> dict[str, Any]:
    metrics = adapter.build_snapshot_metrics(inputs, timeseries)
    current_row = timeseries.iloc[-1]
    wait_condition = _build_wait_condition_for_adapter(adapter, current_row, metrics)
    pain_points = _build_pain_points(timeseries, metrics, current_row, wait_condition)
    diagnostics = adapter.build_diagnostics_payload(
        generated_at_utc=generated_at_utc,
        inputs=inputs,
        timeseries=timeseries,
        validation=validation,
    )
    diagnostics["current_trade_state"] = {
        "is_cash": bool(current_row["cash_day"]),
        "is_waiting": wait_condition["code"] != "already_in_target_state",
        "state_code": str(current_row["market_state"]),
        "candidate_asset": str(current_row["candidate_asset"]),
        "selected_asset": str(current_row["selected_asset"]),
        "actual_held_asset": str(current_row["actual_held_asset"]),
        "authorized_tradable_asset": str(current_row["actual_held_asset"]),
        "effective_market_exposure": round(float(current_row["effective_market_exposure"]), 6),
        "model_candidate_exposure": round(float(current_row["model_candidate_exposure"]), 6),
        "trend_permission_active": bool(current_row["trend_permission_active"]),
        "waiting_reason_code": str(current_row["reason_code"]),
        "waiting_reason_text": _build_reason_text_for_adapter(adapter, current_row),
        "waiting_condition_code": wait_condition["code"],
        "waiting_condition_text": wait_condition["text"],
        "waiting_condition_values": wait_condition["current_values"],
        "target_condition": wait_condition["target_condition"],
        "pain_points": pain_points,
    }
    diagnostics["current_pain_points"] = pain_points
    diagnostics["current_wait_condition"] = wait_condition
    return diagnostics


def _build_manifest(
    *,
    generated_at_utc: str,
    build_command: str,
    git_commit: str | None,
    adapter: Any,
    inputs: dict[str, Any],
    validation: dict[str, Any],
    snapshot_path: Path,
    timeseries_path: Path,
    diagnostics_path: Path,
    quality_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    return {
        "artifact_type": "current_strategy_snapshot_manifest",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "strategy_id": adapter.strategy_id,
        "strategy_version": adapter.strategy_version,
        "adapter_name": adapter.adapter_name,
        "build_command": build_command,
        "git_commit": git_commit,
        "source_inputs": adapter.build_source_inputs(inputs),
        "output_paths": {
            "snapshot": _path_for_manifest(snapshot_path, root=ROOT),
            "timeseries": _path_for_manifest(timeseries_path, root=ROOT),
            "diagnostics": _path_for_manifest(diagnostics_path, root=ROOT),
            "quality": _path_for_manifest(quality_path, root=ROOT),
            "manifest": _path_for_manifest(manifest_path, root=ROOT),
        },
        "validation_status": validation["status"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Production Core v1 current strategy snapshot, timeseries, and diagnostics.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot_path = args.output_dir / SNAPSHOT_PATH.name
    timeseries_path = args.output_dir / TIMESERIES_PATH.name
    diagnostics_path = args.output_dir / DIAGNOSTICS_PATH.name
    quality_path = args.output_dir / QUALITY_PATH.name
    manifest_path = args.output_dir / MANIFEST_PATH.name
    strategy_model = _resolve_current_strategy_model(ROOT)
    dependency_materialization = _maybe_materialize_btc_persistence_dependency(
        strategy_model=strategy_model,
        root=ROOT,
    )
    adapter = _resolve_adapter(strategy_model)
    generated_at_utc = utc_now_iso()
    build_command = " ".join([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    git_commit = _git_commit(ROOT)
    inputs = adapter.load_inputs(root=ROOT)
    timeseries = adapter.build_timeseries(inputs)
    snapshot = _build_snapshot(
        generated_at_utc=generated_at_utc,
        adapter=adapter,
        inputs=inputs,
        timeseries=timeseries,
        build_command=build_command,
        git_commit=git_commit,
    )
    provisional_validation = {
        "status": "passed",
        "errors": [],
        "warnings": [],
        "checks": {},
    }
    diagnostics = _build_diagnostics(
        generated_at_utc=generated_at_utc,
        adapter=adapter,
        inputs=inputs,
        timeseries=timeseries,
        validation=provisional_validation,
    )
    validation = validate_production_payloads(
        snapshot=snapshot,
        timeseries=timeseries,
        diagnostics=diagnostics,
        adapter=adapter,
        inputs=inputs,
    )
    if validation["status"] != "passed":
        raise SystemExit(
            "Production Core v1 build blocked fail-closed:\n- " + "\n- ".join(validation["errors"])
        )

    snapshot["validation"] = {
        "status": validation["status"],
        "errors": list(validation["errors"]),
        "warnings": list(validation["warnings"]),
    }
    diagnostics["validation"] = {
        "status": validation["status"],
        "errors": list(validation["errors"]),
        "warnings": list(validation["warnings"]),
    }

    quality = build_quality_payload(
        validation=validation,
        snapshot_path=snapshot_path,
        timeseries_path=timeseries_path,
        diagnostics_path=diagnostics_path,
    )
    manifest = _build_manifest(
        generated_at_utc=generated_at_utc,
        build_command=build_command,
        git_commit=git_commit,
        adapter=adapter,
        inputs=inputs,
        validation=validation,
        snapshot_path=snapshot_path,
        timeseries_path=timeseries_path,
        diagnostics_path=diagnostics_path,
        quality_path=quality_path,
        manifest_path=manifest_path,
    )

    _atomic_write_json(snapshot_path, snapshot)
    _atomic_write_csv(timeseries_path, timeseries)
    _atomic_write_json(diagnostics_path, diagnostics)
    _atomic_write_json(quality_path, quality)
    _atomic_write_json(manifest_path, manifest)

    print(
        json.dumps(
            {
                "snapshot_path": str(snapshot_path.resolve()),
                "timeseries_path": str(timeseries_path.resolve()),
                "diagnostics_path": str(diagnostics_path.resolve()),
                "quality_path": str(quality_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "strategy_id": adapter.strategy_id,
                "strategy_version": adapter.strategy_version,
                "closed_day": inputs["closed_day"],
                "validation_status": validation["status"],
                "dependency_materialization": dependency_materialization,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
