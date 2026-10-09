"""Install a new scheduler and broker; all predecessor releases/state stay intact."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
from .contract import load

PY='/opt/trendatlas-research/venvs/causal-v1/bin/python'
ROOT=Path('/var/lib/trendatlas-continuous-research')
MAILBOX=Path('/var/lib/trendatlas-continuous-mailbox')
WORKER='trendatlas-continuous-research'
BROKER='trendatlas-continuous-broker'
MODULES={'__init__.py','contract.py','common.py','ledger.py','schema.py','bootstrap.py','planner.py','broker.py','runtime.py','entry.py','deploy.py'}


def units(release):
    release=str(release).replace('\\','/');root=str(ROOT).replace('\\','/');mail=str(MAILBOX).replace('\\','/')
    entry=release+'/research/continuous_research/entry.py';c=load()
    deny=('-/opt/leadpilot -/var/lib/docker -/run/docker.sock -/opt/market_regime_v1 -/opt/home_automation '
          '-/opt/trendatlas-production -/var/lib/trendatlas-production -/etc/credstore -/etc/credstore.encrypted '
          '-/var/lib/trendatlas-phase2 -/var/lib/trendatlas-research-v2 -/var/lib/trendatlas-research-development '
          '-/var/lib/trendatlas-research/causal-v1 -/var/lib/trendatlas-anomaly-lab -/var/lib/trendatlas-discovery-evolution')
    common='''NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectProc=invisible
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
CapabilityBoundingSet=
AmbientCapabilities=
MemorySwapMax=0
UMask=0007
Nice=15
CPUWeight=5
Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
StandardOutput=journal
StandardError=journal
'''
    worker=f'''[Unit]
Description=TrendAtlas continuous exploratory discovery and evolution
After=local-fs.target
[Service]
Type=oneshot
User=trendatlas-continuous
Group=trendatlas-research
WorkingDirectory={release}
ExecStart={PY} -I -B {entry} worker --root {root} --mailbox {mail} --inputs {c['input_directory']} --bootstrap {release}/continuous-bootstrap.json
PrivateNetwork=true
RestrictAddressFamilies=AF_UNIX
ReadWritePaths={root} {mail}
InaccessiblePaths={deny} -/run/credentials
CPUQuota=60%
MemoryMax={c['resources']['memory_bytes']}
TasksMax=16
TimeoutStartSec={c['scheduler']['worker_seconds']}
Restart=on-failure
RestartSec=30s
{common}'''
    broker=f'''[Unit]
Description=TrendAtlas shared-budget compact DeepSeek proposal broker
After=network-online.target
[Service]
Type=oneshot
User=trendatlas-continuous-broker
Group=trendatlas-research
WorkingDirectory={release}
ExecStart={PY} -I -B {entry} broker --mailbox {mail}
LoadCredential=deepseek-key:/etc/credstore/trendatlas-research-deepseek
ReadWritePaths={mail}
InaccessiblePaths={deny} {root} {Path(c['input_directory']).parent.as_posix()}
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CPUQuota=10%
MemoryMax=256M
TasksMax=16
TimeoutStartSec=120
{common}'''
    out={WORKER+'.service':worker,BROKER+'.service':broker}
    for name,seconds in ((WORKER,c['scheduler']['timer_seconds']),(BROKER,10)):
        out[name+'.timer']=f'''[Unit]
Description=Continue TrendAtlas isolated {name}
[Timer]
OnBootSec=30s
OnUnitInactiveSec={seconds}s
AccuracySec=1s
RandomizedDelaySec=0
Unit={name}.service
[Install]
WantedBy=timers.target
'''
    return out


def predecessors():
    from research.anomaly_lab.deploy import existing_v2
    from research.discovery_evolution.runtime import audit
    from research.anomaly_lab.audit import audit as lab_audit
    c=load();a=audit(Path(c['predecessor_state']));b=lab_audit(Path('/var/lib/trendatlas-anomaly-lab'))
    return {'v2':existing_v2(),'successor_hash':a['last_event_hash'],'successor_counts':a['counts'],
            'lab_hash':b['last_event_hash'],'lab_counts':b['counts'],'legacy_api_calls':b['api_calls'],'legacy_api_tokens':b['native_tokens']}


def main(package):
    import pwd,grp
    if os.geteuid()!=0:raise ValueError('research_admin_required')
    if ROOT.exists() or MAILBOX.exists() or any(Path('/etc/systemd/system',n).exists() for n in units('/scope')):
        raise ValueError('existing_scheduler_never_overwritten')
    if not Path('/etc/credstore/trendatlas-research-deepseek').is_file():raise ValueError('research_credential_unavailable')
    package=Path(package);sha=hashlib.sha256(package.read_bytes()).hexdigest();c=load()
    release=Path('/opt/trendatlas-research/continuous/releases')/sha[:16]
    allowed={'source_of_truth/continuous_research_contract_v1.json','tests/test_continuous_research.py'}|{'research/continuous_research/'+n for n in MODULES}
    with zipfile.ZipFile(package) as z:
        if set(z.namelist())!=allowed or len(z.namelist())!=len(allowed):raise ValueError('package_scope')
        before=predecessors();shutil.copytree(Path(c['predecessor_release']),release)
        for name in z.namelist():
            target=release/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
    subprocess.run([PY,'-B','-c','from research.continuous_research.bootstrap import build;from research.continuous_research.common import atomic;atomic("continuous-bootstrap.json",build())'],cwd=release,check=True)
    gid=grp.getgrnam('trendatlas-research').gr_gid
    for username in ('trendatlas-continuous','trendatlas-continuous-broker'):
        try:pwd.getpwnam(username)
        except KeyError:subprocess.run(['useradd','--system','--no-create-home','--shell','/usr/sbin/nologin','--gid','trendatlas-research',username],check=True)
    for parent in (release.parent.parent,release.parent):parent.chmod(0o755)
    for p in (release,*release.rglob('*')):os.chown(p,0,gid);p.chmod(0o750 if p.is_dir() else 0o640)
    for root,user in ((ROOT,'trendatlas-continuous'),(MAILBOX,'trendatlas-continuous-broker')):
        root.mkdir();os.chown(root,pwd.getpwnam(user).pw_uid,gid);root.chmod(0o770)
    for name in ('requests','responses'):
        p=MAILBOX/name;p.mkdir();os.chown(p,pwd.getpwnam('trendatlas-continuous-broker').pw_uid,gid);p.chmod(0o770)
    subprocess.run(['sudo','-u','trendatlas-continuous',PY,'-B','-m','research.continuous_research.contract'],cwd=release,check=True)
    subprocess.run(['sudo','-u','trendatlas-continuous',PY,'-B','-m','unittest','tests.test_continuous_research','-q'],cwd=release,check=True)
    paths=[]
    for name,body in units(release).items():
        p=Path('/etc/systemd/system')/name;p.write_text(body);paths.append(str(p))
    subprocess.run(['systemd-analyze','verify',*paths],check=True)
    after=predecessors()
    if before!=after:raise ValueError('predecessor_changed')
    proof={'release':str(release),'package_sha256':sha,'bootstrap_sha256':hashlib.sha256((release/'continuous-bootstrap.json').read_bytes()).hexdigest(),
           'predecessors_before':before,'predecessors_after':after,'predecessors_unchanged':True,'units':paths,'credential_value_exposed':False}
    (ROOT/'deployment.json').write_text(json.dumps(proof,indent=2)+'\n')
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now',WORKER+'.timer',BROKER+'.timer'],check=True)
    print(json.dumps(proof))


if __name__=='__main__':main(__import__('sys').argv[1])
