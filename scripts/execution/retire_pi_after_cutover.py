"""Second operator command: archive/fence/reboot Pi only after verified cutover."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.execution.cutover_pi_to_vps import SSHBackend
from scripts.execution.authority_contract import atomic_write_json


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute-cleanup',action='store_true')
    p.add_argument('--ssh-key',type=Path,default=Path.home()/'.ssh/trendatlas_research_admin_20260928')
    p.add_argument('--pi-host',default='trendatlas.local')
    p.add_argument('--state',type=Path,default=Path.home()/'.codex/trendatlas-production-cutover.json')
    a=p.parse_args(argv)
    state=json.loads(a.state.read_text())
    if state.get('phase')!='SUCCESS': raise RuntimeError('successful operator cutover required before retirement')
    backend=SSHBackend(a.ssh_key,a.pi_host)
    backend.verify_sole_vps()
    receipt=backend.readback()
    if receipt.get('verified') is not True: raise RuntimeError('fresh verified VPS readback required')
    if not a.execute_cleanup:
        print(backend.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/control inventory')); return
    # Send only non-secret verified execution evidence, never command interpolation.
    r=subprocess.run(['ssh','-i',str(a.ssh_key),'-o','BatchMode=yes','-o','HostName='+a.pi_host,'-o','HostKeyAlias=trendatlas.local','trendatlas@trendatlas.local',
        'sudo -n sh -c "umask 077; cat > /var/lib/trendatlas-migration/vps-success.json"'],input=json.dumps(receipt),text=True,capture_output=True)
    if r.returncode: raise RuntimeError('could not transfer cutover receipt')
    try:
        backend.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/control retire --execute-cleanup --receipt /var/lib/trendatlas-migration/vps-success.json')
    except RuntimeError:
        # SSH may be interrupted by reboot; only post-boot verification can succeed.
        pass
    for _ in range(90):
        time.sleep(5)
        try:
            result=json.loads(backend.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/control verify-reboot'))
            if result.get('reboot_verified') and result.get('trading_credential_removed'):
                backend.helper('verify-active')
                if not backend.readback().get('verified'): raise RuntimeError('VPS readback failed after Pi reboot')
                state['PI_SAFE_TO_POWER_OFF']=True; atomic_write_json(a.state,state)
                print(json.dumps({'PI_SAFE_TO_POWER_OFF':True})); return
        except (RuntimeError,ValueError): continue
    raise RuntimeError('Pi reboot or sole VPS verification incomplete; PI_SAFE_TO_POWER_OFF remains false')

if __name__=='__main__': main()
