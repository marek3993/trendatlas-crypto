from __future__ import annotations

import json
import os
import platform
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.market_regime_v1.phase1_time_semantics import (
    ATTEMPT_STATUSES,
    ATTEMPT_STATUS_ARTIFACT_TYPE,
    CURRENTNESS_STATUSES,
    DISPLAY_TIMEZONE,
    SUCCESS_SNAPSHOT_ARTIFACT_TYPE,
    build_authority_payload,
    derive_currentness,
    normalize_utc_day,
    normalize_utc_timestamp,
    render_local_display_timestamp,
)


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_DIR = ROOT / "outputs" / "execution" / "authority"
LATEST_SUCCESSFUL_SNAPSHOT_PATH = AUTHORITY_DIR / "latest_successful_snapshot.json"
LATEST_ATTEMPT_STATUS_PATH = AUTHORITY_DIR / "latest_attempt_status.json"
STAGE_STATUSES = frozenset({"failed", "running", "success"})
PI_ALLOWED_PLATFORM_SYSTEM = "linux"
PI_ALLOWED_PLATFORM_MACHINES = frozenset({"arm64", "armv6l", "armv7l", "aarch64"})


class AuthorityPublishGuardError(PermissionError):
    """Raised when the runtime is not allowed to publish authority artifacts."""


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def authority_paths(root: Path | None = None) -> dict[str, Path]:
    resolved_root = root if root is not None else ROOT
    return {
        "authority_dir": Path(resolved_root) / "outputs" / "execution" / "authority",
        "latest_successful_snapshot": Path(resolved_root) / "outputs" / "execution" / "authority" / "latest_successful_snapshot.json",
        "latest_attempt_status": Path(resolved_root) / "outputs" / "execution" / "authority" / "latest_attempt_status.json",
    }


def _parse_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "on", "yes", "true"}


