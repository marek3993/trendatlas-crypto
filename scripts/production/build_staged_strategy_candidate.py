from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_adapters.phase68g_etf_flow_impulse_early_risk_cooldown_15_adapter import (
    CANDIDATE_ID as ETF_CANDIDATE_ID,
    MANIFEST_SCHEMA_VERSION,
    ROOT,
    SNAPSHOT_SCHEMA_VERSION,
    Phase68gEtfFlowImpulseEarlyRiskCooldown15Adapter,
    build_candidate_reason_text,
    capture_protected_state,
    expected_truth_contract_state,
    read_truth_contract_state,
    utc_now_iso,
)
from scripts.production.strategy_adapters.phase68g_btc_persistence_10d_early_risk_075_adapter import (
    CANDIDATE_ID as BTC_PERSISTENCE_CANDIDATE_ID,
    Phase68gBtcPersistence10dEarlyRisk075StagedAdapter,
    build_reason_text as build_btc_persistence_candidate_reason_text,
    capture_protected_state as capture_btc_persistence_protected_state,
    expected_truth_contract_state as expected_btc_persistence_truth_contract_state,
    read_truth_contract_state as read_btc_persistence_truth_contract_state,
    utc_now_iso as utc_now_iso_btc_persistence,
)
from scripts.production.validate_staged_strategy_candidate import (
    build_quality_payload,
    validate_staged_payloads,
)


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "production" / "candidates" / ETF_CANDIDATE_ID
SNAPSHOT_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_snapshot.json"
TIMESERIES_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_timeseries.csv"
DIAGNOSTICS_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_diagnostics.json"
QUALITY_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_snapshot.quality.json"
MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "candidate_strategy_snapshot.manifest.json"
COMPARE_JSON_PATH = DEFAULT_OUTPUT_DIR / "compare_vs_current_production_core.json"
COMPARE_CSV_PATH = DEFAULT_OUTPUT_DIR / "compare_vs_current_production_core.csv"


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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def _atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temp_path, index=False)
    temp_path.replace(path)


