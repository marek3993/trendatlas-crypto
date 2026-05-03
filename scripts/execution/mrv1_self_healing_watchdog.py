from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"

for candidate in (ROOT, SCRIPTS_DIR):
    candidate_text = str(candidate)
    if candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)

OUTPUT_DIR = ROOT / "outputs" / "execution" / "watchdog"
REPORT_PATH = OUTPUT_DIR / "latest_watchdog_report.json"
SUMMARY_PATH = OUTPUT_DIR / "latest_watchdog_summary.txt"
ACTIONS_PATH = OUTPUT_DIR / "latest_watchdog_actions.json"

AUTHORITY_ATTEMPT_PATH = ROOT / "outputs" / "execution" / "authority" / "latest_attempt_status.json"
AUTHORITY_SUCCESS_PATH = ROOT / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json"
FRESHNESS_REPORT_PATH = ROOT / "outputs" / "execution" / "freshness" / "app_freshness_report.json"
APP_PRODUCT_SNAPSHOT_PATH = ROOT / "outputs" / "execution" / "app_snapshot" / "app_product_snapshot.json"
APP_RUNTIME_SNAPSHOT_PATH = ROOT / "outputs" / "execution" / "app_snapshot" / "app_runtime_snapshot.json"
APP_EXPORT_MAIN_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68g_66g_1p25x_candidate_paper.csv"
APP_EXPORT_MAIN_METRICS_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
APP_EXPORT_REFERENCE_PAPER_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase67j_no_neo_main_paper.csv"
APP_EXPORT_PHASE66G_LIVE_PATH = ROOT / "outputs" / "execution" / "app_exports" / "phase66g_live_status.csv"
BTC_RAW_PATH = ROOT / "data" / "ohlcv" / "BTCUSDT_1d.csv"

LATEST_MANIFEST_GLOB = "*/app_refresh_pipeline_manifest.json"

DAILY_REFRESH_SCRIPT = ROOT / "scripts" / "daily_refresh_app_pipeline.py"
MATERIALIZE_SCRIPT = ROOT / "scripts" / "execution" / "materialize_execution_app_exports.py"

UPSTREAM_PHASE68G_SOURCE_PAPER_PATH = (
    ROOT
    / "outputs"
    / "phase68g_portfolio_exposure_leverage_validation"
    / "papers"
    / "phase68g_66g_1p25x_candidate_paper.csv"
)
UPSTREAM_PHASE68G_SOURCE_METRICS_PATH = (
    ROOT
    / "outputs"
    / "phase68g_portfolio_exposure_leverage_validation"
    / "phase68g_66g_1p25x_candidate_authoritative_net_compare_export.csv"
)
UPSTREAM_PHASE67J_SOURCE_PAPER_PATH = (
    ROOT / "outputs" / "phase67j_final_narrow_validation_pack" / "phase67j_no_neo_main_paper.csv"
)
UPSTREAM_PHASE66G_SOURCE_LIVE_PATH = (
    ROOT / "outputs" / "phase66g_production_candidate_live" / "phase66g_live_status.csv"
)

INCIDENT_CLASSES = {
    "OK_CURRENT",
    "NOT_TIME_YET",
    "SCHEDULER_NOT_RUN",
    "PIPELINE_FAILED",
    "RAW_DATA_STALE",
    "APP_EXPORT_STALE",
    "AUTHORITY_ATTEMPT_FAILED",
    "AUTHORITY_SNAPSHOT_STALE",
    "AUTHORITY_PUBLISH_STALE",
    "APP_DEPLOY_OR_CACHE_STALE",
    "UNKNOWN_NEEDS_HUMAN",
}
CURRENT_STATUSES = {"current", "stale", "not_time_yet"}
SUCCESS_STATUSES = {"OK", "SUCCESS", "PASS", "PASSED"}
NOT_TIME_YET_GRACE_HOURS = 6


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_day_start(ts: datetime | None = None) -> datetime:
    current = ts or utc_now()
    return datetime(current.year, current.month, current.day, tzinfo=timezone.utc)


