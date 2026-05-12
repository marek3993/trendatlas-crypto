from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT_BOOTSTRAP = Path(__file__).resolve().parents[2]
SCRIPTS_BOOTSTRAP = ROOT_BOOTSTRAP / "scripts"
if str(ROOT_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(ROOT_BOOTSTRAP))
if str(SCRIPTS_BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_BOOTSTRAP))

from scripts.execution import authority_contract
from scripts.execution import authority_publish_helpers as authority_helpers
from scripts.execution.current_strategy_root_contract import (
    load_current_main_strategy_root_contract,
    validate_authoritative_dependency_closure,
)
from scripts.production.data_health_common import build_report_bundle
from src.market_regime_v1.phase1_time_semantics import (
    ATTEMPT_STATUS_ARTIFACT_TYPE,
    SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
    build_authority_payload,
)


ROOT = Path(__file__).resolve().parents[2]
PIPELINE_SCRIPT = ROOT / "scripts" / "daily_refresh_app_pipeline.py"
CURRENT_STRATEGY_BUILD_SCRIPT = (
    ROOT / "scripts" / "production" / "build_current_strategy_snapshot.py"
)
CURRENT_STRATEGY_VALIDATE_SCRIPT = (
    ROOT / "scripts" / "production" / "validate_current_strategy_snapshot.py"
)
DATA_HEALTH_BUILD_SCRIPT = ROOT / "scripts" / "production" / "build_data_health_report.py"
DATA_HEALTH_VALIDATE_SCRIPT = (
    ROOT / "scripts" / "production" / "validate_data_health_report.py"
)
MATERIALIZE_APP_EXPORTS_SCRIPT = (
    ROOT / "scripts" / "execution" / "materialize_execution_app_exports.py"
)
TERMINAL_ATTEMPT_STATUSES = frozenset({"success", "failed"})
CANONICAL_APP_EXPORT_PREFIX = ("outputs", "execution", "app_exports")
ALLOWED_SUPPORT_ARTIFACT_RELATIVE_PATHS = frozenset(
    {
        Path("outputs/execution/freshness/app_freshness_report.json").as_posix(),
    }
)
ALLOWED_PRODUCTION_ARTIFACT_RELATIVE_PATHS = frozenset(
    {
        Path("outputs/production/current_strategy_snapshot.json").as_posix(),
        Path("outputs/production/current_strategy_timeseries.csv").as_posix(),
        Path("outputs/production/current_strategy_diagnostics.json").as_posix(),
        Path("outputs/production/current_strategy_snapshot.quality.json").as_posix(),
        Path("outputs/production/current_strategy_snapshot.manifest.json").as_posix(),
        Path("outputs/production/data_health_report.json").as_posix(),
        Path("outputs/production/data_health_report.quality.json").as_posix(),
        Path("outputs/production/data_health_report.manifest.json").as_posix(),
    }
)
REMOTE_DRIFT_PUSH_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "[rejected]",
    "failed to push some refs",
)
DASHBOARD_PUBLIC_STATUS_SNAPSHOT_RELATIVE_PATH = Path(
    "outputs/execution/app_snapshot/dashboard_public_status.json"
).as_posix()
AUTHORITY_GIT_USER_NAME_ENV = "MRV1_AUTHORITY_GIT_USER_NAME"
AUTHORITY_GIT_USER_EMAIL_ENV = "MRV1_AUTHORITY_GIT_USER_EMAIL"
FAST_MODE_REQUIRED_PRODUCTION_ARTIFACTS = (
    ROOT / "outputs" / "production" / "current_strategy_snapshot.json",
    ROOT / "outputs" / "production" / "current_strategy_timeseries.csv",
    ROOT / "outputs" / "production" / "current_strategy_diagnostics.json",
    ROOT / "outputs" / "production" / "current_strategy_snapshot.quality.json",
    ROOT / "outputs" / "production" / "current_strategy_snapshot.manifest.json",
)
FAST_MODE_REQUIRED_APP_SNAPSHOT_ARTIFACTS = (
    ROOT / "outputs" / "execution" / "app_snapshot" / "app_product_snapshot.json",
    ROOT / "outputs" / "execution" / "app_snapshot" / "app_runtime_snapshot.json",
    ROOT / DASHBOARD_PUBLIC_STATUS_SNAPSHOT_RELATIVE_PATH,
)
HEAVY_REFRESH_STEPS = (
    "refresh_legacy_ohlcv",
    "refresh_global_liquidity_weekly",
    "phase60_selective_restore_robustness",
    "phase63_btc_participation_overlay",
    "refresh_phase67_top100_shortlist_ohlcv",
    "phase67_top100_build_and_governance",
    "phase67b_top100_forensic_prune_and_rerun",
    "phase66g_production_candidate_live",
    "phase67j_final_narrow_validation_pack",
)
PUBLISH_EXISTING_TMP_ROOT = (
    ROOT / "outputs" / "execution" / "tmp" / "publish_existing_validation"
)


def data_health_artifact_paths(output_dir: Path) -> tuple[Path, Path, Path]:
    return (
        output_dir / "data_health_report.json",
        output_dir / "data_health_report.quality.json",
        output_dir / "data_health_report.manifest.json",
    )


def authority_repo_publish_context_from_env(
    env: Mapping[str, str] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, str]:
    source = os.environ if env is None else env
    resolved_root = Path(root) if root is not None else ROOT
    remote = str(source.get("MRV1_AUTHORITY_REPO_REMOTE") or "origin").strip()
    branch = str(source.get("MRV1_AUTHORITY_REPO_BRANCH") or "main").strip()
    publish_tree = str(
        source.get("MRV1_AUTHORITY_PUBLISH_TREE")
        or (resolved_root.parent / f"{resolved_root.name}__authority_publish")
    ).strip()
    max_push_attempts_raw = str(
        source.get("MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS") or "3"
    ).strip()
    if not remote:
        raise ValueError("MRV1_AUTHORITY_REPO_REMOTE must be non-empty")
    if not branch:
        raise ValueError("MRV1_AUTHORITY_REPO_BRANCH must be non-empty")
    if not publish_tree:
        raise ValueError("MRV1_AUTHORITY_PUBLISH_TREE must be non-empty")
    try:
        max_push_attempts = int(max_push_attempts_raw)
    except ValueError as exc:
        raise ValueError(
            "MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS must be an integer"
        ) from exc
    if max_push_attempts < 1:
        raise ValueError("MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS must be >= 1")
    return {
        "remote": remote,
        "branch": branch,
        "publish_tree": str(Path(publish_tree).expanduser().resolve()),
        "max_push_attempts": str(max_push_attempts),
    }


