"""Render research-only systemd units. No production files or timers are edited."""
from pathlib import Path

BASE='/var/lib/trendatlas-research/causal-v1'
VENV='/opt/trendatlas-research/venvs/causal-v1'

def units(release):
    entry=f'{release}/research/causal_evolution/bootstrap.py'
    python=f'{VENV}/bin/python3 -I -B'
    clean=f'/usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME=/nonexistent OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 {python}'
    isolation='''NoNewPrivileges=yes
CapabilityBoundingSet=
AmbientCapabilities=
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
ProtectProc=invisible
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
UMask=0027
Nice=19
IOSchedulingClass=idle
Slice=trendatlas-causal-research.slice
TasksMax=16
MemoryMax=768M
MemorySwapMax=0
LimitAS=768M
LimitMEMLOCK=768M
InaccessiblePaths=/opt/market_regime_v1 /opt/home_automation /etc/default -/etc/credstore -/etc/credstore.encrypted -/run/user
'''
    worker=f'''[Unit]
Description=TrendAtlas frozen causal research worker
Conflicts=mrv1-production.service
After=mrv1-production.service
RefuseManualStart=yes
[Service]
Type=exec
User=trendatlas-research
Group=trendatlas-research
ExecCondition={clean} {entry} ready
ExecCondition=/usr/bin/python3 -I -B {release}/research/causal_evolution/gate.py
ExecStart={clean} {entry} run
TimeoutStopSec=2s
RuntimeMaxSec=31min
KillMode=control-group
Restart=no
CPUQuota=20%
CPUWeight=1
PrivateNetwork=yes
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
ReadWritePaths={BASE}/cycles
InaccessiblePaths=-/run/credentials -/var/lib/trendatlas-research/continuous -/var/lib/trendatlas-research/jobs
{isolation}'''
    dispatcher=f'''[Unit]
Description=Admit frozen research without stopping production
After=mrv1-production.service
OnSuccess=trendatlas-evolution-worker.service
OnSuccessJobMode=ignore-requirements
[Service]
Type=oneshot
User=trendatlas-research
Group=trendatlas-research
ExecCondition={clean} {entry} ready
ExecStart=/usr/bin/python3 -I -B {release}/research/causal_evolution/gate.py --dispatch
PrivateNetwork=yes
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
TimeoutStartSec=15s
CPUQuota=5%
{isolation}'''
    broker=f'''[Unit]
Description=Development-only JSON DeepSeek broker, no market/account data
After=mrv1-production.service
[Service]
Type=oneshot
User=trendatlas-research
Group=trendatlas-research
ExecCondition=/usr/bin/python3 -I -B {release}/research/causal_evolution/gate.py
ExecStart={python} {entry} broker
Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
LoadCredentialEncrypted=deepseek-key:/etc/credstore.encrypted/trendatlas-causal-deepseek
BindPaths={BASE}/current/mailbox:/var/lib/trendatlas-causal-broker/mailbox
ReadWritePaths=/var/lib/trendatlas-causal-broker/mailbox
InaccessiblePaths=/var/lib/trendatlas-research {release}/research/causal_evolution/inputs -/run/credentials/mrv1-production.service
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
TimeoutStartSec=60s
CPUQuota=5%
{isolation}'''
    maintenance=f'''[Unit]
Description=Research public-data append and guarded next-cycle admission
Conflicts=mrv1-production.service
After=mrv1-production.service
RefuseManualStart=yes
[Service]
Type=oneshot
User=trendatlas-research
Group=trendatlas-research
ExecCondition=/usr/bin/python3 -I -B {release}/research/causal_evolution/gate.py
ExecStart={clean} {entry} maintain
ReadWritePaths={BASE}
InaccessiblePaths=-/run/credentials
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CPUQuota=10%
TimeoutStartSec=10min
TimeoutStopSec=2s
{isolation}'''
    maintenance_dispatch=f'''[Unit]
Description=Admit research data maintenance after successful production
After=mrv1-production.service
OnSuccess=trendatlas-causal-maintain.service
OnSuccessJobMode=ignore-requirements
[Service]
Type=oneshot
User=trendatlas-research
ExecStart=/usr/bin/python3 -I -B {release}/research/causal_evolution/gate.py --dispatch
PrivateNetwork=yes
RestrictAddressFamilies=AF_UNIX
{isolation}'''
    def timer(service,interval):return f'''[Unit]
Description=Research-only {service} scheduling
[Timer]
OnBootSec=8min
OnUnitInactiveSec={interval}
AccuracySec=15s
Unit={service}.service
[Install]
WantedBy=timers.target
'''
    return {'trendatlas-evolution-worker.service':worker,'trendatlas-evolution-dispatch.service':dispatcher,
            'trendatlas-causal-broker.service':broker,'trendatlas-causal-broker.timer':timer('trendatlas-causal-broker','1min'),
            'trendatlas-causal-maintain.service':maintenance,'trendatlas-causal-maintain-dispatch.service':maintenance_dispatch,
            'trendatlas-causal-maintain-dispatch.timer':timer('trendatlas-causal-maintain-dispatch','30min'),
            'trendatlas-causal-research.slice':'[Unit]\nDescription=Aggregate research CPU ceiling\n[Slice]\nCPUQuota=20%\nCPUWeight=1\n'}

def render(release,destination):
    out=Path(destination);out.mkdir(parents=True,exist_ok=True)
    for name,body in units(release).items():(out/name).write_text(body,encoding='utf-8')
