from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.execution.runtime_path_resolution import (
    format_path_resolution_message,
    resolve_registry_artifact_path,
    resolve_runtime_path,
)
from scripts.execution.current_strategy_root_contract import (
    load_current_main_strategy_root_contract,
    validate_authoritative_dependency_closure,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
OUTPUTS_DIR = ROOT / "outputs" / "execution"
INTENTS_DIR = OUTPUTS_DIR / "intents"
LOGS_DIR = OUTPUTS_DIR / "logs"

PATHS_REGISTRY_PATH = SOURCE_OF_TRUTH_DIR / "paths_registry.json"
EXPORT_CONTRACT_PATH = SOURCE_OF_TRUTH_DIR / "export_contract.json"

INTENT_PATH = INTENTS_DIR / "latest_execution_intent.json"
QUALITY_PATH = INTENTS_DIR / "latest_execution_intent_quality.json"
MANIFEST_PATH = INTENTS_DIR / "latest_execution_intent_manifest.json"
LOG_PATH = LOGS_DIR / "build_execution_intent_from_strategy_exports.log"
AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH = (
    ROOT / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
)
AUTHORITY_LATEST_ATTEMPT_STATUS_PATH = (
    ROOT / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
)
APP_FRESHNESS_REPORT_PATH = ROOT / "outputs" / "execution" / "freshness" / "app_freshness_report.json"
APP_REFRESH_PIPELINE_DIR = ROOT / "outputs" / "app_refresh_pipeline"
ALLOW_IN_PROGRESS_AUTHORITY_ENV = "MRV1_ALLOW_IN_PROGRESS_AUTHORITY_FOR_SAME_RUN"
CURRENT_AUTHORITY_RUN_ID_ENV = "MRV1_CURRENT_AUTHORITY_RUN_ID"
CURRENT_AUTHORITY_TARGET_CLOSED_DAY_ENV = "MRV1_CURRENT_AUTHORITY_TARGET_CLOSED_DAY"


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def log(msg: str) -> None:
    print(msg)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def fail(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    sys.exit(code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"Missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"Invalid JSON in {path}: {e}")
    except Exception as e:
        fail(f"Failed reading {path}: {e}")
    raise RuntimeError("unreachable")


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        fail(f"Missing required CSV: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = list(reader)
            return header, rows
    except Exception as e:
        fail(f"Failed reading CSV {path}: {e}")
    raise RuntimeError("unreachable")


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


def strict_normalize_iso_day_text(value: Any, *, context: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{context} is missing")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) != 10:
        raise ValueError(f"{context} is not an ISO day: {value}")
    return text


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def load_json_strict(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def read_csv_rows_strict(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required CSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)
        return header, rows


def read_required_csv_last_day(
    path: Path,
    *,
    context: str,
    day_candidates: list[str],
) -> str:
    header, rows = read_csv_rows_strict(path)
    if not rows:
        raise ValueError(f"{context} has no rows: {path}")
    last_row = rows[-1]
    column = find_column(header, day_candidates)
    if column is None:
        raise ValueError(
            f"{context} is missing supported day columns: {', '.join(day_candidates)}"
        )
    value = str(last_row.get(column, "")).strip()
    if not value:
        raise ValueError(f"{context}.{column} is missing in last row")
    return strict_normalize_iso_day_text(value, context=f"{context}.{column}")


def normalize_optional_resolved_path_text(raw_path: Any) -> str | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    try:
        return str(Path(text).resolve())
    except Exception:
        return text


def evaluate_same_run_in_progress_authority_allowance(
    *,
    latest_attempt_status: dict[str, Any],
    main_paper_path: Path,
    app_freshness_report_path: Path,
) -> dict[str, Any]:
    evaluation: dict[str, Any] = {
        "requested": env_flag_enabled(ALLOW_IN_PROGRESS_AUTHORITY_ENV),
        "allowed": False,
        "same_run_allowance_applied": False,
        "decision_reason": "allowance_not_requested",
        "live_order_execution_permitted": False,
        "authority_mode": str(os.environ.get("MRV1_AUTHORITY_MODE") or "").strip().lower(),
        "automatic_producer_id": str(os.environ.get("MRV1_AUTOMATIC_PRODUCER_ID") or "").strip().lower(),
        "expected_run_id": str(os.environ.get(CURRENT_AUTHORITY_RUN_ID_ENV) or "").strip(),
        "expected_target_closed_day_utc": str(
            os.environ.get(CURRENT_AUTHORITY_TARGET_CLOSED_DAY_ENV) or ""
        ).strip(),
        "attempt_run_id": str(latest_attempt_status.get("run_id") or "").strip(),
        "attempt_source_manifest_path": normalize_optional_resolved_path_text(
            latest_attempt_status.get("source_manifest_path")
        ),
        "attempt_target_closed_day_utc": str(
            latest_attempt_status.get("target_closed_day_utc") or ""
        ).strip(),
        "attempt_latest_available_closed_utc_day": str(
            latest_attempt_status.get("latest_available_closed_utc_day") or ""
        ).strip(),
        "attempt_currentness_status": str(
            latest_attempt_status.get("currentness_status") or ""
        ).strip().lower(),
        "attempt_status": str(
            latest_attempt_status.get("latest_authoritative_attempt_status") or ""
        ).strip().lower(),
    }

    expected_run_id = str(evaluation["expected_run_id"])
    if expected_run_id:
        expected_manifest_path = (
            APP_REFRESH_PIPELINE_DIR / expected_run_id / "app_refresh_pipeline_manifest.json"
        ).resolve()
        evaluation["expected_source_manifest_path"] = str(expected_manifest_path)
    else:
        expected_manifest_path = None
        evaluation["expected_source_manifest_path"] = None

    if not evaluation["requested"]:
        return evaluation

    try:
        expected_target_closed_day = strict_normalize_iso_day_text(
            evaluation["expected_target_closed_day_utc"],
            context=CURRENT_AUTHORITY_TARGET_CLOSED_DAY_ENV,
        )
        evaluation["expected_target_closed_day_utc"] = expected_target_closed_day

        same_run_match = False
        same_run_match_via = None
        if expected_run_id and evaluation["attempt_run_id"] == expected_run_id:
            same_run_match = True
            same_run_match_via = "run_id"
        elif (
            expected_manifest_path is not None
            and evaluation["attempt_source_manifest_path"] == str(expected_manifest_path)
        ):
            same_run_match = True
            same_run_match_via = "source_manifest_path"
        evaluation["same_run_match"] = same_run_match
        evaluation["same_run_match_via"] = same_run_match_via

        main_paper_last_day = read_required_csv_last_day(
            main_paper_path,
            context="canonical main strategy paper",
            day_candidates=["date"],
        )
        evaluation["main_paper_last_day"] = main_paper_last_day

        freshness_report = load_json_strict(app_freshness_report_path)
        freshness_report_day = strict_normalize_iso_day_text(
            freshness_report.get("latest_closed_utc_date"),
            context="canonical freshness report latest_closed_utc_date",
        )
        freshness_report_status = str(freshness_report.get("status") or "").strip().lower()
        freshness_report_errors = freshness_report.get("errors")
        freshness_report_has_errors = bool(
            isinstance(freshness_report_errors, list) and freshness_report_errors
        )
        evaluation["freshness_report_day"] = freshness_report_day
        evaluation["freshness_report_status"] = freshness_report_status
        evaluation["freshness_report_has_errors"] = freshness_report_has_errors

        decision_checks = [
            (
                evaluation["authority_mode"] == "authoritative"
                and evaluation["automatic_producer_id"] == "raspberry_pi",
                "not_pi_authoritative_post_refresh_context",
            ),
            (bool(expected_run_id), "missing_current_authority_run_id"),
            (same_run_match, "same_run_identity_mismatch"),
            (
                evaluation["attempt_status"] == "in_progress",
                "latest_authoritative_attempt_status_not_in_progress",
            ),
            (
                evaluation["attempt_currentness_status"] == "refresh_in_progress",
                "currentness_status_not_refresh_in_progress",
            ),
            (
                strict_normalize_iso_day_text(
                    evaluation["attempt_target_closed_day_utc"],
                    context="latest_attempt_status.target_closed_day_utc",
                )
                == expected_target_closed_day,
                "target_closed_day_mismatch",
            ),
            (
                strict_normalize_iso_day_text(
                    evaluation["attempt_latest_available_closed_utc_day"],
                    context="latest_attempt_status.latest_available_closed_utc_day",
                )
                == expected_target_closed_day,
                "latest_available_closed_day_mismatch",
            ),
            (
                main_paper_last_day == expected_target_closed_day,
                "canonical_main_strategy_paper_not_current",
            ),
            (
                freshness_report_day == expected_target_closed_day,
                "canonical_freshness_report_not_current",
            ),
            (
                freshness_report_status in {"ok", "success", "current"},
                "canonical_freshness_report_not_green",
            ),
            (
                not freshness_report_has_errors,
                "canonical_freshness_report_contains_errors",
            ),
        ]
        for passed, reason in decision_checks:
            if not passed:
                evaluation["decision_reason"] = reason
                return evaluation

        evaluation["allowed"] = True
        evaluation["same_run_allowance_applied"] = True
        evaluation["decision_reason"] = "accepted_same_run_in_progress_authority_allowance"
        evaluation["notes"] = [
            "Same-run in-progress authority allowance was accepted only for read-only intent generation.",
            "This intent builder still emits trading_enabled=false and does not enable live order placement.",
        ]
        return evaluation
    except Exception as exc:
        evaluation["decision_reason"] = (
            f"allowance_validation_error::{type(exc).__name__}: {exc}"
        )
        return evaluation


def normalize_key(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


def find_column(header: list[str], candidates: list[str]) -> str | None:
    normalized_map = {normalize_key(col): col for col in header}
    for candidate in candidates:
        found = normalized_map.get(normalize_key(candidate))
        if found:
            return found
    return None


def first_nonempty(row: dict[str, str], columns: list[str]) -> str | None:
    for col in columns:
        value = str(row.get(col, "")).strip()
        if value:
            return value
    return None


def load_registered_path(
    artifacts: dict[str, Any],
    artifact_key: str,
    *,
    diagnostics: list[dict[str, Any]],
) -> Path:
    entry = artifacts.get(artifact_key)
    if not isinstance(entry, dict):
        fail(f"paths_registry.json missing artifact entry: {artifact_key}")
    canonical_raw = entry.get("canonical")
    if not isinstance(canonical_raw, str) or not canonical_raw.strip():
        fail(f"Artifact {artifact_key} missing canonical path")
    resolved_path, diagnostic = resolve_registry_artifact_path(
        artifact_key,
        entry,
        root=ROOT,
        context=f"registry:{artifact_key}",
    )
    diagnostics.append(diagnostic)
    return resolved_path


def load_app_export_contract() -> dict[str, Any]:
    payload = read_json(EXPORT_CONTRACT_PATH)
    contract = payload.get("app_export_contract") if isinstance(payload, dict) else None
    if not isinstance(contract, dict):
        fail("export_contract.json missing app_export_contract object")
    return contract


def load_model_source_path_strict(
    contract: dict[str, Any],
    *,
    model_key: str,
    field_name: str,
    diagnostics: list[dict[str, Any]],
) -> Path:
    model_sources = contract.get("model_sources")
    if not isinstance(model_sources, dict):
        fail("export_contract.json missing app_export_contract.model_sources")

    source_cfg = model_sources.get(model_key)
    if not isinstance(source_cfg, dict):
        fail(f"export_contract.json missing model_sources entry for {model_key}")

    raw_path = source_cfg.get(field_name)
    if not isinstance(raw_path, str) or not raw_path.strip():
        fail(f"export_contract.json missing {model_key}.{field_name}")
    resolved_path, diagnostic = resolve_runtime_path(
        raw_path,
        root=ROOT,
        context=f"contract:{model_key}.{field_name}",
    )
    diagnostics.append(diagnostic)
    return resolved_path


def write_fail_closed_intent(
    *,
    started_at: str,
    strategy_model: str,
    reference_model: str,
    blocked_reason: str,
    input_paths: list[str],
    source_paths: dict[str, str],
    path_resolution_diagnostics: list[dict[str, Any]],
    authority_currentness_evaluation: dict[str, Any] | None = None,
) -> None:
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
        "blocked_reason": blocked_reason,
        "guardrail_flags": {
            "contract_validated": False,
            "trading_disabled": True,
            "kill_switch_required": True,
            "manual_approval_required_for_live_orders": True,
            "leverage_live_truth_allowed": False,
        },
        "source_paths": source_paths,
        "path_resolution_diagnostics": path_resolution_diagnostics,
        "authority_currentness_evaluation": authority_currentness_evaluation,
        "resolved_columns": {},
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
        "staleness_ok": False,
        "trading_enabled": False,
        "kill_switch_required": True,
        "leverage_live_truth_allowed": False,
        "blocked_reason": blocked_reason,
        "authority_currentness_evaluation": authority_currentness_evaluation,
    }
    manifest = {
        "artifact_name": "latest_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": input_paths,
        "output_paths": [
            str(INTENT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve()),
        ],
        "status": "blocked",
        "authority_currentness_evaluation": authority_currentness_evaluation,
    }
    INTENT_PATH.write_text(json.dumps(intent, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def fail_closed_intent(
    blocked_reason: str,
    *,
    started_at: str,
    strategy_model: str,
    reference_model: str,
    input_paths: list[str],
    source_paths: dict[str, str],
    path_resolution_diagnostics: list[dict[str, Any]],
    authority_currentness_evaluation: dict[str, Any] | None = None,
) -> None:
    write_fail_closed_intent(
        started_at=started_at,
        strategy_model=strategy_model,
        reference_model=reference_model,
        blocked_reason=blocked_reason,
        input_paths=input_paths,
        source_paths=source_paths,
        path_resolution_diagnostics=path_resolution_diagnostics,
        authority_currentness_evaluation=authority_currentness_evaluation,
    )
    fail(blocked_reason)


def derive_target_asset(
    live_last: dict[str, str],
    paper_last: dict[str, str],
    status_asset_col: str | None,
    status_execution_state_col: str | None,
    paper_asset_col: str | None,
    paper_position_col: str | None,
) -> str:
    live_asset = first_nonempty(live_last, [status_asset_col] if status_asset_col else [])
    live_state = first_nonempty(
        live_last,
        [status_execution_state_col] if status_execution_state_col else []
    )
    paper_asset = first_nonempty(paper_last, [paper_asset_col] if paper_asset_col else [])
    paper_position = first_nonempty(
        paper_last,
        [paper_position_col] if paper_position_col else []
    )

    if live_asset:
        return live_asset
    if live_state:
        return live_state
    if paper_asset:
        return paper_asset
    if paper_position:
        return paper_position

    fail("Could not determine target asset/state from current strategy exports.")
    raise RuntimeError("unreachable")


def main() -> None:
    INTENTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    started_at = utc_now_iso()
    log("[START] build_execution_intent_from_strategy_exports")

    contract = load_app_export_contract()
    current_strategy_contract = load_current_main_strategy_root_contract(root=ROOT)
    path_resolution_diagnostics: list[dict[str, Any]] = []
    strategy_model = str(
        contract.get("main_model_key") or contract.get("main_strategy_model") or ""
    ).strip()
    reference_model = str(
        contract.get("reference_model_key") or contract.get("reference_strategy_model") or ""
    ).strip()
    if not strategy_model:
        fail("export_contract.json missing current main strategy model")
    if not reference_model:
        fail("export_contract.json missing reference strategy model")

    if strategy_model != str(current_strategy_contract["main_strategy_model"]).strip():
        fail(
            "Execution intent blocked: export contract main model diverged from current main strategy contract "
            f"(export_contract={strategy_model} current_strategy_contract={current_strategy_contract['main_strategy_model']})"
        )

    main_paper_path = Path(current_strategy_contract["paper_path"])
    path_resolution_diagnostics.append(
        {
            "context": f"contract:{strategy_model}.paper_path",
            "original_path": str(current_strategy_contract["canonical_paper_source_path"]),
            "resolved_path": str(main_paper_path.resolve()),
            "reason": "resolved_from_current_main_strategy_root_contract",
            "exists": main_paper_path.exists(),
            "selected_source_path": str(main_paper_path.resolve()),
        }
    )
    main_live_status_path = load_model_source_path_strict(
        contract,
        model_key=strategy_model,
        field_name="live_status_path",
        diagnostics=path_resolution_diagnostics,
    )
    reference_paper_path = load_model_source_path_strict(
        contract,
        model_key=reference_model,
        field_name="paper_path",
        diagnostics=path_resolution_diagnostics,
    )
    app_freshness_report_path = APP_FRESHNESS_REPORT_PATH
    path_resolution_diagnostics.append(
        {
            "context": "canonical:app_freshness_report",
            "original_path": str(APP_FRESHNESS_REPORT_PATH),
            "resolved_path": str(APP_FRESHNESS_REPORT_PATH.resolve()),
            "reason": "canonical_execution_freshness_report_path",
            "exists": APP_FRESHNESS_REPORT_PATH.exists(),
            "selected_source_path": str(APP_FRESHNESS_REPORT_PATH.resolve()),
        }
    )

    for diagnostic in path_resolution_diagnostics:
        log(format_path_resolution_message(diagnostic))

    input_paths_for_failure = [
        str(EXPORT_CONTRACT_PATH.resolve()),
        str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
        str(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH.resolve()),
        str(main_paper_path.resolve()),
        str(main_live_status_path.resolve()),
        str(reference_paper_path.resolve()),
        str(app_freshness_report_path.resolve()),
    ]
    source_paths_for_failure = {
        "strategy_paper": str(main_paper_path.resolve()),
        "strategy_live_status": str(main_live_status_path.resolve()),
        "reference_paper": str(reference_paper_path.resolve()),
        "app_freshness_report": str(app_freshness_report_path.resolve()),
        "authority_latest_successful_snapshot": str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
        "authority_latest_attempt_status": str(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH.resolve()),
    }

    latest_attempt_status = read_json(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH)
    attempt_currentness_status = str(latest_attempt_status.get("currentness_status") or "").strip().lower()
    attempt_target_closed_day = normalize_iso_day_text(
        latest_attempt_status.get("target_closed_day_utc"),
        context="latest_attempt_status.target_closed_day_utc",
    )
    attempt_latest_available_closed_day = normalize_iso_day_text(
        latest_attempt_status.get("latest_available_closed_utc_day"),
        context="latest_attempt_status.latest_available_closed_utc_day",
    )
    authority_currentness_evaluation = evaluate_same_run_in_progress_authority_allowance(
        latest_attempt_status=latest_attempt_status,
        main_paper_path=main_paper_path,
        app_freshness_report_path=app_freshness_report_path,
    )
    authority_target_closed_day: str
    authority_strategy_closed_day: str | None
    authority_freshness_closed_day: str | None

    if attempt_currentness_status == "current":
        latest_successful_snapshot = read_json(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH)
        authority_product_snapshot = require_mapping(
            latest_successful_snapshot.get("app_product_snapshot"),
            "latest_successful_snapshot.app_product_snapshot",
        )
        try:
            validate_authoritative_dependency_closure(
                authority_product_snapshot,
                current_strategy_contract,
                root=ROOT,
                context="Execution intent blocked:",
            )
        except Exception as exc:
            fail_closed_intent(
                str(exc),
                started_at=started_at,
                strategy_model=strategy_model,
                reference_model=reference_model,
                input_paths=input_paths_for_failure,
                source_paths=source_paths_for_failure,
                path_resolution_diagnostics=path_resolution_diagnostics,
                authority_currentness_evaluation=authority_currentness_evaluation,
            )

        authority_target_closed_day = normalize_iso_day_text(
            latest_successful_snapshot.get("target_closed_day_utc"),
            context="latest_successful_snapshot.target_closed_day_utc",
        )
        authority_strategy_closed_day = normalize_iso_day_text(
            authority_product_snapshot.get("strategy_last_closed_day"),
            context="latest_successful_snapshot.app_product_snapshot.strategy_last_closed_day",
        )
        authority_freshness_closed_day = normalize_iso_day_text(
            authority_product_snapshot.get("freshness_target_closed_day"),
            context="latest_successful_snapshot.app_product_snapshot.freshness_target_closed_day",
        )
    elif authority_currentness_evaluation.get("allowed"):
        authority_target_closed_day = str(
            authority_currentness_evaluation["expected_target_closed_day_utc"]
        )
        authority_strategy_closed_day = None
        authority_freshness_closed_day = None
        log(
            "[AUTHORITY_CURRENTNESS] "
            "accepted_same_run_in_progress_authority_allowance "
            f"run_id={authority_currentness_evaluation.get('expected_run_id')} "
            f"match_via={authority_currentness_evaluation.get('same_run_match_via')} "
            f"target_closed_day_utc={authority_target_closed_day}"
        )
    else:
        blocked_reason = (
            "Execution intent blocked: authority currentness is not current "
            f"(currentness_status={attempt_currentness_status or 'missing'})"
        )
        allowance_reason = str(
            authority_currentness_evaluation.get("decision_reason") or ""
        ).strip()
        if allowance_reason:
            blocked_reason += f" allowance_reason={allowance_reason}"
        fail_closed_intent(
            blocked_reason,
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )

    if (
        attempt_currentness_status == "current"
        and len(
            {
                authority_target_closed_day,
                authority_strategy_closed_day,
                authority_freshness_closed_day,
                attempt_target_closed_day,
                attempt_latest_available_closed_day,
            }
        )
        != 1
    ):
        fail_closed_intent(
            "Execution intent blocked: authority target day is not aligned across authoritative inputs "
            f"(success_target={authority_target_closed_day} strategy={authority_strategy_closed_day} "
            f"freshness={authority_freshness_closed_day} attempt_target={attempt_target_closed_day} "
            f"attempt_latest_available={attempt_latest_available_closed_day})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )

    paper_header, paper_rows = read_csv_rows(main_paper_path)
    if not paper_rows:
        fail_closed_intent(
            f"Execution intent blocked: no rows found in {main_paper_path}",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )

    live_header, live_rows = read_csv_rows(main_live_status_path)
    if not live_rows:
        fail_closed_intent(
            f"Execution intent blocked: no rows found in {main_live_status_path}",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )

    reference_header, reference_rows = read_csv_rows(reference_paper_path)
    if not reference_rows:
        fail_closed_intent(
            f"Execution intent blocked: no rows found in {reference_paper_path}",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )

    freshness_report = read_json(app_freshness_report_path)
    freshness_report_closed_day = normalize_iso_day_text(
        freshness_report.get("latest_closed_utc_date"),
        context="app_freshness_report.latest_closed_utc_date",
    )
    freshness_report_status = str(freshness_report.get("status") or "").strip().lower()
    freshness_report_errors = freshness_report.get("errors")
    if freshness_report_closed_day != authority_target_closed_day:
        fail_closed_intent(
            "Execution intent blocked: canonical freshness report day diverged from authority day "
            f"(authority_day={authority_target_closed_day} freshness_day={freshness_report_closed_day})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )
    if freshness_report_status not in {"ok", "success", "current"}:
        fail_closed_intent(
            f"Execution intent blocked: canonical freshness report is not green (status={freshness_report_status or 'missing'})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )
    if isinstance(freshness_report_errors, list) and freshness_report_errors:
        fail_closed_intent(
            "Execution intent blocked: canonical freshness report contains errors",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )

    paper_last = paper_rows[-1]
    live_last = live_rows[-1]
    reference_last = reference_rows[-1]

    paper_date_col = find_column(
        paper_header,
        ["date", "timestamp", "day", "trade_date", "bar_date"],
    )
    paper_asset_col = find_column(
        paper_header,
        [
            "selected_asset",
            "held_asset",
            "asset",
            "symbol",
            "ticker",
            "chosen_asset",
            "weekly_authorized_asset",
        ],
    )
    paper_regime_col = find_column(
        paper_header,
        ["regime", "state", "selected_regime", "market_regime", "executed_regime"],
    )
    paper_position_col = find_column(
        paper_header,
        ["position", "held_position", "executed_position", "state_position"],
    )

    status_date_col = find_column(
        live_header,
        ["date", "timestamp", "day", "trade_date", "bar_date", "latest_available_date"],
    )
    status_asset_col = find_column(
        live_header,
        [
            "selected_asset",
            "held_asset",
            "asset",
            "symbol",
            "ticker",
            "held_asset_public",
            "current_asset",
        ],
    )
    status_regime_col = find_column(
        live_header,
        ["regime", "state", "selected_regime", "market_regime", "held_state_label"],
    )
    status_execution_state_col = find_column(
        live_header,
        ["execution_state", "executed_position", "position", "held_position"],
    )

    reference_asset_col = find_column(
        reference_header,
        [
            "selected_asset",
            "held_asset",
            "asset",
            "symbol",
            "ticker",
            "chosen_asset",
            "weekly_authorized_asset",
        ],
    )
    reference_position_col = find_column(
        reference_header,
        ["position", "held_position", "executed_position", "state_position"],
    )

    as_of_source = (
        first_nonempty(live_last, [status_date_col] if status_date_col else [])
        or first_nonempty(paper_last, [paper_date_col] if paper_date_col else [])
    )
    as_of_source = normalize_iso_day_text(
        as_of_source,
        context="execution intent as_of_source",
    )
    if as_of_source != authority_target_closed_day:
        fail_closed_intent(
            "Execution intent blocked: source day diverged from authority day "
            f"(authority_day={authority_target_closed_day} source_day={as_of_source})",
            started_at=started_at,
            strategy_model=strategy_model,
            reference_model=reference_model,
            input_paths=input_paths_for_failure,
            source_paths=source_paths_for_failure,
            path_resolution_diagnostics=path_resolution_diagnostics,
            authority_currentness_evaluation=authority_currentness_evaluation,
        )

    target_asset = derive_target_asset(
        live_last=live_last,
        paper_last=paper_last,
        status_asset_col=status_asset_col,
        status_execution_state_col=status_execution_state_col,
        paper_asset_col=paper_asset_col,
        paper_position_col=paper_position_col,
    )

    target_regime = (
        first_nonempty(live_last, [status_regime_col] if status_regime_col else [])
        or first_nonempty(paper_last, [paper_regime_col] if paper_regime_col else [])
        or first_nonempty(live_last, [status_execution_state_col] if status_execution_state_col else [])
        or first_nonempty(paper_last, [paper_position_col] if paper_position_col else [])
    )

    reference_asset = (
        first_nonempty(reference_last, [reference_asset_col] if reference_asset_col else [])
        or first_nonempty(reference_last, [reference_position_col] if reference_position_col else [])
    )

    freshness_ok = True
    signal_id = f"{strategy_model}::{str(as_of_source).strip()}::{target_asset}"

    intent = {
        "intent_type": "normalized_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "as_of_source": as_of_source,
        "execution_mode": "read_only_intent_only",
        "trading_enabled": False,
        "kill_switch_required": True,
        "strategy_model": strategy_model,
        "reference_model": reference_model,
        "benchmark": "BTC",
        "signal_id": signal_id,
        "target_asset": target_asset,
        "target_side": "long_only_hold_selected_asset_or_cash",
        "target_regime": target_regime,
        "size_mode": "not_computed_yet",
        "target_size_pct": None,
        "target_notional_usd": None,
        "reference_asset": reference_asset,
        "staleness_ok": freshness_ok,
        "stale_signal": not freshness_ok,
        "guardrail_flags": {
            "contract_validated": True,
            "trading_disabled": True,
            "kill_switch_required": True,
            "manual_approval_required_for_live_orders": True,
            "leverage_live_truth_allowed": False
        },
        "source_paths": {
            "strategy_paper": str(main_paper_path.resolve()),
            "strategy_live_status": str(main_live_status_path.resolve()),
            "reference_paper": str(reference_paper_path.resolve()),
            "app_freshness_report": str(app_freshness_report_path.resolve()),
            "authority_latest_successful_snapshot": str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
            "authority_latest_attempt_status": str(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH.resolve()),
        },
        "path_resolution_diagnostics": path_resolution_diagnostics,
        "authority_currentness_evaluation": authority_currentness_evaluation,
        "resolved_columns": {
            "paper_date_col": paper_date_col,
            "paper_asset_col": paper_asset_col,
            "paper_regime_col": paper_regime_col,
            "paper_position_col": paper_position_col,
            "status_date_col": status_date_col,
            "status_asset_col": status_asset_col,
            "status_regime_col": status_regime_col,
            "status_execution_state_col": status_execution_state_col,
            "reference_asset_col": reference_asset_col,
            "reference_position_col": reference_position_col
        },
        "source_samples": {
            "strategy_last_paper_row": paper_last,
            "strategy_last_live_status_row": live_last,
            "reference_last_paper_row": reference_last
        },
        "notes": [
            "Deterministic intent from official execution app exports.",
            "Authority day alignment is required across the full canonical dependency closure.",
            "Uses the current strategy contract from source_of_truth/export_contract.json.",
            "Supports current canonical export schema with chosen_asset / held_asset_public / execution_state.",
            "No order sizing logic yet.",
            "No live order execution allowed."
        ]
    }

    quality = {
        "intent_ok": True,
        "strategy_model": intent["strategy_model"],
        "signal_id_present": bool(intent["signal_id"]),
        "target_asset_present": bool(intent["target_asset"]),
        "target_regime_present": bool(intent["target_regime"]),
        "staleness_ok": bool(intent["staleness_ok"]),
        "trading_enabled": bool(intent["trading_enabled"]),
        "kill_switch_required": bool(intent["kill_switch_required"]),
        "leverage_live_truth_allowed": False,
        "authority_currentness_status": attempt_currentness_status,
        "same_run_allowance_applied": bool(
            authority_currentness_evaluation.get("same_run_allowance_applied")
        ),
        "authority_currentness_evaluation": authority_currentness_evaluation,
    }

    manifest = {
        "artifact_name": "latest_execution_intent",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": started_at,
        "script_path": str(Path(__file__).resolve()),
        "input_paths": [
            str(EXPORT_CONTRACT_PATH.resolve()),
            str(AUTHORITY_LATEST_SUCCESSFUL_SNAPSHOT_PATH.resolve()),
            str(AUTHORITY_LATEST_ATTEMPT_STATUS_PATH.resolve()),
            str(main_paper_path.resolve()),
            str(main_live_status_path.resolve()),
            str(reference_paper_path.resolve()),
            str(app_freshness_report_path.resolve())
        ],
        "output_paths": [
            str(INTENT_PATH.resolve()),
            str(QUALITY_PATH.resolve()),
            str(MANIFEST_PATH.resolve())
        ],
        "status": "success",
        "authority_currentness_evaluation": authority_currentness_evaluation,
    }

    INTENT_PATH.write_text(json.dumps(intent, indent=2, ensure_ascii=False), encoding="utf-8")
    QUALITY_PATH.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log(f"[SAVED] {INTENT_PATH}")
    log(f"[SAVED] {QUALITY_PATH}")
    log(f"[SAVED] {MANIFEST_PATH}")
    log(f"[END] build_execution_intent_from_strategy_exports success target_asset={target_asset}")


if __name__ == "__main__":
    main()
