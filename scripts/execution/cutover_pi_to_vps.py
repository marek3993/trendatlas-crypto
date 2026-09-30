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
from scripts.execution.migration_diagnostics import remote_error, failure_report, MigrationError, reason_code


class Cutover:
    def __init__(self, backend, state_path: Path):
        self.backend, self.path = backend, state_path
        self.state=json.loads(state_path.read_text()) if state_path.exists() else {'phase':'NEW'}

    def save(self, phase, **details):
        self.state.update(phase=phase, updated_at=datetime.now(timezone.utc).isoformat(), **details)
        atomic_write_json(self.path,self.state)

    def reconcile_existing(self):
        # Persist uncertainty before any fallible network call. No start/restore
        # operation belongs in this path, even when a response was lost.
        self.save('RECONCILE_REQUIRED')
        self.backend.verify_pi_fenced()
        result=self.backend.reconcile(self.state)
        if not result.get('verified'):
            self.save('RECONCILE_REQUIRED',readback=result)
            raise MigrationError(result.get('reason_code','SUBMISSION_UNRESOLVED'))
        self.backend.verify_sole_vps()
        self.save('SUCCESS',readback=result)
        return result

    def execute(self):
        b=self.backend
        if self.state['phase']=='SUCCESS':
            b.verify_sole_vps(); return b.readback()
        if self.state['phase'] in {'ACTIVATING','VPS_ACTIVE','RUN_REQUESTED','RECONCILE_REQUIRED'}:
            # Reconcile only: an uncertain start may already have submitted a signed order.
            return self.reconcile_existing()
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
        except BaseException as original_error:
            if self.state['phase'] in {'RUN_REQUESTED','VPS_ACTIVE'}:
                self.save('RECONCILE_REQUIRED',recovery_trigger=reason_code(original_error))
                return self.reconcile_existing()
            self.save('RECONCILE_REQUIRED')
            if b.vps_provably_never_activated():
                b.restore_pi()
                self.save('PI_RESTORED_BEFORE_ACTIVATION')
                raise
            # Possible order: never re-enable Pi, remove journal rows or resubmit here.
            raise


class SSHBackend:
    def __init__(self,key:Path,pi_host='trendatlas.local'):
        self.key,self.pi_host=key,pi_host
        self.phase='NEW'
    def remote(self,host,command):
        options=['-o','HostName='+self.pi_host,'-o','HostKeyAlias=trendatlas.local'] if host=='trendatlas@trendatlas.local' else []
        result=subprocess.run(['ssh','-i',str(self.key),'-o','BatchMode=yes','-o','ConnectTimeout=15',*options,host,command],capture_output=True,text=True,check=False)
        if result.returncode:
            error=remote_error(result.stdout)
            if result.returncode==255:
                for text,code in [('timed out','SSH_CONNECTION_TIMEOUT'),('Connection closed','SSH_CONNECTION_CLOSED'),
                                  ('Connection reset','SSH_CONNECTION_CLOSED'),('Permission denied','SSH_AUTH_FAILED')]:
                    if text in result.stderr:
                        error=MigrationError(code);break
            error.remote_exit_code=result.returncode
            raise error
        return result.stdout.strip()
    def helper(self,action):
        return json.loads(self.remote('ubuntu@57.129.127.49',
            'sudo -n /opt/trendatlas-production/current/.venv/bin/python /opt/trendatlas-production/current/scripts/execution/migration_host_control.py '+action+(' --execute-live' if action in {'activate','run-once'} else '')))
    def preflight(self):
        self.phase='PREFLIGHT_PI'
        pi=json.loads(self.remote('trendatlas@trendatlas.local','sudo -n /var/lib/trendatlas-migration/bin/readback'))
        self.phase='PREFLIGHT_VPS'
        vps=self.helper('preflight')
        self.phase='PREFLIGHT_COMPARE'
        if pi['identity']!=vps['identity'] or pi['journal_sha256']!=vps['journal_sha256'] or pi['target']!=vps['target']:
            raise RuntimeError('account/signer/journal identity mismatch')
        if not pi['only_live_host'] or not vps['no_submit']: raise RuntimeError('single execution host not established')
        self.phase='PREPARED'
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
    def snapshot(self):
        import shlex
        script = ('import json,subprocess;from pathlib import Path;'
                  'units=["mrv1-production.timer","mrv1-production.service","mrv1-watchdog.timer"];'
                  'print(json.dumps({"available":True,"fenced":Path("/etc/systemd/system/mrv1-production.service.d/90-migration-fence.conf").exists(),'
                  '"units":{u:{k:subprocess.check_output(["systemctl","show",u,"--value","-p",k],text=True).strip() '
                  'for k in ["UnitFileState","ActiveState"]} for u in units}}))')
        result={}
        for name,call in [('pi',lambda:json.loads(self.remote('trendatlas@trendatlas.local','python3 -c '+shlex.quote(script)))),
                          ('vps',lambda:self.helper('snapshot'))]:
            try: result[name]=call()
            except Exception: result[name]={'available':False}
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-live',action='store_true',help='Operator confirmation: migrate authority and activate automatic real trading')
    parser.add_argument('--reconcile-only',action='store_true',help='Read back an existing activation; never activate or request a production run')
    parser.add_argument('--ssh-key',type=Path,default=Path.home()/'.ssh/trendatlas_research_admin_20260928')
    parser.add_argument('--pi-host',default='trendatlas.local',help='Optional current Pi IP; original SSH host-key identity is retained')
    parser.add_argument('--state',type=Path,default=Path.home()/'.codex/trendatlas-production-cutover.json')
    parser.add_argument('--diagnostic-report',type=Path,default=Path.home()/'.codex/trendatlas-cutover-diagnostic.json')
    args=parser.parse_args(argv); backend=SSHBackend(args.ssh_key,args.pi_host)
    cutover=None
    try:
        with SingleRunLock(args.state.with_suffix('.lock')):
            cutover=Cutover(backend,args.state)
            if args.reconcile_only:
                if cutover.state['phase'] not in {'ACTIVATING','VPS_ACTIVE','RUN_REQUESTED','RECONCILE_REQUIRED','SUCCESS'}:
                    raise MigrationError('SUBMISSION_UNRESOLVED')
                result=cutover.reconcile_existing()
            else:
                result=cutover.execute() if args.execute_live else backend.preflight()
    except Exception as error:
        state=cutover.state if cutover is not None else {'phase':'UNKNOWN'}
        phase=backend.phase if state.get('phase') in {'NEW','PREPARED'} else None
        report=failure_report(error,state,phase)
        if isinstance(error,MigrationError) and hasattr(error,'remote_exit_code'):
            report['remote_exit_code']=error.remote_exit_code
        if report['live_activation_possible'] is not False:
            report['host_state']=backend.snapshot()
            pi=report['host_state']['pi']
            if pi.get('available'):
                report['pi_fenced']=pi['fenced']
        report['diagnostic_report']=str(args.diagnostic_report.resolve())
        report['observed_at']=datetime.now(timezone.utc).isoformat()
        atomic_write_json(args.diagnostic_report,report)
        print(json.dumps(report,indent=2))
        return 1
    print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
