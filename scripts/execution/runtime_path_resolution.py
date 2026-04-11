from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable


REPO_ANCHORS = (
    "outputs",
    "source_of_truth",
    "data",
    "execution",
    "canonical",
    "configs",
    "scripts",
    "services",
    "tests",
)

WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def _normalized_text(raw_path: str | Path) -> str:
    return str(raw_path or "").strip()


def _is_windows_style_path(text: str) -> bool:
    return bool(text) and (
        "\\" in text
        or bool(WINDOWS_DRIVE_PATTERN.match(text))
        or text.startswith("\\\\")
    )


def _path_parts_for_detection(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    if _is_windows_style_path(text):
        return PureWindowsPath(text).parts
    if text.startswith("/"):
        return PurePosixPath(text).parts
    return Path(text).parts


def _relative_suffix_from_repo(text: str, root: Path) -> Path | None:
    parts = _path_parts_for_detection(text)
    if not parts:
        return None

    lowered_parts = [part.strip("\\/").lower() for part in parts]
    root_name = root.name.strip("\\/").lower()

    if root_name in lowered_parts:
        root_index = lowered_parts.index(root_name)
        suffix_parts = [part for part in parts[root_index + 1 :] if part.strip("\\/")]
        return Path(*suffix_parts) if suffix_parts else Path()

    for anchor in REPO_ANCHORS:
        if anchor in lowered_parts:
            anchor_index = lowered_parts.index(anchor)
            suffix_parts = [part for part in parts[anchor_index:] if part.strip("\\/")]
            return Path(*suffix_parts) if suffix_parts else Path()

    return None


def resolve_runtime_path(
    raw_path: str | Path,
    *,
    root: Path,
    context: str = "",
) -> tuple[Path, dict[str, Any]]:
    text = _normalized_text(raw_path)
    host_candidate = Path(text) if text else root

    reason = "repo_relative_path"
    resolved = root / host_candidate

    if not text:
        reason = "empty_path_defaulted_to_repo_root"
        resolved = root
    elif host_candidate.is_absolute():
        if host_candidate.exists():
            reason = "host_absolute_path"
            resolved = host_candidate
        else:
            repo_relative = _relative_suffix_from_repo(text, root)
            if repo_relative is not None:
                resolved = root / repo_relative
                reason = "missing_host_absolute_path_remapped_to_repo_root"
            else:
                reason = "missing_host_absolute_path_left_literal"
                resolved = host_candidate
    else:
        repo_relative = _relative_suffix_from_repo(text, root)
        if repo_relative is not None:
            resolved = root / repo_relative
            if _is_windows_style_path(text):
                reason = "windows_path_remapped_to_repo_root"
            elif repo_relative != host_candidate:
                reason = "repo_anchored_path_remapped_to_repo_root"
            else:
                reason = "repo_relative_path"
        elif _is_windows_style_path(text):
            resolved = host_candidate
            reason = "windows_path_left_literal_no_repo_mapping"

    diagnostic = {
        "context": context,
        "original_path": text,
        "resolved_path": str(resolved),
        "reason": reason,
        "exists": resolved.exists(),
    }
    return resolved, diagnostic


def resolve_registry_artifact_path(
    artifact_key: str,
    artifact_entry: dict[str, Any],
    *,
    root: Path,
    context: str = "",
) -> tuple[Path, dict[str, Any]]:
    canonical_raw = str(artifact_entry.get("canonical") or "").strip()
    canonical_path, canonical_diag = resolve_runtime_path(
        canonical_raw,
        root=root,
        context=context or artifact_key,
    )

    if canonical_path.exists():
        diagnostic = dict(canonical_diag)
        diagnostic["artifact_key"] = artifact_key
        diagnostic["selected_source"] = "canonical"
        diagnostic["selected_source_path"] = canonical_raw
        return canonical_path, diagnostic

    legacy_aliases = artifact_entry.get("legacy_aliases", [])
    if isinstance(legacy_aliases, Iterable) and not isinstance(legacy_aliases, (str, bytes)):
        for raw_alias in legacy_aliases:
            alias_text = str(raw_alias or "").strip()
            if not alias_text:
                continue
            alias_path, alias_diag = resolve_runtime_path(
                alias_text,
                root=root,
                context=f"{context or artifact_key}:legacy_alias",
            )
            if alias_path.exists():
                diagnostic = dict(alias_diag)
                diagnostic.update(
                    {
                        "artifact_key": artifact_key,
                        "original_path": canonical_raw,
                        "resolved_path": str(alias_path),
                        "reason": "canonical_missing_using_legacy_alias",
                        "selected_source": "legacy_alias",
                        "selected_source_path": alias_text,
                    }
                )
                return alias_path, diagnostic

    diagnostic = dict(canonical_diag)
    diagnostic["artifact_key"] = artifact_key
    diagnostic["selected_source"] = "canonical"
    diagnostic["selected_source_path"] = canonical_raw
    if legacy_aliases:
        diagnostic["reason"] = "canonical_missing_no_existing_legacy_alias"
    return canonical_path, diagnostic


def format_path_resolution_message(diagnostic: dict[str, Any]) -> str:
    parts = [
        "[PATH_RESOLUTION]",
        str(diagnostic.get("context") or diagnostic.get("artifact_key") or "path"),
        f"original={diagnostic.get('original_path') or ''}",
        f"resolved={diagnostic.get('resolved_path') or ''}",
        f"reason={diagnostic.get('reason') or 'unknown'}",
    ]
    selected_source_path = str(diagnostic.get("selected_source_path") or "").strip()
    if selected_source_path and selected_source_path != str(diagnostic.get("original_path") or "").strip():
        parts.append(f"selected_source={selected_source_path}")
    return " ".join(parts)
