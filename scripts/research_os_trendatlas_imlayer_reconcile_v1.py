from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

EXPECTED_EXPORT_MANIFEST_SCHEMA = "trendatlas.imlayer.export_manifest.v1"
EXPECTED_INGESTION_MANIFEST_SCHEMA = "trendatlas.imlayer.ingestion_manifest.v1"
EXPECTED_READ_CONTRACT = "imlayer.trendatlas.v1"
DEFAULT_EXPORTS_ROOT = Path("outputs/research_os/dev_only/imlayer_exports")
DEFAULT_INGESTION_ROOT = Path("outputs/research_os/dev_only/imlayer_ingestion")
DEFAULT_READ_URL = "http://127.0.0.1:8000/api/v1/reads/decision-episodes/{memory_id}"
EXPECTED_NAMESPACE = "trendatlas"
EXPECTED_COLLECTION = "decision_episodes"
EXPECTED_TENANT_ID = "research_os_prod"
READ_CONTRACT_MARKERS = (
    "TRENDATLAS_IML_READ_URL",
    "/api/v1/reads",
)
READ_CONTRACT_SEARCH_ROOTS = (
    "configs",
    "services",
    "scripts",
)
READ_CONTRACT_EXCLUDED_FILES = {
    "research_os_trendatlas_imlayer_reconcile_v1.py",
}
PERSISTENCE_CANDIDATE_PATTERNS = (
    "*.sqlite",
    "*.db",
    "*.duckdb",
    "*.jsonl",
    "*.ndjson",
    "*.parquet",
)
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_VERIFY_TLS = False
FRESHNESS_HOURS_FIELD_PATH = ("decision_packet", "freshness_hours")
FRESHNESS_HOURS_TOLERANCE_HOURS = 0.0005


class ReconciliationFailure(RuntimeError):
    pass


def compact_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def canonical_json_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def drop_nested_field(value: Any, path: tuple[str, ...]) -> Any:
    cloned = deepcopy(value)
    current = cloned
    for key in path[:-1]:
        if not isinstance(current, dict):
            return cloned
        current = current.get(key)
    if isinstance(current, dict):
        current.pop(path[-1], None)
    return cloned


