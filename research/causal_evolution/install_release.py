"""Run as root on Pi ONLY after tests. Never pulls or writes production checkout.

Archive must contain research/causal_evolution only. Production is a read-only
source of specifically named Python dependencies, copied into an isolated venv.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

def command(args):
    return subprocess.run(args,check=True,capture_output=True,text=True).stdout

def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--sha256',required=True);p.add_argument('--commit',required=True);p.add_argument('--state-archive');p.add_argument('--prepare-only',action='store_true');a=p.parse_args()
    if os.geteuid()!=0:raise RuntimeError('Research release installer requires root')
    if not re.fullmatch('[a-f0-9]{40}',a.commit):raise ValueError('Exact commit required')
    archive=Path(a.archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=a.sha256:raise RuntimeError('Release transfer checksum mismatch')
    release=Path('/opt/trendatlas-research/releases')/a.commit
    release.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.name.startswith('research/causal_evolution/') or member.issym() or member.islnk() or '..' in Path(member.name).parts:raise ValueError('Non-research archive member')
            if not member.isfile() and not member.isdir():raise ValueError('Special archive member')
        tar.extractall(release,filter='data')
    venv=Path('/opt/trendatlas-research/venvs/causal-v1')
    if not (venv/'bin/python3').exists():command(['/usr/bin/python3','-m','venv','--without-pip',str(venv)])
    minor=f'python{sys.version_info.major}.{sys.version_info.minor}'
    origin=Path('/opt/market_regime_v1/.venv/lib')/minor/'site-packages';dest=venv/'lib'/minor/'site-packages'
    allowed=['numpy','numpy.libs','pandas','dateutil','six.py']
    allowed += sorted(p.name for pattern in ('numpy-*.dist-info','pandas-*.dist-info','python_dateutil-*.dist-info','six-*.dist-info') for p in origin.glob(pattern))
    for name in allowed:
        src=origin/name;dst=dest/name
        if not src.exists():raise RuntimeError('Missing allowlisted dependency '+name)
        if not dst.exists():
            if src.is_dir():shutil.copytree(src,dst,ignore=shutil.ignore_patterns('tests','__pycache__'))
            else:shutil.copyfile(src,dst)
    dependency_hashes={str(f.relative_to(dest)):hashlib.sha256(f.read_bytes()).hexdigest() for name in allowed for f in ([dest/name] if (dest/name).is_file() else (dest/name).rglob('*')) if f.is_file()}
    (release/'runtime_dependencies.json').write_text(json.dumps(dependency_hashes,indent=2)+'\n')
    base=Path('/var/lib/trendatlas-research/causal-v1');cycles=base/'cycles';cycle=cycles/'causal_nested_v1_20260927'
    cycle.mkdir(parents=True,exist_ok=True);(cycle/'mailbox').mkdir(exist_ok=True)
    if a.state_archive:
        if (cycle/'candidates.sqlite').exists():raise RuntimeError('Refuse to overwrite existing research results')
        with tarfile.open(a.state_archive) as tar:
            for m in tar.getmembers():
                if m.issym() or m.islnk() or '..' in Path(m.name).parts or Path(m.name).is_absolute():raise ValueError('Unsafe state archive')
            tar.extractall(cycle,filter='data')
    if not (base/'current').exists():(base/'current').symlink_to(cycle,target_is_directory=True)
    broker=Path('/var/lib/trendatlas-causal-broker/mailbox');broker.mkdir(parents=True,exist_ok=True)
    command(['chown','-R','trendatlas-research:trendatlas-research',str(base),str(broker.parent)])
    command(['chmod','750',str(base),str(broker.parent)])
    if a.prepare_only:
        print(json.dumps(dict(release=str(release),state=str(cycle),prepared=True,production_changed=False)));return
    sys.path.insert(0,str(release))
    from research.causal_evolution.deployment import units
    generated=units(str(release));backup=base/'deployment-backup'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());backup.mkdir(parents=True)
    # Only existing research admissions/worker are stopped for the cutover.
    command(['systemctl','stop','trendatlas-evolution-dispatch.timer'])
    command(['systemctl','stop','trendatlas-evolution-worker.service'])
    for name in generated:
        target=Path('/etc/systemd/system')/name
        if target.exists():shutil.copyfile(target,backup/name)
        target.write_text(generated[name])
    for relative in ('trendatlas-evolution-worker.service.d/20-memory-guard.conf','trendatlas-evolution-dispatch.service.d/20-sqlite-recovery.conf'):
        old=Path('/etc/systemd/system')/relative
        if old.exists():
            saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(old,saved);old.unlink()
    (base/'release.json').write_text(json.dumps(dict(commit=a.commit,release=str(release),archive_sha256=a.sha256,backup=str(backup)))+'\n')
    command(['systemd-analyze','verify']+[str(Path('/etc/systemd/system')/name) for name in generated])
    command(['systemctl','daemon-reload'])
    # Original dispatcher timer content/cadence stays unchanged. Production timer untouched.
    command(['systemctl','start','trendatlas-evolution-dispatch.timer'])
    command(['systemctl','enable','--now','trendatlas-causal-broker.timer','trendatlas-causal-maintain-dispatch.timer'])
    print(json.dumps(dict(release=str(release),state=str(cycle),research_units=list(generated),backup=str(backup),production_changed=False)))

if __name__=='__main__':main()