def load_json_required(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Missing required authority artifact: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Authority artifact must be a JSON object: {path}")
    return payload


def ensure_required_artifacts_exist(paths: Sequence[Path], *, label: str) -> None:
    missing_paths = [str(path) for path in paths if not path.exists() or not path.is_file()]
    if not missing_paths:
        return
    raise FileNotFoundError(
        f"Missing required {label} artifacts:\n" + "\n".join(missing_paths)
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_iso_day_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is missing")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        raise ValueError(f"{field_name} is not an ISO day: {value}")
    date.fromisoformat(text)
    return text


def build_publish_existing_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def build_publish_existing_run_dir(root: Path, *, run_id: str) -> Path:
    relative_tmp_root = PUBLISH_EXISTING_TMP_ROOT.relative_to(ROOT)
    run_dir = root / relative_tmp_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def determine_publish_existing_target_closed_day(root: Path) -> str:
    snapshot_path = root / "outputs" / "production" / "current_strategy_snapshot.json"
    snapshot_payload = load_json_required(snapshot_path)
    return normalize_iso_day_text(
        snapshot_payload.get("closed_day"),
        field_name=f"{snapshot_path}.closed_day",
    )


def build_reference_now_for_closed_day(target_closed_day_utc: str) -> datetime:
    normalized_target_day = normalize_iso_day_text(
        target_closed_day_utc,
        field_name="target_closed_day_utc",
    )
    target_day = date.fromisoformat(normalized_target_day)
    return datetime.combine(
        target_day + timedelta(days=1),
        time(hour=12, minute=0, second=0),
        tzinfo=timezone.utc,
    )


def load_publish_existing_app_snapshots(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    product_path = root / "outputs" / "execution" / "app_snapshot" / "app_product_snapshot.json"
    runtime_path = root / "outputs" / "execution" / "app_snapshot" / "app_runtime_snapshot.json"
    product_snapshot = load_json_required(product_path)
    runtime_snapshot = load_json_required(runtime_path)
    if product_snapshot.get("snapshot_type") != "app_product_snapshot":
        raise ValueError(f"{product_path} is not app_product_snapshot")
    if runtime_snapshot.get("snapshot_type") != "app_runtime_snapshot":
        raise ValueError(f"{runtime_path} is not app_runtime_snapshot")
    return product_snapshot, runtime_snapshot


def build_publish_existing_authority_state(
    *,
    root: Path,
    env: Mapping[str, str],
    run_id: str,
    refresh_started_at_utc: str,
    target_closed_day_utc: str,
) -> dict[str, Any]:
    run_dir = build_publish_existing_run_dir(root, run_id=run_id)
    return authority_helpers.build_authority_publish_state(
        run_id=run_id,
        run_dir=run_dir,
        refresh_started_at_utc=refresh_started_at_utc,
        target_closed_day_utc=target_closed_day_utc,
        latest_available_closed_utc_day=target_closed_day_utc,
        env=env,
    )


def validate_publish_existing_strategy_source_of_truth(
    *,
    state: Mapping[str, Any],
    app_product_snapshot: dict[str, Any],
    app_runtime_snapshot: Mapping[str, Any],
    current_strategy_contract: Mapping[str, Any],
) -> dict[str, str]:
    target_closed_day_utc = authority_contract.normalize_utc_day(
        state.get("target_closed_day_utc"),
        field_name="target_closed_day_utc",
    )
    latest_available_closed_utc_day = authority_contract.normalize_utc_day(
        app_runtime_snapshot.get("latest_available_closed_utc_date")
        or app_product_snapshot.get("freshness_target_closed_day")
        or state.get("latest_available_closed_utc_day"),
        field_name="latest_available_closed_utc_day",
    )
    strategy_artifact_closed_day_utc = authority_contract.normalize_utc_day(
        app_product_snapshot.get("strategy_last_closed_day"),
        field_name="app_product_snapshot.strategy_last_closed_day",
    )
    live_public_state = authority_helpers._payload_mapping(
        app_product_snapshot.get("live_public_state"),
        field_name="app_product_snapshot.live_public_state",
    )
    live_public_state_date = authority_contract.normalize_utc_day(
        live_public_state.get("date"),
        field_name="app_product_snapshot.live_public_state.date",
    )
    runtime_strategy_artifact_closed_day_utc = authority_contract.normalize_utc_day(
        app_runtime_snapshot.get("latest_strategy_artifact_date"),
        field_name="app_runtime_snapshot.latest_strategy_artifact_date",
    )

    if latest_available_closed_utc_day != target_closed_day_utc:
        raise ValueError(
            "publish-existing blocked: target day is not the same as the latest available closed day "
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
                "publish-existing blocked: strategy truth is not aligned with the target closed day "
                f"({field_name}={value} target_closed_day_utc={target_closed_day_utc})"
            )

    main_strategy_model = str(app_product_snapshot.get("main_strategy_model") or "").strip()
    if not main_strategy_model:
        raise ValueError("publish-existing blocked: app_product_snapshot.main_strategy_model is missing")
    main_strategy_metrics = authority_helpers._payload_mapping(
        app_product_snapshot.get("main_strategy_metrics"),
        field_name="app_product_snapshot.main_strategy_metrics",
    )
    metrics_model = str(main_strategy_metrics.get("model") or "").strip()
    if metrics_model != main_strategy_model:
        raise ValueError(
            "publish-existing blocked: app_product_snapshot.main_strategy_metrics.model diverged from "
            f"main_strategy_model (expected={main_strategy_model} actual={metrics_model or 'missing'})"
        )

    expected_main_strategy_metrics_path = str(
        current_strategy_contract["canonical_metrics_source_path"]
    ).strip()
    expected_main_strategy_paper_path = str(
        current_strategy_contract["canonical_paper_source_path"]
    ).strip()

    chart_source_paths = authority_helpers._payload_mapping(
        app_product_snapshot.get("chart_source_paths"),
        field_name="app_product_snapshot.chart_source_paths",
    )
    main_strategy_chart_path = str(chart_source_paths.get("main_strategy") or "").strip()
    if not main_strategy_chart_path:
        raise ValueError(
            "publish-existing blocked: app_product_snapshot.chart_source_paths.main_strategy is missing"
        )
    if main_strategy_chart_path != expected_main_strategy_paper_path:
        raise ValueError(
            "publish-existing blocked: app_product_snapshot.chart_source_paths.main_strategy diverged "
            "from the current main strategy root contract "
            f"(expected={expected_main_strategy_paper_path} actual={main_strategy_chart_path})"
        )

    source_metadata = authority_helpers._payload_mapping(
        app_product_snapshot.get("source_metadata"),
        field_name="app_product_snapshot.source_metadata",
    )
    main_strategy_metrics_source = authority_helpers._payload_mapping(
        source_metadata.get("main_strategy_metrics"),
        field_name="app_product_snapshot.source_metadata.main_strategy_metrics",
    )
    strategy_last_closed_day_source = authority_helpers._payload_mapping(
        source_metadata.get("strategy_last_closed_day"),
        field_name="app_product_snapshot.source_metadata.strategy_last_closed_day",
    )
    live_public_state_source = authority_helpers._payload_mapping(
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
            "publish-existing blocked: app_product_snapshot.source_metadata.main_strategy_metrics.path "
            "diverged from the current main strategy root contract "
            f"(expected={expected_main_strategy_metrics_path} actual={main_strategy_metrics_source_path or 'missing'})"
        )
    if strategy_last_closed_day_source_path != main_strategy_chart_path:
        raise ValueError(
            "publish-existing blocked: strategy_last_closed_day path diverged from chart_source_paths.main_strategy "
            f"(expected={main_strategy_chart_path} actual={strategy_last_closed_day_source_path or 'missing'})"
        )
    if live_public_state_source_path != main_strategy_chart_path:
        raise ValueError(
            "publish-existing blocked: live_public_state path diverged from chart_source_paths.main_strategy "
            f"(expected={main_strategy_chart_path} actual={live_public_state_source_path or 'missing'})"
        )

    return {
        "latest_available_closed_utc_day": latest_available_closed_utc_day,
        "strategy_artifact_closed_day_utc": strategy_artifact_closed_day_utc,
    }


def resolve_publish_existing_runtime_sync_fields(
    app_runtime_snapshot: Mapping[str, Any],
) -> dict[str, str]:
    return authority_helpers._resolve_runtime_sync_fields(app_runtime_snapshot)


def build_publish_existing_success_payloads(
    *,
    state: Mapping[str, Any],
    app_product_snapshot: dict[str, Any],
    app_runtime_snapshot: Mapping[str, Any],
    refresh_finished_at_utc: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    working_state = dict(state)
    current_strategy_contract = authority_helpers._validate_authority_app_product_snapshot(
        app_product_snapshot
    )
    strategy_source_truth = validate_publish_existing_strategy_source_of_truth(
        state=working_state,
        app_product_snapshot=app_product_snapshot,
        app_runtime_snapshot=app_runtime_snapshot,
        current_strategy_contract=current_strategy_contract,
    )
    runtime_sync_fields = resolve_publish_existing_runtime_sync_fields(
        app_runtime_snapshot
    )
    normalized_finished_at_utc = authority_contract.normalize_utc_timestamp(
        refresh_finished_at_utc,
        field_name="refresh_finished_at_utc",
    )
    latest_available_closed_utc_day = strategy_source_truth["latest_available_closed_utc_day"]
    strategy_artifact_closed_day_utc = strategy_source_truth["strategy_artifact_closed_day_utc"]
    working_state["latest_available_closed_utc_day"] = latest_available_closed_utc_day
    stage_history = [
        authority_contract.build_stage_history_entry(
            authority_helpers.AUTHORITY_STAGE_NAME,
            "running",
            started_at_utc=working_state["refresh_started_at_utc"],
            finished_at_utc=None,
            script_path=working_state["pipeline_script_path"],
            non_authoritative_support_only=working_state["authority_mode"]
            != "pi_only_authoritative_producer",
        ),
        authority_contract.build_stage_history_entry(
            authority_helpers.AUTHORITY_STAGE_NAME,
            "success",
            started_at_utc=working_state["refresh_started_at_utc"],
            finished_at_utc=normalized_finished_at_utc,
            script_path=working_state["pipeline_script_path"],
            non_authoritative_support_only=working_state["authority_mode"]
            != "pi_only_authoritative_producer",
        ),
    ]
    working_state["stage_history"] = stage_history
    extra_fields = authority_helpers._build_extra_fields(
        working_state,
        generated_at_utc=normalized_finished_at_utc,
        attempt_stage_status="success",
        stage_history=stage_history,
        authority_wallet_sync_utc=runtime_sync_fields["authority_wallet_sync_utc"],
        authority_account_snapshot_as_of_utc=runtime_sync_fields[
            "authority_account_snapshot_as_of_utc"
        ],
        authority_runtime_snapshot_generated_at_utc=runtime_sync_fields[
            "authority_runtime_snapshot_generated_at_utc"
        ],
        app_product_snapshot=app_product_snapshot,
        app_runtime_snapshot=dict(app_runtime_snapshot),
    )
    attempt_payload = build_authority_payload(
        artifact_type=ATTEMPT_STATUS_ARTIFACT_TYPE,
        target_closed_day_utc=working_state["target_closed_day_utc"],
        latest_available_closed_utc_day=latest_available_closed_utc_day,
        refresh_started_at_utc=working_state["refresh_started_at_utc"],
        refresh_finished_at_utc=normalized_finished_at_utc,
        latest_authoritative_attempt_status="success",
        latest_authoritative_attempt_error=None,
        strategy_artifact_closed_day_utc=strategy_artifact_closed_day_utc,
        extra_fields=extra_fields,
    )
    success_payload = build_authority_payload(
        artifact_type=SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
        target_closed_day_utc=working_state["target_closed_day_utc"],
        latest_available_closed_utc_day=latest_available_closed_utc_day,
        refresh_started_at_utc=working_state["refresh_started_at_utc"],
        refresh_finished_at_utc=normalized_finished_at_utc,
        latest_authoritative_attempt_status="success",
        latest_authoritative_attempt_error=None,
        strategy_artifact_closed_day_utc=strategy_artifact_closed_day_utc,
        extra_fields=extra_fields,
    )
    return attempt_payload, success_payload, working_state


def publish_existing_authority_success_payloads(
    *,
    root: Path,
    env: Mapping[str, str],
    attempt_payload: Mapping[str, Any],
    success_payload: Mapping[str, Any],
) -> dict[str, Any]:
    publish_result = authority_helpers.publish_authority_artifacts(
        dict(attempt_payload),
        dict(success_payload),
        root=root,
        env=env,
    )
    if not bool(publish_result.get("published")):
        raise RuntimeError(
            "publish-existing authority write failed: "
            f"{publish_result.get('reason') or 'unknown reason'}"
        )
    return publish_result


def write_json_payload(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nested_get(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def build_publish_existing_synthetic_execution_intent(
    *,
    root: Path,
    target_closed_day_utc: str,
    generated_at_utc: str,
    attempt_payload: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot_path = root / "outputs" / "production" / "current_strategy_snapshot.json"
    snapshot = load_json_required(snapshot_path)
    execution_intent = _as_mapping(snapshot.get("execution_intent"))
    strategy_model = str(snapshot.get("strategy_version") or "").strip()
    target_asset = str(
        execution_intent.get("target_asset") or snapshot.get("current_asset") or "CASH"
    ).strip().upper()
    target_exposure = execution_intent.get("target_exposure")
    signal_id = str(execution_intent.get("signal_id") or "").strip()
    if not signal_id:
        signal_id = (
            f"current_strategy::{strategy_model}::{target_closed_day_utc}"
            f"::target_{target_asset or 'CASH'}"
            f"::candidate_{str(snapshot.get('candidate_asset') or 'CASH').strip().upper()}"
        )
    return {
        "intent_type": "normalized_execution_intent",
        "generated_at_utc": generated_at_utc,
        "as_of_source": target_closed_day_utc,
        "execution_mode": "publish_existing_validation_only",
        "trading_enabled": False,
        "kill_switch_required": True,
        "strategy_model": strategy_model,
        "signal_id": signal_id,
        "target_asset": target_asset or "CASH",
        "target_side": "hold_cash_no_market_entry"
        if target_asset in {"", "CASH"}
        else "validation_only_no_live_order",
        "target_regime": str(snapshot.get("current_regime") or target_asset or "CASH").strip().upper(),
        "size_mode": "production_snapshot_target_exposure",
        "target_size_pct": target_exposure,
        "staleness_ok": True,
        "stale_signal": False,
        "allow_live_order_candidate": False,
        "guardrail_flags": {
            "contract_validated": True,
            "trading_disabled": True,
            "kill_switch_required": True,
            "manual_approval_required_for_live_orders": True,
            "leverage_live_truth_allowed": False,
            "production_snapshot_validated": True,
            "publish_existing_validation_only": True,
        },
        "authority_day_context": {
            "attempt_status": str(
                attempt_payload.get("latest_authoritative_attempt_status") or ""
            ).strip().lower(),
            "attempt_target_closed_day": target_closed_day_utc,
            "aligned_closed_day": target_closed_day_utc,
            "authority_alignment_mode": "publish_existing_synthetic_authority",
        },
        "source_samples": {
            "production_snapshot_execution_intent": dict(execution_intent),
            "production_snapshot_summary": {
                "strategy_status": snapshot.get("strategy_status"),
                "candidate_asset": snapshot.get("candidate_asset"),
                "current_asset": snapshot.get("current_asset"),
                "effective_market_exposure": snapshot.get("effective_market_exposure"),
                "trend_permission_active": snapshot.get("trend_permission_active"),
                "current_regime": snapshot.get("current_regime"),
                "validation_status": _nested_get(snapshot, "validation", "status"),
            },
        },
        "source_paths": {
            "production_snapshot": str(snapshot_path),
        },
        "notes": [
            "Synthetic publish-existing validation intent.",
            "No runtime preview chain is invoked.",
            "No live order execution is allowed by this artifact.",
        ],
    }


def build_publish_existing_synthetic_real_order_gate(
    *,
    root: Path,
    target_closed_day_utc: str,
    generated_at_utc: str,
    intent_payload: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot_path = root / "outputs" / "production" / "current_strategy_snapshot.json"
    snapshot = load_json_required(snapshot_path)
    execution_intent = _as_mapping(snapshot.get("execution_intent"))
    signal_id = str(intent_payload.get("signal_id") or "").strip()
    target_asset = str(intent_payload.get("target_asset") or "CASH").strip().upper()
    target_exposure = intent_payload.get("target_size_pct")
    try:
        target_exposure_value = float(target_exposure)
    except (TypeError, ValueError):
        target_exposure_value = 0.0
    trend_permission_active = snapshot.get("trend_permission_active") is True
    allow_live_order_candidate = execution_intent.get("allow_live_order_candidate") is True
    validation_status = str(
        _nested_get(snapshot, "validation", "status") or ""
    ).strip().lower()
    return {
        "decision_type": "real_order_gate_decision",
        "generated_at_utc": generated_at_utc,
        "signal_id": signal_id,
        "target_asset": target_asset or "CASH",
        "mode": "publish_existing_validation_only",
        "approval_gate_status": "blocked_validation_only",
        "would_place_real_order": False,
        "real_orders_enabled": False,
        "status": "blocked",
        "block_reasons": [
            "publish_existing_validation_only",
            "live_order_chain_not_invoked",
        ],
        "checks": {
            "signal_present": bool(signal_id),
            "target_asset_present": bool(target_asset),
            "target_asset_allowed": True,
            "target_asset_is_cash": target_asset in {"", "CASH"},
            "target_exposure_positive": target_exposure_value > 0.0,
            "contract_validated": True,
            "execution_trading_enabled": False,
            "allow_live_orders": False,
            "kill_switch": True,
            "stale_signal": False,
            "duplicate_order_risk": False,
            "open_orders_present": False,
            "manual_approval_required": True,
            "production_snapshot_validation_passed": validation_status == "passed",
            "production_snapshot_closed_day_present": True,
            "production_snapshot_signal_present": bool(signal_id),
            "production_snapshot_target_asset_present": bool(target_asset),
            "production_snapshot_target_exposure_positive": target_exposure_value > 0.0,
            "production_snapshot_trend_permission_active": trend_permission_active,
            "production_snapshot_allow_live_order_candidate": allow_live_order_candidate,
            "production_snapshot_stale_signal": False,
            "intent_day_matches_production_snapshot": True,
            "intent_signal_matches_production_snapshot": True,
            "intent_target_asset_matches_production_snapshot": True,
            "intent_target_exposure_matches_production_snapshot": True,
            "intent_stale_signal_matches_production_snapshot": True,
            "intent_strategy_model_matches_production_snapshot": True,
            "intent_allow_live_order_candidate_matches_snapshot": True,
        },
        "production_signal_context": {
            "strategy_version": snapshot.get("strategy_version"),
            "closed_day": target_closed_day_utc,
            "validation_status": validation_status,
            "candidate_asset": snapshot.get("candidate_asset"),
            "current_asset": snapshot.get("current_asset"),
            "signal_id": signal_id,
            "target_asset": target_asset or "CASH",
            "target_exposure": target_exposure,
            "effective_market_exposure": snapshot.get("effective_market_exposure"),
            "model_candidate_exposure": snapshot.get("model_candidate_exposure"),
            "trend_permission_active": snapshot.get("trend_permission_active"),
            "allow_live_order_candidate": execution_intent.get("allow_live_order_candidate"),
        },
        "source_paths": {
            "intent_path": "synthetic_publish_existing_validation_bundle",
            "production_snapshot_path": str(snapshot_path),
        },
        "notes": [
            "Synthetic publish-existing validation gate.",
            "No live order placement is performed.",
            "live_order_chain remains not_invoked.",
        ],
    }


def build_publish_existing_validation_bundle(
    *,
    root: Path,
    run_dir: Path,
    target_closed_day_utc: str,
    attempt_payload: Mapping[str, Any],
    success_payload: Mapping[str, Any],
) -> dict[str, Any]:
    authority_dir = run_dir / "authority"
    synthetic_attempt_path = authority_dir / "latest_attempt_status.json"
    synthetic_success_path = authority_dir / "latest_successful_snapshot.json"
    write_json_payload(synthetic_attempt_path, attempt_payload)
    write_json_payload(synthetic_success_path, success_payload)
    synthetic_intent_path = run_dir / "execution" / "latest_execution_intent.json"
    synthetic_gate_path = run_dir / "execution" / "latest_real_order_gate_decision.json"
    generated_at_utc = str(success_payload.get("generated_at_utc") or utc_now_iso()).strip()
    synthetic_intent = build_publish_existing_synthetic_execution_intent(
        root=root,
        target_closed_day_utc=target_closed_day_utc,
        generated_at_utc=generated_at_utc,
        attempt_payload=attempt_payload,
    )
    synthetic_gate = build_publish_existing_synthetic_real_order_gate(
        root=root,
        target_closed_day_utc=target_closed_day_utc,
        generated_at_utc=generated_at_utc,
        intent_payload=synthetic_intent,
    )
    write_json_payload(synthetic_intent_path, synthetic_intent)
    write_json_payload(synthetic_gate_path, synthetic_gate)
    reference_now = build_reference_now_for_closed_day(target_closed_day_utc)
    return build_report_bundle(
        root=root,
        output_dir=run_dir / "production",
        reference_now=reference_now,
        path_overrides={
            "execution_authority_latest_attempt_status": str(synthetic_attempt_path),
            "execution_authority_latest_successful_snapshot": str(synthetic_success_path),
            "execution_latest_execution_intent": str(synthetic_intent_path),
            "execution_latest_real_order_gate_decision": str(synthetic_gate_path),
        },
        write_outputs=False,
    )


def publish_existing_synthetic_execution_path_overrides(run_dir: Path) -> dict[str, str]:
    return {
        "execution_latest_execution_intent": str(
            run_dir / "execution" / "latest_execution_intent.json"
        ),
        "execution_latest_real_order_gate_decision": str(
            run_dir / "execution" / "latest_real_order_gate_decision.json"
        ),
    }


def validate_publish_existing_readiness_bundle(
    bundle: Mapping[str, Any],
    *,
    target_closed_day_utc: str,
) -> dict[str, Any]:
    quality = bundle.get("quality") if isinstance(bundle.get("quality"), dict) else {}
    report = bundle.get("report") if isinstance(bundle.get("report"), dict) else {}
    quality_status = str(quality.get("status") or "").strip().lower()
    if quality_status != "passed":
        raise RuntimeError(
            "publish-existing validation failed: data health quality did not pass "
            f"(status={quality_status or 'missing'})"
        )
    report_reference_day = normalize_iso_day_text(
        report.get("reference_closed_day_utc"),
        field_name="report.reference_closed_day_utc",
    )
    if report_reference_day != target_closed_day_utc:
        raise RuntimeError(
            "publish-existing validation failed: data health report reference day diverged "
            f"(expected={target_closed_day_utc} actual={report_reference_day})"
        )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if bool(summary.get("block_app")) or bool(summary.get("block_execution")):
        raise RuntimeError(
            "publish-existing validation failed: production/app/execution blockers remain "
            f"(block_app={bool(summary.get('block_app'))} "
            f"block_execution={bool(summary.get('block_execution'))})"
        )
    return dict(report)


def build_publish_existing_dry_run_publish_result(
    *,
    root: Path,
    env: Mapping[str, str],
    attempt_payload: Mapping[str, Any],
    success_payload: Mapping[str, Any],
) -> dict[str, Any]:
    context = authority_repo_publish_context_from_env(env, root=root)
    publish_paths = [
        root / "outputs" / "execution" / "authority" / "latest_attempt_status.json",
        root / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json",
        *_resolve_required_app_publish_paths(success_payload, root=root),
        *_resolve_required_production_publish_paths(root=root),
    ]
    deduped_pathspecs: list[str] = []
    seen_pathspecs: set[str] = set()
    for path in publish_paths:
        pathspec = str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
        if pathspec in seen_pathspecs:
            continue
        seen_pathspecs.add(pathspec)
        deduped_pathspecs.append(pathspec)
    return {
        "published": False,
        "reason": "dry_run",
        "attempt_status": str(
            attempt_payload.get("latest_authoritative_attempt_status") or ""
        ).strip().lower(),
        "remote": context["remote"],
        "branch": context["branch"],
        "remote_url": None,
        "publish_tree": context["publish_tree"],
        "push_attempts": 0,
        "pathspecs": deduped_pathspecs,
        "commit_message": build_authority_publish_commit_message(attempt_payload),
        "commit_sha": None,
        "dry_run": True,
    }


def _resolve_canonical_app_export_path(
    raw_path: Any,
    *,
    root: Path,
    field_name: str,
) -> Path:
    path_text = str(raw_path or "").strip()
    if not path_text:
        raise ValueError(f"Missing required canonical app export path: {field_name}")
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved_candidate = candidate.resolve()
    resolved_root = root.resolve()
    try:
        relative_path = resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"Canonical app export path must stay inside the runtime checkout: {field_name}={path_text}"
        ) from exc
    if relative_path.parts[: len(CANONICAL_APP_EXPORT_PREFIX)] != CANONICAL_APP_EXPORT_PREFIX:
        raise ValueError(
            "Canonical app export path must stay inside outputs/execution/app_exports: "
            f"{field_name}={path_text}"
        )
    if not resolved_candidate.exists() or not resolved_candidate.is_file():
        raise FileNotFoundError(
            f"Missing required canonical app export artifact: {resolved_candidate}"
        )
    return resolved_candidate


def _resolve_canonical_support_artifact_path(
    raw_path: Any,
    *,
    root: Path,
    field_name: str,
) -> Path:
    path_text = str(raw_path or "").strip()
    if not path_text:
        raise ValueError(f"Missing required canonical support artifact path: {field_name}")
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved_candidate = candidate.resolve()
    resolved_root = root.resolve()
    try:
        relative_path = resolved_candidate.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Canonical support artifact path must stay inside the runtime checkout: {field_name}={path_text}"
        ) from exc
    if relative_path not in ALLOWED_SUPPORT_ARTIFACT_RELATIVE_PATHS:
        allowed_display = ", ".join(sorted(ALLOWED_SUPPORT_ARTIFACT_RELATIVE_PATHS))
        raise ValueError(
            "Canonical support artifact path is not allowlisted: "
            f"{field_name}={path_text} allowed={allowed_display}"
        )
    if not resolved_candidate.exists() or not resolved_candidate.is_file():
        raise FileNotFoundError(
            f"Missing required canonical support artifact: {resolved_candidate}"
        )
    return resolved_candidate


def _resolve_allowlisted_repo_artifact_path(
    relative_path: str,
    *,
    root: Path,
    allowed_relative_paths: frozenset[str],
    artifact_label: str,
) -> Path:
    normalized_relative_path = Path(relative_path).as_posix()
    if normalized_relative_path not in allowed_relative_paths:
        allowed_display = ", ".join(sorted(allowed_relative_paths))
        raise ValueError(
            f"{artifact_label} is not allowlisted for repo publish: "
            f"{normalized_relative_path} allowed={allowed_display}"
        )
    resolved_candidate = (root / normalized_relative_path).resolve()
    if not resolved_candidate.exists() or not resolved_candidate.is_file():
        raise FileNotFoundError(
            f"Missing required {artifact_label}: {resolved_candidate}"
        )
    return resolved_candidate


def _resolve_required_dashboard_public_status_snapshot_path(*, root: Path) -> Path:
    resolved_candidate = (root / DASHBOARD_PUBLIC_STATUS_SNAPSHOT_RELATIVE_PATH).resolve()
    if not resolved_candidate.exists() or not resolved_candidate.is_file():
        raise FileNotFoundError(
            "Missing required app snapshot repo publish artifact: "
            f"{resolved_candidate}"
        )
    return resolved_candidate


def _resolve_required_app_publish_paths(
    latest_successful_snapshot_payload: Mapping[str, Any],
    *,
    root: Path,
) -> list[Path]:
    product_snapshot = latest_successful_snapshot_payload.get("app_product_snapshot")
    if not isinstance(product_snapshot, dict):
        raise ValueError(
            "Authority latest_successful_snapshot missing app_product_snapshot"
        )
    chart_source_paths = product_snapshot.get("chart_source_paths")
    if not isinstance(chart_source_paths, dict):
        raise ValueError(
            "Authority latest_successful_snapshot missing app_product_snapshot.chart_source_paths"
        )
    source_metadata = product_snapshot.get("source_metadata")
    if not isinstance(source_metadata, dict):
        raise ValueError(
            "Authority latest_successful_snapshot missing app_product_snapshot.source_metadata"
        )
    main_strategy_metrics_metadata = source_metadata.get("main_strategy_metrics")
    if not isinstance(main_strategy_metrics_metadata, dict):
        raise ValueError(
            "Authority latest_successful_snapshot missing "
            "app_product_snapshot.source_metadata.main_strategy_metrics"
        )
    current_strategy_contract = load_current_main_strategy_root_contract(root=root)
    dependency_closure = validate_authoritative_dependency_closure(
        product_snapshot,
        current_strategy_contract,
        root=root,
        context="Authority repo publish blocked:",
    )
    return [
        _resolve_canonical_app_export_path(
            main_strategy_metrics_metadata.get("path"),
            root=root,
            field_name="app_product_snapshot.source_metadata.main_strategy_metrics.path",
        ),
        _resolve_canonical_app_export_path(
            chart_source_paths.get("main_strategy"),
            root=root,
            field_name="app_product_snapshot.chart_source_paths.main_strategy",
        ),
        _resolve_canonical_app_export_path(
            str(dependency_closure["reference_paper_path"]),
            root=root,
            field_name="app_product_snapshot.chart_source_paths.reference_strategy",
        ),
        _resolve_canonical_app_export_path(
            str(dependency_closure["reference_live_status_path"]),
            root=root,
            field_name="app_export_contract.model_sources.reference_strategy.live_status_path",
        ),
        _resolve_canonical_app_export_path(
            str(dependency_closure["phase66g_live_status_path"]),
            root=root,
            field_name="app_product_snapshot.source_metadata.trend_barometer_summary.path",
        ),
        _resolve_canonical_app_export_path(
            str(dependency_closure["phase66g_trend_history_path"]),
            root=root,
            field_name="app_product_snapshot.trend_history_source_path",
        ),
        _resolve_canonical_support_artifact_path(
            str(dependency_closure["freshness_report_path"]),
            root=root,
            field_name="app_product_snapshot.source_metadata.freshness.path",
        ),
        _resolve_required_dashboard_public_status_snapshot_path(root=root),
    ]


def _resolve_required_production_publish_paths(*, root: Path) -> list[Path]:
    return [
        _resolve_allowlisted_repo_artifact_path(
            relative_path,
            root=root,
            allowed_relative_paths=ALLOWED_PRODUCTION_ARTIFACT_RELATIVE_PATHS,
            artifact_label="production repo publish artifact",
        )
        for relative_path in sorted(ALLOWED_PRODUCTION_ARTIFACT_RELATIVE_PATHS)
    ]


def resolve_authority_publish_paths(root: Path | None = None) -> list[Path]:
    resolved_root = Path(root) if root is not None else ROOT
    latest_attempt_status_path = (
        resolved_root / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
    )
    publish_paths = [latest_attempt_status_path]
    snapshot_path = (
        resolved_root / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
    )
    latest_attempt_payload = load_json_required(latest_attempt_status_path)
    latest_attempt_status = str(
        latest_attempt_payload.get("latest_authoritative_attempt_status") or ""
    ).strip().lower()
    if latest_attempt_status == "success":
        latest_successful_snapshot_payload = load_json_required(snapshot_path)
        publish_paths.append(snapshot_path)
        publish_paths.extend(
            _resolve_required_app_publish_paths(
                latest_successful_snapshot_payload,
                root=resolved_root,
            )
        )
        publish_paths.extend(_resolve_required_production_publish_paths(root=resolved_root))
    deduped_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for path in publish_paths:
        resolved_path = path.resolve()
        if resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        deduped_paths.append(resolved_path)
    return deduped_paths


def _run_git_command(
    args: list[str],
    *,
    root: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        env=dict(os.environ if env is None else env),
        text=True,
        capture_output=True,
        check=False,
    )


def _ensure_git_ok(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    if result.returncode == 0:
        return
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    details = stderr or stdout or f"returncode={result.returncode}"
    raise RuntimeError(f"{label} failed: {details}")


def _is_remote_drift_push_failure(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    combined = "\n".join(
        part.strip() for part in ((result.stderr or ""), (result.stdout or "")) if part.strip()
    ).lower()
    return any(marker in combined for marker in REMOTE_DRIFT_PUSH_MARKERS)


def _ensure_publish_tree_is_external(runtime_root: Path, publish_tree: Path) -> None:
    resolved_runtime_root = runtime_root.resolve()
    resolved_publish_tree = publish_tree.resolve()
    if resolved_publish_tree == resolved_runtime_root:
        raise RuntimeError(
            "Authority publish tree must not be the runtime checkout root"
        )
    if resolved_runtime_root in resolved_publish_tree.parents:
        raise RuntimeError(
            "Authority publish tree must live outside the runtime checkout"
        )


def _resolve_git_remote_url(
    *,
    runtime_root: Path,
    remote: str,
    env: Mapping[str, str] | None = None,
) -> str:
    result = _run_git_command(
        ["remote", "get-url", remote],
        root=runtime_root,
        env=env,
    )
    _ensure_git_ok(result, label=f"git remote get-url {remote}")
    remote_url = (result.stdout or "").strip()
    if not remote_url:
        raise RuntimeError(f"git remote get-url {remote} returned an empty URL")
    return remote_url


def _resolve_authority_git_identity(
    *,
    runtime_root: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    source = os.environ if env is None else env
    configured_name = str(source.get(AUTHORITY_GIT_USER_NAME_ENV) or "").strip()
    configured_email = str(source.get(AUTHORITY_GIT_USER_EMAIL_ENV) or "").strip()

    if bool(configured_name) != bool(configured_email):
        raise RuntimeError(
            f"{AUTHORITY_GIT_USER_NAME_ENV} and {AUTHORITY_GIT_USER_EMAIL_ENV} must either both be set or both be unset"
        )
    if configured_name and configured_email:
        return configured_name, configured_email

    name_result = _run_git_command(
        ["config", "--get", "user.name"],
        root=runtime_root,
        env=env,
    )
    email_result = _run_git_command(
        ["config", "--get", "user.email"],
        root=runtime_root,
        env=env,
    )
    fallback_name = (name_result.stdout or "").strip() if name_result.returncode == 0 else ""
    fallback_email = (email_result.stdout or "").strip() if email_result.returncode == 0 else ""
    if fallback_name and fallback_email:
        return fallback_name, fallback_email

    raise RuntimeError(
        "Authority repo publish requires a git commit identity. "
        f"Set {AUTHORITY_GIT_USER_NAME_ENV}/{AUTHORITY_GIT_USER_EMAIL_ENV} "
        "or configure git user.name/user.email in the runtime checkout."
    )


def _build_git_publish_env(
    *,
    git_user_name: str,
    git_user_email: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    git_env = dict(os.environ if env is None else env)
    git_env["GIT_AUTHOR_NAME"] = git_user_name
    git_env["GIT_AUTHOR_EMAIL"] = git_user_email
    git_env["GIT_COMMITTER_NAME"] = git_user_name
    git_env["GIT_COMMITTER_EMAIL"] = git_user_email
    return git_env


def _clone_publish_tree(
    *,
    publish_tree: Path,
    remote: str,
    branch: str,
    remote_url: str,
    env: Mapping[str, str] | None = None,
) -> None:
    publish_tree.parent.mkdir(parents=True, exist_ok=True)
    clone_result = subprocess.run(
        [
            "git",
            "clone",
            "--origin",
            remote,
            "--branch",
            branch,
            "--single-branch",
            remote_url,
            str(publish_tree),
        ],
        cwd=str(publish_tree.parent),
        env=dict(os.environ if env is None else env),
        text=True,
        capture_output=True,
        check=False,
    )
    _ensure_git_ok(clone_result, label="git clone authority publish tree")


def _ensure_publish_tree_remote(
    *,
    publish_tree: Path,
    remote: str,
    remote_url: str,
    env: Mapping[str, str] | None = None,
) -> None:
    get_url_result = _run_git_command(
        ["remote", "get-url", remote],
        root=publish_tree,
        env=env,
    )
    if get_url_result.returncode == 0:
        current_remote_url = (get_url_result.stdout or "").strip()
        if current_remote_url != remote_url:
            set_url_result = _run_git_command(
                ["remote", "set-url", remote, remote_url],
                root=publish_tree,
                env=env,
            )
            _ensure_git_ok(set_url_result, label=f"git remote set-url {remote}")
        return

    add_remote_result = _run_git_command(
        ["remote", "add", remote, remote_url],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(add_remote_result, label=f"git remote add {remote}")


def _ensure_clean_publish_tree(
    *,
    runtime_root: Path,
    publish_tree: Path,
    remote: str,
    branch: str,
    remote_url: str,
    env: Mapping[str, str] | None = None,
) -> None:
    _ensure_publish_tree_is_external(runtime_root, publish_tree)
    if publish_tree.exists() and not (publish_tree / ".git").exists():
        raise RuntimeError(
            f"Authority publish tree exists but is not a git clone: {publish_tree}"
        )
    if not publish_tree.exists():
        _clone_publish_tree(
            publish_tree=publish_tree,
            remote=remote,
            branch=branch,
            remote_url=remote_url,
            env=env,
        )

    _ensure_publish_tree_remote(
        publish_tree=publish_tree,
        remote=remote,
        remote_url=remote_url,
        env=env,
    )

    fetch_result = _run_git_command(
        ["fetch", remote, branch],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(fetch_result, label="git fetch authority publish branch")

    checkout_result = _run_git_command(
        ["checkout", "-B", branch, f"{remote}/{branch}"],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(checkout_result, label="git checkout authority publish branch")

    reset_result = _run_git_command(
        ["reset", "--hard", f"{remote}/{branch}"],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(reset_result, label="git reset authority publish branch")

    clean_result = _run_git_command(
        ["clean", "-fd"],
        root=publish_tree,
        env=env,
    )
    _ensure_git_ok(clean_result, label="git clean authority publish tree")


def _copy_publish_paths(
    *,
    runtime_root: Path,
    publish_tree: Path,
    publish_paths: list[Path],
) -> list[str]:
    pathspecs: list[str] = []
    for source_path in publish_paths:
        relative_path = source_path.relative_to(runtime_root)
        destination_path = publish_tree / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        pathspecs.append(relative_path.as_posix())
    return pathspecs


def build_authority_publish_commit_message(attempt_payload: Mapping[str, Any]) -> str:
    attempt_status = str(
        attempt_payload.get("latest_authoritative_attempt_status") or "unknown"
    ).strip().lower()
    target_closed_day = str(
        attempt_payload.get("target_closed_day_utc") or "unknown_day"
    ).strip()
    run_id = str(attempt_payload.get("run_id") or "unknown_run").strip()
    return f"Publish Pi authority artifacts: {attempt_status} {target_closed_day} {run_id}"


def publish_authority_artifacts_to_repo(
    *,
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    resolved_root = Path(root) if root is not None else ROOT
    latest_attempt_status_path = (
        resolved_root / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
    )
    latest_successful_snapshot_path = (
        resolved_root / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
    )
    context = authority_repo_publish_context_from_env(env, root=resolved_root)
    attempt_payload = load_json_required(latest_attempt_status_path)
    attempt_status = str(
        attempt_payload.get("latest_authoritative_attempt_status") or ""
    ).strip().lower()
    automatic_producer_id = str(attempt_payload.get("automatic_producer_id") or "").strip().lower()
    authority_role = str(attempt_payload.get("authority_role") or "").strip().lower()

    if attempt_status not in TERMINAL_ATTEMPT_STATUSES:
        raise RuntimeError(
            "Authority repo publish requires a terminal latest_attempt_status payload"
        )
    if automatic_producer_id != "raspberry_pi":
        raise RuntimeError(
            "Authority repo publish requires automatic_producer_id=raspberry_pi"
        )
    if authority_role != "pi_only_authoritative_producer":
        raise RuntimeError(
            "Authority repo publish requires authority_role=pi_only_authoritative_producer"
        )
    if attempt_status == "success" and not latest_successful_snapshot_path.exists():
        raise FileNotFoundError(
            "Successful authority publish requires snapshot artifact: "
            f"{latest_successful_snapshot_path}"
        )

    publish_paths = resolve_authority_publish_paths(resolved_root)
    if not publish_paths:
        raise RuntimeError("No authority artifacts available for repo publish")
    remote = context["remote"]
    branch = context["branch"]
    publish_tree = Path(context["publish_tree"])
    max_push_attempts = int(context["max_push_attempts"])
    _ensure_publish_tree_is_external(resolved_root, publish_tree)
    pathspecs = [
        str(path.resolve().relative_to(resolved_root.resolve())).replace("\\", "/")
        for path in publish_paths
    ]
    commit_message = build_authority_publish_commit_message(attempt_payload)
    if dry_run:
        return {
            "published": False,
            "reason": "dry_run",
            "attempt_status": attempt_status,
            "remote": remote,
            "branch": branch,
            "remote_url": None,
            "publish_tree": str(publish_tree),
            "push_attempts": 0,
            "pathspecs": pathspecs,
            "commit_message": commit_message,
            "commit_sha": None,
            "dry_run": True,
        }
    git_user_name, git_user_email = _resolve_authority_git_identity(
        runtime_root=resolved_root,
        env=env,
    )
    git_env = _build_git_publish_env(
        git_user_name=git_user_name,
        git_user_email=git_user_email,
        env=env,
    )
    remote_url = _resolve_git_remote_url(
        runtime_root=resolved_root,
        remote=remote,
        env=git_env,
    )
    for push_attempt in range(1, max_push_attempts + 1):
        _ensure_clean_publish_tree(
            runtime_root=resolved_root,
            publish_tree=publish_tree,
            remote=remote,
            branch=branch,
            remote_url=remote_url,
            env=git_env,
        )
        pathspecs = _copy_publish_paths(
            runtime_root=resolved_root,
            publish_tree=publish_tree,
            publish_paths=publish_paths,
        )
        add_result = _run_git_command(
            ["add", "--", *pathspecs],
            root=publish_tree,
            env=git_env,
        )
        _ensure_git_ok(add_result, label="git add authority artifacts")

        diff_result = _run_git_command(
            ["diff", "--cached", "--quiet", "--", *pathspecs],
            root=publish_tree,
            env=git_env,
        )
        if diff_result.returncode == 0:
            return {
                "published": False,
                "reason": "no_authority_repo_changes",
                "attempt_status": attempt_status,
                "remote": remote,
                "branch": branch,
                "remote_url": remote_url,
                "publish_tree": str(publish_tree),
                "push_attempts": push_attempt,
                "pathspecs": pathspecs,
                "commit_message": None,
            }
        if diff_result.returncode != 1:
            _ensure_git_ok(diff_result, label="git diff --cached authority artifacts")

        commit_result = _run_git_command(
            ["commit", "--only", "-m", commit_message, "--", *pathspecs],
            root=publish_tree,
            env=git_env,
        )
        _ensure_git_ok(commit_result, label="git commit authority artifacts")

        push_result = _run_git_command(
            ["push", remote, f"HEAD:{branch}"],
            root=publish_tree,
            env=git_env,
        )
        if push_result.returncode == 0:
            break
        if push_attempt < max_push_attempts and _is_remote_drift_push_failure(push_result):
            continue
        _ensure_git_ok(push_result, label="git push authority artifacts")

    head_result = _run_git_command(["rev-parse", "HEAD"], root=publish_tree, env=git_env)
    _ensure_git_ok(head_result, label="git rev-parse HEAD")
    commit_sha = (head_result.stdout or "").strip()

    return {
        "published": True,
        "reason": None,
        "attempt_status": attempt_status,
        "remote": remote,
        "branch": branch,
        "remote_url": remote_url,
        "publish_tree": str(publish_tree),
        "push_attempts": push_attempt,
        "pathspecs": pathspecs,
        "commit_message": commit_message,
        "commit_sha": commit_sha,
    }


def build_pi_authoritative_env(
    *,
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> dict[str, str]:
    resolved_root = Path(root) if root is not None else ROOT
    merged_env = dict(os.environ if env is None else env)
    merged_env["MRV1_ENABLE_AUTHORITY_PUBLISH"] = "1"
    merged_env["MRV1_AUTHORITY_MODE"] = "authoritative"
    merged_env["MRV1_AUTOMATIC_PRODUCER_ID"] = "raspberry_pi"
    merged_env["MRV1_REQUIRE_PI_RUNTIME"] = "1"
    merged_env.setdefault("MRV1_PUBLISH_HOSTNAME", socket.gethostname())
    merged_env.setdefault("MRV1_AUTHORITY_REPO_REMOTE", "origin")
    merged_env.setdefault("MRV1_AUTHORITY_REPO_BRANCH", "main")
    merged_env.setdefault(
        "MRV1_AUTHORITY_PUBLISH_TREE",
        str(resolved_root.parent / f"{resolved_root.name}__authority_publish"),
    )
    merged_env.setdefault("MRV1_AUTHORITY_PUBLISH_MAX_PUSH_ATTEMPTS", "3")
    merged_env["MRV1_AUTHORITY_ENTRYPOINT"] = str(Path(__file__).resolve())
    return merged_env


def run_checked_python_command(
    script_path: Path,
    *,
    env: Mapping[str, str],
    root: Path,
    args: Sequence[str] | None = None,
    label: str,
) -> subprocess.CompletedProcess[Any]:
    if not script_path.exists() or not script_path.is_file():
        raise FileNotFoundError(f"Missing required script for {label}: {script_path}")
    command = [sys.executable, str(script_path), *(list(args or []))]
    completed = subprocess.run(
        command,
        cwd=str(root),
        env=dict(env),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")
    return completed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pi-only authority wrapper. The safe default publishes existing authoritative "
            "artifacts after validation; the full refresh path is explicit only."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("publish-existing", "full-refresh"),
        default="publish-existing",
        help=(
            "publish-existing validates and publishes the current authoritative artifacts "
            "without running the heavy refresh chain. full-refresh runs the daily refresh pipeline."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate the publish-existing path and show the authority repo publish plan "
            "without cloning, committing, or pushing."
        ),
    )
    return parser


def parse_cli_args(
    argv: Sequence[str] | None = None,
) -> tuple[argparse.Namespace, list[str]]:
    parser = build_arg_parser()
    args, passthrough_args = parser.parse_known_args(argv)
    if args.mode != "full-refresh" and passthrough_args:
        parser.error("extra arguments are only supported with --mode full-refresh")
    if args.mode == "full-refresh" and args.dry_run:
        parser.error("--dry-run is supported only with --mode publish-existing")
    return args, passthrough_args


def print_mode_banner(mode: str) -> None:
    print(f"[AUTHORITY] mode={mode}", flush=True)
    if mode == "publish-existing":
        print("[AUTHORITY] heavy_refresh_steps=skipped", flush=True)
        return
    print("[AUTHORITY] heavy_refresh_steps=enabled", flush=True)


def run_publish_existing_flow(
    *,
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    resolved_root = Path(root) if root is not None else ROOT
    pi_env = build_pi_authoritative_env(env=env, root=resolved_root)
    executed_steps: list[str] = []
    run_checked_python_command(
        CURRENT_STRATEGY_BUILD_SCRIPT,
        env=pi_env,
        root=resolved_root,
        label="build_current_strategy_snapshot",
    )
    executed_steps.append("build_current_strategy_snapshot")
    ensure_required_artifacts_exist(
        FAST_MODE_REQUIRED_PRODUCTION_ARTIFACTS,
        label="publish-existing Production Core",
    )
    target_closed_day_utc = determine_publish_existing_target_closed_day(resolved_root)
    refresh_started_at_utc = utc_now_iso()
    authority_state = build_publish_existing_authority_state(
        root=resolved_root,
        env=pi_env,
        run_id=build_publish_existing_run_id(),
        refresh_started_at_utc=refresh_started_at_utc,
        target_closed_day_utc=target_closed_day_utc,
    )
    run_checked_python_command(
        CURRENT_STRATEGY_VALIDATE_SCRIPT,
        env=pi_env,
        root=resolved_root,
        label="validate_current_strategy_snapshot",
    )
    executed_steps.append("validate_current_strategy_snapshot")
    ensure_required_artifacts_exist(
        FAST_MODE_REQUIRED_PRODUCTION_ARTIFACTS,
        label="publish-existing Production Core",
    )
    run_checked_python_command(
        MATERIALIZE_APP_EXPORTS_SCRIPT,
        env=pi_env,
        root=resolved_root,
        label="materialize_execution_app_exports",
    )
    executed_steps.append("materialize_execution_app_exports")
    ensure_required_artifacts_exist(
        FAST_MODE_REQUIRED_APP_SNAPSHOT_ARTIFACTS,
        label="publish-existing app snapshots",
    )

    app_product_snapshot, app_runtime_snapshot = load_publish_existing_app_snapshots(resolved_root)
    refresh_finished_at_utc = utc_now_iso()
    attempt_payload, success_payload, authority_state = build_publish_existing_success_payloads(
        state=authority_state,
        app_product_snapshot=app_product_snapshot,
        app_runtime_snapshot=app_runtime_snapshot,
        refresh_finished_at_utc=refresh_finished_at_utc,
    )
    validation_run_dir = Path(str(authority_state["run_dir"]))
    validation_bundle = build_publish_existing_validation_bundle(
        root=resolved_root,
        run_dir=validation_run_dir,
        target_closed_day_utc=target_closed_day_utc,
        attempt_payload=attempt_payload,
        success_payload=success_payload,
    )
    executed_steps.append("build_publish_existing_validation_bundle")
    readiness_report = validate_publish_existing_readiness_bundle(
        validation_bundle,
        target_closed_day_utc=target_closed_day_utc,
    )
    executed_steps.append("validate_publish_existing_readiness")

    runtime_preview_chain = "not_invoked"
    live_order_chain = "not_invoked"
    print("[AUTHORITY] runtime_preview_chain=not_invoked", flush=True)
    print("[AUTHORITY] live_order_chain=not_invoked", flush=True)

    if dry_run:
        authority_artifact_write = "skipped_dry_run"
        publish_result = build_publish_existing_dry_run_publish_result(
            root=resolved_root,
            env=pi_env,
            attempt_payload=attempt_payload,
            success_payload=success_payload,
        )
    else:
        publish_existing_authority_success_payloads(
            root=resolved_root,
            env=pi_env,
            attempt_payload=attempt_payload,
            success_payload=success_payload,
        )
        authority_artifact_write = "success_payload_written"
        reference_now = build_reference_now_for_closed_day(target_closed_day_utc)
        canonical_bundle = build_report_bundle(
            root=resolved_root,
            output_dir=resolved_root / "outputs" / "production",
            reference_now=reference_now,
            path_overrides=publish_existing_synthetic_execution_path_overrides(
                validation_run_dir
            ),
            write_outputs=False,
        )
        validate_publish_existing_readiness_bundle(
            canonical_bundle,
            target_closed_day_utc=target_closed_day_utc,
        )
        build_report_bundle(
            root=resolved_root,
            output_dir=resolved_root / "outputs" / "production",
            reference_now=reference_now,
            path_overrides=publish_existing_synthetic_execution_path_overrides(
                validation_run_dir
            ),
            write_outputs=True,
        )
        publish_result = publish_authority_artifacts_to_repo(
            root=resolved_root,
            env=pi_env,
            dry_run=False,
        )
    return {
        "mode": "publish-existing",
        "dry_run": dry_run,
        "heavy_refresh_steps": "skipped",
        "skipped_heavy_steps": list(HEAVY_REFRESH_STEPS),
        "runtime_preview_chain": runtime_preview_chain,
        "live_order_chain": live_order_chain,
        "authority_artifact_write": authority_artifact_write,
        "target_closed_day_utc": target_closed_day_utc,
        "data_health_reference_closed_day_utc": readiness_report["reference_closed_day_utc"],
        "executed_steps": executed_steps,
        "authority_repo_publish": publish_result,
    }


def run_full_refresh_flow(
    *,
    pipeline_args: Sequence[str],
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    resolved_root = Path(root) if root is not None else ROOT
    if not PIPELINE_SCRIPT.exists():
        raise FileNotFoundError(f"Missing pipeline script: {PIPELINE_SCRIPT}")

    command = [sys.executable, str(PIPELINE_SCRIPT), *list(pipeline_args)]
    pi_env = build_pi_authoritative_env(env=env, root=resolved_root)
    completed = subprocess.run(
        command,
        cwd=str(resolved_root),
        env=pi_env,
        check=False,
    )
    publish_result = publish_authority_artifacts_to_repo(
        root=resolved_root,
        env=pi_env,
    )
    return completed.returncode, {
        "mode": "full-refresh",
        "pipeline_command": command,
        "pipeline_returncode": completed.returncode,
        "heavy_refresh_steps": "enabled",
        "authority_repo_publish": publish_result,
    }


def main(argv: Sequence[str] | None = None) -> None:
    args, passthrough_args = parse_cli_args(argv)
    print_mode_banner(args.mode)
    if args.mode == "publish-existing":
        result = run_publish_existing_flow(
            root=ROOT,
            dry_run=bool(args.dry_run),
        )
        exit_code = 0
    else:
        exit_code, result = run_full_refresh_flow(
            pipeline_args=passthrough_args,
            root=ROOT,
        )
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        flush=True,
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