def expected_latest_closed_utc_day(ts: datetime | None = None) -> str:
    return (utc_day_start(ts) - timedelta(days=1)).date().isoformat()


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_last_csv_date(path: Path, columns: list[str]) -> date | None:
    if not path.exists() or not path.is_file():
        return None
    rows = read_csv_rows(path)
    if not rows:
        return None
    for column in columns:
        if column in rows[0]:
            raw = str(rows[-1].get(column, "")).strip()
            parsed = parse_iso_date(raw)
            if parsed is not None:
                return parsed
    return None


def read_first_csv_date(path: Path, columns: list[str]) -> date | None:
    if not path.exists() or not path.is_file():
        return None
    rows = read_csv_rows(path)
    if not rows:
        return None
    for column in columns:
        raw = str(rows[0].get(column, "")).strip()
        parsed = parse_iso_date(raw)
        if parsed is not None:
            return parsed
    return None


def path_mtime_utc(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def summarize_path(
    path: Path,
    *,
    date_reader: tuple[str, list[str]] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": relative_path(path),
        "exists": path.exists() and path.is_file(),
        "mtime_utc": path_mtime_utc(path),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else None,
        "sha256": sha256_file(path),
        "last_date": None,
    }
    if date_reader and record["exists"]:
        reader_mode, columns = date_reader
        try:
            if reader_mode == "csv_last":
                parsed = read_last_csv_date(path, columns)
            elif reader_mode == "csv_first":
                parsed = read_first_csv_date(path, columns)
            else:
                parsed = None
        except Exception as exc:
            record["date_error"] = str(exc)
            parsed = None
        record["last_date"] = iso_date(parsed)
    if extra_fields:
        record.update(extra_fields)
    return record


def discover_latest_manifest() -> Path | None:
    manifest_dir = ROOT / "outputs" / "app_refresh_pipeline"
    if not manifest_dir.exists():
        return None
    manifests = sorted(
        manifest_dir.glob(LATEST_MANIFEST_GLOB),
        key=lambda candidate: candidate.stat().st_mtime if candidate.exists() else 0,
        reverse=True,
    )
    return manifests[0] if manifests else None


def compute_publish_tree_state() -> dict[str, Any]:
    result: dict[str, Any] = {
        "current": None,
        "reason": "publish_tree_unchecked",
        "publish_tree": None,
        "path_count": 0,
        "mismatches": [],
    }
    try:
        from scripts.execution.run_pi_authoritative_producer import (
            authority_repo_publish_context_from_env,
            resolve_authority_publish_paths,
        )
    except Exception as exc:
        result["reason"] = f"publish_helper_import_failed::{exc}"
        return result

    try:
        context = authority_repo_publish_context_from_env(root=ROOT)
    except Exception as exc:
        result["reason"] = f"publish_context_failed::{exc}"
        return result

    publish_tree = Path(str(context["publish_tree"]))
    result["publish_tree"] = str(publish_tree)
    if not publish_tree.exists():
        result["reason"] = "publish_tree_missing"
        return result
    if not (publish_tree / ".git").exists():
        result["reason"] = "publish_tree_not_git_clone"
        return result

    try:
        publish_paths = resolve_authority_publish_paths(root=ROOT)
    except Exception as exc:
        result["reason"] = f"resolve_publish_paths_failed::{exc}"
        return result

    result["path_count"] = len(publish_paths)
    mismatches: list[dict[str, Any]] = []
    for source_path in publish_paths:
        relative = source_path.relative_to(ROOT)
        published_path = publish_tree / relative
        local_hash = sha256_file(source_path)
        published_hash = sha256_file(published_path)
        if local_hash != published_hash:
            mismatches.append(
                {
                    "path": relative.as_posix(),
                    "local_exists": source_path.exists(),
                    "published_exists": published_path.exists(),
                    "local_sha256": local_hash,
                    "published_sha256": published_hash,
                }
            )

    result["mismatches"] = mismatches
    result["current"] = not mismatches
    result["reason"] = "publish_tree_matches_local_authority_paths" if not mismatches else "publish_tree_drift_detected"
    return result


def collect_state() -> dict[str, Any]:
    manifest_path = discover_latest_manifest()
    manifest_payload = read_json_optional(manifest_path) if manifest_path else {}
    authority_attempt = read_json_optional(AUTHORITY_ATTEMPT_PATH)
    authority_success = read_json_optional(AUTHORITY_SUCCESS_PATH)
    freshness_payload = read_json_optional(FRESHNESS_REPORT_PATH)
    local_product_snapshot = read_json_optional(APP_PRODUCT_SNAPSHOT_PATH)
    local_runtime_snapshot = read_json_optional(APP_RUNTIME_SNAPSHOT_PATH)

    checked_files = [
        summarize_path(AUTHORITY_ATTEMPT_PATH),
        summarize_path(AUTHORITY_SUCCESS_PATH),
        summarize_path(FRESHNESS_REPORT_PATH),
        summarize_path(APP_EXPORT_MAIN_PAPER_PATH, date_reader=("csv_last", ["date"])),
        summarize_path(APP_EXPORT_MAIN_METRICS_PATH, date_reader=("csv_first", ["latest_available_date"])),
        summarize_path(APP_EXPORT_REFERENCE_PAPER_PATH, date_reader=("csv_last", ["date"])),
        summarize_path(APP_EXPORT_PHASE66G_LIVE_PATH, date_reader=("csv_first", ["latest_available_date"])),
        summarize_path(BTC_RAW_PATH, date_reader=("csv_last", ["date"])),
        summarize_path(APP_PRODUCT_SNAPSHOT_PATH),
        summarize_path(APP_RUNTIME_SNAPSHOT_PATH),
    ]
    if manifest_path is not None:
        checked_files.append(summarize_path(manifest_path))

    observed_dates = {
        "expected_closed_utc_day": expected_latest_closed_utc_day(),
        "btc_raw_last_date": iso_date(read_last_csv_date(BTC_RAW_PATH, ["date"])),
        "app_export_main_paper_last_date": iso_date(read_last_csv_date(APP_EXPORT_MAIN_PAPER_PATH, ["date"])),
        "app_export_main_metrics_latest_available_date": iso_date(
            read_first_csv_date(APP_EXPORT_MAIN_METRICS_PATH, ["latest_available_date"])
        ),
        "app_export_reference_paper_last_date": iso_date(
            read_last_csv_date(APP_EXPORT_REFERENCE_PAPER_PATH, ["date"])
        ),
        "app_export_phase66g_live_latest_available_date": iso_date(
            read_first_csv_date(APP_EXPORT_PHASE66G_LIVE_PATH, ["latest_available_date"])
        ),
        "freshness_report_latest_closed_utc_date": str(freshness_payload.get("latest_closed_utc_date") or "").strip() or None,
        "local_app_product_strategy_last_closed_day": str(
            local_product_snapshot.get("strategy_last_closed_day") or ""
        ).strip()
        or None,
        "local_app_runtime_latest_strategy_artifact_date": str(
            local_runtime_snapshot.get("latest_strategy_artifact_date") or ""
        ).strip()
        or None,
        "local_app_runtime_latest_available_closed_utc_date": str(
            local_runtime_snapshot.get("latest_available_closed_utc_date") or ""
        ).strip()
        or None,
        "authority_attempt_target_closed_day_utc": str(
            authority_attempt.get("target_closed_day_utc") or ""
        ).strip()
        or None,
        "authority_attempt_latest_available_closed_utc_day": str(
            authority_attempt.get("latest_available_closed_utc_day") or ""
        ).strip()
        or None,
        "authority_attempt_strategy_artifact_closed_day_utc": str(
            authority_attempt.get("strategy_artifact_closed_day_utc") or ""
        ).strip()
        or None,
        "authority_success_target_closed_day_utc": str(
            authority_success.get("target_closed_day_utc") or ""
        ).strip()
        or None,
        "authority_success_strategy_artifact_closed_day_utc": str(
            authority_success.get("strategy_artifact_closed_day_utc") or ""
        ).strip()
        or None,
        "authority_success_app_product_strategy_last_closed_day": str(
            (authority_success.get("app_product_snapshot") or {}).get("strategy_last_closed_day") or ""
        ).strip()
        or None,
        "authority_success_app_runtime_latest_strategy_artifact_date": str(
            (authority_success.get("app_runtime_snapshot") or {}).get("latest_strategy_artifact_date") or ""
        ).strip()
        or None,
        "latest_manifest_target_closed_day_utc": str(
            ((manifest_payload.get("raw_skip_preflight") or {}).get("target_last_closed_date")) or ""
        ).strip()
        or None,
    }

    export_dates = [
        parse_iso_date(observed_dates["app_export_main_paper_last_date"]),
        parse_iso_date(observed_dates["app_export_main_metrics_latest_available_date"]),
        parse_iso_date(observed_dates["app_export_reference_paper_last_date"]),
        parse_iso_date(observed_dates["app_export_phase66g_live_latest_available_date"]),
    ]
    available_export_dates = [value for value in export_dates if value is not None]
    latest_strategy_artifact_date = min(available_export_dates).isoformat() if available_export_dates else None

    latest_available_candidates = [
        parse_iso_date(observed_dates["btc_raw_last_date"]),
        parse_iso_date(observed_dates["authority_attempt_latest_available_closed_utc_day"]),
        parse_iso_date(observed_dates["local_app_runtime_latest_available_closed_utc_date"]),
        parse_iso_date(observed_dates["freshness_report_latest_closed_utc_date"]),
    ]
    available_candidates = [value for value in latest_available_candidates if value is not None]
    latest_available_closed_utc_day = max(available_candidates).isoformat() if available_candidates else None
    comparison_target = min(
        parse_iso_date(observed_dates["expected_closed_utc_day"]) or date.min,
        parse_iso_date(latest_available_closed_utc_day) or date.min,
    ).isoformat() if available_candidates else None

    publish_tree_state = compute_publish_tree_state()

    return {
        "generated_at_utc": utc_now_iso(),
        "checked_files": checked_files,
        "observed_dates": observed_dates,
        "authority_attempt": authority_attempt,
        "authority_success": authority_success,
        "freshness_payload": freshness_payload,
        "local_product_snapshot": local_product_snapshot,
        "local_runtime_snapshot": local_runtime_snapshot,
        "latest_manifest_path": relative_path(manifest_path) if manifest_path else None,
        "latest_manifest_payload": manifest_payload,
        "expected_closed_utc_day": observed_dates["expected_closed_utc_day"],
        "latest_available_closed_utc_day": latest_available_closed_utc_day,
        "latest_strategy_artifact_date": latest_strategy_artifact_date,
        "comparison_target_closed_utc_day": comparison_target,
        "last_successful_run_id": str(authority_success.get("run_id") or manifest_payload.get("run_id") or "").strip() or None,
        "last_attempt_run_id": str(authority_attempt.get("run_id") or manifest_payload.get("run_id") or "").strip() or None,
        "latest_authoritative_attempt_status": str(
            authority_attempt.get("latest_authoritative_attempt_status") or ""
        ).strip()
        or None,
        "github_published_local_files_current": publish_tree_state,
    }


def state_truths(state: dict[str, Any]) -> dict[str, Any]:
    expected_day = parse_iso_date(state["expected_closed_utc_day"])
    latest_available_day = parse_iso_date(state["latest_available_closed_utc_day"])
    comparison_target = parse_iso_date(state["comparison_target_closed_utc_day"])
    observed = state["observed_dates"]
    manifest_payload = state["latest_manifest_payload"]
    authority_attempt = state["authority_attempt"]
    authority_success = state["authority_success"]
    freshness_payload = state["freshness_payload"]
    local_product_snapshot = state["local_product_snapshot"]
    local_runtime_snapshot = state["local_runtime_snapshot"]

    export_date_values = {
        "main_paper": parse_iso_date(observed["app_export_main_paper_last_date"]),
        "main_metrics": parse_iso_date(observed["app_export_main_metrics_latest_available_date"]),
        "reference_paper": parse_iso_date(observed["app_export_reference_paper_last_date"]),
        "phase66g_live": parse_iso_date(observed["app_export_phase66g_live_latest_available_date"]),
    }

    app_exports_current = bool(comparison_target) and all(
        value == comparison_target for value in export_date_values.values() if value is not None
    )
    app_snapshots_current = bool(comparison_target) and (
        parse_iso_date(observed["local_app_product_strategy_last_closed_day"]) == comparison_target
        and parse_iso_date(observed["local_app_runtime_latest_strategy_artifact_date"]) == comparison_target
        and parse_iso_date(observed["freshness_report_latest_closed_utc_date"]) == comparison_target
    )
    authority_current = bool(comparison_target) and (
        str(authority_attempt.get("latest_authoritative_attempt_status") or "").strip().lower() == "success"
        and parse_iso_date(observed["authority_attempt_target_closed_day_utc"]) == comparison_target
        and parse_iso_date(observed["authority_attempt_strategy_artifact_closed_day_utc"]) == comparison_target
        and parse_iso_date(observed["authority_success_target_closed_day_utc"]) == comparison_target
        and parse_iso_date(observed["authority_success_strategy_artifact_closed_day_utc"]) == comparison_target
        and parse_iso_date(observed["authority_success_app_product_strategy_last_closed_day"]) == comparison_target
        and parse_iso_date(observed["authority_success_app_runtime_latest_strategy_artifact_date"]) == comparison_target
    )

    manifest_status = str(
        manifest_payload.get("main_refresh_chain_status")
        or manifest_payload.get("refresh_source_status")
        or manifest_payload.get("status")
        or ""
    ).strip().upper()
    manifest_success = manifest_status in SUCCESS_STATUSES
    manifest_target = parse_iso_date(observed["latest_manifest_target_closed_day_utc"])
    scheduler_has_current_run = bool(comparison_target and manifest_target == comparison_target and manifest_success)

    authority_attempt_status = str(authority_attempt.get("latest_authoritative_attempt_status") or "").strip().lower()
    authority_attempt_failed = authority_attempt_status == "failed"
    authority_attempt_success = authority_attempt_status == "success"

    freshness_status_ok = str(freshness_payload.get("status") or "").strip().lower() == "ok"
    raw_btc_last_date = parse_iso_date(observed["btc_raw_last_date"])
    raw_data_current = bool(comparison_target and raw_btc_last_date == comparison_target)
    raw_data_stale = bool(expected_day and raw_btc_last_date and raw_btc_last_date < expected_day)

    not_time_yet = bool(
        expected_day
        and latest_available_day
        and latest_available_day < expected_day
        and utc_now() < utc_day_start() + timedelta(hours=NOT_TIME_YET_GRACE_HOURS)
        and app_exports_current
        and authority_current
    )

    local_backend_current = app_exports_current and app_snapshots_current and freshness_status_ok and raw_data_current

    publish_state = state["github_published_local_files_current"]
    publish_current = publish_state.get("current")
    publish_known_stale = publish_current is False

    upstream_date_values = {
        "phase68g_source_paper": read_last_csv_date(UPSTREAM_PHASE68G_SOURCE_PAPER_PATH, ["date"]),
        "phase68g_source_metrics": read_first_csv_date(UPSTREAM_PHASE68G_SOURCE_METRICS_PATH, ["latest_available_date"]),
        "phase67j_source_paper": read_last_csv_date(UPSTREAM_PHASE67J_SOURCE_PAPER_PATH, ["date"]),
        "phase66g_source_live": read_first_csv_date(UPSTREAM_PHASE66G_SOURCE_LIVE_PATH, ["latest_available_date"]),
    }
    upstream_phase_outputs_current = bool(comparison_target) and all(
        value == comparison_target for value in upstream_date_values.values() if value is not None
    )

    authority_snapshot_present = bool(authority_success)
    authority_snapshot_stale = authority_attempt_success and not authority_current

    return {
        "comparison_target": iso_date(comparison_target),
        "export_date_values": {key: iso_date(value) for key, value in export_date_values.items()},
        "upstream_date_values": {key: iso_date(value) for key, value in upstream_date_values.items()},
        "app_exports_current": app_exports_current,
        "app_snapshots_current": app_snapshots_current,
        "authority_current": authority_current,
        "authority_attempt_failed": authority_attempt_failed,
        "authority_attempt_success": authority_attempt_success,
        "authority_snapshot_present": authority_snapshot_present,
        "authority_snapshot_stale": authority_snapshot_stale,
        "manifest_success": manifest_success,
        "manifest_status": manifest_status or None,
        "manifest_target": iso_date(manifest_target),
        "scheduler_has_current_run": scheduler_has_current_run,
        "freshness_status_ok": freshness_status_ok,
        "raw_data_current": raw_data_current,
        "raw_data_stale": raw_data_stale,
        "not_time_yet": not_time_yet,
        "local_backend_current": local_backend_current,
        "publish_current": publish_current,
        "publish_known_stale": publish_known_stale,
        "upstream_phase_outputs_current": upstream_phase_outputs_current,
    }


def classify_incident(state: dict[str, Any], truths: dict[str, Any]) -> tuple[str, str, str, str | None]:
    comparison_target = truths["comparison_target"]
    expected_day = state["expected_closed_utc_day"]

    if truths["local_backend_current"] and truths["authority_current"] and truths["publish_current"] is not False:
        return (
            "ok",
            "OK_CURRENT",
            f"Local backend artifacts and authority artifacts are aligned with {comparison_target}.",
            None,
        )

    if truths["not_time_yet"]:
        return (
            "waiting",
            "NOT_TIME_YET",
            (
                "Latest closed-day raw data has not fully arrived within the configured UTC grace window; "
                f"backend artifacts remain aligned to {comparison_target}."
            ),
            None,
        )

    if truths["authority_attempt_failed"]:
        return (
            "needs_attention",
            "AUTHORITY_ATTEMPT_FAILED",
            "The latest authority attempt ended in failed state, so the backend cannot trust the most recent refresh output.",
            "Inspect outputs/execution/authority/latest_attempt_status.json and the upstream authoritative run logs.",
        )

    if state["latest_manifest_path"] and truths["manifest_target"] == comparison_target and not truths["manifest_success"]:
        return (
            "needs_attention",
            "PIPELINE_FAILED",
            "The latest local app refresh manifest targeted the expected day but did not finish successfully.",
            "Inspect the latest app refresh pipeline logs and rerun the refresh pipeline after fixing the failing step.",
        )

    if not truths["scheduler_has_current_run"]:
        return (
            "needs_attention",
            "SCHEDULER_NOT_RUN",
            (
                "The local app refresh pipeline has not produced a successful manifest for the latest required closed day, "
                "so the app snapshot/runtime layer is stale even though some authority files may already be current."
            ),
            f"Rerun {relative_path(DAILY_REFRESH_SCRIPT)} to rebuild the local app-facing layer for {comparison_target or expected_day}.",
        )

    if truths["raw_data_stale"]:
        return (
            "needs_attention",
            "RAW_DATA_STALE",
            f"BTC raw daily data is still behind the expected latest closed UTC day {expected_day}.",
            "Refresh the raw OHLCV source before attempting further app-facing rebuilds.",
        )

    if truths["authority_snapshot_stale"] or not truths["authority_snapshot_present"]:
        return (
            "needs_attention",
            "AUTHORITY_SNAPSHOT_STALE",
            "Authority attempt metadata exists, but the latest successful authority snapshot is missing or not aligned with the expected closed day.",
            "Repair the authority publish step on the authoritative producer and republish the snapshot.",
        )

    if not truths["app_exports_current"] and truths["upstream_phase_outputs_current"]:
        return (
            "needs_attention",
            "APP_EXPORT_STALE",
            "Canonical app export files are stale relative to current upstream phase outputs.",
            f"Rerun {relative_path(MATERIALIZE_SCRIPT)} to rematerialize canonical app exports.",
        )

    if truths["authority_current"] and truths["publish_known_stale"]:
        return (
            "needs_attention",
            "AUTHORITY_PUBLISH_STALE",
            "Authority artifacts are current locally, but the local authority publish tree diverges from those files.",
            "Rerun the authority repo publish helper and verify the publish tree can fetch/push the remote branch.",
        )

    if truths["authority_current"] and truths["app_exports_current"] and truths["app_snapshots_current"]:
        return (
            "needs_attention",
            "APP_DEPLOY_OR_CACHE_STALE",
            "Backend artifacts are current, which points to a downstream deploy or cache issue outside this repository.",
            "Invalidate the downstream app cache or redeploy the app layer that reads these artifacts.",
        )

    return (
        "needs_attention",
        "UNKNOWN_NEEDS_HUMAN",
        "The watchdog found stale or divergent backend state, but it did not match a safe deterministic remediation pattern.",
        "Review the checked files, authority state, and latest manifest manually.",
    )


def choose_safe_action(incident_class: str, truths: dict[str, Any]) -> dict[str, Any]:
    if incident_class == "SCHEDULER_NOT_RUN":
        return {
            "eligible": True,
            "action": "rerun_daily_refresh_app_pipeline",
            "command": [sys.executable, str(DAILY_REFRESH_SCRIPT)],
            "reason": "Local scheduler/pipeline has not produced a successful current-day manifest.",
        }
    if incident_class == "APP_EXPORT_STALE" and truths["upstream_phase_outputs_current"]:
        return {
            "eligible": True,
            "action": "rerun_materialize_execution_app_exports",
            "command": [sys.executable, str(MATERIALIZE_SCRIPT)],
            "reason": "Canonical app exports are stale while upstream phase outputs are already current.",
        }
    if incident_class == "AUTHORITY_PUBLISH_STALE" and truths["authority_current"]:
        return {
            "eligible": True,
            "action": "rerun_authority_repo_publish_helper",
            "command": None,
            "reason": "Authority artifacts are current locally, but the publish tree is stale.",
        }
    return {
        "eligible": False,
        "action": None,
        "command": None,
        "reason": "No safe remediation action is allowed for this incident class.",
    }


def run_safe_action(action: dict[str, Any]) -> dict[str, Any]:
    if not action.get("eligible"):
        return {
            "status": "skipped",
            "action": action.get("action"),
            "reason": action.get("reason"),
        }

    if action["action"] == "rerun_authority_repo_publish_helper":
        try:
            from scripts.execution.run_pi_authoritative_producer import publish_authority_artifacts_to_repo

            publish_result = publish_authority_artifacts_to_repo(root=ROOT)
            return {
                "status": "completed" if publish_result.get("published") else "failed",
                "action": action["action"],
                "reason": action["reason"],
                "publish_result": publish_result,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "action": action["action"],
                "reason": action["reason"],
                "error": str(exc),
            }

    command = action["command"]
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "status": "completed" if completed.returncode == 0 else "failed",
        "action": action["action"],
        "reason": action["reason"],
        "returncode": completed.returncode,
        "command": command,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-12000:],
    }


