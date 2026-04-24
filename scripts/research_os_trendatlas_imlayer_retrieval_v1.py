from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from research_os_trendatlas_imlayer_ingest_v1 import IngestionFailure, load_env_file, parse_bool, parse_utc_timestamp
    from research_os_trendatlas_imlayer_reconcile_v1 import (
        DEFAULT_EXPORTS_ROOT,
        DEFAULT_READ_URL,
        EXPECTED_COLLECTION,
        EXPECTED_NAMESPACE,
        EXPECTED_READ_CONTRACT,
        EXPECTED_TENANT_ID,
        ReconciliationFailure,
        load_export_batch,
        read_memory_record,
        resolve_read_url,
    )
except ModuleNotFoundError:
    from scripts.research_os_trendatlas_imlayer_ingest_v1 import (  # type: ignore
        IngestionFailure,
        load_env_file,
        parse_bool,
        parse_utc_timestamp,
    )
    from scripts.research_os_trendatlas_imlayer_reconcile_v1 import (  # type: ignore
        DEFAULT_EXPORTS_ROOT,
        DEFAULT_READ_URL,
        EXPECTED_COLLECTION,
        EXPECTED_NAMESPACE,
        EXPECTED_READ_CONTRACT,
        EXPECTED_TENANT_ID,
        ReconciliationFailure,
        load_export_batch,
        read_memory_record,
        resolve_read_url,
    )

PACKET_SCHEMA_VERSION = "trendatlas.imlayer.retrieval_packet.v1"
DEFAULT_OUTPUT_ROOT = Path("outputs/research_os/dev_only/imlayer_retrieval")
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_VERIFY_TLS = False
MAX_RECENT_RECORDS = 5
FRESHNESS_FIELD_PATH = ("decision_packet", "freshness_hours")


class RetrievalFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ReadConfig:
    read_url_template: str
    auth_header: str
    auth_scheme: str
    auth_token: str
    timeout_seconds: int
    verify_tls: bool


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compact_json(payload) + "\n", encoding="utf-8")


