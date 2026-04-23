from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo


DISPLAY_TIMEZONE = "Europe/Bratislava"
SUCCESS_SNAPSHOT_ARTIFACT_TYPE = "authority_latest_successful_snapshot"
ATTEMPT_STATUS_ARTIFACT_TYPE = "authority_latest_attempt_status"
ATTEMPT_STATUSES = frozenset({"in_progress", "failed", "success"})
CURRENTNESS_STATUSES = frozenset({"current", "stale", "refresh_in_progress", "refresh_failed"})

__all__ = (
    "ATTEMPT_STATUSES",
    "ATTEMPT_STATUS_ARTIFACT_TYPE",
    "CURRENTNESS_STATUSES",
    "DISPLAY_TIMEZONE",
    "SUCCESS_SNAPSHOT_ARTIFACT_TYPE",
    "build_authority_payload",
    "derive_currentness",
    "normalize_utc_day",
    "normalize_utc_timestamp",
    "render_local_display_timestamp",
)


def normalize_utc_timestamp(
    value: Any,
    field_name: str = "timestamp",
    allow_none: bool = False,
) -> str | None:
    text = str(value or "").strip()
    if not text:
        if allow_none:
            return None
        raise ValueError(f"{field_name} must be a non-empty UTC timestamp")

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601 timestamp") from exc

    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include UTC timezone information")

    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_utc_day(
    value: Any,
    field_name: str = "utc_day",
    allow_none: bool = False,
) -> str | None:
    text = str(value or "").strip()
    if not text:
        if allow_none:
            return None
        raise ValueError(f"{field_name} must be a non-empty UTC day string")

    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc

    return parsed.isoformat()


def render_local_display_timestamp(
    value_utc: Any,
    display_timezone: str = DISPLAY_TIMEZONE,
    allow_none: bool = False,
) -> str | None:
    normalized = normalize_utc_timestamp(
        value_utc,
        field_name="display_timestamp",
        allow_none=allow_none,
    )
    if normalized is None:
        return None

    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    return (
        parsed.astimezone(ZoneInfo(display_timezone))
        .replace(microsecond=0)
        .isoformat()
    )


def derive_currentness(
    *,
    target_closed_day_utc: str,
    latest_available_closed_utc_day: str,
    latest_authoritative_attempt_status: str,
    latest_authoritative_attempt_error: str | None = None,
    strategy_artifact_closed_day_utc: str | None = None,
) -> tuple[str, str]:
    attempt_status = str(latest_authoritative_attempt_status or "").strip().lower()
    if attempt_status not in ATTEMPT_STATUSES:
        raise ValueError(
            "latest_authoritative_attempt_status must be one of: "
            + ", ".join(sorted(ATTEMPT_STATUSES))
        )

    if attempt_status == "in_progress":
        return (
            "refresh_in_progress",
            f"Authoritative refresh is in progress for target_closed_day_utc={target_closed_day_utc}.",
        )

    if attempt_status == "failed":
        suffix = (
            f" error={str(latest_authoritative_attempt_error).strip()}."
            if str(latest_authoritative_attempt_error or "").strip()
            else "."
        )
        return (
            "refresh_failed",
            f"The latest authoritative refresh attempt failed for target_closed_day_utc={target_closed_day_utc}.{suffix}",
        )

    if strategy_artifact_closed_day_utc is None:
        return (
            "stale",
            "The latest authoritative strategy artifact day is missing, so currentness cannot be established from UTC market-day alignment.",
        )

    if strategy_artifact_closed_day_utc == latest_available_closed_utc_day:
        return (
            "current",
            "The authoritative strategy artifact is aligned with the latest closed UTC market day "
            f"{latest_available_closed_utc_day}.",
        )

    return (
        "stale",
        "The authoritative strategy artifact closed UTC day "
        f"{strategy_artifact_closed_day_utc} does not match the latest available closed UTC market day "
        f"{latest_available_closed_utc_day}.",
    )


