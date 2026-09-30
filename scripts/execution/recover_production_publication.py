"""Resume only publication of an already verified production run; never execute."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.execution.authority_contract import atomic_write_json
from scripts.execution.migration_reconciliation import classify_execution
from scripts.execution.run_trendatlas_production import SingleRunLock


def write_preserving_access(path, payload):
    info=path.stat()
    atomic_write_json(path,payload)
    if hasattr(os,'chown'): os.chown(path,info.st_uid,info.st_gid)
    path.chmod(info.st_mode & 0o777)


def recover(root, run_id, payload, activation, publish):
    latest=root/'outputs/execution/production_runs/latest_production_run.json'
    manifest=json.loads(latest.read_text())
    if manifest.get('run_id')!=run_id:
        raise RuntimeError('recovery_run_identity_mismatch')
    if manifest.get('publication_recovery',{}).get('status')=='SUCCESS':
        return {'run_id':run_id,'already_recovered':True}
    resumable=(manifest.get('final_status')=='SUCCESS' and manifest.get('authority_status')=='RECOVERY_PENDING'
               and manifest.get('publication_recovery',{}).get('status')=='RUNNING')
    if (not (manifest.get('final_status')=='EXECUTION_COMPLETE_PUBLISH_FAILED' or resumable)
            or manifest.get('failure_stage')!='AUTHORITY_PUBLISH'
            or not classify_execution(manifest,payload,activation)['execution_verified']):
        raise RuntimeError('publication_recovery_requires_verified_execution')
    original=copy.deepcopy(manifest)
    per_run=latest.parent/run_id/'production_run_manifest.json'
    if json.loads(per_run.read_text()).get('run_id')!=run_id:
        raise RuntimeError('recovery_run_identity_mismatch')
    # As in the canonical orchestrator, finalize verified execution before the
    # publisher materializes it. Keep the original failure as immutable evidence.
    manifest.update(final_status='SUCCESS',authority_status='RECOVERY_PENDING')
    manifest['publication_recovery']={'status':'RUNNING','started_at':datetime.now(timezone.utc).isoformat(),
        'original_final_status':original['final_status'],'original_failure_reason':original.get('failure_reason'),
        'original_failure_stage':original.get('failure_stage'),'execution_repeated':False}
    try:
        for p in (per_run,latest): write_preserving_access(p,manifest)
        publish(True)
        publish(False)
    except BaseException:
        for p in (per_run,latest): write_preserving_access(p,original)
        raise
    manifest['authority_status']='PASSED'
    manifest['publication_recovery'].update(status='SUCCESS',finished_at=datetime.now(timezone.utc).isoformat())
    manifest['stages']['AUTHORITY_PUBLISH'].update(status='PASSED',error=None,finished_at=datetime.now(timezone.utc).isoformat())
    for p in (per_run,latest): write_preserving_access(p,manifest)
    return {'run_id':run_id,'publication_recovered':True,'execution_repeated':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);a=p.parse_args()
    from scripts.execution import migration_host_control as host
    with SingleRunLock(ROOT/'outputs/execution/production_runs/trendatlas_production.lock'):
        host.assert_inactive()
        payload,_=host.fresh_readback()
        activation=json.loads(host.ACTIVATION.read_text())
        user=host.property_value('mrv1-production.service','User')
        def publish(dry_run):
            command=['runuser','-u',user,'--',sys.executable,str(ROOT/'scripts/execution/run_pi_authoritative_producer.py'),
                     '--mode','publish-existing']+(['--dry-run'] if dry_run else [])
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
            # Keep raw diagnostics protected on-host, never send them to the CLI.
            path=host.STATE/('publication-recovery-dry.log' if dry_run else 'publication-recovery.log')
            path.write_text(result.stdout+result.stderr);path.chmod(0o600)
            if result.returncode: raise RuntimeError('publication_recovery_failed')
        print(json.dumps(recover(ROOT,a.run_id,payload,activation,publish)))


if __name__=='__main__': main()
