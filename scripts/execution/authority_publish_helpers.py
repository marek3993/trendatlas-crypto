from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
from scripts.execution.current_strategy_root_contract import (
    load_current_main_strategy_root_contract,
    validate_product_snapshot_current_strategy_contract,
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


def _validate_authority_app_product_snapshot(app_product_snapshot: dict[str, Any]) -> dict[str, Any]:
    current_strategy_contract = load_current_main_strategy_root_contract()
    validate_product_snapshot_current_strategy_contract(
        app_product_snapshot,
        current_strategy_contract,
        context="Authority publish blocked:",
    )
    return current_strategy_contract


def _payload_mapping(
    value: Any,
    *,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Authority publish blocked: {field_name} must be an object")
    return value


def _require_source_modified_during_run(
    source_metadata: Mapping[str, Any],
    *,
    field_name: str,
    refresh_started_at_utc: str,
) -> None:
    modified_utc = normalize_utc_timestamp(
        source_metadata.get("modified_utc"),
        field_name=f"{field_name}.modified_utc",
    )
    if _parse_utc_datetime(modified_utc, field_name=f"{field_name}.modified_utc") < _parse_utc_datetime(
        refresh_started_at_utc,
        field_name="refresh_started_at_utc",
    ):
        raise ValueError(
            "Authority publish blocked: strategy source was not regenerated during this authoritative run "
            f"({field_name}.modified_utc={modified_utc} refresh_started_at_utc={refresh_started_at_utc})"
        )


def _validate_success_strategy_source_of_truth(
    state: Mapping[str, Any],
    app_product_snapshot: dict[str, Any],
    app_runtime_snapshot: Mapping[str, Any],
    current_strategy_contract: Mapping[str, Any],
) -> dict[str, str]:
    refresh_started_at_utc = normalize_utc_timestamp(
        state.get("refresh_started_at_utc"),
        field_name="refresh_started_at_utc",
    )
    target_closed_day_utc = normalize_utc_day(
        state.get("target_closed_day_utc"),
        field_name="target_closed_day_utc",
    )
    latest_available_closed_utc_day = normalize_utc_day(
        app_runtime_snapshot.get("latest_available_closed_utc_date")
        or app_product_snapshot.get("freshness_target_closed_day")
        or state.get("latest_available_closed_utc_day"),
        field_name="latest_available_closed_utc_day",
    )
    strategy_artifact_closed_day_utc = normalize_utc_day(
        app_product_snapshot.get("strategy_last_closed_day"),
        field_name="app_product_snapshot.strategy_last_closed_day",
    )
    live_public_state = _payload_mapping(
        app_product_snapshot.get("live_public_state"),
        field_name="app_product_snapshot.live_public_state",
    )
    live_public_state_date = normalize_utc_day(
        live_public_state.get("date"),
        field_name="app_product_snapshot.live_public_state.date",
    )
    runtime_strategy_artifact_closed_day_utc = normalize_utc_day(
        app_runtime_snapshot.get("latest_strategy_artifact_date"),
        field_name="app_runtime_snapshot.latest_strategy_artifact_date",
    )

    if latest_available_closed_utc_day != target_closed_day_utc:
        raise ValueError(
            "Authority publish blocked: authoritative run target day is not the same as the latest available closed day "
            f"(target_closed_day_utc={target_closed_day_utc} "
            f"latest_available_closed_utc_day={latest_available_closed_utc_day})"
        )

    expected_day_fields = {
        "app_product_snapshot.strategy_last_closed_day": strategy_artifact_closed_day_utc,
        "app_product_snapshot.live_public_state.date": live_public_state_date,
        "app_runtime_snapshot.latest_strategy_artifact_date": runtime_strategy_artifact_closed_day_utc,
    }
    for field_name, value in expected_day_fields.items():
        if value != target_closed_day_utc:
            raise ValueError(
                "Authority publish blocked: strategy truth does not come from the just-finished authoritative run "
                f"({field_name}={value} target_closed_day_utc={target_closed_day_utc})"
            )

    main_strategy_model = str(app_product_snapshot.get("main_strategy_model") or "").strip()
    if not main_strategy_model:
        raise ValueError("Authority publish blocked: app_product_snapshot.main_strategy_model is missing")
    main_strategy_metrics = _payload_mapping(
        app_product_snapshot.get("main_strategy_metrics"),
        field_name="app_product_snapshot.main_strategy_metrics",
    )
    metrics_model = str(main_strategy_metrics.get("model") or "").strip()
    if metrics_model != main_strategy_model:
        raise ValueError(
            "Authority publish blocked: app_product_snapshot.main_strategy_metrics.model diverged from main_strategy_model "
            f"(expected={main_strategy_model} actual={metrics_model or 'missing'})"
        )

    expected_main_strategy_metrics_path = str(
        current_strategy_contract["canonical_metrics_source_path"]
    ).strip()
    expected_main_strategy_paper_path = str(
        current_strategy_contract["canonical_paper_source_path"]
    ).strip()

    chart_source_paths = _payload_mapping(
        app_product_snapshot.get("chart_source_paths"),
        field_name="app_product_snapshot.chart_source_paths",
    )
    main_strategy_chart_path = str(chart_source_paths.get("main_strategy") or "").strip()
    if not main_strategy_chart_path:
        raise ValueError(
            "Authority publish blocked: app_product_snapshot.chart_source_paths.main_strategy is missing"
        )
    if main_strategy_chart_path != expected_main_strategy_paper_path:
        raise ValueError(
            "Authority publish blocked: app_product_snapshot.chart_source_paths.main_strategy diverged from "
            "the current main strategy root contract "
            f"(expected={expected_main_strategy_paper_path} actual={main_strategy_chart_path})"
        )

    source_metadata = _payload_mapping(
        app_product_snapshot.get("source_metadata"),
        field_name="app_product_snapshot.source_metadata",
    )
    main_strategy_metrics_source = _payload_mapping(
        source_metadata.get("main_strategy_metrics"),
        field_name="app_product_snapshot.source_metadata.main_strategy_metrics",
    )
    strategy_last_closed_day_source = _payload_mapping(
        source_metadata.get("strategy_last_closed_day"),
        field_name="app_product_snapshot.source_metadata.strategy_last_closed_day",
    )
    live_public_state_source = _payload_mapping(
        source_metadata.get("live_public_state"),
        field_name="app_product_snapshot.source_metadata.live_public_state",
    )

    strategy_last_closed_day_source_path = str(
        strategy_last_closed_day_source.get("path") or ""
    ).strip()
    live_public_state_source_path = str(live_public_state_source.get("path") or "").strip()
    main_strategy_metrics_source_path = str(main_strategy_metrics_source.get("path") or "").strip()
    if main_strategy_metrics_source_path != expected_main_strategy_metrics_path:
        raise ValueError(
            "Authority publish blocked: app_product_snapshot.source_metadata.main_strategy_metrics.path diverged from "
            "the current main strategy root contract "
            f"(expected={expected_main_strategy_metrics_path} actual={main_strategy_metrics_source_path or 'missing'})"
        )
    if strategy_last_closed_day_source_path != main_strategy_chart_path:
        raise ValueError(
            "Authority publish blocked: strategy_last_closed_day path diverged from chart_source_paths.main_strategy "
            f"(expected={main_strategy_chart_path} actual={strategy_last_closed_day_source_path or 'missing'})"
        )
    if live_public_state_source_path != main_strategy_chart_path:
        raise ValueError(
            "Authority publish blocked: live_public_state path diverged from chart_source_paths.main_strategy "
            f"(expected={main_strategy_chart_path} actual={live_public_state_source_path or 'missing'})"
        )

    _require_source_modified_during_run(
        main_strategy_metrics_source,
        field_name="app_product_snapshot.source_metadata.main_strategy_metrics",
        refresh_started_at_utc=refresh_started_at_utc,
    )
    _require_source_modified_during_run(
        strategy_last_closed_day_source,
        field_name="app_product_snapshot.source_metadata.strategy_last_closed_day",
        refresh_started_at_utc=refresh_started_at_utc,
    )
    _require_source_modified_during_run(
        live_public_state_source,
        field_name="app_product_snapshot.source_metadata.live_public_state",
        refresh_started_at_utc=refresh_started_at_utc,
    )

    return {
        "latest_available_closed_utc_day": latest_available_closed_utc_day,
        "strategy_artifact_closed_day_utc": strategy_artifact_closed_day_utc,
    }


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
    authority_wallet_sync_utc: str | None = None,
    authority_account_snapshot_as_of_utc: str | None = None,
    authority_runtime_snapshot_generated_at_utc: str | None = None,
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
        authority_wallet_sync_utc=authority_wallet_sync_utc,
        authority_account_snapshot_as_of_utc=authority_account_snapshot_as_of_utc,
        authority_runtime_snapshot_generated_at_utc=authority_runtime_snapshot_generated_at_utc,
        app_product_snapshot=app_product_snapshot,
        app_runtime_snapshot=app_runtime_snapshot,
    )


def _parse_utc_datetime(value: str, *, field_name: str) -> datetime:
    normalized = normalize_utc_timestamp(value, field_name=field_name)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_runtime_sync_fields(app_runtime_snapshot: Mapping[str, Any]) -> dict[str, str]:
    wallet_sync_utc = normalize_utc_timestamp(
        app_runtime_snapshot.get("latest_wallet_sync_utc")
        or app_runtime_snapshot.get("account_snapshot_as_of_utc"),
        field_name="app_runtime_snapshot.latest_wallet_sync_utc",
    )
    account_snapshot_as_of_utc = normalize_utc_timestamp(
        app_runtime_snapshot.get("account_snapshot_as_of_utc") or wallet_sync_utc,
        field_name="app_runtime_snapshot.account_snapshot_as_of_utc",
    )
    runtime_snapshot_generated_at_utc = normalize_utc_timestamp(
        app_runtime_snapshot.get("app_runtime_snapshot_generated_at_utc"),
        field_name="app_runtime_snapshot.app_runtime_snapshot_generated_at_utc",
    )
    return {
        "authority_wallet_sync_utc": wallet_sync_utc,
        "authority_account_snapshot_as_of_utc": account_snapshot_as_of_utc,
        "authority_runtime_snapshot_generated_at_utc": runtime_snapshot_generated_at_utc,
    }


def _validate_success_runtime_sync_fields(
    state: Mapping[str, Any],
    app_runtime_snapshot: Mapping[str, Any],
) -> dict[str, str]:
    sync_fields = _resolve_runtime_sync_fields(app_runtime_snapshot)
    refresh_started_at_utc = normalize_utc_timestamp(
        state.get("refresh_started_at_utc"),
        field_name="refresh_started_at_utc",
    )
    refresh_started_at = _parse_utc_datetime(
        refresh_started_at_utc,
        field_name="refresh_started_at_utc",
    )
    wallet_sync_at = _parse_utc_datetime(
        sync_fields["authority_wallet_sync_utc"],
        field_name="authority_wallet_sync_utc",
    )
    runtime_snapshot_generated_at = _parse_utc_datetime(
        sync_fields["authority_runtime_snapshot_generated_at_utc"],
        field_name="authority_runtime_snapshot_generated_at_utc",
    )

    if wallet_sync_at < refresh_started_at:
        raise ValueError(
            "Authority publish blocked: app_runtime_snapshot wallet sync is stale for this run "
            f"(wallet_sync_utc={sync_fields['authority_wallet_sync_utc']} "
            f"refresh_started_at_utc={refresh_started_at_utc})"
        )
    if runtime_snapshot_generated_at < refresh_started_at:
        raise ValueError(
            "Authority publish blocked: app_runtime_snapshot was not regenerated during this run "
            f"(app_runtime_snapshot_generated_at_utc={sync_fields['authority_runtime_snapshot_generated_at_utc']} "
            f"refresh_started_at_utc={refresh_started_at_utc})"
        )
    return sync_fields


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
    current_strategy_contract = _validate_authority_app_product_snapshot(app_product_snapshot)
    strategy_source_truth = _validate_success_strategy_source_of_truth(
        state,
        app_product_snapshot,
        app_runtime_snapshot,
        current_strategy_contract,
    )
    runtime_sync_fields = _validate_success_runtime_sync_fields(state, app_runtime_snapshot)
    normalized_finished_at_utc = normalize_utc_timestamp(
        refresh_finished_at_utc,
        field_name="refresh_finished_at_utc",
    )

    latest_available_closed_utc_day = strategy_source_truth["latest_available_closed_utc_day"]
    strategy_artifact_closed_day_utc = strategy_source_truth["strategy_artifact_closed_day_utc"]
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
        authority_wallet_sync_utc=runtime_sync_fields["authority_wallet_sync_utc"],
        authority_account_snapshot_as_of_utc=runtime_sync_fields["authority_account_snapshot_as_of_utc"],
        authority_runtime_snapshot_generated_at_utc=runtime_sync_fields["authority_runtime_snapshot_generated_at_utc"],
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
