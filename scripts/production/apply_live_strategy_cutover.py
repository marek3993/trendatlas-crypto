from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.production.strategy_catalog_common import (
    DEFAULT_OUTPUT_PATH as STRATEGY_CATALOG_PATH,
    PHASE68I_MODEL,
    ROOT,
    build_strategy_catalog_payload,
    read_json_required,
    repo_rel,
    validate_strategy_catalog_payload,
    write_json_atomic,
)


PROMOTION_REPORT_DIR = ROOT / "outputs" / "production" / "promotion"
PROMOTION_REPORT_PATH = PROMOTION_REPORT_DIR / "latest_promotion_report.json"
PROMOTION_QUALITY_PATH = PROMOTION_REPORT_DIR / "latest_promotion_report.quality.json"
PROMOTION_GIT_ADD_PATH = PROMOTION_REPORT_DIR / "latest_promotion_git_add.txt"

CURRENT_STRATEGY_SNAPSHOT_PATH = ROOT / "outputs" / "production" / "current_strategy_snapshot.json"
CURRENT_STRATEGY_QUALITY_PATH = ROOT / "outputs" / "production" / "current_strategy_snapshot.quality.json"
CURRENT_STRATEGY_TIMESERIES_PATH = ROOT / "outputs" / "production" / "current_strategy_timeseries.csv"
CURRENT_STRATEGY_DIAGNOSTICS_PATH = ROOT / "outputs" / "production" / "current_strategy_diagnostics.json"
CURRENT_STRATEGY_MANIFEST_PATH = ROOT / "outputs" / "production" / "current_strategy_snapshot.manifest.json"

DATA_HEALTH_REPORT_PATH = ROOT / "outputs" / "production" / "data_health_report.json"
DATA_HEALTH_QUALITY_PATH = ROOT / "outputs" / "production" / "data_health_report.quality.json"
DATA_HEALTH_MANIFEST_PATH = ROOT / "outputs" / "production" / "data_health_report.manifest.json"

MATERIALIZE_REPORT_PATH = ROOT / "outputs" / "execution" / "refresh_pipeline" / "materialize_execution_app_exports_report.json"
MATERIALIZE_QUALITY_PATH = ROOT / "outputs" / "execution" / "refresh_pipeline" / "materialize_execution_app_exports_quality.json"
MATERIALIZE_MANIFEST_PATH = ROOT / "outputs" / "execution" / "refresh_pipeline" / "materialize_execution_app_exports_manifest.json"

INTENT_PATH = ROOT / "outputs" / "execution" / "intents" / "latest_execution_intent.json"
INTENT_QUALITY_PATH = ROOT / "outputs" / "execution" / "intents" / "latest_execution_intent_quality.json"
INTENT_MANIFEST_PATH = ROOT / "outputs" / "execution" / "intents" / "latest_execution_intent_manifest.json"

GATE_DECISION_PATH = ROOT / "outputs" / "execution" / "live_gate" / "latest_real_order_gate_decision.json"
GATE_QUALITY_PATH = ROOT / "outputs" / "execution" / "live_gate" / "latest_real_order_gate_quality.json"
GATE_MANIFEST_PATH = ROOT / "outputs" / "execution" / "live_gate" / "latest_real_order_gate_manifest.json"

SOURCE_CONTRACT_REPORT_PATH = ROOT / "outputs" / "execution" / "source_contract" / "execution_source_contract_report.json"
SOURCE_CONTRACT_QUALITY_PATH = ROOT / "outputs" / "execution" / "source_contract" / "execution_source_contract_quality.json"
SOURCE_CONTRACT_MANIFEST_PATH = ROOT / "outputs" / "execution" / "source_contract" / "execution_source_contract_manifest.json"

AUTHORITY_SUCCESS_PATH = ROOT / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
AUTHORITY_ATTEMPT_PATH = ROOT / "outputs" / "execution" / "authority" / "latest_attempt_status.json"