def build_authority_extra_fields(
    run_id: str,
    source_manifest_path: str,
    authority_role: str,
    automatic_producer_id: str,
    latest_successful_snapshot_path: str | Path | None = None,
    latest_attempt_status_path: str | Path | None = None,
    generated_at_utc: str | None = None,
    display_timezone: str = DISPLAY_TIMEZONE,
    attempt_stage: str | None = None,
    attempt_stage_status: str | None = None,
    stage_history: list[dict[str, Any]] | None = None,
    authority_wallet_sync_utc: str | None = None,
    authority_account_snapshot_as_of_utc: str | None = None,
    authority_runtime_snapshot_generated_at_utc: str | None = None,
    app_product_snapshot: dict[str, Any] | None = None,
    app_runtime_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        raise ValueError("run_id must be non-empty")

    normalized_manifest_path = str(source_manifest_path or "").strip()
    if not normalized_manifest_path:
        raise ValueError("source_manifest_path must be non-empty")

    resolved_generated_at_utc = normalize_utc_timestamp(
        generated_at_utc or utc_now_iso(),
        field_name="generated_at_utc",
    )
    payload: dict[str, Any] = {
        "generated_at_utc": resolved_generated_at_utc,
        "generated_at_local": render_local_display_timestamp(
            resolved_generated_at_utc,
            display_timezone=display_timezone,
        ),
        "run_id": normalized_run_id,
        "authority_role": authority_role,
        "automatic_producer_id": automatic_producer_id,
        "manual_recovery_only": True,
        "github_actions_role": "validation_only",
        "source_manifest_path": normalized_manifest_path,
    }

    if latest_successful_snapshot_path:
        payload["latest_successful_snapshot_path"] = str(latest_successful_snapshot_path)
    if latest_attempt_status_path:
        payload["latest_attempt_status_path"] = str(latest_attempt_status_path)

    if attempt_stage is not None:
        normalized_attempt_stage = str(attempt_stage).strip()
        if not normalized_attempt_stage:
            raise ValueError("attempt_stage must be non-empty when provided")
        payload["attempt_stage"] = normalized_attempt_stage

    if attempt_stage_status is not None:
        normalized_attempt_stage_status = str(attempt_stage_status).strip().lower()
        if normalized_attempt_stage_status not in STAGE_STATUSES:
            raise ValueError(
                "attempt_stage_status must be one of: " + ", ".join(sorted(STAGE_STATUSES))
            )
        payload["attempt_stage_status"] = normalized_attempt_stage_status

    if stage_history is not None:
        payload["stage_history"] = stage_history
    if authority_wallet_sync_utc is not None:
        payload["authority_wallet_sync_utc"] = normalize_utc_timestamp(
            authority_wallet_sync_utc,
            field_name="authority_wallet_sync_utc",
        )
    if authority_account_snapshot_as_of_utc is not None:
        payload["authority_account_snapshot_as_of_utc"] = normalize_utc_timestamp(
            authority_account_snapshot_as_of_utc,
            field_name="authority_account_snapshot_as_of_utc",
        )
    if authority_runtime_snapshot_generated_at_utc is not None:
        payload["authority_runtime_snapshot_generated_at_utc"] = normalize_utc_timestamp(
            authority_runtime_snapshot_generated_at_utc,
            field_name="authority_runtime_snapshot_generated_at_utc",
        )
    if app_product_snapshot is not None:
        payload["app_product_snapshot"] = app_product_snapshot
    if app_runtime_snapshot is not None:
        payload["app_runtime_snapshot"] = app_runtime_snapshot

    return payload


def build_stage_history_entry(
    stage_name: str,
    status: str,
    started_at_utc: str,
    finished_at_utc: str | None = None,
    script_path: str | Path | None = None,
    stdout_log: str | Path | None = None,
    stderr_log: str | Path | None = None,
    error: str | None = None,
    non_authoritative_support_only: bool = True,
) -> dict[str, Any]:
    normalized_stage_name = str(stage_name or "").strip()
    if not normalized_stage_name:
        raise ValueError("stage_name must be non-empty")

    normalized_status = str(status or "").strip().lower()
    if normalized_status not in STAGE_STATUSES:
        raise ValueError("stage status must be running, success, or failed")

    payload = {
        "stage_name": normalized_stage_name,
        "status": normalized_status,
        "started_at_utc": normalize_utc_timestamp(
            started_at_utc,
            field_name=f"{normalized_stage_name}.started_at_utc",
        ),
        "finished_at_utc": normalize_utc_timestamp(
            finished_at_utc,
            field_name=f"{normalized_stage_name}.finished_at_utc",
            allow_none=normalized_status == "running",
        ),
        "script_path": str(script_path).strip() if script_path else None,
        "stdout_log": str(stdout_log).strip() if stdout_log else None,
        "stderr_log": str(stderr_log).strip() if stderr_log else None,
        "error": str(error).strip() if error else None,
        "non_authoritative_support_only": bool(non_authoritative_support_only),
    }
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(path, rendered)


def atomic_write_text(path: Path, rendered: str) -> None:
    resolved_path = Path(path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    handle = None
    temp_path: str | None = None
    try:
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(resolved_path.parent),
            prefix=resolved_path.name + ".",
            suffix=".tmp",
            delete=False,
        )
        temp_path = handle.name
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp_path, resolved_path)
    finally:
        if handle is not None:
            handle.close()
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def read_text_if_exists(path: Path) -> str | None:
    resolved_path = Path(path)
    if not resolved_path.exists() or not resolved_path.is_file():
        return None
    return resolved_path.read_text(encoding="utf-8")


def restore_text_or_remove(path: Path, previous_contents: str | None) -> None:
    resolved_path = Path(path)
    if previous_contents is None:
        if resolved_path.exists():
            resolved_path.unlink()
        return
    atomic_write_text(resolved_path, previous_contents)


