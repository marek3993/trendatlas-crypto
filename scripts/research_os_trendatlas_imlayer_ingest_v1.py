from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_EXPORT_MANIFEST_SCHEMA = "trendatlas.imlayer.export_manifest.v1"
EXPECTED_EPISODE_SCHEMA = "trendatlas.imlayer.decision_episode.v1"
EXPECTED_PROJECT = "trendatlas-crypto"
EXPECTED_SOURCE_SYSTEM = "trendatlas-research-os"
EXPECTED_AUTH_HEADER = "Authorization"
EXPECTED_AUTH_SCHEME = "Bearer"
TARGET_SCHEMA_VERSION = "imlayer.trendatlas.v1"
TARGET_TENANT_ID = "research_os_prod"
TARGET_NAMESPACE = "trendatlas"
TARGET_COLLECTION = "decision_episodes"
TARGET_ENTITY_TYPE = "mechanism"
TARGET_EPISODE_TYPE = "heavy_validation_verdict"
TARGET_ENVIRONMENT = "dev"
DEFAULT_CONFIDENCE = 0.5
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_VERIFY_TLS = False
DEFAULT_WRITE_URL = "http://127.0.0.1:8000/api/v1/writes/decision-episodes"
DEFAULT_EXPORTS_ROOT = Path("outputs/research_os/dev_only/imlayer_exports")
DEFAULT_REPORTS_ROOT = Path("outputs/research_os/dev_only/imlayer_ingestion")
REQUIRED_KEYS = (
    "cycle_id",
    "family_id",
    "proposal_id",
    "request_id",
    "result_id",
    "verdict_id",
    "state_id",
)


class IngestionFailure(RuntimeError):
    def __init__(self, message: str, *, result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.result = result or {"status": "failed", "error": {"message": message}}


@dataclass(frozen=True)
class Config:
    mode: str
    write_url: str
    auth_token: str
    auth_header: str
    auth_scheme: str
    timeout_seconds: int
    verify_tls: bool

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "write_url": self.write_url,
            "auth_header": self.auth_header,
            "auth_scheme": self.auth_scheme,
            "auth_token_redacted": redact_token(self.auth_token),
            "payload_schema_version": TARGET_SCHEMA_VERSION,
            "payload_tenant_id": TARGET_TENANT_ID,
            "payload_namespace": TARGET_NAMESPACE,
            "payload_collection": TARGET_COLLECTION,
            "timeout_seconds": self.timeout_seconds,
            "verify_tls": self.verify_tls,
        }


def utc_now() -> datetime:
    return datetime.now(UTC)


def compact_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compact_json(payload) + "\n", encoding="utf-8")


def parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise IngestionFailure(f"Invalid boolean value: {raw!r}")