ALLOWED_FINAL_VERDICTS = {
    "PROMOTION_READY_FOR_COMMIT_REVIEW",
    "BLOCKED_DATA",
    "BLOCKED_CONTRACT",
    "BLOCKED_AUTHORITY",
    "FAILED",
}
AUTHORITY_BLOCKING_SOURCE_IDS = {
    "execution_authority_latest_successful_snapshot",
    "execution_authority_latest_attempt_status",
}
PENDING_AUTHORITY_ERROR_FRAGMENTS = (
    "current_main_strategy_root_contract diverged from source_of_truth/export_contract.json",
    "production current_strategy_snapshot.closed_day diverged from authority target day",
    "target_closed_day_utc diverged from app_product_snapshot.strategy_last_closed_day",
    "target_closed_day_utc diverged from app_runtime_snapshot.latest_available_closed_utc_date",
    "target_closed_day_utc diverged from app_runtime_snapshot.latest_strategy_artifact_date",
)
FORBIDDEN_GIT_ADD_PREFIXES = (
    "outputs/execution/authority/",
    "outputs/app_refresh_pipeline/",
    "data/ohlcv/",
    "data/ohlcv_phase67_top100/",
    "artifacts/home_automation_bundle/",
)
FORBIDDEN_GIT_ADD_GLOBS = ("*.pyc",)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a fail-closed dry-run for Production Core strategy cutover.")
    parser.add_argument("--strategy", required=True, type=str)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=PROMOTION_REPORT_DIR)
    return parser.parse_args()


def run_python_step(script_relative_path: str) -> dict[str, Any]:
    script_path = ROOT / script_relative_path
    command = [sys.executable, str(script_path)]
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": " ".join(command),
        "returncode": int(result.returncode),
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
        "ok": result.returncode == 0,
    }


def load_catalog_entry(catalog: dict[str, Any], target_strategy: str) -> dict[str, Any] | None:
    strategies = catalog.get("strategies")
    if not isinstance(strategies, list):
        return None
    for entry in strategies:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("strategy_model") or "").strip() == target_strategy:
            return entry
    return None


def read_timeseries_window(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"first": None, "last": None, "row_count": 0}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        first_value: str | None = None
        last_value: str | None = None
        row_count = 0
        for row in reader:
            row_count += 1
            current_value = str(row.get("date") or "").strip() or None
            if first_value is None:
                first_value = current_value
            last_value = current_value
    return {"first": first_value, "last": last_value, "row_count": row_count}


def build_evidence_window_proof(snapshot: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any] | None:
    source_inputs = snapshot.get("source_inputs")
    if not isinstance(source_inputs, dict):
        return None
    evidence_window = source_inputs.get("etf_flow_evidence_window")
    if not isinstance(evidence_window, dict):
        return None
    checks = quality.get("checks") if isinstance(quality.get("checks"), dict) else {}
    return {
        "strategy_model": str(snapshot.get("strategy_version") or "").strip(),
        "start_date": evidence_window.get("start_date"),
        "end_date": evidence_window.get("end_date"),
        "feature_row_count": evidence_window.get("feature_row_count"),
        "quality_checks": {
            "etf_full_history_matches_baseline_date_universe": checks.get(
                "etf_full_history_matches_baseline_date_universe"
            ),
            "etf_evidence_window_starts_on_first_feature_day": checks.get(
                "etf_evidence_window_starts_on_first_feature_day"
            ),
            "etf_evidence_window_is_contiguous_to_closed_day": checks.get(
                "etf_evidence_window_is_contiguous_to_closed_day"
            ),
            "etf_feature_rows_match_source_panel": checks.get(
                "etf_feature_rows_match_source_panel"
            ),
        },
    }


def normalize_relative_path(path_text: str) -> str:
    return str(path_text or "").replace("\\", "/").strip().lstrip("./")


def is_forbidden_git_add_path(path_text: str) -> bool:
    normalized = normalize_relative_path(path_text)
    if not normalized:
        return True
    if "/opt/home_automation" in normalized or normalized.startswith("opt/home_automation"):
        return True
    if any(segment == "__pycache__" for segment in normalized.split("/")):
        return True
    if any(normalized.startswith(prefix) for prefix in FORBIDDEN_GIT_ADD_PREFIXES):
        return True
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in FORBIDDEN_GIT_ADD_GLOBS)