def authority_publish_context_from_env(
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source = os.environ if env is None else env
    platform_system = str(
        source.get("MRV1_RUNTIME_PLATFORM_SYSTEM") or platform.system()
    ).strip().lower()
    platform_machine = str(
        source.get("MRV1_RUNTIME_PLATFORM_MACHINE") or platform.machine()
    ).strip().lower()
    return {
        "authority_publish_enabled": _parse_bool(source.get("MRV1_ENABLE_AUTHORITY_PUBLISH")),
        "authority_mode": str(source.get("MRV1_AUTHORITY_MODE") or "").strip().lower(),
        "automatic_producer_id": str(
            source.get("MRV1_AUTOMATIC_PRODUCER_ID") or ""
        ).strip().lower(),
        "require_pi_runtime": _parse_bool(source.get("MRV1_REQUIRE_PI_RUNTIME")),
        "hostname": str(source.get("MRV1_PUBLISH_HOSTNAME") or socket.gethostname()).strip()
        or None,
        "platform_system": platform_system,
        "platform_machine": platform_machine,
    }


def resolve_authority_publish_mode(env: Mapping[str, str] | None = None) -> str:
    context = authority_publish_context_from_env(env)
    pi_runtime_ok = (
        context["platform_system"] == PI_ALLOWED_PLATFORM_SYSTEM
        and (
            context["platform_machine"] in PI_ALLOWED_PLATFORM_MACHINES
            or str(context["platform_machine"]).startswith("armv")
        )
    )

    if (
        context["authority_publish_enabled"]
        and context["authority_mode"] == "authoritative"
        and context["automatic_producer_id"] == "raspberry_pi"
        and ((not context["require_pi_runtime"]) or pi_runtime_ok)
    ):
        return "pi_only_authoritative_producer"
    return "non_authoritative_manual_or_validation"


def ensure_pi_only_publish_allowed(
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    context = authority_publish_context_from_env(env)
    if not context["authority_publish_enabled"]:
        raise AuthorityPublishGuardError("authority publish is disabled")
    if context["authority_mode"] != "authoritative":
        raise AuthorityPublishGuardError(
            "authority publish requires MRV1_AUTHORITY_MODE=authoritative"
        )
    if context["automatic_producer_id"] != "raspberry_pi":
        raise AuthorityPublishGuardError(
            "authority publish requires MRV1_AUTOMATIC_PRODUCER_ID=raspberry_pi"
        )
    if context["require_pi_runtime"]:
        if context["platform_system"] != PI_ALLOWED_PLATFORM_SYSTEM:
            raise AuthorityPublishGuardError(
                "authority publish requires Linux Pi runtime when MRV1_REQUIRE_PI_RUNTIME=1"
            )
        machine = str(context["platform_machine"] or "").strip().lower()
        if machine not in PI_ALLOWED_PLATFORM_MACHINES and not machine.startswith("armv"):
            raise AuthorityPublishGuardError(
                "authority publish requires ARM Pi runtime when MRV1_REQUIRE_PI_RUNTIME=1"
            )
    return context


def publish_authority_artifacts(
    latest_attempt_payload: dict[str, Any],
    latest_successful_snapshot_payload: dict[str, Any] | None = None,
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    paths = authority_paths(root)
    context = authority_publish_context_from_env(env)
    try:
        context = ensure_pi_only_publish_allowed(env)
        successful_snapshot_written = False
        if latest_successful_snapshot_payload is None:
            atomic_write_json(paths["latest_attempt_status"], latest_attempt_payload)
        else:
            previous_snapshot_contents = read_text_if_exists(
                paths["latest_successful_snapshot"]
            )
            atomic_write_json(
                paths["latest_successful_snapshot"],
                latest_successful_snapshot_payload,
            )
            try:
                atomic_write_json(paths["latest_attempt_status"], latest_attempt_payload)
            except Exception:
                restore_text_or_remove(
                    paths["latest_successful_snapshot"],
                    previous_snapshot_contents,
                )
                raise
            successful_snapshot_written = True

        return {
            "published": True,
            "attempt_written": True,
            "successful_snapshot_written": successful_snapshot_written,
            "reason": None,
            "context": context,
            "latest_attempt_status_path": str(paths["latest_attempt_status"]),
            "latest_successful_snapshot_path": str(paths["latest_successful_snapshot"]),
        }
    except AuthorityPublishGuardError as exc:
        return {
            "published": False,
            "attempt_written": False,
            "successful_snapshot_written": False,
            "reason": str(exc),
            "context": context,
            "latest_attempt_status_path": str(paths["latest_attempt_status"]),
            "latest_successful_snapshot_path": str(paths["latest_successful_snapshot"]),
        }
