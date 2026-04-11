from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from services.shared.schemas import (
    HEAVY_VALIDATION_STATUS_SUBMITTED,
    JOB_STATUS_QUEUED,
    FamilyGovernorState,
    FamilyVerdict,
    HeavyValidationResult,
    WorkerJob,
    WorkerResult,
    utc_now_iso,
)


class RegistryService:
    """SQLite registry for local 24/7 Research OS job and artifact state."""

    def __init__(self, registry_path: str | Path) -> None:
        self.registry_path = Path(registry_path).resolve()
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    artifact_root TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    format TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS family_state (
                    family_id TEXT PRIMARY KEY,
                    last_artifact_id TEXT NOT NULL,
                    last_verdict TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    last_metrics_json TEXT NOT NULL,
                    lineage_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mutation_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    lineage_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proposal_events (
                    event_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    lineage_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS heavy_validation_requests (
                    request_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    queue_stream TEXT NOT NULL,
                    queue_message_id TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS heavy_validation_events (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS heavy_validation_results (
                    result_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    summary_path TEXT NOT NULL,
                    compare_path TEXT NOT NULL,
                    cost_metrics_path TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS family_verdicts (
                    verdict_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    mechanism_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    status TEXT NOT NULL,
                    verdict_json TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS family_verdict_events (
                    event_id TEXT PRIMARY KEY,
                    verdict_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS family_governor_state (
                    family_id TEXT PRIMARY KEY,
                    state_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    verdict_id TEXT NOT NULL,
                    mechanism_id TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    confirmatory_count INTEGER NOT NULL,
                    last_verdict TEXT NOT NULL,
                    last_next_action TEXT NOT NULL,
                    last_updated_at TEXT NOT NULL,
                    planning_eligible INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS family_governor_events (
                    event_id TEXT PRIMARY KEY,
                    state_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    verdict_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def upsert_job(self, job: WorkerJob, status: str = JOB_STATUS_QUEUED) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, job_type, family_id, status, priority, payload_json,
                    artifact_root, created_at, updated_at, result_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status,
                    priority=excluded.priority,
                    payload_json=excluded.payload_json,
                    artifact_root=excluded.artifact_root,
                    updated_at=excluded.updated_at
                """,
                (
                    job.job_id,
                    job.job_type,
                    job.family_id,
                    status,
                    job.priority,
                    json.dumps(job.to_dict(), sort_keys=True, default=str),
                    job.artifact_root,
                    job.created_at,
                    now,
                ),
            )
            conn.commit()

    def update_job_status(self, job_id: str, status: str, result: WorkerResult | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ?, result_json = COALESCE(?, result_json) WHERE job_id = ?",
                (
                    status,
                    utc_now_iso(),
                    json.dumps(result.to_dict(), sort_keys=True, default=str) if result else None,
                    job_id,
                ),
            )
            conn.commit()

    def record_artifact(self, job_id: str, artifact: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts (artifact_id, job_id, path, format, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(artifact["artifact_id"]),
                    job_id,
                    str(artifact["path"]),
                    str(artifact["format"]),
                    json.dumps(artifact.get("metadata", {}), sort_keys=True, default=str),
                    str(artifact["created_at"]),
                ),
            )
            conn.commit()

    def upsert_family_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._connect() as conn:
            for family in snapshot.get("families", []):
                conn.execute(
                    """
                    INSERT INTO family_state (
                        family_id, last_artifact_id, last_verdict, attempt_count,
                        last_metrics_json, lineage_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(family_id) DO UPDATE SET
                        last_artifact_id=excluded.last_artifact_id,
                        last_verdict=excluded.last_verdict,
                        attempt_count=excluded.attempt_count,
                        last_metrics_json=excluded.last_metrics_json,
                        lineage_json=excluded.lineage_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        str(family["family_id"]),
                        str(family.get("last_artifact_id", "")),
                        str(family.get("last_verdict", "")),
                        int(family.get("attempt_count", 0)),
                        json.dumps(family.get("last_metrics", {}), sort_keys=True, default=str),
                        json.dumps(family.get("lineage", []), sort_keys=True, default=str),
                        utc_now_iso(),
                    ),
                )
            conn.commit()

    def record_mutation_proposal(
        self,
        job_id: str,
        proposal: dict[str, Any],
        lineage: dict[str, Any],
        status: str,
    ) -> None:
        proposal_id = str(proposal["proposal_id"])
        family_id = str(proposal["family_id"])
        now = utc_now_iso()
        event = {
            "status": status,
            "proposal_id": proposal_id,
            "job_id": job_id,
            "family_id": family_id,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mutation_proposals (
                    proposal_id, job_id, family_id, status, proposal_json,
                    lineage_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    job_id=excluded.job_id,
                    family_id=excluded.family_id,
                    status=excluded.status,
                    proposal_json=excluded.proposal_json,
                    lineage_json=excluded.lineage_json,
                    updated_at=excluded.updated_at
                """,
                (
                    proposal_id,
                    job_id,
                    family_id,
                    status,
                    json.dumps(proposal, sort_keys=True, default=str),
                    json.dumps(lineage, sort_keys=True, default=str),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO proposal_events (
                    event_id, proposal_id, job_id, family_id, event_type,
                    event_json, lineage_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{job_id}_{status}",
                    proposal_id,
                    job_id,
                    family_id,
                    status,
                    json.dumps(event, sort_keys=True, default=str),
                    json.dumps(lineage, sort_keys=True, default=str),
                    now,
                ),
            )
            conn.commit()

    def record_heavy_validation_request(
        self,
        job_id: str,
        request: dict[str, Any],
        status: str,
        artifact_path: str = "",
        queue_stream: str = "",
        queue_message_id: str = "",
        error: str = "",
    ) -> None:
        request_id = str(request["request_id"])
        proposal_id = str(request["proposal_id"])
        family_id = str(request["family_id"])
        now = utc_now_iso()
        event = {
            "status": status,
            "request_id": request_id,
            "proposal_id": proposal_id,
            "job_id": job_id,
            "family_id": family_id,
            "artifact_path": artifact_path,
            "queue_stream": queue_stream,
            "queue_message_id": queue_message_id,
            "error": error,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO heavy_validation_requests (
                    request_id, proposal_id, job_id, family_id, status, request_json,
                    artifact_path, queue_stream, queue_message_id, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    proposal_id=excluded.proposal_id,
                    job_id=excluded.job_id,
                    family_id=excluded.family_id,
                    status=excluded.status,
                    request_json=excluded.request_json,
                    artifact_path=excluded.artifact_path,
                    queue_stream=excluded.queue_stream,
                    queue_message_id=excluded.queue_message_id,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    request_id,
                    proposal_id,
                    job_id,
                    family_id,
                    status,
                    json.dumps(request, sort_keys=True, default=str),
                    artifact_path,
                    queue_stream,
                    queue_message_id,
                    error,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO heavy_validation_events (
                    event_id, request_id, proposal_id, job_id, family_id,
                    event_type, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{request_id}_{status}",
                    request_id,
                    proposal_id,
                    job_id,
                    family_id,
                    status,
                    json.dumps(event, sort_keys=True, default=str),
                    now,
                ),
            )
            conn.commit()

    def record_heavy_validation_result(
        self,
        result: HeavyValidationResult,
        summary_path: str,
        compare_path: str,
        cost_metrics_path: str,
    ) -> None:
        payload = result.to_dict()
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO heavy_validation_results (
                    result_id, request_id, proposal_id, job_id, family_id, status,
                    result_json, summary_path, compare_path, cost_metrics_path,
                    error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(result_id) DO UPDATE SET
                    request_id=excluded.request_id,
                    proposal_id=excluded.proposal_id,
                    job_id=excluded.job_id,
                    family_id=excluded.family_id,
                    status=excluded.status,
                    result_json=excluded.result_json,
                    summary_path=excluded.summary_path,
                    compare_path=excluded.compare_path,
                    cost_metrics_path=excluded.cost_metrics_path,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    result.result_id,
                    result.request_id,
                    result.proposal_id,
                    result.job_id,
                    result.family_id,
                    result.status,
                    json.dumps(payload, sort_keys=True, default=str),
                    summary_path,
                    compare_path,
                    cost_metrics_path,
                    result.error,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE heavy_validation_requests
                SET status = ?, updated_at = ?, error = ?
                WHERE request_id = ?
                """,
                (result.status, now, result.error, result.request_id),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO heavy_validation_events (
                    event_id, request_id, proposal_id, job_id, family_id,
                    event_type, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{result.request_id}_{result.status}",
                    result.request_id,
                    result.proposal_id,
                    result.job_id,
                    result.family_id,
                    result.status,
                    json.dumps(payload, sort_keys=True, default=str),
                    now,
                ),
            )
            conn.commit()

    def record_heavy_validation_event(
        self,
        request_id: str,
        proposal_id: str,
        job_id: str,
        family_id: str,
        event_type: str,
        event: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE heavy_validation_requests
                SET status = ?, updated_at = ?
                WHERE request_id = ?
                """,
                (event_type, now, request_id),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO heavy_validation_events (
                    event_id, request_id, proposal_id, job_id, family_id,
                    event_type, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{request_id}_{event_type}",
                    request_id,
                    proposal_id,
                    job_id,
                    family_id,
                    event_type,
                    json.dumps(event, sort_keys=True, default=str),
                    now,
                ),
            )
            conn.commit()

    def record_family_verdict(
        self,
        verdict: FamilyVerdict,
        artifact_path: str,
    ) -> None:
        payload = verdict.to_dict()
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO family_verdicts (
                    verdict_id, job_id, result_id, request_id, proposal_id, family_id,
                    mechanism_id, verdict, status, verdict_json, artifact_path,
                    error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(verdict_id) DO UPDATE SET
                    job_id=excluded.job_id,
                    result_id=excluded.result_id,
                    request_id=excluded.request_id,
                    proposal_id=excluded.proposal_id,
                    family_id=excluded.family_id,
                    mechanism_id=excluded.mechanism_id,
                    verdict=excluded.verdict,
                    status=excluded.status,
                    verdict_json=excluded.verdict_json,
                    artifact_path=excluded.artifact_path,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    verdict.verdict_id,
                    verdict.job_id,
                    verdict.result_id,
                    verdict.request_id,
                    verdict.proposal_id,
                    verdict.family_id,
                    verdict.mechanism_id,
                    verdict.verdict,
                    verdict.status,
                    json.dumps(payload, sort_keys=True, default=str),
                    artifact_path,
                    verdict.error,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO family_verdict_events (
                    event_id, verdict_id, job_id, family_id, event_type, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{verdict.verdict_id}_{verdict.status}",
                    verdict.verdict_id,
                    verdict.job_id,
                    verdict.family_id,
                    verdict.status,
                    json.dumps(payload, sort_keys=True, default=str),
                    now,
                ),
            )
            conn.commit()

    def record_family_verdict_event(
        self,
        verdict_id: str,
        job_id: str,
        family_id: str,
        event_type: str,
        event: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO family_verdict_events (
                    event_id, verdict_id, job_id, family_id, event_type, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{verdict_id}_{event_type}",
                    verdict_id,
                    job_id,
                    family_id,
                    event_type,
                    json.dumps(event, sort_keys=True, default=str),
                    now,
                ),
            )
            conn.commit()

    def record_family_governor_state(
        self,
        state: FamilyGovernorState,
        artifact_path: str,
    ) -> None:
        payload = state.to_dict()
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO family_governor_state (
                    family_id, state_id, job_id, verdict_id, mechanism_id,
                    lifecycle_state, status, attempt_count, confirmatory_count,
                    last_verdict, last_next_action, last_updated_at, planning_eligible,
                    state_json, artifact_path, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(family_id) DO UPDATE SET
                    state_id=excluded.state_id,
                    job_id=excluded.job_id,
                    verdict_id=excluded.verdict_id,
                    mechanism_id=excluded.mechanism_id,
                    lifecycle_state=excluded.lifecycle_state,
                    status=excluded.status,
                    attempt_count=excluded.attempt_count,
                    confirmatory_count=excluded.confirmatory_count,
                    last_verdict=excluded.last_verdict,
                    last_next_action=excluded.last_next_action,
                    last_updated_at=excluded.last_updated_at,
                    planning_eligible=excluded.planning_eligible,
                    state_json=excluded.state_json,
                    artifact_path=excluded.artifact_path,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    state.family_id,
                    state.state_id,
                    state.job_id,
                    state.verdict_id,
                    state.mechanism_id,
                    state.lifecycle_state,
                    state.status,
                    state.attempt_count,
                    state.confirmatory_count,
                    state.last_verdict,
                    state.last_next_action,
                    state.last_updated_at,
                    1 if state.planning_eligible else 0,
                    json.dumps(payload, sort_keys=True, default=str),
                    artifact_path,
                    state.error,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO family_governor_events (
                    event_id, state_id, job_id, verdict_id, family_id,
                    event_type, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{state.state_id}_{state.status}",
                    state.state_id,
                    state.job_id,
                    state.verdict_id,
                    state.family_id,
                    state.status,
                    json.dumps(payload, sort_keys=True, default=str),
                    now,
                ),
            )
            conn.commit()

    def record_family_governor_event(
        self,
        state_id: str,
        job_id: str,
        verdict_id: str,
        family_id: str,
        event_type: str,
        event: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO family_governor_events (
                    event_id, state_id, job_id, verdict_id, family_id,
                    event_type, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{state_id}_{event_type}",
                    state_id,
                    job_id,
                    verdict_id,
                    family_id,
                    event_type,
                    json.dumps(event, sort_keys=True, default=str),
                    now,
                ),
            )
            conn.commit()

    def has_submitted_heavy_validation_request(self, exclude_request_id: str = "") -> bool:
        with self._connect() as conn:
            if exclude_request_id:
                row = conn.execute(
                    "SELECT 1 FROM heavy_validation_requests WHERE status = ? AND request_id != ? LIMIT 1",
                    (HEAVY_VALIDATION_STATUS_SUBMITTED, exclude_request_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM heavy_validation_requests WHERE status = ? LIMIT 1",
                    (HEAVY_VALIDATION_STATUS_SUBMITTED,),
                ).fetchone()
        return row is not None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_family_state(self, family_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM family_state WHERE family_id = ?", (family_id,)).fetchone()
        return dict(row) if row else None

    def get_family_governor_state(self, family_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM family_governor_state WHERE family_id = ?", (family_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM jobs"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def list_family_states(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM family_state ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_mutation_proposals(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mutation_proposals ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_heavy_validation_requests(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM heavy_validation_requests ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_heavy_validation_results(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM heavy_validation_results ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_family_verdicts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM family_verdicts ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_family_governor_states(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM family_governor_state ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.registry_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
