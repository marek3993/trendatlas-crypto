"""Root-owned host helper for an explicitly operator-invoked migration.

No action is implicit: activation and execution require the operator flag.
Read-only actions never run the production service.
"""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.execution.authority_contract import atomic_write_json
from scripts.execution.production_host import validate_evidence, verify_systemd_evidence
from scripts.execution.migration_diagnostics import reason_code, MigrationError
from scripts.execution.migration_readiness import validate_receipt, digest
from scripts.execution.rehearsal_workspace import runtime_fingerprints
from scripts.execution.migration_reconciliation import classify_execution

STATE=Path('/var/lib/trendatlas-production')
CAPABILITIES=Path('/etc/trendatlas-production/capabilities.json')
OVERRIDE=Path('/etc/systemd/system/mrv1-production.service.d/no-submit.conf')
ACTIVATION=STATE/'operator-activation.json'


def run(*args):
    p=subprocess.run(args,capture_output=True,text=True,check=False)
    if p.returncode: raise MigrationError('SERVICE_COMMAND_FAILED')
    return p.stdout.strip()


def property_value(unit,prop): return run('systemctl','show',unit,'--value','-p',prop)


def write_capabilities(evidence):
    import pwd
    user = property_value('mrv1-production.service', 'User')
    gid = pwd.getpwnam(user).pw_gid
    atomic_write_json(CAPABILITIES, evidence)
    # atomic_write_json creates a new 0600 inode. These are non-secret admission
    # hashes, which the unprivileged publisher must be able to read.
    os.chown(CAPABILITIES, 0, gid)
    CAPABILITIES.chmod(0o640)
    verify_service_readability()


def verify_service_readability():
    user = property_value('mrv1-production.service', 'User')
    p = subprocess.run(['runuser', '-u', user, '--', sys.executable, '-c',
                        'import json;from pathlib import Path;'
                        'c=json.loads(Path("/etc/trendatlas-production/capabilities.json").read_text());'
                        'r=Path(c["runtime_root"]);'
                        '[p.read_bytes() for p in [*(r/k for k in c["files"]),*(Path(k) for k in c["systemd_files"])]]'],
                       capture_output=True, text=True)
    if p.returncode:
        raise MigrationError('CAPABILITIES_UNREADABLE')


def host_snapshot():
    result = {'available': True, 'no_submit': OVERRIDE.exists(), 'activation_exists': ACTIVATION.exists(),
              'units': {u: {k: property_value(u, k) for k in ('UnitFileState', 'ActiveState', 'ExecMainStatus')}
                        for u in ('mrv1-production.timer', 'mrv1-production.service', 'mrv1-watchdog.timer')}}
    path = ROOT/'outputs/execution/production_runs/latest_production_run.json'
    manifest = json.loads(path.read_text())
    result['run'] = {k: manifest.get(k) for k in ('run_id', 'final_status', 'no_submit', 'real_order_sent', 'execution_outcome', 'authority_status')}
    return result


