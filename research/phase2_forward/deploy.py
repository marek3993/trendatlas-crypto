"""Narrow VPS-only preparatory deploy; no research worker or production start."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

OLD = Path('/opt/trendatlas-research/orchestration/causal-migration-20260928/research/causal_migration/runtime.py')
EXPECTED_OLD = '747fc938dccc139a39eb2f3b619a36bba3120fda9a6a20ce9957592dfa1227fc'
BASE = Path('/opt/trendatlas-phase2')
PAYLOAD = ['contract.json','research_contract.json','collector.py','admission.py','collector.service','collector.timer','DESIGN_AUDIT.md']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def deploy(source, release, apply=False):
    if os.name!='posix' or os.geteuid()!=0:raise ValueError('VPS_root_deployment_only')
    if not re.fullmatch('[0-9a-f]{40}',release):raise ValueError('exact_commit_required')
    source=source.resolve();package=source/'research/phase2_forward';patched=source/'research/causal_migration/runtime.py'
    hashes={name:sha(package/name) for name in PAYLOAD};hashes['runtime.py']=sha(patched)
    if sha(OLD)!=EXPECTED_OLD:raise ValueError('unexpected_installed_orchestration_hash')
    target=BASE/'releases'/release
    if target.exists() or (BASE/'current').exists():raise ValueError('existing_release_refuse_overwrite')
    contract=json.loads((package/'contract.json').read_text())
    if contract['admission']['implementation_ready'] or contract['forward']['current_nominees']:
        raise ValueError('preparation_only_no_search_or_nominees')
    plan={'release':release,'hashes':hashes,'old_runtime_sha256':EXPECTED_OLD,
          'changes':['isolated_public_collector','SEALED_ExecCondition_successful_skip'],
          'old_experiment_writes':False,'production_writes':False,'apply':apply}
    if not apply:print(json.dumps(plan,indent=2));return
    target.mkdir(parents=True)
    for name in PAYLOAD:shutil.copyfile(package/name,target/name)
    (target/'release.json').write_text(json.dumps(plan,indent=2)+'\n')
    for p in target.iterdir():p.chmod(0o444)
    target.chmod(0o555)
    (BASE/'current').symlink_to(target,target_is_directory=True)
    for name in ('service','timer'):
        shutil.copyfile(target/('collector.'+name),Path('/etc/systemd/system')/('trendatlas-phase2-collector.'+name))
    subprocess.run(['systemd-analyze','verify','/etc/systemd/system/trendatlas-phase2-collector.service',
                    '/etc/systemd/system/trendatlas-phase2-collector.timer'],check=True)
    backup=Path('/var/backups/trendatlas-phase2');backup.mkdir(parents=True,exist_ok=True)
    saved=backup/'pre-sealed-noop-runtime.py'
    with saved.open('xb') as f:f.write(OLD.read_bytes())
    temporary=OLD.with_name('runtime.py.phase2-new')
    with temporary.open('xb') as f:
        f.write(patched.read_bytes());f.flush();os.fsync(f.fileno())
    temporary.chmod(0o644);temporary.replace(OLD)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    # Existing admission verifies hashes before the successful skip. It cannot
    # start a SEALED worker; neither its timer nor its scientific state changes.
    subprocess.run(['systemctl','start','trendatlas-research-dispatch.service'],check=True)
    subprocess.run(['systemctl','enable','--now','trendatlas-phase2-collector.timer'],check=True)
    subprocess.run(['systemctl','start','trendatlas-phase2-collector.service'],check=True)
    print(json.dumps(plan,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--release',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args();deploy(a.source,a.release,a.apply)
