"""Explicit research entry points. No production imports or order endpoints."""
import argparse
import json
import os
import time
from pathlib import Path
from .protocol import freeze, atomic, utc
from .store import Store

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('command',choices=['run','smoke','broker','status','export'])
    p.add_argument('--state',required=True);p.add_argument('--synthetic',action='store_true')
    p.add_argument('--inline-broker',action='store_true');p.add_argument('--pi',action='store_true')
    p.add_argument('--seconds',type=int);p.add_argument('--proposal-only',action='store_true')
    a=p.parse_args(argv)
    if a.pi and a.inline_broker:raise ValueError('Pi worker cannot perform network proposal calls')
    if a.command=='broker':
        from .mailbox import Mailbox
        from .designer import broker_once
        from .locking import WorkerLock
        box=Path(a.state)/'mailbox'
        with WorkerLock(box/'broker.lock'):
            mailbox=Mailbox(box)
            try:
                with mailbox.db:mailbox.db.execute("UPDATE proposals SET state='FALLBACK',validation=? WHERE state='INFLIGHT'",(json.dumps(dict(accepted=[],rejected=[dict(reason='UNCERTAIN_CALL_NOT_RETRIED')])),))
                broker_once(mailbox,forced_no_key=a.synthetic)
            finally:mailbox.close()
        return 0
    from .locking import WorkerLock
    lock=WorkerLock(Path(a.state)/('broker.lock' if a.command=='broker' else 'worker.lock')) if a.command in ('run','smoke','broker') else None
    if lock:lock.__enter__()
    s=Store(a.state)
    try:
        if a.command=='status':print(json.dumps(s.status(),indent=2));return 0
        if a.command=='export':
            from .reporting import export
            export(s);return 0
        manifest=freeze(a.state,a.synthetic)
        with s.db:s.db.execute("UPDATE attempts SET status='INTERRUPTED' WHERE status='RUNNING'")
        if s.meta('fingerprint') not in (None,manifest['fingerprint']):raise RuntimeError('State belongs to a different frozen experiment')
        s.set('fingerprint',manifest['fingerprint']);s.set('experiment_id',manifest['experiment_id'])
        if (s.root/'cycle.json').exists():s.set('prior_attempts',json.loads((s.root/'cycle.json').read_text()).get('prior_attempts',0))
        if s.meta('status')=='SEALED':s.status();return 0
        s.set('status','RUNNING')
        from .resources import Guard,PauseResearch
        guard=Guard(s,pi=a.pi,seconds=a.seconds)
        from .evaluator import Evaluator
        e=Evaluator(s,synthetic=a.synthetic,guard=guard)
        if a.command=='smoke':
            from .protocol import periods
            from .vendor.common import config
            result=e.evaluate(config(),periods(2024)[0],'spot')
            atomic(s.root/'smoke.json',dict(scope='inner_train',metrics=result['metrics'],audit=result['audit']))
            print(json.dumps(dict(smoke='PASS',attempts=s.counts(),audit=result['audit']['pass_audit'])));return 0
        from .controller import run_search,outer_estimate,AwaitBroker
        while True:
            try:
                run_search(s,e,a.synthetic,a.inline_broker)
                outer_estimate(s,e,a.synthetic)
                from .reporting import export
                export(s);print(json.dumps(s.status()));return 0
            except AwaitBroker:
                if a.proposal_only:return 0
                time.sleep(3);guard(force=True)
            except PauseResearch as exc:
                s.set('pause_reason',str(exc));s.status();return 0
    except Exception as exc:
        # Exception text may contain untrusted remote content: store only type and safe local reason.
        s.set('status','FAILED');s.set('failure',dict(type=type(exc).__name__,reason=str(exc)[:500],utc=utc()));s.status()
        raise
    finally:
        s.close()
        if lock:lock.__exit__()

if __name__=='__main__':raise SystemExit(main())