def fresh_readback():
    run('systemctl','start','trendatlas-migration-readback.service')
    payload=json.loads((STATE/'readback.json').read_text())
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(payload['observedAt'].replace('Z','+00:00'))).total_seconds()
    if not 0<=age<120 or not payload['journalUnchanged'] or payload['real_order_sent'] is not False:
        raise RuntimeError('readback is stale or unsafe')
    if payload['target']['closedDay']!=(datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat():
        raise RuntimeError('production target needs the current closed day')
    if not payload['accounts'] or any(p['status'] not in {'ALIGNED','READY'} for p in payload['preflight']):
        raise RuntimeError('account preflight is not ready')
    if payload['journal']['tables']['multi_account_execution_locks']:
        raise RuntimeError('execution lease is present')
    identity=sorted([{'master':a['masterAddress'].lower(),'signer':a['signerFingerprint']} for a in payload['accounts']],key=lambda a:a['master'])
    return payload,{'identity':identity,'target':payload['target'],'journal_sha256':payload['journal']['sha256'],
        'nonce_watermarks':payload['journal']['tables']['multi_account_agent_nonces'],
        'plans':[a['plan'] for a in payload['accounts']]}


def validate_ready():
    evidence=json.loads(CAPABILITIES.read_text())
    verify_systemd_evidence(evidence)
    contract=json.loads((ROOT/'source_of_truth/production_host_contract.json').read_text())
    validate_evidence(evidence,system=platform.system(),machine=platform.machine(),python_version=platform.python_version(),
        packages={k:importlib.metadata.version(k) for k in contract['critical_python_packages']},
        machine_id=Path('/etc/machine-id').read_text().strip(),root=ROOT,require_active=False)
    ready=json.loads((Path('/etc/trendatlas-production/ready.json')).read_text())
    required={'canonical_no_submit','publication_dry_run','cross_arch_core','cross_arch_planner','journal_isolation',
        'research_permissions','research_checkpoint_preemption','systemd_verified','publisher_access','cleanup_tool_verified'}
    if any(ready.get(k) is not True for k in required): raise RuntimeError('deployment readiness gates are incomplete')
    if ready.get('capabilities_sha256')!=__import__('hashlib').sha256(CAPABILITIES.read_bytes()).hexdigest():
        raise RuntimeError('readiness receipt does not bind capabilities')
    verify_service_readability()
    return evidence


def assert_inactive():
    if property_value('mrv1-production.service','ActiveState') not in {'inactive','failed'}:
        raise RuntimeError('production service is running')


def action(name,execute_live=False):
    if name in {'activate','run-once'} and not execute_live: raise RuntimeError('explicit operator live confirmation required')
    if name=='snapshot': return host_snapshot()
    if name=='activation-status':
        return {'never_activated':not ACTIVATION.exists() and OVERRIDE.exists() and property_value('mrv1-production.timer','ActiveState')=='inactive'}
    if name=='preflight':
        validate_ready(); assert_inactive()
        if (ACTIVATION.exists() or not OVERRIDE.exists()
                or property_value('mrv1-production.timer','UnitFileState')!='disabled'
                or property_value('mrv1-production.timer','ActiveState')!='inactive'
                or 'run_production_rehearsal.py' not in property_value('mrv1-production.service','ExecStart')):
            raise RuntimeError('VPS must still be disabled and no-submit')
        payload,result=fresh_readback()
        validate_receipt(json.loads(Path('/etc/trendatlas-production/ready.json').read_text()), payload,
                         runtime_inputs_sha256=digest(runtime_fingerprints(ROOT)))
        result['no_submit']=True; return result
    if name=='checkpoint':
        _,result=fresh_readback(); atomic_write_json(STATE/'final-handoff.json',result); return result
    if name=='activate':
        evidence=validate_ready(); assert_inactive()
        if ACTIVATION.exists(): raise RuntimeError('activation already attempted; reconcile instead')
        handoff=json.loads((STATE/'final-handoff.json').read_text())
        payload,current=fresh_readback()
        validate_receipt(json.loads(Path('/etc/trendatlas-production/ready.json').read_text()), payload,
                         runtime_inputs_sha256=digest(runtime_fingerprints(ROOT)))
        if current['journal_sha256']!=handoff['journal_sha256']: raise RuntimeError('journal changed after handoff')
        previous=json.loads((ROOT/'outputs/execution/production_runs/latest_production_run.json').read_text())
        atomic_write_json(ACTIVATION,{'phase':'ACTIVATING','previous_run_id':previous.get('run_id'),
            'at':datetime.now(timezone.utc).isoformat(),'handoff':handoff})
        evidence.update(activated_by_operator=True,single_execution_host=Path('/etc/machine-id').read_text().strip())
        write_capabilities(evidence)
        OVERRIDE.unlink()
        run('systemctl','daemon-reload')
        run('systemctl','enable','--now','mrv1-production.timer','mrv1-watchdog.timer')
        return {'activated':True}
    if name=='run-once':
        activation=json.loads(ACTIVATION.read_text())
        current=json.loads((ROOT/'outputs/execution/production_runs/latest_production_run.json').read_text())
        if current.get('run_id')!=activation['previous_run_id'] or property_value('mrv1-production.service','ActiveState')=='activating':
            for _ in range(2700):
                if property_value('mrv1-production.service','ActiveState') in {'inactive','failed'}: break
                time.sleep(2)
            else: raise RuntimeError('production run remains active; reconcile later')
            return {'persistent_timer_already_started_run':True}
        if activation.get('run_requested'): raise RuntimeError('start already requested; reconcile before retry')
        activation['run_requested']=True; atomic_write_json(ACTIVATION,activation)
        run('systemctl','start','mrv1-production.service')
        return {'run_requested':True}
    if name in {'readback','reconcile'}:
        assert_inactive()
        payload,result=fresh_readback()
        activation=json.loads(ACTIVATION.read_text())
        manifest=json.loads((ROOT/'outputs/execution/production_runs/latest_production_run.json').read_text())
        result.update(classify_execution(manifest,payload,activation),run_id=manifest.get('run_id'),real_order_sent=manifest.get('real_order_sent'))
        result['host_state']=host_snapshot()
        if result['verified']: atomic_write_json(STATE/'cutover-success.json',result)
        return result
    if name=='verify-active':
        if OVERRIDE.exists() or not ACTIVATION.exists() or any(property_value(unit,'UnitFileState')!='enabled' or property_value(unit,'ActiveState')!='active' for unit in ('mrv1-production.timer','mrv1-watchdog.timer')):
            raise RuntimeError('VPS activation not established')
        return {'sole_vps_local_posture':True}
    raise RuntimeError('unsupported action')


def main():
    p=argparse.ArgumentParser(); p.add_argument('action'); p.add_argument('--execute-live',action='store_true'); a=p.parse_args()
    if os.geteuid()!=0: raise RuntimeError('root required')
    try:
        result=action(a.action,a.execute_live)
    except Exception as error:
        # Raw exception/command output is deliberately never transported to the operator.
        print(json.dumps({'reason_code':reason_code(error)}))
        return 1
    print(json.dumps(result))
    return 0

if __name__=='__main__': raise SystemExit(main())
