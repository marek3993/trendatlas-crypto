from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from services.shared.runtime_bootstrap import resolve_project_root


DEFAULT_RETRIEVAL_ROOT = "outputs/research_os/dev_only/imlayer_retrieval"
DEFAULT_RETRIEVAL_SUFFIX = ".latest.retrieval_packet.json"
PASSIVE_RETRIEVAL_COMPARISON_AXIS = "passive_retrieval_packet_presence"
CONTROLLED_RETRIEVAL_AUTHORITATIVE_VARIANT = "without_retrieval_packet"
CONTROLLED_RETRIEVAL_CANDIDATE_VARIANT = "with_retrieval_packet"
CONSTRAINED_INFLUENCE_SCHEMA_VERSION = "trendatlas.imlayer.constrained_influence.v2"
CONSTRAINED_INFLUENCE_CONFIG_KEY = "constrained_influence_v2"
CONSTRAINED_INFLUENCE_FIELD_CONTRACTS = {
    "planner": {
        "allowed_influence_fields": (
            "mechanism_hypothesis",
            "selection_rationale",
        ),
        "blocked_frozen_fields": (
            "exact_change",
            "stop_condition",
            "target_id",
            "target_type",
            "source_artifact_id",
        ),
    },
    "critic": {
        "allowed_influence_fields": (
            "policy_alignment_note",
            "recommended_reason",
        ),
        "blocked_frozen_fields": (
            "recommended_verdict",
            "recommended_next_action",
        ),
    },
}


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


def build_passive_retrieval_comparison(
    packet: dict[str, Any] | None,
    *,
    component: str,
) -> dict[str, Any]:
    packet = dict(packet or {})
    status = str(packet.get("status", "missing")).strip() or "missing"
    summary = dict(packet.get("summary", {}))
    retrieval_packet_present = status == "loaded"
    return {
        "component": component,
        "comparison_axis": PASSIVE_RETRIEVAL_COMPARISON_AXIS,
        "comparison_bucket": (
            "with_retrieval_packet"
            if retrieval_packet_present
            else "without_retrieval_packet"
        ),
        "retrieval_packet_present": retrieval_packet_present,
        "retrieval_packet_status": status,
        "passive_integration": True,
        "decision_behavior_changed": False,
        "fail_closed": True,
        "retrieval_packet_path": str(packet.get("path", "")),
        "latest_memory_id": str(summary.get("latest_memory_id", "")),
        "semantic_sha256": str(summary.get("semantic_sha256", "")),
        "load_error": str(packet.get("load_error", "")),
    }


def _clone_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, sort_keys=True))


def _payload_prompt_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    serialized_bytes = serialized.encode("utf-8")
    return {
        "json_char_count": len(serialized),
        "utf8_byte_count": len(serialized_bytes),
        "estimated_input_tokens_char_div4": int(math.ceil(len(serialized) / 4.0)),
        "payload_sha256": hashlib.sha256(serialized_bytes).hexdigest(),
    }


