"""Install only isolated v2 research code, input mount and two research timers."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import shutil
import subprocess
import sys
import zipfile

def migrate_serialization(release,frozen,state,old_release):
    """Only the exact native-int checkpoint repair; never a general math migration."""
    import sqlite3
    for name in ('development','broker'):
        status=subprocess.run(['systemctl','is-active',f'trendatlas-phase2-v2-{name}.service'],capture_output=True,text=True).stdout.strip()
        if status not in ('inactive','failed'):raise RuntimeError('v2_migration_requires_drained_services')
    before=(old_release/'research/phase2_v2/engine.py').read_text()
    after=(release/'research/phase2_v2/engine.py').read_text()
    if before.replace("state['cooldown'][j]=i+7","state['cooldown'][int(j)]=int(i+7)")!=after:
        raise RuntimeError('migration_not_serialization_only')
    for name in ('runtime.py','market.py','contract.py'):
        if (old_release/'research/phase2_v2'/name).read_bytes()!=(release/'research/phase2_v2'/name).read_bytes():
            raise RuntimeError('migration_changes_other_evaluator_code')
    old_c=json.loads((old_release/'source_of_truth/phase2_v2_contract.json').read_text())
    new_c=json.loads((release/'source_of_truth/phase2_v2_contract.json').read_text());new_c.pop('checkpoint_serialization')
    if old_c!=new_c:raise RuntimeError('migration_changes_math_contract')
    unit=Path('/etc/systemd/system/trendatlas-phase2-v2-development.service').read_text()
    import re
    old_inputs=Path(re.search(r'--inputs (\S+)',unit).group(1))
    for name in ('identity_events.json','venue_notices.json','production_targets.csv'):
        if (old_inputs/name).read_bytes()!=(frozen/name).read_bytes():raise RuntimeError('migration_input_change')
    with zipfile.ZipFile(old_inputs/'spot_daily.zip') as a,zipfile.ZipFile(frozen/'spot_daily.zip') as b:
        if a.namelist()!=b.namelist() or any(a.read(n)!=b.read(n) for n in a.namelist()):raise RuntimeError('migration_price_change')
    sys.path.insert(0,str(release))
    from research.phase2_v2 import runtime
    db=runtime.connect(state)
    old_binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
    runtime.init_worker(runtime.load_market(frozen))
    checked=0
    for cid,origin,stress,body in db.execute('SELECT candidate_id,origin,stress,result FROM evaluations'):
        genes=json.loads(db.execute('SELECT genes FROM candidates WHERE id=?',(cid,)).fetchone()[0])
        rebuilt=runtime.job((cid,genes,origin,stress))[3]
        if runtime.canonical(rebuilt)!=body:raise RuntimeError('completed_result_parity_failure:'+cid+':'+stress)
        checked+=1
    backup_path=state/'serialization-checkpoint.sqlite'
    if backup_path.exists():raise RuntimeError('migration_backup_already_exists')
    backup=sqlite3.connect(backup_path);db.backup(backup);backup.close()
    new_binding=runtime.binding(frozen)
    cycle=json.loads(db.execute("SELECT value FROM meta WHERE key='cycle'").fetchone()[0])
    receipt={'cycle':cycle,'old_binding':old_binding,'new_binding':new_binding,
        'completed_evaluations_identical':checked,'candidate_or_evaluation_rows_changed':False,
        'reason':'native_integer_JSON_cooldown_key_only','old_inputs':str(old_inputs),'new_inputs':str(frozen)}
    with db:
        db.execute("INSERT INTO meta VALUES('serialization_binding_before',?)",(runtime.canonical(old_binding),))
        db.execute("UPDATE meta SET value=? WHERE key='binding'",(runtime.canonical(new_binding),))
        runtime.event(db,'serialization_binding_migrated',**receipt)
    runtime.atomic(state/'serialization-migration.json',receipt);db.close()
    print(json.dumps({'migration':receipt}),flush=True)

def main(package):
    package=Path(package)
    revision=hashlib.sha256(package.read_bytes()).hexdigest()[:16]
    root=Path('/opt/trendatlas-research/phase2-v2');release=root/'releases'/revision
    release.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(package) as z:
        for name in z.namelist():
            target=(release/name).resolve()
            if not target.is_relative_to(release.resolve()):raise RuntimeError('package_path')
        z.extractall(release)
    py='/opt/trendatlas-research/venvs/causal-v1/bin/python'
    subprocess.run([py,'-B','-m','research.phase2_v2.contract'],cwd=release,check=True)
    subprocess.run([py,'-B','-m','unittest','tests.test_phase2_v2','-q'],cwd=release,check=True)
    inputs=Path('/tmp/phase2-v2-20261005-inputs')
    if not (inputs/'public_manifest.json').exists():raise RuntimeError('public_acquisition_incomplete')
    input_bundle=inputs/('frozen-'+revision)
    if not (input_bundle/'manifest.json').exists():
        subprocess.run([py,'-B','-m','research.phase2_v2.freeze_inputs',str(inputs),str(input_bundle)],cwd=release,check=True)
    frozen=Path('/var/lib/trendatlas-research-v2-inputs')/revision
    frozen.parent.mkdir(exist_ok=True);shutil.copytree(input_bundle,frozen)
    uid=pwd.getpwnam('trendatlas-research').pw_uid;gid=grp.getgrnam('trendatlas-research').gr_gid
    state=Path('/var/lib/trendatlas-research-v2');logs=Path('/var/log/trendatlas-research-v2')
    for directory in (state,logs,state/'mailbox',state/'mailbox/requests',state/'mailbox/responses'):
        directory.mkdir(parents=True,exist_ok=True);os.chown(directory,uid,gid);directory.chmod(0o770)
    for parent in (root,root/'releases',release,frozen.parent):parent.chmod(0o755)
    for folder in (release,frozen):
        for p in [folder,*folder.rglob('*')]:
            os.chown(p,0,gid);p.chmod(0o750 if p.is_dir() else 0o640)
    if (state/'v2.sqlite').exists():
        migrate_serialization(release,frozen,state,(root/'current').resolve())
    link=root/'current.new';link.symlink_to(release);os.replace(link,root/'current')
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
UMask=0007
MemorySwapMax=0
Nice=15
CPUWeight=5
Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
'''
    deny='-/opt/leadpilot -/var/lib/docker -/run/docker.sock -/var/run/docker.sock -/opt/market_regime_v1 -/opt/home_automation -/opt/trendatlas-production -/var/lib/trendatlas-production -/etc/credstore -/etc/credstore.encrypted -/var/lib/trendatlas-research-development -/var/lib/trendatlas-research/causal-v1'
    worker=f'''[Unit]
Description=Isolated TrendAtlas Phase 2 v2 nested development evolution
After=local-fs.target
[Service]
Type=oneshot
User=trendatlas-research
Group=trendatlas-research
WorkingDirectory={release}
ExecCondition={py} -I -B {release}/research/phase2_v2/dispatch_condition.py --root {state} --fold-count 14
ExecStart={py} -I -B {release}/research/phase2_v2/run.py run --root {state} --inputs {frozen} --workers 2 --seconds 240
TimeoutStartSec=400
PrivateNetwork=true
RestrictAddressFamilies=AF_UNIX
CPUQuota=160%
MemoryMax=4096M
TasksMax=32
ReadWritePaths={state} {logs}
InaccessiblePaths={deny}
StandardOutput=append:{logs}/worker.log
StandardError=journal
{common}'''
    broker=f'''[Unit]
Description=Isolated compact Phase 2 v2 DeepSeek broker
After=network-online.target
[Service]
Type=oneshot
User=trendatlas-research-broker
Group=trendatlas-research
WorkingDirectory={release}
ExecCondition={py} -I -B {release}/research/phase2_v2/dispatch_condition.py --mailbox /var/lib/trendatlas-phase2-v2-mailbox
ExecStart={py} -I -B {release}/research/phase2_v2/run.py broker --mailbox /var/lib/trendatlas-phase2-v2-mailbox
LoadCredential=deepseek-key:/etc/credstore/trendatlas-research-deepseek
BindPaths={state}/mailbox:/var/lib/trendatlas-phase2-v2-mailbox
ReadWritePaths=/var/lib/trendatlas-phase2-v2-mailbox {logs}
InaccessiblePaths={deny} {state} {frozen.parent}
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
TimeoutStartSec=115
CPUQuota=20%
MemoryMax=512M
StandardOutput=append:{logs}/broker.log
StandardError=journal
{common}'''
    units={'trendatlas-phase2-v2-development.service':worker,'trendatlas-phase2-v2-broker.service':broker}
    for name,seconds in [('development',20),('broker',10)]:
        units[f'trendatlas-phase2-v2-{name}.timer']=f'''[Unit]
Description=Continue isolated Phase 2 v2 {name}
[Timer]
OnBootSec=2min
OnUnitInactiveSec={seconds}s
Unit=trendatlas-phase2-v2-{name}.service
[Install]
WantedBy=timers.target
'''
    for name,body in units.items():(Path('/etc/systemd/system')/name).write_text(body)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    # References must succeed before enabling either evolution timer.
    if (state/'references').exists() and not (state/'v2.sqlite').exists():
        failed=state/'preflight-attempts'/revision
        failed.parent.mkdir(exist_ok=True);shutil.move(str(state/'references'),str(failed))
        os.chown(failed,uid,gid)
    print(json.dumps({'release':str(release),'inputs':str(frozen),'state':str(state),'timers_enabled':False}),flush=True)
    subprocess.run(['sudo','-u','trendatlas-research',py,'-B','-m','research.phase2_v2.runtime','references','--root',str(state),'--inputs',str(frozen)],cwd=release,check=True)
    subprocess.run(['systemctl','enable','--now','trendatlas-phase2-v2-broker.timer','trendatlas-phase2-v2-development.timer'],check=True)
    print(json.dumps({'deployment_complete':True,'revision':revision,'release':str(release),'inputs':str(frozen)}),flush=True)

if __name__=='__main__':main(sys.argv[1])
