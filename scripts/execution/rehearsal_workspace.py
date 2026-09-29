"""Copy runtime before rehearsal. No writable links to the canonical runtime."""
from __future__ import annotations
import hashlib
import json
import shutil
from pathlib import Path

EXCLUDED = {'.git', '.venv', '.runtime', 'node_modules', '__pycache__', '.next', '.env', '.env.local'}


def runtime_fingerprints(root: Path) -> dict[str, str]:
    result = {}
    for directory in ('data', 'outputs', 'execution/config'):
        for path in sorted((root / directory).rglob('*')):
            if path.is_file():
                with path.open('rb') as stream:
                    result[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def create_rehearsal(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('rehearsal must be outside the production tree')
    if destination.exists():
        raise ValueError('rehearsal destination must be new')
    before = runtime_fingerprints(source)
    # Dereference data links into independent copies; dependencies are excluded.
    shutil.copytree(source, destination, symlinks=False,
                    ignore=shutil.ignore_patterns(*EXCLUDED))
    after = runtime_fingerprints(source)
    if before != after or before != runtime_fingerprints(destination):
        raise RuntimeError('runtime changed during snapshot; staging is invalid')
    journal = destination / 'outputs/execution/execution_journal'
    for path in journal.rglob('*') if journal.exists() else []:
        if path.is_file(): path.chmod(0o440)
    manifest = {'source_root': str(source), 'staging_root': str(destination), 'files': before}
    (destination / '.rehearsal.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def assert_isolated_rehearsal(root: Path) -> None:
    marker = root / '.rehearsal.json'
    if not marker.is_file():
        raise RuntimeError('no-submit requires an isolated rehearsal workspace')
    manifest = json.loads(marker.read_text())
    source = Path(manifest['source_root']).resolve()
    if root.resolve() != Path(manifest['staging_root']).resolve() or root.resolve() == source:
        raise RuntimeError('rehearsal workspace binding mismatch')
    for directory in ('data', 'outputs', 'execution/config'):
        for path in (root / directory).rglob('*'):
            if path.is_symlink() or (path.is_file() and (source / path.relative_to(root)).exists()
                                     and path.samefile(source / path.relative_to(root))):
                raise RuntimeError('rehearsal contains a shared runtime file')