def get_nested_field(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReconciliationFailure(f"JSON file not found: {path.as_posix()}") from exc
    except json.JSONDecodeError as exc:
        raise ReconciliationFailure(f"JSON file is invalid: {path.as_posix()} ({exc})") from exc


def require_non_empty_string(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReconciliationFailure(f"{label} must be a non-empty string")
    return value.strip()


def resolve_export_batch_root(batch_id: str | None, batch_root: str | None) -> Path:
    if batch_root:
        return Path(batch_root)
    if not batch_id:
        raise ReconciliationFailure("Either --batch-id or --batch-root must be provided")
    return DEFAULT_EXPORTS_ROOT / batch_id


def resolve_ingestion_manifest_path(
    batch_id: str,
    ingestion_manifest: str | None,
    ingestion_root: str | None,
) -> Path:
    if ingestion_manifest:
        return Path(ingestion_manifest)
    root = Path(ingestion_root) if ingestion_root else DEFAULT_INGESTION_ROOT / batch_id
    if root.is_file():
        return root
    if not root.exists():
        raise ReconciliationFailure(f"Ingestion root not found: {root.as_posix()}")
    manifests = sorted(root.glob("*/ingestion_manifest.json"))
    if not manifests:
        raise ReconciliationFailure(
            f"No ingestion manifests found under: {root.as_posix()}"
        )
    return manifests[-1]


def load_export_batch(batch_root: Path) -> dict[str, Any]:
    manifest_path = batch_root / "manifest.json"
    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != EXPECTED_EXPORT_MANIFEST_SCHEMA:
        raise ReconciliationFailure(
            f"export manifest schema_version must be {EXPECTED_EXPORT_MANIFEST_SCHEMA}"
        )
    batch_id = require_non_empty_string("export_batch_id", manifest.get("export_batch_id"))
    episode_paths = manifest.get("episode_paths")
    if not isinstance(episode_paths, list) or not episode_paths:
        raise ReconciliationFailure("export manifest episode_paths must contain at least one entry")

    episodes: list[dict[str, Any]] = []
    memory_ids: list[str] = []
    for relative_path in episode_paths:
        episode_path = batch_root / str(relative_path)
        episode = load_json(episode_path)
        memory_id = require_non_empty_string(
            f"{episode_path.as_posix()} memory_id",
            episode.get("memory_id"),
        )
        memory_ids.append(memory_id)
        episodes.append(
            {
                "relative_path": str(relative_path),
                "path": episode_path.as_posix(),
                "memory_id": memory_id,
                "episode": episode,
            }
        )

    return {
        "batch_id": batch_id,
        "batch_root": batch_root.as_posix(),
        "manifest_path": manifest_path.as_posix(),
        "manifest": manifest,
        "episodes": episodes,
        "memory_ids": memory_ids,
    }


def load_ingestion_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != EXPECTED_INGESTION_MANIFEST_SCHEMA:
        raise ReconciliationFailure(
            f"ingestion manifest schema_version must be {EXPECTED_INGESTION_MANIFEST_SCHEMA}"
        )
    results = manifest.get("results")
    if not isinstance(results, list):
        raise ReconciliationFailure("ingestion manifest results must be a list")
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise ReconciliationFailure("ingestion manifest counts must be an object")
    if counts.get("total") != len(results):
        raise ReconciliationFailure("ingestion manifest counts.total must equal len(results)")
    return {
        "manifest_path": manifest_path.as_posix(),
        "manifest": manifest,
        "results": results,
    }


def normalize_result_field(result: dict[str, Any], field_name: str) -> str | None:
    request = result.get("request")
    response = result.get("response")
    request_value = request.get(field_name) if isinstance(request, dict) else None
    response_value = response.get(field_name) if isinstance(response, dict) else None
    if isinstance(response_value, str) and response_value.strip():
        return response_value.strip()
    if isinstance(request_value, str) and request_value.strip():
        return request_value.strip()
    return None


def build_write_ack_parity(
    export_batch: dict[str, Any],
    ingestion_manifest: dict[str, Any],
) -> dict[str, Any]:
    export_memory_ids = list(export_batch["memory_ids"])
    export_memory_id_set = set(export_memory_ids)
    results = ingestion_manifest["results"]
    writer = ingestion_manifest["manifest"].get("writer", {})
    expected_namespace = writer.get("payload_namespace") or EXPECTED_NAMESPACE
    expected_collection = writer.get("payload_collection") or EXPECTED_COLLECTION

    acknowledged = [
        result
        for result in results
        if result.get("status") in {"ingested", "deduplicated"}
    ]
    failed = [
        {
            "memory_id": result.get("memory_id"),
            "episode_path": result.get("episode_path"),
            "status": result.get("status"),
            "reason": result.get("reason"),
        }
        for result in results
        if result.get("status") not in {"ingested", "deduplicated"}
    ]

    observed: list[dict[str, Any]] = []
    field_mismatches: list[dict[str, Any]] = []
    for result in acknowledged:
        request = result.get("request") if isinstance(result.get("request"), dict) else {}
        response = result.get("response") if isinstance(result.get("response"), dict) else {}
        memory_id = normalize_result_field(result, "memory_id")
        namespace = normalize_result_field(result, "namespace")
        collection = normalize_result_field(result, "collection")
        if request.get("memory_id") and response.get("memory_id") and request["memory_id"] != response["memory_id"]:
            field_mismatches.append(
                {
                    "episode_path": result.get("episode_path"),
                    "field": "memory_id",
                    "request": request.get("memory_id"),
                    "response": response.get("memory_id"),
                }
            )
        if request.get("namespace") and response.get("namespace") and request["namespace"] != response["namespace"]:
            field_mismatches.append(
                {
                    "episode_path": result.get("episode_path"),
                    "field": "namespace",
                    "request": request.get("namespace"),
                    "response": response.get("namespace"),
                }
            )
        if request.get("collection") and response.get("collection") and request["collection"] != response["collection"]:
            field_mismatches.append(
                {
                    "episode_path": result.get("episode_path"),
                    "field": "collection",
                    "request": request.get("collection"),
                    "response": response.get("collection"),
                }
            )
        observed.append(
            {
                "memory_id": memory_id,
                "namespace": namespace,
                "collection": collection,
                "status": result.get("status"),
                "episode_path": result.get("episode_path"),
            }
        )

    observed_memory_ids = [item["memory_id"] for item in observed if item["memory_id"]]
    observed_memory_id_set = set(observed_memory_ids)
    namespaces = sorted({item["namespace"] for item in observed if item["namespace"]})
    collections = sorted({item["collection"] for item in observed if item["collection"]})
    missing_on_iml = sorted(export_memory_id_set - observed_memory_id_set)
    unexpected_on_iml = sorted(observed_memory_id_set - export_memory_id_set)

    status = "passed"
    reasons: list[str] = []
    if failed:
        status = "failed"
        reasons.append("ingestion manifest contains non-acknowledged results")
    if field_mismatches:
        status = "failed"
        reasons.append("ingestion request/response field mismatches detected")
    if len(export_memory_ids) != len(observed):
        status = "failed"
        reasons.append("count parity failed between export manifest and acknowledged IML writes")
    if missing_on_iml or unexpected_on_iml:
        status = "failed"
        reasons.append("memory_id parity failed")
    if namespaces != [expected_namespace]:
        status = "failed"
        reasons.append("namespace parity failed against ingestion writer contract")
    if collections != [expected_collection]:
        status = "failed"
        reasons.append("collection parity failed against ingestion writer contract")

    return {
        "status": status,
        "reason": "; ".join(reasons) if reasons else None,
        "export_count": len(export_memory_ids),
        "acknowledged_count": len(observed),
        "expected_namespace": expected_namespace,
        "expected_collection": expected_collection,
        "namespace_source": "ingestion_manifest.writer",
        "collection_source": "ingestion_manifest.writer",
        "export_manifest_has_namespace": False,
        "export_manifest_has_collection": False,
        "memory_ids_expected": sorted(export_memory_ids),
        "memory_ids_acknowledged": sorted(observed_memory_ids),
        "missing_on_imlayer": missing_on_iml,
        "unexpected_on_imlayer": unexpected_on_iml,
        "observed_namespaces": namespaces,
        "observed_collections": collections,
        "failed_results": failed,
        "field_mismatches": field_mismatches,
    }


def load_ingest_helper_module():
    ingest_path = Path(__file__).with_name("research_os_trendatlas_imlayer_ingest_v1.py")
    spec = importlib.util.spec_from_file_location(
        "research_os_trendatlas_imlayer_ingest_v1_for_reconcile",
        ingest_path,
    )
    if spec is None or spec.loader is None:
        raise ReconciliationFailure(
            f"Unable to load ingest helper module: {ingest_path.as_posix()}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_true_read_back_parity(
    export_batch: dict[str, Any],
    ingestion_manifest: dict[str, Any],
) -> dict[str, Any]:
    ingest_module = load_ingest_helper_module()
    build_live_episode_payload = ingest_module.build_live_episode_payload
    parse_utc_timestamp = ingest_module.parse_utc_timestamp

    read_url_template = os.environ.get("TRENDATLAS_IML_READ_URL", DEFAULT_READ_URL)
    auth_header = os.environ.get("TRENDATLAS_IML_AUTH_HEADER", "Authorization")
    auth_scheme = os.environ.get("TRENDATLAS_IML_AUTH_SCHEME", "Bearer")
    auth_token = os.environ.get("TRENDATLAS_IML_AUTH_TOKEN", "")
    timeout_seconds_raw = os.environ.get("TRENDATLAS_IML_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    verify_tls_raw = os.environ.get(
        "TRENDATLAS_IML_VERIFY_TLS",
        "true" if DEFAULT_VERIFY_TLS else "false",
    )

    try:
        timeout_seconds = int(timeout_seconds_raw)
    except ValueError as exc:
        raise ReconciliationFailure(
            f"TRENDATLAS_IML_TIMEOUT_SECONDS must be an integer, got {timeout_seconds_raw!r}"
        ) from exc
    if timeout_seconds <= 0:
        raise ReconciliationFailure("TRENDATLAS_IML_TIMEOUT_SECONDS must be positive")
    try:
        verify_tls = ingest_module.parse_bool(verify_tls_raw)
    except Exception as exc:
        raise ReconciliationFailure(
            f"TRENDATLAS_IML_VERIFY_TLS must be a boolean, got {verify_tls_raw!r}"
        ) from exc

    expected_by_memory_id = {
        episode_entry["memory_id"]: episode_entry
        for episode_entry in export_batch["episodes"]
    }
    acked_by_memory_id = {
        item["memory_id"]: item
        for item in ingestion_manifest["results"]
        if item.get("status") in {"ingested", "deduplicated"} and item.get("memory_id")
    }

    verified: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    request_failures: list[dict[str, Any]] = []
    semantic_parity_passed = 0
    semantic_parity_failed = 0
    freshness_within_tolerance = 0
    freshness_outside_tolerance = 0

    for memory_id in export_batch["memory_ids"]:
        episode_entry = expected_by_memory_id[memory_id]
        ack_result = acked_by_memory_id.get(memory_id)
        url = resolve_read_url(read_url_template, memory_id)
        try:
            response_payload = read_memory_record(
                url=url,
                timeout_seconds=timeout_seconds,
                verify_tls=verify_tls,
                auth_header=auth_header,
                auth_scheme=auth_scheme,
                auth_token=auth_token,
            )
        except ReconciliationFailure as exc:
            request_failures.append(
                {
                    "memory_id": memory_id,
                    "episode_path": episode_entry["relative_path"],
                    "url": url,
                    "reason": str(exc),
                }
            )
            continue

        record = response_payload.get("record")
        if not isinstance(record, dict):
            request_failures.append(
                {
                    "memory_id": memory_id,
                    "episode_path": episode_entry["relative_path"],
                    "url": url,
                    "reason": "read response record must be an object",
                    "response": response_payload,
                }
            )
            continue
        stored_payload = record.get("payload")
        if not isinstance(stored_payload, dict):
            request_failures.append(
                {
                    "memory_id": memory_id,
                    "episode_path": episode_entry["relative_path"],
                    "url": url,
                    "reason": "read response record.payload must be an object",
                    "response": response_payload,
                }
            )
            continue

        received_at_utc = require_non_empty_string(
            "record.received_at_utc",
            record.get("received_at_utc"),
        )
        expected_payload = build_live_episode_payload(
            episode_entry["episode"],
            now_utc=parse_utc_timestamp(received_at_utc, label="record.received_at_utc"),
        )
        expected_semantic_payload = drop_nested_field(
            expected_payload,
            FRESHNESS_HOURS_FIELD_PATH,
        )
        observed_semantic_payload = drop_nested_field(
            stored_payload,
            FRESHNESS_HOURS_FIELD_PATH,
        )
        expected_payload_sha256 = canonical_json_sha256(expected_semantic_payload)
        observed_payload_sha256 = canonical_json_sha256(observed_semantic_payload)
        expected_freshness_hours = get_nested_field(expected_payload, FRESHNESS_HOURS_FIELD_PATH)
        observed_freshness_hours = get_nested_field(stored_payload, FRESHNESS_HOURS_FIELD_PATH)

        per_memory_mismatches: list[dict[str, Any]] = []
        semantic_parity_status = "passed"
        freshness_hours_status = "passed"
        freshness_hours_drift_hours: float | None = None
        if response_payload.get("success") is not True:
            per_memory_mismatches.append(
                {
                    "field": "success",
                    "expected": True,
                    "actual": response_payload.get("success"),
                }
            )
        if response_payload.get("contract") != EXPECTED_READ_CONTRACT:
            per_memory_mismatches.append(
                {
                    "field": "contract",
                    "expected": EXPECTED_READ_CONTRACT,
                    "actual": response_payload.get("contract"),
                }
            )
        if response_payload.get("memory_id") != memory_id:
            per_memory_mismatches.append(
                {
                    "field": "memory_id",
                    "expected": memory_id,
                    "actual": response_payload.get("memory_id"),
                }
            )
        if stored_payload.get("memory_id") != memory_id:
            per_memory_mismatches.append(
                {
                    "field": "record.payload.memory_id",
                    "expected": memory_id,
                    "actual": stored_payload.get("memory_id"),
                }
            )
        if stored_payload.get("namespace") != EXPECTED_NAMESPACE:
            per_memory_mismatches.append(
                {
                    "field": "record.payload.namespace",
                    "expected": EXPECTED_NAMESPACE,
                    "actual": stored_payload.get("namespace"),
                }
            )
        if stored_payload.get("collection") != EXPECTED_COLLECTION:
            per_memory_mismatches.append(
                {
                    "field": "record.payload.collection",
                    "expected": EXPECTED_COLLECTION,
                    "actual": stored_payload.get("collection"),
                }
            )
        if stored_payload.get("schema_version") != EXPECTED_READ_CONTRACT:
            per_memory_mismatches.append(
                {
                    "field": "record.payload.schema_version",
                    "expected": EXPECTED_READ_CONTRACT,
                    "actual": stored_payload.get("schema_version"),
                }
            )
        if stored_payload.get("tenant_id") != EXPECTED_TENANT_ID:
            per_memory_mismatches.append(
                {
                    "field": "record.payload.tenant_id",
                    "expected": EXPECTED_TENANT_ID,
                    "actual": stored_payload.get("tenant_id"),
                }
            )
        if observed_payload_sha256 != expected_payload_sha256:
            semantic_parity_status = "failed"
            per_memory_mismatches.append(
                {
                    "field": "record.payload.semantic_sha256",
                    "expected": expected_payload_sha256,
                    "actual": observed_payload_sha256,
                    "excluded_fields": ["decision_packet.freshness_hours"],
                }
            )
        else:
            semantic_parity_passed += 1
        if observed_payload_sha256 == expected_payload_sha256:
            semantic_parity_status = "passed"
        else:
            semantic_parity_failed += 1
        if not isinstance(expected_freshness_hours, (int, float)) or not isinstance(observed_freshness_hours, (int, float)):
            freshness_hours_status = "failed"
            per_memory_mismatches.append(
                {
                    "field": "record.payload.decision_packet.freshness_hours",
                    "expected": expected_freshness_hours,
                    "actual": observed_freshness_hours,
                    "tolerance_hours": FRESHNESS_HOURS_TOLERANCE_HOURS,
                    "reason": "freshness_hours must be numeric on both expected and stored payloads",
                }
            )
            freshness_outside_tolerance += 1
        else:
            freshness_hours_drift_hours = abs(
                float(observed_freshness_hours) - float(expected_freshness_hours)
            )
            if freshness_hours_drift_hours > FRESHNESS_HOURS_TOLERANCE_HOURS:
                freshness_hours_status = "failed"
                per_memory_mismatches.append(
                    {
                        "field": "record.payload.decision_packet.freshness_hours",
                        "expected": expected_freshness_hours,
                        "actual": observed_freshness_hours,
                        "drift_hours": freshness_hours_drift_hours,
                        "tolerance_hours": FRESHNESS_HOURS_TOLERANCE_HOURS,
                    }
                )
                freshness_outside_tolerance += 1
            else:
                freshness_within_tolerance += 1
        if ack_result is not None:
            ack_response = ack_result.get("response")
            if isinstance(ack_response, dict) and ack_response.get("write_id") and record.get("write_id") != ack_response.get("write_id"):
                per_memory_mismatches.append(
                    {
                        "field": "record.write_id",
                        "expected": ack_response.get("write_id"),
                        "actual": record.get("write_id"),
                    }
                )

        verified.append(
            {
                "memory_id": memory_id,
                "episode_path": episode_entry["relative_path"],
                "url": url,
                "write_id": record.get("write_id"),
                "received_at_utc": received_at_utc,
                "expected_payload_sha256": expected_payload_sha256,
                "observed_payload_sha256": observed_payload_sha256,
                "semantic_parity_status": semantic_parity_status,
                "freshness_hours_status": freshness_hours_status,
                "expected_freshness_hours": expected_freshness_hours,
                "observed_freshness_hours": observed_freshness_hours,
                "freshness_hours_drift_hours": freshness_hours_drift_hours,
                "freshness_hours_tolerance_hours": FRESHNESS_HOURS_TOLERANCE_HOURS,
                "status": "passed" if not per_memory_mismatches else "failed",
            }
        )
        for mismatch in per_memory_mismatches:
            mismatches.append(
                {
                    "memory_id": memory_id,
                    "episode_path": episode_entry["relative_path"],
                    **mismatch,
                }
            )

    missing_reads = sorted(set(export_batch["memory_ids"]) - {item["memory_id"] for item in verified})
    unexpected_reads = sorted({item["memory_id"] for item in verified} - set(export_batch["memory_ids"]))

    status = "passed"
    reasons: list[str] = []
    if request_failures:
        status = "failed"
        reasons.append("read-back requests failed")
    if mismatches:
        status = "failed"
        reasons.append("read-back parity mismatches detected")
    if len(verified) != len(export_batch["memory_ids"]):
        status = "failed"
        reasons.append("not every exported memory_id produced a readable stored record")
    if missing_reads or unexpected_reads:
        status = "failed"
        reasons.append("memory_id read-back set parity failed")

    return {
        "status": status,
        "reason": "; ".join(reasons) if reasons else None,
        "contract": EXPECTED_READ_CONTRACT,
        "read_url_template": read_url_template,
        "expected_count": len(export_batch["memory_ids"]),
        "verified_count": len(verified),
        "memory_ids_expected": sorted(export_batch["memory_ids"]),
        "memory_ids_verified": sorted(item["memory_id"] for item in verified),
        "missing_on_imlayer": missing_reads,
        "unexpected_on_imlayer": unexpected_reads,
        "checks_performed": [
            "response.success",
            "response.contract",
            "response.memory_id",
            "record.payload.memory_id",
            "record.payload.namespace",
            "record.payload.collection",
            "record.payload.schema_version",
            "record.payload.tenant_id",
            "record.payload.semantic_sha256 excluding decision_packet.freshness_hours",
            f"record.payload.decision_packet.freshness_hours drift <= {FRESHNESS_HOURS_TOLERANCE_HOURS} hours",
            "record.write_id parity against ingestion acknowledgement when available",
        ],
        "semantic_parity": {
            "status": "passed" if semantic_parity_failed == 0 else "failed",
            "excluded_fields": ["decision_packet.freshness_hours"],
            "passed_records": semantic_parity_passed,
            "failed_records": semantic_parity_failed,
        },
        "freshness_hours_drift_check": {
            "status": "passed" if freshness_outside_tolerance == 0 else "failed",
            "field": "decision_packet.freshness_hours",
            "tolerance_hours": FRESHNESS_HOURS_TOLERANCE_HOURS,
            "within_tolerance_records": freshness_within_tolerance,
            "outside_tolerance_records": freshness_outside_tolerance,
        },
        "verified_records": verified,
        "mismatches": mismatches,
        "request_failures": request_failures,
    }


def resolve_read_url(read_url_template: str, memory_id: str) -> str:
    encoded_memory_id = urllib.parse.quote(memory_id, safe="")
    if "{memory_id}" in read_url_template:
        return read_url_template.replace("{memory_id}", encoded_memory_id)
    return f"{read_url_template.rstrip('/')}/{encoded_memory_id}"


def decode_json_bytes(value: bytes) -> Any:
    text = value.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def read_memory_record(
    *,
    url: str,
    timeout_seconds: int,
    verify_tls: bool,
    auth_header: str,
    auth_scheme: str,
    auth_token: str,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
    }
    if auth_token:
        headers[auth_header] = f"{auth_scheme} {auth_token}"
    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    context = None
    if url.startswith("https://") and not verify_tls:
        context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
            context=context,
        ) as response:
            payload = decode_json_bytes(response.read())
    except urllib.error.HTTPError as exc:
        payload = decode_json_bytes(exc.read())
        raise ReconciliationFailure(
            f"read-back HTTP {exc.code} for {url}: {payload}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ReconciliationFailure(
            f"read-back transport error for {url}: {exc.reason}"
        ) from exc

    if not isinstance(payload, dict):
        raise ReconciliationFailure(f"read response must be a JSON object for {url}")
    return payload


def reconcile_batch(
    *,
    batch_id: str | None,
    batch_root: str | None,
    ingestion_manifest: str | None,
    ingestion_root: str | None,
    project_root: Path,
) -> dict[str, Any]:
    export_batch_root = resolve_export_batch_root(batch_id, batch_root)
    export_batch = load_export_batch(export_batch_root)
    resolved_batch_id = export_batch["batch_id"]
    ingestion_manifest_path = resolve_ingestion_manifest_path(
        resolved_batch_id,
        ingestion_manifest,
        ingestion_root,
    )
    ingestion_data = load_ingestion_manifest(ingestion_manifest_path)
    ingestion_batch_id = require_non_empty_string(
        "ingestion_manifest.batch_id",
        ingestion_data["manifest"].get("batch_id"),
    )
    if ingestion_batch_id != resolved_batch_id:
        raise ReconciliationFailure(
            f"ingestion manifest batch_id {ingestion_batch_id!r} does not match export batch_id {resolved_batch_id!r}"
        )

    write_ack_parity = build_write_ack_parity(export_batch, ingestion_data)
    true_read_back_parity = build_true_read_back_parity(export_batch, ingestion_data)

    final_status = "working"
    if write_ack_parity["status"] != "passed" or true_read_back_parity["status"] != "passed":
        final_status = "blocked"

    return {
        "schema_version": "trendatlas.imlayer.reconciliation_manifest.v1",
        "batch_id": resolved_batch_id,
        "export_batch_root": export_batch["batch_root"],
        "export_manifest_path": export_batch["manifest_path"],
        "ingestion_manifest_path": ingestion_data["manifest_path"],
        "write_ack_parity": write_ack_parity,
        "true_read_back_parity": true_read_back_parity,
        "final_status": final_status,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reconcile TrendAtlas imLayer export and ingestion artifacts for a batch.",
    )
    parser.add_argument("--batch-id")
    parser.add_argument("--batch-root")
    parser.add_argument("--ingestion-manifest")
    parser.add_argument("--ingestion-root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parent.parent
    try:
        report = reconcile_batch(
            batch_id=args.batch_id,
            batch_root=args.batch_root,
            ingestion_manifest=args.ingestion_manifest,
            ingestion_root=args.ingestion_root,
            project_root=project_root,
        )
    except ReconciliationFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(compact_json(report))
    write_ack_status = report["write_ack_parity"]["status"]
    read_back_status = report["true_read_back_parity"]["status"]
    if write_ack_status != "passed":
        return 1
    if read_back_status != "passed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
