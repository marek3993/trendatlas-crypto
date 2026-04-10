from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from services.shared.schemas import ArtifactRecord, SCHEMA_VERSION, utc_now_iso


class ArtifactWriter:
    """Writes dev-only Research OS artifacts below one configured root."""

    def __init__(self, artifact_root: str | Path) -> None:
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def write_json(
        self,
        relative_path: str | Path,
        payload: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRecord:
        path = self._resolve(relative_path)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str), encoding="utf-8")
        return self._record(path=path, fmt="json", row_count=None, metadata=dict(metadata or {}))

    def write_csv(
        self,
        relative_path: str | Path,
        rows: Iterable[Mapping[str, Any]],
        fieldnames: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRecord:
        path = self._resolve(relative_path)
        materialized_rows = [dict(row) for row in rows]
        columns = list(fieldnames or self._derive_fieldnames(materialized_rows))
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(materialized_rows)
        return self._record(path=path, fmt="csv", row_count=len(materialized_rows), metadata=dict(metadata or {}))

    def write_parquet(
        self,
        relative_path: str | Path,
        rows: Any,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRecord:
        path = self._resolve(relative_path)
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("Parquet writing requires pandas.") from exc

        frame = rows if hasattr(rows, "to_parquet") else pd.DataFrame(list(rows))
        frame.to_parquet(path, index=False)
        row_count = int(len(frame)) if hasattr(frame, "__len__") else None
        return self._record(path=path, fmt="parquet", row_count=row_count, metadata=dict(metadata or {}))

    def _resolve(self, relative_path: str | Path) -> Path:
        raw = Path(relative_path)
        if raw.is_absolute():
            raise ValueError("artifact paths must be relative to artifact_root")
        path = (self.artifact_root / raw).resolve()
        if not path.is_relative_to(self.artifact_root):
            raise ValueError(f"artifact path escapes artifact_root: {relative_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _record(self, path: Path, fmt: str, row_count: int | None, metadata: dict[str, Any]) -> ArtifactRecord:
        relative_id = path.relative_to(self.artifact_root).as_posix().replace("/", "__").replace(".", "_")
        return ArtifactRecord(
            schema_version=SCHEMA_VERSION,
            artifact_id=relative_id,
            path=str(path),
            format=fmt,
            created_at=utc_now_iso(),
            sha256=self._sha256(path),
            row_count=row_count,
            metadata=metadata,
        )

    @staticmethod
    def _derive_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
        fieldnames: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
        return fieldnames

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
