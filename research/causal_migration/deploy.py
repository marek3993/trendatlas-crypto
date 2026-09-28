"""Render only research units. Frozen engine and production units remain untouched."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import runtime as r

ENTRY='/opt/trendatlas-research/orchestration/causal-migration-20260928/research/causal_migration'
PY='/opt/trendatlas-research/venvs/causal-v1/bin/python3 -I -B'
BASE='/var/lib/trendatlas-research/causal-v1'


def pi_dropins(maximum=2):
    cmd=f'{PY} {ENTRY}/runtime.py'
    return {
        'trendatlas-evolution-worker.service':f'''[Service]
ExecCondition=
ExecCondition={cmd} ready --platform pi
ExecCondition=/usr/bin/python3 -I -B {r.ENGINE.as_posix()}/research/causal_evolution/gate.py
ExecStart=
ExecStart={cmd} run --platform pi --seconds 300 --max-evaluations {maximum} --no-outer
ExecStop={cmd} stop --platform pi
ExecStopPost={cmd} finalize --platform pi
KillMode=mixed
TimeoutStartSec=120s
TimeoutStopSec=120s
RuntimeMaxSec=1800s
''',
        'trendatlas-evolution-dispatch.service':f'''[Service]
ExecCondition=
ExecCondition={cmd} ready --platform pi
TimeoutStartSec=120s
'''}


def vps_units():
    isolation='''NoNewPrivileges=true
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
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0027
MemoryMax=4608M
MemorySwapMax=0
CPUQuota=300%
CPUWeight=10
Nice=10
IOSchedulingClass=idle
TasksMax=32
InaccessiblePaths=/opt/leadpilot -/var/lib/docker -/run/docker.sock -/var/run/docker.sock -/etc/credstore.encrypted -/opt/market_regime_v1 -/opt/home_automation
Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
'''
    cmd=f'{PY} {ENTRY}/runtime.py'
    worker=f'''[Unit]
Description=TrendAtlas isolated research worker
After=local-fs.target
StartLimitIntervalSec=600
StartLimitBurst=3
[Service]
Type=exec
User=trendatlas-research
Group=trendatlas-research
ExecCondition={cmd} ready --platform vps
ExecStart={cmd} run --platform vps
ExecStop={cmd} stop --platform vps
ExecStopPost={cmd} finalize --platform vps
Restart=on-failure
RestartSec=30s
RuntimeMaxSec=1800s
TimeoutStartSec=120s
TimeoutStopSec=120s
KillMode=mixed
PrivateNetwork=true
StandardOutput=append:/var/log/trendatlas-research/worker.log
StandardError=inherit
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
ReadWritePaths={BASE}/cycles /var/log/trendatlas-research /srv/trendatlas-research-export
InaccessiblePaths=-/run/credentials
{isolation}
[Install]
WantedBy=multi-user.target
'''
    dispatcher=f'''[Unit]
Description=Resume a checkpointed TrendAtlas research activation
[Service]
Type=oneshot
ExecCondition={cmd} ready --platform vps
ExecStart=/usr/bin/systemctl start trendatlas-research-worker.service
'''
    # Successful checkpoints exit 0; timer resumes them. Failures use Restart.
    timer='''[Unit]
Description=Resume bounded TrendAtlas research checkpoints
[Timer]
OnBootSec=2min
OnUnitInactiveSec=1min
Unit=trendatlas-research-dispatch.service
[Install]
WantedBy=timers.target
'''
    broker=f'''[Unit]
Description=Development-only research proposal broker
[Service]
Type=oneshot
User=trendatlas-research-broker
Group=trendatlas-research
ExecStart={PY} {ENTRY}/broker.py
LoadCredential=deepseek-key:/etc/credstore/trendatlas-research-deepseek
BindPaths={BASE}/current/mailbox:/var/lib/trendatlas-research-broker/mailbox
ReadWritePaths=/var/lib/trendatlas-research-broker/mailbox
InaccessiblePaths=/var/lib/trendatlas-research {r.ENGINE.as_posix()}/research/causal_evolution/inputs -/etc/credstore
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
TimeoutStartSec=60s
{isolation}
MemoryMax=512M
CPUQuota=20%
StandardOutput=append:/var/log/trendatlas-research/broker.log
StandardError=inherit
'''
    broker_timer='''[Timer]
OnBootSec=2min
OnUnitInactiveSec=30s
Unit=trendatlas-research-broker.service
[Install]
WantedBy=timers.target
'''
    backup=f'''[Unit]
Description=Verified SQLite research backup and read-only export
[Service]
Type=oneshot
User=root
ExecStart={PY} {ENTRY}/maintenance.py
StandardOutput=append:/var/log/trendatlas-research/maintenance.log
StandardError=inherit
Nice=15
IOSchedulingClass=idle
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateNetwork=true
ReadWritePaths=/var/lib/trendatlas-research /var/backups/trendatlas-research /srv/trendatlas-research-export /var/log/trendatlas-research
InaccessiblePaths=/opt/leadpilot -/var/lib/docker -/run/docker.sock -/etc/credstore -/etc/credstore.encrypted
'''
    backup_timer='''[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
Unit=trendatlas-research-backup.service
[Install]
WantedBy=timers.target
'''
    return {'trendatlas-research-worker.service':worker,'trendatlas-research-dispatch.service':dispatcher,
            'trendatlas-research-dispatch.timer':timer,'trendatlas-research-broker.service':broker,
            'trendatlas-research-broker.timer':broker_timer,'trendatlas-research-backup.service':backup,
            'trendatlas-research-backup.timer':backup_timer}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('platform',choices=['pi','vps']);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    for name,body in (pi_dropins() if a.platform=='pi' else vps_units()).items():
        path=a.output/(name+'.d/60-migration.conf' if a.platform=='pi' else name)
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
