from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_OF_TRUTH_DIR = ROOT / "source_of_truth"
RUNTIME_HEALTH_DIR = ROOT / "outputs" / "execution" / "runtime_health"
LOOPS_DIR = RUNTIME_HEALTH_DIR / "loops"
ARCHIVE_DIR = RUNTIME_HEALTH_DIR / "archive"
LATEST_HEALTH_PATH = RUNTIME_HEALTH_DIR / "latest_runtime_health.json"
LATEST_MANIFEST_PATH = RUNTIME_HEALTH_DIR / "latest_runtime_health_manifest.json"
EVENTS_PATH = RUNTIME_HEALTH_DIR / "runtime_loop_events.jsonl"
LOCK_PATH = RUNTIME_HEALTH_DIR / "active_runtime.lock.json"
STOP_MARKER_PATH = RUNTIME_HEALTH_DIR / "graceful_stop_request.json"

EXECUTION_MODE_PATH = ROOT / "execution" / "config" / "execution_mode.json"
LIVE_ORDER_POLICY_PATH = ROOT / "execution" / "config" / "live_order_policy.json"
SCRIPT_REGISTRY_PATH = ROOT / "canonical" / "script_registry.json"

APPROVED_LIGHTWEIGHT_STEP_CHAIN: list[tuple[str, str]] = [
    (
        "materialize_execution_app_exports",
        "scripts/execution/materialize_execution_app_exports.py",
    ),
    (
        "validate_execution_source_contract",
        "scripts/execution/validate_execution_source_contract.py",
    ),
    (
        "hyperliquid_read_only_snapshot",
        "scripts/execution/hyperliquid_read_only_snapshot.py",
    ),
    (
        "render_execution_app_status",
        "scripts/execution/render_execution_app_status.py",
    ),
    (
        "build_execution_intent_from_strategy_exports",
        "scripts/execution/build_execution_intent_from_strategy_exports.py",
    ),
    (
        "run_dry_execution_bridge",
        "scripts/execution/run_dry_execution_bridge.py",
    ),
]

STEP_CHAIN: list[tuple[str, Path]] = [
    (
        "materialize_execution_app_exports",
        ROOT / "scripts" / "execution" / "materialize_execution_app_exports.py",
    ),
    (
        "validate_execution_source_contract",
        ROOT / "scripts" / "execution" / "validate_execution_source_contract.py",
    ),
    (
        "hyperliquid_read_only_snapshot",
        ROOT / "scripts" / "execution" / "hyperliquid_read_only_snapshot.py",
    ),
    (
        "render_execution_app_status",
        ROOT / "scripts" / "execution" / "render_execution_app_status.py",
    ),
    (
        "build_execution_intent_from_strategy_exports",
        ROOT / "scripts" / "execution" / "build_execution_intent_from_strategy_exports.py",
    ),
    (
        "run_dry_execution_bridge",
        ROOT / "scripts" / "execution" / "run_dry_execution_bridge.py",
    ),
]

