"""Operator-only production migration. Default invocation is read-only preflight.

The engine records possible activation before the first activation operation.
After that boundary it never automatically restores Pi or blindly reruns orders.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.execution.authority_contract import atomic_write_json
from scripts.execution.run_trendatlas_production import SingleRunLock


class Cutover:
    def __init__(self, backend, state_path: Path):
        self.backend, self.path = backend, state_path
        self.state=json.loads(state_path.read_text()) if state_path.exists() else {'phase':'NEW'}

    def save(self, phase, **details):
        self.state.update(phase=phase, updated_at=datetime.now(timezone.utc).isoformat(), **details)
        atomic_write_json(self.path,self.state)

    def execute(self):
        b=self.backend
        if self.state['phase']=='SUCCESS':
            b.verify_sole_vps(); return b.readback()
        if self.state['phase'] in {'ACTIVATING','VPS_ACTIVE','RUN_REQUESTED','RECONCILE_REQUIRED'}:
            # Reconcile only: an uncertain start may already have submitted a signed order.
            b.verify_pi_fenced()
            result=b.reconcile(self.state)
            if not result.get('verified'): raise RuntimeError('readback unresolved; no new run or Pi restoration permitted')
            b.verify_sole_vps(); self.save('SUCCESS',readback=result); return result
        try:
            evidence=b.preflight()
            self.save('PREPARED',evidence=evidence)
            b.wait_pi_idle()
            self.save('FENCING_PI')
            b.fence_pi()
            self.save('PI_FENCED')
            b.verify_pi_fenced()
            checkpoint=b.final_checkpoint()
            b.verify_handoff(checkpoint)
            self.save('CHECKPOINTED',checkpoint=checkpoint)
        except BaseException:
            if self.state['phase'] in {'FENCING_PI','PI_FENCED','CHECKPOINTED'} and b.vps_provably_never_activated(): b.restore_pi()
            raise
        self.save('ACTIVATING')
        try:
            b.activate_vps()
            self.save('VPS_ACTIVE')
            self.save('RUN_REQUESTED')
            b.run_once(self.state)
            result=b.readback()
            if not result.get('verified'): raise RuntimeError('post-cutover readback not verified')
            b.verify_sole_vps()
            self.save('SUCCESS',readback=result)
            return result
        except BaseException:
            if b.vps_provably_never_activated():
                b.restore_pi()
                self.save('PI_RESTORED_BEFORE_ACTIVATION')
                raise
            self.save('RECONCILE_REQUIRED')
            # Possible order: never re-enable Pi, remove journal rows or resubmit here.
            raise


class SSHBackend:
    def __init__(self,key:Path,pi_host='trendatlas.local'): self.key,self.pi_host=key,pi_host
    def remote(self,host,command):
        options=['-o','HostName='+self.pi_host,'-o','HostKeyAlias=trendatlas.local'] if host=='trendatlas@trendatlas.local' else []
        result=subprocess.run(['ssh','-i',str(self.key),'-o','BatchMode=yes','-o','ConnectTimeout=15',*options,host,command],capture_output=True,text=True,check=False)
        if result.returncode: raise RuntimeError(f'{host}: migration operation failed ({result.returncode}); inspect protected host logs')
        return result.stdout.strip()
    def helper(self,action):
        return json.loads(self.remote('ubuntu@57.129.127.49',
            'sudo -n /opt/trendatlas-production/current/.venv/bin/python /opt/trendatlas-production/current/scripts/execution/migration_host_control.py '+action+(' --execute-live' if action in {'activate','run-once'} else '')))
    def preflight(self):
        pi=json.loads(self.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/readback'))
        vps=self.helper('preflight')
        if pi['identity']!=vps['identity'] or pi['journal_sha256']!=vps['journal_sha256'] or pi['target']!=vps['target']:
            raise RuntimeError('account/signer/journal identity mismatch')
        if not pi['only_live_host'] or not vps['no_submit']: raise RuntimeError('single execution host not established')
        return {'pi':pi,'vps':vps}
    def wait_pi_idle(self):
        self.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/control wait-idle')
    def fence_pi(self): self.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/control fence')
    def verify_pi_fenced(self): self.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/control verify-fenced')
    def final_checkpoint(self): return json.loads(self.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/readback'))
    def verify_handoff(self,checkpoint):
        result=self.helper('checkpoint')
        if checkpoint['journal_sha256']!=result['journal_sha256'] or checkpoint['identity']!=result['identity']:
            raise RuntimeError('journal/nonce handoff mismatch; never restore a stale DB snapshot')
    def vps_provably_never_activated(self): return self.helper('activation-status')['never_activated']
    def restore_pi(self): self.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/control restore')
    def activate_vps(self): self.helper('activate')
    def run_once(self,state): self.helper('run-once')
    def readback(self): return self.helper('readback')
    def reconcile(self,state): return self.helper('reconcile')
    def verify_sole_vps(self): self.verify_pi_fenced(); self.helper('verify-active')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-live',action='store_true',help='Operator confirmation: migrate authority and activate automatic real trading')
    parser.add_argument('--ssh-key',type=Path,default=Path.home()/'.ssh/trendatlas_research_admin_20260928')
    parser.add_argument('--pi-host',default='trendatlas.local',help='Optional current Pi IP; original SSH host-key identity is retained')
    parser.add_argument('--state',type=Path,default=Path.home()/'.codex/trendatlas-production-cutover.json')
    args=parser.parse_args(argv); backend=SSHBackend(args.ssh_key,args.pi_host)
    with SingleRunLock(args.state.with_suffix('.lock')):
        result=Cutover(backend,args.state).execute() if args.execute_live else backend.preflight()
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
