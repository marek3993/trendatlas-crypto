from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRADING_OPERATION_MODE_PATH = ROOT / "execution" / "config" / "trading_operation_mode.json"

DEFAULT_TRADING_OPERATION_MODE_PAYLOAD: dict[str, Any] = {
    "mode": "manual",
    "updated_at_utc": "",
    "updated_by": "system_default",
    "fail_closed": True,
}


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode not in {"manual", "automatic"}:
        return "manual"
    return mode


def build_default_payload(*, reason: str = "") -> dict[str, Any]:
    payload = dict(DEFAULT_TRADING_OPERATION_MODE_PAYLOAD)
    if reason:
        payload["error"] = reason
        if not payload.get("updated_at_utc"):
            payload["updated_at_utc"] = utc_now_iso()
    return payload


def load_trading_operation_mode_payload(
    path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_path = Path(path) if path is not None else DEFAULT_TRADING_OPERATION_MODE_PATH
    if not resolved_path.is_absolute():
        resolved_path = ROOT / resolved_path

    if not resolved_path.exists():
        payload = build_default_payload(reason=f"Missing file: {resolved_path}")
        payload["path"] = str(resolved_path)
        return payload

    raw_text = ""
    try:
        raw_text = resolved_path.read_text(encoding="utf-8")
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError:
            legacy_fixed_text = raw_text.replace("`n", "").strip()
            raw = json.loads(legacy_fixed_text)
    except json.JSONDecodeError as exc:
        payload = build_default_payload(reason=f"Invalid JSON in {resolved_path}: {exc}")
        payload["path"] = str(resolved_path)
        return payload
    except OSError as exc:
        payload = build_default_payload(reason=f"Failed to read {resolved_path}: {exc}")
        payload["path"] = str(resolved_path)
        return payload

    if not isinstance(raw, dict):
        payload = build_default_payload(reason=f"Expected JSON object in {resolved_path}")
        payload["path"] = str(resolved_path)
        return payload

    payload = dict(DEFAULT_TRADING_OPERATION_MODE_PAYLOAD)
    payload.update(raw)
    payload["mode"] = normalize_mode(payload.get("mode"))
    payload["fail_closed"] = False
    payload["updated_at_utc"] = str(payload.get("updated_at_utc") or "").strip()
    payload["updated_by"] = str(payload.get("updated_by") or "system").strip() or "system"
    payload["path"] = str(resolved_path)
    return payload


def save_trading_operation_mode_payload(
    mode: str,
    *,
    path: str | Path | None = None,
    updated_by: str = "system",
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_path = Path(path) if path is not None else DEFAULT_TRADING_OPERATION_MODE_PATH
    if not resolved_path.is_absolute():
        resolved_path = ROOT / resolved_path

    payload = {
        "mode": normalize_mode(mode),
        "updated_at_utc": utc_now_iso(),
        "updated_by": str(updated_by or "system").strip() or "system",
        "fail_closed": False,
    }

    if extra_fields:
        payload.update(extra_fields)
        payload["mode"] = normalize_mode(payload.get("mode"))

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    payload["path"] = str(resolved_path)
    return payload



def write_trading_operation_mode_payload(
    mode: str,
    *,
    path: str | Path | None = None,
    updated_by: str = "system",
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return save_trading_operation_mode_payload(
        mode,
        path=path,
        updated_by=updated_by,
        extra_fields=extra_fields,
    )


if __name__ == "__main__":
    print(
        json.dumps(
            load_trading_operation_mode_payload(),
            indent=2,
            ensure_ascii=False,
        )
    )
