"""Install only new research units; predecessors remain immutable and untouched."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import sqlite3
from research.anomaly_lab.deploy import existing_v2
from .pool import bootstrap
from .contract import load

BASE=Path('/opt/trendatlas-research/anomaly-lab/releases/c23fc478faf29b8a')
PY='/opt/trendatlas-research/venvs/causal-v1/bin/python'
ROOT=Path('/var/lib/trendatlas-discovery-evolution')
LOGS=Path('/var/log/trendatlas-discovery-evolution')
UNIT='trendatlas-discovery-evolution'


def units(release):
    # Render Linux units consistently even when validated on Windows.
    release=str(release).replace('\\','/')
    root=str(ROOT).replace('\\','/');logs=str(LOGS).replace('\\','/')
    entry=release+'/research/discovery_evolution/entry.py'
    worker=f'''[Unit]
Description=TrendAtlas discovery to evolution research successors
After=local-fs.target
[Service]
Type=oneshot
User=trendatlas-evolution
Group=trendatlas-research
WorkingDirectory={release}
ExecStart={PY} -I -B {entry} --root {root} --inputs {load()['inputs']} --bootstrap {release}/bootstrap.json
PrivateNetwork=true
RestrictAddressFamilies=AF_UNIX
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectProc=invisible
CapabilityBoundingSet=
AmbientCapabilities=
ReadWritePaths={root} {logs}
InaccessiblePaths=-/opt/leadpilot -/var/lib/docker -/run/docker.sock -/opt/market_regime_v1 -/opt/home_automation -/opt/trendatlas-production -/var/lib/trendatlas-production -/etc/credstore -/etc/credstore.encrypted -/run/credentials -/var/lib/trendatlas-anomaly-lab -/var/lib/trendatlas-research-development -/var/lib/trendatlas-research-v2 -/var/lib/trendatlas-phase2 -/var/lib/trendatlas-research/causal-v1
Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
UMask=0007
CPUQuota=60%
CPUWeight=5
Nice=15
MemoryMax=3G
MemorySwapMax=0
TasksMax=16
TimeoutStartSec={load()['budgets']['worker_seconds']}
Restart=on-failure
RestartSec=30s
StandardOutput=append:{logs}/worker.log
StandardError=journal
'''
    timer=f'''[Unit]
Description=Continue isolated TrendAtlas discovery and evolution batches
[Timer]
OnBootSec=10s
OnUnitInactiveSec=30s
Unit={UNIT}.service
[Install]
WantedBy=timers.target
'''
    return {UNIT+'.service':worker,UNIT+'.timer':timer}


def main(package):
    import pwd,grp
    if os.geteuid()!=0:raise ValueError('research_admin_required')
    if ROOT.exists() or any(Path('/etc/systemd/system',n).exists() for n in (UNIT+'.service',UNIT+'.timer')):
        raise ValueError('existing_checkpoint_never_overwritten')
    package=Path(package); revision=hashlib.sha256(package.read_bytes()).hexdigest()[:16]
    release=Path('/opt/trendatlas-research/discovery-evolution/releases')/revision
    before=existing_v2(); shutil.copytree(BASE,release)
    allowed={'source_of_truth/discovery_evolution_contract_v2.json','tests/test_discovery_evolution.py'}
    with zipfile.ZipFile(package) as z:
        for name in z.namelist():
            if name not in allowed and not (name.startswith('research/discovery_evolution/') and name.endswith('.py')):raise ValueError('package_scope')
            target=(release/name).resolve()
            if not target.is_relative_to(release.resolve()):raise ValueError('package_escape')
        for name in z.namelist():
            target=release/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
    # Bootstrap uses THIS release's versioned policy, not the importing installer's policy.
    subprocess.run([PY,'-B','-c','import json;from pathlib import Path;from research.discovery_evolution.pool import bootstrap;Path("bootstrap.json").write_text(json.dumps(bootstrap(),sort_keys=True))'],cwd=release,check=True)
    boot=json.loads((release/'bootstrap.json').read_text())
    try:pwd.getpwnam('trendatlas-evolution')
    except KeyError:subprocess.run(['useradd','--system','--no-create-home','--shell','/usr/sbin/nologin','--gid','trendatlas-research','trendatlas-evolution'],check=True)
    uid=pwd.getpwnam('trendatlas-evolution').pw_uid;gid=grp.getgrnam('trendatlas-research').gr_gid
    for parent in (release.parent.parent,release.parent):parent.chmod(0o755)
    for p in (release,*release.rglob('*')):
        os.chown(p,0,gid);p.chmod(0o750 if p.is_dir() else 0o640)
    for p in (ROOT,LOGS):p.mkdir();os.chown(p,uid,gid);p.chmod(0o770)
    subprocess.run(['sudo','-u','trendatlas-evolution',PY,'-B','-m','research.discovery_evolution.contract'],cwd=release,check=True)
    subprocess.run(['sudo','-u','trendatlas-evolution',PY,'-B','-m','unittest','tests.test_discovery_evolution','-q'],cwd=release,check=True)
    paths=[]
    for name,body in units(release).items():
        p=Path('/etc/systemd/system')/name;p.write_text(body);paths.append(str(p))
    subprocess.run(['systemd-analyze','verify',*paths],check=True)
    if before!=existing_v2():raise ValueError('old_v2_changed')
    proof={'release':str(release),'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
           'bootstrap_sha256':hashlib.sha256((release/'bootstrap.json').read_bytes()).hexdigest(),'pool_digest':boot['pool_digest'],
           'pool_entries':len(boot['pool']),'old_v2_hashes':before,'predecessors_unchanged':True,'new_api_calls':0,'unit_paths':paths}
    (ROOT/'deployment.json').write_text(json.dumps(proof,indent=2))
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now',UNIT+'.timer'],check=True)
    print(json.dumps(proof))


if __name__=='__main__':main(sys.argv[1])


def repair_before_first_batch(package):
    """Retain the failed pre-result release/checkpoint; freeze a compatible repair."""
    if os.geteuid()!=0:raise ValueError('research_admin_required')
    db=sqlite3.connect('file:'+str(ROOT/'research.sqlite')+'?mode=ro',uri=True)
    try:
        from .runtime import TABLES
        if any(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in TABLES if t not in ('meta','events')):
            raise ValueError('repair_forbidden_after_first_batch')
    finally:db.close()
    prior=json.loads((ROOT/'deployment.json').read_text());old=Path(prior['release'])
    package=Path(package);sha=hashlib.sha256(package.read_bytes()).hexdigest()
    release=old.parent/sha[:16];before=existing_v2()
    changed=[]
    with zipfile.ZipFile(package) as z:
        for name in z.namelist():
            if (old/name).read_bytes()!=z.read(name):changed.append(name)
        if not set(changed).issubset({'research/discovery_evolution/runtime.py','research/discovery_evolution/deploy.py','tests/test_discovery_evolution.py'}):
            raise ValueError('pre_result_repair_scope')
        shutil.copytree(old,release)
        for name in changed:(release/name).write_bytes(z.read(name))
    import grp
    gid=grp.getgrnam('trendatlas-research').gr_gid
    for p in (release,*release.rglob('*')):os.chown(p,0,gid);p.chmod(0o750 if p.is_dir() else 0o640)
    subprocess.run(['sudo','-u','trendatlas-evolution',PY,'-B','-m','unittest','tests.test_discovery_evolution','-q'],cwd=release,check=True)
    paths=[]
    for name,body in units(release).items():
        p=Path('/etc/systemd/system')/name;p.write_text(body);paths.append(str(p))
    subprocess.run(['systemd-analyze','verify',*paths],check=True)
    if before!=existing_v2():raise ValueError('old_v2_changed')
    proof={'previous_release':str(old),'release':str(release),'package_sha256':sha,'changed_files':changed,
           'old_v2_unchanged':True,'bootstrap_bytes_unchanged':(old/'bootstrap.json').read_bytes()==(release/'bootstrap.json').read_bytes(),
           'results_before_repair':0,'checkpoint_retained':True}
    (ROOT/'repair-deployment.json').write_text(json.dumps(proof,indent=2))
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','start',UNIT+'.timer'],check=True)
    print(json.dumps(proof))
