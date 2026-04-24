from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_EXPORT_MANIFEST_SCHEMA = "trendatlas.imlayer.export_manifest.v1"
EXPECTED_INGESTION_MANIFEST_SCHEMA = "trendatlas.imlayer.ingestion_manifest.v1"
DEFAULT_EXPORTS_ROOT = Path("outputs/research_os/dev_only/imlayer_exports")
DEFAULT_INGESTION_ROOT = Path("outputs/research_os/dev_only/imlayer_ingestion")
EXPECTED_NAMESPACE = "trendatlas"
EXPECTED_COLLECTION = "decision_episodes"
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


def find_repo_read_contract_markers(project_root: Path) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for relative_root in READ_CONTRACT_SEARCH_ROOTS:
        root = project_root / relative_root
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in READ_CONTRACT_EXCLUDED_FILES:
                continue
            if path.suffix.lower() not in {".py", ".json", ".env", ".example", ".md", ".toml", ".yaml", ".yml"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for marker in READ_CONTRACT_MARKERS:
                if marker in text:
                    matches.append(
                        {
                            "path": path.relative_to(project_root).as_posix(),
                            "marker": marker,
                        }
                    )
    return matches


def find_local_persistence_candidates(project_root: Path) -> list[str]:
    outputs_root = project_root / "outputs" / "research_os" / "dev_only"
    if not outputs_root.exists():
        return []
    excluded_roots = {
        (outputs_root / "imlayer_exports").resolve(),
        (outputs_root / "imlayer_ingestion").resolve(),
    }
    candidates: list[str] = []
    for pattern in PERSISTENCE_CANDIDATE_PATTERNS:
        for path in outputs_root.rglob(pattern):
            resolved = path.resolve()
            if any(str(resolved).startswith(str(excluded_root)) for excluded_root in excluded_roots):
                continue
            lowered = path.as_posix().lower()
            if "imlayer" in lowered or "decision_episode" in lowered or "decision_episodes" in lowered:
                candidates.append(path.relative_to(project_root).as_posix())
    return sorted(set(candidates))


def load_build_live_episode_payload():
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
    return module.build_live_episode_payload


def build_expected_stored_records(export_batch: dict[str, Any]) -> list[dict[str, Any]]:
    build_live_episode_payload = load_build_live_episode_payload()
    expected_records: list[dict[str, Any]] = []
    for episode_entry in export_batch["episodes"]:
        try:
            stored_payload = build_live_episode_payload(episode_entry["episode"])
        except Exception as exc:
            expected_records.append(
                {
                    "memory_id": episode_entry["memory_id"],
                    "payload_sha256": None,
                    "derivation_error": str(exc),
                }
            )
            continue
        expected_records.append(
            {
                "memory_id": stored_payload["memory_id"],
                "namespace": stored_payload["namespace"],
                "collection": stored_payload["collection"],
                "entity_id": stored_payload["entity_id"],
                "episode_type": stored_payload["episode_type"],
                "payload_sha256": canonical_json_sha256(stored_payload),
            }
        )
    return expected_records


def build_minimal_read_surface_v1(export_batch: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "proposal_only",
        "why": (
            "TrendAtlas already has the exported source episodes and stable memory_ids; "
            "the thinnest missing capability is a read-by-memory_id surface that returns "
            "the exact stored record payload."
        ),
        "required_iml_change": {
            "type": "local_dev_http_read_endpoint",
            "env_var": "TRENDATLAS_IML_READ_URL",
            "method": "GET",
            "path_template": "/api/v1/reads/decision-episodes/{memory_id}",
            "query": {
                "namespace": EXPECTED_NAMESPACE,
                "collection": EXPECTED_COLLECTION,
            },
            "auth": {
                "header": "Authorization",
                "scheme": "Bearer",
            },
            "success_response": {
                "found": True,
                "memory_id": "<memory_id>",
                "namespace": EXPECTED_NAMESPACE,
                "collection": EXPECTED_COLLECTION,
                "record": "<exact stored decision episode payload object>",
            },
            "not_found_response": {
                "found": False,
                "memory_id": "<memory_id>",
                "namespace": EXPECTED_NAMESPACE,
                "collection": EXPECTED_COLLECTION,
            },
        },
        "trendatlas_verification_rule": {
            "for_each_memory_id": "call TRENDATLAS_IML_READ_URL with the memory_id path parameter",
            "required_checks": [
                "response.found == true",
                "response.memory_id matches exported memory_id",
                "response.namespace == trendatlas",
                "response.collection == decision_episodes",
                "sha256(canonical_json(response.record)) matches expected payload_sha256",
            ],
        },
        "batch_verification_targets": build_expected_stored_records(export_batch),
    }


def build_true_read_back_parity(
    project_root: Path,
    export_batch: dict[str, Any],
) -> dict[str, Any]:
    repo_markers = find_repo_read_contract_markers(project_root)
    persistence_candidates = find_local_persistence_candidates(project_root)
    minimal_read_surface_v1 = build_minimal_read_surface_v1(export_batch)
    if repo_markers:
        return {
            "status": "blocked",
            "blocker": "Read contract markers exist, but this repo does not define a supported true read-back verifier yet.",
            "read_contract_markers": repo_markers,
            "persistence_candidates": persistence_candidates,
            "minimal_read_surface_v1": minimal_read_surface_v1,
        }
    if persistence_candidates:
        return {
            "status": "blocked",
            "blocker": "Local persistence candidates exist, but no repo-defined imLayer read contract or storage parser is available for true read-back parity.",
            "read_contract_markers": repo_markers,
            "persistence_candidates": persistence_candidates,
            "minimal_read_surface_v1": minimal_read_surface_v1,
        }
    return {
        "status": "blocked",
        "blocker": (
            "No repo-local imLayer read contract was found and no workspace-local persisted imLayer store "
            "was discoverable outside export/ingestion artifacts, so true read-back parity cannot be proven."
        ),
        "read_contract_markers": repo_markers,
        "persistence_candidates": persistence_candidates,
        "minimal_read_surface_v1": minimal_read_surface_v1,
    }


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
    true_read_back_parity = build_true_read_back_parity(project_root, export_batch)

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
