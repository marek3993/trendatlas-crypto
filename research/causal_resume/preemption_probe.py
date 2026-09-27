"""Isolated systemd regression: fake authority only, never real production."""
import json
import os
from pathlib import Path
import pwd
import subprocess
import time

PREFIX = 'trendatlas-resume-probe-'
ROOT = Path('/run/trendatlas-resume-probe')
UNIT_ROOT = Path('/run/systemd/system')


def call(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def status(name):
    return dict(line.split('=', 1) for line in call('systemctl','show',name,
        '-p','ActiveState','-p','MainPID','-p','Result').splitlines())


def until(predicate):
    end = time.monotonic()+12
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.2)
    raise AssertionError('Probe transition timed out')


def main():
    ROOT.mkdir(exist_ok=False)
    user = pwd.getpwnam('trendatlas-research')
    os.chown(ROOT, user.pw_uid, user.pw_gid)
    child = ROOT/'worker.py'
    child.write_text('''import signal,time
from pathlib import Path
p=Path('/run/trendatlas-resume-probe/events')
def event(s):
 with p.open('a') as f:f.write(s+'\\n');f.flush()
def stop(*_):
 event('CHECKPOINTED');raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
event('RUNNING')
while True:time.sleep(.1)
''')
    authority, worker, dispatch, hung = [PREFIX+n+'.service' for n in ('authority','worker','dispatch','hung')]
    common = 'User=trendatlas-research\nPrivateNetwork=yes\nProtectSystem=strict\nProtectHome=yes\nNoNewPrivileges=yes\nReadWritePaths='+str(ROOT)+'\n'
    units = {
        authority:'[Service]\nType=exec\nExecStart=/bin/sleep 60\n'+common,
        worker:'[Unit]\nConflicts='+authority+'\nAfter='+authority+'\nRefuseManualStart=yes\n[Service]\nType=exec\nExecCondition=/bin/sh -c "! /bin/systemctl is-active --quiet '+authority+'"\nExecStart=/usr/bin/python3 '+str(child)+'\nTimeoutStopSec=20s\nRuntimeMaxSec=30min\n'+common,
        dispatch:'[Unit]\nOnSuccess='+worker+'\nOnSuccessJobMode=ignore-requirements\n[Service]\nType=oneshot\nExecStart=/bin/true\n'+common,
        hung:'[Service]\nType=exec\nExecStart=/bin/sleep 60\nRuntimeMaxSec=2s\nTimeoutStopSec=1s\n'+common,
    }
    try:
        for name,text in units.items():
            path=UNIT_ROOT/name
            if path.exists():
                raise FileExistsError(path)
            path.write_text(text)
        call('systemctl','daemon-reload')
        call('systemctl','start',dispatch)
        until(lambda:(ROOT/'events').exists())
        call('systemctl','start',authority)
        until(lambda:status(worker)['ActiveState']=='inactive')
        checkpoint = (ROOT/'events').read_text().splitlines()
        assert checkpoint == ['RUNNING','CHECKPOINTED'], checkpoint
        active=status(authority)
        call('systemctl','start',dispatch)
        time.sleep(.5)
        assert status(authority)['MainPID']==active['MainPID']
        assert status(worker)['ActiveState']=='inactive'
        call('systemctl','stop',authority)
        call('systemctl','start',dispatch)
        until(lambda:(ROOT/'events').read_text().splitlines()==checkpoint+['RUNNING'])
        call('systemctl','start',hung)
        until(lambda:status(hung)['ActiveState']=='failed')
        assert status(hung)['Result']=='timeout'
        print(json.dumps(dict(production_preemption_checkpoints=True,
            dispatch_does_not_stop_authority=True, resume_after_authority=True,
            hard_timeout_still_fails=True, real_production_invoked=False,
            events=(ROOT/'events').read_text().splitlines())))
    finally:
        for name in units:
            subprocess.run(['systemctl','stop',name],capture_output=True)
            (UNIT_ROOT/name).unlink(missing_ok=True)
        subprocess.run(['systemctl','reset-failed',hung],capture_output=True)
        call('systemctl','daemon-reload')
        for path in ROOT.iterdir():
            path.unlink()
        ROOT.rmdir()


if __name__ == '__main__':
    main()