def filter_git_add_candidates(paths: list[str]) -> tuple[list[str], list[str]]:
    safe_paths: list[str] = []
    forbidden_paths: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        normalized = normalize_relative_path(raw_path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if is_forbidden_git_add_path(normalized):
            forbidden_paths.append(normalized)
            continue
        safe_paths.append(normalized)
    return safe_paths, forbidden_paths


def mtime_touched_since(path: Path, started_at_epoch: float) -> bool:
    return path.exists() and path.stat().st_mtime >= started_at_epoch - 1.0


def classify_source_contract(
    *,
    report: dict[str, Any] | None,
    authority_success: dict[str, Any] | None,
    authority_attempt: dict[str, Any] | None,
    target_strategy: str,
    closed_day: str | None,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {
            "status": "missing",
            "reason_classification": "missing_report",
            "errors": ["execution_source_contract_report.json is missing or unreadable"],
            "pending_authority_publish": False,
        }

    contract_status = str(report.get("contract_status") or "").strip().lower() or "missing"
    errors = list(report.get("hard_required_missing") or [])
    if contract_status == "valid":
        return {
            "status": "valid",
            "reason_classification": "valid",
            "errors": errors,
            "pending_authority_publish": False,
        }

    success_product = authority_success.get("app_product_snapshot") if isinstance(authority_success, dict) else {}
    attempt_product = authority_attempt.get("app_product_snapshot") if isinstance(authority_attempt, dict) else {}
    success_model = str((success_product or {}).get("main_strategy_model") or "").strip()
    success_day = str(authority_success.get("target_closed_day_utc") or "").strip() if isinstance(authority_success, dict) else ""
    attempt_model = str((attempt_product or {}).get("main_strategy_model") or "").strip()
    attempt_status = str(authority_attempt.get("latest_authoritative_attempt_status") or "").strip() if isinstance(authority_attempt, dict) else ""
    attempt_target_day = str(authority_attempt.get("target_closed_day_utc") or "").strip() if isinstance(authority_attempt, dict) else ""

    authority_lag_visible = (
        bool(closed_day)
        and (
            success_model != target_strategy
            or success_day != closed_day
            or attempt_target_day != closed_day
            or attempt_status.lower() != "success"
        )
    )
    def _is_pending_authority_error(error: str) -> bool:
        normalized = str(error or "")
        if any(fragment in normalized for fragment in PENDING_AUTHORITY_ERROR_FRAGMENTS):
            return True
        return (
            "canonical source validation blocked: product_snapshot.main_strategy_metrics." in normalized
            and attempt_model == target_strategy
            and bool(closed_day)
            and attempt_target_day == closed_day
            and attempt_status.lower() in {"failed", "in_progress"}
        )

    pending_authority_publish = bool(errors) and authority_lag_visible and all(
        _is_pending_authority_error(error) for error in errors
    )
    reason_classification = "pending_authority_publish" if pending_authority_publish else "other_contract_mismatch"
    return {
        "status": contract_status,
        "reason_classification": reason_classification,
        "errors": errors,
        "pending_authority_publish": pending_authority_publish,
    }


def classify_data_health_block(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {
            "block_app": False,
            "block_execution": False,
            "authority_only_block": False,
            "blocking_source_ids": [],
        }
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return {
            "block_app": False,
            "block_execution": False,
            "authority_only_block": False,
            "blocking_source_ids": [],
        }
    blocking_source_ids = list(summary.get("app_blocking_source_ids") or []) + list(
        summary.get("execution_blocking_source_ids") or []
    )
    normalized_ids = [str(value or "").strip() for value in blocking_source_ids if str(value or "").strip()]
    authority_only_block = bool(normalized_ids) and all(
        source_id in AUTHORITY_BLOCKING_SOURCE_IDS for source_id in normalized_ids
    )
    return {
        "block_app": bool(summary.get("block_app", False)),
        "block_execution": bool(summary.get("block_execution", False)),
        "authority_only_block": authority_only_block,
        "blocking_source_ids": normalized_ids,
    }


def build_intent_status(intent_payload: dict[str, Any] | None, step_ran: bool) -> dict[str, Any]:
    if not step_ran:
        return {"status": "skipped", "stale_signal": None, "target_asset": None, "target_size_pct": None}
    if not isinstance(intent_payload, dict):
        return {"status": "missing", "stale_signal": None, "target_asset": None, "target_size_pct": None}
    if str(intent_payload.get("intent_status") or "").strip().lower() == "blocked":
        status = "blocked"
    else:
        status = "ready"
    return {
        "status": status,
        "stale_signal": intent_payload.get("stale_signal"),
        "target_asset": intent_payload.get("target_asset"),
        "target_size_pct": intent_payload.get("target_size_pct"),
    }


def build_gate_status(gate_payload: dict[str, Any] | None, step_ran: bool) -> dict[str, Any]:
    if not step_ran:
        return {"status": "skipped", "would_place_real_order": None, "target_asset": None}
    if not isinstance(gate_payload, dict):
        return {"status": "missing", "would_place_real_order": None, "target_asset": None}
    return {
        "status": str(gate_payload.get("status") or "").strip() or "unknown",
        "would_place_real_order": gate_payload.get("would_place_real_order"),
        "target_asset": gate_payload.get("target_asset"),
    }


def build_quality_payload(report: dict[str, Any]) -> dict[str, Any]:
    final_verdict = str(report.get("final_verdict") or "").strip()
    git_add_list = report.get("exact_proposed_git_add_list")
    safe_git_add = isinstance(git_add_list, list) and not report.get("forbidden_files_detected")
    checks = {
        "target_strategy_present": bool(str(report.get("target_strategy") or "").strip()),
        "final_verdict_allowed": final_verdict in ALLOWED_FINAL_VERDICTS,
        "current_strategy_snapshot_status_present": bool(
            str(report.get("current_strategy_snapshot_validation_status") or "").strip()
        ),
        "git_add_list_safe": safe_git_add,
        "source_contract_classified": bool(
            str(((report.get("source_contract") or {}).get("reason_classification") or "")).strip()
        ),
    }
    errors = [
        key for key, passed in checks.items() if not passed
    ]
    return {
        "artifact_type": "promotion_report_quality",
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "checks": checks,
        "report_path": repo_rel(PROMOTION_REPORT_PATH),
    }


def main() -> None:
    args = parse_args()
    if args.apply:
        raise SystemExit(
            "Apply mode is blocked in v1. Use --dry-run only; live cutover still requires separate authority publish."
        )

    started_at_iso = utc_now_iso()
    started_at_epoch = datetime.now(timezone.utc).timestamp()
    target_strategy = str(args.strategy or "").strip()

    promotion_report: dict[str, Any] = {
        "artifact_type": "promotion_report",
        "schema_version": 1,
        "generated_at_utc": started_at_iso,
        "mode": "dry_run",
        "target_strategy": target_strategy,
        "previous_strategy": None,
        "closed_day": None,
        "current_strategy_snapshot_validation_status": "not_started",
        "current_strategy_timeseries": {"first": None, "last": None, "row_count": 0},
        "evidence_window_proof": None,
        "data_health": {
            "overall_status": "not_run",
            "block_app": False,
            "block_execution": False,
            "app_blocking_source_ids": [],
            "execution_blocking_source_ids": [],
        },
        "execution_intent": {
            "status": "not_run",
            "stale_signal": None,
            "target_asset": None,
            "target_size_pct": None,
        },
        "gate": {
            "status": "not_run",
            "would_place_real_order": None,
            "target_asset": None,
        },
        "source_contract": {
            "status": "not_run",
            "reason_classification": "not_run",
            "errors": [],
        },
        "authority": {
            "latest_successful": {"status": None, "model": None, "date": None},
            "latest_attempt": {"status": None, "model": None, "date": None},
        },
        "pending_authority_publish": False,
        "exact_proposed_git_add_list": [],
        "forbidden_files_detected": [],
        "final_verdict": "FAILED",
        "blocker": None,
        "next_command": None,
        "step_results": {},
    }

    generated_candidates: list[str] = [
        repo_rel(STRATEGY_CATALOG_PATH),
        repo_rel(PROMOTION_REPORT_PATH),
        repo_rel(PROMOTION_QUALITY_PATH),
        repo_rel(PROMOTION_GIT_ADD_PATH),
    ]

    try:
        catalog_payload = build_strategy_catalog_payload()
        catalog_validation = validate_strategy_catalog_payload(catalog_payload)
        write_json_atomic(STRATEGY_CATALOG_PATH, catalog_payload)
        promotion_report["step_results"]["strategy_catalog"] = {
            "output_path": repo_rel(STRATEGY_CATALOG_PATH),
            "validation_status": catalog_validation["status"],
            "error_count": catalog_validation["error_count"],
            "errors": list(catalog_validation["errors"]),
        }
        if catalog_validation["status"] != "passed":
            promotion_report["blocker"] = "strategy catalog validation failed"
            promotion_report["final_verdict"] = "FAILED"
            raise RuntimeError("strategy catalog validation failed")

        catalog_entry = load_catalog_entry(catalog_payload, target_strategy)
        if catalog_entry is None:
            promotion_report["blocker"] = f"target strategy is not present in the strategy catalog: {target_strategy}"
            promotion_report["final_verdict"] = "FAILED"
            raise RuntimeError("target strategy missing from catalog")

        required_source_paths = [
            str(value or "").strip() for value in catalog_entry.get("required_source_paths") or []
        ]
        missing_required_paths = [
            path_text for path_text in required_source_paths if not (ROOT / path_text).exists()
        ]
        promotion_report["step_results"]["required_paths"] = {
            "checked_count": len(required_source_paths),
            "missing": missing_required_paths,
        }
        if missing_required_paths:
            promotion_report["blocker"] = "required strategy source paths are missing"
            promotion_report["final_verdict"] = "BLOCKED_DATA"
            raise RuntimeError("required source paths are missing")

        project_truth = read_json_required(ROOT / "source_of_truth" / "project_truth.json")
        app_product_truth = project_truth.get("app_product_truth")
        if not isinstance(app_product_truth, dict):
            raise ValueError("project_truth.json missing app_product_truth")
        current_official_strategy = str(app_product_truth.get("main_strategy_model") or "").strip()
        if current_official_strategy != target_strategy:
            promotion_report["blocker"] = (
                "v1 dry-run supports only the current official Production Core strategy without source_of_truth mutation "
                f"(current_official_strategy={current_official_strategy} target_strategy={target_strategy})"
            )
            promotion_report["next_command"] = (
                "Update source_of_truth under explicit governance first, then rerun this dry-run for the new official target."
            )
            promotion_report["final_verdict"] = "FAILED"
            raise RuntimeError("target strategy does not match the current official Production Core strategy")

        authority_success = read_json_if_exists(AUTHORITY_SUCCESS_PATH)
        authority_attempt = read_json_if_exists(AUTHORITY_ATTEMPT_PATH)
        success_product = authority_success.get("app_product_snapshot") if isinstance(authority_success, dict) else {}
        attempt_product = authority_attempt.get("app_product_snapshot") if isinstance(authority_attempt, dict) else {}
        promotion_report["previous_strategy"] = str((success_product or {}).get("main_strategy_model") or "").strip() or None
        promotion_report["authority"] = {
            "latest_successful": {
                "status": str((authority_success or {}).get("latest_authoritative_attempt_status") or "").strip() or None,
                "model": str((success_product or {}).get("main_strategy_model") or "").strip() or None,
                "date": str((authority_success or {}).get("target_closed_day_utc") or "").strip() or None,
            },
            "latest_attempt": {
                "status": str((authority_attempt or {}).get("latest_authoritative_attempt_status") or "").strip() or None,
                "model": str((attempt_product or {}).get("main_strategy_model") or "").strip() or None,
                "date": str((authority_attempt or {}).get("target_closed_day_utc") or "").strip() or None,
            },
        }

        build_snapshot_step = run_python_step("scripts/production/build_current_strategy_snapshot.py")
        validate_snapshot_step = run_python_step("scripts/production/validate_current_strategy_snapshot.py")
        materialize_step = run_python_step("scripts/execution/materialize_execution_app_exports.py")
        data_health_build_step = run_python_step("scripts/production/build_data_health_report.py")
        data_health_validate_step = run_python_step("scripts/production/validate_data_health_report.py")

        promotion_report["step_results"]["build_current_strategy_snapshot"] = build_snapshot_step
        promotion_report["step_results"]["validate_current_strategy_snapshot"] = validate_snapshot_step
        promotion_report["step_results"]["materialize_execution_app_exports"] = materialize_step
        promotion_report["step_results"]["build_data_health_report"] = data_health_build_step
        promotion_report["step_results"]["validate_data_health_report"] = data_health_validate_step

        if build_snapshot_step["ok"]:
            generated_candidates.extend(
                [
                    repo_rel(CURRENT_STRATEGY_SNAPSHOT_PATH),
                    repo_rel(CURRENT_STRATEGY_TIMESERIES_PATH),
                    repo_rel(CURRENT_STRATEGY_DIAGNOSTICS_PATH),
                    repo_rel(CURRENT_STRATEGY_QUALITY_PATH),
                    repo_rel(CURRENT_STRATEGY_MANIFEST_PATH),
                ]
            )
        else:
            promotion_report["blocker"] = promotion_report["blocker"] or (
                "build_current_strategy_snapshot.py failed: "
                + (build_snapshot_step["stderr"] or build_snapshot_step["stdout"] or "unknown error")
            )
            promotion_report["final_verdict"] = "BLOCKED_DATA"

        if not validate_snapshot_step["ok"]:
            promotion_report["blocker"] = promotion_report["blocker"] or (
                "validate_current_strategy_snapshot.py failed: "
                + (validate_snapshot_step["stderr"] or validate_snapshot_step["stdout"] or "unknown error")
            )
            promotion_report["final_verdict"] = "BLOCKED_CONTRACT"

        snapshot_payload = read_json_if_exists(CURRENT_STRATEGY_SNAPSHOT_PATH)
        snapshot_quality = read_json_if_exists(CURRENT_STRATEGY_QUALITY_PATH)
        timeseries_window = read_timeseries_window(CURRENT_STRATEGY_TIMESERIES_PATH)
        if isinstance(snapshot_payload, dict):
            promotion_report["closed_day"] = str(snapshot_payload.get("closed_day") or "").strip() or None
        if isinstance(snapshot_quality, dict) or isinstance(snapshot_payload, dict):
            promotion_report["current_strategy_snapshot_validation_status"] = str(
                ((snapshot_quality or {}).get("status") if isinstance(snapshot_quality, dict) else "")
                or ((snapshot_payload or {}).get("validation", {}).get("status") if isinstance(snapshot_payload, dict) else "")
                or ""
            ).strip() or "missing"
        promotion_report["current_strategy_timeseries"] = timeseries_window
        if isinstance(snapshot_payload, dict) and isinstance(snapshot_quality, dict):
            promotion_report["evidence_window_proof"] = build_evidence_window_proof(
                snapshot_payload,
                snapshot_quality,
            )

        materialize_report = read_json_if_exists(MATERIALIZE_REPORT_PATH)
        if materialize_step["ok"]:
            for candidate_path in (
                MATERIALIZE_REPORT_PATH,
                MATERIALIZE_QUALITY_PATH,
                MATERIALIZE_MANIFEST_PATH,
            ):
                if mtime_touched_since(candidate_path, started_at_epoch):
                    generated_candidates.append(repo_rel(candidate_path))
            if isinstance(materialize_report, dict):
                rows = materialize_report.get("rows")
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        for key in ("paper_output_path", "metrics_output_path"):
                            path_value = str(row.get(key) or "").strip()
                            if path_value:
                                generated_candidates.append(repo_rel(path_value))
        else:
            promotion_report["blocker"] = promotion_report["blocker"] or (
                "materialize_execution_app_exports.py failed: "
                + (materialize_step["stderr"] or materialize_step["stdout"] or "unknown error")
            )

        if data_health_build_step["ok"]:
            generated_candidates.extend(
                [
                    repo_rel(DATA_HEALTH_REPORT_PATH),
                    repo_rel(DATA_HEALTH_QUALITY_PATH),
                    repo_rel(DATA_HEALTH_MANIFEST_PATH),
                ]
            )
        if not data_health_build_step["ok"] or not data_health_validate_step["ok"]:
            promotion_report["blocker"] = promotion_report["blocker"] or (
                "data health build or validation failed: "
                + (
                    data_health_validate_step["stderr"]
                    or data_health_validate_step["stdout"]
                    or data_health_build_step["stderr"]
                    or data_health_build_step["stdout"]
                    or "unknown error"
                )
            )

        data_health_report = read_json_if_exists(DATA_HEALTH_REPORT_PATH)
        data_health_summary = (
            data_health_report.get("summary") if isinstance(data_health_report, dict) else {}
        )
        if not isinstance(data_health_summary, dict):
            data_health_summary = {}
        promotion_report["data_health"] = {
            "overall_status": str(data_health_report.get("overall_status") or data_health_summary.get("overall_status") or "").strip()
            if isinstance(data_health_report, dict)
            else "missing",
            "block_app": bool(data_health_summary.get("block_app", False)),
            "block_execution": bool(data_health_summary.get("block_execution", False)),
            "app_blocking_source_ids": list(data_health_summary.get("app_blocking_source_ids") or []),
            "execution_blocking_source_ids": list(data_health_summary.get("execution_blocking_source_ids") or []),
        }

        intent_step_ran = False
        gate_step_ran = False
        intent_payload: dict[str, Any] | None = None
        gate_payload: dict[str, Any] | None = None
        snapshot_ready_for_downstream = (
            build_snapshot_step["ok"]
            and validate_snapshot_step["ok"]
            and promotion_report["current_strategy_snapshot_validation_status"] == "passed"
        )

        data_health_classification = classify_data_health_block(data_health_report)
        allow_downstream_execution = (
            snapshot_ready_for_downstream
            and isinstance(snapshot_payload, dict)
            and data_health_build_step["ok"]
            and data_health_validate_step["ok"]
            and not data_health_classification["block_app"]
            and not data_health_classification["block_execution"]
            and materialize_step["ok"]
        )

        if allow_downstream_execution:
            intent_step_ran = True
            intent_step = run_python_step("scripts/execution/build_execution_intent_from_strategy_exports.py")
            promotion_report["step_results"]["build_execution_intent_from_strategy_exports"] = intent_step
            intent_payload = read_json_if_exists(INTENT_PATH)
            if mtime_touched_since(INTENT_PATH, started_at_epoch):
                generated_candidates.extend(
                    [
                        repo_rel(INTENT_PATH),
                        repo_rel(INTENT_QUALITY_PATH),
                        repo_rel(INTENT_MANIFEST_PATH),
                    ]
                )

            intent_status = build_intent_status(intent_payload, step_ran=True)
            promotion_report["execution_intent"] = intent_status
            if intent_status["status"] == "ready":
                gate_step_ran = True
                gate_step = run_python_step("scripts/execution/prepare_real_order_gate.py")
                promotion_report["step_results"]["prepare_real_order_gate"] = gate_step
                gate_payload = read_json_if_exists(GATE_DECISION_PATH)
                if mtime_touched_since(GATE_DECISION_PATH, started_at_epoch):
                    generated_candidates.extend(
                        [
                            repo_rel(GATE_DECISION_PATH),
                            repo_rel(GATE_QUALITY_PATH),
                            repo_rel(GATE_MANIFEST_PATH),
                        ]
                    )
            else:
                promotion_report["step_results"]["prepare_real_order_gate"] = {
                    "command": None,
                    "returncode": None,
                    "stdout": "",
                    "stderr": "",
                    "ok": False,
                    "skipped": True,
                    "reason": "execution intent is blocked or missing",
                }
        else:
            promotion_report["step_results"]["build_execution_intent_from_strategy_exports"] = {
                "command": None,
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "ok": False,
                "skipped": True,
                "reason": "data_health blocked downstream execution or materialize step failed",
            }
            promotion_report["step_results"]["prepare_real_order_gate"] = {
                "command": None,
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "ok": False,
                "skipped": True,
                "reason": "execution intent step did not run",
            }
            promotion_report["execution_intent"] = build_intent_status(None, step_ran=False)

        promotion_report["gate"] = build_gate_status(gate_payload, step_ran=gate_step_ran)

        source_contract_step = run_python_step("scripts/execution/validate_execution_source_contract.py")
        promotion_report["step_results"]["validate_execution_source_contract"] = source_contract_step
        source_contract_report = read_json_if_exists(SOURCE_CONTRACT_REPORT_PATH)
        if mtime_touched_since(SOURCE_CONTRACT_REPORT_PATH, started_at_epoch):
            generated_candidates.extend(
                [
                    repo_rel(SOURCE_CONTRACT_REPORT_PATH),
                    repo_rel(SOURCE_CONTRACT_QUALITY_PATH),
                    repo_rel(SOURCE_CONTRACT_MANIFEST_PATH),
                ]
            )

        source_contract_classification = classify_source_contract(
            report=source_contract_report,
            authority_success=authority_success,
            authority_attempt=authority_attempt,
            target_strategy=target_strategy,
            closed_day=promotion_report["closed_day"],
        )
        promotion_report["source_contract"] = source_contract_classification
        promotion_report["pending_authority_publish"] = bool(
            source_contract_classification["pending_authority_publish"]
        )

        if not materialize_step["ok"] or not data_health_build_step["ok"] or not data_health_validate_step["ok"]:
            final_verdict = "BLOCKED_DATA"
        elif data_health_classification["block_app"] or data_health_classification["block_execution"]:
            final_verdict = (
                "BLOCKED_AUTHORITY"
                if data_health_classification["authority_only_block"]
                else "BLOCKED_DATA"
            )
        elif intent_step_ran and promotion_report["execution_intent"]["status"] == "missing":
            final_verdict = "FAILED"
        elif gate_step_ran and promotion_report["gate"]["status"] == "missing":
            final_verdict = "FAILED"
        elif source_contract_classification["status"] == "valid":
            final_verdict = "PROMOTION_READY_FOR_COMMIT_REVIEW"
        elif source_contract_classification["pending_authority_publish"]:
            final_verdict = "BLOCKED_AUTHORITY"
        else:
            final_verdict = "BLOCKED_CONTRACT"

        if final_verdict == "PROMOTION_READY_FOR_COMMIT_REVIEW" and target_strategy == PHASE68I_MODEL:
            final_verdict = "FAILED"
            promotion_report["blocker"] = "phase68i_dynamic_ladder_candidate is cataloged as legacy fallback only"

        if final_verdict == "BLOCKED_AUTHORITY" and not promotion_report["blocker"]:
            promotion_report["blocker"] = (
                "Raspberry Pi authority publish is still pending or failed for the current Production Core closed day."
            )
        elif final_verdict == "BLOCKED_CONTRACT" and not promotion_report["blocker"]:
            promotion_report["blocker"] = "Execution source contract is invalid for reasons beyond pending authority publish."
        elif final_verdict == "BLOCKED_DATA" and not promotion_report["blocker"]:
            promotion_report["blocker"] = "One or more required data or materialization steps failed closed."

        if final_verdict in {"BLOCKED_DATA", "BLOCKED_CONTRACT", "BLOCKED_AUTHORITY"} and not promotion_report["next_command"]:
            promotion_report["next_command"] = (
                "python scripts/production/apply_live_strategy_cutover.py --strategy "
                f"{target_strategy} --dry-run"
            )

        safe_git_add_list, forbidden_files_detected = filter_git_add_candidates(generated_candidates)
        promotion_report["exact_proposed_git_add_list"] = safe_git_add_list
        promotion_report["forbidden_files_detected"] = forbidden_files_detected
        promotion_report["final_verdict"] = final_verdict

    except Exception as exc:
        if promotion_report["final_verdict"] not in ALLOWED_FINAL_VERDICTS:
            promotion_report["final_verdict"] = "FAILED"
        if not promotion_report["blocker"]:
            promotion_report["blocker"] = f"{type(exc).__name__}: {exc}"

    quality_payload = build_quality_payload(promotion_report)
    write_json_atomic(args.report_dir / PROMOTION_REPORT_PATH.name, promotion_report)
    write_json_atomic(args.report_dir / PROMOTION_QUALITY_PATH.name, quality_payload)
    write_text_atomic(
        args.report_dir / PROMOTION_GIT_ADD_PATH.name,
        "\n".join(promotion_report["exact_proposed_git_add_list"]) + (
            "\n" if promotion_report["exact_proposed_git_add_list"] else ""
        ),
    )

    print(json.dumps(promotion_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