def build_retrieval_constrained_influence_contract(
    *,
    component: str,
    comparison_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    comparison_config = dict(comparison_config or {})
    v2_config = dict(comparison_config.get(CONSTRAINED_INFLUENCE_CONFIG_KEY) or {})
    field_contract = dict(CONSTRAINED_INFLUENCE_FIELD_CONTRACTS.get(component, {}))
    allowed_influence_fields = [
        str(field_name)
        for field_name in list(field_contract.get("allowed_influence_fields", ()))
    ]
    blocked_frozen_fields = [
        str(field_name)
        for field_name in list(field_contract.get("blocked_frozen_fields", ()))
    ]
    comparison_enabled = bool(comparison_config.get("enabled", False))
    requested = bool(v2_config.get("enabled", False))
    return {
        "schema_version": CONSTRAINED_INFLUENCE_SCHEMA_VERSION,
        "component": component,
        "enabled": comparison_enabled and requested,
        "requested": requested,
        "controlled_comparison_enabled": comparison_enabled,
        "mode": (
            "v2_constrained_reasoning_only"
            if comparison_enabled and requested
            else "v1_default_controlled_comparison"
        ),
        "allowed_influence_fields": allowed_influence_fields,
        "blocked_frozen_fields": blocked_frozen_fields,
        "decision_critical_fields_frozen": True,
        "future_decision_critical_field_unlock_requested": bool(
            v2_config.get("allow_decision_critical_field_influence", False)
        ),
        "future_decision_critical_field_unlock_honored": False,
        "official_decision_behavior_changed": False,
        "production_authority_transfer_enabled": False,
        "fail_closed_preserved": True,
    }


def apply_retrieval_constrained_influence_contract(
    *,
    component: str,
    authoritative_fields: dict[str, Any],
    candidate_fields: dict[str, Any],
    comparison_config: dict[str, Any] | None = None,
    freeze_blocked_fields: bool,
) -> dict[str, Any]:
    contract = build_retrieval_constrained_influence_contract(
        component=component,
        comparison_config=comparison_config,
    )
    allowed_influence_fields = list(contract.get("allowed_influence_fields", []))
    blocked_frozen_fields = list(contract.get("blocked_frozen_fields", []))
    contract_fields = allowed_influence_fields + blocked_frozen_fields
    normalized_authoritative_fields = {
        field_name: str(authoritative_fields.get(field_name, ""))
        for field_name in contract_fields
    }
    raw_candidate_fields = {
        field_name: str(candidate_fields.get(field_name, ""))
        for field_name in contract_fields
    }
    enforced_candidate_fields = dict(raw_candidate_fields)
    if freeze_blocked_fields:
        for field_name in blocked_frozen_fields:
            enforced_candidate_fields[field_name] = normalized_authoritative_fields.get(field_name, "")
    allowed_fields_changed = [
        field_name
        for field_name in allowed_influence_fields
        if normalized_authoritative_fields.get(field_name) != enforced_candidate_fields.get(field_name)
    ]
    blocked_fields_changed = [
        field_name
        for field_name in blocked_frozen_fields
        if normalized_authoritative_fields.get(field_name) != enforced_candidate_fields.get(field_name)
    ]
    attempted_forbidden_fields = [
        field_name
        for field_name in blocked_frozen_fields
        if normalized_authoritative_fields.get(field_name) != raw_candidate_fields.get(field_name)
    ]
    return {
        "contract": contract,
        "blocked_fields_frozen": freeze_blocked_fields,
        "forbidden_field_change_attempted": bool(attempted_forbidden_fields),
        "attempted_forbidden_fields": attempted_forbidden_fields,
        "raw_candidate_fields": raw_candidate_fields,
        "enforced_candidate_fields": enforced_candidate_fields,
        "allowed_fields_changed": allowed_fields_changed,
        "blocked_fields_changed": blocked_fields_changed,
        "blocked_fields_preserved": not blocked_fields_changed,
    }


def build_controlled_retrieval_comparison_harness(
    *,
    authoritative_user_payload: dict[str, Any],
    packet: dict[str, Any] | None,
    component: str,
    comparison_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    packet = dict(packet or {})
    comparison_config = dict(comparison_config or {})
    constrained_influence = build_retrieval_constrained_influence_contract(
        component=component,
        comparison_config=comparison_config,
    )
    candidate_user_payload: dict[str, Any] | None = None
    packet_status = str(packet.get("status", "missing")).strip() or "missing"
    candidate_available = packet_status == "loaded"
    if candidate_available:
        candidate_user_payload = _clone_json_payload(authoritative_user_payload)
        optional_input_artifacts = dict(candidate_user_payload.get("optional_input_artifacts", {}))
        optional_input_artifacts["retrieval_packet"] = packet
        candidate_user_payload["optional_input_artifacts"] = optional_input_artifacts
        if bool(constrained_influence.get("enabled", False)):
            candidate_user_payload["retrieval_influence_contract"] = {
                "schema_version": str(constrained_influence.get("schema_version", "")),
                "component": component,
                "mode": str(constrained_influence.get("mode", "")),
                "allowed_influence_fields": list(constrained_influence.get("allowed_influence_fields", [])),
                "blocked_frozen_fields": list(constrained_influence.get("blocked_frozen_fields", [])),
                "retrieval_influence_scope": "allowed_fields_only",
                "decision_critical_fields_must_match_authoritative_baseline": True,
                "official_decision_behavior_changed": False,
                "production_authority_transfer_enabled": False,
            }
    shadow_status = "disabled"
    if bool(comparison_config.get("enabled", False)):
        shadow_status = "ready" if candidate_available else "unavailable_missing_retrieval_packet"
    harness = {
        "component": component,
        "comparison_only": True,
        "decision_behavior_changed": False,
        "fail_closed_preserved": True,
        "explicitly_enabled": bool(comparison_config.get("enabled", False)),
        "authoritative_variant": CONTROLLED_RETRIEVAL_AUTHORITATIVE_VARIANT,
        "candidate_variant": CONTROLLED_RETRIEVAL_CANDIDATE_VARIANT,
        "candidate_available": candidate_available,
        "retrieval_packet_status": packet_status,
        "constrained_influence": constrained_influence,
        "authoritative_prompt_metrics": _payload_prompt_metrics(authoritative_user_payload),
        "candidate_prompt_metrics": (
            _payload_prompt_metrics(candidate_user_payload)
            if candidate_user_payload is not None
            else {}
        ),
        "observations": {
            "authoritative": {
                "user_payload_includes_retrieval_packet": False,
                "usage": {},
                "note_fields": {},
                "proposal_content_fields": {},
            },
            "candidate": {
                "status": shadow_status,
                "user_payload_includes_retrieval_packet": candidate_user_payload is not None,
                "usage": {},
                "note_fields": {},
                "proposal_content_fields": {},
                "enforcement": {
                    "blocked_fields_frozen": False,
                    "forbidden_field_change_attempted": False,
                    "attempted_forbidden_fields": [],
                },
                "error": "",
            },
            "diff": {
                "fields_compared": [],
                "changed_fields": [],
                "has_note_differences": False,
                "proposal_content_fields_compared": [],
                "proposal_content_fields_changed": [],
                "proposal_content_fields_preserved": True,
                "forbidden_fields_compared": list(constrained_influence.get("blocked_frozen_fields", [])),
                "forbidden_fields_changed": [],
                "forbidden_field_change_attempted": False,
            },
        },
    }
    return harness, candidate_user_payload
