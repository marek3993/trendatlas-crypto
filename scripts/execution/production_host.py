"""Fail-closed admission of a canonical production host; no exchange operations."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import stat
from pathlib import Path


class HostAdmissionError(PermissionError):
    pass


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_evidence(evidence: dict, *, system: str, machine: str,
                      python_version: str, packages: dict, machine_id: str,
                      root: Path, require_active: bool = True) -> None:
    contract = json.loads((root / 'source_of_truth/production_host_contract.json').read_text())
    if f'{system.lower()}/{machine.lower()}' not in contract['supported_platforms']:
        raise HostAdmissionError('unsupported production platform')
    if python_version != contract['python_version'] or any(
        packages.get(k) != v for k, v in contract['critical_python_packages'].items()
    ):
        raise HostAdmissionError('production dependency pin mismatch')
    if evidence.get('node_version') != contract['node_version']:
        raise HostAdmissionError('production Node pin mismatch')
    if evidence.get('machine_id') != machine_id or evidence.get('runtime_root') != str(root.resolve()):
        raise HostAdmissionError('production host binding mismatch')
    files = evidence.get('files', {})
    if not files or any(not isinstance(k, str) or Path(k).is_absolute() or '..' in Path(k).parts for k in files):
        raise HostAdmissionError('invalid runtime manifest')
    for relative, digest in files.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
            raise HostAdmissionError('runtime manifest mismatch')
    manifest_digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    replay = evidence.get('cross_arch_golden_replay', {})
    if (replay.get('status') != 'PASS' or replay.get('comparison') != 'exact'
            or replay.get('manifest_sha256') != manifest_digest
            or replay.get('platforms') != ['linux/aarch64', 'linux/x86_64']
            or not replay.get('result_sha256')):
        raise HostAdmissionError('cross architecture golden replay missing or unbound')
    if evidence.get('systemd_verified') is not True:
        raise HostAdmissionError('systemd runtime not validated')
    if require_active and (evidence.get('single_execution_host') != machine_id or evidence.get('activated_by_operator') is not True):
        raise HostAdmissionError('canonical host not activated by operator')


def require_canonical_host(env: dict) -> dict:
    # Platform values are measured here; legacy MRV1_RUNTIME_PLATFORM_* cannot spoof admission.
    evidence_path = Path('/etc/trendatlas-production/capabilities.json')
    for path in (evidence_path.parent, evidence_path):
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or path.is_symlink():
            raise HostAdmissionError('host admission evidence must be root owned and protected')
    root = Path(__file__).resolve().parents[2]
    contract = json.loads((root / 'source_of_truth/production_host_contract.json').read_text())
    evidence = json.loads(evidence_path.read_text())
    verify_systemd_evidence(evidence)
    validate_evidence(evidence, system=platform.system(), machine=platform.machine(),
        python_version=platform.python_version(),
        packages={k: importlib.metadata.version(k) for k in contract['critical_python_packages']},
        machine_id=Path('/etc/machine-id').read_text().strip(), root=root)
    return evidence


def verify_systemd_evidence(evidence: dict) -> None:
    units=evidence.get('systemd_files',{})
    required={'/etc/systemd/system/mrv1-production.service','/etc/systemd/system/mrv1-production.timer'}
    if not required.issubset(units): raise HostAdmissionError('systemd manifest is incomplete')
    for name,digest in units.items():
        path=Path(name)
        if path.parent != Path('/etc/systemd/system') or sha256(path)!=digest:
            raise HostAdmissionError('installed systemd unit drift')
