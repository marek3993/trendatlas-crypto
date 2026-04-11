from __future__ import annotations

import platform
import socket
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "research_os_mvp.v1"
JOB_TYPE_VALIDATION_PLACEHOLDER = "validation_placeholder"
JOB_TYPE_ANALYZE_FAMILY_STATE = "analyze_family_state"
JOB_TYPE_PROPOSE_NEXT_MUTATION = "propose_next_mutation"
JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB = "submit_heavy_validation_job"
SAFE_JOB_TYPES = {
    JOB_TYPE_VALIDATION_PLACEHOLDER,
    JOB_TYPE_ANALYZE_FAMILY_STATE,
    JOB_TYPE_PROPOSE_NEXT_MUTATION,
    JOB_TYPE_SUBMIT_HEAVY_VALIDATION_JOB,
}
HEAVY_VALIDATION_STATUS_PREPARED_NOT_SUBMITTED = "prepared_not_submitted"
HEAVY_VALIDATION_STATUS_SUBMITTED = "submitted_for_heavy_validation"
HEAVY_VALIDATION_STATUS_QUEUE_PUBLISH_FAILED = "queue_publish_failed"
HEAVY_VALIDATION_STATUS_STARTED = "heavy_validation_started"
HEAVY_VALIDATION_STATUS_COMPLETED = "heavy_validation_completed"
HEAVY_VALIDATION_STATUS_FAILED = "heavy_validation_failed"
HEAVY_VALIDATION_STATUSES = {
    HEAVY_VALIDATION_STATUS_PREPARED_NOT_SUBMITTED,
    HEAVY_VALIDATION_STATUS_SUBMITTED,
    HEAVY_VALIDATION_STATUS_QUEUE_PUBLISH_FAILED,
    HEAVY_VALIDATION_STATUS_STARTED,
    HEAVY_VALIDATION_STATUS_COMPLETED,
    HEAVY_VALIDATION_STATUS_FAILED,
}
CRITIC_STATUS_STARTED = "critic_started"
CRITIC_STATUS_COMPLETED = "critic_completed"
CRITIC_STATUS_FAILED = "critic_failed"
CRITIC_STATUSES = {
    CRITIC_STATUS_STARTED,
    CRITIC_STATUS_COMPLETED,
    CRITIC_STATUS_FAILED,
}
GOVERNOR_STATUS_STARTED = "governor_started"
GOVERNOR_STATUS_COMPLETED = "governor_completed"
GOVERNOR_STATUS_FAILED = "governor_failed"
GOVERNOR_STATUSES = {
    GOVERNOR_STATUS_STARTED,
    GOVERNOR_STATUS_COMPLETED,
    GOVERNOR_STATUS_FAILED,
}
FAMILY_VERDICT_CONTINUE = "continue"
FAMILY_VERDICT_PAUSE = "pause"
FAMILY_VERDICT_STOP = "stop"
FAMILY_VERDICTS = {
    FAMILY_VERDICT_CONTINUE,
    FAMILY_VERDICT_PAUSE,
    FAMILY_VERDICT_STOP,
}
FAMILY_NEXT_ACTION_CONTINUE = "continue_family"
FAMILY_NEXT_ACTION_PAUSE = "pause_family"
FAMILY_NEXT_ACTION_STOP = "stop_family"
FAMILY_NEXT_ACTIONS = {
    FAMILY_NEXT_ACTION_CONTINUE,
    FAMILY_NEXT_ACTION_PAUSE,
    FAMILY_NEXT_ACTION_STOP,
}
FAMILY_LIFECYCLE_ACTIVE = "active"
FAMILY_LIFECYCLE_PAUSED = "paused"
FAMILY_LIFECYCLE_STOPPED = "stopped"
FAMILY_LIFECYCLE_STATES = {
    FAMILY_LIFECYCLE_ACTIVE,
    FAMILY_LIFECYCLE_PAUSED,
    FAMILY_LIFECYCLE_STOPPED,
}
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