KEY_RUNTIME_OUTPUTS = {
    "materialize_execution_app_exports_report": ROOT
    / "outputs"
    / "execution"
    / "refresh_pipeline"
    / "materialize_execution_app_exports_report.json",
    "execution_source_contract_report": ROOT
    / "outputs"
    / "execution"
    / "source_contract"
    / "execution_source_contract_report.json",
    "hyperliquid_account_snapshot": ROOT
    / "outputs"
    / "execution"
    / "read_only"
    / "hyperliquid_account_snapshot.json",
    "execution_status": ROOT / "outputs" / "execution" / "live_status" / "execution_status.json",
    "latest_execution_intent": ROOT / "outputs" / "execution" / "intents" / "latest_execution_intent.json",
    "latest_dry_run_decision": ROOT / "outputs" / "execution" / "dry_run" / "latest_dry_run_decision.json",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def safe_file_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return info

    stat = path.stat()
    info["size_bytes"] = stat.st_size
    info["modified_utc"] = datetime.fromtimestamp(
        stat.st_mtime,
        tz=timezone.utc,
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return info


def snapshot_source_of_truth_state() -> dict[str, dict[str, int]]:
    state: dict[str, dict[str, int]] = {}
    for path in sorted(SOURCE_OF_TRUTH_DIR.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        state[str(path.relative_to(SOURCE_OF_TRUTH_DIR))] = {
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    return state


def diff_source_of_truth_state(
    before: dict[str, dict[str, int]],
    after: dict[str, dict[str, int]],
) -> list[str]:
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed.append(key)
    return changed


def load_execution_mode_guardrail() -> dict[str, Any]:
    cfg = read_json(EXECUTION_MODE_PATH)
    guardrail = {
        "path": str(EXECUTION_MODE_PATH.resolve()),
        "mode": cfg.get("mode"),
        "trading_enabled": cfg.get("trading_enabled"),
        "dry_run_enabled": cfg.get("dry_run_enabled"),
        "kill_switch": cfg.get("kill_switch"),
        "ok": True,
        "violations": [],
    }

    violations = guardrail["violations"]
    if str(cfg.get("mode", "")).strip() != "read_only":
        violations.append("execution_mode.mode must be 'read_only'")
    if bool(cfg.get("trading_enabled")):
        violations.append("execution_mode.trading_enabled must be false")
    if not bool(cfg.get("kill_switch")):
        violations.append("execution_mode.kill_switch must be true")
    if "dry_run_enabled" in cfg and not bool(cfg.get("dry_run_enabled")):
        violations.append("execution_mode.dry_run_enabled must be true when present")

    guardrail["ok"] = not violations
    return guardrail


def build_controlled_runtime_preflight() -> dict[str, Any]:
    execution_mode_guardrail = load_execution_mode_guardrail()
    live_order_policy = read_json(LIVE_ORDER_POLICY_PATH)
    script_registry = read_json(SCRIPT_REGISTRY_PATH)

    registry_entries = script_registry.get("scripts", [])
    registry_by_path = {
        str(entry.get("script_path", "")).strip(): entry
        for entry in registry_entries
        if isinstance(entry, dict)
    }

    approved_chain = [
        {"step_name": step_name, "script_path": rel_path}
        for step_name, rel_path in APPROVED_LIGHTWEIGHT_STEP_CHAIN
    ]
    actual_chain = []
    chain_violations: list[str] = []

    approved_pairs = list(APPROVED_LIGHTWEIGHT_STEP_CHAIN)
    actual_pairs = [
        (step_name, script_path.relative_to(ROOT).as_posix())
        for step_name, script_path in STEP_CHAIN
    ]
    if actual_pairs != approved_pairs:
        chain_violations.append(
            "controlled runtime step chain differs from the approved lightweight step list"
        )

    for step_name, script_path in STEP_CHAIN:
        relative_path = script_path.relative_to(ROOT).as_posix()
        registry_entry = registry_by_path.get(relative_path)
        actual_chain.append(
            {
                "step_name": step_name,
                "script_path": relative_path,
                "exists": script_path.exists(),
                "registry_found": registry_entry is not None,
                "registry_status": None if registry_entry is None else registry_entry.get("status"),
                "registry_layer": None if registry_entry is None else registry_entry.get("layer"),
                "registry_output_type": None
                if registry_entry is None
                else registry_entry.get("output_type"),
                "writes_source_of_truth": None
                if registry_entry is None
                else registry_entry.get("writes_source_of_truth"),
            }
        )

        if not script_path.exists():
            chain_violations.append(f"controlled runtime step is missing: {relative_path}")
            continue
        if registry_entry is None:
            chain_violations.append(
                f"controlled runtime step is not registered in canonical/script_registry.json: {relative_path}"
            )
            continue
        if registry_entry.get("status") != "active":
            chain_violations.append(
                f"controlled runtime step is not active in canonical/script_registry.json: {relative_path}"
            )
        if registry_entry.get("writes_source_of_truth"):
            chain_violations.append(
                f"controlled runtime step must not write source_of_truth: {relative_path}"
            )

    real_order_enabled = bool(live_order_policy.get("allow_live_orders"))
    violations = []
    violations.extend(execution_mode_guardrail.get("violations", []))
    violations.extend(chain_violations)
    if real_order_enabled:
        violations.append("live_order_policy.allow_live_orders must be false for controlled runtime")

    preflight = {
        "checked_at_utc": utc_now_iso(),
        "ok": not violations,
        "violations": violations,
        "execution_mode_guardrail": execution_mode_guardrail,
        "step_chain_verification": {
            "approved_chain": approved_chain,
            "actual_chain": actual_chain,
            "ok": not chain_violations,
            "violations": chain_violations,
        },
        "real_order_path_check": {
            "path": str(LIVE_ORDER_POLICY_PATH.resolve()),
            "allow_live_orders": real_order_enabled,
            "manual_approval_required": live_order_policy.get("manual_approval_required"),
            "require_kill_switch_off": live_order_policy.get("require_kill_switch_off"),
            "ok": not real_order_enabled,
        },
    }
    return preflight


def emit_step_output(step_name: str, stdout: str, stderr: str) -> None:
    if stdout:
        print(f"[RUNTIME][{step_name}][stdout] BEGIN", flush=True)
        sys.stdout.write(stdout if stdout.endswith("\n") else stdout + "\n")
        print(f"[RUNTIME][{step_name}][stdout] END", flush=True)
    if stderr:
        print(f"[RUNTIME][{step_name}][stderr] BEGIN", file=sys.stderr, flush=True)
        sys.stderr.write(stderr if stderr.endswith("\n") else stderr + "\n")
        print(f"[RUNTIME][{step_name}][stderr] END", file=sys.stderr, flush=True)


def run_step(step_name: str, script_path: Path, cycle_dir: Path) -> dict[str, Any]:
    if not script_path.exists():
        raise FileNotFoundError(f"Missing runtime step script: {script_path}")

    stdout_path = cycle_dir / f"{step_name}.stdout.log"
    stderr_path = cycle_dir / f"{step_name}.stderr.log"
    command = [sys.executable, str(script_path)]

    started_at_utc = utc_now_iso()
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed_sec = round(time.monotonic() - started, 3)

    stdout_text = result.stdout or ""
    stderr_text = result.stderr or ""
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")
    emit_step_output(step_name, stdout_text, stderr_text)

    step_result = {
        "step_name": step_name,
        "script_path": str(script_path),
        "command": command,
        "started_at_utc": started_at_utc,
        "finished_at_utc": utc_now_iso(),
        "elapsed_sec": elapsed_sec,
        "returncode": result.returncode,
        "status": "success" if result.returncode == 0 else "failed",
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }

    if result.returncode != 0:
        raise RuntimeError(
            f"Runtime step failed: {step_name} "
            f"(returncode={result.returncode}, stdout_log={stdout_path}, stderr_log={stderr_path})"
        )

    return step_result


def pid_is_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def archive_runtime_file(path: Path, prefix: str) -> Path | None:
    if not path.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archived_path = ARCHIVE_DIR / f"{prefix}_{utc_stamp()}.json"
    path.replace(archived_path)
    return archived_path


def create_lock_file(lock_payload: dict[str, Any]) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(str(LOCK_PATH), flags)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(lock_payload, indent=2, ensure_ascii=False) + "\n")
    except Exception:
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def acquire_runtime_lock(lock_payload: dict[str, Any]) -> dict[str, Any]:
    try:
        create_lock_file(lock_payload)
        return lock_payload
    except FileExistsError:
        existing_lock = read_json_if_exists(LOCK_PATH) or {}
        existing_pid_raw = existing_lock.get("pid")
        existing_pid = existing_pid_raw if isinstance(existing_pid_raw, int) else None
        if pid_is_running(existing_pid):
            raise RuntimeError(
                "Another controlled runtime is already active "
                f"(pid={existing_pid}, label={existing_lock.get('runtime_label')}, lock={LOCK_PATH})."
            )

        archived = archive_runtime_file(LOCK_PATH, "stale_runtime_lock")
        append_jsonl(
            EVENTS_PATH,
            {
                "timestamp_utc": utc_now_iso(),
                "event_type": "stale_runtime_lock_archived",
                "archived_path": None if archived is None else str(archived),
                "stale_lock": existing_lock,
            },
        )
        create_lock_file(lock_payload)
        return lock_payload


def release_runtime_lock(runtime_state: dict[str, Any]) -> None:
    existing_lock = read_json_if_exists(LOCK_PATH)
    if not isinstance(existing_lock, dict):
        return
    if (
        existing_lock.get("run_id") == runtime_state.get("run_id")
        and existing_lock.get("pid") == os.getpid()
    ):
        LOCK_PATH.unlink(missing_ok=True)


def write_stop_marker(*, reason: str, source: str, runtime_label: str | None) -> dict[str, Any]:
    payload = {
        "requested_at_utc": utc_now_iso(),
        "reason": reason,
        "source": source,
        "requested_by_pid": os.getpid(),
        "runtime_label": runtime_label,
        "lock_path": str(LOCK_PATH),
    }
    write_json(STOP_MARKER_PATH, payload)
    append_jsonl(
        EVENTS_PATH,
        {
            "timestamp_utc": payload["requested_at_utc"],
            "event_type": "runtime_stop_requested",
            "reason": reason,
            "source": source,
            "runtime_label": runtime_label,
        },
    )
    return payload


def clear_stop_marker() -> None:
    STOP_MARKER_PATH.unlink(missing_ok=True)


def load_stop_marker() -> dict[str, Any] | None:
    return read_json_if_exists(STOP_MARKER_PATH)


def build_runtime_health_payload(runtime_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_type": "controlled_runtime_health",
        "runtime_label": runtime_state["runtime_label"],
        "run_id": runtime_state["run_id"],
        "mode": "controlled_runtime_loop",
        "control_mode": runtime_state["control_mode"],
        "loop_requested": runtime_state["loop_requested"],
        "loop_seconds": runtime_state["loop_seconds"],
        "max_runtime_seconds": runtime_state["max_runtime_seconds"],
        "run_active": runtime_state["run_active"],
        "status": runtime_state["status"],
        "error": runtime_state["error"],
        "stop_requested": runtime_state["stop_requested"],
        "stop_reason": runtime_state["stop_reason"],
        "started_at_utc": runtime_state["started_at_utc"],
        "updated_at_utc": utc_now_iso(),
        "finished_at_utc": runtime_state["finished_at_utc"],
        "root": str(ROOT),
        "python": sys.executable,
        "run_dir": runtime_state["run_dir"],
        "current_cycle_dir": runtime_state["current_cycle_dir"],
        "cycle_index": runtime_state["cycle_index"],
        "cycles_completed": runtime_state["cycles_completed"],
        "current_step": runtime_state["current_step"],
        "last_started_step": runtime_state["last_started_step"],
        "last_completed_step": runtime_state["last_completed_step"],
        "last_finished_step": runtime_state["last_finished_step"],
        "last_success_utc": runtime_state["last_success_utc"],
        "outputs_possibly_stale_or_partial": runtime_state["outputs_possibly_stale_or_partial"],
        "execution_mode_guardrail": runtime_state["execution_mode_guardrail"],
        "preflight_check": runtime_state["preflight_check"],
        "source_of_truth_write_check": runtime_state["source_of_truth_write_check"],
        "safe_contract": runtime_state["safe_contract"],
        "step_order": [name for name, _ in STEP_CHAIN],
        "latest_cycle_steps": runtime_state["latest_cycle_steps"],
        "active_lock": safe_file_info(LOCK_PATH),
        "active_stop_marker": safe_file_info(STOP_MARKER_PATH),
        "stop_marker_payload": load_stop_marker(),
        "key_runtime_outputs": {name: safe_file_info(path) for name, path in KEY_RUNTIME_OUTPUTS.items()},
        "notes": [
            "Manual/local-PC runtime controller only.",
            "Default mode is one pass. Continuous looping requires explicit --loop.",
            "Preflight must pass before the controlled runtime loop can start.",
            "Any source_of_truth write or unsafe execution mode is treated as a hard failure.",
            "Only read-only snapshot plus dry-run execution steps are allowed here.",
        ],
    }


def build_manifest(runtime_state: dict[str, Any]) -> dict[str, Any]:
    output_paths = [
        str(LATEST_HEALTH_PATH.resolve()),
        str(LATEST_MANIFEST_PATH.resolve()),
        str(EVENTS_PATH.resolve()),
        str(LOCK_PATH.resolve()),
        str(STOP_MARKER_PATH.resolve()),
    ]
    if runtime_state["current_cycle_dir"]:
        cycle_dir = Path(runtime_state["current_cycle_dir"])
        output_paths.extend(
            [
                str((cycle_dir / "runtime_health.json").resolve()),
                str((cycle_dir / "runtime_health_manifest.json").resolve()),
            ]
        )

    return {
        "artifact_name": "controlled_runtime_health",
        "generated_at_utc": utc_now_iso(),
        "started_at_utc": runtime_state["started_at_utc"],
        "script_path": str(Path(__file__).resolve()),
        "runtime_label": runtime_state["runtime_label"],
        "run_id": runtime_state["run_id"],
        "control_mode": runtime_state["control_mode"],
        "run_dir": runtime_state["run_dir"],
        "cycle_index": runtime_state["cycle_index"],
        "output_paths": output_paths,
        "status": runtime_state["status"],
    }


def publish_runtime_health(runtime_state: dict[str, Any], cycle_dir: Path | None = None) -> None:
    health = build_runtime_health_payload(runtime_state)
    manifest = build_manifest(runtime_state)
    write_json(LATEST_HEALTH_PATH, health)
    write_json(LATEST_MANIFEST_PATH, manifest)

    if cycle_dir is not None:
        write_json(cycle_dir / "runtime_health.json", health)
        write_json(cycle_dir / "runtime_health_manifest.json", manifest)


def set_stop_requested(runtime_state: dict[str, Any], *, reason: str, source: str) -> None:
    runtime_state["stop_requested"] = True
    runtime_state["stop_reason"] = reason
    write_stop_marker(
        reason=reason,
        source=source,
        runtime_label=runtime_state["runtime_label"],
    )
    publish_runtime_health(runtime_state)


def refresh_stop_request_from_marker(runtime_state: dict[str, Any]) -> dict[str, Any] | None:
    marker = load_stop_marker()
    if not isinstance(marker, dict):
        return None
    runtime_state["stop_requested"] = True
    runtime_state["stop_reason"] = str(marker.get("reason", "graceful_stop_requested")).strip() or "graceful_stop_requested"
    return marker


def install_signal_handlers(runtime_state: dict[str, Any]) -> None:
    def handle_signal(signum: int, _frame: Any) -> None:
        try:
            signal_name = signal.Signals(signum).name
        except Exception:
            signal_name = f"signal_{signum}"

        reason = f"graceful_stop_via_{signal_name.lower()}"
        runtime_state["status"] = "stopping"
        set_stop_requested(runtime_state, reason=reason, source="local_signal")
        print(
            f"[RUNTIME] stop requested via {signal_name}; finishing the current step when possible.",
            flush=True,
        )

    signal.signal(signal.SIGINT, handle_signal)
    sigterm = getattr(signal, "SIGTERM", None)
    if sigterm is not None:
        signal.signal(sigterm, handle_signal)


def sleep_with_stop_checks(runtime_state: dict[str, Any], total_seconds: int) -> None:
    deadline = time.monotonic() + total_seconds
    while True:
        refresh_stop_request_from_marker(runtime_state)
        if runtime_state["stop_requested"]:
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return

        time.sleep(min(1.0, remaining))


def run_cycle(runtime_state: dict[str, Any]) -> dict[str, Any]:
    cycle_index = runtime_state["cycle_index"]
    cycle_dir = Path(runtime_state["run_dir"]) / f"cycle_{cycle_index:04d}_{utc_stamp()}"
    cycle_dir.mkdir(parents=True, exist_ok=True)

    started_at_utc = utc_now_iso()
    before_state = snapshot_source_of_truth_state()
    steps: list[dict[str, Any]] = []
    cycle_status = "success"
    cycle_error: str | None = None

    runtime_state["current_cycle_dir"] = str(cycle_dir)
    runtime_state["current_step"] = None
    runtime_state["last_started_step"] = None
    runtime_state["last_finished_step"] = None
    runtime_state["outputs_possibly_stale_or_partial"] = False
    runtime_state["latest_cycle_steps"] = steps
    runtime_state["source_of_truth_write_check"] = {
        "before_file_count": len(before_state),
        "after_file_count": None,
        "changed_files": [],
        "ok": True,
    }
    runtime_state["status"] = "running"
    publish_runtime_health(runtime_state)

    append_jsonl(
        EVENTS_PATH,
        {
            "timestamp_utc": started_at_utc,
            "event_type": "runtime_cycle_started",
            "runtime_label": runtime_state["runtime_label"],
            "cycle_index": cycle_index,
            "cycle_dir": str(cycle_dir),
        },
    )

    try:
        guardrail = load_execution_mode_guardrail()
        runtime_state["execution_mode_guardrail"] = guardrail
        publish_runtime_health(runtime_state)
        if not bool(guardrail.get("ok")):
            raise RuntimeError("Unsafe execution mode: " + " | ".join(guardrail.get("violations", [])))

        for step_name, script_path in STEP_CHAIN:
            runtime_state["current_step"] = step_name
            runtime_state["last_started_step"] = step_name
            publish_runtime_health(runtime_state)

            step_result = run_step(step_name=step_name, script_path=script_path, cycle_dir=cycle_dir)
            steps.append(step_result)
            runtime_state["latest_cycle_steps"] = steps
            runtime_state["current_step"] = None
            runtime_state["last_completed_step"] = step_name
            runtime_state["last_finished_step"] = step_name
            runtime_state["last_success_utc"] = step_result["finished_at_utc"]
            publish_runtime_health(runtime_state)

            if refresh_stop_request_from_marker(runtime_state):
                cycle_status = "stopped"
                break
    except Exception as exc:
        cycle_status = "failed"
        cycle_error = str(exc)
        runtime_state["current_step"] = None

    runtime_state["outputs_possibly_stale_or_partial"] = bool(
        cycle_status == "failed"
        and runtime_state["last_started_step"]
        and runtime_state["last_started_step"] != runtime_state["last_finished_step"]
    )

    after_state = snapshot_source_of_truth_state()
    source_of_truth_changes = diff_source_of_truth_state(before_state, after_state)
    runtime_state["source_of_truth_write_check"] = {
        "before_file_count": len(before_state),
        "after_file_count": len(after_state),
        "changed_files": source_of_truth_changes,
        "ok": not source_of_truth_changes,
    }
    if source_of_truth_changes:
        cycle_status = "failed"
        message = "Runtime modified source_of_truth unexpectedly: " + ", ".join(source_of_truth_changes)
        cycle_error = f"{cycle_error}; {message}" if cycle_error else message

    if cycle_status == "success":
        runtime_state["cycles_completed"] = cycle_index
    elif cycle_status == "stopped" and len(steps) == len(STEP_CHAIN):
        runtime_state["cycles_completed"] = cycle_index

    runtime_state["status"] = "running" if cycle_status == "success" and runtime_state["run_active"] else cycle_status
    if cycle_status == "failed":
        runtime_state["error"] = cycle_error
        if not runtime_state["stop_reason"]:
            runtime_state["stop_reason"] = "runtime_failed"
    elif cycle_status == "stopped":
        runtime_state["status"] = "stopping"
        runtime_state["error"] = None
        if not runtime_state["stop_reason"]:
            runtime_state["stop_reason"] = "graceful_stop_requested"
    else:
        runtime_state["error"] = None

    publish_runtime_health(runtime_state, cycle_dir=cycle_dir)

    append_jsonl(
        EVENTS_PATH,
        {
            "timestamp_utc": utc_now_iso(),
            "event_type": "runtime_cycle_finished",
            "runtime_label": runtime_state["runtime_label"],
            "cycle_index": cycle_index,
            "cycle_dir": str(cycle_dir),
            "status": cycle_status,
            "error": cycle_error,
            "last_started_step": runtime_state["last_started_step"],
            "last_completed_step": runtime_state["last_completed_step"],
            "last_finished_step": runtime_state["last_finished_step"],
            "last_success_utc": runtime_state["last_success_utc"],
            "outputs_possibly_stale_or_partial": runtime_state["outputs_possibly_stale_or_partial"],
            "stop_reason": runtime_state["stop_reason"],
        },
    )

    return {
        "status": cycle_status,
        "error": cycle_error,
        "cycle_dir": str(cycle_dir),
    }


def request_stop(args: argparse.Namespace) -> int:
    existing_lock = read_json_if_exists(LOCK_PATH)
    if not isinstance(existing_lock, dict):
        print(f"[RUNTIME] no active runtime lock found at {LOCK_PATH}", flush=True)
        return 0

    payload = write_stop_marker(
        reason=args.stop_reason,
        source="manual_stop_command",
        runtime_label=str(existing_lock.get("runtime_label", "")) or None,
    )
    print(f"[RUNTIME] graceful stop requested: {STOP_MARKER_PATH}", flush=True)
    print(json.dumps(payload, indent=2, ensure_ascii=False), flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local-PC controlled runtime for the lightweight execution refresh chain."
    )
    parser.add_argument(
        "--label",
        default="controlled_runtime",
        help="Human-readable label written into runtime health artifacts.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously until a graceful stop is requested. Default is one pass.",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Deprecated alias for one-pass mode. One pass is already the default.",
    )
    parser.add_argument(
        "--loop-seconds",
        type=int,
        default=300,
        help="Sleep interval between cycles when --loop is explicitly enabled.",
    )
    parser.add_argument(
        "--max-runtime-seconds",
        type=int,
        default=0,
        help="Optional wall-clock limit for the whole loop. Zero means no explicit limit.",
    )
    parser.add_argument(
        "--request-stop",
        action="store_true",
        help="Write a graceful stop marker for the active local runtime and exit.",
    )
    parser.add_argument(
        "--stop-reason",
        default="manual_local_pc_stop",
        help="Reason written into the stop marker when --request-stop is used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.loop_seconds < 0:
        raise SystemExit("--loop-seconds must be >= 0")
    if args.max_runtime_seconds < 0:
        raise SystemExit("--max-runtime-seconds must be >= 0")

    RUNTIME_HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    LOOPS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    if args.request_stop:
        return request_stop(args)

    control_mode = "loop" if args.loop else "one_pass"
    run_started_at_utc = utc_now_iso()
    run_started_monotonic = time.monotonic()
    run_id = utc_stamp()
    run_dir = LOOPS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    runtime_state: dict[str, Any] = {
        "runtime_label": args.label,
        "run_id": run_id,
        "control_mode": control_mode,
        "loop_requested": bool(args.loop),
        "loop_seconds": args.loop_seconds,
        "max_runtime_seconds": args.max_runtime_seconds,
        "started_at_utc": run_started_at_utc,
        "finished_at_utc": None,
        "run_active": True,
        "status": "starting",
        "error": None,
        "stop_requested": False,
        "stop_reason": None,
        "run_dir": str(run_dir),
        "current_cycle_dir": None,
        "cycle_index": 0,
        "cycles_completed": 0,
        "current_step": None,
        "last_started_step": None,
        "last_completed_step": None,
        "last_finished_step": None,
        "last_success_utc": None,
        "outputs_possibly_stale_or_partial": False,
        "latest_cycle_steps": [],
        "execution_mode_guardrail": {
            "path": str(EXECUTION_MODE_PATH.resolve()),
            "mode": None,
            "trading_enabled": None,
            "dry_run_enabled": None,
            "kill_switch": None,
            "ok": None,
            "violations": [],
        },
        "preflight_check": {
            "checked_at_utc": None,
            "ok": None,
            "violations": [],
            "execution_mode_guardrail": None,
            "step_chain_verification": None,
            "real_order_path_check": None,
        },
        "source_of_truth_write_check": {
            "before_file_count": None,
            "after_file_count": None,
            "changed_files": [],
            "ok": True,
        },
        "safe_contract": {
            "read_only_only": True,
            "trading_enabled": False,
            "kill_switch_required": True,
            "real_orders_submitted": False,
            "source_of_truth_writes_allowed": False,
        },
    }

    try:
        preflight = build_controlled_runtime_preflight()
    except Exception as exc:
        runtime_state["run_active"] = False
        runtime_state["status"] = "blocked"
        runtime_state["error"] = f"Controlled runtime preflight failed: {exc}"
        runtime_state["stop_reason"] = "preflight_failed"
        runtime_state["finished_at_utc"] = utc_now_iso()
        runtime_state["preflight_check"] = {
            "checked_at_utc": utc_now_iso(),
            "ok": False,
            "violations": [str(exc)],
            "execution_mode_guardrail": runtime_state["execution_mode_guardrail"],
            "step_chain_verification": None,
            "real_order_path_check": None,
        }
        publish_runtime_health(runtime_state)
        append_jsonl(
            EVENTS_PATH,
            {
                "timestamp_utc": runtime_state["finished_at_utc"],
                "event_type": "runtime_preflight_failed",
                "runtime_label": args.label,
                "run_id": run_id,
                "run_dir": str(run_dir),
                "violations": runtime_state["preflight_check"]["violations"],
            },
        )
        print(f"[RUNTIME] {runtime_state['error']}", flush=True)
        return 1

    runtime_state["execution_mode_guardrail"] = preflight["execution_mode_guardrail"]
    runtime_state["preflight_check"] = preflight
    publish_runtime_health(runtime_state)
    if not preflight["ok"]:
        runtime_state["run_active"] = False
        runtime_state["status"] = "blocked"
        runtime_state["error"] = "Controlled runtime preflight failed: " + " | ".join(
            preflight["violations"]
        )
        runtime_state["stop_reason"] = "preflight_failed"
        runtime_state["finished_at_utc"] = utc_now_iso()
        publish_runtime_health(runtime_state)
        append_jsonl(
            EVENTS_PATH,
            {
                "timestamp_utc": runtime_state["finished_at_utc"],
                "event_type": "runtime_preflight_failed",
                "runtime_label": args.label,
                "run_id": run_id,
                "run_dir": str(run_dir),
                "violations": preflight["violations"],
            },
        )
        print(f"[RUNTIME] {runtime_state['error']}", flush=True)
        return 1

    lock_payload = {
        "lock_type": "controlled_runtime_loop",
        "run_id": run_id,
        "runtime_label": args.label,
        "pid": os.getpid(),
        "started_at_utc": run_started_at_utc,
        "control_mode": control_mode,
        "run_dir": str(run_dir),
        "script_path": str(Path(__file__).resolve()),
    }
    try:
        acquire_runtime_lock(lock_payload)
    except Exception as exc:
        runtime_state["run_active"] = False
        runtime_state["status"] = "blocked"
        runtime_state["error"] = str(exc)
        runtime_state["stop_reason"] = "active_lock_present"
        runtime_state["finished_at_utc"] = utc_now_iso()
        publish_runtime_health(runtime_state)
        print(f"[RUNTIME] {exc}", flush=True)
        return 1

    clear_stop_marker()
    install_signal_handlers(runtime_state)

    append_jsonl(
        EVENTS_PATH,
        {
            "timestamp_utc": run_started_at_utc,
            "event_type": "runtime_loop_started",
            "runtime_label": args.label,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "control_mode": control_mode,
            "loop_seconds": args.loop_seconds,
            "max_runtime_seconds": args.max_runtime_seconds,
            "pid": os.getpid(),
        },
    )

    publish_runtime_health(runtime_state)

    exit_code = 0
    try:
        while True:
            if refresh_stop_request_from_marker(runtime_state):
                runtime_state["status"] = "stopping"
                break

            if args.max_runtime_seconds > 0 and runtime_state["cycle_index"] > 0:
                elapsed = time.monotonic() - run_started_monotonic
                if elapsed >= args.max_runtime_seconds:
                    runtime_state["stop_reason"] = "max_runtime_seconds_reached"
                    runtime_state["status"] = "stopping"
                    break

            runtime_state["cycle_index"] += 1
            cycle_result = run_cycle(runtime_state)

            if cycle_result["status"] == "failed":
                runtime_state["status"] = "failed"
                runtime_state["error"] = cycle_result["error"]
                if not runtime_state["stop_reason"]:
                    runtime_state["stop_reason"] = "runtime_failed"
                exit_code = 1
                break

            if cycle_result["status"] == "stopped":
                runtime_state["status"] = "stopping"
                if not runtime_state["stop_reason"]:
                    runtime_state["stop_reason"] = "graceful_stop_requested"
                break

            if not args.loop:
                runtime_state["stop_reason"] = "one_pass_completed"
                break

            if args.max_runtime_seconds > 0:
                elapsed = time.monotonic() - run_started_monotonic
                remaining = args.max_runtime_seconds - elapsed
                if remaining <= 0:
                    runtime_state["stop_reason"] = "max_runtime_seconds_reached"
                    break
                sleep_seconds = min(args.loop_seconds, max(0, int(remaining)))
            else:
                sleep_seconds = args.loop_seconds

            if sleep_seconds <= 0:
                runtime_state["stop_reason"] = "loop_interval_not_positive"
                break

            runtime_state["status"] = "sleeping"
            publish_runtime_health(runtime_state)
            print(f"[RUNTIME] sleeping seconds={sleep_seconds}", flush=True)
            sleep_with_stop_checks(runtime_state, sleep_seconds)
            if runtime_state["stop_requested"]:
                runtime_state["status"] = "stopping"
                if not runtime_state["stop_reason"]:
                    runtime_state["stop_reason"] = "graceful_stop_requested"
                break
    finally:
        runtime_state["run_active"] = False
        runtime_state["finished_at_utc"] = utc_now_iso()
        if runtime_state["status"] not in {"failed", "blocked"}:
            if runtime_state["stop_requested"] or runtime_state["stop_reason"] not in {None, "one_pass_completed"}:
                runtime_state["status"] = "stopped"
            else:
                runtime_state["status"] = "success"
        release_runtime_lock(runtime_state)
        clear_stop_marker()
        publish_runtime_health(runtime_state)
        append_jsonl(
            EVENTS_PATH,
            {
                "timestamp_utc": runtime_state["finished_at_utc"],
                "event_type": "runtime_loop_finished",
                "runtime_label": args.label,
                "run_id": run_id,
                "run_dir": str(run_dir),
                "cycles_completed": runtime_state["cycles_completed"],
                "last_status": runtime_state["status"],
                "last_completed_step": runtime_state["last_completed_step"],
                "last_success_utc": runtime_state["last_success_utc"],
                "stop_reason": runtime_state["stop_reason"],
                "exit_code": exit_code,
            },
        )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