def build_authority_payload(
    *,
    artifact_type: str,
    target_closed_day_utc: str,
    latest_available_closed_utc_day: str,
    refresh_started_at_utc: str,
    refresh_finished_at_utc: str | None,
    latest_authoritative_attempt_status: str,
    latest_authoritative_attempt_error: str | None = None,
    strategy_artifact_closed_day_utc: str | None = None,
    display_timezone: str = DISPLAY_TIMEZONE,
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_target_day = normalize_utc_day(
        target_closed_day_utc,
        field_name="target_closed_day_utc",
    )
    normalized_latest_available_day = normalize_utc_day(
        latest_available_closed_utc_day,
        field_name="latest_available_closed_utc_day",
    )
    normalized_refresh_started_at_utc = normalize_utc_timestamp(
        refresh_started_at_utc,
        field_name="refresh_started_at_utc",
    )

    attempt_status = str(latest_authoritative_attempt_status or "").strip().lower()
    if attempt_status not in ATTEMPT_STATUSES:
        raise ValueError(
            "latest_authoritative_attempt_status must be one of: "
            + ", ".join(sorted(ATTEMPT_STATUSES))
        )

    allow_open_attempt = attempt_status == "in_progress"
    normalized_refresh_finished_at_utc = normalize_utc_timestamp(
        refresh_finished_at_utc,
        field_name="refresh_finished_at_utc",
        allow_none=allow_open_attempt,
    )
    if attempt_status != "in_progress" and normalized_refresh_finished_at_utc is None:
        raise ValueError("refresh_finished_at_utc is required when attempt is not in_progress")

    normalized_strategy_day = normalize_utc_day(
        strategy_artifact_closed_day_utc,
        field_name="strategy_artifact_closed_day_utc",
        allow_none=artifact_type == ATTEMPT_STATUS_ARTIFACT_TYPE,
    )
    normalized_error = str(latest_authoritative_attempt_error or "").strip() or None

    if artifact_type == SUCCESS_SNAPSHOT_ARTIFACT_TYPE:
        if attempt_status != "success":
            raise ValueError(
                "latest_successful_snapshot payload must have latest_authoritative_attempt_status=success"
            )
        if normalized_strategy_day is None:
            raise ValueError(
                "latest_successful_snapshot payload requires strategy_artifact_closed_day_utc"
            )
    elif artifact_type != ATTEMPT_STATUS_ARTIFACT_TYPE:
        raise ValueError(f"Unsupported authority artifact_type={artifact_type}")

    refresh_started_at_local = render_local_display_timestamp(
        normalized_refresh_started_at_utc,
        display_timezone=display_timezone,
    )
    refresh_finished_at_local = render_local_display_timestamp(
        normalized_refresh_finished_at_utc,
        display_timezone=display_timezone,
        allow_none=True,
    )
    currentness_status, currentness_reason = derive_currentness(
        target_closed_day_utc=normalized_target_day,
        latest_available_closed_utc_day=normalized_latest_available_day,
        latest_authoritative_attempt_status=attempt_status,
        latest_authoritative_attempt_error=normalized_error,
        strategy_artifact_closed_day_utc=normalized_strategy_day,
    )
    if currentness_status not in CURRENTNESS_STATUSES:
        raise ValueError(f"Unsupported derived currentness_status={currentness_status}")

    payload: dict[str, Any] = {
        "artifact_type": artifact_type,
        "schema_version": 1,
        "target_closed_day_utc": normalized_target_day,
        "latest_available_closed_utc_day": normalized_latest_available_day,
        "refresh_started_at_utc": normalized_refresh_started_at_utc,
        "refresh_finished_at_utc": normalized_refresh_finished_at_utc,
        "refresh_started_at_local": refresh_started_at_local,
        "refresh_finished_at_local": refresh_finished_at_local,
        "display_timezone": display_timezone,
        "latest_authoritative_attempt_status": attempt_status,
        "latest_authoritative_attempt_error": normalized_error,
        "strategy_artifact_closed_day_utc": normalized_strategy_day,
        "currentness_status": currentness_status,
        "currentness_reason": currentness_reason,
    }
    if extra_fields:
        payload.update(dict(extra_fields))
    return payload