def _path_for_manifest(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _resolve_candidate_adapter(candidate_id: str):
    if candidate_id == ETF_CANDIDATE_ID:
        return Phase68gEtfFlowImpulseEarlyRiskCooldown15Adapter()
    if candidate_id == BTC_PERSISTENCE_CANDIDATE_ID:
        return Phase68gBtcPersistence10dEarlyRisk075StagedAdapter()
    raise ValueError(f"Unsupported candidate: {candidate_id!r}")


def _candidate_reason_text(adapter, current_row) -> str:
    if hasattr(adapter, "build_candidate_reason_text"):
        return str(adapter.build_candidate_reason_text(current_row))
    return build_candidate_reason_text(current_row)


def _capture_protected_state(candidate_id: str):
    if candidate_id == BTC_PERSISTENCE_CANDIDATE_ID:
        return capture_btc_persistence_protected_state(root=ROOT)
    return capture_protected_state(root=ROOT)


def _expected_truth_contract_state(candidate_id: str) -> dict[str, str]:
    if candidate_id == BTC_PERSISTENCE_CANDIDATE_ID:
        return expected_btc_persistence_truth_contract_state()
    return expected_truth_contract_state()


def _read_truth_contract_state(candidate_id: str) -> dict[str, Any]:
    if candidate_id == BTC_PERSISTENCE_CANDIDATE_ID:
        return read_btc_persistence_truth_contract_state(root=ROOT)
    return read_truth_contract_state(root=ROOT)


def _utc_now_iso(candidate_id: str) -> str:
    if candidate_id == BTC_PERSISTENCE_CANDIDATE_ID:
        return utc_now_iso_btc_persistence()
    return utc_now_iso()


def _build_snapshot(
    *,
    generated_at_utc: str,
    adapter,
    inputs: dict[str, Any],
    timeseries: pd.DataFrame,
    build_command: str,
    git_commit: str | None,
) -> dict[str, Any]:
    current_row = timeseries.iloc[-1]
    metrics = adapter.build_snapshot_metrics(inputs)
    baseline_closed_day = (
        inputs.get("baseline_closed_day")
        or inputs.get("current_closed_day")
        or inputs.get("candidate_compare_closed_day")
        or str(current_row["date"])
    )
    return {
        "artifact_type": "staged_strategy_candidate_snapshot",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "candidate_id": adapter.candidate_id,
        "candidate_label": getattr(adapter, "candidate_label", adapter.candidate_id),
        "base_strategy_version": adapter.base_strategy_version,
        "status": "staged_candidate",
        "live_truth": False,
        "app_truth": False,
        "execution_truth": False,
        "dev_only_source_lineage": True,
        "non_authoritative_research_input": True,
        "official_truth": False,
        "strategy_advancement": False,
        "closed_day": str(current_row["date"]),
        "compare_universe": {
            "start_date": str(timeseries["date"].iloc[0]),
            "end_date": str(timeseries["date"].iloc[-1]),
            "row_count": int(len(timeseries)),
            "baseline_closed_day": baseline_closed_day,
            "baseline_source_path": "outputs/production/current_strategy_timeseries.csv",
        },
        "current_state": {
            "candidate_asset": str(current_row["candidate_asset"]),
            "selected_asset": str(current_row["selected_asset"]),
            "actual_held_asset": str(current_row["actual_held_asset"]),
            "authorized_tradable_asset": str(current_row["authorized_tradable_asset"]),
            "effective_market_exposure": round(float(current_row["effective_market_exposure"]), 6),
            "model_candidate_exposure": round(float(current_row["model_candidate_exposure"]), 6),
            "trend_permission_active": bool(current_row["trend_permission_active"]),
            "execution_target_asset": str(current_row["execution_target_asset"]),
            "execution_target_exposure": round(float(current_row["execution_target_exposure"]), 6),
            "reason_code": str(current_row["reason_code"]),
            "reason_text": _candidate_reason_text(adapter, current_row),
            "early_risk_active": bool(current_row["early_risk_active"]),
            "cooldown_active": bool(current_row.get("cooldown_active", False)),
            "cooldown_blocked_entry": bool(current_row.get("cooldown_blocked_entry", False)),
        },
        "baseline_current_state": {
            "candidate_asset": str(current_row["baseline_candidate_asset"]),
            "selected_asset": str(current_row["baseline_selected_asset"]),
            "actual_held_asset": str(current_row["baseline_actual_held_asset"]),
            "effective_market_exposure": round(float(current_row["baseline_effective_market_exposure"]), 6),
            "trend_permission_active": bool(current_row["baseline_trend_permission_active"]),
            "reason_code": str(current_row["baseline_reason_code"]),
        },
        "metrics": metrics,
        "decision_context": adapter.build_decision_context(timeseries),
        "source_inputs": adapter.build_source_inputs(inputs),
        "validation": {
            "status": "pending",
            "errors": [],
            "warnings": [],
        },
        "provenance": {
            "adapter_name": adapter.adapter_name,
            "build_command": build_command,
            "git_commit": git_commit,
            "baseline_source_path": "outputs/production/current_strategy_timeseries.csv",
            "source_paths": [
                meta["path"]
                for meta in adapter.build_source_inputs(inputs)["files"].values()
                if isinstance(meta, dict) and "path" in meta
            ],
        },
    }


def _build_manifest(
    *,
    generated_at_utc: str,
    build_command: str,
    git_commit: str | None,
    adapter,
    inputs: dict[str, Any],
    validation: dict[str, Any],
    snapshot_path: Path,
    timeseries_path: Path,
    diagnostics_path: Path,
    quality_path: Path,
    manifest_path: Path,
    compare_json_path: Path,
    compare_csv_path: Path,
    protected_before: dict[str, Any],
    protected_after: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_type": "staged_strategy_candidate_snapshot_manifest",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "candidate_id": adapter.candidate_id,
        "base_strategy_version": adapter.base_strategy_version,
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
            "compare_json": _path_for_manifest(compare_json_path, root=ROOT),
            "compare_csv": _path_for_manifest(compare_csv_path, root=ROOT),
        },
        "protected_paths_before": protected_before,
        "protected_paths_after": protected_after,
        "truth_contract_expectations": _expected_truth_contract_state(adapter.candidate_id),
        "truth_contract_current": _read_truth_contract_state(adapter.candidate_id),
        "validation_status": validation["status"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the staged Production Core candidate bundle.")
    parser.add_argument("--candidate", default=ETF_CANDIDATE_ID)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    adapter = _resolve_candidate_adapter(args.candidate)
    output_dir = args.output_dir.resolve()
    if output_dir == DEFAULT_OUTPUT_DIR.resolve() and args.candidate != ETF_CANDIDATE_ID:
        output_dir = (ROOT / "outputs" / "production" / "candidates" / args.candidate).resolve()
    snapshot_path = output_dir / SNAPSHOT_PATH.name
    timeseries_path = output_dir / TIMESERIES_PATH.name
    diagnostics_path = output_dir / DIAGNOSTICS_PATH.name
    quality_path = output_dir / QUALITY_PATH.name
    manifest_path = output_dir / MANIFEST_PATH.name
    compare_json_path = output_dir / COMPARE_JSON_PATH.name
    compare_csv_path = output_dir / COMPARE_CSV_PATH.name

    generated_at_utc = _utc_now_iso(adapter.candidate_id)
    build_command = " ".join([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    git_commit = _git_commit(ROOT)
    protected_before = _capture_protected_state(adapter.candidate_id)
    inputs = adapter.load_inputs(root=ROOT)
    timeseries = adapter.build_candidate_timeseries(inputs)
    compare_payload, compare_rows = adapter.build_compare_payload(inputs)

    provisional_validation = {
        "status": "pending",
        "errors": [],
        "warnings": [],
        "checks": {},
    }
    diagnostics = adapter.build_diagnostics_payload(
        generated_at_utc=generated_at_utc,
        inputs=inputs,
        timeseries=timeseries,
        compare_payload=compare_payload,
        validation=provisional_validation,
    )
    snapshot = _build_snapshot(
        generated_at_utc=generated_at_utc,
        adapter=adapter,
        inputs=inputs,
        timeseries=timeseries,
        build_command=build_command,
        git_commit=git_commit,
    )

    _atomic_write_json(snapshot_path, snapshot)
    _atomic_write_csv(timeseries_path, timeseries)
    _atomic_write_json(diagnostics_path, diagnostics)
    _atomic_write_json(compare_json_path, compare_payload)
    _atomic_write_csv(compare_csv_path, pd.DataFrame(compare_rows))

    protected_after = _capture_protected_state(adapter.candidate_id)
    temp_manifest = _build_manifest(
        generated_at_utc=generated_at_utc,
        build_command=build_command,
        git_commit=git_commit,
        adapter=adapter,
        inputs=inputs,
        validation=provisional_validation,
        snapshot_path=snapshot_path,
        timeseries_path=timeseries_path,
        diagnostics_path=diagnostics_path,
        quality_path=quality_path,
        manifest_path=manifest_path,
        compare_json_path=compare_json_path,
        compare_csv_path=compare_csv_path,
        protected_before=protected_before,
        protected_after=protected_after,
    )

    validation = validate_staged_payloads(
        snapshot=snapshot,
        timeseries=timeseries,
        diagnostics=diagnostics,
        compare_payload=compare_payload,
        compare_rows=pd.DataFrame(compare_rows),
        manifest=temp_manifest,
        adapter=adapter,
        inputs=inputs,
        protected_before=protected_before,
        protected_after=protected_after,
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
        compare_json_path=compare_json_path,
        compare_csv_path=compare_csv_path,
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
        compare_json_path=compare_json_path,
        compare_csv_path=compare_csv_path,
        protected_before=protected_before,
        protected_after=protected_after,
    )

    _atomic_write_json(snapshot_path, snapshot)
    _atomic_write_json(diagnostics_path, diagnostics)
    _atomic_write_json(quality_path, quality)
    _atomic_write_json(manifest_path, manifest)

    print(
        json.dumps(
            {
                "candidate_id": adapter.candidate_id,
                "snapshot_path": str(snapshot_path.resolve()),
                "timeseries_path": str(timeseries_path.resolve()),
                "diagnostics_path": str(diagnostics_path.resolve()),
                "quality_path": str(quality_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "compare_json_path": str(compare_json_path.resolve()),
                "compare_csv_path": str(compare_csv_path.resolve()),
                "closed_day": snapshot["closed_day"],
                "validation_status": validation["status"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if validation["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
