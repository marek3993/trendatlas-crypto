import json,subprocess,time
from pathlib import Path
prefix='trendatlas-causal-preempt-'; authority=prefix+'authority.service';victim=prefix+'victim.service';dispatch=prefix+'dispatch.service'
common='User=trendatlas-research\nPrivateNetwork=yes\nProtectSystem=strict\nProtectHome=yes\nNoNewPrivileges=yes\nSlice=trendatlas-causal-research.slice\n'
units={authority:'[Unit]\nDescription=Research preemption probe authority (NOT production)\n[Service]\nType=exec\nExecStart=/bin/sleep 30\n'+common,
 victim:'[Unit]\nDescription=Research preemption probe victim\nConflicts='+authority+'\nAfter='+authority+'\nRefuseManualStart=yes\n[Service]\nType=exec\nExecCondition=/bin/sh -c "! /bin/systemctl is-active --quiet '+authority+'"\nExecStart=/bin/sleep 30\nTimeoutStopSec=2s\n'+common,
 dispatch:'[Unit]\nDescription=Research preemption probe admission\nOnSuccess='+victim+'\nOnSuccessJobMode=ignore-requirements\n[Service]\nType=oneshot\nExecStart=/bin/true\n'+common}
def call(args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout
def state(unit):
    value=call(['systemctl','show',unit,'-p','ActiveState','-p','MainPID'])
    return dict(line.split('=',1) for line in value.splitlines())
try:
    for name,body in units.items():(Path('/run/systemd/system')/name).write_text(body)
    call(['systemctl','daemon-reload']);call(['systemctl','start',dispatch]);time.sleep(1)
    before=state(victim);assert before['ActiveState']=='active',before
    call(['systemctl','start',authority]);time.sleep(1)
    stopped=state(victim);active=state(authority);assert stopped['ActiveState']=='inactive',stopped
    call(['systemctl','start',dispatch]);time.sleep(1)
    protected=state(authority);blocked=state(victim)
    assert protected['MainPID']==active['MainPID'] and protected['ActiveState']=='active' and blocked['ActiveState']=='inactive'
    print(json.dumps(dict(preempts_running_research=True,admission_does_not_stop_authority=True,real_production_invoked=False,units=list(units))))
finally:
    for unit in (authority,victim,dispatch):subprocess.run(['systemctl','stop',unit],capture_output=True)
    for name in units:
        p=Path('/run/systemd/system')/name
        if p.exists():p.unlink()
    subprocess.run(['systemctl','daemon-reload'],check=True)
