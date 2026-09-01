from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.data_health_common import (
    REPORT_PATH as DATA_HEALTH_REPORT_PATH,
    build_report_bundle,
    execution_blocking_sources,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
INTENTS_DIR = OUTPUTS_DIR / "intents"
LOGS_DIR = OUTPUTS_DIR / "logs"
PRODUCTION_DIR = ROOT / "outputs" / "production"

EXPORT_CONTRACT_PATH = SOURCE_OF_TRUTH_DIR / "export_contract.json"
INTENT_PATH = INTENTS_DIR / "latest_execution_intent.json"
QUALITY_PATH = INTENTS_DIR / "latest_execution_intent_quality.json"
MANIFEST_PATH = INTENTS_DIR / "latest_execution_intent_manifest.json"
PRODUCTION_SNAPSHOT_PATH = PRODUCTION_DIR / "current_strategy_snapshot.json"
AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH = (
    OUTPUTS_DIR / "authority" / "latest_successful_snapshot.json"
)
AUTHORITY_LATEST_ATTEMPT_STATUS_PATH = (
    OUTPUTS_DIR / "authority" / "latest_attempt_status.json"
)
LOG_PATH = LOGS_DIR / "build_execution_intent_from_strategy_exports.log"

DEFAULT_REFERENCE_MODEL = "phase67j_no_neo_main"
CASH_LIKE_ASSETS = {"CASH", "USD", "USDC", "USDT", "NONE", "OUT_OF_MARKET"}
INTENT_HEALTH_GUARD_SOURCE_IDS = frozenset(
    {
        "production_current_strategy_snapshot",
        "production_current_strategy_timeseries",
        "production_current_strategy_diagnostics",
        "production_current_strategy_snapshot_quality",
        "data_ohlcv_btcusdt_1d",
    }
)
SAME_RUN_AUTHORITY_ALLOW_ENV = "MRV1_ALLOW_IN_PROGRESS_AUTHORITY_FOR_SAME_RUN"
SAME_RUN_AUTHORITY_RUN_ID_ENV = "MRV1_CURRENT_AUTHORITY_RUN_ID"
SAME_RUN_AUTHORITY_TARGET_DAY_ENV = "MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY"


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def log(msg: str) -> None:
    print(msg)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(msg + "\n")


def fail(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing required file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid JSON in {path}: {exc}")
    except Exception as exc:
        fail(f"Failed reading {path}: {exc}")
    if not isinstance(payload, dict):
        fail(f"Expected JSON object in {path}")
    return payload
    raise RuntimeError("unreachable")


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{context} must be an object")
    return value
    raise RuntimeError("unreachable")


def normalize_iso_day_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        fail(f"{context} is missing")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        fail(f"{context} is not an ISO day: {value}")
    return text
    raise RuntimeError("unreachable")


def normalize_optional_iso_day_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def require_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        fail(f"{context} is missing")
    return text
    raise RuntimeError("unreachable")


def require_float(value: Any, *, context: str) -> float:
    if value is None:
        fail(f"{context} is missing")
    text = str(value).strip()
    if not text:
        fail(f"{context} is missing")
    try:
        return float(text)
    except ValueError as exc:
        fail(f"{context} must be numeric (actual={text})")
    raise RuntimeError("unreachable")


def is_cash_like_asset(value: Any) -> bool:
    return str(value or "").strip().upper() in CASH_LIKE_ASSETS


def env_flag(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def resolve_same_run_authority_context(*, expected_closed_day: str) -> dict[str, Any]:
    target_closed_day = normalize_optional_iso_day_text(
        os.environ.get(SAME_RUN_AUTHORITY_TARGET_DAY_ENV)
    )
    run_id = str(os.environ.get(SAME_RUN_AUTHORITY_RUN_ID_ENV) or "").strip() or None
    allow_in_progress = env_flag(SAME_RUN_AUTHORITY_ALLOW_ENV)
    return {
        "allow_in_progress": allow_in_progress,
        "run_id": run_id,
        "target_closed_day": target_closed_day,
        "active": allow_in_progress and target_closed_day == expected_closed_day,
    }


def select_intent_health_blockers(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        source
        for source in execution_blocking_sources(report)
        if str(source.get("source_id") or "").strip() in INTENT_HEALTH_GUARD_SOURCE_IDS
    ]


def load_reference_model(export_contract_path: Path) -> str:
    payload = read_json(export_contract_path)
    contract = payload.get("app_export_contract")
    if not isinstance(contract, dict):
        return DEFAULT_REFERENCE_MODEL
    candidate = str(contract.get("reference_strategy_model") or "").strip()
    return candidate or DEFAULT_REFERENCE_MODEL


def validate_production_snapshot(snapshot: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    artifact_type = str(snapshot.get("artifact_type") or "").strip()
    if artifact_type != "current_strategy_snapshot":
        fail(
            "Execution intent blocked: production snapshot has wrong artifact_type "
            f"(path={source_path} actual={artifact_type or 'missing'})"
        )

    strategy_version = require_text(
        snapshot.get("strategy_version"),
        context="production snapshot strategy_version",
    )
    closed_day = normalize_iso_day_text(
        snapshot.get("closed_day"),
        context="production snapshot closed_day",
    )

    validation = require_mapping(
        snapshot.get("validation"),
        "production snapshot validation",
    )
    validation_status = str(validation.get("status") or "").strip().lower()
    if validation_status != "passed":
        fail(
            "Execution intent blocked: production snapshot validation is not passed "
            f"(path={source_path} status={validation_status or 'missing'})"
        )

    execution_intent = require_mapping(
        snapshot.get("execution_intent"),
        "production snapshot execution_intent",
    )
    signal_id = require_text(
        execution_intent.get("signal_id"),
        context="production snapshot execution_intent.signal_id",
    )
    target_asset = require_text(
        execution_intent.get("target_asset"),
        context="production snapshot execution_intent.target_asset",
    ).upper()
    target_exposure = require_float(
        execution_intent.get("target_exposure"),
        context="production snapshot execution_intent.target_exposure",
    )
    current_asset = require_text(
        snapshot.get("current_asset"),
        context="production snapshot current_asset",
    ).upper()
    candidate_asset = require_text(
        snapshot.get("candidate_asset"),
        context="production snapshot candidate_asset",
    ).upper()
    effective_market_exposure = require_float(
        snapshot.get("effective_market_exposure"),
        context="production snapshot effective_market_exposure",
    )
    model_candidate_exposure = require_float(
        snapshot.get("model_candidate_exposure"),
        context="production snapshot model_candidate_exposure",
    )
    trend_permission_active = bool(snapshot.get("trend_permission_active", False))
    stale_signal = bool(execution_intent.get("stale_signal", False))
    if stale_signal:
        fail(
            "Execution intent blocked: production snapshot execution_intent.stale_signal=true "
            f"(path={source_path} closed_day={closed_day})"
        )

    strategy_status = str(snapshot.get("strategy_status") or "").strip().lower()
    if strategy_status != "ready":
        fail(
            "Execution intent blocked: production snapshot strategy_status is not ready "
            f"(path={source_path} status={strategy_status or 'missing'})"
        )

    allow_live_order_candidate = bool(
        execution_intent.get("allow_live_order_candidate", False)
    )
    if not trend_permission_active:
        if effective_market_exposure > 1e-9:
            fail(
                "Execution intent blocked: production snapshot reports market exposure while "
                f"trend_permission_active=false (path={source_path} exposure={effective_market_exposure})"
            )
        if not is_cash_like_asset(current_asset):
            fail(
                "Execution intent blocked: production snapshot current_asset must be CASH when "
                f"trend_permission_active=false (path={source_path} current_asset={current_asset})"
            )
        if not is_cash_like_asset(target_asset):
            fail(
                "Execution intent blocked: production snapshot execution target must be CASH when "
                f"trend_permission_active=false (path={source_path} target_asset={target_asset})"
            )
        if target_exposure > 1e-9:
            fail(
                "Execution intent blocked: production snapshot execution target exposure must be 0.0 when "
                f"trend_permission_active=false (path={source_path} target_exposure={target_exposure})"
            )
        if allow_live_order_candidate:
            fail(
                "Execution intent blocked: production snapshot allow_live_order_candidate must be false when "
                f"trend_permission_active=false (path={source_path})"
            )
    else:
        if effective_market_exposure <= 1e-9:
            fail(
                "Execution intent blocked: production snapshot effective_market_exposure must be above zero when "
                f"trend_permission_active=true (path={source_path})"
            )
        if is_cash_like_asset(target_asset):
            fail(
                "Execution intent blocked: production snapshot execution target must not be CASH when "
                f"trend_permission_active=true (path={source_path})"
            )

    return {
        "strategy_version": strategy_version,
        "closed_day": closed_day,
        "validation_status": validation_status,
        "signal_id": signal_id,
        "target_asset": target_asset,
        "target_exposure": target_exposure,
        "target_regime": str(snapshot.get("current_regime") or "").strip() or target_asset,
        "stale_signal": stale_signal,
        "allow_live_order_candidate": allow_live_order_candidate,
        "current_asset": current_asset,
        "candidate_asset": candidate_asset,
        "effective_market_exposure": effective_market_exposure,
        "model_candidate_exposure": model_candidate_exposure,
        "trend_permission_active": trend_permission_active,
        "execution_intent": execution_intent,
    }


def validate_authority_alignment(
    *,
    latest_attempt_status: dict[str, Any],
    latest_successful_snapshot: dict[str, Any] | None,
    expected_closed_day: str,
    same_run_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    same_run_authority = same_run_authority or {}
    same_run_active = bool(same_run_authority.get("active"))
    same_run_run_id = str(same_run_authority.get("run_id") or "").strip() or None
    same_run_target_closed_day = str(
        same_run_authority.get("target_closed_day") or ""
    ).strip() or None

    attempt_status = str(
        latest_attempt_status.get("latest_authoritative_attempt_status") or ""
    ).strip().lower()
    attempt_currentness_status = str(
        latest_attempt_status.get("currentness_status") or ""
    ).strip().lower()
    attempt_target_closed_day = normalize_optional_iso_day_text(
        latest_attempt_status.get("target_closed_day_utc")
    )
    attempt_latest_available_closed_day = normalize_optional_iso_day_text(
        latest_attempt_status.get("latest_available_closed_utc_day")
    )
    attempt_run_id = str(latest_attempt_status.get("run_id") or "").strip() or None

    if same_run_active and attempt_status == "in_progress":
        if attempt_currentness_status not in {"", "current", "refresh_in_progress"}:
            fail(
                "Execution intent blocked: authority latest_attempt_status has unsupported "
                "currentness_status during same-run in-progress validation "
                f"(currentness_status={attempt_currentness_status})"
            )
        if attempt_currentness_status == "":
            fail(
                "Execution intent blocked: authority latest_attempt_status currentness_status is missing "
                f"during same-run in-progress validation "
            )
        if (
            attempt_target_closed_day is not None
            and attempt_target_closed_day != expected_closed_day
        ):
            fail(
                "Execution intent blocked: authority latest_attempt_status target day diverged "
                f"during same-run in-progress validation "
                f"(attempt_target={attempt_target_closed_day} snapshot={expected_closed_day})"
            )
        if (
            attempt_latest_available_closed_day is not None
            and attempt_latest_available_closed_day != expected_closed_day
        ):
            fail(
                "Execution intent blocked: authority latest_attempt_status latest available day diverged "
                f"during same-run in-progress validation "
                f"(attempt_latest_available={attempt_latest_available_closed_day} snapshot={expected_closed_day})"
            )
        if same_run_run_id and attempt_run_id and attempt_run_id != same_run_run_id:
            fail(
                "Execution intent blocked: authority latest_attempt_status run_id diverged "
                f"from the current authoritative run "
                f"(attempt_run_id={attempt_run_id} current_run_id={same_run_run_id})"
            )

        success_payload = (
            latest_successful_snapshot if isinstance(latest_successful_snapshot, dict) else {}
        )
        success_target_closed_day = normalize_optional_iso_day_text(
            success_payload.get("target_closed_day_utc")
        )
        success_latest_available_closed_day = normalize_optional_iso_day_text(
            success_payload.get("latest_available_closed_utc_day")
        )
        success_attempt_status = str(
            success_payload.get("latest_authoritative_attempt_status") or ""
        ).strip().lower()
        success_currentness_status = str(
            success_payload.get("currentness_status") or ""
        ).strip().lower()

        return {
            "attempt_status": attempt_status,
            "attempt_currentness_status": attempt_currentness_status or "current",
            "attempt_target_closed_day": attempt_target_closed_day or expected_closed_day,
            "attempt_latest_available_closed_day": (
                attempt_latest_available_closed_day or expected_closed_day
            ),
            "success_currentness_status": success_currentness_status or None,
            "success_target_closed_day": success_target_closed_day,
            "success_latest_available_closed_day": success_latest_available_closed_day,
            "success_attempt_status": success_attempt_status or None,
            "aligned_closed_day": expected_closed_day,
            "authority_alignment_mode": "same_run_in_progress",
            "same_run_authority_allowed": True,
            "same_run_authority_run_id": same_run_run_id,
            "same_run_authority_target_closed_day": same_run_target_closed_day,
        }

    attempt_target_closed_day = normalize_iso_day_text(
        latest_attempt_status.get("target_closed_day_utc"),
        context="latest_attempt_status.target_closed_day_utc",
    )
    attempt_latest_available_closed_day = normalize_iso_day_text(
        latest_attempt_status.get("latest_available_closed_utc_day"),
        context="latest_attempt_status.latest_available_closed_utc_day",
    )
    if not isinstance(latest_successful_snapshot, dict):
        fail(
            "Execution intent blocked: authority latest_successful_snapshot is missing "
            "outside same-run in-progress validation"
        )
    success_target_closed_day = normalize_iso_day_text(
        latest_successful_snapshot.get("target_closed_day_utc"),
        context="latest_successful_snapshot.target_closed_day_utc",
    )
    success_latest_available_closed_day = normalize_iso_day_text(
        latest_successful_snapshot.get("latest_available_closed_utc_day"),
        context="latest_successful_snapshot.latest_available_closed_utc_day",
    )
    success_attempt_status = str(
        latest_successful_snapshot.get("latest_authoritative_attempt_status") or ""
    ).strip().lower()
    success_currentness_status = str(
        latest_successful_snapshot.get("currentness_status") or ""
    ).strip().lower()

    if attempt_currentness_status != "current":
        fail(
            "Execution intent blocked: authority latest_attempt_status is not current "
            f"(currentness_status={attempt_currentness_status or 'missing'})"
        )
    if success_attempt_status != "success":
        fail(
            "Execution intent blocked: authority latest_successful_snapshot is not successful "
            f"(latest_authoritative_attempt_status={success_attempt_status or 'missing'})"
        )
    if success_currentness_status != "current":
        fail(
            "Execution intent blocked: authority latest_successful_snapshot is not current "
            f"(currentness_status={success_currentness_status or 'missing'})"
        )

    aligned_days = {
        expected_closed_day,
        attempt_target_closed_day,
        attempt_latest_available_closed_day,
        success_target_closed_day,
        success_latest_available_closed_day,
    }
    if len(aligned_days) != 1:
        fail(
            "Execution intent blocked: production snapshot closed_day is not aligned with authority day "
            f"(snapshot={expected_closed_day} attempt_target={attempt_target_closed_day} "
            f"attempt_latest_available={attempt_latest_available_closed_day} "
            f"success_target={success_target_closed_day} "
            f"success_latest_available={success_latest_available_closed_day})"
        )

    return {
        "attempt_status": attempt_status,
        "attempt_currentness_status": attempt_currentness_status,
        "attempt_target_closed_day": attempt_target_closed_day,
        "attempt_latest_available_closed_day": attempt_latest_available_closed_day,
        "success_currentness_status": success_currentness_status,
        "success_target_closed_day": success_target_closed_day,
        "success_latest_available_closed_day": success_latest_available_closed_day,
        "success_attempt_status": success_attempt_status,
        "aligned_closed_day": expected_closed_day,
        "authority_alignment_mode": "published_authority_snapshot",
        "same_run_authority_allowed": False,
        "same_run_authority_run_id": same_run_run_id,
        "same_run_authority_target_closed_day": same_run_target_closed_day,
    }


def write_fail_closed_intent(
    *,
    started_at: str,
    strategy_model: str,
    reference_model: str,
    blocked_reason: str,
    input_paths: list[str],
    source_paths: dict[str, str],
    authority_day_context: dict[str, Any] | None,
    output_intent_path: Path,
    output_quality_path: Path,
    output_manifest_path: Path,
) -> None:
    output_intent_path.parent.mkdir(parents=True, exist_ok=True)
    output_quality_path.parent.mkdir(parents=True, exist_ok=True)
    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)

    intent = {
        "intent_type": "normalized_execution_intent",
        "intent_status": "blocked",
        "generated_at_utc": utc_now_iso(),
        "as_of_source": None,
        "execution_mode": "read_only_intent_only",
        "trading_enabled": False,
        "kill_switch_required": True,
        "strategy_model": strategy_model,
        "reference_model": reference_model,
        "benchmark": "BTC",
        "signal_id": None,
        "target_asset": None,
        "target_side": "long_only_hold_selected_asset_or_cash",
        "target_regime": None,
        "size_mode": "not_computed_yet",
        "target_size_pct": None,
        "target_notional_usd": None,
        "reference_asset": None,
        "staleness_ok": False,
        "stale_signal": True,
        "allow_live_order_candidate": False,
        "blocked_reason": blocked_reason,
        "guardrail_flags": {
            "contract_validated": False,
            "trading_disabled": True,
            "kill_switch_required": True,
            "manual_approval_required_for_live_orders": True,
            "leverage_live_truth_allowed": False,
            "production_snapshot_validated": False,
        },
        "source_paths": source_paths,
        "authority_day_context": authority_day_context,
        "source_samples": {},
        "notes": [
            "Intent generation was blocked fail-closed.",
            blocked_reason,
        ],
    }

    quality = {
        "intent_ok": False,
        "intent_status": "blocked",
        "strategy_model": strategy_model,
        "signal_id_present": False,
        "target_asset_present": False,
        "target_regime_present": False,
        "target_size_present": False,
        "staleness_ok": False,
        "trading_enabled": False,
        "kill_switch_required": True,
        "leverage_live_truth_allowed": False,
        "production_snapshot_validation_status": "failed_or_missing",
        "strategy_signal_source_path": source_paths.get("production_snapshot"),
        "blocked_reason": blocked_reason,
        "authority_day_context": authority_day_context,
    }

    manifest = {
        "artifact_name": "latest_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": input_paths,
        "output_paths": [
            str(output_intent_path.resolve()),
            str(output_quality_path.resolve()),
            str(output_manifest_path.resolve()),
        ],
        "status": "blocked",
        "authority_day_context": authority_day_context,
    }

    output_intent_path.write_text(
        json.dumps(intent, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    output_quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    output_manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def fail_closed_intent(
    blocked_reason: str,
    *,
    started_at: str,
    strategy_model: str,
    reference_model: str,
    input_paths: list[str],
    source_paths: dict[str, str],
    authority_day_context: dict[str, Any] | None,
    output_intent_path: Path,
    output_quality_path: Path,
    output_manifest_path: Path,
) -> None:
    write_fail_closed_intent(
        started_at=started_at,
        strategy_model=strategy_model,
        reference_model=reference_model,
        blocked_reason=blocked_reason,
        input_paths=input_paths,
        source_paths=source_paths,
        authority_day_context=authority_day_context,
        output_intent_path=output_intent_path,
        output_quality_path=output_quality_path,
        output_manifest_path=output_manifest_path,
    )
    fail(blocked_reason)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build fail-closed execution intent from the Production Core v1 current strategy snapshot."
        )
    )
    parser.add_argument(
        "--export-contract-path",
        type=Path,
        default=EXPORT_CONTRACT_PATH,
    )
    parser.add_argument(
        "--production-snapshot-path",
        type=Path,
        default=PRODUCTION_SNAPSHOT_PATH,
    )
    parser.add_argument(
        "--authority-latest-successful-snapshot-path",
        type=Path,
        default=AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH,
    )
    parser.add_argument(
        "--authority-latest-attempt-status-path",
        type=Path,
        default=AUTHORITY_LATEST_ATTEMPT_STATUS_PATH,
    )
    parser.add_argument("--intent-path", type=Path, default=INTENT_PATH)
    parser.add_argument("--quality-path", type=Path, default=QUALITY_PATH)
    parser.add_argument("--manifest-path", type=Path, default=MANIFEST_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    INTENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] build_execution_intent_from_strategy_exports")

    reference_model = load_reference_model(args.export_contract_path)
    input_paths = [
        str(args.export_contract_path.resolve()),
        str(args.production_snapshot_path.resolve()),
        str(args.authority_latest_successful_snapshot_path.resolve()),
        str(args.authority_latest_attempt_status_path.resolve()),
        str((PRODUCTION_DIR / DATA_HEALTH_REPORT_PATH.name).resolve()),
    ]
    source_paths = {
        "production_snapshot": str(args.production_snapshot_path.resolve()),
        "authority_latest_successful_snapshot": str(
            args.authority_latest_successful_snapshot_path.resolve()
        ),
        "authority_latest_attempt_status": str(
            args.authority_latest_attempt_status_path.resolve()
        ),
        "data_health_report": str((PRODUCTION_DIR / DATA_HEALTH_REPORT_PATH.name).resolve()),
    }

    strategy_model = "unknown"
    authority_day_context: dict[str, Any] | None = None

    try:
        production_snapshot = read_json(args.production_snapshot_path)
        snapshot_context = validate_production_snapshot(
            production_snapshot,
            source_path=args.production_snapshot_path,
        )
        strategy_model = snapshot_context["strategy_version"]
        same_run_authority = resolve_same_run_authority_context(
            expected_closed_day=snapshot_context["closed_day"]
        )

        data_health_bundle = build_report_bundle(
            root=ROOT,
            output_dir=PRODUCTION_DIR,
            write_outputs=True,
        )
        data_health_report = data_health_bundle["report"]
        health_blockers = select_intent_health_blockers(data_health_report)
        if health_blockers:
            blocker_summary = " | ".join(
                f"{item['source_id']}:{item['status']}" for item in health_blockers
            )
            fail_closed_intent(
                f"Execution intent blocked by data_health_report: {blocker_summary}",
                started_at=started_at,
                strategy_model=strategy_model,
                reference_model=reference_model,
                input_paths=input_paths,
                source_paths=source_paths,
                authority_day_context=authority_day_context,
                output_intent_path=args.intent_path,
                output_quality_path=args.quality_path,
                output_manifest_path=args.manifest_path,
            )

        latest_attempt_status = read_json(args.authority_latest_attempt_status_path)
        allow_in_progress_same_run = (
            bool(same_run_authority.get("active"))
            and str(
                latest_attempt_status.get("latest_authoritative_attempt_status") or ""
            )
            .strip()
            .lower()
            == "in_progress"
        )
        latest_successful_snapshot = (
            read_json_if_exists(args.authority_latest_successful_snapshot_path)
            if allow_in_progress_same_run
            else read_json(args.authority_latest_successful_snapshot_path)
        )
        authority_day_context = validate_authority_alignment(
            latest_attempt_status=latest_attempt_status,
            latest_successful_snapshot=latest_successful_snapshot,
            expected_closed_day=snapshot_context["closed_day"],
            same_run_authority=same_run_authority,
        )
    except SystemExit:
        raise
    except Exception as exc:
        fail_closed_intent(
            f"Execution intent blocked: failed to validate production snapshot contract ({type(exc).__name__}: {exc})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths,
            source_paths=source_paths,
            authority_day_context=authority_day_context,
            output_intent_path=args.intent_path,
            output_quality_path=args.quality_path,
            output_manifest_path=args.manifest_path,
        )

    intent = {
        "intent_type": "normalized_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "as_of_source": snapshot_context["closed_day"],
        "execution_mode": "read_only_intent_only",
        "trading_enabled": False,
        "kill_switch_required": True,
        "strategy_model": snapshot_context["strategy_version"],
        "reference_model": reference_model,
        "benchmark": "BTC",
        "signal_id": snapshot_context["signal_id"],
        "target_asset": snapshot_context["target_asset"],
        "target_side": (
            "hold_cash_no_market_entry"
            if is_cash_like_asset(snapshot_context["target_asset"])
            else "long_only_hold_selected_asset_or_cash"
        ),
        "target_regime": snapshot_context["target_regime"],
        "size_mode": "production_snapshot_target_exposure",
        "target_size_pct": snapshot_context["target_exposure"],
        "target_notional_usd": None,
        "reference_asset": None,
        "staleness_ok": True,
        "stale_signal": False,
        "allow_live_order_candidate": snapshot_context["allow_live_order_candidate"],
        "guardrail_flags": {
            "contract_validated": True,
            "trading_disabled": True,
            "kill_switch_required": True,
            "manual_approval_required_for_live_orders": True,
            "leverage_live_truth_allowed": False,
            "production_snapshot_validated": True,
            "same_run_authority_allowed": bool(
                authority_day_context.get("same_run_authority_allowed")
            ),
            "same_run_authority_run_id": authority_day_context.get(
                "same_run_authority_run_id"
            ),
            "same_run_authority_target_closed_day": authority_day_context.get(
                "same_run_authority_target_closed_day"
            ),
        },
        "source_fingerprints": {
            "production_snapshot_sha256": sha256_file(args.production_snapshot_path),
        },
        "source_paths": source_paths,
        "authority_day_context": authority_day_context,
        "source_samples": {
            "production_snapshot_execution_intent": snapshot_context["execution_intent"],
            "production_snapshot_summary": {
                "strategy_status": production_snapshot.get("strategy_status"),
                "candidate_asset": production_snapshot.get("candidate_asset"),
                "current_asset": production_snapshot.get("current_asset"),
                "effective_market_exposure": production_snapshot.get("effective_market_exposure"),
                "trend_permission_active": production_snapshot.get("trend_permission_active"),
                "current_regime": production_snapshot.get("current_regime"),
                "validation_status": (
                    require_mapping(
                        production_snapshot.get("validation"),
                        "production snapshot validation",
                    ).get("status")
                ),
            },
        },
        "notes": [
            "Deterministic intent from outputs/production/current_strategy_snapshot.json.",
            "Execution signal truth no longer reads canonical app_exports directly.",
            "Authority target day must match production snapshot closed_day.",
            "No order sizing beyond production snapshot target exposure is inferred here.",
            "If trend permission is inactive, the execution target must stay in CASH with 0.0 exposure.",
            "No live order execution is allowed by this script.",
        ],
    }

    quality = {
        "intent_ok": True,
        "strategy_model": intent["strategy_model"],
        "signal_id_present": bool(intent["signal_id"]),
        "target_asset_present": bool(intent["target_asset"]),
        "target_regime_present": bool(intent["target_regime"]),
        "target_size_present": intent["target_size_pct"] is not None,
        "staleness_ok": bool(intent["staleness_ok"]),
        "trading_enabled": bool(intent["trading_enabled"]),
        "kill_switch_required": bool(intent["kill_switch_required"]),
        "leverage_live_truth_allowed": False,
        "production_snapshot_validation_status": "passed",
        "authority_currentness_status": authority_day_context["attempt_currentness_status"],
        "strategy_signal_source_path": source_paths["production_snapshot"],
        "production_snapshot_sha256_matches_intent": True,
    }

    manifest = {
        "artifact_name": "latest_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": input_paths,
        "output_paths": [
            str(args.intent_path.resolve()),
            str(args.quality_path.resolve()),
            str(args.manifest_path.resolve()),
        ],
        "status": "success",
        "authority_day_context": authority_day_context,
    }

    args.intent_path.parent.mkdir(parents=True, exist_ok=True)
    args.quality_path.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    args.intent_path.write_text(
        json.dumps(intent, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    args.quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    args.manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log(f"[SAVED] {args.intent_path}")
    log(f"[SAVED] {args.quality_path}")
    log(f"[SAVED] {args.manifest_path}")
    log(
        "[END] build_execution_intent_from_strategy_exports success "
        f"target_asset={intent['target_asset']} closed_day={intent['as_of_source']}"
    )


if __name__ == "__main__":
    main()