def build_summary(report: dict[str, Any]) -> str:
    lines = [
        f"status: {report['status']}",
        f"incident_class: {report['incident_class']}",
        f"root_cause: {report['root_cause']}",
        f"expected_closed_utc_day: {report['expected_closed_utc_day']}",
        f"latest_available_closed_utc_day: {report['latest_available_closed_utc_day']}",
        f"latest_strategy_artifact_date: {report['latest_strategy_artifact_date']}",
        f"latest_authoritative_attempt_status: {report['latest_authoritative_attempt_status']}",
        f"currentness_status: {report['currentness_status']}",
        f"last_successful_run_id: {report['last_successful_run_id']}",
        f"last_attempt_run_id: {report['last_attempt_run_id']}",
        (
            "github_published_local_files_current: "
            + json.dumps(report["github_published_local_files_current"]["current"])
        ),
        f"action_taken: {report['action_taken']}",
        f"action_result: {report['action_result'].get('status')}",
    ]
    if report.get("manual_next_step"):
        lines.append(f"manual_next_step: {report['manual_next_step']}")
    return "\n".join(lines) + "\n"


def currentness_status_from_incident(incident_class: str) -> str:
    if incident_class == "OK_CURRENT":
        return "current"
    if incident_class == "NOT_TIME_YET":
        return "not_time_yet"
    return "stale"


