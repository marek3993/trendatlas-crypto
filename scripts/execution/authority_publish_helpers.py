from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from execution.authority_contract import (
    authority_paths,
    authority_publish_context_from_env,
    build_authority_extra_fields,
    build_stage_history_entry,
    publish_authority_artifacts,
    resolve_authority_publish_mode,
)
from src.market_regime_v1.phase1_time_semantics import (
    ATTEMPT_STATUS_ARTIFACT_TYPE,
    SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
    build_authority_payload,
    normalize_utc_day,
    normalize_utc_timestamp,
)


ROOT = Path(__file__).resolve().parents[2]
APP_PRODUCT_SNAPSHOT_PATH = ROOT / "outputs" / "execution" / "app_snapshot" / "app_product_snapshot.json"
APP_RUNTIME_SNAPSHOT_PATH = ROOT / "outputs" / "execution" / "app_snapshot" / "app_runtime_snapshot.json"
EXPORT_CONTRACT_PATH = ROOT / "source_of_truth" / "export_contract.json"
AUTHORITY_STAGE_NAME = "daily_refresh_app_pipeline"
PIPELINE_SCRIPT_PATH = ROOT / "scripts" / "daily_refresh_app_pipeline.py"


def read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required authority source file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Authority source payload must be an object: {path}")
    return payload


