from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_adapters.phase68g_66g_1p25x_candidate_adapter import (
    ADAPTER_NAME,
    MANIFEST_SCHEMA_VERSION,
    PRODUCTION_STRATEGY_ID,
    ROOT,
    SNAPSHOT_SCHEMA_VERSION,
    SOURCE_STRATEGY_VERSION,
    Phase68g66g1p25xCandidateAdapter,
    build_reason_text,
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


def _resolve_adapter(strategy_model: str) -> Phase68g66g1p25xCandidateAdapter:
    if strategy_model != SOURCE_STRATEGY_VERSION:
        raise ValueError(
            "No Production Core v1 adapter is registered for the current official strategy "
            f"(strategy_model={strategy_model})"
        )
    return Phase68g66g1p25xCandidateAdapter()


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


def _build_wait_condition(current_row, metrics: dict[str, Any]) -> dict[str, Any]:
    held_asset = str(current_row["held_asset"])
    trend_score = float(current_row["trend_score"])
    buy_threshold = float(current_row["buy_threshold"])
    activation_threshold = float(current_row["trend_activation_threshold"])
    if bool(current_row["cash_day"]) and bool(current_row["stress_block_day"]):
        return {
            "code": "stress_block_active",
            "text": "The strategy is waiting for the stress block to clear before taking market exposure.",
            "current_values": {
                "stress_block_day": True,
                "trend_score": trend_score,
                "buy_threshold": buy_threshold,
            },
            "target_condition": {
                "stress_block_day": False,
            },
        }
    if bool(current_row["cash_day"]):
        return {
            "code": "trend_score_below_buy_threshold",
            "text": (
                "The strategy is waiting for the trend gate to move back above the buy threshold "
                f"before leaving CASH ({trend_score:.4f} vs {buy_threshold:.4f})."
            ),
            "current_values": {
                "trend_score": trend_score,
                "buy_threshold": buy_threshold,
            },
            "target_condition": {
                "trend_score_min": buy_threshold,
            },
        }
    if str(current_row["leverage_state_reason"]).strip().lower() == "trend_gate":
        return {
            "code": "trend_score_below_leverage_activation",
            "text": (
                f"The strategy is holding {held_asset} but waiting for the trend score to reach the leverage "
                f"activation threshold before increasing exposure ({trend_score:.4f} vs {activation_threshold:.4f})."
            ),
            "current_values": {
                "held_asset": held_asset,
                "trend_score": trend_score,
                "trend_activation_threshold": activation_threshold,
                "current_exposure": float(current_row["exposure"]),
            },
            "target_condition": {
                "trend_score_min": activation_threshold,
            },
        }
    return {
        "code": "already_in_target_state",
        "text": f"The strategy is already in its current target state for {held_asset}.",
        "current_values": {
            "held_asset": held_asset,
            "current_exposure": float(current_row["exposure"]),
        },
        "target_condition": {
            "next_rebalance_date": None,
        },
    }


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
    adapter: Phase68g66g1p25xCandidateAdapter,
    inputs: dict[str, Any],
    timeseries,
    build_command: str,
    git_commit: str | None,
) -> dict[str, Any]:
    current_row = timeseries.iloc[-1]
    metrics = adapter.build_snapshot_metrics(inputs, timeseries)
    decision_context = adapter.build_decision_context(timeseries)
    wait_condition = _build_wait_condition(current_row, metrics)
    return {
        "artifact_type": "current_strategy_snapshot",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "strategy_id": PRODUCTION_STRATEGY_ID,
        "strategy_version": SOURCE_STRATEGY_VERSION,
        "closed_day": inputs["closed_day"],
        "strategy_status": "ready",
        "current_asset": str(current_row["held_asset"]),
        "current_exposure": round(float(current_row["exposure"]), 6),
        "current_regime": str(current_row["regime"]),
        "execution_state": str(current_row["execution_state"]),
        "trend_state": str(current_row["trend_state"]),
        "trend_score": round(float(current_row["trend_score"]), 6),
        "next_rebalance_date": str(inputs["trend_status_row"].get("next_rebalance_date") or "").strip() or None,
        "metrics": metrics,
        "decision_context": decision_context,
        "execution_intent": {
            "target_asset": str(current_row["held_asset"]),
            "target_exposure": round(float(current_row["exposure"]), 6),
            "signal_id": (
                f"{PRODUCTION_STRATEGY_ID}::{SOURCE_STRATEGY_VERSION}::{inputs['closed_day']}::"
                f"{str(current_row['held_asset'])}"
            ),
            "stale_signal": False,
            "allow_live_order_candidate": True,
        },
        "source_inputs": adapter.build_source_inputs(inputs),
        "validation": {
            "status": "pending",
            "errors": [],
            "warnings": [],
        },
        "provenance": {
            "adapter_name": ADAPTER_NAME,
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
    adapter: Phase68g66g1p25xCandidateAdapter,
    inputs: dict[str, Any],
    timeseries,
    validation: dict[str, Any],
) -> dict[str, Any]:
    metrics = adapter.build_snapshot_metrics(inputs, timeseries)
    current_row = timeseries.iloc[-1]
    wait_condition = _build_wait_condition(current_row, metrics)
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
        "waiting_reason_code": str(current_row["reason_code"]),
        "waiting_reason_text": build_reason_text(current_row),
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
    adapter: Phase68g66g1p25xCandidateAdapter,
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
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