def _dicts(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{label} must be a list")
    return [_dict(item, f"{label}[]") for item in value]


@dataclass(frozen=True)
class RuntimeConfig:
    schema_version: str
    role: str
    registry_path: str
    artifact_root: str
    runtime_root: str
    queue_backend: str
    redis_url: str
    streams: dict[str, str]
    consumer_group: str
    consumer_name: str
    openai: dict[str, Any]
    scanner_paths: list[str]
    scanner_env_keys: list[str]
    research_artifacts: list[dict[str, Any]] = field(default_factory=list)
    critic: dict[str, Any] = field(default_factory=dict)
    governor: dict[str, Any] = field(default_factory=dict)
    research_cycle: dict[str, Any] = field(default_factory=dict)
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
                "runtime_root",
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
            runtime_root=str(payload["runtime_root"]),
            queue_backend=str(payload["queue_backend"]),
            redis_url=str(payload["redis_url"]),
            streams={str(k): str(v) for k, v in _dict(payload["streams"], "runtime_config.streams").items()},
            consumer_group=str(payload["consumer_group"]),
            consumer_name=str(payload["consumer_name"]),
            openai=_dict(payload["openai"], "runtime_config.openai"),
            scanner_paths=_strings(payload["scanner_paths"], "runtime_config.scanner_paths"),
            scanner_env_keys=_strings(payload["scanner_env_keys"], "runtime_config.scanner_env_keys"),
            research_artifacts=_dicts(payload.get("research_artifacts", []), "runtime_config.research_artifacts"),
            critic=_dict(payload.get("critic", {}), "runtime_config.critic"),
            governor=_dict(payload.get("governor", {}), "runtime_config.governor"),
            research_cycle=_dict(payload.get("research_cycle", {}), "runtime_config.research_cycle"),
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
    source_artifact_ids: list[str] = field(default_factory=list)

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
            source_artifact_ids=_strings(payload.get("source_artifact_ids", []), "family_spec.source_artifact_ids"),
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
class MarketStateSnapshot:
    schema_version: str
    snapshot_id: str
    generated_at: str
    mode: str
    dev_only: bool
    non_authoritative: bool
    official_truth: bool
    source_artifact_count: int
    source_artifacts: list[dict[str, Any]]
    market_context: dict[str, Any]
    governance: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilyAttempt:
    artifact_id: str
    family_id: str
    path: str
    generated_at_utc: str
    verdict: str
    mechanism_id: str
    metrics: dict[str, Any]
    governance: dict[str, Any]
    lineage_refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilyStateSnapshot:
    schema_version: str
    snapshot_id: str
    generated_at: str
    mode: str
    dev_only: bool
    non_authoritative: bool
    official_truth: bool
    families: list[dict[str, Any]]
    artifact_count: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MutationProposal:
    schema_version: str
    proposal_id: str
    family_id: str
    mechanism_hypothesis: str
    mutation_target: dict[str, Any]
    expected_impact: dict[str, Any]
    stop_condition: str
    lineage_refs: dict[str, Any]
    dev_only: bool = True
    non_authoritative: bool = True
    official_truth: bool = False
    execution_allowed: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MutationProposal":
        _require(
            payload,
            (
                "schema_version",
                "proposal_id",
                "family_id",
                "mechanism_hypothesis",
                "mutation_target",
                "expected_impact",
                "stop_condition",
                "lineage_refs",
            ),
            "mutation_proposal",
        )
        expected_impact = _dict(payload["expected_impact"], "mutation_proposal.expected_impact")
        _require(
            expected_impact,
            ("churn", "switch_count", "dd", "net_benefit"),
            "mutation_proposal.expected_impact",
        )
        execution_allowed = bool(payload.get("execution_allowed", False))
        if execution_allowed:
            raise SchemaValidationError("mutation_proposal.execution_allowed must be false")
        if bool(payload.get("dev_only", True)) is not True:
            raise SchemaValidationError("mutation_proposal.dev_only must be true")
        if bool(payload.get("non_authoritative", True)) is not True:
            raise SchemaValidationError("mutation_proposal.non_authoritative must be true")
        if bool(payload.get("official_truth", False)) is not False:
            raise SchemaValidationError("mutation_proposal.official_truth must be false")
        return cls(
            schema_version=str(payload["schema_version"]),
            proposal_id=str(payload["proposal_id"]),
            family_id=str(payload["family_id"]),
            mechanism_hypothesis=str(payload["mechanism_hypothesis"]),
            mutation_target=_dict(payload["mutation_target"], "mutation_proposal.mutation_target"),
            expected_impact=expected_impact,
            stop_condition=str(payload["stop_condition"]),
            lineage_refs=_dict(payload["lineage_refs"], "mutation_proposal.lineage_refs"),
            dev_only=bool(payload.get("dev_only", True)),
            non_authoritative=bool(payload.get("non_authoritative", True)),
            official_truth=bool(payload.get("official_truth", False)),
            execution_allowed=execution_allowed,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HeavyValidationRequest:
    schema_version: str
    request_id: str
    proposal_id: str
    family_id: str
    source_mutation_proposal_artifact: str
    mutation_target: dict[str, Any]
    expected_impact: dict[str, Any]
    stop_condition: str
    constraints: dict[str, Any]
    status: str = HEAVY_VALIDATION_STATUS_PREPARED_NOT_SUBMITTED
    dev_only: bool = True
    non_authoritative: bool = True
    official_truth: bool = False
    execution_allowed: bool = False
    strategy_code_executed: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "HeavyValidationRequest":
        _require(
            payload,
            (
                "schema_version",
                "request_id",
                "proposal_id",
                "family_id",
                "source_mutation_proposal_artifact",
                "mutation_target",
                "expected_impact",
                "stop_condition",
                "constraints",
                "status",
            ),
            "heavy_validation_request",
        )
        status = str(payload["status"])
        if status not in HEAVY_VALIDATION_STATUSES:
            raise SchemaValidationError(f"heavy_validation_request unsupported status: {status}")
        constraints = _dict(payload["constraints"], "heavy_validation_request.constraints")
        if bool(payload.get("execution_allowed", False)):
            raise SchemaValidationError("heavy_validation_request.execution_allowed must be false")
        if bool(payload.get("strategy_code_executed", False)):
            raise SchemaValidationError("heavy_validation_request.strategy_code_executed must be false")
        if bool(payload.get("dev_only", True)) is not True:
            raise SchemaValidationError("heavy_validation_request.dev_only must be true")
        if bool(payload.get("non_authoritative", True)) is not True:
            raise SchemaValidationError("heavy_validation_request.non_authoritative must be true")
        if bool(payload.get("official_truth", False)) is not False:
            raise SchemaValidationError("heavy_validation_request.official_truth must be false")
        if bool(payload.get("strategy_advancement", False)) is not False:
            raise SchemaValidationError("heavy_validation_request.strategy_advancement must be false")
        if constraints.get("dev_only") is not True:
            raise SchemaValidationError("heavy_validation_request.constraints.dev_only must be true")
        if constraints.get("non_authoritative") is not True:
            raise SchemaValidationError("heavy_validation_request.constraints.non_authoritative must be true")
        if constraints.get("source_of_truth_mutation") is not False:
            raise SchemaValidationError("heavy_validation_request.constraints.source_of_truth_mutation must be false")
        if constraints.get("live_trading") is not False:
            raise SchemaValidationError("heavy_validation_request.constraints.live_trading must be false")
        if constraints.get("official_promotion_logic") is not False:
            raise SchemaValidationError("heavy_validation_request.constraints.official_promotion_logic must be false")
        if bool(constraints.get("strategy_advancement", False)) is not False:
            raise SchemaValidationError("heavy_validation_request.constraints.strategy_advancement must be false")
        return cls(
            schema_version=str(payload["schema_version"]),
            request_id=str(payload["request_id"]),
            proposal_id=str(payload["proposal_id"]),
            family_id=str(payload["family_id"]),
            source_mutation_proposal_artifact=str(payload["source_mutation_proposal_artifact"]),
            mutation_target=_dict(payload["mutation_target"], "heavy_validation_request.mutation_target"),
            expected_impact=_dict(payload["expected_impact"], "heavy_validation_request.expected_impact"),
            stop_condition=str(payload["stop_condition"]),
            constraints=constraints,
            status=status,
            dev_only=bool(payload.get("dev_only", True)),
            non_authoritative=bool(payload.get("non_authoritative", True)),
            official_truth=bool(payload.get("official_truth", False)),
            execution_allowed=bool(payload.get("execution_allowed", False)),
            strategy_code_executed=bool(payload.get("strategy_code_executed", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HeavyValidationResult:
    schema_version: str
    result_id: str
    request_id: str
    proposal_id: str
    job_id: str
    family_id: str
    status: str
    started_at: str
    finished_at: str
    adapter_id: str
    summary: dict[str, Any]
    artifact_refs: list[dict[str, Any]]
    dev_only: bool = True
    non_authoritative: bool = True
    official_truth: bool = False
    strategy_advancement: bool = False
    strategy_code_executed: bool = False
    live_trading: bool = False
    source_of_truth_mutation: bool = False
    official_promotion_logic: bool = False
    error: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "HeavyValidationResult":
        _require(
            payload,
            (
                "schema_version",
                "result_id",
                "request_id",
                "proposal_id",
                "job_id",
                "family_id",
                "status",
                "started_at",
                "finished_at",
                "adapter_id",
                "summary",
                "artifact_refs",
            ),
            "heavy_validation_result",
        )
        status = str(payload["status"])
        if status not in HEAVY_VALIDATION_STATUSES:
            raise SchemaValidationError(f"heavy_validation_result unsupported status: {status}")
        if status not in {HEAVY_VALIDATION_STATUS_COMPLETED, HEAVY_VALIDATION_STATUS_FAILED}:
            raise SchemaValidationError(f"heavy_validation_result unsupported terminal status: {status}")
        if bool(payload.get("dev_only", True)) is not True:
            raise SchemaValidationError("heavy_validation_result.dev_only must be true")
        if bool(payload.get("non_authoritative", True)) is not True:
            raise SchemaValidationError("heavy_validation_result.non_authoritative must be true")
        if bool(payload.get("official_truth", False)) is not False:
            raise SchemaValidationError("heavy_validation_result.official_truth must be false")
        if bool(payload.get("strategy_advancement", False)) is not False:
            raise SchemaValidationError("heavy_validation_result.strategy_advancement must be false")
        if bool(payload.get("strategy_code_executed", False)) is not False:
            raise SchemaValidationError("heavy_validation_result.strategy_code_executed must be false")
        if bool(payload.get("live_trading", False)) is not False:
            raise SchemaValidationError("heavy_validation_result.live_trading must be false")
        if bool(payload.get("source_of_truth_mutation", False)) is not False:
            raise SchemaValidationError("heavy_validation_result.source_of_truth_mutation must be false")
        if bool(payload.get("official_promotion_logic", False)) is not False:
            raise SchemaValidationError("heavy_validation_result.official_promotion_logic must be false")
        return cls(
            schema_version=str(payload["schema_version"]),
            result_id=str(payload["result_id"]),
            request_id=str(payload["request_id"]),
            proposal_id=str(payload["proposal_id"]),
            job_id=str(payload["job_id"]),
            family_id=str(payload["family_id"]),
            status=status,
            started_at=str(payload["started_at"]),
            finished_at=str(payload["finished_at"]),
            adapter_id=str(payload["adapter_id"]),
            summary=_dict(payload["summary"], "heavy_validation_result.summary"),
            artifact_refs=_dicts(payload["artifact_refs"], "heavy_validation_result.artifact_refs"),
            dev_only=bool(payload.get("dev_only", True)),
            non_authoritative=bool(payload.get("non_authoritative", True)),
            official_truth=bool(payload.get("official_truth", False)),
            strategy_advancement=bool(payload.get("strategy_advancement", False)),
            strategy_code_executed=bool(payload.get("strategy_code_executed", False)),
            live_trading=bool(payload.get("live_trading", False)),
            source_of_truth_mutation=bool(payload.get("source_of_truth_mutation", False)),
            official_promotion_logic=bool(payload.get("official_promotion_logic", False)),
            error=str(payload.get("error", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilyVerdict:
    schema_version: str
    verdict_id: str
    job_id: str
    result_id: str
    request_id: str
    proposal_id: str
    family_id: str
    mechanism_id: str
    status: str
    verdict: str
    verdict_reason: str
    key_metrics: dict[str, Any]
    next_action: str
    generated_at: str
    source_summary_path: str
    source_compare_path: str
    source_cost_metrics_path: str
    evidence: dict[str, Any] = field(default_factory=dict)
    dev_only: bool = True
    non_authoritative: bool = True
    official_truth: bool = False
    strategy_advancement: bool = False
    strategy_code_executed: bool = False
    live_trading: bool = False
    source_of_truth_mutation: bool = False
    official_promotion_logic: bool = False
    error: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FamilyVerdict":
        _require(
            payload,
            (
                "schema_version",
                "verdict_id",
                "job_id",
                "result_id",
                "request_id",
                "proposal_id",
                "family_id",
                "mechanism_id",
                "status",
                "verdict",
                "verdict_reason",
                "key_metrics",
                "next_action",
                "generated_at",
                "source_summary_path",
                "source_compare_path",
                "source_cost_metrics_path",
            ),
            "family_verdict",
        )
        status = str(payload["status"])
        verdict = str(payload["verdict"])
        next_action = str(payload["next_action"])
        key_metrics = _dict(payload["key_metrics"], "family_verdict.key_metrics")
        required_metrics = {
            "net_return",
            "dd",
            "trade_days_delta",
            "switch_count_delta",
            "turnover_pressure",
        }
        missing_metrics = sorted(required_metrics.difference(key_metrics))
        if missing_metrics:
            raise SchemaValidationError(f"family_verdict.key_metrics missing required keys: {missing_metrics}")
        if status not in CRITIC_STATUSES:
            raise SchemaValidationError(f"family_verdict unsupported status: {status}")
        if verdict not in FAMILY_VERDICTS:
            raise SchemaValidationError(f"family_verdict unsupported verdict: {verdict}")
        if next_action not in FAMILY_NEXT_ACTIONS:
            raise SchemaValidationError(f"family_verdict unsupported next_action: {next_action}")
        if "verdicts" in payload and len(list(payload.get("verdicts") or [])) != 1:
            raise SchemaValidationError("family_verdict must contain exactly one verdict")
        if bool(payload.get("dev_only", True)) is not True:
            raise SchemaValidationError("family_verdict.dev_only must be true")
        if bool(payload.get("non_authoritative", True)) is not True:
            raise SchemaValidationError("family_verdict.non_authoritative must be true")
        if bool(payload.get("official_truth", False)) is not False:
            raise SchemaValidationError("family_verdict.official_truth must be false")
        if bool(payload.get("strategy_advancement", False)) is not False:
            raise SchemaValidationError("family_verdict.strategy_advancement must be false")
        if bool(payload.get("strategy_code_executed", False)) is not False:
            raise SchemaValidationError("family_verdict.strategy_code_executed must be false")
        if bool(payload.get("live_trading", False)) is not False:
            raise SchemaValidationError("family_verdict.live_trading must be false")
        if bool(payload.get("source_of_truth_mutation", False)) is not False:
            raise SchemaValidationError("family_verdict.source_of_truth_mutation must be false")
        if bool(payload.get("official_promotion_logic", False)) is not False:
            raise SchemaValidationError("family_verdict.official_promotion_logic must be false")
        return cls(
            schema_version=str(payload["schema_version"]),
            verdict_id=str(payload["verdict_id"]),
            job_id=str(payload["job_id"]),
            result_id=str(payload["result_id"]),
            request_id=str(payload["request_id"]),
            proposal_id=str(payload["proposal_id"]),
            family_id=str(payload["family_id"]),
            mechanism_id=str(payload["mechanism_id"]),
            status=status,
            verdict=verdict,
            verdict_reason=str(payload["verdict_reason"]),
            key_metrics=key_metrics,
            next_action=next_action,
            generated_at=str(payload["generated_at"]),
            source_summary_path=str(payload["source_summary_path"]),
            source_compare_path=str(payload["source_compare_path"]),
            source_cost_metrics_path=str(payload["source_cost_metrics_path"]),
            evidence=_dict(payload.get("evidence", {}), "family_verdict.evidence"),
            dev_only=bool(payload.get("dev_only", True)),
            non_authoritative=bool(payload.get("non_authoritative", True)),
            official_truth=bool(payload.get("official_truth", False)),
            strategy_advancement=bool(payload.get("strategy_advancement", False)),
            strategy_code_executed=bool(payload.get("strategy_code_executed", False)),
            live_trading=bool(payload.get("live_trading", False)),
            source_of_truth_mutation=bool(payload.get("source_of_truth_mutation", False)),
            official_promotion_logic=bool(payload.get("official_promotion_logic", False)),
            error=str(payload.get("error", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilyGovernorState:
    schema_version: str
    state_id: str
    job_id: str
    verdict_id: str
    family_id: str
    mechanism_id: str
    lifecycle_state: str
    status: str
    attempt_count: int
    confirmatory_count: int
    last_verdict: str
    last_next_action: str
    last_updated_at: str
    source_verdict_artifact_path: str
    planning_eligible: bool
    governance: dict[str, Any] = field(default_factory=dict)
    dev_only: bool = True
    non_authoritative: bool = True
    official_truth: bool = False
    strategy_advancement: bool = False
    strategy_code_executed: bool = False
    live_trading: bool = False
    source_of_truth_mutation: bool = False
    official_promotion_logic: bool = False
    error: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FamilyGovernorState":
        _require(
            payload,
            (
                "schema_version",
                "state_id",
                "job_id",
                "verdict_id",
                "family_id",
                "mechanism_id",
                "lifecycle_state",
                "status",
                "attempt_count",
                "confirmatory_count",
                "last_verdict",
                "last_next_action",
                "last_updated_at",
                "source_verdict_artifact_path",
                "planning_eligible",
            ),
            "family_governor_state",
        )
        lifecycle_state = str(payload["lifecycle_state"])
        status = str(payload["status"])
        last_verdict = str(payload["last_verdict"])
        last_next_action = str(payload["last_next_action"])
        if lifecycle_state not in FAMILY_LIFECYCLE_STATES:
            raise SchemaValidationError(f"family_governor_state unsupported lifecycle_state: {lifecycle_state}")
        if status not in GOVERNOR_STATUSES:
            raise SchemaValidationError(f"family_governor_state unsupported status: {status}")
        if last_verdict not in FAMILY_VERDICTS:
            raise SchemaValidationError(f"family_governor_state unsupported last_verdict: {last_verdict}")
        if last_next_action not in FAMILY_NEXT_ACTIONS:
            raise SchemaValidationError(f"family_governor_state unsupported last_next_action: {last_next_action}")
        if int(payload["attempt_count"]) < 0:
            raise SchemaValidationError("family_governor_state.attempt_count must be non-negative")
        if int(payload["confirmatory_count"]) < 0:
            raise SchemaValidationError("family_governor_state.confirmatory_count must be non-negative")
        if bool(payload["planning_eligible"]) is not (lifecycle_state == FAMILY_LIFECYCLE_ACTIVE):
            raise SchemaValidationError("family_governor_state.planning_eligible must match lifecycle_state")
        if bool(payload.get("dev_only", True)) is not True:
            raise SchemaValidationError("family_governor_state.dev_only must be true")
        if bool(payload.get("non_authoritative", True)) is not True:
            raise SchemaValidationError("family_governor_state.non_authoritative must be true")
        if bool(payload.get("official_truth", False)) is not False:
            raise SchemaValidationError("family_governor_state.official_truth must be false")
        if bool(payload.get("strategy_advancement", False)) is not False:
            raise SchemaValidationError("family_governor_state.strategy_advancement must be false")
        if bool(payload.get("strategy_code_executed", False)) is not False:
            raise SchemaValidationError("family_governor_state.strategy_code_executed must be false")
        if bool(payload.get("live_trading", False)) is not False:
            raise SchemaValidationError("family_governor_state.live_trading must be false")
        if bool(payload.get("source_of_truth_mutation", False)) is not False:
            raise SchemaValidationError("family_governor_state.source_of_truth_mutation must be false")
        if bool(payload.get("official_promotion_logic", False)) is not False:
            raise SchemaValidationError("family_governor_state.official_promotion_logic must be false")
        return cls(
            schema_version=str(payload["schema_version"]),
            state_id=str(payload["state_id"]),
            job_id=str(payload["job_id"]),
            verdict_id=str(payload["verdict_id"]),
            family_id=str(payload["family_id"]),
            mechanism_id=str(payload["mechanism_id"]),
            lifecycle_state=lifecycle_state,
            status=status,
            attempt_count=int(payload["attempt_count"]),
            confirmatory_count=int(payload["confirmatory_count"]),
            last_verdict=last_verdict,
            last_next_action=last_next_action,
            last_updated_at=str(payload["last_updated_at"]),
            source_verdict_artifact_path=str(payload["source_verdict_artifact_path"]),
            planning_eligible=bool(payload["planning_eligible"]),
            governance=_dict(payload.get("governance", {}), "family_governor_state.governance"),
            dev_only=bool(payload.get("dev_only", True)),
            non_authoritative=bool(payload.get("non_authoritative", True)),
            official_truth=bool(payload.get("official_truth", False)),
            strategy_advancement=bool(payload.get("strategy_advancement", False)),
            strategy_code_executed=bool(payload.get("strategy_code_executed", False)),
            live_trading=bool(payload.get("live_trading", False)),
            source_of_truth_mutation=bool(payload.get("source_of_truth_mutation", False)),
            official_promotion_logic=bool(payload.get("official_promotion_logic", False)),
            error=str(payload.get("error", "")),
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
class ResearchCycleSummary:
    schema_version: str
    cycle_id: str
    started_at: str
    completed_at: str
    planner_jobs_count: int
    executed_steps: list[str]
    family_ids_touched: list[str]
    final_status: str
    final_governor_states: list[dict[str, Any]]
    produced_artifacts: list[dict[str, Any]]
    errors: list[str]
    dev_only: bool = True
    non_authoritative: bool = True
    official_truth: bool = False
    strategy_advancement: bool = False
    live_trading: bool = False
    source_of_truth_mutation: bool = False
    official_promotion_logic: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchCycleSummary":
        _require(
            payload,
            (
                "schema_version",
                "cycle_id",
                "started_at",
                "completed_at",
                "planner_jobs_count",
                "executed_steps",
                "family_ids_touched",
                "final_status",
                "final_governor_states",
                "produced_artifacts",
                "errors",
            ),
            "research_cycle_summary",
        )
        if int(payload["planner_jobs_count"]) > 1:
            raise SchemaValidationError("research_cycle_summary.planner_jobs_count must be <= 1")
        if bool(payload.get("dev_only", True)) is not True:
            raise SchemaValidationError("research_cycle_summary.dev_only must be true")
        if bool(payload.get("non_authoritative", True)) is not True:
            raise SchemaValidationError("research_cycle_summary.non_authoritative must be true")
        if bool(payload.get("official_truth", False)) is not False:
            raise SchemaValidationError("research_cycle_summary.official_truth must be false")
        if bool(payload.get("strategy_advancement", False)) is not False:
            raise SchemaValidationError("research_cycle_summary.strategy_advancement must be false")
        if bool(payload.get("live_trading", False)) is not False:
            raise SchemaValidationError("research_cycle_summary.live_trading must be false")
        if bool(payload.get("source_of_truth_mutation", False)) is not False:
            raise SchemaValidationError("research_cycle_summary.source_of_truth_mutation must be false")
        if bool(payload.get("official_promotion_logic", False)) is not False:
            raise SchemaValidationError("research_cycle_summary.official_promotion_logic must be false")
        return cls(
            schema_version=str(payload["schema_version"]),
            cycle_id=str(payload["cycle_id"]),
            started_at=str(payload["started_at"]),
            completed_at=str(payload["completed_at"]),
            planner_jobs_count=int(payload["planner_jobs_count"]),
            executed_steps=_strings(payload["executed_steps"], "research_cycle_summary.executed_steps"),
            family_ids_touched=_strings(payload["family_ids_touched"], "research_cycle_summary.family_ids_touched"),
            final_status=str(payload["final_status"]),
            final_governor_states=_dicts(payload["final_governor_states"], "research_cycle_summary.final_governor_states"),
            produced_artifacts=_dicts(payload["produced_artifacts"], "research_cycle_summary.produced_artifacts"),
            errors=_strings(payload["errors"], "research_cycle_summary.errors"),
            dev_only=bool(payload.get("dev_only", True)),
            non_authoritative=bool(payload.get("non_authoritative", True)),
            official_truth=bool(payload.get("official_truth", False)),
            strategy_advancement=bool(payload.get("strategy_advancement", False)),
            live_trading=bool(payload.get("live_trading", False)),
            source_of_truth_mutation=bool(payload.get("source_of_truth_mutation", False)),
            official_promotion_logic=bool(payload.get("official_promotion_logic", False)),
        )

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
        job_type = str(payload["job_type"])
        if job_type not in SAFE_JOB_TYPES:
            raise SchemaValidationError(f"worker_job unsupported safe job_type: {job_type}")
        return cls(
            schema_version=str(payload["schema_version"]),
            job_id=str(payload["job_id"]),
            job_type=job_type,
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