def read_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _path_for_app(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _resolve_export_contract_path_text(raw_path: Any, *, context: str) -> str:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError(f"source_of_truth/export_contract.json missing {context}")
    path = Path(text)
    if not path.is_absolute():
        path = ROOT / path
    return _path_for_app(path)


def _validate_authority_app_product_snapshot(app_product_snapshot: dict[str, Any]) -> None:
    export_contract = read_json_required(EXPORT_CONTRACT_PATH)
    app_export_contract = export_contract.get("app_export_contract")
    if not isinstance(app_export_contract, dict):
        raise ValueError("source_of_truth/export_contract.json missing app_export_contract")

    model_sources = app_export_contract.get("model_sources")
    if not isinstance(model_sources, dict):
        raise ValueError("source_of_truth/export_contract.json missing app_export_contract.model_sources")

    expected_main_strategy_model = str(app_export_contract.get("main_strategy_model") or "").strip()
    if not expected_main_strategy_model:
        raise ValueError("source_of_truth/export_contract.json missing app_export_contract.main_strategy_model")

    main_source_entry = model_sources.get(expected_main_strategy_model)
    if not isinstance(main_source_entry, dict):
        raise ValueError(
            "source_of_truth/export_contract.json missing model_sources entry "
            f"for main strategy '{expected_main_strategy_model}'"
        )

    expected_main_summary_path = _resolve_export_contract_path_text(
        main_source_entry.get("summary_path"),
        context=f"app_export_contract.model_sources.{expected_main_strategy_model}.summary_path",
    )
    expected_main_chart_path = _resolve_export_contract_path_text(
        main_source_entry.get("paper_path"),
        context=f"app_export_contract.model_sources.{expected_main_strategy_model}.paper_path",
    )

    actual_main_strategy_model = str(app_product_snapshot.get("main_strategy_model") or "").strip()
    if actual_main_strategy_model != expected_main_strategy_model:
        raise ValueError(
            "Authority publish blocked: app_product_snapshot.main_strategy_model diverged from "
            "source_of_truth/export_contract.json "
            f"(expected={expected_main_strategy_model} actual={actual_main_strategy_model or 'missing'})"
        )

    main_strategy_metrics = (
        app_product_snapshot.get("main_strategy_metrics")
        if isinstance(app_product_snapshot.get("main_strategy_metrics"), dict)
        else {}
    )
    actual_metrics_model = str(main_strategy_metrics.get("model") or "").strip()
    if actual_metrics_model != expected_main_strategy_model:
        raise ValueError(
            "Authority publish blocked: app_product_snapshot.main_strategy_metrics.model diverged from "
            "source_of_truth/export_contract.json "
            f"(expected={expected_main_strategy_model} actual={actual_metrics_model or 'missing'})"
        )

    chart_source_paths = (
        app_product_snapshot.get("chart_source_paths")
        if isinstance(app_product_snapshot.get("chart_source_paths"), dict)
        else {}
    )
    actual_main_chart_path = str(chart_source_paths.get("main_strategy") or "").strip()
    if actual_main_chart_path != expected_main_chart_path:
        raise ValueError(
            "Authority publish blocked: app_product_snapshot.chart_source_paths.main_strategy diverged from "
            "source_of_truth/export_contract.json "
            f"(expected={expected_main_chart_path} actual={actual_main_chart_path or 'missing'})"
        )

    source_metadata = (
        app_product_snapshot.get("source_metadata")
        if isinstance(app_product_snapshot.get("source_metadata"), dict)
        else {}
    )
    metrics_metadata = (
        source_metadata.get("main_strategy_metrics")
        if isinstance(source_metadata.get("main_strategy_metrics"), dict)
        else {}
    )
    actual_main_summary_path = str(metrics_metadata.get("path") or "").strip()
    if actual_main_summary_path != expected_main_summary_path:
        raise ValueError(
            "Authority publish blocked: app_product_snapshot.source_metadata.main_strategy_metrics.path diverged from "
            "source_of_truth/export_contract.json "
            f"(expected={expected_main_summary_path} actual={actual_main_summary_path or 'missing'})"
        )


def build_authority_publish_state(
    *,
    run_id: str,
    run_dir: Path,
    refresh_started_at_utc: str,
    target_closed_day_utc: str,
    latest_available_closed_utc_day: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    paths = authority_paths(ROOT)
    context = authority_publish_context_from_env(env)
    normalized_target_day = normalize_utc_day(
        target_closed_day_utc,
        field_name="target_closed_day_utc",
    )
    normalized_latest_available_day = normalize_utc_day(
        latest_available_closed_utc_day or normalized_target_day,
        field_name="latest_available_closed_utc_day",
    )
    authority_mode = resolve_authority_publish_mode(env)
    return {
        "run_id": str(run_id).strip(),
        "run_dir": str(run_dir),
        "source_manifest_path": str((run_dir / "app_refresh_pipeline_manifest.json").resolve()),
        "refresh_started_at_utc": normalize_utc_timestamp(
            refresh_started_at_utc,
            field_name="refresh_started_at_utc",
        ),
        "target_closed_day_utc": normalized_target_day,
        "latest_available_closed_utc_day": normalized_latest_available_day,
        "authority_mode": authority_mode,
        "authority_role": authority_mode,
        "authority_publish_enabled": bool(context.get("authority_publish_enabled")),
        "automatic_producer_id": str(context.get("automatic_producer_id") or "").strip().lower(),
        "latest_attempt_status_path": str(paths["latest_attempt_status"]),
        "latest_successful_snapshot_path": str(paths["latest_successful_snapshot"]),
        "pipeline_script_path": str(PIPELINE_SCRIPT_PATH.resolve()),
        "stage_history": [],
    }


def build_authority_manifest_stub(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mode": state["authority_mode"],
        "published": False,
        "successful_snapshot_written": False,
        "latest_attempt_status_path": state["latest_attempt_status_path"],
        "latest_successful_snapshot_path": state["latest_successful_snapshot_path"],
        "status": "NOT_RUN",
        "reason": "strategy_refresh_chain_not_completed",
        "last_publish_result": None,
    }


def _build_extra_fields(
    state: Mapping[str, Any],
    *,
    generated_at_utc: str,
    attempt_stage_status: str,
    stage_history: list[dict[str, Any]],
    app_product_snapshot: dict[str, Any] | None = None,
    app_runtime_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_authority_extra_fields(
        run_id=str(state["run_id"]),
        source_manifest_path=str(state["source_manifest_path"]),
        authority_role=str(state["authority_role"]),
        automatic_producer_id=str(state["automatic_producer_id"]),
        latest_successful_snapshot_path=str(state["latest_successful_snapshot_path"]),
        latest_attempt_status_path=str(state["latest_attempt_status_path"]),
        generated_at_utc=generated_at_utc,
        attempt_stage=AUTHORITY_STAGE_NAME,
        attempt_stage_status=attempt_stage_status,
        stage_history=stage_history,
        app_product_snapshot=app_product_snapshot,
        app_runtime_snapshot=app_runtime_snapshot,
    )


def publish_authority_refresh_started(
    state: dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    stage_history = [
        build_stage_history_entry(
            AUTHORITY_STAGE_NAME,
            "running",
            started_at_utc=state["refresh_started_at_utc"],
            finished_at_utc=None,
            script_path=state["pipeline_script_path"],
            non_authoritative_support_only=state["authority_mode"] != "pi_only_authoritative_producer",
        )
    ]
    state["stage_history"] = stage_history

    attempt_payload = build_authority_payload(
        artifact_type=ATTEMPT_STATUS_ARTIFACT_TYPE,
        target_closed_day_utc=state["target_closed_day_utc"],
        latest_available_closed_utc_day=state["latest_available_closed_utc_day"],
        refresh_started_at_utc=state["refresh_started_at_utc"],
        refresh_finished_at_utc=None,
        latest_authoritative_attempt_status="in_progress",
        latest_authoritative_attempt_error=None,
        strategy_artifact_closed_day_utc=None,
        extra_fields=_build_extra_fields(
            state,
            generated_at_utc=state["refresh_started_at_utc"],
            attempt_stage_status="running",
            stage_history=stage_history,
        ),
    )
    return publish_authority_artifacts(
        attempt_payload,
        None,
        root=ROOT,
        env=env,
    )


def publish_authority_refresh_success(
    state: dict[str, Any],
    *,
    refresh_finished_at_utc: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    app_product_snapshot = read_json_required(APP_PRODUCT_SNAPSHOT_PATH)
    app_runtime_snapshot = read_json_required(APP_RUNTIME_SNAPSHOT_PATH)
    _validate_authority_app_product_snapshot(app_product_snapshot)
    normalized_finished_at_utc = normalize_utc_timestamp(
        refresh_finished_at_utc,
        field_name="refresh_finished_at_utc",
    )

    latest_available_closed_utc_day = normalize_utc_day(
        app_runtime_snapshot.get("latest_available_closed_utc_date")
        or app_product_snapshot.get("freshness_target_closed_day")
        or state["latest_available_closed_utc_day"],
        field_name="latest_available_closed_utc_day",
    )
    strategy_artifact_closed_day_utc = normalize_utc_day(
        app_product_snapshot.get("strategy_last_closed_day")
        or app_runtime_snapshot.get("latest_strategy_artifact_date"),
        field_name="strategy_artifact_closed_day_utc",
    )
    state["latest_available_closed_utc_day"] = latest_available_closed_utc_day
    stage_history = list(state.get("stage_history") or [])
    stage_history.append(
        build_stage_history_entry(
            AUTHORITY_STAGE_NAME,
            "success",
            started_at_utc=state["refresh_started_at_utc"],
            finished_at_utc=normalized_finished_at_utc,
            script_path=state["pipeline_script_path"],
            non_authoritative_support_only=state["authority_mode"] != "pi_only_authoritative_producer",
        )
    )
    state["stage_history"] = stage_history

    extra_fields = _build_extra_fields(
        state,
        generated_at_utc=normalized_finished_at_utc,
        attempt_stage_status="success",
        stage_history=stage_history,
        app_product_snapshot=app_product_snapshot,
        app_runtime_snapshot=app_runtime_snapshot,
    )
    attempt_payload = build_authority_payload(
        artifact_type=ATTEMPT_STATUS_ARTIFACT_TYPE,
        target_closed_day_utc=state["target_closed_day_utc"],
        latest_available_closed_utc_day=latest_available_closed_utc_day,
        refresh_started_at_utc=state["refresh_started_at_utc"],
        refresh_finished_at_utc=normalized_finished_at_utc,
        latest_authoritative_attempt_status="success",
        latest_authoritative_attempt_error=None,
        strategy_artifact_closed_day_utc=strategy_artifact_closed_day_utc,
        extra_fields=extra_fields,
    )
    success_payload = build_authority_payload(
        artifact_type=SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
        target_closed_day_utc=state["target_closed_day_utc"],
        latest_available_closed_utc_day=latest_available_closed_utc_day,
        refresh_started_at_utc=state["refresh_started_at_utc"],
        refresh_finished_at_utc=normalized_finished_at_utc,
        latest_authoritative_attempt_status="success",
        latest_authoritative_attempt_error=None,
        strategy_artifact_closed_day_utc=strategy_artifact_closed_day_utc,
        extra_fields=extra_fields,
    )
    return publish_authority_artifacts(
        attempt_payload,
        success_payload,
        root=ROOT,
        env=env,
    )


def publish_authority_refresh_failure(
    state: dict[str, Any],
    *,
    refresh_finished_at_utc: str,
    error: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    app_product_snapshot = read_json_optional(APP_PRODUCT_SNAPSHOT_PATH)
    app_runtime_snapshot = read_json_optional(APP_RUNTIME_SNAPSHOT_PATH)
    normalized_finished_at_utc = normalize_utc_timestamp(
        refresh_finished_at_utc,
        field_name="refresh_finished_at_utc",
    )

    latest_available_closed_utc_day = normalize_utc_day(
        app_runtime_snapshot.get("latest_available_closed_utc_date")
        or app_product_snapshot.get("freshness_target_closed_day")
        or state["latest_available_closed_utc_day"],
        field_name="latest_available_closed_utc_day",
    )
    strategy_artifact_closed_day_utc = (
        normalize_utc_day(
            app_product_snapshot.get("strategy_last_closed_day")
            or app_runtime_snapshot.get("latest_strategy_artifact_date"),
            field_name="strategy_artifact_closed_day_utc",
            allow_none=True,
        )
        if app_product_snapshot or app_runtime_snapshot
        else None
    )
    state["latest_available_closed_utc_day"] = latest_available_closed_utc_day
    stage_history = list(state.get("stage_history") or [])
    stage_history.append(
        build_stage_history_entry(
            AUTHORITY_STAGE_NAME,
            "failed",
            started_at_utc=state["refresh_started_at_utc"],
            finished_at_utc=normalized_finished_at_utc,
            script_path=state["pipeline_script_path"],
            error=error,
            non_authoritative_support_only=state["authority_mode"] != "pi_only_authoritative_producer",
        )
    )
    state["stage_history"] = stage_history

    attempt_payload = build_authority_payload(
        artifact_type=ATTEMPT_STATUS_ARTIFACT_TYPE,
        target_closed_day_utc=state["target_closed_day_utc"],
        latest_available_closed_utc_day=latest_available_closed_utc_day,
        refresh_started_at_utc=state["refresh_started_at_utc"],
        refresh_finished_at_utc=normalized_finished_at_utc,
        latest_authoritative_attempt_status="failed",
        latest_authoritative_attempt_error=error,
        strategy_artifact_closed_day_utc=strategy_artifact_closed_day_utc,
        extra_fields=_build_extra_fields(
            state,
            generated_at_utc=normalized_finished_at_utc,
            attempt_stage_status="failed",
            stage_history=stage_history,
            app_product_snapshot=app_product_snapshot or None,
            app_runtime_snapshot=app_runtime_snapshot or None,
        ),
    )
    return publish_authority_artifacts(
        attempt_payload,
        None,
        root=ROOT,
        env=env,
    )
