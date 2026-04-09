from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: Missing dependency 'requests'. Install with: pip install requests")
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.execution.app_execute_bridge import run_app_execute_action  # noqa: E402
from scripts.execution.trading_operation_mode import (  # noqa: E402
    DEFAULT_TRADING_OPERATION_MODE_PATH,
    load_trading_operation_mode_payload,
)

OUTPUTS_DIR = ROOT / "outputs" / "execution"
FULL_AUTO_DIR = OUTPUTS_DIR / "full_auto"
DRY_RUN_DIR = OUTPUTS_DIR / "dry_run"
INTENTS_DIR = OUTPUTS_DIR / "intents"
READ_ONLY_DIR = OUTPUTS_DIR / "read_only"
LIVE_STATUS_DIR = OUTPUTS_DIR / "live_status"
LIVE_GATE_DIR = OUTPUTS_DIR / "live_gate"
RECON_DIR = OUTPUTS_DIR / "reconciliation"
SUBMIT_DIR = OUTPUTS_DIR / "submit_preview"
SCHEDULER_DIR = OUTPUTS_DIR / "full_auto_scheduler"
RUNS_DIR = SCHEDULER_DIR / "runs"
LOGS_DIR = OUTPUTS_DIR / "logs"
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"

CHILD_SCRIPT_PATH = ROOT / "scripts" / "execution" / "run_full_auto_execution_cycle.py"

DECISION_PATH = SCHEDULER_DIR / "latest_scheduler_entry_decision.json"
MANIFEST_PATH = SCHEDULER_DIR / "latest_scheduler_entry_manifest.json"
RESTORE_PROFILE_PATH = SCHEDULER_DIR / "latest_scheduler_entry_restore_profile.json"
LOG_PATH = LOGS_DIR / "run_full_auto_scheduler_entry.log"

FULL_AUTO_RUNNER_DECISION_PATH = FULL_AUTO_DIR / "latest_full_auto_runner_decision.json"
FULL_AUTO_RUNNER_MANIFEST_PATH = FULL_AUTO_DIR / "latest_full_auto_runner_manifest.json"
FULL_AUTO_RUNNER_SNAPSHOT_PATH = FULL_AUTO_DIR / "latest_full_auto_runner_snapshot.json"
FULL_AUTO_SKIP_REASON_PATH = FULL_AUTO_DIR / "latest_full_auto_skip_reason.json"

INFO_URL = "https://api.hyperliquid.xyz/info"
MANUAL_CONFIRM_TOKEN = "FULL_AUTO_EXECUTION"
TRADING_OPERATION_MODE_PATH = DEFAULT_TRADING_OPERATION_MODE_PATH
LIVE_ORDER_ACTIONS = {
    "simulate_enter_target_asset",
    "simulate_exit_to_cash",
    "simulate_rotate_position",
}

BASE_REQUIRED_DOWNSTREAM_ARTIFACTS: list[tuple[str, Path, list[str]]] = [
    (
        "account_snapshot",
        READ_ONLY_DIR / "hyperliquid_account_snapshot.json",
        ["account_address", "summary", "raw"],
    ),
    (
        "account_snapshot_quality",
        READ_ONLY_DIR / "hyperliquid_account_snapshot_quality.json",
        ["snapshot_ok", "account_address_present"],
    ),
    (
        "account_snapshot_manifest",
        READ_ONLY_DIR / "hyperliquid_account_snapshot_manifest.json",
        ["artifact_name", "status", "output_paths"],
    ),
    (
        "execution_status",
        LIVE_STATUS_DIR / "execution_status.json",
        ["status_type", "signal_id", "target_asset"],
    ),
    (
        "execution_intent",
        INTENTS_DIR / "latest_execution_intent.json",
        ["intent_type", "signal_id", "target_asset"],
    ),
    (
        "execution_intent_quality",
        INTENTS_DIR / "latest_execution_intent_quality.json",
        ["intent_ok", "signal_id_present"],
    ),
    (
        "execution_intent_manifest",
        INTENTS_DIR / "latest_execution_intent_manifest.json",
        ["artifact_name", "status", "output_paths"],
    ),
    (
        "dry_run_decision",
        DRY_RUN_DIR / "latest_dry_run_decision.json",
        ["decision_type", "signal_id", "recommended_action"],
    ),
    (
        "dry_run_quality",
        DRY_RUN_DIR / "latest_dry_run_decision_quality.json",
        ["dry_run_ok", "recommended_action"],
    ),
    (
        "dry_run_manifest",
        DRY_RUN_DIR / "latest_dry_run_decision_manifest.json",
        ["artifact_name", "status", "output_paths"],
    ),
    (
        "live_gate_decision",
        LIVE_GATE_DIR / "latest_real_order_gate_decision.json",
        ["decision_type", "status", "block_reasons"],
    ),
    (
        "live_gate_quality",
        LIVE_GATE_DIR / "latest_real_order_gate_quality.json",
        ["gate_ok", "status"],
    ),
    (
        "live_gate_manifest",
        LIVE_GATE_DIR / "latest_real_order_gate_manifest.json",
        ["artifact_name", "status", "output_paths"],
    ),
    (
        "reconciliation_report",
        RECON_DIR / "latest_reconciliation_report.json",
        ["report_type", "signal_id", "reconciliation_action"],
    ),
    (
        "reconciliation_quality",
        RECON_DIR / "latest_reconciliation_quality.json",
        ["reconciliation_ok", "reconciled"],
    ),
    (
        "reconciliation_manifest",
        RECON_DIR / "latest_reconciliation_manifest.json",
        ["artifact_name", "status", "output_paths"],
    ),
]

