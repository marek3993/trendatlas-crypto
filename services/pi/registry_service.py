from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from services.shared.schemas import JOB_STATUS_QUEUED, WorkerJob, WorkerResult, utc_now_iso


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

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
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

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.registry_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
