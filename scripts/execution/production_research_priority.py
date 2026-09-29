"""Production preemption through the research worker's existing checkpoint stop."""
import argparse
import json
import os
from pathlib import Path
import subprocess

MARKER=Path('/run/trendatlas-production-preempted')
WORKER='trendatlas-research-worker.service'


def control(action,run=subprocess.run,marker=MARKER):
    if action=='pause':
        active=run(['systemctl','is-active','--quiet',WORKER],check=False).returncode==0
        marker.write_text(json.dumps({'was_active':active}))
        if active:
            run(['systemctl','stop',WORKER],check=True)
            # ExecStop/ExecStopPost in the pinned worker validate its durable checkpoint.
            p=run(['systemctl','show',WORKER,'--value','-p','Result'],check=True,capture_output=True,text=True)
            if p.stdout.strip()!='success': raise RuntimeError('research checkpoint stop did not succeed')
    elif action=='resume' and marker.exists():
        state=json.loads(marker.read_text()); marker.unlink()
        if state['was_active']: run(['systemctl','start','--no-block',WORKER],check=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['pause','resume']); a=p.parse_args()
    if os.geteuid()!=0: raise RuntimeError('root required')
    control(a.action)
