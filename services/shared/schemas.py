from __future__ import annotations

import platform
import socket
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "research_os_mvp.v1"
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"


class SchemaValidationError(ValueError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _require(payload: Mapping[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise SchemaValidationError(f"{label} missing required keys: {missing}")


def _dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{label} must be an object")
    return dict(value)


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{label} must be a list")
    return [str(item) for item in value]


@dataclass(frozen=True)
class RuntimeConfig:
    schema_version: str
    role: str
    registry_path: str
    artifact_root: str
    queue_backend: str
    redis_url: str
    streams: dict[str, str]
    consumer_group: str
    consumer_name: str
    openai: dict[str, Any]
    scanner_paths: list[str]
    scanner_env_keys: list[str]
    max_jobs_per_cycle: int = 1

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RuntimeConfig":
        _require(
            payload,
            (
                "schema_version",
                "role",
                "registry_path",
                "artifact_root",
                "queue_backend",
                "redis_url",
                "streams",
                "consumer_group",
                "consumer_name",
                "openai",
                "scanner_paths",
                "scanner_env_keys",
            ),
            "runtime_config",
        )
        return cls(
            schema_version=str(payload["schema_version"]),
            role=str(payload["role"]),
            registry_path=str(payload["registry_path"]),
            artifact_root=str(payload["artifact_root"]),
            queue_backend=str(payload["queue_backend"]),
            redis_url=str(payload["redis_url"]),
            streams={str(k): str(v) for k, v in _dict(payload["streams"], "runtime_config.streams").items()},
            consumer_group=str(payload["consumer_group"]),
            consumer_name=str(payload["consumer_name"]),
            openai=_dict(payload["openai"], "runtime_config.openai"),
            scanner_paths=_strings(payload["scanner_paths"], "runtime_config.scanner_paths"),
            scanner_env_keys=_strings(payload["scanner_env_keys"], "runtime_config.scanner_env_keys"),
            max_jobs_per_cycle=int(payload.get("max_jobs_per_cycle", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilySpec:
    family_id: str
    owner: str
    status: str
    description: str
    allowed_job_types: list[str]
    default_priority: int = 5
    constraints: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FamilySpec":
        _require(payload, ("family_id", "owner", "status", "description", "allowed_job_types"), "family_spec")
        return cls(
            family_id=str(payload["family_id"]),
            owner=str(payload["owner"]),
            status=str(payload["status"]),
            description=str(payload["description"]),
            allowed_job_types=_strings(payload["allowed_job_types"], "family_spec.allowed_job_types"),
            default_priority=int(payload.get("default_priority", 5)),
            constraints=_dict(payload.get("constraints", {}), "family_spec.constraints"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilyRegistry:
    schema_version: str
    registry_id: str
    owner: str
    families: list[FamilySpec]
    constraints: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FamilyRegistry":
        _require(payload, ("schema_version", "registry_id", "owner", "families"), "family_registry")
        families = [FamilySpec.from_mapping(_dict(item, "family_registry.families[]")) for item in payload["families"]]
        return cls(
            schema_version=str(payload["schema_version"]),
            registry_id=str(payload["registry_id"]),
            owner=str(payload["owner"]),
            families=families,
            constraints=_dict(payload.get("constraints", {}), "family_registry.constraints"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_id": self.registry_id,
            "owner": self.owner,
            "families": [family.to_dict() for family in self.families],
            "constraints": dict(self.constraints),
        }


@dataclass(frozen=True)
class EnvironmentScan:
    schema_version: str
    scanner_id: str
    scanned_at: str
    role: str
    host: str
    platform: str
    python_executable: str
    python_version: str
    cwd: str
    project_root: str
    path_checks: dict[str, dict[str, Any]]
    environment: dict[str, str]
    notes: list[str] = field(default_factory=list)

    @classmethod
    def collect(
        cls,
        scanner_id: str,
        role: str,
        project_root: Path,
        paths: list[str],
        environment: dict[str, str],
        notes: list[str] | None = None,
    ) -> "EnvironmentScan":
        root = project_root.resolve()
        checks: dict[str, dict[str, Any]] = {}
        for raw_path in paths:
            path = (root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
            checks[raw_path] = {
                "resolved_path": str(path),
                "exists": path.exists(),
                "is_file": path.is_file(),
                "is_dir": path.is_dir(),
            }
        return cls(
            schema_version=SCHEMA_VERSION,
            scanner_id=scanner_id,
            scanned_at=utc_now_iso(),
            role=role,
            host=socket.gethostname(),
            platform=platform.platform(),
            python_executable=sys.executable,
            python_version=sys.version.split()[0],
            cwd=str(Path.cwd()),
            project_root=str(root),
            path_checks=checks,
            environment=dict(environment),
            notes=list(notes or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlannerInput:
    schema_version: str
    request_id: str
    family_registry: dict[str, Any]
    environment_scan: dict[str, Any]
    constraints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlannerOutput:
    schema_version: str
    planner_id: str
    created_at: str
    request_id: str
    jobs: list[dict[str, Any]]
    notes: list[str]
    openai_hook: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerJob:
    schema_version: str
    job_id: str
    job_type: str
    family_id: str
    priority: int
    payload: dict[str, Any]
    artifact_root: str
    created_at: str
    constraints: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "WorkerJob":
        _require(
            payload,
            ("schema_version", "job_id", "job_type", "family_id", "priority", "payload", "artifact_root", "created_at"),
            "worker_job",
        )
        return cls(
            schema_version=str(payload["schema_version"]),
            job_id=str(payload["job_id"]),
            job_type=str(payload["job_type"]),
            family_id=str(payload["family_id"]),
            priority=int(payload["priority"]),
            payload=_dict(payload["payload"], "worker_job.payload"),
            artifact_root=str(payload["artifact_root"]),
            created_at=str(payload["created_at"]),
            constraints=_dict(payload.get("constraints", {}), "worker_job.constraints"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerResult:
    schema_version: str
    job_id: str
    status: str
    started_at: str
    finished_at: str
    artifact_refs: list[dict[str, Any]]
    metrics: dict[str, Any]
    notes: list[str]
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactRecord:
    schema_version: str
    artifact_id: str
    path: str
    format: str
    created_at: str
    sha256: str
    row_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
