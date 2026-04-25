from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.shared.runtime_bootstrap import resolve_project_root


DEFAULT_RETRIEVAL_ROOT = "outputs/research_os/dev_only/imlayer_retrieval"
DEFAULT_RETRIEVAL_SUFFIX = ".latest.retrieval_packet.json"


def _resolve_packet_path(
    family_id: str,
    retrieval_config: dict[str, Any],
    *,
    project_root: Path,
) -> Path | None:
    configured_path = str(retrieval_config.get("path", "")).strip()
    if configured_path:
        candidate = Path(configured_path)
        return candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()

    root_value = str(retrieval_config.get("root_dir", DEFAULT_RETRIEVAL_ROOT)).strip() or DEFAULT_RETRIEVAL_ROOT
    suffix = str(retrieval_config.get("filename_suffix", DEFAULT_RETRIEVAL_SUFFIX)).strip() or DEFAULT_RETRIEVAL_SUFFIX
    search_root = Path(root_value)
    search_root = search_root.resolve() if search_root.is_absolute() else (project_root / search_root).resolve()
    if not search_root.exists():
        return None

    pattern = str(retrieval_config.get("filename_pattern", f"**/{family_id}{suffix}")).strip() or f"**/{family_id}{suffix}"
    candidates = [path for path in search_root.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, str(path)))


def _record_family_ids(records: list[dict[str, Any]]) -> list[str]:
    family_ids = {
        str(dict(record.get("run_context", {})).get("family_id", "")).strip()
        for record in records
    }
    return sorted(family_id for family_id in family_ids if family_id)


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    family_summary = dict(payload.get("family_summary", {}))
    query = dict(payload.get("query", {}))
    records = [dict(item) for item in list(payload.get("records", []))]
    latest_record = records[0] if records else {}
    latest_decision = dict(latest_record.get("decision", {}))
    latest_decision_packet = dict(latest_record.get("decision_packet", {}))
    latest_run_context = dict(latest_record.get("run_context", {}))
    return {
        "resolved_batch_id": str(query.get("resolved_batch_id", "")),
        "memory_query_target": str(query.get("memory_query_target", "")),
        "latest_memory_id": str(family_summary.get("latest_memory_id", "")),
        "latest_cycle_id": str(family_summary.get("latest_cycle_id", "")),
        "latest_verdict": str(family_summary.get("latest_verdict", latest_decision.get("verdict", ""))),
        "latest_action": str(family_summary.get("latest_action", latest_decision.get("action", ""))),
        "selected_count": int(family_summary.get("selected_count", len(records)) or 0),
        "record_count": len(records),
        "semantic_sha256": str(latest_decision_packet.get("semantic_sha256", "")),
        "risk_flag_union": [str(item) for item in list(family_summary.get("risk_flag_union", []))],
        "run_context": {
            "proposal_id": str(latest_run_context.get("proposal_id", "")),
            "critic_run_id": str(latest_run_context.get("critic_run_id", "")),
            "governor_run_id": str(latest_run_context.get("governor_run_id", "")),
            "validation_job_id": str(latest_run_context.get("validation_job_id", "")),
        },
    }


def load_passive_retrieval_packet(
    family_id: str,
    retrieval_config: dict[str, Any] | None = None,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    retrieval_config = dict(retrieval_config or {})
    enabled = bool(retrieval_config.get("enabled", True))
    project_root = project_root.resolve() if project_root is not None else resolve_project_root(require_env=False)
    packet = {
        "artifact_type": "trendatlas_imlayer_retrieval_packet",
        "family_id": family_id,
        "passive_integration": True,
        "decision_behavior_changed": False,
        "status": "disabled" if not enabled else "missing",
        "path": "",
        "schema_version": "",
        "retrieval_generated_at_utc": "",
        "summary": {},
        "payload": {},
        "load_error": "",
    }
    if not enabled:
        return packet

    try:
        packet_path = _resolve_packet_path(family_id, retrieval_config, project_root=project_root)
    except Exception as exc:
        packet["status"] = "invalid"
        packet["load_error"] = str(exc)
        return packet
    if packet_path is None or not packet_path.exists():
        return packet

    packet["path"] = str(packet_path)
    try:
        payload = json.loads(packet_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        packet["status"] = "invalid"
        packet["load_error"] = str(exc)
        return packet
    if not isinstance(payload, dict):
        packet["status"] = "invalid"
        packet["load_error"] = "retrieval packet payload must be a JSON object"
        return packet

    query_family_id = str(dict(payload.get("query", {})).get("family_id", "")).strip()
    record_family_ids = _record_family_ids([dict(item) for item in list(payload.get("records", []))])
    if query_family_id and query_family_id != family_id:
        packet["status"] = "invalid"
        packet["load_error"] = f"retrieval packet query family_id mismatch: {query_family_id}"
        return packet
    if record_family_ids and family_id not in record_family_ids:
        packet["status"] = "invalid"
        packet["load_error"] = f"retrieval packet record family_id mismatch: {record_family_ids}"
        return packet

    packet["status"] = "loaded"
    packet["schema_version"] = str(payload.get("schema_version", ""))
    packet["retrieval_generated_at_utc"] = str(payload.get("retrieval_generated_at_utc", ""))
    packet["summary"] = _payload_summary(payload)
    packet["payload"] = payload
    return packet