LIVE_CHILD_REQUIRED_DOWNSTREAM_ARTIFACTS: list[tuple[str, Path, list[str]]] = [
    (
        "full_auto_runner_decision",
        FULL_AUTO_RUNNER_DECISION_PATH,
        ["artifact_type", "status", "signal_id"],
    ),
    (
        "full_auto_runner_manifest",
        FULL_AUTO_RUNNER_MANIFEST_PATH,
        ["artifact_type", "status", "output_paths"],
    ),
    (
        "full_auto_runner_snapshot",
        FULL_AUTO_RUNNER_SNAPSHOT_PATH,
        ["account_address"],
    ),
    (
        "full_auto_skip_reason",
        FULL_AUTO_SKIP_REASON_PATH,
        ["artifact_type", "runner_status"],
    ),
    (
        "live_gate_decision",
        LIVE_GATE_DIR / "latest_real_order_gate_decision.json",
        ["decision_type", "status", "block_reasons"],
    ),
    (
        "live_gate_quality",
        LIVE_GATE_DIR / "latest_real_order_gate_quality.json",
        ["gate_ok", "status"],
    ),
    (
        "live_gate_manifest",
        LIVE_GATE_DIR / "latest_real_order_gate_manifest.json",
        ["artifact_name", "status", "output_paths"],
    ),
    (
        "reconciliation_report",
        RECON_DIR / "latest_reconciliation_report.json",
        ["report_type", "signal_id", "reconciliation_action"],
    ),
    (
        "reconciliation_quality",
        RECON_DIR / "latest_reconciliation_quality.json",
        ["reconciliation_ok", "reconciled"],
    ),
    (
        "reconciliation_manifest",
        RECON_DIR / "latest_reconciliation_manifest.json",
        ["artifact_name", "status", "output_paths"],
    ),
    (
        "submit_preview_decision",
        SUBMIT_DIR / "latest_submit_preview_decision.json",
        ["submit_type", "status", "would_submit"],
    ),
    (
        "submit_preview_quality",
        SUBMIT_DIR / "latest_submit_preview_quality.json",
        ["submit_preview_ok", "status"],
    ),
    (
        "submit_preview_manifest",
        SUBMIT_DIR / "latest_submit_preview_manifest.json",
        ["artifact_name", "status", "output_paths"],
    ),
    (
        "submit_request_payload",
        SUBMIT_DIR / "latest_submit_request_payload.json",
        ["artifact_type", "signal_id", "steps"],
    ),
    (
        "submit_exchange_response",
        SUBMIT_DIR / "latest_submit_exchange_response.json",
        ["artifact_type", "signal_id", "action_results"],
    ),
    (
        "submit_leverage_response",
        SUBMIT_DIR / "latest_submit_leverage_action_response.json",
        ["artifact_type", "signal_id", "leverage_action_result"],
    ),
    (
        "submit_pre_snapshot",
        SUBMIT_DIR / "latest_submit_pre_snapshot.json",
        ["account_address"],
    ),
    (
        "submit_post_snapshot",
        SUBMIT_DIR / "latest_submit_post_snapshot.json",
        ["account_address"],
    ),
    (
        "submit_post_reconciliation",
        SUBMIT_DIR / "latest_post_submit_reconciliation.json",
        ["artifact_type", "final_status", "signal_id"],
    ),
]


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(message: str) -> None:
    print(message)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def normalize_asset(value: Any) -> str:
    return str(value or "").strip().upper()