def redact_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        raise IngestionFailure(f"Env file not found: {path}")
    content = path.read_text(encoding="utf-8").lstrip("\ufeff")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise IngestionFailure(f"Invalid env line: {raw_line!r}")
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def config_from_env(mode: str, env: dict[str, str]) -> Config:
    if mode == "dry-run":
        return Config(
            mode=mode,
            write_url=env.get("TRENDATLAS_IML_WRITE_URL", DEFAULT_WRITE_URL),
            auth_token=env.get("TRENDATLAS_IML_AUTH_TOKEN", ""),
            auth_header=env.get("TRENDATLAS_IML_AUTH_HEADER", EXPECTED_AUTH_HEADER),
            auth_scheme=env.get("TRENDATLAS_IML_AUTH_SCHEME", EXPECTED_AUTH_SCHEME),
            timeout_seconds=int(env.get("TRENDATLAS_IML_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
            verify_tls=parse_bool(
                env.get(
                    "TRENDATLAS_IML_VERIFY_TLS",
                    "true" if DEFAULT_VERIFY_TLS else "false",
                )
            ),
        )

    required = (
        "TRENDATLAS_IML_WRITE_URL",
        "TRENDATLAS_IML_AUTH_TOKEN",
        "TRENDATLAS_IML_AUTH_HEADER",
        "TRENDATLAS_IML_AUTH_SCHEME",
        "TRENDATLAS_IML_TIMEOUT_SECONDS",
        "TRENDATLAS_IML_VERIFY_TLS",
    )
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise IngestionFailure(f"Missing required live env vars: {', '.join(missing)}")

    if env["TRENDATLAS_IML_AUTH_HEADER"] != EXPECTED_AUTH_HEADER:
        raise IngestionFailure(
            f"TRENDATLAS_IML_AUTH_HEADER must be {EXPECTED_AUTH_HEADER}"
        )
    if env["TRENDATLAS_IML_AUTH_SCHEME"] != EXPECTED_AUTH_SCHEME:
        raise IngestionFailure(
            f"TRENDATLAS_IML_AUTH_SCHEME must be {EXPECTED_AUTH_SCHEME}"
        )

    try:
        timeout_seconds = int(env["TRENDATLAS_IML_TIMEOUT_SECONDS"])
    except ValueError as exc:
        raise IngestionFailure("TRENDATLAS_IML_TIMEOUT_SECONDS must be an integer") from exc
    if timeout_seconds <= 0:
        raise IngestionFailure("TRENDATLAS_IML_TIMEOUT_SECONDS must be positive")

    return Config(
        mode=mode,
        write_url=env["TRENDATLAS_IML_WRITE_URL"],
        auth_token=env["TRENDATLAS_IML_AUTH_TOKEN"],
        auth_header=env["TRENDATLAS_IML_AUTH_HEADER"],
        auth_scheme=env["TRENDATLAS_IML_AUTH_SCHEME"],
        timeout_seconds=timeout_seconds,
        verify_tls=parse_bool(env["TRENDATLAS_IML_VERIFY_TLS"]),
    )


def require_non_empty_string(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionFailure(f"{label} must be a non-empty string")
    return value.strip()


def get_nested(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def compact_summary(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def normalize_string_list(label: str, value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise IngestionFailure(f"{label} must be a list")
    items: list[str] = []
    for item in value:
        text = compact_summary(item)
        if text:
            items.append(text)
    return items


def first_non_empty_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_utc_timestamp(raw: str, *, label: str) -> datetime:
    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise IngestionFailure(f"{label} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def resolve_decision_timestamp_utc(episode: dict[str, Any]) -> str:
    timestamp = first_non_empty_string(
        get_nested(episode, "episode_timestamps", "heavy_validation_finished_at"),
        get_nested(episode, "episode_timestamps", "critic_generated_at"),
        get_nested(episode, "episode_timestamps", "governor_updated_at"),
        episode.get("export_generated_at"),
    )
    if timestamp is None:
        raise IngestionFailure(
            "decision_timestamp_utc could not be resolved from episode timestamps"
        )
    return parse_utc_timestamp(
        timestamp,
        label="decision_timestamp_utc",
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_confidence(episode: dict[str, Any]) -> float:
    for candidate in (
        get_nested(episode, "critic_verdict", "confidence"),
        get_nested(episode, "governor_decision", "confidence"),
        get_nested(episode, "planner_proposal", "confidence"),
    ):
        if isinstance(candidate, (int, float)):
            return float(candidate)
    return DEFAULT_CONFIDENCE


def compute_freshness_hours(decision_timestamp_utc: str) -> float:
    decision_time = parse_utc_timestamp(
        decision_timestamp_utc,
        label="decision_timestamp_utc",
    )
    freshness_hours = (utc_now() - decision_time).total_seconds() / 3600.0
    return round(max(freshness_hours, 0.0), 6)


def extract_artifact_metadata(episode: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    artifact_refs = episode.get("artifact_refs")
    if artifact_refs is None:
        return [], {}
    if not isinstance(artifact_refs, dict):
        raise IngestionFailure("artifact_refs must be an object")

    artifact_paths: list[str] = []
    artifact_hashes: dict[str, str] = {}
    for artifact_key, artifact_payload in artifact_refs.items():
        if not isinstance(artifact_payload, dict):
            raise IngestionFailure(f"artifact_refs.{artifact_key} must be an object")
        path = artifact_payload.get("path")
        if isinstance(path, str) and path.strip():
            artifact_paths.append(path.strip())
        sha256 = artifact_payload.get("sha256")
        if isinstance(sha256, str) and sha256.strip():
            artifact_hashes[str(artifact_key)] = sha256.strip()
    return artifact_paths, artifact_hashes


def build_salient_facts(episode: dict[str, Any]) -> list[str]:
    compact_packet = episode.get("compact_packet")
    if compact_packet is None:
        return []
    if not isinstance(compact_packet, dict):
        raise IngestionFailure("compact_packet must be an object")
    facts: list[str] = []
    for value in compact_packet.values():
        text = compact_summary(value)
        if text:
            facts.append(text)
    return facts


def build_live_episode_payload(episode: dict[str, Any]) -> dict[str, Any]:
    memory_id = require_non_empty_string("memory_id", episode.get("memory_id"))
    entity_id = require_non_empty_string(
        "planner_proposal.mutation_target.target_id",
        get_nested(episode, "planner_proposal", "mutation_target", "target_id"),
    )
    decision_timestamp_utc = resolve_decision_timestamp_utc(episode)
    guardrail_breaches = normalize_string_list(
        "critic_verdict.guardrail_breaches",
        get_nested(episode, "critic_verdict", "guardrail_breaches"),
    )
    artifact_refs, artifact_hashes = extract_artifact_metadata(episode)

    tags = [
        value
        for value in (
            get_nested(episode, "keys", "family_id"),
            get_nested(episode, "critic_verdict", "verdict"),
            get_nested(episode, "governor_decision", "lifecycle_state"),
            "dev_only",
            "non_authoritative",
        )
        if isinstance(value, str) and value.strip()
    ]

    payload = {
        "schema_version": TARGET_SCHEMA_VERSION,
        "tenant_id": TARGET_TENANT_ID,
        "namespace": TARGET_NAMESPACE,
        "collection": TARGET_COLLECTION,
        "memory_id": memory_id,
        "entity_type": TARGET_ENTITY_TYPE,
        "entity_id": entity_id,
        "episode_type": TARGET_EPISODE_TYPE,
        "decision_timestamp_utc": decision_timestamp_utc,
        "decision": {
            "action": require_non_empty_string(
                "critic_verdict.next_action",
                get_nested(episode, "critic_verdict", "next_action"),
            ),
            "verdict": require_non_empty_string(
                "critic_verdict.verdict",
                get_nested(episode, "critic_verdict", "verdict"),
            ),
            "rationale_summary": compact_summary(
                get_nested(episode, "critic_verdict", "verdict_reason")
            ),
            "expected_impact_summary": compact_summary(
                get_nested(episode, "planner_proposal", "expected_impact")
            ),
            "stop_condition": compact_summary(
                get_nested(episode, "planner_proposal", "stop_condition")
            ),
            "confidence": resolve_confidence(episode),
        },
        "run_context": {
            "cycle_id": compact_summary(get_nested(episode, "keys", "cycle_id")),
            "family_id": compact_summary(get_nested(episode, "keys", "family_id")),
            "mechanism_id": entity_id,
            "proposal_id": compact_summary(get_nested(episode, "keys", "proposal_id")),
            "validation_job_id": compact_summary(
                get_nested(episode, "heavy_validation_verdict", "job_id")
            ),
            "critic_run_id": compact_summary(
                get_nested(episode, "critic_verdict", "job_id")
            ),
            "governor_run_id": compact_summary(
                get_nested(episode, "governor_decision", "job_id")
            ),
        },
        "outcome": {
            "status": compact_summary(
                get_nested(episode, "heavy_validation_verdict", "status")
            ),
            "actual_impact_summary": compact_summary(
                get_nested(episode, "critic_verdict", "key_metrics")
            ),
            "delta_summary": compact_summary(
                get_nested(episode, "critic_verdict", "net_first_rules")
            ),
            "cost_summary": compact_summary(
                get_nested(episode, "heavy_validation_verdict", "expected_impact")
            ),
            "failure_modes": guardrail_breaches,
            "contradiction_flags": guardrail_breaches,
        },
        "decision_packet": {
            "packet_text": require_non_empty_string(
                "retrieval_text",
                episode.get("retrieval_text"),
            ),
            "salient_facts": build_salient_facts(episode),
            "risk_flags": guardrail_breaches,
            "unknownness_score": 0.0,
            "contradiction_load": float(len(guardrail_breaches)),
            "freshness_hours": compute_freshness_hours(decision_timestamp_utc),
        },
        "metadata": {
            "authoritative": False,
            "environment": TARGET_ENVIRONMENT,
            "artifact_refs": artifact_refs,
            "artifact_hashes": artifact_hashes,
            "tags": tags,
        },
    }
    return payload


class HttpJsonWriter:
    def __init__(self, config: Config) -> None:
        self.config = config

    def write(
        self,
        batch_id: str,
        episode_path: Path,
        episode: dict[str, Any],
    ) -> dict[str, Any]:
        payload = build_live_episode_payload(episode)
        request_body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            self.config.auth_header: f"{self.config.auth_scheme} {self.config.auth_token}",
        }
        request = urllib.request.Request(
            self.config.write_url,
            data=request_body,
            headers=headers,
            method="POST",
        )
        request_summary = {
            "method": "POST",
            "url": self.config.write_url,
            "content_type": "application/json",
            "accept": "application/json",
            "auth_header": self.config.auth_header,
            "auth_scheme": self.config.auth_scheme,
            "auth_token_redacted": redact_token(self.config.auth_token),
            "body_bytes": len(request_body),
            "batch_id": batch_id,
            "memory_id": payload.get("memory_id"),
            "entity_id": payload.get("entity_id"),
            "episode_type": payload.get("episode_type"),
            "namespace": payload.get("namespace"),
            "collection": payload.get("collection"),
            "episode_path": episode_path.as_posix(),
        }
        context = None
        if self.config.write_url.startswith("https://") and not self.config.verify_tls:
            context = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.timeout_seconds,
                context=context,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                status = "deduplicated" if payload.get("deduplicated") else "ingested"
                return {
                    "status": status,
                    "request": request_summary,
                    "response": payload,
                }
        except urllib.error.HTTPError as exc:
            response_body = exc.read()
            payload = decode_json_bytes(response_body)
            result = {
                "status": "failed",
                "request": request_summary,
                "response": {
                    "http_status": exc.code,
                    **({"body": payload} if isinstance(payload, str) else payload),
                },
            }
            message = extract_failure_message(payload, fallback=f"HTTP {exc.code}")
            raise IngestionFailure(message, result=result) from exc
        except urllib.error.URLError as exc:
            result = {
                "status": "failed",
                "request": request_summary,
                "response": {
                    "transport_error": str(exc.reason),
                    "retryable": True,
                },
            }
            raise IngestionFailure(f"Transport error: {exc.reason}", result=result) from exc


def decode_json_bytes(value: bytes) -> Any:
    text = value.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def extract_failure_message(payload: Any, *, fallback: str) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            if code and message:
                return f"{code}: {message}"
            if code:
                return str(code)
            if message:
                return str(message)
    return fallback


def resolve_batch_root(batch_id: str | None, batch_root: str | None) -> Path:
    if batch_root:
        return Path(batch_root)
    if not batch_id:
        raise IngestionFailure("Either --batch-id or --batch-root must be provided")
    return DEFAULT_EXPORTS_ROOT / batch_id


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != EXPECTED_EXPORT_MANIFEST_SCHEMA:
        errors.append(
            f"manifest schema_version must be {EXPECTED_EXPORT_MANIFEST_SCHEMA}"
        )
    episode_paths = manifest.get("episode_paths")
    if not isinstance(episode_paths, list) or not episode_paths:
        errors.append("manifest episode_paths must contain at least one episode path")
    return errors


def validate_episode(episode: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if episode.get("schema_version") != EXPECTED_EPISODE_SCHEMA:
        errors.append(f"schema_version must be {EXPECTED_EPISODE_SCHEMA}")
    if episode.get("project") != EXPECTED_PROJECT:
        errors.append(f"project must be {EXPECTED_PROJECT}")
    if episode.get("source_system") != EXPECTED_SOURCE_SYSTEM:
        errors.append(f"source_system must be {EXPECTED_SOURCE_SYSTEM}")
    retrieval_text = episode.get("retrieval_text")
    if not isinstance(retrieval_text, str) or not retrieval_text.strip():
        errors.append("retrieval_text must be a non-empty string")

    governance = episode.get("governance")
    if not isinstance(governance, dict):
        errors.append("governance must be an object")
    else:
        governance_expectations = {
            "dev_only": True,
            "non_authoritative": True,
            "official_truth": False,
            "live_trading": False,
            "official_promotion_logic": False,
            "source_of_truth_mutation": False,
            "strategy_advancement": False,
            "planner_blocked_without_override": True,
            "fail_closed": True,
        }
        for key, expected in governance_expectations.items():
            if governance.get(key) is not expected:
                errors.append(f"governance.{key} must be {str(expected).lower()}")

    export_policy = episode.get("export_policy")
    if not isinstance(export_policy, dict):
        errors.append("export_policy must be an object")
    else:
        export_policy_expectations = {
            "mode": "dev_only_export_preparation",
            "dev_only": True,
            "non_authoritative": True,
            "official_truth": False,
            "live_trading": False,
            "fail_closed_export": True,
            "partial_episode_export_allowed": False,
            "live_integration": False,
        }
        for key, expected in export_policy_expectations.items():
            if export_policy.get(key) != expected:
                errors.append(f"export_policy.{key} must be {expected!r}")

    keys = episode.get("keys")
    if not isinstance(keys, dict):
        errors.append("keys must be an object")
    else:
        for key in REQUIRED_KEYS:
            value = keys.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"keys.{key} must be a non-empty string")
    return errors


def build_run_paths(batch_id: str) -> tuple[str, Path, Path]:
    run_id = utc_now().strftime("%Y%m%dT%H%M%SZ")
    run_root = DEFAULT_REPORTS_ROOT / batch_id / run_id
    manifest_path = run_root / "ingestion_manifest.json"
    return run_id, run_root, manifest_path


def load_batch(batch_root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    manifest_path = batch_root / "manifest.json"
    if not batch_root.exists():
        errors.append(f"Batch root not found: {batch_root.as_posix()}")
        return None, [], errors
    if not manifest_path.exists():
        errors.append(f"Batch manifest not found: {manifest_path.as_posix()}")
        return None, [], errors
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"Batch manifest is not valid JSON: {exc}")
        return None, [], errors

    errors.extend(validate_manifest(manifest))
    episodes: list[dict[str, Any]] = []
    episode_paths = manifest.get("episode_paths")
    if isinstance(episode_paths, list):
        for relative_path in episode_paths:
            episode_path = batch_root / str(relative_path)
            episode_record = {
                "path": episode_path,
                "relative_path": str(relative_path),
                "memory_id": None,
                "episode": None,
                "validation_errors": [],
                "load_error": None,
            }
            if not episode_path.exists():
                episode_record["load_error"] = f"Episode file not found: {episode_path.as_posix()}"
                episodes.append(episode_record)
                continue
            try:
                episode_payload = json.loads(episode_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                episode_record["load_error"] = f"Episode JSON is invalid: {exc}"
                episodes.append(episode_record)
                continue
            episode_record["episode"] = episode_payload
            episode_record["memory_id"] = episode_payload.get("memory_id")
            episode_record["validation_errors"] = validate_episode(episode_payload)
            episodes.append(episode_record)
    return manifest, episodes, errors


def summarize_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(results),
        "ingested": 0,
        "deduplicated": 0,
        "failed": 0,
        "not_attempted": 0,
    }
    for result in results:
        status = result.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def build_result(
    *,
    memory_id: str | None,
    episode_path: str,
    status: str,
    reason: str | None = None,
    request: dict[str, Any] | None = None,
    response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "memory_id": memory_id,
        "episode_path": episode_path,
        "status": status,
    }
    if reason is not None:
        result["reason"] = reason
    if request is not None:
        result["request"] = request
    if response is not None:
        result["response"] = response
    return result


def run_ingestion(args: argparse.Namespace) -> tuple[int, dict[str, Any], Path]:
    runtime_env = dict(os.environ)
    file_env = load_env_file(Path(args.env_file)) if args.env_file else {}
    merged_env = {**file_env, **runtime_env}
    config = config_from_env(args.mode, merged_env)

    batch_root = resolve_batch_root(args.batch_id, args.batch_root)
    batch_id = args.batch_id or Path(batch_root).name
    run_id, run_root, manifest_path = build_run_paths(batch_id)
    manifest, episodes, load_errors = load_batch(batch_root)

    results: list[dict[str, Any]] = []
    fatal_error: str | None = None

    if load_errors:
        fatal_error = "; ".join(load_errors)
    else:
        preflight_errors: list[str] = []
        for episode_record in episodes:
            if episode_record["load_error"]:
                preflight_errors.append(str(episode_record["load_error"]))
            if episode_record["validation_errors"]:
                joined = "; ".join(episode_record["validation_errors"])
                preflight_errors.append(
                    f"{episode_record['relative_path']}: {joined}"
                )
        if preflight_errors:
            fatal_error = "; ".join(preflight_errors)

    exit_code = 0
    if fatal_error is None:
        if args.mode == "dry-run":
            for episode_record in episodes:
                results.append(
                    build_result(
                        memory_id=episode_record["memory_id"],
                        episode_path=str(episode_record["relative_path"]),
                        status="not_attempted",
                        reason="dry-run validation passed; no live write attempted",
                    )
                )
        else:
            writer = HttpJsonWriter(config)
            for index, episode_record in enumerate(episodes):
                if index > 0 and results and results[-1]["status"] == "failed" and not args.continue_on_error:
                    results.append(
                        build_result(
                            memory_id=episode_record["memory_id"],
                            episode_path=str(episode_record["relative_path"]),
                            status="not_attempted",
                            reason="skipped after prior failure",
                        )
                    )
                    continue
                try:
                    write_result = writer.write(
                        batch_id,
                        Path(str(episode_record["relative_path"])),
                        episode_record["episode"],
                    )
                    results.append(
                        build_result(
                            memory_id=episode_record["memory_id"],
                            episode_path=str(episode_record["relative_path"]),
                            status=str(write_result["status"]),
                            request=write_result.get("request"),
                            response=write_result.get("response"),
                        )
                    )
                except IngestionFailure as exc:
                    failure = dict(exc.result)
                    failure["memory_id"] = episode_record["memory_id"]
                    failure["episode_path"] = str(episode_record["relative_path"])
                    results.append(failure)
                    exit_code = 1
                    if not args.continue_on_error:
                        for remaining in episodes[index + 1 :]:
                            results.append(
                                build_result(
                                    memory_id=remaining["memory_id"],
                                    episode_path=str(remaining["relative_path"]),
                                    status="not_attempted",
                                    reason="skipped after prior failure",
                                )
                            )
                        break
    else:
        exit_code = 1

    counts = summarize_counts(results)
    if fatal_error is not None:
        exit_code = 1

    manifest_payload = {
        "schema_version": "trendatlas.imlayer.ingestion_manifest.v1",
        "batch_id": batch_id,
        "run_id": run_id,
        "mode": args.mode,
        "status": "failed" if exit_code else "completed",
        "generated_at_utc": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "batch_root": batch_root.as_posix(),
        "report_root": run_root.as_posix(),
        "writer": config.summary(),
        "source_manifest": manifest,
        "counts": counts,
        "results": results,
        "errors": [fatal_error] if fatal_error else [],
    }
    write_json(manifest_path, manifest_payload)
    return exit_code, manifest_payload, manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest TrendAtlas dev-only decision episodes into imLayer V1.",
    )
    parser.add_argument("--mode", choices=("dry-run", "live"), default="dry-run")
    parser.add_argument("--env-file")
    parser.add_argument("--batch-id")
    parser.add_argument("--batch-root")
    parser.add_argument("--continue-on-error", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        exit_code, manifest_payload, manifest_path = run_ingestion(args)
    except IngestionFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(compact_json({"manifest_path": manifest_path.as_posix(), "status": manifest_payload["status"]}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
