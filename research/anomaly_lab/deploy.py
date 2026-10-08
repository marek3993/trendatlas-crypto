"""Install only a standalone Lab release and its new systemd units on the VPS."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile

BASE = Path('/opt/trendatlas-research/phase2-v2/releases/91237299dee6880e')
INPUTS = Path('/var/lib/trendatlas-research-v2-inputs/91237299dee6880e')
PYTHON = '/opt/trendatlas-research/venvs/causal-v1/bin/python'
ROOT = Path('/var/lib/trendatlas-anomaly-lab')
UNIT_NAMES = ('trendatlas-anomaly-lab.service', 'trendatlas-anomaly-lab.timer',
              'trendatlas-anomaly-broker.service', 'trendatlas-anomaly-broker.timer')


def checked(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def existing_v2():
    db = sqlite3.connect('file:/var/lib/trendatlas-research-v2/v2.sqlite?mode=ro', uri=True); db.execute('BEGIN')
    try:
        return {n: hashlib.sha256(json.dumps(db.execute('SELECT * FROM '+n+' ORDER BY 1').fetchall(), separators=(',', ':')).encode()).hexdigest()
                for n in ('meta', 'candidates', 'evaluations', 'members', 'stages', 'selections', 'test_books', 'terminal_test_failures', 'events')}
    finally: db.rollback(); db.close()


def units(release):
    logs = Path('/var/log/trendatlas-anomaly-lab'); entry = release/'research/anomaly_lab/entry.py'
    condition = release/'research/anomaly_lab/condition.py'; mailbox = '/var/lib/trendatlas-anomaly-mailbox'
    deny = ('-/opt/leadpilot -/var/lib/docker -/run/docker.sock -/var/run/docker.sock '
            '-/opt/market_regime_v1 -/opt/home_automation -/opt/trendatlas-production '
            '-/var/lib/trendatlas-production -/etc/credstore -/etc/credstore.encrypted '
            '-/var/lib/trendatlas-phase2 -/var/lib/trendatlas-research-v2 '
            '-/var/lib/trendatlas-research-development -/var/lib/trendatlas-research/causal-v1')
    common = '''NoNewPrivileges=true
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
    worker = f'''[Unit]
Description=TrendAtlas Anomaly Discovery Lab
After=local-fs.target
[Service]
Type=oneshot
User=trendatlas-anomaly
Group=trendatlas-research
WorkingDirectory={release}
ExecCondition={PYTHON} -I -B {condition} --root {ROOT}
ExecStart={PYTHON} -I -B {entry} worker --root {ROOT} --inputs {INPUTS} --seconds 180
PrivateNetwork=true
RestrictAddressFamilies=AF_UNIX
ReadWritePaths={ROOT} {logs}
InaccessiblePaths={deny} -/run/credentials
CPUQuota=60%
MemoryMax=3G
TasksMax=16
TimeoutStartSec=420
StandardOutput=append:{logs}/worker.log
StandardError=journal
{common}'''
    broker = f'''[Unit]
Description=TrendAtlas Anomaly Lab compact DeepSeek broker
After=network-online.target
[Service]
Type=oneshot
User=trendatlas-research-broker
Group=trendatlas-research
WorkingDirectory={release}
ExecCondition={PYTHON} -I -B {condition} --mailbox {mailbox}
ExecStart={PYTHON} -I -B {entry} broker --mailbox {mailbox}
LoadCredential=deepseek-key:/etc/credstore/trendatlas-research-deepseek
BindPaths={ROOT}/mailbox:{mailbox}
ReadWritePaths={mailbox} {logs}
InaccessiblePaths={deny} {ROOT} {INPUTS.parent}
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CPUQuota=10%
MemoryMax=256M
TasksMax=8
TimeoutStartSec=115
StandardOutput=append:{logs}/broker.log
StandardError=journal
{common}'''
    result = {UNIT_NAMES[0]: worker, UNIT_NAMES[2]: broker}
    for name, seconds in [('lab', 20), ('broker', 10)]:
        unit = 'trendatlas-anomaly-'+name
        result[unit+'.timer'] = f'''[Unit]
Description=Continue TrendAtlas Anomaly {name}
[Timer]
OnBootSec=2min
OnUnitInactiveSec={seconds}s
Unit={unit}.service
[Install]
WantedBy=timers.target
'''
    return result


def main(package):
    import pwd
    import grp
    if os.geteuid() != 0: raise ValueError('deploy_requires_research_admin')
    for name in UNIT_NAMES:
        if Path('/etc/systemd/system', name).exists(): raise ValueError('existing_lab_requires_explicit_checkpoint_preserving_upgrade')
    if (ROOT/'lab.sqlite').exists(): raise ValueError('existing_lab_checkpoint_never_reset')
    package = Path(package); revision = hashlib.sha256(package.read_bytes()).hexdigest()[:16]
    release = Path('/opt/trendatlas-research/anomaly-lab/releases')/revision
    if release.exists(): raise ValueError('release_already_exists')
    before = existing_v2(); shutil.copytree(BASE, release)
    allowed = {'source_of_truth/anomaly_lab_contract.json', 'tests/test_anomaly_lab.py'}
    with zipfile.ZipFile(package) as archive:
        for name in archive.namelist():
            if name not in allowed and not (name.startswith('research/anomaly_lab/') and name.endswith('.py')):
                raise ValueError('package_scope_violation')
            target = (release/name).resolve()
            if not target.is_relative_to(release.resolve()): raise ValueError('package_path_escape')
        for name in archive.namelist():
            target = release/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(archive.read(name))
    try: pwd.getpwnam('trendatlas-anomaly')
    except KeyError: checked(['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', '--gid', 'trendatlas-research', 'trendatlas-anomaly'])
    uid = pwd.getpwnam('trendatlas-anomaly').pw_uid; gid = grp.getgrnam('trendatlas-research').gr_gid
    for parent in (release.parent.parent, release.parent): parent.chmod(0o755)
    for p in (release, *release.rglob('*')):
        os.chown(p, 0, gid); p.chmod(0o750 if p.is_dir() else 0o640)
    for folder in (ROOT, ROOT/'mailbox', ROOT/'mailbox/requests', ROOT/'mailbox/responses', ROOT/'handoff', Path('/var/log/trendatlas-anomaly-lab')):
        folder.mkdir(parents=True, exist_ok=True); os.chown(folder, uid, gid); folder.chmod(0o770)
    checked(['sudo', '-u', 'trendatlas-anomaly', PYTHON, '-B', '-m', 'research.anomaly_lab.contract'], cwd=release)
    checked(['sudo', '-u', 'trendatlas-anomaly', PYTHON, '-B', '-m', 'unittest', 'tests.test_anomaly_lab', 'tests.test_phase2_v2', '-q'], cwd=release)
    unit_paths = []
    for name, body in units(release).items():
        path = Path('/etc/systemd/system')/name; path.write_text(body); unit_paths.append(str(path))
    checked(['systemd-analyze', 'verify', *unit_paths])
    if existing_v2() != before: raise ValueError('v2_changed_during_lab_preflight')
    receipt = {'release': str(release), 'package_sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
               'inputs': str(INPUTS), 'units': unit_paths, 'existing_v2_table_hashes_before': before,
               'existing_v2_table_hashes_after': existing_v2(), 'existing_v2_unchanged': True,
               'engine_unchanged': (release/'research/phase2_v2/engine.py').read_bytes() == (BASE/'research/phase2_v2/engine.py').read_bytes(),
               'production_touched': False, 'pi_touched': False, 'leadpilot_touched': False}
    (ROOT/'deployment.json').write_text(json.dumps(receipt, indent=2)+'\n')
    checked(['systemctl', 'daemon-reload'])
    checked(['systemctl', 'enable', '--now', 'trendatlas-anomaly-broker.timer', 'trendatlas-anomaly-lab.timer'])
    print(json.dumps(receipt))


if __name__ == '__main__': main(sys.argv[1])