def safe_file_state(path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {
        "path": str(path.resolve()),
        "exists": path.exists(),
    }
    if not path.exists():
        return state
    stat = path.stat()
    state["size_bytes"] = stat.st_size
    state["mtime_ns"] = stat.st_mtime_ns
    state["modified_at_utc"] = (
        datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return state


def state_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if bool(before.get("exists")) != bool(after.get("exists")):
        return True
    if not bool(after.get("exists")):
        return False
    return (
        before.get("mtime_ns") != after.get("mtime_ns")
        or before.get("size_bytes") != after.get("size_bytes")
    )


def snapshot_source_of_truth_state() -> dict[str, dict[str, int]]:
    snapshot: dict[str, dict[str, int]] = {}
    for path in sorted(SOURCE_OF_TRUTH_DIR.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        snapshot[str(path.relative_to(SOURCE_OF_TRUTH_DIR))] = {
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    return snapshot


def diff_source_of_truth_state(
    before: dict[str, dict[str, int]],
    after: dict[str, dict[str, int]],
) -> list[str]:
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed.append(key)
    return changed


def parse_http_date_header(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def compute_fresh_time_offset() -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    offsets: list[int] = []

    for attempt in range(1, 4):
        request_started_ms = time.time_ns() // 1_000_000
        try:
            response = requests.post(INFO_URL, json={"type": "meta"}, timeout=15)
            request_finished_ms = time.time_ns() // 1_000_000
        except requests.RequestException as exc:
            samples.append(
                {
                    "attempt": attempt,
                    "request_started_ms": request_started_ms,
                    "request_finished_ms": time.time_ns() // 1_000_000,
                    "error": f"request_failed:{type(exc).__name__}:{exc}",
                }
            )
            continue

        sample: dict[str, Any] = {
            "attempt": attempt,
            "request_started_ms": request_started_ms,
            "request_finished_ms": request_finished_ms,
            "round_trip_ms": max(0, request_finished_ms - request_started_ms),
            "http_status": response.status_code,
            "date_header": response.headers.get("Date"),
        }

        server_time_ms = parse_http_date_header(sample["date_header"] or "")
        sample["server_time_ms"] = server_time_ms
        if response.status_code != 200:
            sample["error"] = f"http_status_{response.status_code}"
            samples.append(sample)
            continue
        if server_time_ms is None:
            sample["error"] = "missing_or_invalid_date_header"
            samples.append(sample)
            continue

        midpoint_ms = (request_started_ms + request_finished_ms) // 2
        offset_ms = int(server_time_ms - midpoint_ms)
        sample["midpoint_ms"] = midpoint_ms
        sample["offset_ms"] = offset_ms
        samples.append(sample)
        offsets.append(offset_ms)

    if not offsets:
        errors = [
            str(sample.get("error", "unknown_error"))
            for sample in samples
            if sample.get("error")
        ]
        raise RuntimeError(
            "Could not compute fresh HYPERLIQUID_TIME_OFFSET_MS from Hyperliquid info endpoint: "
            + " | ".join(errors or ["no_valid_samples"])
        )

    sorted_offsets = sorted(offsets)
    selected_offset_ms = int(sorted_offsets[len(sorted_offsets) // 2])
    return {
        "artifact_type": "hyperliquid_time_offset_refresh",
        "generated_at_utc": utc_now_iso(),
        "source_url": INFO_URL,
        "probe_payload": {"type": "meta"},
        "sample_count": len(offsets),
        "selected_offset_ms": selected_offset_ms,
        "min_offset_ms": min(offsets),
        "max_offset_ms": max(offsets),
        "samples": samples,
        "notes": [
            "Offset is estimated from the HTTP Date header on a fresh Hyperliquid info request.",
            "The selected offset is the median valid sample to reduce one-off jitter.",
        ],
    }


def require_manual_execution(*, execute_live: bool, manual_confirm: str) -> None:
    if not execute_live:
        return
    if manual_confirm != MANUAL_CONFIRM_TOKEN:
        raise ValueError(
            "Manual confirmation missing. "
            f"Pass --manual-confirm {MANUAL_CONFIRM_TOKEN} together with --execute-live."
        )


def emit_child_output(stdout_text: str, stderr_text: str) -> None:
    if stdout_text:
        print("[SCHEDULER_ENTRY][child][stdout] BEGIN", flush=True)
        sys.stdout.write(stdout_text if stdout_text.endswith("\n") else stdout_text + "\n")
        print("[SCHEDULER_ENTRY][child][stdout] END", flush=True)
    if stderr_text:
        print("[SCHEDULER_ENTRY][child][stderr] BEGIN", file=sys.stderr, flush=True)
        sys.stderr.write(stderr_text if stderr_text.endswith("\n") else stderr_text + "\n")
        print("[SCHEDULER_ENTRY][child][stderr] END", file=sys.stderr, flush=True)


def build_child_command(
    args: argparse.Namespace,
    *,
    execute_live: bool,
) -> list[str]:
    command = [sys.executable, str(CHILD_SCRIPT_PATH.resolve())]
    if execute_live:
        command.extend(["--execute-live", "--manual-confirm", args.manual_confirm])
    if args.intent_path is not None:
        command.extend(["--intent-path", str(args.intent_path.resolve())])
    if args.snapshot_path is not None:
        command.extend(["--snapshot-path", str(args.snapshot_path.resolve())])
    if args.mode_config_path is not None:
        command.extend(["--mode-config-path", str(args.mode_config_path.resolve())])
    if args.live_order_policy_path is not None:
        command.extend(
            ["--live-order-policy-path", str(args.live_order_policy_path.resolve())]
        )
    if args.account_config_path is not None:
        command.extend(["--account-config-path", str(args.account_config_path.resolve())])
    if args.commit_idempotency_record:
        command.append("--commit-idempotency-record")
    return command


def run_child_process(
    *,
    args: argparse.Namespace,
    env: dict[str, str],
    run_dir: Path,
    execute_live: bool,
) -> dict[str, Any]:
    child_stdout_path = run_dir / "child.stdout.log"
    child_stderr_path = run_dir / "child.stderr.log"
    command = build_child_command(args, execute_live=execute_live)
    child_started_at_utc = utc_now_iso()
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    elapsed_sec = round(time.monotonic() - started, 3)
    stdout_text = result.stdout or ""
    stderr_text = result.stderr or ""
    child_stdout_path.write_text(stdout_text, encoding="utf-8")
    child_stderr_path.write_text(stderr_text, encoding="utf-8")
    emit_child_output(stdout_text, stderr_text)
    return {
        "command": command,
        "started_at_utc": child_started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "elapsed_sec": elapsed_sec,
        "returncode": result.returncode,
        "stdout_log_path": str(child_stdout_path.resolve()),
        "stderr_log_path": str(child_stderr_path.resolve()),
    }


def verify_required_artifacts(
    required_artifacts: list[tuple[str, Path, list[str]]],
    before_states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    missing_labels: list[str] = []
    unchanged_labels: list[str] = []
    invalid_labels: list[str] = []

    for label, path, required_keys in required_artifacts:
        before_state = before_states[label]
        after_state = safe_file_state(path)
        artifact_result: dict[str, Any] = {
            "label": label,
            "before": before_state,
            "after": after_state,
            "changed_after_run": state_changed(before_state, after_state),
            "valid_json": None,
            "missing_required_keys": [],
        }

        if not after_state["exists"]:
            missing_labels.append(label)
            artifacts.append(artifact_result)
            continue

        if not artifact_result["changed_after_run"]:
            unchanged_labels.append(label)

        payload = read_json_if_exists(path)
        if payload is None:
            artifact_result["valid_json"] = False
            invalid_labels.append(label)
            artifacts.append(artifact_result)
            continue

        artifact_result["valid_json"] = True
        missing_required_keys = [key for key in required_keys if key not in payload]
        artifact_result["missing_required_keys"] = missing_required_keys
        if missing_required_keys:
            invalid_labels.append(label)
        artifacts.append(artifact_result)

    return {
        "artifacts": artifacts,
        "missing_labels": missing_labels,
        "unchanged_labels": unchanged_labels,
        "invalid_labels": invalid_labels,
        "ok": not any((missing_labels, unchanged_labels, invalid_labels)),
    }


def build_runner_summary() -> dict[str, Any] | None:
    runner_decision = read_json_if_exists(FULL_AUTO_RUNNER_DECISION_PATH)
    if runner_decision is None:
        return None
    return {
        "status": runner_decision.get("status"),
        "signal_id": runner_decision.get("signal_id"),
        "target_asset": normalize_asset(runner_decision.get("target_asset")),
        "execute_live": bool(runner_decision.get("execute_live", False)),
        "real_order_sent": bool(runner_decision.get("real_order_sent", False)),
        "duplicate_prevented": bool(runner_decision.get("duplicate_prevented", False)),
        "gate_status": runner_decision.get("gate_status"),
        "reconciliation_action": runner_decision.get("reconciliation_action"),
        "idempotency_record_written": bool(
            runner_decision.get("idempotency_record_written", False)
        ),
    }


def build_submit_summary() -> dict[str, Any] | None:
    decision = read_json_if_exists(SUBMIT_DIR / "latest_submit_preview_decision.json")
    if decision is None:
        return None
    return {
        "status": decision.get("status"),
        "would_submit": bool(decision.get("would_submit", False)),
        "real_order_sent": bool(decision.get("real_order_sent", False)),
        "target_asset": normalize_asset(decision.get("target_asset")),
        "signal_id": decision.get("signal_id"),
        "submit_block_reasons": decision.get("submit_block_reasons", []),
    }


def build_reconciliation_summary() -> dict[str, Any] | None:
    report = read_json_if_exists(RECON_DIR / "latest_reconciliation_report.json")
    if report is None:
        return None
    return {
        "signal_id": report.get("signal_id"),
        "target_asset": normalize_asset(report.get("target_asset")),
        "current_state": report.get("current_state"),
        "reconciled": bool(report.get("reconciled", False)),
        "reconciliation_action": report.get("reconciliation_action"),
        "open_orders_count": report.get("open_orders_count"),
    }


def build_gate_summary() -> dict[str, Any] | None:
    decision = read_json_if_exists(LIVE_GATE_DIR / "latest_real_order_gate_decision.json")
    if decision is None:
        return None
    return {
        "status": decision.get("status"),
        "signal_id": decision.get("signal_id"),
        "target_asset": normalize_asset(decision.get("target_asset")),
        "approval_gate_status": decision.get("approval_gate_status"),
        "would_place_real_order": bool(decision.get("would_place_real_order", False)),
        "block_reasons": decision.get("block_reasons", []),
    }


def build_dry_run_summary() -> dict[str, Any] | None:
    decision = read_json_if_exists(DRY_RUN_DIR / "latest_dry_run_decision.json")
    if decision is None:
        return None
    return {
        "signal_id": decision.get("signal_id"),
        "target_asset": normalize_asset(decision.get("target_asset")),
        "recommended_action": decision.get("recommended_action"),
        "would_place_order": bool(
            decision.get("simulated_order", {}).get("would_place_order", False)
        ),
        "stale_signal": bool(decision.get("stale_signal", False)),
        "duplicate_order_risk": bool(decision.get("duplicate_order_risk", False)),
    }


def summarize_bridge_dry_run_result(result: dict[str, Any]) -> dict[str, Any]:
    result_summary = (
        result.get("result_summary")
        if isinstance(result.get("result_summary"), dict)
        else {}
    )
    return {
        "ok": bool(result.get("ok", False)),
        "status": result.get("status"),
        "error": result.get("error"),
        "user_summary": result.get("user_summary"),
        "recommended_action": result_summary.get("recommended_action"),
        "target_asset": normalize_asset(result_summary.get("target_asset")),
        "would_place_order": bool(result_summary.get("would_place_order", False)),
        "gate_status": result_summary.get("gate_status"),
        "generated_at_utc": result_summary.get("generated_at_utc"),
        "artifact_paths": result.get("artifact_paths", {}),
    }


def evaluate_auto_submit_readiness() -> dict[str, Any]:
    dry_run_payload = read_json_if_exists(DRY_RUN_DIR / "latest_dry_run_decision.json") or {}
    gate_payload = read_json_if_exists(LIVE_GATE_DIR / "latest_real_order_gate_decision.json") or {}
    execution_mode_payload = read_json_if_exists(
        ROOT / "execution" / "config" / "execution_mode.json"
    ) or {}

    recommended_action = str(dry_run_payload.get("recommended_action") or "").strip()
    gate_status = str(gate_payload.get("status") or "").strip()
    reasons: list[str] = []

    if gate_status != "ready_if_enabled":
        reasons.append(f"gate_status_not_ready_if_enabled::{gate_status or 'missing'}")
    if not bool(gate_payload.get("would_place_real_order", False)):
        reasons.append("gate_does_not_allow_real_order")
    for item in gate_payload.get("block_reasons", []) or []:
        text = str(item or "").strip()
        if text:
            reasons.append(f"gate_block_reason::{text}")

    if recommended_action not in LIVE_ORDER_ACTIONS:
        reasons.append(
            "dry_run_not_real_trade_path::"
            f"{recommended_action or 'missing'}"
        )
    if not bool(dry_run_payload.get("simulated_order", {}).get("would_place_order", False)):
        reasons.append("dry_run_would_place_order_false")
    if bool(dry_run_payload.get("stale_signal", False)):
        reasons.append("dry_run_stale_signal")
    if bool(dry_run_payload.get("duplicate_order_risk", False)):
        reasons.append("dry_run_duplicate_order_risk")
    if not bool(dry_run_payload.get("guardrails", {}).get("contract_validated", False)):
        reasons.append("dry_run_contract_not_validated")

    mode = str(execution_mode_payload.get("mode") or "").strip().lower()
    if mode != "live":
        reasons.append(f"execution_mode_not_live::{mode or 'missing'}")
    if execution_mode_payload.get("trading_enabled") is not True:
        reasons.append("execution_mode_trading_enabled_false")
    if execution_mode_payload.get("kill_switch") is True:
        reasons.append("execution_mode_kill_switch_true")

    deduped_reasons = list(dict.fromkeys(reasons))
    return {
        "ok": not deduped_reasons,
        "signal_id": dry_run_payload.get("signal_id"),
        "target_asset": normalize_asset(dry_run_payload.get("target_asset")),
        "recommended_action": recommended_action,
        "would_place_order": bool(
            dry_run_payload.get("simulated_order", {}).get("would_place_order", False)
        ),
        "gate_status": gate_status,
        "reasons": deduped_reasons,
    }


def build_restore_profile(
    *,
    args: argparse.Namespace,
    run_id: str,
    status: str,
    abort_conditions: list[str],
    decision_path: Path,
) -> dict[str, Any]:
    preview_command = [sys.executable, str(Path(__file__).resolve())]
    if args.intent_path is not None:
        preview_command.extend(["--intent-path", str(args.intent_path.resolve())])
    if args.snapshot_path is not None:
        preview_command.extend(["--snapshot-path", str(args.snapshot_path.resolve())])
    if args.mode_config_path is not None:
        preview_command.extend(["--mode-config-path", str(args.mode_config_path.resolve())])
    if args.live_order_policy_path is not None:
        preview_command.extend(
            ["--live-order-policy-path", str(args.live_order_policy_path.resolve())]
        )
    if args.account_config_path is not None:
        preview_command.extend(["--account-config-path", str(args.account_config_path.resolve())])

    return {
        "artifact_type": "full_auto_scheduler_restore_profile",
        "generated_at_utc": utc_now_iso(),
        "run_id": run_id,
        "scheduler_entry_status": status,
        "abort_conditions": abort_conditions,
        "decision_path": str(decision_path.resolve()),
        "safe_baseline": {
            "trading_operation_mode_expected": {
                "mode": "manual",
            },
            "execution_mode_expected": {
                "mode": "read_only",
                "trading_enabled": False,
                "dry_run_enabled": True,
                "kill_switch": True,
            },
            "live_order_policy_expected": {
                "allow_live_orders": False,
                "max_order_notional_usd": 0.0,
            },
            "source_of_truth_runtime_writes_allowed": False,
        },
        "recovery_steps": [
            "Restore execution/config/trading_operation_mode.json so mode=manual before any further scheduler invocation.",
            "Restore execution/config/execution_mode.json to the validated safe baseline: mode=read_only, trading_enabled=false, dry_run_enabled=true, kill_switch=true.",
            "Restore execution/config/live_order_policy.json so allow_live_orders=false and max_order_notional_usd=0.0 before any further scheduled invocation.",
            "Do not create or modify source_of_truth files from the runtime path.",
            "Rerun the scheduler entry in preview mode first and inspect the latest scheduler-entry, runner, gate, reconciliation, and submit-preview artifacts before considering live mode again.",
            "Use live mode only with the exact two-flag unlock: --execute-live --manual-confirm FULL_AUTO_EXECUTION.",
        ],
        "preview_rerun_command": preview_command,
        "paths": {
            "trading_operation_mode_path": str(TRADING_OPERATION_MODE_PATH.resolve()),
            "execution_mode_path": str(
                (ROOT / "execution" / "config" / "execution_mode.json").resolve()
            ),
            "live_order_policy_path": str(
                (ROOT / "execution" / "config" / "live_order_policy.json").resolve()
            ),
            "scheduler_entry_script_path": str(Path(__file__).resolve()),
            "scheduler_entry_decision_path": str(decision_path.resolve()),
            "runner_decision_path": str(FULL_AUTO_RUNNER_DECISION_PATH.resolve()),
        },
    }


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    run_dir: Path,
    status: str,
    child_process: dict[str, Any] | None,
) -> dict[str, Any]:
    input_paths = [str(CHILD_SCRIPT_PATH.resolve())]
    input_paths.append(str(TRADING_OPERATION_MODE_PATH.resolve()))
    for candidate in (
        args.intent_path,
        args.snapshot_path,
        args.mode_config_path,
        args.live_order_policy_path,
        args.account_config_path,
    ):
        if candidate is not None:
            input_paths.append(str(candidate.resolve()))

    output_paths = [
        str(DECISION_PATH.resolve()),
        str(MANIFEST_PATH.resolve()),
        str(RESTORE_PROFILE_PATH.resolve()),
        str((run_dir / "scheduler_entry_decision.json").resolve()),
        str((run_dir / "scheduler_entry_manifest.json").resolve()),
        str((run_dir / "scheduler_entry_restore_profile.json").resolve()),
    ]
    if child_process is not None:
        output_paths.extend(
            [
                child_process["stdout_log_path"],
                child_process["stderr_log_path"],
            ]
        )

    return {
        "artifact_type": "full_auto_scheduler_entry_manifest",
        "generated_at_utc": utc_now_iso(),
        "run_id": run_id,
        "script_path": str(Path(__file__).resolve()),
        "working_directory": str(ROOT.resolve()),
        "execute_live": bool(args.execute_live),
        "status": status,
        "input_paths": input_paths,
        "output_paths": output_paths,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scheduler-facing one-shot wrapper for the full-auto execution cycle. "
            "Refreshes HYPERLIQUID_TIME_OFFSET_MS, runs exactly one child cycle, "
            "and verifies required downstream artifacts."
        )
    )
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="Unlock live mode. Requires --manual-confirm FULL_AUTO_EXECUTION.",
    )
    parser.add_argument(
        "--manual-confirm",
        default="",
        help=f"Required with --execute-live. Must equal {MANUAL_CONFIRM_TOKEN}.",
    )
    parser.add_argument("--intent-path", type=Path, default=None)
    parser.add_argument("--snapshot-path", type=Path, default=None)
    parser.add_argument("--mode-config-path", type=Path, default=None)
    parser.add_argument("--live-order-policy-path", type=Path, default=None)
    parser.add_argument("--account-config-path", type=Path, default=None)
    parser.add_argument(
        "--commit-idempotency-record",
        action="store_true",
        help="Pass through to run_full_auto_execution_cycle.py.",
    )
    return parser.parse_args()


def resolve_exit_code(status: str) -> int:
    return {
        "success": 0,
        "failed_manual_confirmation": 2,
        "failed_time_offset_refresh": 3,
        "failed_child_process": 4,
        "failed_partial_output_verification": 5,
        "failed_source_of_truth_write_check": 6,
        "failed_preflight": 7,
        "failed_base_chain": 8,
    }.get(status, 1)


def main() -> None:
    args = parse_args()

    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    original_cwd = Path.cwd()
    os.chdir(ROOT)

    started_at_utc = utc_now_iso()
    run_id = utc_stamp()
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    status = "failed_preflight"
    abort_conditions: list[str] = []
    child_process: dict[str, Any] | None = None
    time_offset_refresh: dict[str, Any] | None = None
    source_of_truth_before = snapshot_source_of_truth_state()
    source_of_truth_changes: list[str] = []
    bridge_result: dict[str, Any] | None = None
    auto_submit_evaluation: dict[str, Any] | None = None
    trading_operation_mode = load_trading_operation_mode_payload(TRADING_OPERATION_MODE_PATH)
    requested_execute_live = bool(args.execute_live)
    effective_execute_live = bool(
        requested_execute_live
        and str(trading_operation_mode.get("mode") or "").strip().lower() == "automatic"
    )
    live_child_invoked = False
    execution_suppressed_reasons: list[str] = []

    all_required_artifacts = (
        BASE_REQUIRED_DOWNSTREAM_ARTIFACTS + LIVE_CHILD_REQUIRED_DOWNSTREAM_ARTIFACTS
    )
    downstream_before_states = {
        label: safe_file_state(path)
        for label, path, _required_keys in all_required_artifacts
    }
    downstream_verification: dict[str, Any] = {
        "artifacts": [],
        "missing_labels": [],
        "unchanged_labels": [],
        "invalid_labels": [],
        "ok": False,
    }

    log(
        "[START] run_full_auto_scheduler_entry "
        f"run_id={run_id} requested_execute_live={requested_execute_live} "
        f"effective_execute_live={effective_execute_live} "
        f"trading_operation_mode={trading_operation_mode.get('mode')}"
    )

    try:
        bridge_result = run_app_execute_action(action="dry_run")
        if not bridge_result.get("ok", False):
            abort_conditions.append(
                "base_chain_failed::"
                + str(
                    bridge_result.get("error")
                    or bridge_result.get("user_summary")
                    or "dry_run_failed"
                )
            )
            status = "failed_base_chain"
        else:
            if requested_execute_live and not effective_execute_live:
                execution_suppressed_reasons.append(
                    "requested_execute_live_but_trading_operation_mode_fail_closed_to_manual"
                )

            auto_submit_evaluation = evaluate_auto_submit_readiness()
            if effective_execute_live and not auto_submit_evaluation["ok"]:
                execution_suppressed_reasons.extend(auto_submit_evaluation["reasons"])

            if effective_execute_live and auto_submit_evaluation["ok"]:
                if not CHILD_SCRIPT_PATH.exists():
                    abort_conditions.append(
                        f"missing_child_script::{CHILD_SCRIPT_PATH.resolve()}"
                    )
                    status = "failed_preflight"
                else:
                    require_manual_execution(
                        execute_live=True,
                        manual_confirm=args.manual_confirm,
                    )
                    time_offset_refresh = compute_fresh_time_offset()
                    os.environ["HYPERLIQUID_TIME_OFFSET_MS"] = str(
                        time_offset_refresh["selected_offset_ms"]
                    )
                    log(
                        "[TIME_OFFSET] "
                        f"selected_offset_ms={time_offset_refresh['selected_offset_ms']}"
                    )

                    child_process = run_child_process(
                        args=args,
                        env=os.environ.copy(),
                        run_dir=run_dir,
                        execute_live=True,
                    )
                    live_child_invoked = True
                    if child_process["returncode"] != 0:
                        abort_conditions.append(
                            f"child_process_failed::returncode={child_process['returncode']}"
                        )
                        status = "failed_child_process"

        source_of_truth_after = snapshot_source_of_truth_state()
        source_of_truth_changes = diff_source_of_truth_state(
            source_of_truth_before,
            source_of_truth_after,
        )
        if source_of_truth_changes:
            abort_conditions.append(
                "source_of_truth_modified::" + ",".join(source_of_truth_changes)
            )
            status = "failed_source_of_truth_write_check"

        required_artifacts = list(BASE_REQUIRED_DOWNSTREAM_ARTIFACTS)
        if live_child_invoked:
            required_artifacts.extend(LIVE_CHILD_REQUIRED_DOWNSTREAM_ARTIFACTS)

        downstream_verification = verify_required_artifacts(
            required_artifacts,
            downstream_before_states,
        )
        if status not in {"failed_base_chain", "failed_child_process", "failed_source_of_truth_write_check"} and not downstream_verification["ok"]:
            if downstream_verification["missing_labels"]:
                abort_conditions.append(
                    "missing_downstream_artifacts::"
                    + ",".join(downstream_verification["missing_labels"])
                )
            if downstream_verification["unchanged_labels"]:
                abort_conditions.append(
                    "stale_downstream_artifacts::"
                    + ",".join(downstream_verification["unchanged_labels"])
                )
            if downstream_verification["invalid_labels"]:
                abort_conditions.append(
                    "invalid_downstream_artifacts::"
                    + ",".join(downstream_verification["invalid_labels"])
                )
            status = "failed_partial_output_verification"

        if not abort_conditions:
            status = "success"
    except ValueError as exc:
        abort_conditions.append(f"manual_confirmation_failed::{exc}")
        status = "failed_manual_confirmation"
    except RuntimeError as exc:
        abort_conditions.append(f"time_offset_refresh_failed::{exc}")
        status = "failed_time_offset_refresh"
    finally:
        runner_summary = build_runner_summary() if live_child_invoked else None
        dry_run_summary = build_dry_run_summary()
        gate_summary = build_gate_summary()
        reconciliation_summary = build_reconciliation_summary()
        submit_summary = build_submit_summary() if live_child_invoked else None

        decision = {
            "artifact_type": "full_auto_scheduler_entry_decision",
            "generated_at_utc": utc_now_iso(),
            "started_at_utc": started_at_utc,
            "run_id": run_id,
            "status": status,
            "exit_code": resolve_exit_code(status),
            "execute_live": requested_execute_live,
            "requested_execute_live": requested_execute_live,
            "effective_execute_live": effective_execute_live,
            "live_child_invoked": live_child_invoked,
            "preview_only": not live_child_invoked,
            "manual_confirmation_verified": bool(
                (not effective_execute_live) or args.manual_confirm == MANUAL_CONFIRM_TOKEN
            ),
            "working_directory": str(ROOT.resolve()),
            "invoked_from_cwd": str(original_cwd.resolve()),
            "trading_operation_mode": {
                "mode": trading_operation_mode.get("mode"),
                "updated_at_utc": trading_operation_mode.get("updated_at_utc"),
                "updated_by": trading_operation_mode.get("updated_by"),
                "fail_closed": bool(trading_operation_mode.get("fail_closed", False)),
                "error": trading_operation_mode.get("error"),
                "path": str(TRADING_OPERATION_MODE_PATH.resolve()),
            },
            "hyperliquid_time_offset_ms": (
                None
                if time_offset_refresh is None
                else time_offset_refresh.get("selected_offset_ms")
            ),
            "time_offset_refresh": time_offset_refresh,
            "bridge_dry_run": (
                summarize_bridge_dry_run_result(bridge_result or {})
                if bridge_result is not None
                else None
            ),
            "auto_submit_evaluation": auto_submit_evaluation,
            "execution_suppressed_reasons": execution_suppressed_reasons,
            "child_process": child_process,
            "downstream_verification": downstream_verification,
            "source_of_truth_write_check": {
                "ok": not source_of_truth_changes,
                "changed_files": source_of_truth_changes,
            },
            "runner_summary": runner_summary,
            "dry_run_summary": dry_run_summary,
            "gate_summary": gate_summary,
            "reconciliation_summary": reconciliation_summary,
            "submit_summary": submit_summary,
            "abort_conditions": abort_conditions,
            "restore_profile_path": str(RESTORE_PROFILE_PATH.resolve()),
            "notes": [
                "Scheduler entry is one-shot only. It never loops and it never creates a Task Scheduler task.",
                "Trading operation mode is a separate runtime switch from execution_mode.json and defaults fail-closed to manual.",
                "Live child execution is allowed only with --execute-live --manual-confirm FULL_AUTO_EXECUTION and trading_operation_mode=automatic.",
                "A zero-exit child run is treated as incomplete if required downstream artifacts are missing, stale, or invalid.",
            ],
        }

        restore_profile = build_restore_profile(
            args=args,
            run_id=run_id,
            status=status,
            abort_conditions=abort_conditions,
            decision_path=DECISION_PATH,
        )
        manifest = build_manifest(
            args=args,
            run_id=run_id,
            run_dir=run_dir,
            status=status,
            child_process=child_process,
        )

        write_json(run_dir / "scheduler_entry_decision.json", decision)
        write_json(run_dir / "scheduler_entry_manifest.json", manifest)
        write_json(run_dir / "scheduler_entry_restore_profile.json", restore_profile)
        write_json(DECISION_PATH, decision)
        write_json(MANIFEST_PATH, manifest)
        write_json(RESTORE_PROFILE_PATH, restore_profile)

        log(f"[SAVED] {DECISION_PATH}")
        log(f"[SAVED] {MANIFEST_PATH}")
        log(f"[SAVED] {RESTORE_PROFILE_PATH}")
        log(f"[END] run_full_auto_scheduler_entry status={status}")

    raise SystemExit(resolve_exit_code(status))


if __name__ == "__main__":
    main()