def require_non_empty_string(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalFailure(f"{label} must be a non-empty string")
    return value.strip()


def get_nested(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def normalize_string_list(label: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RetrievalFailure(f"{label} must be a list")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            item = str(item)
        text = " ".join(item.split())
        if text:
            items.append(text)
    return items


def canonical_json_sha256(value: Any) -> str:
    import hashlib

    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def drop_nested_field(value: Any, path: tuple[str, ...]) -> Any:
    from copy import deepcopy

    cloned = deepcopy(value)
    current = cloned
    for key in path[:-1]:
        if not isinstance(current, dict):
            return cloned
        current = current.get(key)
    if isinstance(current, dict):
        current.pop(path[-1], None)
    return cloned


def slugify_query_target(value: str) -> str:
    out = []
    for char in value:
        if char.isalnum() or char in {"-", "_", "."}:
            out.append(char)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    return slug or "query_target"


def resolve_read_config(env: dict[str, str]) -> ReadConfig:
    auth_token = env.get("TRENDATLAS_IML_AUTH_TOKEN", "").strip()
    if not auth_token:
        raise RetrievalFailure("TRENDATLAS_IML_AUTH_TOKEN is required for read-back retrieval")

    auth_header = env.get("TRENDATLAS_IML_AUTH_HEADER", "Authorization").strip()
    auth_scheme = env.get("TRENDATLAS_IML_AUTH_SCHEME", "Bearer").strip()
    if auth_header != "Authorization":
        raise RetrievalFailure("TRENDATLAS_IML_AUTH_HEADER must be Authorization")
    if auth_scheme != "Bearer":
        raise RetrievalFailure("TRENDATLAS_IML_AUTH_SCHEME must be Bearer")

    timeout_raw = env.get("TRENDATLAS_IML_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        timeout_seconds = int(timeout_raw)
    except ValueError as exc:
        raise RetrievalFailure("TRENDATLAS_IML_TIMEOUT_SECONDS must be an integer") from exc
    if timeout_seconds <= 0:
        raise RetrievalFailure("TRENDATLAS_IML_TIMEOUT_SECONDS must be positive")

    verify_tls = parse_bool(
        env.get(
            "TRENDATLAS_IML_VERIFY_TLS",
            "true" if DEFAULT_VERIFY_TLS else "false",
        )
    )

    return ReadConfig(
        read_url_template=env.get("TRENDATLAS_IML_READ_URL", DEFAULT_READ_URL).strip() or DEFAULT_READ_URL,
        auth_header=auth_header,
        auth_scheme=auth_scheme,
        auth_token=auth_token,
        timeout_seconds=timeout_seconds,
        verify_tls=verify_tls,
    )


def resolve_batch_root(batch_id: str | None, batch_root: str | None) -> Path:
    if batch_root:
        return Path(batch_root)
    if batch_id:
        return DEFAULT_EXPORTS_ROOT / batch_id
    if not DEFAULT_EXPORTS_ROOT.exists():
        raise RetrievalFailure(f"Export root not found: {DEFAULT_EXPORTS_ROOT.as_posix()}")
    batch_dirs = sorted(path for path in DEFAULT_EXPORTS_ROOT.iterdir() if path.is_dir())
    if not batch_dirs:
        raise RetrievalFailure(f"No export batches found under: {DEFAULT_EXPORTS_ROOT.as_posix()}")
    return batch_dirs[-1]


def resolve_episode_timestamp_utc(episode: dict[str, Any]) -> str:
    for candidate in (
        get_nested(episode, "episode_timestamps", "heavy_validation_finished_at"),
        get_nested(episode, "episode_timestamps", "critic_generated_at"),
        get_nested(episode, "episode_timestamps", "governor_updated_at"),
        episode.get("export_generated_at"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return parse_utc_timestamp(candidate, label="episode timestamp").isoformat().replace("+00:00", "Z")
    raise RetrievalFailure(
        f"Unable to resolve ordering timestamp for episode {episode.get('memory_id')!r}"
    )


def load_family_candidates(batch_root: Path, family_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    export_batch = load_export_batch(batch_root)
    matches: list[dict[str, Any]] = []
    for episode_entry in export_batch["episodes"]:
        episode = episode_entry["episode"]
        if get_nested(episode, "keys", "family_id") != family_id:
            continue
        matches.append(
            {
                "memory_id": require_non_empty_string("memory_id", episode.get("memory_id")),
                "cycle_id": require_non_empty_string("keys.cycle_id", get_nested(episode, "keys", "cycle_id")),
                "timestamp_utc": resolve_episode_timestamp_utc(episode),
                "relative_path": episode_entry["relative_path"],
                "episode": episode,
            }
        )
    if not matches:
        raise RetrievalFailure(
            f"No exported episodes found for family_id={family_id!r} in batch {batch_root.as_posix()}"
        )
    matches.sort(key=lambda item: (item["timestamp_utc"], item["memory_id"]), reverse=True)
    return export_batch, matches


def resolve_memory_query_target(
    candidates: list[dict[str, Any]],
    memory_query_target: str,
) -> list[dict[str, Any]]:
    target = memory_query_target.strip()
    if not target:
        raise RetrievalFailure("memory_query_target must be a non-empty string")
    if target == "latest":
        return [candidates[0]]
    if target.startswith("recent:"):
        raw_limit = target.split(":", 1)[1].strip()
        try:
            limit = int(raw_limit)
        except ValueError as exc:
            raise RetrievalFailure(f"Invalid recent:N query target: {target!r}") from exc
        if limit <= 0 or limit > MAX_RECENT_RECORDS:
            raise RetrievalFailure(f"recent:N limit must be between 1 and {MAX_RECENT_RECORDS}")
        return candidates[:limit]
    if target.startswith("cycle:"):
        cycle_id = target.split(":", 1)[1].strip()
        if not cycle_id:
            raise RetrievalFailure("cycle:<cycle_id> requires a non-empty cycle_id")
        matches = [item for item in candidates if item["cycle_id"] == cycle_id]
        if len(matches) != 1:
            raise RetrievalFailure(f"Expected exactly one cycle match for {cycle_id!r}, found {len(matches)}")
        return matches
    if target.startswith("memory_id:"):
        memory_id = target.split(":", 1)[1].strip()
        if not memory_id:
            raise RetrievalFailure("memory_id:<memory_id> requires a non-empty memory_id")
        matches = [item for item in candidates if item["memory_id"] == memory_id]
        if len(matches) != 1:
            raise RetrievalFailure(f"Expected exactly one memory_id match for {memory_id!r}, found {len(matches)}")
        return matches
    raise RetrievalFailure(
        "Unsupported memory_query_target. Use latest, recent:N, cycle:<cycle_id>, or memory_id:<memory_id>."
    )


def require_payload_bool(label: str, value: Any, expected: bool) -> None:
    if value is not expected:
        raise RetrievalFailure(f"{label} must be {str(expected).lower()}")


def build_record_summary(
    *,
    family_id: str,
    response_payload: dict[str, Any],
) -> dict[str, Any]:
    if response_payload.get("success") is not True:
        raise RetrievalFailure("read response success must be true")
    if response_payload.get("contract") != EXPECTED_READ_CONTRACT:
        raise RetrievalFailure(
            f"read response contract must be {EXPECTED_READ_CONTRACT}"
        )

    response_memory_id = require_non_empty_string("response.memory_id", response_payload.get("memory_id"))
    record = response_payload.get("record")
    if not isinstance(record, dict):
        raise RetrievalFailure("read response record must be an object")
    stored_payload = record.get("payload")
    if not isinstance(stored_payload, dict):
        raise RetrievalFailure("read response record.payload must be an object")

    stored_memory_id = require_non_empty_string("record.payload.memory_id", stored_payload.get("memory_id"))
    if stored_memory_id != response_memory_id:
        raise RetrievalFailure("response.memory_id must match record.payload.memory_id")
    if stored_payload.get("namespace") != EXPECTED_NAMESPACE:
        raise RetrievalFailure(f"record.payload.namespace must be {EXPECTED_NAMESPACE}")
    if stored_payload.get("collection") != EXPECTED_COLLECTION:
        raise RetrievalFailure(f"record.payload.collection must be {EXPECTED_COLLECTION}")
    if stored_payload.get("schema_version") != EXPECTED_READ_CONTRACT:
        raise RetrievalFailure(f"record.payload.schema_version must be {EXPECTED_READ_CONTRACT}")
    if stored_payload.get("tenant_id") != EXPECTED_TENANT_ID:
        raise RetrievalFailure(f"record.payload.tenant_id must be {EXPECTED_TENANT_ID}")

    stored_family_id = require_non_empty_string(
        "record.payload.run_context.family_id",
        get_nested(stored_payload, "run_context", "family_id"),
    )
    if stored_family_id != family_id:
        raise RetrievalFailure(
            f"record.payload.run_context.family_id {stored_family_id!r} does not match requested family {family_id!r}"
        )

    authoritative = get_nested(stored_payload, "metadata", "authoritative")
    environment = get_nested(stored_payload, "metadata", "environment")
    require_payload_bool("record.payload.metadata.authoritative", authoritative, False)
    if environment != "dev":
        raise RetrievalFailure("record.payload.metadata.environment must be 'dev'")

    freshness_hours = get_nested(stored_payload, "decision_packet", "freshness_hours")
    if not isinstance(freshness_hours, (int, float)):
        raise RetrievalFailure("record.payload.decision_packet.freshness_hours must be numeric")

    semantic_sha256 = canonical_json_sha256(drop_nested_field(stored_payload, FRESHNESS_FIELD_PATH))
    return {
        "memory_id": stored_memory_id,
        "decision_timestamp_utc": require_non_empty_string(
            "record.payload.decision_timestamp_utc",
            stored_payload.get("decision_timestamp_utc"),
        ),
        "received_at_utc": require_non_empty_string(
            "record.received_at_utc",
            record.get("received_at_utc"),
        ),
        "write_id": require_non_empty_string("record.write_id", record.get("write_id")),
        "entity_id": require_non_empty_string("record.payload.entity_id", stored_payload.get("entity_id")),
        "decision": {
            "action": require_non_empty_string(
                "record.payload.decision.action",
                get_nested(stored_payload, "decision", "action"),
            ),
            "verdict": require_non_empty_string(
                "record.payload.decision.verdict",
                get_nested(stored_payload, "decision", "verdict"),
            ),
            "rationale_summary": require_non_empty_string(
                "record.payload.decision.rationale_summary",
                get_nested(stored_payload, "decision", "rationale_summary"),
            ),
            "expected_impact_summary": require_non_empty_string(
                "record.payload.decision.expected_impact_summary",
                get_nested(stored_payload, "decision", "expected_impact_summary"),
            ),
            "stop_condition": require_non_empty_string(
                "record.payload.decision.stop_condition",
                get_nested(stored_payload, "decision", "stop_condition"),
            ),
            "confidence": get_nested(stored_payload, "decision", "confidence"),
        },
        "run_context": {
            "cycle_id": require_non_empty_string(
                "record.payload.run_context.cycle_id",
                get_nested(stored_payload, "run_context", "cycle_id"),
            ),
            "family_id": stored_family_id,
            "mechanism_id": require_non_empty_string(
                "record.payload.run_context.mechanism_id",
                get_nested(stored_payload, "run_context", "mechanism_id"),
            ),
            "proposal_id": require_non_empty_string(
                "record.payload.run_context.proposal_id",
                get_nested(stored_payload, "run_context", "proposal_id"),
            ),
            "validation_job_id": require_non_empty_string(
                "record.payload.run_context.validation_job_id",
                get_nested(stored_payload, "run_context", "validation_job_id"),
            ),
            "critic_run_id": require_non_empty_string(
                "record.payload.run_context.critic_run_id",
                get_nested(stored_payload, "run_context", "critic_run_id"),
            ),
            "governor_run_id": require_non_empty_string(
                "record.payload.run_context.governor_run_id",
                get_nested(stored_payload, "run_context", "governor_run_id"),
            ),
        },
        "outcome": {
            "status": require_non_empty_string(
                "record.payload.outcome.status",
                get_nested(stored_payload, "outcome", "status"),
            ),
            "actual_impact_summary_text": require_non_empty_string(
                "record.payload.outcome.actual_impact_summary",
                get_nested(stored_payload, "outcome", "actual_impact_summary"),
            ),
            "delta_summary_text": require_non_empty_string(
                "record.payload.outcome.delta_summary",
                get_nested(stored_payload, "outcome", "delta_summary"),
            ),
            "cost_summary_text": require_non_empty_string(
                "record.payload.outcome.cost_summary",
                get_nested(stored_payload, "outcome", "cost_summary"),
            ),
            "failure_modes": normalize_string_list(
                "record.payload.outcome.failure_modes",
                get_nested(stored_payload, "outcome", "failure_modes"),
            ),
            "contradiction_flags": normalize_string_list(
                "record.payload.outcome.contradiction_flags",
                get_nested(stored_payload, "outcome", "contradiction_flags"),
            ),
        },
        "decision_packet": {
            "packet_text": require_non_empty_string(
                "record.payload.decision_packet.packet_text",
                get_nested(stored_payload, "decision_packet", "packet_text"),
            ),
            "salient_facts": normalize_string_list(
                "record.payload.decision_packet.salient_facts",
                get_nested(stored_payload, "decision_packet", "salient_facts"),
            ),
            "risk_flags": normalize_string_list(
                "record.payload.decision_packet.risk_flags",
                get_nested(stored_payload, "decision_packet", "risk_flags"),
            ),
            "freshness_hours": round(float(freshness_hours), 6),
            "semantic_sha256": semantic_sha256,
        },
        "metadata": {
            "authoritative": authoritative,
            "environment": environment,
            "tags": normalize_string_list(
                "record.payload.metadata.tags",
                get_nested(stored_payload, "metadata", "tags"),
            ),
        },
    }


def build_family_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    latest = records[0]
    risk_flag_union = sorted(
        {
            risk_flag
            for record in records
            for risk_flag in record["decision_packet"]["risk_flags"]
        }
    )
    return {
        "selected_count": len(records),
        "latest_memory_id": latest["memory_id"],
        "latest_cycle_id": latest["run_context"]["cycle_id"],
        "latest_verdict": latest["decision"]["verdict"],
        "latest_action": latest["decision"]["action"],
        "latest_write_id": latest["write_id"],
        "verdict_sequence": [record["decision"]["verdict"] for record in records],
        "action_sequence": [record["decision"]["action"] for record in records],
        "risk_flag_union": risk_flag_union,
    }


def build_retrieval_packet(
    *,
    batch_id: str,
    family_id: str,
    memory_query_target: str,
    selected_records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": PACKET_SCHEMA_VERSION,
        "retrieval_generated_at_utc": utc_now_iso(),
        "policy": {
            "fail_closed": True,
            "repo_safe_read_only": True,
            "planner_logic_mutation": False,
            "critic_logic_mutation": False,
            "strategy_mutation": False,
            "source_of_truth_mutation": False,
            "official_promotion_logic": False,
        },
        "query": {
            "family_id": family_id,
            "memory_query_target": memory_query_target,
            "resolved_batch_id": batch_id,
            "resolved_memory_ids": [record["memory_id"] for record in selected_records],
        },
        "records": selected_records,
        "family_summary": build_family_summary(selected_records),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read back TrendAtlas decision episodes from imLayer and build a compact retrieval packet.",
    )
    parser.add_argument("--family-id", required=True)
    parser.add_argument("--memory-query-target", default="latest")
    parser.add_argument("--batch-id")
    parser.add_argument("--batch-root")
    parser.add_argument("--env-file")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runtime_env = dict(os.environ)
        file_env = load_env_file(Path(args.env_file)) if args.env_file else {}
        merged_env = {**file_env, **runtime_env}
        read_config = resolve_read_config(merged_env)

        batch_root = resolve_batch_root(args.batch_id, args.batch_root)
        export_batch, candidates = load_family_candidates(batch_root.resolve(), args.family_id)
        selected = resolve_memory_query_target(candidates, args.memory_query_target)

        selected_records: list[dict[str, Any]] = []
        for selection in selected:
            url = resolve_read_url(read_config.read_url_template, selection["memory_id"])
            response_payload = read_memory_record(
                url=url,
                timeout_seconds=read_config.timeout_seconds,
                verify_tls=read_config.verify_tls,
                auth_header=read_config.auth_header,
                auth_scheme=read_config.auth_scheme,
                auth_token=read_config.auth_token,
            )
            selected_records.append(
                build_record_summary(
                    family_id=args.family_id,
                    response_payload=response_payload,
                )
            )

        if not selected_records:
            raise RetrievalFailure("No read-back records were selected")

        batch_id = require_non_empty_string("export_batch.batch_id", export_batch.get("batch_id"))
        retrieval_packet = build_retrieval_packet(
            batch_id=batch_id,
            family_id=args.family_id,
            memory_query_target=args.memory_query_target,
            selected_records=selected_records,
        )

        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_root = Path(args.output_root).resolve()
        output_path = output_root / run_id / f"{args.family_id}.{slugify_query_target(args.memory_query_target)}.retrieval_packet.json"
        write_json(output_path, retrieval_packet)
        print(
            compact_json(
                {
                    "status": "completed",
                    "output_path": output_path.as_posix(),
                    "batch_id": batch_id,
                    "family_id": args.family_id,
                    "memory_query_target": args.memory_query_target,
                    "selected_count": len(selected_records),
                }
            )
        )
        return 0
    except (RetrievalFailure, IngestionFailure, ReconciliationFailure) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