def build_report(*, remediation_enabled: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    state = collect_state()
    truths = state_truths(state)
    status, incident_class, root_cause, manual_next_step = classify_incident(state, truths)
    if incident_class not in INCIDENT_CLASSES:
        raise RuntimeError(f"Unexpected incident class: {incident_class}")

    safe_action = choose_safe_action(incident_class, truths)
    action_result: dict[str, Any]
    final_state = state
    final_truths = truths
    final_status = status
    final_incident_class = incident_class
    final_root_cause = root_cause
    final_manual_next_step = manual_next_step

    if remediation_enabled:
        action_result = run_safe_action(safe_action)
        if action_result.get("status") == "completed":
            final_state = collect_state()
            final_truths = state_truths(final_state)
            (
                final_status,
                final_incident_class,
                final_root_cause,
                final_manual_next_step,
            ) = classify_incident(final_state, final_truths)
        elif action_result.get("status") == "failed":
            final_status = "remediation_failed"
    else:
        action_result = {
            "status": "skipped",
            "reason": "check_only_mode",
            "eligible": safe_action.get("eligible"),
        }

    report = {
        "generated_at_utc": utc_now_iso(),
        "mode": "remediate_safe" if remediation_enabled else "check_only",
        "status": final_status,
        "incident_class": final_incident_class,
        "root_cause": final_root_cause,
        "expected_closed_utc_day": final_state["expected_closed_utc_day"],
        "latest_available_closed_utc_day": final_state["latest_available_closed_utc_day"],
        "latest_strategy_artifact_date": final_state["latest_strategy_artifact_date"],
        "latest_authoritative_attempt_status": final_state["latest_authoritative_attempt_status"],
        "currentness_status": currentness_status_from_incident(final_incident_class),
        "last_successful_run_id": final_state["last_successful_run_id"],
        "last_attempt_run_id": final_state["last_attempt_run_id"],
        "github_published_local_files_current": final_state["github_published_local_files_current"],
        "observed_dates": final_state["observed_dates"],
        "checked_files": final_state["checked_files"],
        "latest_manifest_path": final_state["latest_manifest_path"],
        "latest_manifest_status": final_truths["manifest_status"],
        "latest_manifest_target_closed_day_utc": final_truths["manifest_target"],
        "comparison_target_closed_utc_day": final_truths["comparison_target"],
        "diagnostic_flags": {
            "app_exports_current": final_truths["app_exports_current"],
            "app_snapshots_current": final_truths["app_snapshots_current"],
            "authority_current": final_truths["authority_current"],
            "raw_data_current": final_truths["raw_data_current"],
            "raw_data_stale": final_truths["raw_data_stale"],
            "scheduler_has_current_run": final_truths["scheduler_has_current_run"],
            "upstream_phase_outputs_current": final_truths["upstream_phase_outputs_current"],
            "not_time_yet": final_truths["not_time_yet"],
        },
        "date_breakdown": {
            "app_exports": final_truths["export_date_values"],
            "upstream_phase_outputs": final_truths["upstream_date_values"],
        },
        "action_taken": safe_action["action"] if remediation_enabled and safe_action.get("eligible") else "none",
        "action_result": action_result,
        "manual_next_step": final_manual_next_step,
    }
    actions_payload = {
        "generated_at_utc": report["generated_at_utc"],
        "mode": report["mode"],
        "incident_class": report["incident_class"],
        "selected_action": safe_action,
        "action_result": action_result,
    }
    return report, actions_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic MRV1 backend self-healing watchdog")
    parser.add_argument("--check-only", action="store_true", help="Run diagnostics only (default).")
    parser.add_argument("--remediate-safe", action="store_true", help="Allow only safe remediation actions.")
    parser.add_argument("--json", action="store_true", help="Print the final report JSON to stdout.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    remediation_enabled = bool(args.remediate_safe)
    report, actions_payload = build_report(remediation_enabled=remediation_enabled)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(build_summary(report), encoding="utf-8")
    ACTIONS_PATH.write_text(json.dumps(actions_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(build_summary(report), end="")


if __name__ == "__main__":
    main()
